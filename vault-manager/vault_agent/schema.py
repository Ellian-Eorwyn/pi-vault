"""Starter schema for deterministic vault validation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .paths import paths_for


SCHEMA_VERSION = "1.0.0"

CORE_PROPERTIES = {
    "type": {
        "type": "string",
        "required": False,
        "allowed": [
            "",
            "project",
            "source",
            "person",
            "organization",
            "meeting",
            "task",
            "note",
            "index",
            "daily",
            "template",
            "system",
        ],
    },
    "status": {
        "type": "string",
        "required": False,
        "allowed": ["", "active", "someday", "completed", "archived"],
    },
    "domain": {
        "type": "string",
        "required": False,
        "allowed": [
            "",
            "academic",
            "work",
            "craft",
            "technology",
            "philosophy",
            "health",
            "personal",
            "administration",
            "finance",
            "travel",
            "household",
            "meta",
        ],
    },
    "parent": {"type": "string", "required": False},
    "related": {"type": "list", "required": False},
    "cover": {"type": "string", "required": False},
    "source_kind": {
        "type": "string",
        "required": False,
        "allowed": [
            "",
            "book",
            "article",
            "report",
            "policy",
            "standard",
            "website",
            "dataset",
            "video",
            "podcast",
            "interview",
            "transcript",
            "presentation",
            "manual",
        ],
    },
    "capture_type": {
        "type": "string",
        "required": False,
        "allowed": ["", "voice", "meeting", "chat", "imported", "manual"],
    },
}

COMMON_PROPERTIES = CORE_PROPERTIES
CORE_PROPERTY_ORDER = (
    "type",
    "status",
    "domain",
    "parent",
    "related",
    "cover",
    "source_kind",
    "capture_type",
)

NOTE_TYPES = {
    "project": {
        "folder": "04 Work/<project> or a domain project folder",
        "description": "Temporary effort with a defined outcome.",
    },
    "source": {
        "folder": "07 Sources",
        "description": "Book, paper, article, video, podcast, dataset, or website.",
    },
    "person": {
        "folder": "02 People/02.01 Contacts or 02 People/02.02 Authors",
        "description": "Individual human being.",
    },
    "organization": {
        "folder": "03 Organizations",
        "description": "Institution, company, group, lab, or department.",
    },
    "meeting": {
        "folder": "Owning project or purpose-based domain folder",
        "description": "Notes from a meeting, interview, conversation, or call.",
    },
    "task": {
        "folder": "Owning project or purpose-based domain folder",
        "description": "Standalone actionable item.",
    },
    "note": {
        "folder": "Purpose-based domain folder or 06 Thoughts",
        "description": "General knowledge, reference, or idea note.",
    },
    "index": {
        "folder": "01 Dashboards",
        "description": "Dashboard, MOC, hub, or navigation page.",
    },
    "daily": {"folder": "06 Thoughts", "description": "Daily note."},
    "template": {
        "folder": "99 System/0.02 templates",
        "description": "Reusable note template.",
    },
    "system": {
        "folder": "99 System",
        "description": "Vault infrastructure, workflows, schemas, and agent memory.",
    },
}

STATUS_DEFINITIONS = {
    "active": "Currently relevant or maintained.",
    "someday": "Potential future work.",
    "completed": "Finished but retained.",
    "archived": "Historical or inactive.",
}

DOMAIN_DEFINITIONS = {
    "academic": "Research, scholarship, coursework, dissertation work.",
    "work": "Employment, consulting, professional projects.",
    "craft": "Making, building, artistic and hobby pursuits.",
    "technology": "Computing, software, hardware, automation.",
    "philosophy": "Ethics, religion, contemplative practice, intellectual traditions.",
    "health": "Physical health, fitness, nutrition, medical topics.",
    "personal": "Life events, relationships, identity, personal growth.",
    "administration": "Bureaucracy, paperwork, scheduling, insurance, legal matters.",
    "finance": "Money, taxes, budgeting, investments.",
    "travel": "Trips, destinations, logistics.",
    "household": "Home, pets, maintenance, possessions.",
    "meta": "PKM, vault design, workflows, agent systems.",
}

RECOMMENDED_TOPIC_HUBS = [
    "Academia",
    "Research",
    "Writing",
    "Teaching",
    "Work",
    "Career",
    "Technology",
    "Programming",
    "Linux",
    "Automation",
    "AI",
    "PKM",
    "Philosophy",
    "Ethics",
    "Religion",
    "Buddhism",
    "Health",
    "Exercise",
    "Nutrition",
    "Medicine",
    "Craft",
    "Sewing",
    "Leatherworking",
    "Photography",
    "Mycology",
    "Woodworking",
    "Cooking",
    "Personal",
    "Family",
    "Friends",
    "Relationships",
    "Finance",
    "Taxes",
    "Travel",
    "Household",
    "Home",
    "Pets",
    "Meta",
    "Vault",
    "Agents",
    "Workflows",
]

AGENT_RULES = [
    "Never invent new type values.",
    "Never invent new status values.",
    "Prefer existing domain values.",
    "Create new topic notes rather than new domain values.",
    "Use parent for hierarchy.",
    "Use related for cross-cutting connections.",
    "Treat topic notes as the primary ontology of the vault.",
    "Treat metadata as navigation support, not the primary knowledge structure.",
]


def default_topic_hubs() -> dict[str, list[dict[str, str]]]:
    """Empty per-domain topic-hub registry; hubs are surfaced per vault from its notes."""
    return {domain: [] for domain in DOMAIN_DEFINITIONS}


def new_domains(extra_domains: list[str] | None) -> list[str]:
    """User-defined domains not already part of the built-in vocabulary."""
    existing = set(DOMAIN_DEFINITIONS) | set(CORE_PROPERTIES["domain"]["allowed"])
    result: list[str] = []
    for domain in extra_domains or []:
        if domain and domain not in existing and domain not in result:
            result.append(domain)
    return result


def default_schema(extra_domains: list[str] | None = None) -> dict[str, Any]:
    extra = new_domains(extra_domains)
    core = deepcopy(CORE_PROPERTIES)
    core["domain"]["allowed"] = list(core["domain"]["allowed"]) + extra
    domain_definitions = deepcopy(DOMAIN_DEFINITIONS)
    for domain in extra:
        domain_definitions[domain] = "User-defined domain."
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "vault-agent",
        "note_types": deepcopy(NOTE_TYPES),
        "status_definitions": deepcopy(STATUS_DEFINITIONS),
        "domain_definitions": domain_definitions,
        "recommended_topic_hubs": list(RECOMMENDED_TOPIC_HUBS),
        "topic_hubs": {domain: [] for domain in domain_definitions},
        "agent_rules": list(AGENT_RULES),
        "core_properties": core,
        "common_properties": core,
        "folder_norms": {
            note_type: {"preferred_folder": spec["folder"]}
            for note_type, spec in NOTE_TYPES.items()
        },
    }


def topic_hubs_from_schema(schema: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Return the per-domain topic-hub registry from a loaded schema dict."""
    hubs = schema.get("topic_hubs")
    return hubs if isinstance(hubs, dict) else {}


def _hub_name(entry: Any) -> str:
    if isinstance(entry, dict):
        name = entry.get("name")
    else:
        name = entry
    return name.strip() if isinstance(name, str) else ""


def approved_hubs_for(domain: str | None, schema: dict[str, Any]) -> list[str]:
    """Return approved topic-hub names for a domain, in registry order."""
    entries = topic_hubs_from_schema(schema).get(domain or "", [])
    names: list[str] = []
    for entry in entries:
        name = _hub_name(entry)
        if name and name not in names:
            names.append(name)
    return names


def all_hub_names(schema: dict[str, Any]) -> set[str]:
    """Return every approved topic-hub name across all domains."""
    names: set[str] = set()
    for entries in topic_hubs_from_schema(schema).values():
        for entry in entries:
            name = _hub_name(entry)
            if name:
                names.add(name)
    return names


def note_types_from_schema(schema: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Built-in note types overlaid with any custom types from an on-disk schema.

    Built-ins always win and are always present; the schema-change guard prevents a
    loaded schema from dropping them. Custom types declared in ``schema["note_types"]``
    (or ``core_properties.type.allowed``) are added on top.
    """
    result: dict[str, dict[str, Any]] = {
        name: dict(spec) for name, spec in NOTE_TYPES.items()
    }
    if isinstance(schema, dict):
        extra = schema.get("note_types")
        if isinstance(extra, dict):
            for name, spec in extra.items():
                if isinstance(name, str) and name and name not in result:
                    result[name] = dict(spec) if isinstance(spec, dict) else {}
        core = schema.get("core_properties")
        type_spec = core.get("type") if isinstance(core, dict) else None
        for value in type_spec.get("allowed", []) if isinstance(type_spec, dict) else []:
            if isinstance(value, str) and value and value not in result:
                result[value] = {}
    return result


def allowed_note_types_from_schema(schema: dict[str, Any] | None) -> set[str]:
    """Return the set of allowed note-type names for a loaded schema."""
    return set(note_types_from_schema(schema))


def load_schema(vault_root: Path) -> dict[str, Any]:
    """Load the on-disk vault schema.json, or {} when missing or malformed."""
    path = vault_root / paths_for(vault_root).agent_dir / "schema.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def allowed_note_types(vault_root: Path) -> set[str]:
    """Allowed note-type names for a vault: built-ins plus on-disk custom types."""
    return allowed_note_types_from_schema(load_schema(vault_root))


def allowed_controlled_values_from_schema(
    schema: dict[str, Any] | None, property_name: str
) -> list[str]:
    """Built-in allowed values for a controlled property plus schema additions."""
    values = list(COMMON_PROPERTIES.get(property_name, {}).get("allowed", []))
    if isinstance(schema, dict):
        core = schema.get("core_properties")
        prop = core.get(property_name) if isinstance(core, dict) else None
        for value in prop.get("allowed", []) if isinstance(prop, dict) else []:
            if isinstance(value, str) and value not in values:
                values.append(value)
    return values


def accepted_properties_for(note_type: str | None = None) -> set[str]:
    """Return schema-approved frontmatter properties for a note type."""
    del note_type
    return set(CORE_PROPERTY_ORDER)


def ordered_properties_for(note_type: str | None = None) -> tuple[str, ...]:
    """Return stable canonical frontmatter order for a note type."""
    del note_type
    return CORE_PROPERTY_ORDER


def default_schema_json(extra_domains: list[str] | None = None) -> str:
    return json.dumps(default_schema(extra_domains), indent=2) + "\n"


def schema_markdown(extra_domains: list[str] | None = None) -> str:
    lines = [
        "---",
        "type: system",
        "status: active",
        "domain:",
        "parent:",
        "related: []",
        "cover:",
        "source_kind:",
        "capture_type:",
        "---",
        "",
        "# Obsidian Vault Metadata Schema",
        "",
        "Human-readable mirror of `99 System/0.01 agent/schema.json`.",
        "",
        "This vault uses a small, controlled metadata schema intended to support Obsidian Bases, dashboards, retrieval, and agent-based maintenance.",
        "",
        "## Core Properties",
        "",
        "Every managed note may use these eight properties:",
        "",
        "```yaml",
        "---",
        "type:",
        "status:",
        "domain:",
        "parent:",
        "related:",
        "cover:",
        "source_kind:",
        "capture_type:",
        "---",
        "```",
        "",
        "## Note Types",
        "",
    ]
    for note_type, spec in NOTE_TYPES.items():
        lines.append(f"- `{note_type}`: {spec['description']} Preferred folder: `{spec['folder']}`.")
    extra = new_domains(extra_domains)
    lines.extend(["", "## Common Properties", ""])
    for prop, spec in CORE_PROPERTIES.items():
        allowed = spec.get("allowed")
        if prop == "domain" and allowed:
            allowed = list(allowed) + extra
        suffix = f" Allowed: {', '.join(f'`{value}`' for value in allowed)}." if allowed else ""
        lines.append(f"- `{prop}`: {spec['type']}.{suffix}")
    lines.extend(
        [
            "",
            "## Design Rules",
            "",
            "- Keep the schema sparse.",
            "- Use controlled values only for `type`, `status`, `domain`, `source_kind`, and `capture_type`.",
            "- Do not use `domain` for every topic or interest.",
            "- Represent specific topics as notes.",
            "- Use `parent` for hierarchy.",
            "- Use `related` for cross-links.",
            "- Avoid adding new properties unless the need recurs across many notes.",
            "- Preserve compatibility with plain Markdown and Obsidian-native workflows.",
        ]
    )
    return "\n".join(lines) + "\n"


def property_values_markdown(extra_domains: list[str] | None = None) -> str:
    lines = [
        "---",
        "type: system",
        "status: active",
        "domain: meta",
        "parent:",
        "related: []",
        "cover:",
        "source_kind:",
        "capture_type:",
        "---",
        "",
        "# Obsidian Vault Metadata Schema",
        "",
        "This controlled vocabulary is intentionally broad enough to avoid frequent schema changes while staying small enough for agents to use consistently.",
        "",
        "## Core Schema",
        "",
        "```yaml",
        "---",
        "type:",
        "status:",
        "domain:",
        "parent:",
        "related:",
        "cover:",
        "source_kind:",
        "capture_type:",
        "---",
        "```",
        "",
        "## type",
        "",
        "Defines what kind of object the note represents.",
        "",
    ]
    for note_type, spec in NOTE_TYPES.items():
        lines.append(f"- `{note_type}`: {spec['description']}")
    lines.extend(["", "## status", "", "Defines lifecycle state.", ""])
    for status, definition in STATUS_DEFINITIONS.items():
        lines.append(f"- `{status}`: {definition}")
    lines.extend(
        [
            "",
            "## domain",
            "",
            "Defines broad life area. These should remain relatively stable over time.",
            "",
        ]
    )
    for domain, definition in DOMAIN_DEFINITIONS.items():
        lines.append(f"- `{domain}`: {definition}")
    for domain in new_domains(extra_domains):
        lines.append(f"- `{domain}`: User-defined domain.")
    lines.extend(
        [
            "",
            "## source_kind",
            "",
            "Defines the medium or publication form for source notes. Leave blank when the note is not a source or the kind is unclear.",
            "",
        ]
    )
    for source_kind in CORE_PROPERTIES["source_kind"]["allowed"]:
        if source_kind:
            lines.append(f"- `{source_kind}`")
    lines.extend(
        [
            "",
            "## capture_type",
            "",
            "Defines how the note entered the vault. Optional for all notes.",
            "",
        ]
    )
    for capture_type in CORE_PROPERTIES["capture_type"]["allowed"]:
        if capture_type:
            lines.append(f"- `{capture_type}`")
    lines.extend(
        [
            "",
            "## parent",
            "",
            "- Zero or one value.",
            "- Should reference another note.",
            "- Represents primary organizational context.",
            "- Used for hierarchy and navigation.",
            "",
            "Examples:",
            "",
            "```yaml",
            "parent: Topic Name",
            'parent: "[[Topic Name]]"',
            "```",
            "",
            "## related",
            "",
            "- Zero or many values.",
            "- References other notes.",
            "- Represents meaningful relationships that are not hierarchical.",
            "",
            "Example:",
            "",
            "```yaml",
            "related:",
            "  - Topic A",
            "  - Topic B",
            "  - Person C",
            "```",
            "",
            "## cover",
            "",
            "Accepted formats:",
            "",
            "```yaml",
            "cover: image.jpg",
            "cover: assets/images/image.jpg",
            'cover: "[[image.jpg]]"',
            "cover: https://example.com/image.jpg",
            "```",
            "",
            "## Default Empty Template",
            "",
            "```yaml",
            "---",
            "type:",
            "status:",
            "domain:",
            "parent:",
            "related:",
            "cover:",
            "source_kind:",
            "capture_type:",
            "---",
            "```",
            "",
            "## Example Filled Template",
            "",
            "```yaml",
            "---",
            "type: source",
            "status: active",
            "domain: academic",
            'parent: "[[Topic Hub]]"',
            "related:",
            '  - "[[Related Project]]"',
            'cover: "[[cover-image.jpg]]"',
            "source_kind: article",
            "capture_type: imported",
            "---",
            "```",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def folder_norms_markdown() -> str:
    lines = [
        "---",
        "type: system",
        "status: active",
        "domain: meta",
        "parent:",
        "related: []",
        "cover:",
        "source_kind:",
        "capture_type:",
        "---",
        "",
        "# Folder Norms",
        "",
        "Dashboards are the primary navigation layer and folders are secondary storage. Inbox sorting may move only high-confidence, warning-free notes through validated proposals.",
        "",
    ]
    for note_type, spec in NOTE_TYPES.items():
        lines.append(f"- `{spec['folder']}`: preferred home for `{note_type}` notes.")
    lines.extend(
        [
            "",
            "## Recommended Topic Hubs",
            "",
            "These are not property values. They are ordinary notes that should exist as navigation hubs and commonly appear as `parent` values.",
            "",
        ]
    )
    lines.extend(f"- {hub}" for hub in RECOMMENDED_TOPIC_HUBS)
    lines.extend(["", "## Agent Rules", ""])
    lines.extend(f"{index}. {rule}" for index, rule in enumerate(AGENT_RULES, start=1))
    return "\n".join(lines) + "\n"


def topic_hubs_markdown(topic_hubs: dict[str, Any] | None = None) -> str:
    """Render the per-domain approved topic-hub registry as a human-readable system file."""
    registry = topic_hubs if isinstance(topic_hubs, dict) else default_topic_hubs()
    lines = [
        "---",
        "type: system",
        "status: active",
        "domain: meta",
        "parent:",
        "related: []",
        "cover:",
        "source_kind:",
        "capture_type:",
        "---",
        "",
        "# Topic Hubs",
        "",
        "Approved topic hubs are ordinary navigation notes (usually `type: index`) that notes "
        "point to through the `parent` property. They are the vault's organizational scheme: "
        "domain dashboards render one section per hub.",
        "",
        "Hubs are surfaced from the vault's own notes and added only through reviewed "
        "`propose-topic-hubs` proposals. The agent may set `parent` only to an approved hub "
        "below; anything else is blocked for review.",
        "",
    ]
    for domain in DOMAIN_DEFINITIONS:
        entries = registry.get(domain, []) if isinstance(registry, dict) else []
        lines.append(f"## {domain}")
        lines.append("")
        if not entries:
            lines.append("- _No hubs yet._")
        else:
            for entry in entries:
                name = _hub_name(entry)
                if not name:
                    continue
                description = entry.get("description", "") if isinstance(entry, dict) else ""
                lines.append(f"- `{name}`" + (f" - {description}" if description else ""))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


TEMPLATE_BODIES = {
    "project": """# Project Name

> [!abstract] Outcome
> Define the finished state in one sentence. A project has a temporary arc and a concrete result.

## Summary

Briefly explain why this project exists, who it serves, and what changes when it is done.

## Status Board

| Area | Current State | Next Review |
| --- | --- | --- |
| Outcome |  |  |
| Scope |  |  |
| Risk |  |  |

## Milestones

- [ ] Define outcome
- [ ] Identify constraints
- [ ] Complete next deliverable

## Decisions

> [!tip] Decision Log
> Record dated decisions here so the agent can preserve project history instead of re-litigating old choices.

## Open Questions

- 

## Notes

""",
    "source": """# Source Title

> [!info] Source Snapshot
> Capture what this source is, why it matters, and whether it should be cited, summarized, or ignored.

## Summary

One to three sentences describing the source's main contribution.

## Citation

| Field | Value |
| --- | --- |
| Creator |  |
| Date |  |
| Publisher / Venue |  |
| URL / DOI |  |

## Key Claims

- 

## Evidence And Excerpts

> [!quote] Useful Passage
> Add short excerpts or paraphrases with page, timestamp, or section references.

## Connections

- Parent topic:
- Related notes:

## Notes

""",
    "person": """# Person Name

> [!info] Relationship Context
> Capture who this person is in the vault, why they matter, and what context should be remembered.

## Summary

Brief description of the person and current relevance.

## Contact And Context

| Field | Value |
| --- | --- |
| Role / Relationship |  |
| Organization |  |
| Contact |  |
| Last Interaction |  |

## Current Threads

- [ ] 

## Notes From Interactions

> [!note] Interaction Notes
> Use dated bullets for meetings, calls, emails, or personal context.

## Related

- 

## Notes

""",
    "organization": """# Organization Name

> [!abstract] Organization Snapshot
> Describe what this organization is, what it does, and why it appears in the vault.

## Summary

Brief overview of the institution, company, group, lab, or department.

## Profile

| Field | Value |
| --- | --- |
| Kind |  |
| Website |  |
| People |  |
| Relationship |  |

## Active Threads

- [ ] 

## Key Notes

- 

## Related People And Projects

- 

## Notes

""",
    "meeting": """# Meeting Title

> [!todo] Meeting Outcome
> State what this conversation should decide, clarify, or move forward.

## Summary

Short recap of what happened and what changed.

## Details

| Field | Value |
| --- | --- |
| Date |  |
| Attendees |  |
| Context |  |

## Agenda

- 

## Notes

- 

## Decisions

- 

## Action Items

- [ ] 

""",
    "task": """# Task

> [!todo] Next Action
> Write the concrete next action so it can be done without rereading the whole note.

## Summary

What needs to happen and why.

## Checklist

- [ ] 

## Context

| Field | Value |
| --- | --- |
| Due / Review |  |
| Waiting On |  |
| Project / Parent |  |

## Notes

- 

## Done Criteria

- 

""",
    "note": """# Note Title

> [!note] Core Idea
> State the durable idea, reference point, or observation this note should preserve.

## Summary

One to three sentences that let an agent understand the note without rereading everything.

## Main Points

- 

## Context

| Field | Value |
| --- | --- |
| Parent topic |  |
| Useful for |  |
| Confidence |  |

## Links

- Parent:
- Related:

## Notes

""",
    "index": """# Index Title

> [!abstract] Navigation Hub
> This note is a map. Keep it useful for humans and agents trying to decide where to look next.

## Summary

What this hub covers and when to use it.

## Start Here

- [[ ]]

## Key Notes

| Note | Why It Matters |
| --- | --- |
|  |  |

## Active Areas

- [ ] 

## Related Hubs

- 

## Maintenance Notes

> [!tip] Agent Maintenance
> Prefer links to existing notes. Create topic notes when a recurring theme needs a home.

## Notes

""",
    "daily": """# Daily Note

> [!info] Daily Frame
> Capture the day as lived: priorities, events, notes, and loose ends.

## Summary

One to three sentences about the day.

## Today

- [ ] 

## Schedule / Events

| Time | Event | Notes |
| --- | --- | --- |
|  |  |  |

## Log

- 

## Notes And Ideas

- 

## Carry Forward

- [ ] 

""",
    "template": """# Template Name

> [!info] Template Purpose
> Explain what this template is for and when an agent should apply it.

## Summary

Briefly describe the reusable structure.

## YAML

```yaml
---
type:
status:
domain:
parent:
related: []
cover:
source_kind:
capture_type:
---
```

## Body Pattern

- 

## Agent Instructions

- Preserve user-authored content.
- Keep frontmatter sparse.
- Add links and headings only when they improve navigation.

## Notes

""",
    "system": """# System Note

> [!warning] System Surface
> This note supports vault infrastructure, workflows, schemas, generated files, or agent memory. Edit deliberately.

## Summary

What this system note controls or documents.

## Purpose

- 

## Managed By

| Field | Value |
| --- | --- |
| Owner | vault-agent |
| Source of truth |  |
| Generated? |  |

## Operating Rules

- Preserve user-authored notes.
- Keep metadata sparse.
- Validate before applying changes.

## Change Log

- 

## Notes

""",
}


def template_for(note_type: str, description: str) -> str:
    body = TEMPLATE_BODIES[note_type]
    return f"""---
type: {note_type}
status:
domain:
parent:
related: []
cover:
source_kind:
capture_type:
---

{body.rstrip()}

<!-- {description} -->
"""


def starter_templates() -> dict[str, str]:
    return {
        f"99 System/0.02 templates/note-types/{note_type}.md": template_for(
            note_type, spec["description"]
        )
        for note_type, spec in NOTE_TYPES.items()
    }


def index_base_templates() -> dict[str, str]:
    return {
        "99 System/0.02 templates/indexes/domain-index.md": _domain_index_template(),
        "99 System/0.02 templates/indexes/parent-dashboard.md": _parent_dashboard_template(),
        "99 System/0.02 templates/indexes/object-collections.md": _object_collections_template(),
        "99 System/0.02 templates/indexes/cover-gallery.md": _cover_gallery_template(),
    }


def _index_template_frontmatter() -> str:
    return """---
type: index
status:
domain:
parent:
related: []
cover:
source_kind:
capture_type:
---
"""


def _domain_index_template() -> str:
    return _index_template_frontmatter() + """
# Domain Index

> [!abstract] Domain Dashboard
> Set this note's `domain` property to one of the controlled values. The embedded Bases below use `this.domain`, so the same template works for `academic`, `work`, `craft`, `technology`, and the other broad life areas.

## Summary

This dashboard gathers notes in the same broad life area without adding new metadata.

## Highlights

- 

## Domain Cards

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'domain == this.domain'
    - 'type != "system"'
views:
  - type: cards
    name: "Cards"
    order:
      - file.name
      - cover
      - type
      - status
      - parent
  - type: table
    name: "Table"
    groupBy:
      property: type
      direction: ASC
    order:
      - file.name
      - type
      - status
      - parent
      - related
```

## Active Work

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'domain == this.domain'
    - 'status == "active"'
views:
  - type: table
    name: "Active"
    groupBy:
      property: type
      direction: ASC
    order:
      - file.name
      - type
      - parent
      - related
      - file.mtime
```

## Notes

"""


def _parent_dashboard_template() -> str:
    return _index_template_frontmatter() + """
# Parent Dashboard

> [!abstract] Topic Or Project Dashboard
> Use this for topic hubs and project dashboards. Child notes should point their `parent` property at this note, preferably with a wikilink.

## Summary

This dashboard gathers notes whose `parent` is this hub.

## Start Here

- 

## Child Notes

```base
filters:
  or:
    - 'parent == this.file.asLink()'
    - 'parent == this.file.name'
    - 'parent == this.file.basename'
views:
  - type: cards
    name: "Cards"
    order:
      - file.name
      - cover
      - type
      - status
      - domain
  - type: table
    name: "Table"
    groupBy:
      property: type
      direction: ASC
    order:
      - file.name
      - type
      - status
      - domain
      - related
      - file.mtime
```

## Open Items

```base
filters:
  and:
    - 'type == "task"'
    - 'status == "active"'
    - or:
        - 'parent == this.file.asLink()'
        - 'parent == this.file.name'
        - 'parent == this.file.basename'
views:
  - type: table
    name: "Active Tasks"
    order:
      - file.name
      - status
      - domain
      - related
```

## Notes

"""


def _object_collections_template() -> str:
    return _index_template_frontmatter() + """
# Object Collections

> [!abstract] Type-Filtered Collections
> Use this as a vault object directory. Each view filters by `type` only, so it remains compatible with the sparse schema.

## Summary

Browse object collections without introducing new metadata.

## Projects

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'type == "project"'
views:
  - type: cards
    name: "Project Cards"
    order:
      - file.name
      - cover
      - status
      - domain
      - parent
  - type: table
    name: "Project Table"
    groupBy:
      property: status
      direction: ASC
    order:
      - file.name
      - status
      - domain
      - parent
      - related
```

## Sources

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'type == "source"'
views:
  - type: table
    name: "Sources"
    groupBy:
      property: domain
      direction: ASC
    order:
      - file.name
      - status
      - domain
      - parent
      - related
```

## People And Organizations

```base
filters:
  or:
    - 'type == "person"'
    - 'type == "organization"'
views:
  - type: cards
    name: "Directory Cards"
    order:
      - file.name
      - cover
      - type
      - domain
      - related
  - type: table
    name: "Directory Table"
    groupBy:
      property: type
      direction: ASC
    order:
      - file.name
      - type
      - status
      - domain
      - parent
```

## Meetings And Tasks

```base
filters:
  or:
    - 'type == "meeting"'
    - 'type == "task"'
views:
  - type: table
    name: "Action Surface"
    groupBy:
      property: status
      direction: ASC
    order:
      - file.name
      - type
      - status
      - domain
      - parent
      - related
```

## Notes

"""


def _cover_gallery_template() -> str:
    return _index_template_frontmatter() + """
# Cover Gallery

> [!abstract] Visual Index
> Use this when notes have useful `cover` images. Cards are the primary view; the table view helps compare metadata.

## Summary

Visual browsing surface for notes with cover images.

## Gallery

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'cover != ""'
    - 'type != "system"'
views:
  - type: cards
    name: "Gallery"
    groupBy:
      property: domain
      direction: ASC
    order:
      - file.name
      - cover
      - type
      - status
      - parent
  - type: table
    name: "Compare"
    groupBy:
      property: type
      direction: ASC
    order:
      - file.name
      - cover
      - type
      - status
      - domain
      - parent
      - related
```

## Missing Covers To Consider

```base
filters:
  and:
    - 'file.ext == "md"'
    - 'cover == ""'
    - 'type != "system"'
views:
  - type: table
    name: "No Cover"
    order:
      - file.name
      - type
      - status
      - domain
      - parent
```

## Notes

"""
