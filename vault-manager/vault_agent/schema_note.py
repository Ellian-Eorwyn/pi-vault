"""Canonical, human-editable schema note.

A single scannable Markdown note at the top of the vault system folder is the
source of truth for the vault's categories and their definitions. The user edits
it directly; the agent checks it first on every run and syncs only what changed
into the structured ``schema.json`` so the model is always aligned on the current
categories + definitions.

This module renders that note from a schema, parses it back (tolerantly), and
syncs changes into ``schema.json`` with a file-hash short-circuit for the common
unchanged case.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .paths import paths_for
from .safety import write_text_safely
from .scanner import scan_vault
from .schema import (
    COMMON_PROPERTIES,
    CORE_PROPERTY_ORDER,
    DEFINITION_SCHEMA_KEYS,
    NOTE_TYPES,
    allowed_controlled_values_from_schema,
    custom_properties_from_schema,
    default_schema,
    definitions_for,
    hub_descriptions_for,
    load_schema,
    note_type_definitions_from_schema,
    note_types_from_schema,
    property_definitions_for,
    property_order_from_schema,
    topic_hubs_from_schema,
)

SCHEMA_NOTE_NAME = "0.00 Vault Schema.md"
STATE_FILENAME = "schema-note-state.json"

# Generated-region markers around the dashboard-request table. Everything between
# them is refreshed from a vault scan; the user only edits the `Build` checkmarks,
# which a refresh preserves.
DASHBOARDS_START = "<!-- pi-vault:dashboards:start -->"
DASHBOARDS_END = "<!-- pi-vault:dashboards:end -->"
_DASHBOARDS_HEADER = "| Build | Property | Value | Notes |"
_DASHBOARDS_DIVIDER = "| --- | --- | --- | --- |"

# Controlled-value sections rendered/parsed as `## <heading>` of `- value — def`.
# Order is the display order in the note.
_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Note types", "note_type"),
    ("Status", "status"),
    ("Domains", "domain"),
    ("Source kinds", "source_kind"),
    ("Capture types", "capture_type"),
)
_HEADING_TO_PROPERTY = {heading.lower(): prop for heading, prop in _SECTIONS}
# Tolerate singular/plural and spacing variants when parsing user edits.
_HEADING_ALIASES = {
    "note type": "note_type",
    "note-types": "note_type",
    "domain": "domain",
    "source kind": "source_kind",
    "source-kinds": "source_kind",
    "capture type": "capture_type",
    "capture-types": "capture_type",
    "statuses": "status",
    "topic hub": "topic_hubs",
    "topic hubs": "topic_hubs",
    "property": "properties",
    "properties": "properties",
}

_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
# value/definition separator: em/en dash (spaced), a colon (space after, optional
# space before — the common `value: def`), or a spaced hyphen. First match wins.
_SEPARATOR_RE = re.compile(r"\s+[—–]\s+|\s*:\s*|\s+-\s+")
_HEADING_RE = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")


# --------------------------------------------------------------------------- IO


def schema_note_path(config: AgentConfig) -> Path:
    return config.vault_root / config.paths.system_dir / SCHEMA_NOTE_NAME


def state_path(config: AgentConfig) -> Path:
    return config.vault_root / config.paths.agent_dir / STATE_FILENAME


# ------------------------------------------------------------------- rendering


def _value_line(value: str, definition: str) -> str:
    definition = (definition or "").strip()
    return f"- {value} — {definition}" if definition else f"- {value}"


def _property_type_from_schema(schema: dict[str, Any] | None, name: str) -> str:
    """Return ``"list"`` for a list-typed property, else ``"string"``."""
    if isinstance(schema, dict):
        core = schema.get("core_properties")
        spec = core.get(name) if isinstance(core, dict) else None
        if isinstance(spec, dict) and spec.get("type") == "list":
            return "list"
    builtin = COMMON_PROPERTIES.get(name)
    if isinstance(builtin, dict) and builtin.get("type") == "list":
        return "list"
    return "string"


def _property_line(name: str, ptype: str, definition: str) -> str:
    label = f"{name} (list)" if ptype == "list" else name
    definition = (definition or "").strip()
    return f"- {label} — {definition}" if definition else f"- {label}"


def render_schema_note(schema: dict[str, Any] | None) -> str:
    """Render the canonical, human-editable schema note from a schema dict."""
    schema = schema or default_schema()
    lines = [
        "---",
        "type: system",
        "status: active",
        "domain: meta",
        "---",
        "",
        "# Vault Schema",
        "",
        "This note is the source of truth for your vault's categories and what they",
        "mean. Edit it freely: keep one `value — definition` per bulleted line under",
        "the matching heading. The agent reads this note first on every run and syncs",
        "your changes into its structured schema before doing any work, so the model",
        "always classifies with your current categories and definitions.",
        "",
        "## Properties",
        "",
        "The frontmatter properties notes can carry, and what each means. Add a property",
        "by adding a `name — definition` line; mark a list-valued property with `(list)`",
        "after the name. The controlled vocabularies for type, status, domain, source_kind,",
        "and capture_type live in their own sections below.",
        "",
    ]

    prop_defs = property_definitions_for(schema)
    for name in property_order_from_schema(schema):
        ptype = _property_type_from_schema(schema, name)
        lines.append(_property_line(name, ptype, prop_defs.get(name, "")))
    lines.append("")

    note_type_defs = note_type_definitions_from_schema(schema)
    for heading, prop in _SECTIONS:
        lines.append(f"## {heading}")
        lines.append("")
        if prop == "note_type":
            values = list(note_types_from_schema(schema))
            defs = note_type_defs
        else:
            values = [v for v in allowed_controlled_values_from_schema(schema, prop) if v]
            defs = definitions_for(schema, prop)
        for value in values:
            lines.append(_value_line(value, defs.get(value, "")))
        lines.append("")

    lines.append("## Topic hubs")
    lines.append("")
    lines.append("Navigation hubs notes point to via `parent`, grouped by domain.")
    lines.append("")
    hubs = topic_hubs_from_schema(schema)
    any_hub = False
    for domain in [v for v in allowed_controlled_values_from_schema(schema, "domain") if v]:
        pairs = hub_descriptions_for(domain, schema)
        if not pairs:
            continue
        any_hub = True
        lines.append(f"### {domain}")
        lines.append("")
        for name, description in pairs:
            lines.append(_value_line(name, description))
        lines.append("")
    if not any_hub:
        lines.append("_No topic hubs yet._")
        lines.append("")
    del hubs

    lines.append("## Dashboards")
    lines.append("")
    lines.append("Property/value combinations the agent can build a Bases dashboard for. Put an")
    lines.append("`x` in the `Build` column for each one you want, then run schema sync to record")
    lines.append("your choices and ask the agent to build them. The agent refreshes the rows below")
    lines.append("from your vault (your checkmarks are preserved); only edit the `Build` column.")
    lines.append("")
    lines.extend(render_dashboard_table(schema.get("dashboard_requests") or []))
    lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def render_dashboard_table(
    rows: list[dict[str, Any]],
    *,
    checked: set[tuple[str, str]] | None = None,
) -> list[str]:
    """Render the marker-delimited dashboard-request table.

    ``rows`` are ``{property, value, count?}`` candidates; ``checked`` overrides which
    rows are ticked (defaults to each row's own ``enabled`` flag).
    """
    out = [DASHBOARDS_START, _DASHBOARDS_HEADER, _DASHBOARDS_DIVIDER]
    for row in rows:
        prop = str(row.get("property", "")).strip()
        value = str(row.get("value", "")).strip()
        if not prop or not value:
            continue
        is_checked = (prop, value) in checked if checked is not None else bool(row.get("enabled"))
        mark = "x" if is_checked else " "
        count = row.get("count")
        notes = str(count) if count is not None else ""
        out.append(f"| {mark} | {prop} | {value} | {notes} |")
    out.append(DASHBOARDS_END)
    return out


# --------------------------------------------------------------------- parsing


_LIST_MARKER_RE = re.compile(r"\s*\((list|array)\)\s*$", re.IGNORECASE)


def _split_property_type(value: str) -> tuple[str, str]:
    """Split a property name from a trailing ``(list)`` type marker."""
    match = _LIST_MARKER_RE.search(value)
    if match:
        return value[: match.start()].strip(), "list"
    return value.strip(), "string"


def _split_value_def(text: str) -> tuple[str, str]:
    match = _SEPARATOR_RE.search(text)
    if match:
        value = text[: match.start()].strip()
        definition = text[match.end():].strip()
    else:
        value, definition = text.strip(), ""
    value = value.strip().strip("`").strip()
    return value, definition


def parse_schema_note(text: str) -> dict[str, Any]:
    """Tolerantly parse the canonical note into per-property definition maps.

    Returns ``{note_type, status, domain, source_kind, capture_type}`` each a
    ``{value: definition}`` dict, ``topic_hubs`` as ``{domain: [(name, desc)]}``, and
    ``properties`` as ``{name: (type, definition)}`` from the Properties section
    (a trailing ``(list)`` marker on a name sets ``type`` to ``list``).
    Headings are case-insensitive; ``—``/``–``/``:``/spaced-``-`` all separate a
    value from its definition; non-bullet prose is ignored.
    """
    result: dict[str, Any] = {prop: {} for _, prop in _SECTIONS}
    result["topic_hubs"] = {}
    result["properties"] = {}
    section: str | None = None
    hub_domain: str | None = None

    for raw_line in text.splitlines():
        heading = _HEADING_RE.match(raw_line)
        if heading:
            level, label = len(heading.group(1)), heading.group(2).strip().lower()
            if level == 3 and section == "topic_hubs":
                hub_domain = heading.group(2).strip()
                continue
            section = _HEADING_TO_PROPERTY.get(label) or _HEADING_ALIASES.get(label)
            hub_domain = None
            continue
        if section is None:
            continue
        bullet = _BULLET_RE.match(raw_line)
        if not bullet:
            continue
        value, definition = _split_value_def(bullet.group(1))
        if not value:
            continue
        if section == "topic_hubs":
            if hub_domain:
                result["topic_hubs"].setdefault(hub_domain, []).append((value, definition))
        elif section == "properties":
            name, ptype = _split_property_type(value)
            if name:
                result["properties"][name] = (ptype, definition)
        else:
            result[section][value] = definition
    return result


def dashboards_region(text: str) -> str:
    """The text between the dashboard markers, or the whole `## Dashboards` section."""
    start = text.find(DASHBOARDS_START)
    end = text.find(DASHBOARDS_END)
    if start != -1 and end != -1 and end > start:
        return text[start + len(DASHBOARDS_START) : end]
    # Tolerate a note whose markers were removed: fall back to the heading's section.
    match = re.search(r"(?im)^##\s+dashboards\s*$", text)
    if not match:
        return ""
    rest = text[match.end() :]
    next_heading = re.search(r"(?m)^##\s+", rest)
    return rest[: next_heading.start()] if next_heading else rest


_CHECKED = {"x", "✓", "✔", "[x]", "yes", "true"}


def parse_dashboard_requests(text: str) -> list[dict[str, str]]:
    """Return ``[{property, value}]`` for each checked row of the dashboard table."""
    requests: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in dashboards_region(text).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 3:
            continue
        build, prop, value = cells[0], cells[1], cells[2]
        if prop.lower() == "property" or (prop and set(prop) <= {"-", ":"}):
            continue  # header or divider row
        if build.lower() not in _CHECKED:
            continue
        key = (prop, value)
        if prop and value and key not in seen:
            seen.add(key)
            requests.append({"property": prop, "value": value})
    return requests


# ------------------------------------------------------------------- hashing


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def section_hashes(parsed: dict[str, Any]) -> dict[str, str]:
    """Stable per-section hash so only changed sections need re-applying."""
    hashes: dict[str, str] = {}
    for key, value in parsed.items():
        hashes[key] = _hash_text(json.dumps(value, sort_keys=True, default=list))
    return hashes


def load_state(config: AgentConfig) -> dict[str, Any]:
    path = state_path(config)
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_state(config: AgentConfig, file_hash: str, sections: dict[str, str]) -> None:
    payload = {
        "path": (config.paths.system_dir / SCHEMA_NOTE_NAME).as_posix(),
        "file_hash": file_hash,
        "section_hashes": sections,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    write_text_safely(state_path(config), json.dumps(payload, indent=2, sort_keys=True) + "\n")


def note_changed(config: AgentConfig) -> bool:
    """Read-only: has the schema note changed since the last ingest?"""
    path = schema_note_path(config)
    if not path.exists():
        return False
    try:
        current = _hash_text(path.read_text(encoding="utf-8"))
    except OSError:
        return False
    return load_state(config).get("file_hash") != current


# ----------------------------------------------------------------------- sync


@dataclass
class SyncResult:
    changed: bool = False
    note_missing: bool = False
    added: dict[str, list[str]] = field(default_factory=dict)
    edited: dict[str, list[str]] = field(default_factory=dict)
    removed: dict[str, list[str]] = field(default_factory=dict)
    blocked: dict[str, list[str]] = field(default_factory=dict)
    summary: str = ""
    schema: dict[str, Any] | None = None


_FRONTMATTER_KEY = {
    "note_type": "type",
    "status": "status",
    "domain": "domain",
    "source_kind": "source_kind",
    "capture_type": "capture_type",
}


def _value_in_use(entries: list[dict[str, Any]], prop: str, value: str) -> bool:
    key = _FRONTMATTER_KEY[prop]
    for entry in entries:
        for candidate in (entry.get(key), (entry.get("frontmatter") or {}).get(key)):
            if candidate == value:
                return True
            if isinstance(candidate, list) and value in candidate:
                return True
    return False


def _hub_in_use(entries: list[dict[str, Any]], name: str) -> bool:
    for entry in entries:
        parent = entry.get("parent") or (entry.get("frontmatter") or {}).get("parent")
        if parent in (name, f"[[{name}]]"):
            return True
    return False


def _set_allowed(schema: dict[str, Any], prop: str, values: list[str]) -> None:
    allowed = [""] + values
    for bucket in ("core_properties", "common_properties"):
        section = schema.setdefault(bucket, {})
        spec = section.get(prop)
        if not isinstance(spec, dict):
            spec = {k: v for k, v in COMMON_PROPERTIES.get(prop, {"type": "string"}).items()}
            section[prop] = spec
        spec["allowed"] = allowed


def _apply_controlled(schema, prop, parsed_map, entries, result):
    current = [v for v in allowed_controlled_values_from_schema(schema, prop) if v]
    desired = list(parsed_map.keys())
    cur_set, des_set = set(current), set(desired)
    existing_defs = definitions_for(schema, prop)

    additions = [v for v in desired if v not in cur_set]
    removals = [v for v in current if v not in des_set]
    blocked = [v for v in removals if _value_in_use(entries, prop, v)]
    applied_removals = [v for v in removals if v not in blocked]
    edited = [
        v for v in desired
        if v in cur_set and (parsed_map[v] or "").strip()
        and parsed_map[v].strip() != (existing_defs.get(v) or "").strip()
    ]

    final = [v for v in current if v not in applied_removals]
    final += [v for v in desired if v not in set(final)]
    _set_allowed(schema, prop, final)

    defs: dict[str, str] = {}
    for value in blocked:  # keep definitions for removals we refused to drop
        if existing_defs.get(value):
            defs[value] = existing_defs[value]
    for value, definition in parsed_map.items():
        if (definition or "").strip():
            defs[value] = definition.strip()
    schema[DEFINITION_SCHEMA_KEYS[prop]] = defs

    result.added[prop] = additions
    result.edited[prop] = edited
    result.removed[prop] = applied_removals
    result.blocked[prop] = blocked


def _apply_note_types(schema, parsed_map, entries, result):
    current = list(note_types_from_schema(schema))
    desired = list(parsed_map.keys())
    cur_set, des_set = set(current), set(desired)
    existing = note_type_definitions_from_schema(schema)

    additions = [v for v in desired if v not in cur_set]
    removals = [v for v in current if v not in des_set]
    blocked = [v for v in removals if _value_in_use(entries, "note_type", v)]
    applied_removals = [v for v in removals if v not in blocked]
    edited = [
        v for v in desired
        if v in cur_set and (parsed_map[v] or "").strip()
        and parsed_map[v].strip() != (existing.get(v) or "").strip()
    ]

    base = {name: dict(spec) for name, spec in NOTE_TYPES.items()}
    src = schema.get("note_types")
    if isinstance(src, dict):
        for name, spec in src.items():
            if isinstance(spec, dict):
                base[name] = dict(spec)
    note_types: dict[str, Any] = {}
    for name in desired + blocked:
        spec = dict(base.get(name, {}))
        if (parsed_map.get(name) or "").strip():
            spec["description"] = parsed_map[name].strip()
        spec.setdefault("description", existing.get(name, ""))
        spec.setdefault("folder", "")
        note_types[name] = spec
    schema["note_types"] = note_types
    _set_allowed(schema, "type", list(note_types.keys()))

    result.added["note_type"] = additions
    result.edited["note_type"] = edited
    result.removed["note_type"] = applied_removals
    result.blocked["note_type"] = blocked


def _apply_hubs(schema, parsed_hubs, entries, result):
    current = topic_hubs_from_schema(schema)
    added: list[str] = []
    edited: list[str] = []
    removed: list[str] = []
    blocked: list[str] = []
    registry: dict[str, Any] = {}
    for domain in set(current) | set(parsed_hubs):
        cur_map = {n: d for n, d in hub_descriptions_for(domain, schema)}
        des_map = {n: (d or "") for n, d in parsed_hubs.get(domain, [])}
        for name in list(cur_map):
            if name not in des_map:
                if _hub_in_use(entries, name):
                    blocked.append(f"{domain}:{name}")
                    des_map[name] = cur_map[name]  # keep an in-use hub
                else:
                    removed.append(f"{domain}:{name}")
        for name, description in des_map.items():
            if name not in cur_map:
                added.append(f"{domain}:{name}")
            elif description.strip() and description.strip() != (cur_map.get(name) or "").strip():
                edited.append(f"{domain}:{name}")
        if des_map:
            registry[domain] = [{"name": n, "description": d} for n, d in des_map.items()]
    schema["topic_hubs"] = registry
    result.added["topic_hubs"] = added
    result.edited["topic_hubs"] = edited
    result.removed["topic_hubs"] = removed
    result.blocked["topic_hubs"] = blocked


def _property_in_use(entries: list[dict[str, Any]], name: str) -> bool:
    """Whether any scanned note carries ``name`` as a frontmatter key."""
    for entry in entries:
        if name in (entry.get("frontmatter") or {}):
            return True
    return False


def _set_property(schema: dict[str, Any], name: str, ptype: str) -> None:
    resolved = "list" if ptype == "list" else "string"
    for bucket in ("core_properties", "common_properties"):
        section = schema.setdefault(bucket, {})
        spec = section.get(name)
        if not isinstance(spec, dict):
            spec = {}
            section[name] = spec
        spec["type"] = resolved
        spec.setdefault("required", False)


def _apply_properties(schema, parsed_props, entries, result):
    """Add/remove user-declared frontmatter properties from the schema note.

    ``parsed_props`` maps ``{name: (type, definition)}``. Built-in core properties
    are never removed; a custom property still present in a note's frontmatter is
    kept (its removal is blocked and reported).
    """
    builtins = set(CORE_PROPERTY_ORDER)
    current = set(property_order_from_schema(schema))
    current_custom = list(custom_properties_from_schema(schema))
    desired = list(parsed_props.keys())
    desired_set = set(desired)
    existing_defs = property_definitions_for(schema)

    additions = [n for n in desired if n not in current]
    removals = [n for n in current_custom if n not in desired_set]
    blocked = [n for n in removals if _property_in_use(entries, n)]
    applied_removals = [n for n in removals if n not in blocked]
    edited = [
        n for n in desired
        if n in current and (parsed_props[n][1] or "").strip()
        and parsed_props[n][1].strip() != (existing_defs.get(n) or "").strip()
    ]

    for name in desired:
        if name in builtins:
            continue  # built-in specs are authoritative; only their definition may change
        _set_property(schema, name, parsed_props[name][0])
    for name in applied_removals:
        for bucket in ("core_properties", "common_properties"):
            section = schema.get(bucket)
            if isinstance(section, dict):
                section.pop(name, None)

    prop_defs: dict[str, str] = {}
    for name in blocked:  # keep definitions for removals we refused to drop
        if existing_defs.get(name):
            prop_defs[name] = existing_defs[name]
    for name, (_ptype, definition) in parsed_props.items():
        if name in applied_removals:
            continue
        if (definition or "").strip():
            prop_defs[name] = definition.strip()
    schema["property_definitions"] = prop_defs

    result.added["properties"] = additions
    result.edited["properties"] = edited
    result.removed["properties"] = applied_removals
    result.blocked["properties"] = blocked


def _apply_dashboards(schema: dict[str, Any], text: str, result: SyncResult) -> None:
    """Record the checked dashboard-request rows into ``schema["dashboard_requests"]``."""
    requests = parse_dashboard_requests(text)
    current = schema.get("dashboard_requests") or []
    cur_keys = {
        (r.get("property"), r.get("value")) for r in current if isinstance(r, dict)
    }
    new_keys = {(r["property"], r["value"]) for r in requests}
    schema["dashboard_requests"] = requests
    result.added["dashboards"] = [f"{p}:{v}" for p, v in sorted(new_keys - cur_keys)]
    result.removed["dashboards"] = [f"{p}:{v}" for p, v in sorted(cur_keys - new_keys)]
    result.edited["dashboards"] = []
    result.blocked["dashboards"] = []


def _summary(result: SyncResult) -> str:
    def total(bucket: dict[str, list[str]]) -> int:
        return sum(len(v) for v in bucket.values())

    parts = [
        f"+{total(result.added)} categories",
        f"{total(result.edited)} definitions edited",
        f"{total(result.removed)} removed",
    ]
    if total(result.blocked):
        parts.append(f"{total(result.blocked)} removals blocked (in use)")
    return "schema sync: " + ", ".join(parts)


def sync_schema_from_note(config: AgentConfig, *, write: bool = True) -> SyncResult:
    """Ingest the canonical schema note into ``schema.json`` (only what changed).

    Fast path: if the note's file hash matches the last ingest, returns immediately
    without parsing. Otherwise applies additions + definition edits + safe removals,
    refusing to remove a value still used by notes. The note itself is left exactly
    as the user wrote it (only its hash is recorded).
    """
    import copy

    result = SyncResult()
    path = schema_note_path(config)
    if not path.exists():
        result.note_missing = True
        result.summary = "no schema note to sync"
        return result

    text = path.read_text(encoding="utf-8")
    file_hash = _hash_text(text)
    if load_state(config).get("file_hash") == file_hash:
        result.summary = "schema note unchanged"
        return result

    parsed = parse_schema_note(text)
    schema = copy.deepcopy(load_schema(config.vault_root) or default_schema())
    entries = scan_vault(config.vault_root).entries

    for _, prop in _SECTIONS:
        if prop == "note_type":
            _apply_note_types(schema, parsed["note_type"], entries, result)
        else:
            _apply_controlled(schema, prop, parsed[prop], entries, result)
    _apply_hubs(schema, parsed["topic_hubs"], entries, result)
    # Only reconcile properties when the note actually declares a Properties section,
    # so a legacy note without one is never read as "remove every custom property".
    if parsed.get("properties"):
        _apply_properties(schema, parsed["properties"], entries, result)
    _apply_dashboards(schema, text, result)

    result.changed = any(
        result.added.get(k) or result.edited.get(k) or result.removed.get(k)
        for k in result.added
    )
    result.schema = schema
    result.summary = _summary(result)

    if write and not getattr(config, "dry_run", False):
        if result.changed:
            backup_root = config.vault_root / config.paths.agent_dir / "backups"
            write_text_safely(
                config.vault_root / config.paths.agent_dir / "schema.json",
                json.dumps(schema, indent=2) + "\n",
                backup_root=backup_root,
            )
        # Record the hash even when only prose/whitespace changed, so the next run
        # short-circuits instead of re-parsing.
        _write_state(config, file_hash, section_hashes(parsed))
    return result
