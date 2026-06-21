"""Retrieval index generation."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .config import AgentConfig
from .logging_utils import append_log
from .safety import write_text_safely
from .scanner import (
    render_note_catalog,
    render_vault_map,
    scan_vault,
)


def render_property_index(entries: list[dict[str, Any]]) -> str:
    groups: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for entry in entries:
        for key in ("type", "status", "domain"):
            value = entry.get(key) or "(missing)"
            groups[key][value] += 1
    lines = ["# Property Index", ""]
    for key in sorted(groups):
        lines.extend([f"## {key}", ""])
        for value, count in sorted(groups[key].items()):
            lines.append(f"- `{value}`: {count}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_summary_brief(entries: list[dict[str, Any]]) -> str:
    lines = ["# Summary Brief", "", "Generated from frontmatter and note titles.", ""]
    for entry in entries:
        lines.append(
            f"- `{entry['path']}`: {entry.get('title') or ''} "
            f"({entry.get('type') or 'unknown'}, {entry.get('domain') or 'no domain'})"
        )
    if not entries:
        lines.append("- No notes discovered.")
    return "\n".join(lines) + "\n"


def run_rebuild_retrieval(config: AgentConfig) -> tuple[int, str]:
    result = scan_vault(config.vault_root)
    if config.dry_run:
        return (
            0,
            f"vault-agent rebuild-retrieval dry run\nWould rebuild retrieval files for {len(result.entries)} note(s).\nNo files were changed.",
        )
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    writes = {
        config.paths.retrieval_dir / "01 vault-map.md": render_vault_map(result),
        config.paths.retrieval_dir / "02 note-catalog.md": render_note_catalog(result),
        config.paths.retrieval_dir / "03 property-index.md": render_property_index(result.entries),
        config.paths.retrieval_dir / "04 summary-brief.md": render_summary_brief(result.entries),
    }
    for relative, content in writes.items():
        write_text_safely(config.vault_root / relative, content, backup_root=backup_root)
    append_log(config.vault_root, "rebuild-retrieval", [f"rebuilt for {len(result.entries)} note(s)"])
    return 0, f"vault-agent rebuild-retrieval complete\nUpdated retrieval files for {len(result.entries)} note(s)."
