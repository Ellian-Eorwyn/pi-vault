"""Shared runtime configuration for vault-agent commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .paths import VaultPaths, paths_for

DEFAULT_TYPE_ALIASES = {
    "administrative": "system",
    "draft": "note",
    "inbox": "note",
    "journal": "daily",
    "plan": "project",
    "reference": "note",
    "reflection": "note",
}

DEFAULT_STATUS_ALIASES = {
    "complete": "completed",
    "raw": "active",
    "reference": "active",
}

DEFAULT_SOURCE_KIND_ALIASES = {
    "academic paper": "article",
    "paper": "article",
    "web": "website",
    "webpage": "website",
}

DEFAULT_PROPERTY_ALIASES = {
    "area": "domain",
    "areas": "domain",
    "domains": "domain",
    "publication_type": "source_kind",
    "source": "source_kind",
    "source_type": "source_kind",
    "tags": "related",
    "topic": "related",
    "topics": "related",
}


@dataclass(frozen=True)
class AgentConfig:
    vault_root: Path
    paths: VaultPaths
    config_path: Path | None
    dry_run: bool
    verbose: bool
    llm_enabled: bool
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str | None
    llm_confidence_threshold: float
    llm_timeout_seconds: int
    llm_max_input_tokens: int
    llm_chars_per_token: int
    llm_max_input_chars: int
    embedding_base_url: str | None
    embedding_model: str | None
    max_notes: int
    max_runtime_minutes: int
    legacy_type_aliases: dict[str, str]
    legacy_status_aliases: dict[str, str]
    legacy_source_kind_aliases: dict[str, str]
    legacy_property_aliases: dict[str, str]
    preserve_unknown_properties: bool
    review_on_warnings: bool
    warning_confidence_margin: float
    versioning_enabled: bool
    versioning_auto_init: bool
    versioning_separate_git_dir: str | None
    versioning_auto_snapshot_before_write: bool
    versioning_auto_snapshot_after_write: bool
    versioning_dirty_before_write_policy: str
    versioning_auto_push: bool
    versioning_remote: str | None
    versioning_branch: str | None
    versioning_managed_gitignore: bool
    versioning_commit_author_name: str | None
    versioning_commit_author_email: str | None
    versioning_lockfile: str | None
    versioning_mass_edit_threshold_files: int
    versioning_mass_edit_threshold_deletions: int
    versioning_require_explicit_mass_edit_flag: bool
    versioning_full_restore_requires_force: bool
    versioning_ignored_paths: list[str]
    versioning_protected_paths: list[str]


def load_config(args: argparse.Namespace) -> AgentConfig:
    """Resolve shared CLI options and optional vault-agent config."""
    config = getattr(args, "config", None)
    vault_root = Path(getattr(args, "vault_root", ".")).expanduser().resolve()
    config_path = Path(config).expanduser().resolve() if config else None
    paths = paths_for(
        vault_root,
        system_dir=getattr(args, "system_dir", None),
        inbox_dir=getattr(args, "inbox_dir", None),
    )
    file_config = _load_config_file(config_path or vault_root / paths.agent_dir / "config.yaml")
    auto_process = _mapping(file_config.get("auto_process"))
    llm = _mapping(file_config.get("llm"))
    legacy = _mapping(file_config.get("legacy_metadata"))
    review = _mapping(file_config.get("review"))
    versioning = _mapping(file_config.get("versioning"))
    max_input_tokens = int(llm.get("max_input_tokens", 64000))
    chars_per_token = int(llm.get("chars_per_token", 4))
    max_input_chars = int(
        llm.get("max_input_chars", max_input_tokens * chars_per_token)
    )
    return AgentConfig(
        vault_root=vault_root,
        paths=paths,
        config_path=config_path,
        dry_run=bool(getattr(args, "dry_run", False)),
        verbose=bool(getattr(args, "verbose", False)),
        llm_enabled=bool(llm.get("enabled", False)),
        llm_provider=str(llm.get("provider", "none")),
        llm_base_url=str(llm.get("base_url", "http://llms:8008")),
        llm_model=str(llm.get("model", "code")),
        llm_api_key=_optional_string(llm.get("api_key")),
        llm_confidence_threshold=float(llm.get("confidence_threshold", 0.75)),
        llm_timeout_seconds=int(llm.get("timeout_seconds", 120)),
        llm_max_input_tokens=max_input_tokens,
        llm_chars_per_token=chars_per_token,
        llm_max_input_chars=max_input_chars,
        embedding_base_url=_optional_string(llm.get("embedding_base_url")),
        embedding_model=_optional_string(llm.get("embedding_model", "embed")),
        max_notes=int(auto_process.get("max_notes", 5)),
        max_runtime_minutes=int(auto_process.get("max_runtime_minutes", 10)),
        legacy_type_aliases=_string_mapping(
            legacy.get("type_aliases"), DEFAULT_TYPE_ALIASES
        ),
        legacy_status_aliases=_string_mapping(
            legacy.get("status_aliases"), DEFAULT_STATUS_ALIASES
        ),
        legacy_source_kind_aliases=_string_mapping(
            legacy.get("source_kind_aliases"), DEFAULT_SOURCE_KIND_ALIASES
        ),
        legacy_property_aliases=_string_mapping(
            legacy.get("property_aliases"), DEFAULT_PROPERTY_ALIASES
        ),
        preserve_unknown_properties=bool(legacy.get("preserve_unknown_properties", True)),
        review_on_warnings=bool(review.get("model_warnings_block_writes", True)),
        warning_confidence_margin=float(review.get("warning_confidence_margin", 0.05)),
        versioning_enabled=bool(versioning.get("enabled", True)),
        versioning_auto_init=bool(versioning.get("auto_init", True)),
        versioning_separate_git_dir=_optional_string(versioning.get("separate_git_dir")),
        versioning_auto_snapshot_before_write=bool(
            versioning.get("auto_snapshot_before_write", True)
        ),
        versioning_auto_snapshot_after_write=bool(
            versioning.get("auto_snapshot_after_write", True)
        ),
        versioning_dirty_before_write_policy=str(
            versioning.get("dirty_before_write_policy", "snapshot")
        ),
        versioning_auto_push=bool(versioning.get("auto_push", False)),
        versioning_remote=_optional_string(versioning.get("remote")),
        versioning_branch=_optional_string(versioning.get("branch")),
        versioning_managed_gitignore=bool(versioning.get("managed_gitignore", True)),
        versioning_commit_author_name=_optional_string(
            versioning.get("commit_author_name")
        ),
        versioning_commit_author_email=_optional_string(
            versioning.get("commit_author_email")
        ),
        versioning_lockfile=_optional_string(versioning.get("lockfile")),
        versioning_mass_edit_threshold_files=int(
            versioning.get("mass_edit_threshold_files", 25)
        ),
        versioning_mass_edit_threshold_deletions=int(
            versioning.get("mass_edit_threshold_deletions", 5)
        ),
        versioning_require_explicit_mass_edit_flag=bool(
            versioning.get("require_explicit_mass_edit_flag", True)
        ),
        versioning_full_restore_requires_force=bool(
            versioning.get("full_restore_requires_force", True)
        ),
        versioning_ignored_paths=_string_list(versioning.get("ignored_paths")),
        versioning_protected_paths=_string_list(versioning.get("protected_paths")),
    )


def _load_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _string_mapping(value: Any, default: dict[str, str]) -> dict[str, str]:
    result = dict(default)
    if not isinstance(value, dict):
        return result
    for key, mapped in value.items():
        if key in (None, "") or mapped in (None, ""):
            continue
        result[str(key)] = str(mapped)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in (None, "")]
