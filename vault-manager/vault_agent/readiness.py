"""Organization readiness reporting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .frontmatter import parse_note
from .generated_state import generated_state_report
from .legacy import apply_legacy_mappings
from .norms import current_lock_hash
from .processing_state import processing_summary
from .processor import next_needed_stage
from .scanner import scan_vault
from .schema import CORE_PROPERTY_ORDER, accepted_properties_for, allowed_note_types, load_schema
from .validation import issue_groups, validate_entries


def build_readiness_report(config: AgentConfig, *, folder: str | None = None) -> dict[str, Any]:
    scan = scan_vault(config.vault_root)
    issues = validate_entries(scan.entries, config)
    lock_hash = current_lock_hash(config.vault_root)
    state_summary = processing_summary(config.vault_root, norms_lock_hash=lock_hash)
    candidate_stages = _candidate_stages(config, scan.entries, folder=folder, lock_hash=lock_hash)
    cleanup = _cleanup_opportunities(config, scan.entries, folder=folder)
    generated_state = generated_state_report(config)
    latest_report = generated_state["organization_reports"]["latest"]
    errors = sum(1 for issue in issues if issue.severity == "error")
    readiness = _readiness_status(
        generated_state=generated_state,
        validation_issues=len(issues),
        validation_errors=errors,
        candidate_stages=len(candidate_stages),
        cleanup_operations=cleanup["total"],
        stale_notes=state_summary["stale"],
        blocked_notes=state_summary["blocked"],
    )
    return {
        "vault_root": config.vault_root.as_posix(),
        "folder": folder or "",
        "readiness": readiness,
        "notes": len(scan.entries),
        "norms_lock": generated_state["norms_lock"],
        "validation": {
            "issues": len(issues),
            "errors": errors,
            "groups": issue_groups(issues),
        },
        "candidate_stages": {
            "count": len(candidate_stages),
            "sample": candidate_stages[:20],
        },
        "cleanup_queue": cleanup,
        "processing_state": state_summary,
        "generated_state": generated_state,
        "latest_organization_report": latest_report,
    }


def run_organization_readiness(
    config: AgentConfig, *, folder: str | None = None, json_output: bool = False
) -> tuple[int, str]:
    report = build_readiness_report(config, folder=folder)
    if json_output:
        return 0, json.dumps(report, indent=2, sort_keys=True)
    lines = [
        "vault-agent organization-readiness",
        f"Vault root: {report['vault_root']}",
        f"Scope: {report['folder'] or '(entire vault)'}",
        f"Ready for organization pass: {report['readiness']}",
        f"Notes: {report['notes']}",
        f"Norms lock: {report['norms_lock']['status']}",
        f"Validation issues: {report['validation']['issues']}",
        f"Validation errors: {report['validation']['errors']}",
        f"Candidate note stages: {report['candidate_stages']['count']}",
        f"Cleanup queue opportunities: {report['cleanup_queue']['total']}",
        f"Stale tracked notes: {report['processing_state']['stale']}",
        f"Blocked tracked notes: {report['processing_state']['blocked']}",
        f"Latest organization report: {report['latest_organization_report'] or '(none)'}",
    ]
    return 0, "\n".join(lines)


def _candidate_stages(
    config: AgentConfig,
    entries: list[dict[str, Any]],
    *,
    folder: str | None,
    lock_hash: str | None,
) -> list[dict[str, str]]:
    prefix = folder.strip("/").rstrip("/") if folder else ""
    candidates: list[dict[str, str]] = []
    for entry in entries:
        relative = Path(entry["path"])
        if entry.get("system_template") or relative.is_relative_to(config.paths.system_dir):
            continue
        if prefix and not entry["path"].startswith(prefix + "/"):
            continue
        if entry.get("frontmatter_error"):
            continue
        note_path = config.vault_root / relative
        stage = next_needed_stage(
            config.vault_root,
            note_path,
            entry,
            norms_lock_hash=lock_hash,
        )
        if stage:
            candidates.append({"path": entry["path"], "stage": stage})
    return candidates


def _cleanup_opportunities(
    config: AgentConfig, entries: list[dict[str, Any]], *, folder: str | None
) -> dict[str, Any]:
    prefix = folder.strip("/").rstrip("/") if folder else ""
    mappable = 0
    removable = 0
    sample: list[str] = []
    schema = load_schema(config.vault_root)
    approved_properties = accepted_properties_for(None, schema)
    for entry in entries:
        path = entry["path"]
        relative = Path(path)
        if relative.is_relative_to(config.paths.system_dir):
            continue
        if prefix and not path.startswith(prefix + "/"):
            continue
        note_path = config.vault_root / relative
        if not note_path.exists():
            continue
        parsed = parse_note(note_path.read_text(encoding="utf-8"))
        if parsed.error:
            continue
        original = dict(parsed.frontmatter)
        mapped = apply_legacy_mappings(original, config, approved_properties=approved_properties)
        has_mapping = any(mapped.get(key) != original.get(key) for key in CORE_PROPERTY_ORDER if key in mapped)
        note_type = mapped.get("type") if mapped.get("type") in allowed_note_types(config.vault_root) else None
        accepted = accepted_properties_for(note_type, schema)
        unknown = [key for key in mapped if key not in accepted]
        if has_mapping:
            mappable += 1
        if unknown:
            removable += 1
        if (has_mapping or unknown) and len(sample) < 20:
            sample.append(path)
    return {
        "total": mappable + removable,
        "mappable_legacy": mappable,
        "unknown_property_removal_if_requested": removable,
        "sample": sample,
    }


def _readiness_status(
    *,
    generated_state: dict[str, Any],
    validation_issues: int,
    validation_errors: int,
    candidate_stages: int,
    cleanup_operations: int,
    stale_notes: int,
    blocked_notes: int,
) -> str:
    if generated_state["norms_lock"]["status"] != "current" or validation_errors:
        return "no"
    if blocked_notes or stale_notes or validation_issues or candidate_stages or cleanup_operations:
        return "review"
    return "yes"
