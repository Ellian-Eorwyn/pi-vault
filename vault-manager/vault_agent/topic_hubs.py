"""Surface candidate topic hubs from vault notes and match notes to approved hubs.

Topic hubs are the vault's organizational scheme: approved navigation notes that
ordinary notes point to via the ``parent`` property. They live in the approved schema
registry (``schema.json`` ``topic_hubs``) and are surfaced from the vault's own folder/
content structure, then reviewed and approved. Folders are treated as *information* the
agent uses to categorize, not as a dependency — the resulting dashboards filter on the
``parent`` property, so notes can be re-foldered freely.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .base_hierarchy import _base_block, _dashboard_frontmatter, _safe_filename
from .schema import (
    DOMAIN_DEFINITIONS,
    approved_hubs_for,
    default_topic_hubs,
    topic_hubs_markdown,
)

_NUMERIC_PREFIX = re.compile(r"^[0-9]+(?:\.[0-9]+)*[\s_-]*")
_SKIP_TYPES = {"index", "system", "template"}


def clean_segment(segment: str) -> str:
    """Drop a leading numeric/ordinal prefix from a folder name (``2.02 Therapy`` -> ``Therapy``)."""
    return _NUMERIC_PREFIX.sub("", segment).strip()


def candidate_hub_for_path(path: str) -> str:
    """Derive a candidate hub label from a note path.

    Uses the second folder level (the cluster under a top-level area folder) when present,
    otherwise the first folder, so ``02 Journal/2.02 Therapy/x.md`` -> ``Therapy`` and
    ``06 People/Jane.md`` -> ``People``.
    """
    folders = Path(path).parts[:-1]
    if not folders:
        return ""
    index = 1 if len(folders) >= 2 else 0
    return clean_segment(folders[index])


def folder_hub_match(path: str, approved_hubs: list[str]) -> str:
    """Return the approved hub whose name matches this note's folder cluster, else ""."""
    candidate = candidate_hub_for_path(path).lower()
    if not candidate:
        return ""
    for hub in approved_hubs:
        if hub.lower() == candidate:
            return hub
    return ""


def _domain_of(entry: dict[str, Any]) -> str:
    domain = entry.get("domain")
    return domain if isinstance(domain, str) else ""


def cluster_candidate_hubs(
    entries: list[dict[str, Any]], domain: str, *, min_cluster: int = 3
) -> list[dict[str, Any]]:
    """Cluster a domain's notes into candidate hubs by folder, keeping clusters >= min_cluster."""
    clusters: dict[str, list[str]] = {}
    for entry in entries:
        if _domain_of(entry) != domain:
            continue
        if entry.get("type") in _SKIP_TYPES or entry.get("frontmatter_error"):
            continue
        name = candidate_hub_for_path(entry.get("path", ""))
        if not name:
            continue
        clusters.setdefault(name, []).append(entry.get("path", ""))
    hubs: list[dict[str, Any]] = []
    for name, members in sorted(clusters.items(), key=lambda kv: (-len(kv[1]), kv[0].lower())):
        if len(members) < min_cluster:
            continue
        hubs.append({"name": name, "domain": domain, "count": len(members)})
    return hubs


def _hub_note_content(hub: str, domain: str) -> str:
    """A minimal hub/index note that lists notes pointing at it via `parent`."""
    frontmatter = _dashboard_frontmatter(domain=domain, parent="")
    block = _base_block(
        filters=['file.ext == "md"', f'domain == "{domain}"', f'parent == "[[{hub}]]"'],
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
                "order": ["file.name", "type", "status", "related", "file.mtime"],
            },
        ],
    )
    return f"""{frontmatter}

# {hub}

> [!abstract] {hub}
> Topic hub for the `{domain}` domain. Notes join this hub through `parent: "[[{hub}]]"`.

## Notes

{block}
"""


def build_topic_hubs_proposal(
    *,
    entries: list[dict[str, Any]],
    schema: dict[str, Any],
    domains: list[str] | None = None,
    min_cluster: int = 3,
    hub_folder: str = "Indexes/Topics",
    overwrite_hub_notes: bool = False,
    llm_overrides: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]], list[str]]:
    """Build a schema-change proposal that adds surfaced hubs to the approved registry.

    Returns (proposal, new_registry, added_hub_labels). Hubs already present in the
    registry are skipped. Optional ``llm_overrides`` maps domain -> refined hub names.
    """
    registry = deepcopy(schema.get("topic_hubs"))
    if not isinstance(registry, dict) or not registry:
        registry = default_topic_hubs()
    target_domains = domains or [
        d for d in DOMAIN_DEFINITIONS if any(_domain_of(e) == d for e in entries)
    ]

    added: list[tuple[str, str]] = []
    for domain in target_domains:
        existing = {name.lower() for name in approved_hubs_for(domain, {"topic_hubs": registry})}
        if llm_overrides and domain in llm_overrides:
            names = [name.strip() for name in llm_overrides[domain] if name.strip()]
        else:
            names = [hub["name"] for hub in cluster_candidate_hubs(entries, domain, min_cluster=min_cluster)]
        registry.setdefault(domain, [])
        for name in names:
            if name.lower() in existing:
                continue
            existing.add(name.lower())
            registry[domain].append({"name": name, "description": f"Surfaced {domain} hub."})
            added.append((domain, name))

    schema_out = deepcopy(schema)
    schema_out["topic_hubs"] = registry
    operations: list[dict[str, Any]] = [
        {
            "op": "write_file",
            "path": "00 System/0.01 agent/schema.json",
            "if_exists": "overwrite",
            "content": json.dumps(schema_out, indent=2) + "\n",
        },
        {
            "op": "write_file",
            "path": "00 System/0.02 templates/0.023 topic hubs.md",
            "if_exists": "overwrite",
            "content": topic_hubs_markdown(registry),
        },
    ]
    for domain, name in added:
        operations.append(
            {
                "op": "write_file",
                "path": f"{hub_folder}/{_safe_filename(name)}.md",
                "if_exists": "overwrite" if overwrite_hub_notes else "fail",
                "content": _hub_note_content(name, domain),
            }
        )

    proposal = {
        "id": "topic-hubs",
        "title": "Add surfaced topic hubs to the approved registry",
        "kind": "schema-change",
        "status": "pending",
        "summary": (
            f"Surface {len(added)} topic hub(s) from vault content and register them as the "
            "approved organizational scheme."
        ),
        "operations": operations,
    }
    return proposal, registry, [f"{domain}: {name}" for domain, name in added]
