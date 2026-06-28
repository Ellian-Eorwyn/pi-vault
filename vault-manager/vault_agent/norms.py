"""Vault norms lock generation and inspection."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .paths import AGENT_DIR, paths_for
from .safety import write_text_safely
from .schema import default_schema, missing_definitions


NORMS_LOCK = AGENT_DIR / "norms-lock.json"


def build_norms_lock(config: AgentConfig) -> dict[str, Any]:
    """Build a deterministic snapshot of vault organization norms."""
    payload = {
        "generated_by": "vault-agent",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema": _load_schema(config.vault_root),
        "templates": _template_hashes(config.vault_root),
        "legacy_metadata": {
            "preserve_unknown_properties": config.preserve_unknown_properties,
            "type_aliases": dict(sorted(config.legacy_type_aliases.items())),
            "status_aliases": dict(sorted(config.legacy_status_aliases.items())),
            "source_kind_aliases": dict(sorted(config.legacy_source_kind_aliases.items())),
            "property_aliases": dict(sorted(config.legacy_property_aliases.items())),
        },
        "review": {
            "model_warnings_block_writes": config.review_on_warnings,
            "warning_confidence_margin": config.warning_confidence_margin,
            "confidence_threshold": config.llm_confidence_threshold,
        },
    }
    lock_input = {key: value for key, value in payload.items() if key != "generated_at"}
    payload["lock_hash"] = _hash_json(lock_input)
    return payload


def load_norms_lock(vault_root: Path) -> dict[str, Any] | None:
    path = norms_lock_path(vault_root)
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def current_lock_hash(vault_root: Path) -> str | None:
    lock = load_norms_lock(vault_root)
    value = lock.get("lock_hash") if lock else None
    return value if isinstance(value, str) and value else None


def run_norms_lock(config: AgentConfig, *, write: bool = False) -> tuple[int, str]:
    lock = build_norms_lock(config)
    path = norms_lock_path(config.vault_root)
    # Every controlled value must carry a confirmed definition before the schema is
    # locked, so the classifier always has aligned meaning to work from.
    undefined = missing_definitions(lock.get("schema"))
    if config.dry_run or not write:
        message = (
            "vault-agent norms-lock dry run\n"
            f"Would write: {path}\n"
            f"Lock hash: {lock['lock_hash']}\n"
            f"Templates: {len(lock['templates'])}\n"
            "No files were changed."
        )
        if undefined:
            message += (
                f"\nWARNING: {len(undefined)} controlled value(s) lack a definition "
                "and will block the lock: " + ", ".join(undefined[:20])
            )
        return 0, message
    if undefined:
        return (
            1,
            "vault-agent norms-lock failed\n"
            "Error: every controlled value needs a confirmed definition before locking.\n"
            f"Undefined ({len(undefined)}): " + ", ".join(undefined[:50]) + "\n"
            "Add them via `vault-agent export-schema-defaults` -> edit the Value "
            "Definitions -> `vault-agent import-schema-defaults`, then approve, apply, "
            "and retry the lock.",
        )

    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    write_text_safely(
        path,
        json.dumps(lock, indent=2, sort_keys=True) + "\n",
        backup_root=backup_root,
    )
    return (
        0,
        "vault-agent norms-lock complete\n"
        f"Wrote: {path}\n"
        f"Lock hash: {lock['lock_hash']}",
    )


def _load_schema(vault_root: Path) -> dict[str, Any]:
    path = vault_root / paths_for(vault_root).agent_dir / "schema.json"
    if not path.exists():
        return default_schema()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_schema()
    return loaded if isinstance(loaded, dict) else default_schema()


def _template_hashes(vault_root: Path) -> dict[str, str]:
    root = vault_root / paths_for(vault_root).template_dir
    if not root.exists():
        return {}
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(vault_root).as_posix()
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _hash_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def norms_lock_path(vault_root: Path) -> Path:
    return vault_root / paths_for(vault_root).agent_dir / "norms-lock.json"
