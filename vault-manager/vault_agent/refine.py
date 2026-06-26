"""LLM-led note-body refinement: deterministic meaning guard and folder generator.

The model may reformat a note's body for structure and Obsidian Markdown, but it
must never change the wording or meaning. `meaning_preserved` is a deterministic
safeguard that compares the prose word multiset before and after a rewrite and
rejects any proposal that drops or substitutes the author's words. It is a
safeguard, not a proof: every refinement stays proposal-gated, diffable, and
git-backed, so a human reviews the diff before anything is applied.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .frontmatter import parse_note
from .llm import ProposalProvider, validate_stage_proposal
from .logging_utils import append_log
from .norms import current_lock_hash, norms_lock_path
from .paths import paths_for
from .safety import atomic_write_text, write_text_safely
from .scanner import scan_vault


# Line-leading ordered-list markers ("1. ", "2) ") are stripped before tokenizing
# so converting an ordered list to bullets (or renumbering) is not seen as dropping
# the digit "words". Every other Markdown structural token is non-word and is
# ignored by the word pattern already.
_ORDERED_MARKER = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
_WORD = re.compile(r"[0-9A-Za-zÀ-ɏ']+")


def content_words(text: str) -> Counter[str]:
    """Multiset of lowercase prose words, ignoring Markdown structural tokens."""
    normalized = _ORDERED_MARKER.sub("", text)
    return Counter(match.group(0).lower() for match in _WORD.finditer(normalized))


def meaning_preserved(
    old_body: str,
    new_body: str,
    *,
    max_added: int = 12,
    allow_dropped: int = 0,
) -> tuple[bool, dict[str, Any]]:
    """Return (ok, report) for a body rewrite.

    A rewrite is acceptable only when it drops no more than ``allow_dropped`` of the
    author's words and adds no more than ``max_added`` new words (the budget for
    structural heading labels). The report lists the offending words so a human sees
    exactly why a refinement was blocked.
    """
    old_words = content_words(old_body)
    new_words = content_words(new_body)
    dropped = old_words - new_words
    added = new_words - old_words
    dropped_count = sum(dropped.values())
    added_count = sum(added.values())
    ok = dropped_count <= allow_dropped and added_count <= max_added
    report = {
        "ok": ok,
        "dropped_count": dropped_count,
        "added_count": added_count,
        "allow_dropped": allow_dropped,
        "max_added": max_added,
        "dropped": dict(sorted(dropped.items())),
        "added": dict(sorted(added.items())),
    }
    return ok, report


def run_propose_folder_refinement(
    config: AgentConfig,
    *,
    folder: str | None = None,
    note: str | None = None,
    max_notes: int | None = None,
    max_runtime_minutes: int | None = None,
    proposal_provider: ProposalProvider | None = None,
) -> tuple[int, str]:
    """Generate `note-refinement` proposals that reformat note bodies in a folder.

    The model only ever reformats; the deterministic guard and the review gate keep
    wording and meaning intact. Notes whose rewrite fails the guard are reported and
    skipped, never silently applied.
    """
    lock_hash = current_lock_hash(config.vault_root)
    if not lock_hash:
        return (
            1,
            "vault-agent propose-folder-refinement failed\n"
            f"Error: missing norms lock at {norms_lock_path(config.vault_root)}. "
            "Run `vault-agent norms-lock --write` first.",
        )
    if proposal_provider is None:
        return (
            1,
            "vault-agent propose-folder-refinement failed\n"
            "Error: refinement needs the configured LLM backend; enable `llm` in the "
            "vault-agent config.",
        )

    candidates, selection_errors = _candidate_notes(config, folder=folder, note=note)
    if selection_errors:
        return (
            1,
            "vault-agent propose-folder-refinement failed\n"
            + "\n".join(f"Error: {error}" for error in selection_errors),
        )

    limit = max_notes if max_notes is not None else config.max_notes
    runtime_seconds = (
        max_runtime_minutes if max_runtime_minutes is not None else config.max_runtime_minutes
    ) * 60
    selected = candidates[:limit]

    proposal_dir = config.vault_root / config.paths.review_dir / "proposals"
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    results: list[dict[str, Any]] = []
    proposed = 0
    blocked = 0
    unchanged = 0
    started = time.monotonic()
    for relative in selected:
        if time.monotonic() - started >= runtime_seconds:
            break
        note_path = config.vault_root / relative
        text = note_path.read_text(encoding="utf-8")
        parsed = parse_note(text)
        if parsed.error:
            results.append({"path": relative, "status": "skipped", "reason": parsed.error})
            continue
        try:
            raw = proposal_provider.propose_stage(
                note_path=note_path, note_text=text, stage="refine-body"
            )
        except ValueError as exc:
            blocked += 1
            results.append({"path": relative, "status": "error", "reason": str(exc)})
            continue
        validation = validate_stage_proposal("refine-body", raw)
        if not validation.valid:
            blocked += 1
            results.append(
                {"path": relative, "status": "blocked", "reason": "; ".join(validation.errors)}
            )
            continue
        new_body = validation.proposal["body"]
        ok, guard = meaning_preserved(
            parsed.body,
            new_body,
            max_added=config.refine_max_added_words,
            allow_dropped=config.refine_allow_dropped_words,
        )
        if not ok:
            blocked += 1
            results.append(
                {
                    "path": relative,
                    "status": "blocked",
                    "reason": "word-preservation guard failed",
                    "guard": guard,
                }
            )
            continue
        if new_body.strip() == parsed.body.strip():
            unchanged += 1
            results.append({"path": relative, "status": "unchanged"})
            continue
        proposal = _build_refinement_proposal(relative, new_body, validation.proposal)
        results.append(
            {
                "path": relative,
                "status": "proposed",
                "proposal_id": proposal["id"],
                "confidence": validation.proposal.get("confidence"),
                "warnings": validation.proposal.get("warnings", []),
            }
        )
        proposed += 1
        if not config.dry_run:
            proposal_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(
                proposal_dir / f"{proposal['id']}.json",
                json.dumps(proposal, indent=2, sort_keys=True) + "\n",
            )

    report = {
        "generated_by": "vault-agent",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lock_hash": lock_hash,
        "scope": {"folder": folder or "", "note": note or ""},
        "candidates": len(candidates),
        "examined": len(results),
        "proposed": proposed,
        "blocked": blocked,
        "unchanged": unchanged,
        "dry_run": config.dry_run,
        "results": results,
    }
    if not config.dry_run:
        _write_report(config, report, backup_root)
        append_log(
            config.vault_root,
            "propose-folder-refinement",
            [f"proposed {proposed}", f"blocked {blocked}", f"unchanged {unchanged}", f"lock {lock_hash}"],
        )

    lines = [
        "vault-agent propose-folder-refinement "
        + ("dry run" if config.dry_run else "complete"),
        f"Lock hash: {lock_hash}",
        f"Candidate notes: {len(candidates)}",
        f"Examined: {len(results)}",
        f"Proposed refinements: {proposed}",
        f"Blocked (guard or model): {blocked}",
        f"Unchanged: {unchanged}",
    ]
    for item in results:
        if item["status"] in {"proposed", "blocked", "error"}:
            detail = item.get("proposal_id") or item.get("reason", "")
            lines.append(f"- `{item['path']}` ({item['status']}): {detail}")
    if config.dry_run:
        lines.append("No files were changed.")
    else:
        lines.append("Run `vault-agent review-proposals --dry-run` to inspect proposals.")
    return (1 if blocked else 0), "\n".join(lines)


def _build_refinement_proposal(
    relative: str, new_body: str, stage_proposal: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": f"refine-{_safe_id(relative)}",
        "title": f"Refine structure of `{relative}`",
        "kind": "note-refinement",
        "status": "pending",
        "automation_safe": False,
        "summary": "Reformat the note body for structure and skimmability without changing wording.",
        "confidence": stage_proposal.get("confidence"),
        "warnings": stage_proposal.get("warnings", []),
        "operations": [
            {"op": "restructure_body", "path": relative, "body": new_body},
        ],
    }


def _candidate_notes(
    config: AgentConfig, *, folder: str | None, note: str | None
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    folder_prefix = _normalized_scope(folder)
    note_path = _normalized_scope(note)
    system_dir = paths_for(config.vault_root).system_dir
    result = scan_vault(config.vault_root)
    candidates: list[str] = []
    for entry in result.entries:
        relative = Path(entry["path"])
        if entry.get("system_template") or relative.is_relative_to(system_dir):
            continue
        if entry.get("frontmatter_error"):
            continue
        posix = relative.as_posix()
        if folder_prefix and not posix.startswith(folder_prefix.rstrip("/") + "/"):
            continue
        if note_path and posix != note_path:
            continue
        candidates.append(posix)
    if note and not candidates:
        target = config.vault_root / (note_path or note)
        if not target.exists():
            errors.append(f"target note does not exist: {note}")
        else:
            errors.append(f"target note is not eligible for refinement: {note}")
    if folder and not candidates and not errors:
        errors.append(f"no eligible notes found under folder: {folder}")
    return candidates, errors


def _normalized_scope(value: str | None) -> str | None:
    if not value:
        return None
    target = Path(value)
    if target.is_absolute():
        return target.as_posix().lstrip("/")
    return target.as_posix().strip("/")


def _write_report(config: AgentConfig, report: dict[str, Any], backup_root: Path) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_dir = config.vault_root / config.paths.agent_dir / "reports"
    json_path = report_dir / f"refinement-run-{timestamp}.json"
    md_path = report_dir / f"refinement-run-{timestamp}.md"
    write_text_safely(json_path, json.dumps(report, indent=2, sort_keys=True) + "\n", backup_root=backup_root)
    write_text_safely(md_path, _report_markdown(report), backup_root=backup_root)


def _report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Note Refinement Run Report",
        "",
        f"- Lock hash: `{report['lock_hash']}`",
        f"- Scope folder: `{report['scope']['folder']}`",
        f"- Candidate notes: {report['candidates']}",
        f"- Proposed refinements: {report['proposed']}",
        f"- Blocked: {report['blocked']}",
        f"- Unchanged: {report['unchanged']}",
        "",
        "## Notes",
        "",
    ]
    for item in report["results"]:
        lines.append(f"- `{item['path']}`: {item['status']}")
        if item.get("reason"):
            lines.append(f"  - {item['reason']}")
        guard = item.get("guard")
        if guard:
            if guard.get("dropped"):
                lines.append(f"  - Dropped words: `{json.dumps(guard['dropped'], sort_keys=True)}`")
            if guard.get("added"):
                lines.append(f"  - Added words: `{json.dumps(guard['added'], sort_keys=True)}`")
    return "\n".join(lines) + "\n"


def _safe_id(value: str) -> str:
    safe = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in safe.split("-") if part)
