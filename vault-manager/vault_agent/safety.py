"""Safety helpers for deterministic file creation and writes."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class CreationItem:
    kind: str
    path: Path
    description: str = ""
    content: str = ""


@dataclass(frozen=True)
class CreationPlanItem:
    item: CreationItem
    action: str
    backup_path: Path | None = None


def plan_creation(items: list[CreationItem], backup_root: Path) -> list[CreationPlanItem]:
    return [_plan_item(item, backup_root) for item in items]


def apply_creation_plan(plan: list[CreationPlanItem]) -> list[CreationPlanItem]:
    for planned in plan:
        item = planned.item
        if planned.action == "create_directory":
            item.path.mkdir(parents=True, exist_ok=True)
        elif planned.action == "create_file":
            _write_new_file(item.path, item.content)
    return plan


def atomic_write_text(path: Path, content: str) -> None:
    """Write text with a same-directory temporary file followed by replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def backup_file(path: Path, backup_root: Path) -> Path | None:
    """Copy an existing file into the backup tree and return the backup path."""
    if not path.exists():
        return None
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_root / f"{path.name}.{timestamp}.bak"
    shutil.copy2(path, backup_path)
    return backup_path


def write_text_safely(path: Path, content: str, *, backup_root: Path | None = None) -> Path | None:
    """Back up an existing file when requested, then atomically write content."""
    backup_path = backup_file(path, backup_root) if backup_root and path.exists() else None
    atomic_write_text(path, content)
    return backup_path


def _plan_item(item: CreationItem, backup_root: Path) -> CreationPlanItem:
    if _has_parent_conflict(item.path):
        return CreationPlanItem(item, "conflict")

    if item.kind == "directory":
        if item.path.is_dir():
            return CreationPlanItem(item, "exists")
        if item.path.exists():
            return CreationPlanItem(item, "conflict")
        return CreationPlanItem(item, "create_directory")

    if item.kind == "file":
        if item.path.is_file():
            return CreationPlanItem(
                item,
                "preserve_file",
                backup_path=_backup_path_for(item.path, backup_root),
            )
        if item.path.exists():
            return CreationPlanItem(item, "conflict")
        return CreationPlanItem(item, "create_file")

    raise ValueError(f"Unsupported creation item kind: {item.kind}")


def _has_parent_conflict(path: Path) -> bool:
    return any(parent.exists() and not parent.is_dir() for parent in path.parents)


def _backup_path_for(path: Path, backup_root: Path) -> Path:
    return backup_root / f"{path.name}.bak"


def _write_new_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        file.write(content)
