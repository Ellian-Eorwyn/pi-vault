"""Suggest a folder layout from an existing vault before init writes defaults.

This reads a deterministic vault scan and proposes how the user's existing
folders map onto pi-vault's fixed content roles (people, work, sources, ...).
Folders that don't match a built-in role become user-defined **domains**: each is
mapped to its own top-level folder that notes route into by their ``domain``
value. The suggestion is rendered as a human-editable YAML outline; the edited
outline is parsed back and validated via ``build_paths``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import (
    DEFAULT_CONTENT_DIRS,
    DEFAULT_DASHBOARDS_DIR,
    DEFAULT_INBOX_DIR,
    DEFAULT_SYSTEM_DIR,
    BOOTSTRAP_DIR,
    CONTENT_ROLE_DOMAINS,
    VaultPaths,
    build_paths,
)
from .scanner import ScanResult


# Top-level roles that can be mapped to an observed folder, each with the child
# roles that live underneath them in the fixed taxonomy.
TOP_LEVEL_CHILDREN: dict[str, tuple[str, ...]] = {
    "people": ("contacts", "authors"),
    "organizations": (),
    "work": (),
    "administrative": ("health", "home", "finance", "travel", "administrative_general"),
    "thoughts": (),
    "sources": (),
}

# Folder-name keywords that hint at a role. Matched case-insensitively against
# the observed top-level folder name.
ROLE_NAME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "people": ("people", "contacts", "person", "persons"),
    "organizations": ("organization", "organizations", "orgs", "org", "companies", "company"),
    "work": ("work", "projects", "project"),
    "administrative": ("admin", "administrative", "administration"),
    "thoughts": (
        "thoughts",
        "notes",
        "journal",
        "ideas",
        "reflections",
        "zettel",
        "fleeting",
        "daily",
    ),
    "sources": (
        "sources",
        "source",
        "reading",
        "references",
        "reference",
        "library",
        "books",
        "literature",
        "clippings",
    ),
}

# Dominant note type within a folder -> role, used when the name is unclear.
TYPE_ROLE: dict[str, str] = {
    "person": "people",
    "organization": "organizations",
    "source": "sources",
}


@dataclass
class LayoutSuggestion:
    system_dir: Path
    inbox_dir: Path
    dashboards_dir: Path
    content_dirs: dict[str, Path]
    # domain value -> folder that notes with that domain route into
    domain_folders: dict[str, Path] = field(default_factory=dict)
    # role -> short human explanation of why the folder was mapped here
    reasons: dict[str, str] = field(default_factory=dict)
    # domain -> short human explanation of the proposed domain folder
    domain_reasons: dict[str, str] = field(default_factory=dict)


def suggest_layout(scan: ScanResult, paths: VaultPaths | None = None) -> LayoutSuggestion:
    """Propose a folder layout from observed folders and note metadata."""

    system_dir = paths.system_dir if paths else DEFAULT_SYSTEM_DIR
    inbox_dir = paths.inbox_dir if paths else DEFAULT_INBOX_DIR
    dashboards_dir = paths.dashboards_dir if paths else DEFAULT_DASHBOARDS_DIR
    content_dirs = dict(paths.content_dirs) if paths else dict(DEFAULT_CONTENT_DIRS)

    observed = _observed_top_level(scan)
    reserved_names = {
        system_dir.parts[0],
        inbox_dir.parts[0],
        dashboards_dir.parts[0],
        BOOTSTRAP_DIR.as_posix(),
    }

    claimed: dict[str, str] = {}  # role -> folder name
    reasons: dict[str, str] = {}
    domain_folders: dict[str, Path] = {}
    domain_reasons: dict[str, str] = {}

    # Sort by note count (desc) then name so the busiest folder wins a contested role.
    for name in sorted(observed, key=lambda n: (-observed[n]["count"], n.lower())):
        if name in reserved_names:
            continue  # already the system/inbox/dashboards/bootstrap folder
        role, reason = _classify_folder(name, observed[name])
        if role and role not in claimed:
            claimed[role] = name
            reasons[role] = reason
            continue
        # No built-in role: make this a user-defined, routable domain folder.
        domain = _unique_domain_slug(name, domain_folders)
        domain_folders[domain] = Path(name)
        if role:
            domain_reasons[domain] = (
                f"looks like '{role}' but that role is already mapped to "
                f"'{claimed[role]}'; kept as the '{domain}' domain folder"
            )
        else:
            domain_reasons[domain] = (
                f"no built-in role matched; notes with domain '{domain}' route here"
            )

    # Apply claimed top-level roles, rebuilding child paths under the new parent.
    for role, folder_name in claimed.items():
        _remap_role(content_dirs, role, Path(folder_name))

    return LayoutSuggestion(
        system_dir=system_dir,
        inbox_dir=inbox_dir,
        dashboards_dir=dashboards_dir,
        content_dirs=content_dirs,
        domain_folders=domain_folders,
        reasons=reasons,
        domain_reasons=domain_reasons,
    )


def _observed_top_level(scan: ScanResult) -> dict[str, dict[str, Any]]:
    """Aggregate notes by their top-level folder."""

    summary: dict[str, dict[str, Any]] = {}
    for entry in scan.entries:
        parts = Path(entry["path"]).parts
        if len(parts) < 2:
            continue  # note sits at the vault root, not in a folder
        top = parts[0]
        bucket = summary.setdefault(top, {"count": 0, "types": Counter(), "domains": Counter()})
        bucket["count"] += 1
        note_type = (entry.get("type") or "").strip()
        if note_type:
            bucket["types"][note_type] += 1
        domain = (entry.get("domain") or "").strip()
        if domain:
            bucket["domains"][domain] += 1
    return summary


def _classify_folder(name: str, info: dict[str, Any]) -> tuple[str | None, str]:
    lowered = name.lower()
    for role, keywords in ROLE_NAME_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return role, f"folder name '{name}' matches the '{role}' role"

    types: Counter = info["types"]
    if types:
        dominant_type, type_count = types.most_common(1)[0]
        if type_count * 2 >= info["count"]:  # at least half the notes share a type
            if dominant_type == "project":
                domains: Counter = info["domains"]
                if domains and domains.most_common(1)[0][0] == "work":
                    return "work", f"'{name}' is mostly work projects"
                return "thoughts", f"'{name}' is mostly projects without a work domain"
            role = TYPE_ROLE.get(dominant_type)
            if role:
                return role, f"'{name}' is mostly '{dominant_type}' notes"
    return None, ""


def _domain_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "domain"


def _unique_domain_slug(name: str, existing: dict[str, Path]) -> str:
    base = _domain_slug(name)
    # Avoid colliding with content-role domains (work/health/...) or another folder.
    candidate = base
    suffix = 2
    while candidate in CONTENT_ROLE_DOMAINS or candidate in existing:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _remap_role(content_dirs: dict[str, Path], role: str, new_path: Path) -> None:
    """Point a top-level role (and its children) at an observed folder."""

    old_parent = DEFAULT_CONTENT_DIRS[role]
    content_dirs[role] = new_path
    for child in TOP_LEVEL_CHILDREN.get(role, ()):
        default_child = DEFAULT_CONTENT_DIRS[child]
        relative = default_child.relative_to(old_parent)
        content_dirs[child] = new_path / relative


def render_layout_outline(suggestion: LayoutSuggestion) -> str:
    """Render a human-editable YAML outline with explanatory comments."""

    lines = [
        "# pi-vault folder layout suggestion",
        "#",
        "# This is a proposal based on your existing folders and notes. Edit the paths",
        "# below to match the structure you want, then run `vault-agent apply-layout`.",
        "# Nothing has been created yet.",
        "#",
        "# - content_dirs map your folders onto pi-vault's built-in roles (people,",
        "#   organizations, work, sources, ...). Notes route into them by note type/domain.",
        "# - domain_folders are your own folders. Each is a routable domain: a note whose",
        "#   `domain` matches the key is filed into that folder and gets its own dashboard.",
        "#   Add, rename, or remove entries freely (keys must be lowercase slugs).",
        "",
        f"system_dir: {suggestion.system_dir.as_posix()}",
        f"inbox_dir: {suggestion.inbox_dir.as_posix()}",
        f"dashboards_dir: {suggestion.dashboards_dir.as_posix()}",
        "",
        "content_dirs:",
    ]
    for key in DEFAULT_CONTENT_DIRS:
        value = suggestion.content_dirs[key].as_posix()
        reason = suggestion.reasons.get(key)
        comment = f"  # {reason}" if reason else "  # default (no matching folder found)"
        lines.append(f'  {key}: "{value}"{comment}')

    lines.append("")
    if suggestion.domain_folders:
        lines.append("domain_folders:")
        for domain, folder in suggestion.domain_folders.items():
            reason = suggestion.domain_reasons.get(domain, "user-defined domain folder")
            lines.append(f'  {domain}: "{folder.as_posix()}"  # {reason}')
    else:
        lines.append(
            "domain_folders: {}  # add `slug: \"Folder\"` to make your own routable folders"
        )

    lines.extend(
        [
            "",
            "# custom_folders: an arbitrary structure the MODEL sorts notes into, using each",
            "# description as a hint. Only active when routing.mode is 'custom' below.",
            "custom_folders: []",
            "#   - path: Areas/Health",
            "#     description: fitness, medical, nutrition",
            "#   - path: Resources/Books",
            "#     description: book notes and highlights",
            "",
            "# routing.mode 'deterministic' (default) sorts by note type/domain. Set it to",
            "# 'custom' to let the model sort notes into custom_folders during normal",
            "# processing; 'fallback: deterministic' still applies when the model is unsure.",
            "routing:",
            "  mode: deterministic",
            "  fallback: deterministic",
        ]
    )

    return "\n".join(lines) + "\n"


def parse_layout_outline(text: str) -> VaultPaths:
    """Parse an edited outline and validate it into VaultPaths via build_paths."""

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid layout outline: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("layout outline must be a YAML mapping")

    content_dirs = data.get("content_dirs")
    if content_dirs is not None and not isinstance(content_dirs, dict):
        raise ValueError("content_dirs must be a mapping of role to folder path")

    return build_paths(
        data.get("system_dir", DEFAULT_SYSTEM_DIR.as_posix()),
        data.get("inbox_dir", DEFAULT_INBOX_DIR.as_posix()),
        data.get("dashboards_dir", DEFAULT_DASHBOARDS_DIR.as_posix()),
        content_dirs,
        data.get("domain_folders"),
        data.get("custom_folders"),
    )


def parse_layout_routing(text: str) -> dict[str, str] | None:
    """Extract the optional routing block from an edited outline."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    routing = data.get("routing")
    if not isinstance(routing, dict):
        return None
    result: dict[str, str] = {}
    for key in ("mode", "fallback"):
        value = routing.get(key)
        if isinstance(value, str) and value:
            result[key] = value
    return result or None
