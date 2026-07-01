"""Human-readable status command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .generated_state import generated_state_report
from .norms import current_lock_hash
from .organize_pass import latest_report
from .processing_state import processing_summary
from .readiness import build_readiness_report
from .scanner import scan_vault
from .schema import CORE_PROPERTY_ORDER
from .schema_note import SCHEMA_NOTE_NAME, note_changed, schema_note_path
from .validation import issue_groups, validate_entries


def build_status(config: AgentConfig) -> dict[str, object]:
    result = scan_vault(config.vault_root)
    issues = validate_entries(result.entries, config)
    lock_hash = current_lock_hash(config.vault_root)
    summary = processing_summary(config.vault_root, norms_lock_hash=lock_hash)
    report = latest_report(config.vault_root)
    readiness_report = build_readiness_report(config)
    generated_state = generated_state_report(config)
    schema_state = {
        "missing": "provisional",
        "current": "locked",
        "stale": "drifted",
    }[generated_state["norms_lock"]["status"]]
    inbox_prefix = config.paths.inbox_dir.as_posix() + "/"
    inbox_entries = [
        entry
        for entry in result.entries
        if entry["path"].startswith(inbox_prefix)
    ]
    previous_manifest = _load_json(
        config.vault_root / config.paths.agent_dir / "manifest.json"
    )
    previous_notes = {
        entry["path"]: entry
        for entry in previous_manifest.get("notes", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    new_inbox_files = [
        entry["path"] for entry in inbox_entries if entry["path"] not in previous_notes
    ]
    changed_inbox_files = [
        entry["path"]
        for entry in inbox_entries
        if entry["path"] in previous_notes
        and entry.get("hash") != previous_notes[entry["path"]].get("hash")
    ]
    previous_state = _load_json(config.vault_root / config.paths.agent_dir / "state.json")
    pending_proposals = _pending_proposals(
        config.vault_root / config.paths.review_dir / "proposals"
    )
    return {
        "generated_by": "vault-agent",
        "vault_root": config.vault_root.as_posix(),
        "system_dir": config.paths.system_dir.as_posix(),
        "inbox_dir": config.paths.inbox_dir.as_posix(),
        "dashboards_dir": config.paths.dashboards_dir.as_posix(),
        "content_dirs": {
            key: value.as_posix() for key, value in config.paths.content_dirs.items()
        },
        "notes": len(result.entries),
        "inbox_needing_attention": sum(
            1 for entry in inbox_entries if not _has_core_metadata(entry)
        ),
        "inbox_changes": {
            "new": new_inbox_files,
            "changed": changed_inbox_files,
        },
        "validation_issues": len(issues),
        "validation_groups": issue_groups(issues),
        "generated_state": generated_state,
        "norms_lock": lock_hash or "",
        "schema_state": schema_state,
        "schema_note": {
            "path": (config.paths.system_dir / SCHEMA_NOTE_NAME).as_posix(),
            "present": schema_note_path(config).exists(),
            "changed": note_changed(config),
        },
        "previous_scan": previous_state.get("last_scan") or "",
        "stale_tracked_notes": summary["stale"],
        "blocked_tracked_notes": summary["blocked"],
        "pending_proposals": pending_proposals,
        "last_organization_report": (
            report.relative_to(config.vault_root).as_posix() if report else ""
        ),
        "readiness": readiness_report["readiness"],
    }


def run_status(config: AgentConfig, *, json_output: bool = False) -> tuple[int, str]:
    status = build_status(config)
    if json_output:
        return 0, json.dumps(status, indent=2, sort_keys=True)
    lines = [
        "vault-agent status",
        f"Vault root: {status['vault_root']}",
        f"System folder: {status['system_dir']}",
        f"Inbox folder: {status['inbox_dir']}",
        f"Dashboards folder: {status['dashboards_dir']}",
        f"Notes: {status['notes']}",
        f"Inbox needing attention: {status['inbox_needing_attention']}",
        f"New inbox files: {len(status['inbox_changes']['new'])}",
        f"Changed inbox files: {len(status['inbox_changes']['changed'])}",
        f"Validation issues: {status['validation_issues']}",
        f"Schema state: {status['schema_state']}",
        f"Schema note: {status['schema_note']['path']}"
        + (" (changed since last sync)" if status["schema_note"]["changed"] else ""),
        f"Norms lock: {status['norms_lock'] or '(missing)'}",
        f"Previous scan: {status['previous_scan'] or '(none)'}",
        f"Stale tracked notes: {status['stale_tracked_notes']}",
        f"Blocked tracked notes: {status['blocked_tracked_notes']}",
        f"Pending proposals: {status['pending_proposals']['count']}",
        f"Last organization report: {status['last_organization_report'] or '(none)'}",
        f"Ready for organization pass: {status['readiness']}",
    ]
    return 0, "\n".join(lines)


def _has_core_metadata(entry) -> bool:
    frontmatter = entry.get("frontmatter", {})
    return all(key in frontmatter for key in CORE_PROPERTY_ORDER)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _pending_proposals(proposals_dir: Path) -> dict[str, object]:
    paths: list[str] = []
    if proposals_dir.exists():
        for proposal_path in sorted(proposals_dir.glob("*.json")):
            proposal = _load_json(proposal_path)
            if proposal.get("status") == "pending":
                paths.append(proposal_path.name)
    return {"count": len(paths), "files": paths}
