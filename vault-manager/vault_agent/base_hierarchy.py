"""Plan and render hierarchical Bases dashboard proposals."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import COMMON_PROPERTIES, NOTE_TYPES


@dataclass
class ParentGroup:
    key: str
    label: str
    domain: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    project_entries: list[dict[str, Any]] = field(default_factory=list)
    coverage: str = ""

    @property
    def count(self) -> int:
        return len(self.entries)


@dataclass
class DomainGroup:
    domain: str
    label: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    type_counts: Counter[str] = field(default_factory=Counter)
    status_counts: Counter[str] = field(default_factory=Counter)
    parent_groups: list[ParentGroup] = field(default_factory=list)
    coverage: str = ""

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def active_projects(self) -> list[dict[str, Any]]:
        return [
            entry
            for entry in self.entries
            if entry.get("type") == "project" and entry.get("status") == "active"
        ]


@dataclass
class HierarchyPlan:
    domains: list[DomainGroup]
    needs_metadata: list[dict[str, Any]]
    total_notes: int

    @property
    def parent_dashboard_count(self) -> int:
        return sum(len(domain.parent_groups) for domain in self.domains)


def build_base_hierarchy_plan(
    entries: list[dict[str, Any]],
    *,
    min_child_notes: int = 2,
    llm_overrides: dict[str, Any] | None = None,
    system_dir: Path = Path("99 System"),
) -> HierarchyPlan:
    """Build deterministic hierarchy groups from scanned vault entries."""
    allowed_domains = set(COMMON_PROPERTIES["domain"]["allowed"])
    domain_groups: dict[str, DomainGroup] = {}
    needs_metadata: list[dict[str, Any]] = []
    usable_entries: list[dict[str, Any]] = []

    for entry in entries:
        if _excluded_entry(entry, system_dir=system_dir):
            continue
        usable_entries.append(entry)
        domain = entry.get("domain")
        if not isinstance(domain, str) or not domain or domain not in allowed_domains:
            needs_metadata.append(entry)
            continue
        group = domain_groups.setdefault(
            domain,
            DomainGroup(domain=domain, label=domain.title()),
        )
        group.entries.append(entry)
        group.type_counts[_display_value(entry.get("type"))] += 1
        group.status_counts[_display_value(entry.get("status"))] += 1

    overrides = llm_overrides or {}
    domain_overrides = overrides.get("domains", {})
    parent_overrides = overrides.get("parents", {})
    for domain in domain_groups.values():
        domain.parent_groups = _parent_groups_for_domain(
            domain,
            min_child_notes=min_child_notes,
            parent_overrides=parent_overrides,
        )
        if isinstance(domain_overrides, dict):
            override = domain_overrides.get(domain.domain, {})
        else:
            override = {}
        domain.label = _clean_label(override.get("label")) or domain.label
        domain.coverage = _clean_coverage(override.get("coverage")) or _domain_coverage(domain)

    domains = sorted(domain_groups.values(), key=lambda group: (-group.count, group.domain))
    return HierarchyPlan(
        domains=domains,
        needs_metadata=sorted(needs_metadata, key=lambda entry: entry["path"].lower()),
        total_notes=len(usable_entries),
    )


def generate_base_hierarchy_proposal(
    *,
    entries: list[dict[str, Any]],
    output_root: str = "01 Dashboards",
    min_child_notes: int = 2,
    llm_overrides: dict[str, Any] | None = None,
    system_dir: Path = Path("99 System"),
) -> tuple[dict[str, Any], HierarchyPlan]:
    plan = build_base_hierarchy_plan(
        entries,
        min_child_notes=min_child_notes,
        llm_overrides=llm_overrides,
        system_dir=system_dir,
    )
    output = _clean_output_root(output_root)
    operations: list[dict[str, Any]] = [
        {
            "op": "write_file",
            "path": f"{output}/Domains.md",
            "if_exists": "overwrite",
            "merge_generated": True,
            "content": render_primary_dashboard(plan=plan, output_root=output),
        }
    ]
    for domain in plan.domains:
        operations.append(
            {
                "op": "write_file",
                "path": f"{output}/Domains/{_safe_filename(domain.label)}.md",
                "if_exists": "overwrite",
                "merge_generated": True,
                "content": render_domain_dashboard(domain=domain, output_root=output),
            }
        )
        for parent in domain.parent_groups:
            operations.append(
                {
                    "op": "write_file",
                    "path": f"{output}/Domains/{_safe_filename(domain.label)}/{_safe_filename(parent.label)}.md",
                    "if_exists": "overwrite",
                    "merge_generated": True,
                    "content": render_parent_dashboard(parent=parent, output_root=output),
                }
            )
    proposal = {
        "id": "base-hierarchy",
        "title": "Create hierarchical Bases dashboards",
        "kind": "base-hierarchy",
        "status": "pending",
        "summary": (
            "Create reviewable domain and parent/project dashboards with embedded Bases "
            "using sparse vault metadata."
        ),
        "operations": operations,
    }
    return proposal, plan


def hierarchy_llm_prompt(plan: HierarchyPlan, *, max_domains: int) -> str:
    """Return a bounded JSON-only prompt for optional coverage prose enrichment."""
    domains: list[dict[str, Any]] = []
    for domain in plan.domains[:max_domains]:
        domains.append(
            {
                "domain": domain.domain,
                "note_count": domain.count,
                "type_counts": dict(domain.type_counts),
                "top_titles": [entry["title"] for entry in domain.entries[:12]],
                "parents": [
                    {"key": parent.key, "label": parent.label, "note_count": parent.count}
                    for parent in domain.parent_groups[:8]
                ],
            }
        )
    return (
        "Return exactly one JSON object with optional concise dashboard wording.\n"
        "Use this shape: {\"domains\":{\"work\":{\"label\":\"Work\",\"coverage\":\"...\"}},"
        "\"parents\":{\"[[Project]]\":{\"label\":\"Project\",\"coverage\":\"...\"}}}.\n"
        "Coverage must be one sentence, grounded only in the supplied titles and counts. "
        "Do not invent new domains, properties, or links.\n\n"
        + json.dumps({"domains": domains}, indent=2)
    )


def normalize_hierarchy_llm_response(response: dict[str, Any]) -> dict[str, Any]:
    """Keep only safe optional LLM labels/coverage fields."""
    normalized: dict[str, Any] = {"domains": {}, "parents": {}}
    for section in ("domains", "parents"):
        values = response.get(section)
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            label = _clean_label(value.get("label"))
            coverage = _clean_coverage(value.get("coverage"))
            cleaned: dict[str, str] = {}
            if label:
                cleaned["label"] = label
            if coverage:
                cleaned["coverage"] = coverage
            if cleaned:
                normalized[section][key] = cleaned
    return normalized


# Friendly column display names for generated Bases, so views read cleanly in Obsidian.
DISPLAY_NAMES: dict[str, str] = {
    "file.name": "Name",
    "file.mtime": "Modified",
    "file.ctime": "Created",
    "type": "Type",
    "status": "Status",
    "domain": "Domain",
    "parent": "Parent",
    "related": "Related",
    "source_kind": "Source",
    "cover": "Cover",
}

# cssclass that activates the bundled Dashboard++ snippet (.obsidian/snippets/dashboard.css).
DASHBOARD_CSSCLASS = "dashboard"


def _dashboard_frontmatter(*, domain: str, parent: str = "") -> str:
    """Render index-note frontmatter with the dashboard cssclass for styled rendering."""
    parent_line = f'parent: "{_yaml_frontmatter_value(parent)}"' if parent else "parent:"
    return (
        "---\n"
        "type: index\n"
        "status: active\n"
        f"domain: {domain}\n"
        f"{parent_line}\n"
        "related: []\n"
        "cover:\n"
        "source_kind:\n"
        "capture_type:\n"
        "cssclasses:\n"
        f"  - {DASHBOARD_CSSCLASS}\n"
        "---"
    )


def _base_block(*, filters: list[str], views: list[dict[str, Any]]) -> str:
    """Render an embedded ```base block with friendly display names, sorts, and views.

    Each view is a dict with keys: type, name, order, optional sort
    (list of (property, direction)), optional group_by ((property, direction)),
    and optional filters (list of expression strings, ANDed at the view level).
    """
    lines: list[str] = ["```base", "filters:", "  and:"]
    for expression in filters:
        lines.append(f"    - {_yaml_filter(expression)}")

    columns: list[str] = []
    for view in views:
        for column in view.get("order", []):
            if column not in columns:
                columns.append(column)
    property_lines: list[str] = []
    for column in columns:
        display = DISPLAY_NAMES.get(column)
        if display:
            property_lines.append(f"  {column}:")
            property_lines.append(f"    displayName: {display}")
    if property_lines:
        lines.append("properties:")
        lines.extend(property_lines)

    lines.append("views:")
    for view in views:
        lines.append(f"  - type: {view['type']}")
        lines.append(f"    name: {json.dumps(view['name'])}")
        view_filters = view.get("filters")
        if view_filters:
            lines.append("    filters:")
            lines.append("      and:")
            for expression in view_filters:
                lines.append(f"        - {_yaml_filter(expression)}")
        group_by = view.get("group_by")
        if group_by:
            prop, direction = group_by
            lines.append("    groupBy:")
            lines.append(f"      property: {prop}")
            lines.append(f"      direction: {direction}")
        sort = view.get("sort")
        if sort:
            lines.append("    sort:")
            for prop, direction in sort:
                lines.append(f"      - property: {prop}")
                lines.append(f"        direction: {direction}")
        order = view.get("order")
        if order:
            lines.append("    order:")
            for column in order:
                lines.append(f"      - {column}")
    lines.append("```")
    return "\n".join(lines)


def render_primary_dashboard(*, plan: HierarchyPlan, output_root: str) -> str:
    domain_rows = "\n".join(_domain_summary_line(domain, output_root) for domain in plan.domains)
    if not domain_rows:
        domain_rows = "- No populated domains found."
    needs_metadata = _needs_metadata_section(plan.needs_metadata)
    frontmatter = _dashboard_frontmatter(domain="meta")
    domain_cards = _base_block(
        filters=[
            'file.ext == "md"',
            'type == "index"',
            f'file.path.contains("{output_root}")',
            'parent == "[[Domains]]"',
        ],
        views=[
            {
                "type": "cards",
                "name": "Domain Cards",
                "sort": [("file.name", "ASC")],
                "order": ["file.name", "domain", "status", "file.mtime"],
            },
            {
                "type": "table",
                "name": "Domain Table",
                "sort": [("domain", "ASC")],
                "order": ["file.name", "domain", "parent", "file.mtime"],
            },
        ],
    )
    all_notes = _base_block(
        filters=[
            'file.ext == "md"',
            'type != "system"',
            f'!file.path.contains("{output_root}")',
        ],
        views=[
            {
                "type": "table",
                "name": "All Notes",
                "group_by": ("domain", "ASC"),
                "sort": [("file.mtime", "DESC")],
                "order": [
                    "file.name",
                    "type",
                    "status",
                    "domain",
                    "parent",
                    "related",
                    "file.mtime",
                ],
            },
        ],
    )
    return f"""{frontmatter}

# Domains

> [!abstract] Vault Map
> {plan.total_notes} non-system notes across {len(plan.domains)} domains. Generated by `vault-agent propose-base-hierarchy` — open in Reading view with the `dashboard` snippet enabled for the styled layout.

## Orientation

Add durable context and curated domain links here. pi-vault preserves this section.

<!-- pi-vault:generated:start -->

## Domains

{domain_rows}

{needs_metadata}

## Domain Cards

{domain_cards}

## All Notes By Domain

{all_notes}

<!-- pi-vault:generated:end -->
"""


def render_domain_dashboard(*, domain: DomainGroup, output_root: str) -> str:
    parent_links = "\n".join(
        f"- [[{output_root}/Domains/{_safe_filename(domain.label)}/{_safe_filename(parent.label)}|{parent.label}]] ({parent.count})"
        for parent in domain.parent_groups
    )
    if not parent_links:
        parent_links = "- No parent/project dashboards met the threshold."
    frontmatter = _dashboard_frontmatter(domain=domain.domain, parent="[[Domains]]")
    domain_filter = f'domain == "{domain.domain}"'
    projects = _base_block(
        filters=['file.ext == "md"', domain_filter, 'type == "project"'],
        views=[
            {
                "type": "cards",
                "name": "Project Cards",
                "sort": [("status", "ASC"), ("file.name", "ASC")],
                "order": ["file.name", "status", "parent", "related"],
            },
            {
                "type": "table",
                "name": "Project Table",
                "sort": [("status", "ASC"), ("file.mtime", "DESC")],
                "order": ["file.name", "status", "parent", "related", "file.mtime"],
            },
        ],
    )
    stored = _base_block(
        filters=[
            'file.ext == "md"',
            domain_filter,
            '(type == "note" or type == "source" or source_kind != "")',
        ],
        views=[
            {
                "type": "cards",
                "name": "Knowledge Cards",
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "type", "source_kind", "parent"],
            },
            {
                "type": "table",
                "name": "Knowledge Table",
                "sort": [("type", "ASC"), ("file.name", "ASC")],
                "order": ["file.name", "type", "source_kind", "status", "parent", "related"],
            },
        ],
    )
    people = _base_block(
        filters=[
            'file.ext == "md"',
            domain_filter,
            '(type == "person" or type == "organization")',
        ],
        views=[
            {
                "type": "table",
                "name": "People And Organizations",
                "group_by": ("type", "ASC"),
                "sort": [("file.name", "ASC")],
                "order": ["file.name", "type", "status", "parent", "related"],
            },
        ],
    )
    meetings = _base_block(
        filters=['file.ext == "md"', domain_filter, '(type == "meeting" or type == "task")'],
        views=[
            {
                "type": "table",
                "name": "Meetings And Tasks",
                "group_by": ("status", "ASC"),
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "type", "status", "parent", "related", "file.mtime"],
            },
        ],
    )
    all_notes = _base_block(
        filters=['file.ext == "md"', domain_filter],
        views=[
            {
                "type": "table",
                "name": "All Notes",
                "group_by": ("type", "ASC"),
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "type", "status", "parent", "related", "file.mtime"],
            },
        ],
    )
    return f"""{frontmatter}

# {domain.label}

> [!abstract] {domain.label} Domain
> {domain.count} notes — {_counter_summary(domain.type_counts.most_common(4))}. {domain.coverage}

## Orientation

Add durable context and curated links here. pi-vault preserves this section.

<!-- pi-vault:generated:start -->

## Counts

- Notes: {domain.count}
- Types: {_counter_summary(domain.type_counts)}
- Statuses: {_counter_summary(domain.status_counts)}

## Hubs

{parent_links}

## Projects

{projects}

## Stored Information

{stored}

## People And Organizations

{people}

## Meetings And Tasks

{meetings}

## All Domain Notes

{all_notes}

<!-- pi-vault:generated:end -->
"""


def render_parent_dashboard(*, parent: ParentGroup, output_root: str) -> str:
    parent_filter = _parent_filter(parent.key, parent.label)
    frontmatter = _dashboard_frontmatter(domain=parent.domain, parent=parent.key)
    domain_filter = f'domain == "{parent.domain}"'
    scope = ['file.ext == "md"', domain_filter, parent_filter]
    overview = _base_block(
        filters=scope,
        views=[
            {
                "type": "cards",
                "name": "Cards",
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "type", "status", "source_kind"],
            },
            {
                "type": "table",
                "name": "All Notes",
                "group_by": ("type", "ASC"),
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "type", "status", "source_kind", "related", "file.mtime"],
            },
        ],
    )
    active_tasks = _base_block(
        filters=scope + ['type == "task"', 'status == "active"'],
        views=[
            {
                "type": "table",
                "name": "Active Tasks",
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "status", "related", "file.mtime"],
            },
        ],
    )
    sources = _base_block(
        filters=scope + ['(type == "source" or source_kind != "")'],
        views=[
            {
                "type": "table",
                "name": "Sources",
                "sort": [("file.name", "ASC")],
                "order": ["file.name", "source_kind", "status", "related"],
            },
        ],
    )
    meetings = _base_block(
        filters=scope + ['type == "meeting"'],
        views=[
            {
                "type": "table",
                "name": "Meetings",
                "sort": [("file.mtime", "DESC")],
                "order": ["file.name", "status", "related", "file.mtime"],
            },
        ],
    )
    return f"""{frontmatter}

# {parent.label}

> [!abstract] {parent.label}
> {parent.count} notes. {parent.coverage}

## Orientation

Add durable context and curated links here. pi-vault preserves this section.

<!-- pi-vault:generated:start -->

## Counts

- Notes: {parent.count}

## Overview

{overview}

## Active Tasks

{active_tasks}

## Sources

{sources}

## Meetings

{meetings}

<!-- pi-vault:generated:end -->
"""


def _excluded_entry(entry: dict[str, Any], *, system_dir: Path) -> bool:
    path = Path(entry.get("path", ""))
    if path.is_relative_to(system_dir):
        return True
    if entry.get("frontmatter_error"):
        return True
    if entry.get("system_template"):
        return True
    if entry.get("type") == "template":
        return True
    return False


def _parent_groups_for_domain(
    domain: DomainGroup,
    *,
    min_child_notes: int,
    parent_overrides: dict[str, Any],
) -> list[ParentGroup]:
    grouped: dict[str, ParentGroup] = {}
    project_names = {
        _wikilink_name(entry["title"]): entry
        for entry in domain.entries
        if entry.get("type") == "project"
    }
    for entry in domain.entries:
        parent_key = _parent_key(entry.get("parent"))
        if not parent_key and entry.get("type") == "project":
            parent_key = _wikilink_name(entry["title"])
        if not parent_key:
            continue
        label = _parent_label(parent_key)
        group = grouped.setdefault(
            parent_key,
            ParentGroup(key=parent_key, label=label, domain=domain.domain),
        )
        group.entries.append(entry)
        if entry.get("type") == "project":
            group.project_entries.append(entry)
    for project_key, entry in project_names.items():
        group = grouped.setdefault(
            project_key,
            ParentGroup(
                key=project_key,
                label=_parent_label(project_key),
                domain=domain.domain,
            ),
        )
        if entry not in group.entries:
            group.entries.append(entry)
            group.project_entries.append(entry)

    selected: list[ParentGroup] = []
    for key, group in grouped.items():
        # Require every hub (including project hubs) to clear the threshold so single-note
        # projects do not sprawl into their own dashboards.
        if group.count < min_child_notes:
            continue
        override = parent_overrides.get(key, {}) if isinstance(parent_overrides, dict) else {}
        group.label = _clean_label(override.get("label")) or group.label
        group.coverage = _clean_coverage(override.get("coverage")) or _parent_coverage(group)
        selected.append(group)
    return sorted(selected, key=lambda group: (-group.count, group.label.lower()))


def _domain_coverage(domain: DomainGroup) -> str:
    top_types = _counter_summary(domain.type_counts.most_common(3))
    top_parents = ", ".join(parent.label for parent in domain.parent_groups[:3])
    if top_parents:
        return (
            f"Covers {top_types} across {top_parents}, with {domain.count} notes in this domain."
        )
    return f"Covers {top_types}, with {domain.count} notes in this domain."


def _parent_coverage(parent: ParentGroup) -> str:
    type_counts = Counter(_display_value(entry.get("type")) for entry in parent.entries)
    return f"Covers {_counter_summary(type_counts)} connected to {parent.label}."


def _needs_metadata_section(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "## Needs Metadata\n\nNo non-system notes were missing approved domains."
    lines = [
        "## Needs Metadata",
        "",
        (
            f"{len(entries)} non-system notes are missing an approved `domain` value. "
            "They are not treated as a domain in this hierarchy."
        ),
        "",
    ]
    for entry in entries[:20]:
        lines.append(f"- `{entry['path']}`")
    if len(entries) > 20:
        lines.append(f"- ...and {len(entries) - 20} more.")
    return "\n".join(lines)


def _domain_summary_line(domain: DomainGroup, output_root: str) -> str:
    link = f"[[{output_root}/Domains/{_safe_filename(domain.label)}|{domain.label}]]"
    active = len(domain.active_projects)
    parents = ", ".join(parent.label for parent in domain.parent_groups[:3]) or "none yet"
    return (
        f"- {link}: {domain.count} notes; active projects: {active}; "
        f"top hubs: {parents}. {domain.coverage}"
    )


def _parent_filter(parent_key: str, label: str) -> str:
    link = _wikilink_name(label)
    values = []
    for value in (parent_key, label, _parent_label(parent_key), link):
        if value and value not in values:
            values.append(value)
    comparisons = [f"parent == {json.dumps(value)}" for value in values]
    file_match = f"file.basename == {json.dumps(_parent_label(parent_key))}"
    return "(" + " or ".join(comparisons + [file_match]) + ")"


def _parent_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    return text


def _parent_label(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("[[") and stripped.endswith("]]"):
        stripped = stripped[2:-2]
    if "|" in stripped:
        stripped = stripped.split("|", 1)[1]
    if "/" in stripped:
        stripped = stripped.rsplit("/", 1)[1]
    return stripped.strip() or "Parent"


def _wikilink_name(value: str) -> str:
    stripped = _parent_label(value)
    return f"[[{stripped}]]"


def _counter_summary(counter: Counter[str] | list[tuple[str, int]]) -> str:
    items = counter if isinstance(counter, list) else counter.most_common()
    if not items:
        return "none"
    return ", ".join(f"{key}: {value}" for key, value in items)


def _display_value(value: Any) -> str:
    return value if isinstance(value, str) and value else "blank"


def _clean_label(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned[:80]


def _clean_coverage(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned[:300]


def _clean_output_root(value: str) -> str:
    path = Path(value.strip().strip("/"))
    if not value.strip() or path.is_absolute() or ".." in path.parts:
        raise ValueError("output root must be a relative vault path")
    return path.as_posix()


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "", value).strip()
    return cleaned.replace(" ", "-") or "Index"


def _yaml_filter(expression: str) -> str:
    return "'" + expression.replace("'", "''") + "'"


def _yaml_frontmatter_value(value: str) -> str:
    return value.replace('"', '\\"')
