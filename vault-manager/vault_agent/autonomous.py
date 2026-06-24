"""Bounded autonomous maintenance run orchestration."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .execution import active_run_id
from .llm import ProposalProvider
from .model_blocks import model_block_summary
from .norms import norms_lock_path
from .organize_pass import run_organize_vault_pass
from .proposals import run_propose_cleanup_queue, run_propose_inbox_sort
from .readiness import build_readiness_report
from .retrieval import run_rebuild_retrieval
from .review import load_proposals, run_review_proposals
from .safety import write_text_safely
from .scanner import run_scan
from .validation import run_validate
from . import versioning


def run_autonomous(
    config: AgentConfig,
    *,
    max_notes: int,
    max_proposal_operations: int = 10,
    stage: str | None = None,
    proposal_provider: ProposalProvider | None = None,
    create_lock: bool = False,
    apply_safe: bool = False,
    report_format: str = "both",
) -> tuple[int, str]:
    """Run a bounded maintenance pass and write an audit report."""
    if max_notes <= 0:
        return 1, "vault-agent autonomous-run failed\nError: --max-notes must be positive"
    if report_format not in {"markdown", "json", "both"}:
        return 1, "vault-agent autonomous-run failed\nError: report format must be markdown, json, or both"

    dry_run = config.dry_run
    steps: list[dict[str, Any]] = []
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = active_run_id()
    before_readiness = build_readiness_report(config)
    before_change_sets = len(versioning.load_change_sets(config.vault_root))

    def record(name: str, code: int, output: str) -> None:
        status = "ok" if code == 0 else "failed"
        if name == "organize-vault-pass" and code != 0:
            if model_block_summary(config.vault_root)["count"] > 0:
                status = "review-required"
        steps.append(
            {
                "name": name,
                "exit_code": code,
                "status": status,
                "summary": _first_line(output),
                "output_tail": _tail(output),
            }
        )

    if dry_run:
        report = _build_report(
            config,
            started_at=started_at,
            run_id=run_id,
            before_readiness=before_readiness,
            after_readiness=before_readiness,
            steps=[
                {
                    "name": "dry-run",
                    "exit_code": 0,
                    "status": "ok",
                    "summary": "would run bounded autonomous maintenance",
                    "output_tail": [],
                }
            ],
            max_notes=max_notes,
            max_proposal_operations=max_proposal_operations,
            apply_safe=apply_safe,
            stage=stage,
            report_paths={},
            change_set=None,
        )
        return 0, _render_console(report, dry_run=True)

    lock_path = norms_lock_path(config.vault_root)
    if create_lock and not lock_path.exists():
        lock_config = replace(config, dry_run=False)
        code, output = _write_norms_lock(lock_config)
        record("norms-lock", code, output)
        if code != 0:
            return _finish(config, report_format, started_at, run_id, before_readiness, steps, max_notes, max_proposal_operations, apply_safe, stage, before_change_sets)
    elif not lock_path.exists():
        record(
            "norms-lock",
            1,
            f"missing norms lock at {lock_path}; pass --create-lock",
        )
        return _finish(config, report_format, started_at, run_id, before_readiness, steps, max_notes, max_proposal_operations, apply_safe, stage, before_change_sets)

    for name, action in (
        ("scan", lambda: run_scan(config)),
        ("validate-before", lambda: run_validate(config)),
        (
            "propose-cleanup-queue",
            lambda: run_propose_cleanup_queue(
                config,
                max_items=max_proposal_operations,
                remove_unknown=False,
                overwrite_proposal=True,
            ),
        ),
    ):
        code, output = action()
        if name == "propose-cleanup-queue" and "no cleanup queue changes found" in output:
            code = 0
        record(name, code, output)
        if code != 0:
            return _finish(config, report_format, started_at, run_id, before_readiness, steps, max_notes, max_proposal_operations, apply_safe, stage, before_change_sets)

    code, output = run_propose_inbox_sort(
        config,
        max_notes=max_notes,
        safe_only=apply_safe,
        overwrite_proposal=True,
    )
    record("propose-inbox-sort", code, output)
    if code != 0:
        return _finish(config, report_format, started_at, run_id, before_readiness, steps, max_notes, max_proposal_operations, apply_safe, stage, before_change_sets)

    if apply_safe:
        code, output = run_review_proposals(
            config,
            agent_review=True,
            approve_safe=True,
            max_operations=max_proposal_operations,
            include_schema=False,
        )
        record("review-proposals-approve-safe", code, output)
        if code == 0:
            code, output = run_review_proposals(config, apply_approved=True)
            record("review-proposals-apply-approved", code, output)
    else:
        code, output = run_review_proposals(config, agent_review=True)
        record("review-proposals-agent-review", code, output)

    code, output = run_organize_vault_pass(
        config,
        proposal_provider=proposal_provider,
        max_notes=max_notes,
        stage=stage,
        create_lock=create_lock,
    )
    record("organize-vault-pass", code, output)

    code, output = run_rebuild_retrieval(config)
    record("rebuild-retrieval", code, output)

    code, output = run_validate(config)
    record("validate-after", code, output)

    return _finish(config, report_format, started_at, run_id, before_readiness, steps, max_notes, max_proposal_operations, apply_safe, stage, before_change_sets)


def _finish(
    config: AgentConfig,
    report_format: str,
    started_at: str,
    run_id: str | None,
    before_readiness: dict[str, Any],
    steps: list[dict[str, Any]],
    max_notes: int,
    max_proposal_operations: int,
    apply_safe: bool,
    stage: str | None,
    before_change_sets: int,
) -> tuple[int, str]:
    after_readiness = build_readiness_report(config)
    change_sets = versioning.load_change_sets(config.vault_root)
    change_set = change_sets[-1] if len(change_sets) > before_change_sets else None
    report = _build_report(
        config,
        started_at=started_at,
        run_id=run_id,
        before_readiness=before_readiness,
        after_readiness=after_readiness,
        steps=steps,
        max_notes=max_notes,
        max_proposal_operations=max_proposal_operations,
        apply_safe=apply_safe,
        stage=stage,
        report_paths={},
        change_set=change_set,
    )
    paths = _write_report(config, report, report_format=report_format)
    report["report_paths"] = {key: path.relative_to(config.vault_root).as_posix() for key, path in paths.items()}
    if paths:
        _rewrite_report_paths(config, report, paths, report_format)
    if any(step["status"] == "failed" for step in steps):
        exit_code = 1
    elif any(step["status"] == "review-required" for step in steps):
        exit_code = 2
    else:
        exit_code = 0
    return exit_code, _render_console(report, dry_run=False)


def _build_report(
    config: AgentConfig,
    *,
    started_at: str,
    run_id: str | None,
    before_readiness: dict[str, Any],
    after_readiness: dict[str, Any],
    steps: list[dict[str, Any]],
    max_notes: int,
    max_proposal_operations: int,
    apply_safe: bool,
    stage: str | None,
    report_paths: dict[str, str],
    change_set: dict[str, Any] | None,
) -> dict[str, Any]:
    current_run_id = run_id or (change_set or {}).get("run_id")
    changed_files = (change_set or {}).get("changed_files")
    if changed_files is None:
        changed_files = [item.path for item in versioning.changed_files(config.vault_root)]
    return {
        "generated_by": "vault-agent",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "vault_root": config.vault_root.as_posix(),
        "mode": "bounded-safe",
        "max_notes": max_notes,
        "max_proposal_operations": max_proposal_operations,
        "apply_safe": apply_safe,
        "stage": stage or "",
        "llm_enabled_for_run": any(step["name"] == "organize-vault-pass" for step in steps),
        "version_run_id": current_run_id,
        "rollback": _rollback(config, current_run_id, change_set),
        "readiness_before": _readiness_summary(before_readiness),
        "readiness_after": _readiness_summary(after_readiness),
        "steps": steps,
        "proposals": _proposal_summary(config),
        "model_blocks": model_block_summary(config.vault_root),
        "changed_files": changed_files,
        "diff_summary": (change_set or {}).get("diff_summary", ""),
        "report_paths": report_paths,
    }


def _write_norms_lock(config: AgentConfig) -> tuple[int, str]:
    from .norms import run_norms_lock

    return run_norms_lock(config, write=True)


def _write_report(
    config: AgentConfig, report: dict[str, Any], *, report_format: str
) -> dict[str, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    paths: dict[str, Path] = {}
    directory = config.vault_root / config.paths.agent_dir / "reports"
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    if report_format in {"json", "both"}:
        path = directory / f"autonomous-run-{timestamp}.json"
        write_text_safely(path, json.dumps(report, indent=2, sort_keys=True) + "\n", backup_root=backup_root)
        paths["json"] = path
    if report_format in {"markdown", "both"}:
        path = directory / f"autonomous-run-{timestamp}.md"
        write_text_safely(path, _report_markdown(report), backup_root=backup_root)
        paths["markdown"] = path
    return paths


def _rewrite_report_paths(
    config: AgentConfig,
    report: dict[str, Any],
    paths: dict[str, Path],
    report_format: str,
) -> None:
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    if report_format in {"json", "both"} and "json" in paths:
        write_text_safely(paths["json"], json.dumps(report, indent=2, sort_keys=True) + "\n", backup_root=backup_root)
    if report_format in {"markdown", "both"} and "markdown" in paths:
        write_text_safely(paths["markdown"], _report_markdown(report), backup_root=backup_root)


def _proposal_summary(config: AgentConfig) -> dict[str, Any]:
    directory = config.vault_root / config.paths.review_dir / "proposals"
    proposals = load_proposals(directory)
    by_status: dict[str, int] = {}
    schema_deferred = 0
    for proposal in proposals:
        by_status[proposal.status] = by_status.get(proposal.status, 0) + 1
        if proposal.data.get("kind") == "schema-change" and proposal.status == "pending":
            schema_deferred += 1
    return {
        "count": len(proposals),
        "by_status": by_status,
        "schema_changes_deferred": schema_deferred,
    }


def _rollback(config: AgentConfig, run_id: str | None, change_set: dict[str, Any] | None) -> dict[str, Any]:
    if not run_id:
        return {}
    return {
        "run_id": run_id,
        "diff_path": (config.paths.agent_dir / "versioning" / "runs" / run_id / "diff.patch").as_posix(),
        "metadata_path": (config.paths.agent_dir / "versioning" / "runs" / run_id / "change-set.json").as_posix(),
        "undo_command": f"vault-agent --vault-root {config.vault_root} version undo-run {run_id}",
        "restore_one_path": f"vault-agent --vault-root {config.vault_root} version restore {run_id} --path <path>",
        "pre_commit": (change_set or {}).get("pre_commit"),
        "post_commit": (change_set or {}).get("post_commit"),
    }


def _readiness_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "readiness": report.get("readiness"),
        "validation_issues": report.get("validation", {}).get("issues"),
        "validation_errors": report.get("validation", {}).get("errors"),
        "candidate_stages": report.get("candidate_stages", {}).get("count"),
        "cleanup_queue": report.get("cleanup_queue", {}).get("total"),
        "blocked": report.get("processing_state", {}).get("blocked"),
        "stale": report.get("processing_state", {}).get("stale"),
    }


def _render_console(report: dict[str, Any], *, dry_run: bool) -> str:
    lines = ["vault-agent autonomous-run dry run" if dry_run else "vault-agent autonomous-run complete"]
    lines.extend(
        [
            f"Vault root: {report['vault_root']}",
            f"Mode: {report['mode']}",
            f"Max notes: {report['max_notes']}",
            f"Apply safe proposals: {report['apply_safe']}",
            f"Version run id: {report.get('version_run_id') or '(pending)'}",
            f"Readiness before: {report['readiness_before']['readiness']}",
            f"Readiness after: {report['readiness_after']['readiness']}",
            "Steps:",
        ]
    )
    for step in report["steps"]:
        lines.append(f"- {step['name']}: {step['status']}")
    rollback = report.get("rollback") or {}
    if rollback.get("undo_command"):
        lines.append(f"Undo: `{rollback['undo_command']}`")
    model_blocks = report.get("model_blocks") or {}
    if model_blocks.get("count"):
        lines.append(f"Blocked model proposals: {model_blocks['count']}")
        lines.append(f"Review model blocks: `{model_blocks.get('markdown_path', '')}`")
    report_paths = report.get("report_paths") or {}
    if report_paths:
        for kind, path in report_paths.items():
            lines.append(f"Report {kind}: {path}")
    if dry_run:
        lines.append("No files were changed.")
    return "\n".join(lines)


def _report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Autonomous Run Report",
        "",
        f"- Vault root: `{report['vault_root']}`",
        f"- Mode: `{report['mode']}`",
        f"- Version run id: `{report.get('version_run_id') or ''}`",
        f"- Max notes: {report['max_notes']}",
        f"- Max proposal operations: {report['max_proposal_operations']}",
        f"- Apply safe proposals: {report['apply_safe']}",
        f"- Stage: `{report['stage'] or 'next-needed'}`",
        "",
        "## Rollback",
        "",
    ]
    rollback = report.get("rollback") or {}
    if rollback:
        lines.extend(
            [
                f"- Diff: `{rollback.get('diff_path', '')}`",
                f"- Undo run: `{rollback.get('undo_command', '')}`",
                f"- Restore one path: `{rollback.get('restore_one_path', '')}`",
            ]
        )
    else:
        lines.append("- No versioned run id was available.")
    lines.extend(
        [
            "",
            "## Readiness",
            "",
            f"- Before: `{report['readiness_before']['readiness']}`; validation issues {report['readiness_before']['validation_issues']}; candidate stages {report['readiness_before']['candidate_stages']}",
            f"- After: `{report['readiness_after']['readiness']}`; validation issues {report['readiness_after']['validation_issues']}; candidate stages {report['readiness_after']['candidate_stages']}",
            "",
            "## Steps",
            "",
        ]
    )
    for step in report["steps"]:
        lines.append(f"- `{step['name']}`: {step['status']} ({step['summary']})")
    proposals = report.get("proposals", {})
    lines.extend(
        [
            "",
            "## Proposals",
            "",
            f"- Count: {proposals.get('count', 0)}",
            f"- By status: `{json.dumps(proposals.get('by_status', {}), sort_keys=True)}`",
            f"- Schema changes deferred: {proposals.get('schema_changes_deferred', 0)}",
            "",
            "## Model Blocks",
            "",
        ]
    )
    model_blocks = report.get("model_blocks") or {}
    if model_blocks.get("count"):
        lines.extend(
            [
                f"- Count: {model_blocks.get('count', 0)}",
                f"- Review JSON: `{model_blocks.get('json_path', '')}`",
                f"- Review Markdown: `{model_blocks.get('markdown_path', '')}`",
                f"- Top reasons: `{json.dumps(model_blocks.get('top_reasons', {}), sort_keys=True)}`",
            ]
        )
    else:
        lines.append("- Count: 0")
    lines.extend(
        [
            "",
            "## Changed Files",
            "",
        ]
    )
    changed = report.get("changed_files") or []
    if not changed:
        lines.append("No changed files were available when this report was written.")
    for path in changed:
        lines.append(f"- `{path}`")
    return "\n".join(lines) + "\n"


def _first_line(output: str) -> str:
    for line in output.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _tail(output: str, limit: int = 6) -> list[str]:
    lines = [line for line in output.splitlines() if line.strip()]
    return lines[-limit:]
