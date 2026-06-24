"""Suggest a folder layout from an existing vault before init writes defaults.

This reads a deterministic vault scan and proposes how the user's existing
folders map onto pi-vault's fixed content roles (people, work, sources, ...),
keeping any unmatched top-level folders as user-defined "extra" folders that the
agent leaves unmanaged. The suggestion is rendered as a human-editable YAML
outline; the edited outline is parsed back and validated via ``build_paths``.
"""

from __future__ import annotations

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
    extra_folders: list[Path] = field(default_factory=list)
    # role -> short human explanation of why the folder was mapped here
    reasons: dict[str, str] = field(default_factory=dict)
    extra_reasons: dict[str, str] = field(default_factory=dict)


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
    extra_folders: list[Path] = []
    extra_reasons: dict[str, str] = {}

    # Sort by note count (desc) then name so the busiest folder wins a contested role.
    for name in sorted(observed, key=lambda n: (-observed[n]["count"], n.lower())):
        if name in reserved_names:
            continue  # already the system/inbox/dashboards/bootstrap folder
        role, reason = _classify_folder(name, observed[name])
        if role and role not in claimed:
            claimed[role] = name
            reasons[role] = reason
        else:
            extra_folders.append(Path(name))
            if role:
                extra_reasons[name] = (
                    f"looks like '{role}' but that role is already mapped to "
                    f"'{claimed[role]}'; kept as an unmanaged folder"
                )
            else:
                extra_reasons[name] = "no confident role match; kept as an unmanaged folder"

    # Apply claimed top-level roles, rebuilding child paths under the new parent.
    for role, folder_name in claimed.items():
        _remap_role(content_dirs, role, Path(folder_name))

    return LayoutSuggestion(
        system_dir=system_dir,
        inbox_dir=inbox_dir,
        dashboards_dir=dashboards_dir,
        content_dirs=content_dirs,
        extra_folders=extra_folders,
        reasons=reasons,
        extra_reasons=extra_reasons,
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
        "# - content_dirs map your folders onto pi-vault's fixed roles. The agent routes",
        "#   notes and builds dashboards using these roles.",
        "# - extra_folders are kept as-is and left UNMANAGED: created on init but never an",
        "#   automatic routing or dashboard target. Add or remove freely.",
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
    if suggestion.extra_folders:
        lines.append("extra_folders:")
        for folder in suggestion.extra_folders:
            reason = suggestion.extra_reasons.get(folder.as_posix(), "unmanaged folder")
            lines.append(f'  - "{folder.as_posix()}"  # {reason}')
    else:
        lines.append("extra_folders: []  # add any folders you want kept but unmanaged")

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
        data.get("extra_folders"),
    )
