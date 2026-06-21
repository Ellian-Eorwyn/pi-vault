"""Lock-aware full vault organization pass and reporting."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .frontmatter import parse_note
from .llm import ProposalProvider
from .model_blocks import model_block_summary
from .logging_utils import append_log
from .norms import build_norms_lock, load_norms_lock, norms_lock_path
from .paths import paths_for
from .processing_state import mark_stage
from .processor import next_needed_stage, process_note
from .safety import write_text_safely
from .scanner import scan_vault
from .validation import validate_entries


def run_organize_vault_pass(
    config: AgentConfig,
    *,
    proposal_provider: ProposalProvider | None = None,
    max_notes: int | None = None,
    max_runtime_minutes: int | None = None,
    folder: str | None = None,
    note: str | None = None,
    stage: str | None = None,
    create_lock: bool = False,
) -> tuple[int, str]:
    lock = load_norms_lock(config.vault_root)
    lock_created = False
    if lock is None:
        if not create_lock:
            return (
                1,
                "vault-agent organize-vault-pass failed\n"
                f"Error: missing norms lock at {norms_lock_path(config.vault_root)}. "
                "Run `vault-agent norms-lock --write` or pass `--create-lock`.",
            )
        lock = build_norms_lock(config)
        lock_created = True
        if not config.dry_run:
            write_text_safely(
                norms_lock_path(config.vault_root),
                json.dumps(lock, indent=2, sort_keys=True) + "\n",
                backup_root=config.vault_root / config.paths.agent_dir / "backups",
            )
    lock_hash = str(lock["lock_hash"])
    before = scan_vault(config.vault_root)
    before_issues = validate_entries(before.entries, config)
    candidates, selection_errors = _candidate_entries(
        config.vault_root,
        before.entries,
        folder=folder,
        note=note,
        stage=stage,
        lock_hash=lock_hash,
    )
    if selection_errors:
        return (
            1,
            "vault-agent organize-vault-pass failed\n"
            + "\n".join(f"Error: {error}" for error in selection_errors),
        )

    limit = max_notes if max_notes is not None else config.max_notes
    runtime_seconds = (max_runtime_minutes if max_runtime_minutes is not None else config.max_runtime_minutes) * 60
    selected = candidates[:limit]
    if config.dry_run:
        lines = [
            "vault-agent organize-vault-pass dry run",
            f"Lock hash: {lock_hash}",
            f"Would create lock: {lock_created}",
            f"Candidate note stages: {len(candidates)}",
            f"Would process: {len(selected)}",
            f"LLM prompts: {'serialized one note stage at a time' if proposal_provider else 'none'}",
        ]
        for position, item in enumerate(selected[:10], start=1):
            lines.append(f"{position}. `{item['path']}` ({item['stage']})")
        lines.append("No files were changed.")
        return 0, "\n".join(lines)

    processed: list[dict[str, Any]] = []
    changed = 0
    blocked = 0
    started = time.monotonic()
    for position, item in enumerate(selected, start=1):
        if time.monotonic() - started >= runtime_seconds:
            break
        note_path = config.vault_root / item["path"]
        result = process_note(
            config.vault_root,
            note_path,
            proposal_provider=proposal_provider,
            confidence_threshold=config.llm_confidence_threshold,
            preserve_unknown_properties=config.preserve_unknown_properties,
            review_on_warnings=config.review_on_warnings,
            warning_confidence_margin=config.warning_confidence_margin,
            stage=item["stage"],
            norms_lock_hash=lock_hash,
        )
        if result.errors:
            blocked += 1
            mark_stage(
                config.vault_root,
                note_path,
                stage=item["stage"],
                status="blocked",
                norms_lock_hash=lock_hash,
                errors=result.errors,
            )
        if result.changed:
            changed += 1
        processed.append(
            {
                "queue_position": position,
                "path": item["path"],
                "stage": item["stage"],
                "mode": result.mode,
                "changed": result.changed,
                "errors": result.errors,
            }
        )

    after = scan_vault(config.vault_root)
    after_issues = validate_entries(after.entries, config)
    remaining, _errors = _candidate_entries(
        config.vault_root,
        after.entries,
        folder=folder,
        note=note,
        stage=stage,
        lock_hash=lock_hash,
    )
    report = {
        "generated_by": "vault-agent",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lock_hash": lock_hash,
        "lock_created": lock_created,
        "scope": {"folder": folder or "", "note": note or "", "stage": stage or ""},
        "notes_scanned": len(before.entries),
        "validation_issues_before": len(before_issues),
        "validation_issues_after": len(after_issues),
        "candidate_stages_before": len(candidates),
        "remaining_candidate_stages": len(remaining),
        "processed_stages": len(processed),
        "changed_notes": changed,
        "blocked_stages": blocked,
        "model_blocks": model_block_summary(config.vault_root),
        "llm_prompts_serialized": bool(proposal_provider),
        "processed": processed,
    }
    json_path, md_path = _write_report(config, report)
    append_log(
        config.vault_root,
        "organize-vault-pass",
        [
            f"processed {len(processed)} stage(s)",
            f"changed {changed}",
            f"blocked {blocked}",
            f"lock {lock_hash}",
        ],
    )
    return (
        1 if blocked else 0,
        "vault-agent organize-vault-pass complete\n"
        f"Lock hash: {lock_hash}\n"
        f"Processed stages: {len(processed)}\n"
        f"Changed notes: {changed}\n"
        f"Blocked stages: {blocked}\n"
        f"Blocked model proposals: {report['model_blocks']['count']}\n"
        f"LLM prompts: {'serialized one note stage at a time' if proposal_provider else 'none'}\n"
        f"Remaining candidate stages: {len(remaining)}\n"
        f"Report: {md_path}\n"
        f"Report JSON: {json_path}",
    )


def latest_report(vault_root: Path) -> Path | None:
    report_dir = vault_root / paths_for(vault_root).agent_dir / "reports"
    if not report_dir.exists():
        return None
    reports = sorted(report_dir.glob("organization-run-*.md"))
    return reports[-1] if reports else None


def _candidate_entries(
    vault_root: Path,
    entries: list[dict[str, Any]],
    *,
    folder: str | None,
    note: str | None,
    stage: str | None,
    lock_hash: str,
) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    folder_prefix = _normalized_scope(folder)
    note_path = _normalized_scope(note)
    candidates: list[dict[str, str]] = []
    system_dir = paths_for(vault_root).system_dir
    for entry in entries:
        relative = Path(entry["path"])
        if entry.get("system_template") or relative.is_relative_to(system_dir):
            continue
        if folder_prefix and not relative.as_posix().startswith(folder_prefix.rstrip("/") + "/"):
            continue
        if note_path and relative.as_posix() != note_path:
            continue
        if entry.get("frontmatter_error"):
            continue
        path = vault_root / relative
        parsed = parse_note(path.read_text(encoding="utf-8"))
        if parsed.error:
            continue
        next_stage = next_needed_stage(
            vault_root,
            path,
            entry,
            stage=stage,
            norms_lock_hash=lock_hash,
        )
        if next_stage:
            candidates.append({"path": relative.as_posix(), "stage": next_stage})
    if note and not any(candidate["path"] == note_path for candidate in candidates):
        target = vault_root / (note_path or note)
        if not target.exists():
            errors.append(f"target note does not exist: {note}")
    return candidates, errors


def _normalized_scope(value: str | None) -> str | None:
    if not value:
        return None
    target = Path(value)
    if target.is_absolute():
        return target.as_posix().lstrip("/")
    return target.as_posix().strip("/")


def _write_report(config: AgentConfig, report: dict[str, Any]) -> tuple[Path, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_dir = config.paths.agent_dir / "reports"
    json_path = config.vault_root / report_dir / f"organization-run-{timestamp}.json"
    md_path = config.vault_root / report_dir / f"organization-run-{timestamp}.md"
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    write_text_safely(json_path, json.dumps(report, indent=2, sort_keys=True) + "\n", backup_root=backup_root)
    write_text_safely(md_path, _report_markdown(report), backup_root=backup_root)
    return json_path, md_path


def _report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Organization Run Report",
        "",
        f"- Lock hash: `{report['lock_hash']}`",
        f"- Notes scanned: {report['notes_scanned']}",
        f"- Validation issues before: {report['validation_issues_before']}",
        f"- Validation issues after: {report['validation_issues_after']}",
        f"- Candidate stages before: {report['candidate_stages_before']}",
        f"- Processed stages: {report['processed_stages']}",
        f"- Changed notes: {report['changed_notes']}",
        f"- Blocked stages: {report['blocked_stages']}",
        f"- Blocked model proposals: {report.get('model_blocks', {}).get('count', 0)}",
        f"- LLM prompts serialized: {report.get('llm_prompts_serialized', False)}",
        f"- Remaining candidate stages: {report['remaining_candidate_stages']}",
    ]
    model_blocks = report.get("model_blocks") or {}
    if model_blocks.get("count"):
        lines.extend(
            [
                "",
                "## Model Blocks",
                "",
                f"- Model block review JSON: `{model_blocks.get('json_path', '')}`",
                f"- Model block review Markdown: `{model_blocks.get('markdown_path', '')}`",
                f"- Top block reasons: `{json.dumps(model_blocks.get('top_reasons', {}), sort_keys=True)}`",
            ]
        )
    lines.extend(["", "## Processed", ""])
    processed = report.get("processed", [])
    if not processed:
        lines.append("No note stages were processed.")
    for item in processed:
        status = "blocked" if item.get("errors") else "complete"
        lines.append(
            f"- {item.get('queue_position', '?')}. `{item['path']}` ({item['stage']}): {status}, mode `{item['mode']}`, changed `{item['changed']}`"
        )
        for error in item.get("errors", []):
            lines.append(f"  - Error: {error}")
    return "\n".join(lines) + "\n"
