"""Vault-local bootstrap configuration and derived path helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


BOOTSTRAP_DIR = Path(".pi-vault")
BOOTSTRAP_FILE = BOOTSTRAP_DIR / "config.yaml"
DEFAULT_SYSTEM_DIR = Path("00 System")
DEFAULT_INBOX_DIR = Path("01 Inbox")


@dataclass(frozen=True)
class VaultPaths:
    system_dir: Path
    inbox_dir: Path

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


DEFAULT_PATHS = VaultPaths(DEFAULT_SYSTEM_DIR, DEFAULT_INBOX_DIR)

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


def build_paths(system_dir: str | Path, inbox_dir: str | Path) -> VaultPaths:
    system = validate_vault_relative_path(system_dir, label="system_dir")
    inbox = validate_vault_relative_path(inbox_dir, label="inbox_dir")
    if system == inbox or system.is_relative_to(inbox) or inbox.is_relative_to(system):
        raise ValueError("system_dir and inbox_dir must be distinct, non-nested folders")
    return VaultPaths(system, inbox)


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
    return yaml.safe_dump(
        {
            "version": 1,
            "system_dir": paths.system_dir.as_posix(),
            "inbox_dir": paths.inbox_dir.as_posix(),
        },
        sort_keys=False,
    )


def agent_path(vault_root: Path, relative: str | Path) -> Path:
    return vault_root / paths_for(vault_root).agent_dir / relative


def retrieval_path(vault_root: Path, relative: str | Path) -> Path:
    return vault_root / paths_for(vault_root).retrieval_dir / relative


def review_path(vault_root: Path, relative: str | Path) -> Path:
    return vault_root / paths_for(vault_root).review_dir / relative
