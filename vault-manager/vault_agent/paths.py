"""Vault-local bootstrap configuration and derived path helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


BOOTSTRAP_DIR = Path(".pi-vault")
BOOTSTRAP_FILE = BOOTSTRAP_DIR / "config.yaml"
DEFAULT_SYSTEM_DIR = Path("99 System")
DEFAULT_INBOX_DIR = Path("00 Inbox")
DEFAULT_DASHBOARDS_DIR = Path("01 Dashboards")
DEFAULT_CONTENT_DIRS = {
    "people": Path("02 People"),
    "contacts": Path("02 People/02.01 Contacts"),
    "authors": Path("02 People/02.02 Authors"),
    "organizations": Path("03 Organizations"),
    "work": Path("04 Work"),
    "administrative": Path("05 Administrative"),
    "health": Path("05 Administrative/05.01 Health"),
    "home": Path("05 Administrative/05.02 Home"),
    "finance": Path("05 Administrative/05.03 Finance"),
    "travel": Path("05 Administrative/05.04 Travel"),
    "administrative_general": Path("05 Administrative/05.05 General"),
    "thoughts": Path("06 Thoughts"),
    "sources": Path("07 Sources"),
}


@dataclass(frozen=True)
class VaultPaths:
    system_dir: Path
    inbox_dir: Path
    dashboards_dir: Path
    content_dirs: dict[str, Path]
    extra_folders: tuple[Path, ...] = ()

    @property
    def agent_dir(self) -> Path:
        return self.system_dir / "0.01 agent"

    @property
    def template_dir(self) -> Path:
        return self.system_dir / "0.02 templates"

    @property
    def trash_dir(self) -> Path:
        return self.system_dir / "0.99 trash"

    @property
    def retrieval_dir(self) -> Path:
        return self.agent_dir / "retrieval"

    @property
    def review_dir(self) -> Path:
        return self.agent_dir / "review"

    def resolve(self, vault_root: Path, relative: str | Path) -> Path:
        return vault_root / relative


DEFAULT_PATHS = VaultPaths(
    DEFAULT_SYSTEM_DIR,
    DEFAULT_INBOX_DIR,
    DEFAULT_DASHBOARDS_DIR,
    dict(DEFAULT_CONTENT_DIRS),
    (),
)

# Backward-compatible defaults for public helpers and callers that do not yet have a
# vault root. Runtime code should use AgentConfig.paths or paths_for(vault_root).
AGENT_DIR = DEFAULT_PATHS.agent_dir
TEMPLATE_DIR = DEFAULT_PATHS.template_dir
TRASH_DIR = DEFAULT_PATHS.trash_dir
INBOX_DIR = DEFAULT_PATHS.inbox_dir
RETRIEVAL_DIR = DEFAULT_PATHS.retrieval_dir
REVIEW_DIR = DEFAULT_PATHS.review_dir


def validate_vault_relative_path(value: str | Path, *, label: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise ValueError(f"{label} must be relative to the vault root: {value}")
    if not path.parts or path == Path("."):
        raise ValueError(f"{label} must name a folder inside the vault")
    if ".." in path.parts:
        raise ValueError(f"{label} cannot contain parent directory references: {value}")
    if path.parts[0] in {".git", ".obsidian", BOOTSTRAP_DIR.as_posix()}:
        raise ValueError(f"{label} cannot use protected folder: {path.parts[0]}")
    return Path(*path.parts)


def build_paths(
    system_dir: str | Path,
    inbox_dir: str | Path,
    dashboards_dir: str | Path = DEFAULT_DASHBOARDS_DIR,
    content_dirs: dict[str, str | Path] | None = None,
    extra_folders: list[str | Path] | tuple[str | Path, ...] | None = None,
) -> VaultPaths:
    system = validate_vault_relative_path(system_dir, label="system_dir")
    inbox = validate_vault_relative_path(inbox_dir, label="inbox_dir")
    dashboards = validate_vault_relative_path(dashboards_dir, label="dashboards_dir")
    roots = (system, inbox, dashboards)
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                raise ValueError(
                    "system_dir, inbox_dir, and dashboards_dir must be distinct, non-nested folders"
                )
    if content_dirs is not None and not isinstance(content_dirs, dict):
        raise ValueError("content_dirs must be a mapping")
    configured = dict(DEFAULT_CONTENT_DIRS)
    for key, value in (content_dirs or {}).items():
        if key not in DEFAULT_CONTENT_DIRS:
            raise ValueError(f"unknown content directory key: {key}")
        configured[key] = validate_vault_relative_path(value, label=f"content_dirs.{key}")
    for key, value in configured.items():
        protected_roots = (system, inbox, dashboards)
        if any(
            value == root or value.is_relative_to(root) or root.is_relative_to(value)
            for root in protected_roots
        ):
            raise ValueError(
                f"content_dirs.{key} cannot be inside the system, inbox, or dashboards folder"
            )
    top_level_keys = ("people", "organizations", "work", "administrative", "thoughts", "sources")
    top_level = [configured[key] for key in top_level_keys]
    for index, left in enumerate(top_level):
        for right in top_level[index + 1 :]:
            if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                raise ValueError("top-level content directories must be distinct and non-nested")
    for key in ("contacts", "authors"):
        if not configured[key].is_relative_to(configured["people"]):
            raise ValueError(f"content_dirs.{key} must be inside content_dirs.people")
    for key in ("health", "home", "finance", "travel", "administrative_general"):
        if not configured[key].is_relative_to(configured["administrative"]):
            raise ValueError(f"content_dirs.{key} must be inside content_dirs.administrative")
    extras = _validate_extra_folders(extra_folders, system, inbox, dashboards, configured)
    return VaultPaths(system, inbox, dashboards, configured, extras)


def _validate_extra_folders(
    extra_folders: list[str | Path] | tuple[str | Path, ...] | None,
    system: Path,
    inbox: Path,
    dashboards: Path,
    content_dirs: dict[str, Path],
) -> tuple[Path, ...]:
    if extra_folders is None:
        return ()
    if not isinstance(extra_folders, (list, tuple)):
        raise ValueError("extra_folders must be a list of folder paths")
    reserved = (system, inbox, dashboards, *content_dirs.values())
    validated: list[Path] = []
    for value in extra_folders:
        folder = validate_vault_relative_path(value, label="extra_folders")
        for index, existing in enumerate(validated):
            if folder == existing or folder.is_relative_to(existing) or existing.is_relative_to(folder):
                raise ValueError("extra_folders must be distinct and non-nested")
        for root in reserved:
            if folder == root or folder.is_relative_to(root) or root.is_relative_to(folder):
                raise ValueError(
                    "extra_folders cannot equal or nest with the system, inbox, dashboards, or content folders"
                )
        validated.append(folder)
    return tuple(validated)


def paths_for(
    vault_root: Path,
    *,
    system_dir: str | Path | None = None,
    inbox_dir: str | Path | None = None,
) -> VaultPaths:
    if system_dir is not None or inbox_dir is not None:
        return build_paths(
            system_dir or DEFAULT_SYSTEM_DIR,
            inbox_dir or DEFAULT_INBOX_DIR,
        )
    bootstrap = load_bootstrap(vault_root)
    if bootstrap is None:
        return DEFAULT_PATHS
    return build_paths(
        bootstrap.get("system_dir", DEFAULT_SYSTEM_DIR.as_posix()),
        bootstrap.get("inbox_dir", DEFAULT_INBOX_DIR.as_posix()),
        bootstrap.get("dashboards_dir", DEFAULT_DASHBOARDS_DIR.as_posix()),
        bootstrap.get("content_dirs"),
        bootstrap.get("extra_folders"),
    )


def load_bootstrap(vault_root: Path) -> dict[str, Any] | None:
    path = vault_root / BOOTSTRAP_FILE
    if not path.exists():
        return None
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid pi-vault bootstrap config: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("pi-vault bootstrap config must be a YAML mapping")
    version = loaded.get("version")
    if version != 1:
        raise ValueError(f"unsupported pi-vault bootstrap version: {version}")
    return loaded


def render_bootstrap(paths: VaultPaths) -> str:
    data: dict[str, Any] = {
        "version": 1,
        "system_dir": paths.system_dir.as_posix(),
        "inbox_dir": paths.inbox_dir.as_posix(),
        "dashboards_dir": paths.dashboards_dir.as_posix(),
        "content_dirs": {
            key: value.as_posix() for key, value in paths.content_dirs.items()
        },
    }
    if paths.extra_folders:
        data["extra_folders"] = [folder.as_posix() for folder in paths.extra_folders]
    return yaml.safe_dump(data, sort_keys=False)


def agent_path(vault_root: Path, relative: str | Path) -> Path:
    return vault_root / paths_for(vault_root).agent_dir / relative


def retrieval_path(vault_root: Path, relative: str | Path) -> Path:
    return vault_root / paths_for(vault_root).retrieval_dir / relative


def review_path(vault_root: Path, relative: str | Path) -> Path:
    return vault_root / paths_for(vault_root).review_dir / relative
