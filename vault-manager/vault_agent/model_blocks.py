"""Review artifacts for model proposals blocked by safety gates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .llm import ProposalProvider
from .paths import REVIEW_DIR, paths_for
from .safety import atomic_write_text, write_text_safely


MODEL_BLOCKS_JSON = REVIEW_DIR / "model-blocked-proposals.json"
MODEL_BLOCKS_MD = REVIEW_DIR / "model-blocked-proposals.md"
PROPOSAL_DIR = REVIEW_DIR / "proposals"


def load_model_blocks(vault_root: Path) -> dict[str, Any]:
    path = vault_root / paths_for(vault_root).review_dir / "model-blocked-proposals.json"
    if not path.exists():
        return _empty_blocks()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_blocks()
    if not isinstance(loaded, dict):
        return _empty_blocks()
    loaded.setdefault("generated_by", "vault-agent")
    loaded.setdefault("blocked", [])
    if not isinstance(loaded["blocked"], list):
        loaded["blocked"] = []
    return loaded


def record_model_block(
    vault_root: Path,
    note_path: Path,
    *,
    stage: str,
    proposal: dict[str, Any],
    reason: str,
    suggested_next_action: str,
    proposal_provider: ProposalProvider | None = None,
) -> dict[str, Any]:
    blocks = load_model_blocks(vault_root)
    relative = note_path.relative_to(vault_root).as_posix()
    entry = {
        "id": _block_id(relative, stage),
        "note_path": relative,
        "stage": stage,
        "prompt_stage": stage,
        "proposed_values": _proposed_values(stage, proposal),
        "proposal": proposal,
        "confidence": proposal.get("confidence"),
        "warnings": proposal.get("warnings", []),
        "provider": _provider_details(proposal_provider),
        "reason_blocked": reason,
        "suggested_next_action": suggested_next_action,
        "status": "pending",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    existing = [
        item
        for item in blocks["blocked"]
        if not (
            isinstance(item, dict)
            and item.get("note_path") == relative
            and item.get("stage") == stage
        )
    ]
    existing.append(entry)
    blocks["blocked"] = sorted(existing, key=lambda item: (item.get("note_path", ""), item.get("stage", "")))
    blocks["generated_at"] = datetime.now(timezone.utc).isoformat()
    _write_blocks(vault_root, blocks)
    return entry


def model_block_summary(vault_root: Path) -> dict[str, Any]:
    blocks = load_model_blocks(vault_root)
    pending = [
        item
        for item in blocks.get("blocked", [])
        if isinstance(item, dict) and item.get("status", "pending") == "pending"
    ]
    reasons: dict[str, int] = {}
    for item in pending:
        reason = str(item.get("reason_blocked") or "unknown")
        reasons[reason] = reasons.get(reason, 0) + 1
    review_dir = paths_for(vault_root).review_dir
    return {
        "count": len(pending),
        "json_path": (review_dir / "model-blocked-proposals.json").as_posix(),
        "markdown_path": (review_dir / "model-blocked-proposals.md").as_posix(),
        "top_reasons": reasons,
    }


def run_review_model_blocks(
    config: AgentConfig,
    *,
    note: str | None = None,
    stage: str | None = None,
    approve_safe: bool = False,
) -> tuple[int, str]:
    blocks = load_model_blocks(config.vault_root)
    selected = _select_blocks(blocks, note=note, stage=stage)
    safe_selected, unsafe_selected = _partition_safe_blocks(selected, config.llm_confidence_threshold)
    if config.dry_run:
        lines = [
            "vault-agent review-model-blocks dry run",
            f"Selected blocked proposals: {len(selected)}",
            f"Would create review proposals: {len(safe_selected) if approve_safe else 0}",
            f"Would skip unsafe proposals: {len(unsafe_selected) if approve_safe else 0}",
            "No files were changed.",
            "",
            _render_markdown(selected),
        ]
        return 0, "\n".join(lines).rstrip()

    created = 0
    errors: list[str] = []
    skipped: list[str] = []
    if approve_safe:
        proposal_dir = config.vault_root / config.paths.review_dir / "proposals"
        proposal_dir.mkdir(parents=True, exist_ok=True)
        for item in safe_selected:
            proposal, item_errors = _proposal_for_block(item)
            if item_errors:
                errors.extend(f"{item.get('id', 'model-block')}: {error}" for error in item_errors)
                continue
            path = proposal_dir / f"{proposal['id']}.json"
            atomic_write_text(path, json.dumps(proposal, indent=2, sort_keys=True) + "\n")
            item["status"] = "converted"
            item["converted_proposal"] = (
                config.paths.review_dir / "proposals" / path.name
            ).as_posix()
            item["converted_at"] = datetime.now(timezone.utc).isoformat()
            created += 1
        for item in unsafe_selected:
            skipped.append(
                f"{item.get('id', 'model-block')}: skipped because confidence is below the configured threshold"
            )
        blocks["generated_at"] = datetime.now(timezone.utc).isoformat()

    _write_blocks(config.vault_root, blocks)
    lines = [
        "vault-agent review-model-blocks complete",
        f"Selected blocked proposals: {len(selected)}",
        f"Created review proposals: {created}",
        f"Skipped unsafe proposals: {len(unsafe_selected) if approve_safe else 0}",
        f"Review JSON: {(config.paths.review_dir / 'model-blocked-proposals.json').as_posix()}",
        f"Review Markdown: {(config.paths.review_dir / 'model-blocked-proposals.md').as_posix()}",
    ]
    lines.extend(f"Skipped: {item}" for item in skipped)
    lines.extend(f"Error: {error}" for error in errors)
    return (1 if errors else 0), "\n".join(lines)


def _empty_blocks() -> dict[str, Any]:
    return {
        "generated_by": "vault-agent",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "blocked": [],
    }


def _write_blocks(vault_root: Path, blocks: dict[str, Any]) -> None:
    vault_paths = paths_for(vault_root)
    backup_root = vault_root / vault_paths.agent_dir / "backups"
    write_text_safely(
        vault_root / vault_paths.review_dir / "model-blocked-proposals.json",
        json.dumps(blocks, indent=2, sort_keys=True) + "\n",
        backup_root=backup_root,
    )
    write_text_safely(
        vault_root / vault_paths.review_dir / "model-blocked-proposals.md",
        _render_markdown(blocks["blocked"]),
        backup_root=backup_root,
    )


def _render_markdown(blocks: list[dict[str, Any]]) -> str:
    lines = ["# Model-Blocked Proposals", ""]
    pending = [item for item in blocks if item.get("status", "pending") == "pending"]
    if not pending:
        lines.append("No pending model-blocked proposals.")
        return "\n".join(lines) + "\n"
    for item in pending:
        lines.extend(
            [
                f"## `{item.get('note_path', '')}`",
                "",
                f"- ID: `{item.get('id', '')}`",
                f"- Stage: `{item.get('stage', '')}`",
                f"- Confidence: `{item.get('confidence', '')}`",
                f"- Reason blocked: {item.get('reason_blocked', '')}",
                f"- Suggested next action: {item.get('suggested_next_action', '')}",
            ]
        )
        warnings = item.get("warnings") or []
        if warnings:
            lines.append("- Warnings:")
            lines.extend(f"  - {warning}" for warning in warnings)
        proposed = item.get("proposed_values") or {}
        if proposed:
            lines.append("- Proposed values:")
            for key, value in proposed.items():
                lines.append(f"  - `{key}`: `{value}`")
        provider = item.get("provider") or {}
        if provider:
            lines.append(f"- Provider: `{provider.get('provider', '')}` / `{provider.get('model', '')}`")
        lines.append("")
    return "\n".join(lines)


def _select_blocks(
    blocks: dict[str, Any], *, note: str | None = None, stage: str | None = None
) -> list[dict[str, Any]]:
    note_filter = note.strip("/") if note else None
    selected: list[dict[str, Any]] = []
    for item in blocks.get("blocked", []):
        if not isinstance(item, dict):
            continue
        if item.get("status", "pending") != "pending":
            continue
        if note_filter and item.get("note_path") != note_filter:
            continue
        if stage and item.get("stage") != stage:
            continue
        selected.append(item)
    return selected


def _partition_safe_blocks(
    blocks: list[dict[str, Any]], confidence_threshold: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    safe: list[dict[str, Any]] = []
    unsafe: list[dict[str, Any]] = []
    for item in blocks:
        confidence = item.get("confidence")
        if isinstance(confidence, (int, float)) and float(confidence) < confidence_threshold:
            unsafe.append(item)
        else:
            safe.append(item)
    return safe, unsafe


def _proposal_for_block(item: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    note_path = item.get("note_path")
    stage = item.get("stage")
    values = item.get("proposed_values")
    if not isinstance(note_path, str) or not note_path:
        return {}, ["note_path is required"]
    if not isinstance(stage, str) or not stage:
        return {}, ["stage is required"]
    if not isinstance(values, dict) or not values:
        return {}, ["proposed_values are required"]
    operation: dict[str, Any]
    if stage == "summary":
        summary = values.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return {}, ["summary stage requires a summary value"]
        operation = {"op": "organize_note", "path": note_path, "set": {}, "remove": [], "summary": summary}
    else:
        operation = {"op": "update_frontmatter", "path": note_path, "set": values, "remove": []}
    proposal_id = f"model-block-{_safe_id(note_path)}-{_safe_id(stage)}"
    return (
        {
            "id": proposal_id,
            "title": f"Review blocked model proposal for `{note_path}`",
            "kind": "cleanup",
            "status": "pending",
            "summary": f"Convert blocked `{stage}` model output into a normal review proposal.",
            "source_model_block": item.get("id", ""),
            "operations": [operation],
        },
        [],
    )


def _proposed_values(stage: str, proposal: dict[str, Any]) -> dict[str, Any]:
    if stage == "classify-type":
        return {"type": proposal.get("note_type", "")}
    if stage == "property-values":
        keys = ("status", "domain", "parent", "related", "cover", "source_kind", "capture_type")
        return {key: proposal[key] for key in keys if key in proposal}
    if stage == "summary":
        return {"summary": proposal.get("summary", "")}
    return {key: value for key, value in proposal.items() if key not in {"confidence", "warnings"}}


def _provider_details(proposal_provider: ProposalProvider | None) -> dict[str, Any]:
    if proposal_provider is None:
        return {}
    return {
        "provider": proposal_provider.__class__.__name__,
        "base_url": getattr(proposal_provider, "base_url", ""),
        "model": getattr(proposal_provider, "model", ""),
    }


def _block_id(note_path: str, stage: str) -> str:
    return f"model-block-{_safe_id(note_path)}-{_safe_id(stage)}"


def _safe_id(value: str) -> str:
    safe = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in safe.split("-") if part)
