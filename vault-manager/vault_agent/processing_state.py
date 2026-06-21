"""Processing-stage ledger for per-note staged work."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import AGENT_DIR, paths_for
from .safety import write_text_safely


PROCESSING_STATE = AGENT_DIR / "processing-state.json"


def load_processing_state(vault_root: Path) -> dict[str, Any]:
    path = vault_root / paths_for(vault_root).agent_dir / "processing-state.json"
    if not path.exists():
        return {"generated_by": "vault-agent", "notes": {}}
    with path.open(encoding="utf-8") as file:
        loaded = json.load(file)
    if not isinstance(loaded, dict):
        return {"generated_by": "vault-agent", "notes": {}}
    loaded.setdefault("generated_by", "vault-agent")
    loaded.setdefault("notes", {})
    return loaded


def mark_stage(
    vault_root: Path,
    note_path: Path,
    *,
    stage: str,
    status: str,
    norms_lock_hash: str | None = None,
    confidence: float | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> None:
    state = load_processing_state(vault_root)
    relative = note_path.relative_to(vault_root).as_posix()
    text = note_path.read_text(encoding="utf-8")
    note_state = state["notes"].setdefault(relative, {"stages": {}})
    note_state["hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if norms_lock_hash:
        note_state["norms_lock_hash"] = norms_lock_hash
    stage_state = {
        "status": status,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    if confidence is not None:
        stage_state["confidence"] = confidence
    if warnings:
        stage_state["warnings"] = warnings
    if errors:
        stage_state["errors"] = errors
    note_state["stages"][stage] = stage_state
    write_text_safely(
        vault_root / paths_for(vault_root).agent_dir / "processing-state.json",
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        backup_root=vault_root / paths_for(vault_root).agent_dir / "backups",
    )


def stage_status(vault_root: Path, note_path: Path, stage: str) -> str | None:
    state = load_processing_state(vault_root)
    relative = note_path.relative_to(vault_root).as_posix()
    note_state = state.get("notes", {}).get(relative, {})
    stage_state = note_state.get("stages", {}).get(stage, {})
    status = stage_state.get("status")
    return status if isinstance(status, str) else None


def stage_complete(
    vault_root: Path,
    note_path: Path,
    stage: str,
    *,
    norms_lock_hash: str | None = None,
) -> bool:
    state = load_processing_state(vault_root)
    relative = note_path.relative_to(vault_root).as_posix()
    note_state = state.get("notes", {}).get(relative, {})
    stage_state = note_state.get("stages", {}).get(stage, {})
    if stage_state.get("status") != "complete":
        return False
    if note_state.get("hash") != note_hash(note_path):
        return False
    if norms_lock_hash and note_state.get("norms_lock_hash") != norms_lock_hash:
        return False
    return True


def note_hash(note_path: Path) -> str:
    return hashlib.sha256(note_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def processing_summary(vault_root: Path, *, norms_lock_hash: str | None = None) -> dict[str, int]:
    state = load_processing_state(vault_root)
    summary = {"tracked": 0, "stale": 0, "blocked": 0}
    for relative, note_state in state.get("notes", {}).items():
        if not isinstance(note_state, dict):
            continue
        summary["tracked"] += 1
        note_path = vault_root / relative
        stale = False
        if note_path.exists() and note_state.get("hash") != note_hash(note_path):
            stale = True
        if norms_lock_hash and note_state.get("norms_lock_hash") != norms_lock_hash:
            stale = True
        if stale:
            summary["stale"] += 1
        stages = note_state.get("stages", {})
        if any(
            isinstance(stage_state, dict) and stage_state.get("status") == "blocked"
            for stage_state in stages.values()
        ):
            summary["blocked"] += 1
    return summary
