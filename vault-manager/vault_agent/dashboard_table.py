"""Refresh the dashboard-request table inside the canonical schema note.

Scans the vault for the property/value combinations that actually occur (domains,
types, projects/parents, source kinds, capture types), with note counts, and rewrites
the marker-delimited table in ``0.00 Vault Schema.md`` — preserving the user's
checkmarks. The user ticks the ``Build`` column; ``schema-sync`` then records the
choices and ``propose-requested-dashboards`` builds them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .config import AgentConfig
from .safety import write_text_safely
from .scanner import scan_vault
from .schema_note import (
    DASHBOARDS_END,
    DASHBOARDS_START,
    parse_dashboard_requests,
    render_dashboard_table,
    schema_note_path,
)

# Property rows offered as dashboard candidates, in display order. `parent` is shown
# as the project/owner grouping.
_CANDIDATE_PROPERTIES = ("domain", "type", "parent", "source_kind", "capture_type")


@dataclass
class RefreshResult:
    changed: bool = False
    note_missing: bool = False
    rows: int = 0


def _parent_label(value: Any) -> str:
    """Normalize a ``parent`` value to a bare label (strip wikilink + path + alias)."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2].strip()
    if "|" in text:  # wikilink alias: take the display text
        text = text.split("|", 1)[1].strip()
    if "/" in text:  # path target: take the file name
        text = text.rsplit("/", 1)[1].strip()
    return text


def candidate_rows(
    config: AgentConfig, *, min_count: int = 2, keep: set[tuple[str, str]] | None = None
) -> list[dict[str, Any]]:
    """Enumerate `(property, value, count)` candidates from the current vault.

    Rows below ``min_count`` are dropped unless their key is in ``keep`` (so an
    already-checked combination never disappears from the table).
    """
    keep = keep or set()
    counts: dict[str, Counter] = {prop: Counter() for prop in _CANDIDATE_PROPERTIES}
    skip_prefixes = (
        config.paths.system_dir.as_posix().rstrip("/") + "/",
        config.paths.dashboards_dir.as_posix().rstrip("/") + "/",
    )
    for entry in scan_vault(config.vault_root).entries:
        path = entry.get("path", "")
        if isinstance(path, str) and path.startswith(skip_prefixes):
            continue  # scaffolding (system + dashboards), not content to chart
        frontmatter = entry.get("frontmatter") or {}
        for prop in ("domain", "type", "source_kind", "capture_type"):
            value = frontmatter.get(prop) or entry.get(prop)
            if isinstance(value, str) and value.strip():
                counts[prop][value.strip()] += 1
        label = _parent_label(frontmatter.get("parent") or entry.get("parent"))
        if label:
            counts["parent"][label] += 1

    rows: list[dict[str, Any]] = []
    for prop in _CANDIDATE_PROPERTIES:
        for value, count in sorted(counts[prop].items(), key=lambda kv: (-kv[1], kv[0])):
            if count < min_count and (prop, value) not in keep:
                continue
            rows.append({"property": prop, "value": value, "count": count})
    # Surface any checked combination that no longer appears in the vault.
    present = {(r["property"], r["value"]) for r in rows}
    for prop, value in sorted(keep - present):
        rows.append({"property": prop, "value": value, "count": 0})
    return rows


def _splice(note_text: str, table_lines: list[str]) -> str:
    block = "\n".join(table_lines)
    start = note_text.find(DASHBOARDS_START)
    end = note_text.find(DASHBOARDS_END)
    if start != -1 and end != -1 and end > start:
        return note_text[:start] + block + note_text[end + len(DASHBOARDS_END) :]
    # No markers (e.g. an older note): append a fresh Dashboards section.
    suffix = "" if note_text.endswith("\n") else "\n"
    return note_text + suffix + "\n## Dashboards\n\n" + block + "\n"


def refresh_dashboard_table(
    config: AgentConfig, *, min_count: int = 2, write: bool = True
) -> RefreshResult:
    note_path = schema_note_path(config)
    if not note_path.exists():
        return RefreshResult(note_missing=True)
    text = note_path.read_text(encoding="utf-8")
    checked = {(r["property"], r["value"]) for r in parse_dashboard_requests(text)}
    rows = candidate_rows(config, min_count=min_count, keep=checked)
    table = render_dashboard_table(rows, checked=checked)
    updated = _splice(text, table)
    result = RefreshResult(changed=updated != text, rows=len(rows))
    if write and result.changed and not getattr(config, "dry_run", False):
        write_text_safely(note_path, updated)
    return result
