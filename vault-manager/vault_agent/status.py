"""Human-readable status command."""

from __future__ import annotations

import json

from .config import AgentConfig
from .norms import current_lock_hash
from .organize_pass import latest_report
from .processing_state import processing_summary
from .readiness import build_readiness_report
from .scanner import scan_vault
from .schema import CORE_PROPERTY_ORDER
from .validation import validate_entries


def build_status(config: AgentConfig) -> dict[str, object]:
    result = scan_vault(config.vault_root)
    issues = validate_entries(result.entries)
    lock_hash = current_lock_hash(config.vault_root)
    summary = processing_summary(config.vault_root, norms_lock_hash=lock_hash)
    report = latest_report(config.vault_root)
    readiness = build_readiness_report(config)["readiness"]
    inbox_prefix = config.paths.inbox_dir.as_posix() + "/"
    inbox = [
        entry
        for entry in result.entries
        if entry["path"].startswith(inbox_prefix) and not _has_core_metadata(entry)
    ]
    return {
        "generated_by": "vault-agent",
        "vault_root": config.vault_root.as_posix(),
        "system_dir": config.paths.system_dir.as_posix(),
        "inbox_dir": config.paths.inbox_dir.as_posix(),
        "notes": len(result.entries),
        "inbox_needing_attention": len(inbox),
        "validation_issues": len(issues),
        "norms_lock": lock_hash or "",
        "stale_tracked_notes": summary["stale"],
        "blocked_tracked_notes": summary["blocked"],
        "last_organization_report": (
            report.relative_to(config.vault_root).as_posix() if report else ""
        ),
        "readiness": readiness,
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
        f"Notes: {status['notes']}",
        f"Inbox needing attention: {status['inbox_needing_attention']}",
        f"Validation issues: {status['validation_issues']}",
        f"Norms lock: {status['norms_lock'] or '(missing)'}",
        f"Stale tracked notes: {status['stale_tracked_notes']}",
        f"Blocked tracked notes: {status['blocked_tracked_notes']}",
        f"Last organization report: {status['last_organization_report'] or '(none)'}",
        f"Ready for organization pass: {status['readiness']}",
    ]
    return 0, "\n".join(lines)


def _has_core_metadata(entry) -> bool:
    frontmatter = entry.get("frontmatter", {})
    return all(key in frontmatter for key in CORE_PROPERTY_ORDER)
