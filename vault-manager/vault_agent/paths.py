"""Vault-local bootstrap configuration and derived path helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
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
class CustomFolder:
    """A user-declared arbitrary folder the model can sort notes into."""

    path: Path
    description: str = ""


@dataclass(frozen=True)
class VaultPaths:
    system_dir: Path
    inbox_dir: Path
    dashboards_dir: Path
    content_dirs: dict[str, Path]
    domain_folders: dict[str, Path] = field(default_factory=dict)
    custom_folders: tuple[CustomFolder, ...] = ()

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
    {},
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


# Domains already backed by dedicated content-role folders (renamed via content_dirs).
# These are not valid domain_folders keys; their folders are configured through content_dirs.
CONTENT_ROLE_DOMAINS = frozenset(
    {"work", "health", "household", "finance", "travel", "administration"}
)


def build_paths(
    system_dir: str | Path,
    inbox_dir: str | Path,
    dashboards_dir: str | Path = DEFAULT_DASHBOARDS_DIR,
    content_dirs: dict[str, str | Path] | None = None,
    domain_folders: dict[str, str | Path] | None = None,
    custom_folders: list[Any] | tuple[Any, ...] | None = None,
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
    domains = _validate_domain_folders(domain_folders, system, inbox, dashboards, configured)
    customs = _validate_custom_folders(custom_folders, system, inbox, dashboards)
    return VaultPaths(system, inbox, dashboards, configured, domains, customs)


def _validate_custom_folders(
    custom_folders: list[Any] | tuple[Any, ...] | None,
    system: Path,
    inbox: Path,
    dashboards: Path,
) -> tuple[CustomFolder, ...]:
    if custom_folders is None:
        return ()
    if not isinstance(custom_folders, (list, tuple)):
        raise ValueError("custom_folders must be a list of {path, description} entries")
    reserved = (system, inbox, dashboards)
    validated: list[CustomFolder] = []
    seen: list[Path] = []
    for entry in custom_folders:
        if isinstance(entry, CustomFolder):
            raw_path, description = entry.path, entry.description
        elif isinstance(entry, dict):
            raw_path = entry.get("path")
            description = entry.get("description", "")
        else:
            raise ValueError("each custom_folders entry must be a mapping with a 'path'")
        if raw_path is None:
            raise ValueError("each custom_folders entry requires a 'path'")
        folder = validate_vault_relative_path(raw_path, label="custom_folders.path")
        for root in reserved:
            if folder == root or folder.is_relative_to(root) or root.is_relative_to(folder):
                raise ValueError(
                    "custom_folders cannot equal or nest with the system, inbox, or dashboards folder"
                )
        if folder in seen:
            raise ValueError(f"duplicate custom_folders path: {folder.as_posix()}")
        seen.append(folder)
        validated.append(CustomFolder(folder, str(description or "")))
    return tuple(validated)


def _validate_domain_folders(
    domain_folders: dict[str, str | Path] | None,
    system: Path,
    inbox: Path,
    dashboards: Path,
    content_dirs: dict[str, Path],
) -> dict[str, Path]:
    if domain_folders is None:
        return {}
    if not isinstance(domain_folders, dict):
        raise ValueError("domain_folders must be a mapping of domain to folder path")
    reserved = (system, inbox, dashboards, *content_dirs.values())
    validated: dict[str, Path] = {}
    for raw_key, value in domain_folders.items():
        key = str(raw_key).strip()
        if not key or not key.replace("_", "").isalnum() or key != key.lower():
            raise ValueError(
                f"domain_folders key must be a lowercase alphanumeric slug: {raw_key!r}"
            )
        if key in CONTENT_ROLE_DOMAINS:
            raise ValueError(
                f"domain_folders cannot redefine the content-role domain '{key}'; "
                "rename its folder via content_dirs instead"
            )
        folder = validate_vault_relative_path(value, label=f"domain_folders.{key}")
        for existing in validated.values():
            if folder == existing or folder.is_relative_to(existing) or existing.is_relative_to(folder):
                raise ValueError("domain_folders paths must be distinct and non-nested")
        for root in reserved:
            if folder == root or folder.is_relative_to(root) or root.is_relative_to(folder):
                raise ValueError(
                    "domain_folders paths cannot equal or nest with the system, inbox, "
                    "dashboards, or content folders"
                )
        validated[key] = folder
    return validated


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
        bootstrap.get("domain_folders"),
        bootstrap.get("custom_folders"),
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


def render_bootstrap(paths: VaultPaths, *, routing: dict[str, str] | None = None) -> str:
    data: dict[str, Any] = {
        "version": 1,
        "system_dir": paths.system_dir.as_posix(),
        "inbox_dir": paths.inbox_dir.as_posix(),
        "dashboards_dir": paths.dashboards_dir.as_posix(),
        "content_dirs": {
            key: value.as_posix() for key, value in paths.content_dirs.items()
        },
    }
    if paths.custom_folders:
        data["custom_folders"] = [
            {"path": folder.path.as_posix(), "description": folder.description}
            for folder in paths.custom_folders
        ]
    if paths.domain_folders:
        data["domain_folders"] = {
            domain: folder.as_posix() for domain, folder in paths.domain_folders.items()
        }
    if routing:
        data["routing"] = dict(routing)
    return yaml.safe_dump(data, sort_keys=False)


def agent_path(vault_root: Path, relative: str | Path) -> Path:
    return vault_root / paths_for(vault_root).agent_dir / relative


def retrieval_path(vault_root: Path, relative: str | Path) -> Path:
    return vault_root / paths_for(vault_root).retrieval_dir / relative


def review_path(vault_root: Path, relative: str | Path) -> Path:
    return vault_root / paths_for(vault_root).review_dir / relative
