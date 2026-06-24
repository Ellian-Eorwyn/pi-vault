"""Deterministic destination routing for the dashboard-first vault layout."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .frontmatter import parse_note
from .norms import current_lock_hash
from .processing_state import load_processing_state, note_hash


@dataclass(frozen=True)
class RouteDecision:
    destination_dir: Path | None
    reason: str
    review_required: bool = False


def route_note(config: AgentConfig, note_path: Path, frontmatter: dict[str, Any]) -> RouteDecision:
    note_type = _text(frontmatter.get("type"))
    domain = _text(frontmatter.get("domain"))
    parent = _wikilink_name(_text(frontmatter.get("parent")))
    content = config.paths.content_dirs

    if note_type not in {
        "project",
        "source",
        "person",
        "organization",
        "meeting",
        "task",
        "note",
        "daily",
    }:
        return RouteDecision(None, "note type is missing or not routable", True)

    if note_type == "person":
        if parent == "Contacts":
            return RouteDecision(content["contacts"], "direct contact")
        if parent == "Authors":
            return RouteDecision(content["authors"], "referenced author")
        return RouteDecision(None, "person requires parent [[Contacts]] or [[Authors]]", True)
    if note_type == "organization":
        return RouteDecision(content["organizations"], "organization")
    if note_type == "source":
        return RouteDecision(content["sources"], "source")

    project = note_path.stem if note_type == "project" else parent
    if domain == "work":
        destination = content["work"] / _safe_segment(project) if project else content["work"]
        return RouteDecision(destination, "work project or work note")

    administrative = {
        "health": content["health"],
        "household": content["home"],
        "finance": content["finance"],
        "travel": content["travel"],
        "administration": content["administrative_general"],
    }
    if domain in administrative:
        root = administrative[domain]
        destination = root / _safe_segment(project) if project else root
        return RouteDecision(destination, f"{domain} administration")

    if note_type == "project" or project:
        if not domain:
            return RouteDecision(None, "non-work project routing requires an approved domain", True)
        return RouteDecision(
            content["thoughts"] / _safe_segment(domain) / _safe_segment(project),
            "non-work domain project",
        )
    return RouteDecision(content["thoughts"], "general thought or knowledge note")


def build_inbox_sort_proposal(
    config: AgentConfig, *, max_notes: int, safe_only: bool = False
) -> tuple[dict[str, Any], list[str]]:
    inbox = config.vault_root / config.paths.inbox_dir
    operations: list[dict[str, Any]] = []
    warnings: list[str] = []
    planned_dirs: set[Path] = set()
    selected = 0
    for note_path in sorted(inbox.rglob("*.md")) if inbox.exists() else []:
        if selected >= max_notes:
            break
        parsed = parse_note(note_path.read_text(encoding="utf-8"))
        relative = note_path.relative_to(config.vault_root)
        if parsed.error:
            warnings.append(f"{relative.as_posix()}: {parsed.error}")
            continue
        decision = route_note(config, note_path, parsed.frontmatter)
        if decision.destination_dir is None:
            warnings.append(f"{relative.as_posix()}: {decision.reason}")
            continue
        safe = _automation_safe(config, note_path)
        if safe_only and not safe:
            warnings.append(f"{relative.as_posix()}: processing confidence or norms evidence is incomplete")
            continue
        destination_dir = decision.destination_dir
        destination = destination_dir / note_path.name
        if destination == relative:
            continue
        if (config.vault_root / destination).exists():
            warnings.append(f"{relative.as_posix()}: destination exists: {destination.as_posix()}")
            continue
        missing: list[Path] = []
        current = destination_dir
        while current != Path(".") and not (config.vault_root / current).exists():
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            if directory in planned_dirs:
                continue
            planned_dirs.add(directory)
            operations.append(
                {"op": "create_directory", "path": directory.as_posix(), "if_exists": "preserve"}
            )
        operations.append(
            {
                "op": "move_note",
                "path": relative.as_posix(),
                "destination": destination.as_posix(),
                "update_links": True,
            }
        )
        selected += 1
    proposal = {
        "id": "inbox-sort-safe" if safe_only else "inbox-sort",
        "title": "Sort processed inbox notes",
        "kind": "inbox-sort",
        "status": "pending",
        "automation_safe": safe_only and bool(operations),
        "summary": "Move bounded inbox notes into deterministic dashboard-first destinations.",
        "operations": operations,
    }
    return proposal, warnings


def _automation_safe(config: AgentConfig, note_path: Path) -> bool:
    lock_hash = current_lock_hash(config.vault_root)
    if not lock_hash:
        return False
    state = load_processing_state(config.vault_root)
    relative = note_path.relative_to(config.vault_root).as_posix()
    note_state = state.get("notes", {}).get(relative, {})
    if note_state.get("hash") != note_hash(note_path):
        return False
    if note_state.get("norms_lock_hash") != lock_hash:
        return False
    stages = note_state.get("stages", {})
    for stage in ("classify-type", "property-values"):
        stage_state = stages.get(stage, {})
        if stage_state.get("status") != "complete" or stage_state.get("warnings"):
            return False
        confidence = stage_state.get("confidence")
        if not isinstance(confidence, (int, float)) or confidence < config.llm_confidence_threshold:
            return False
    return True


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _wikilink_name(value: str) -> str:
    if value.startswith("[[") and value.endswith("]]" ):
        return value[2:-2].split("|", 1)[0].split("/", 1)[-1].strip()
    return value


def _safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "", value).strip().replace(" ", "-")
    return cleaned or "Project"
