"""Deterministic destination routing for the dashboard-first vault layout."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .frontmatter import parse_note
from .llm import validate_stage_proposal
from .model_blocks import record_model_block
from .norms import current_lock_hash
from .processing_state import load_processing_state, note_hash, routed_destination


@dataclass(frozen=True)
class RouteDecision:
    destination_dir: Path | None
    reason: str
    review_required: bool = False


def custom_routing_enabled(config: AgentConfig) -> bool:
    """True when the vault opts into model-sorted custom folders."""
    return config.routing_mode == "custom" and bool(config.paths.custom_folders)


def assign_custom_destination(
    config: AgentConfig,
    proposal_provider: Any,
    note_path: Path,
    frontmatter: dict[str, Any],
    text: str,
) -> RouteDecision:
    """Let the model sort a note into one of the declared custom folders.

    Falls back to deterministic ``route_note`` (or flags review) when the model
    is unavailable, unsure, or chooses no folder, per ``routing_fallback``.
    """

    def _fallback(reason: str) -> RouteDecision:
        if config.routing_fallback == "deterministic":
            return route_note(config, note_path, frontmatter)
        return RouteDecision(None, reason, review_required=True)

    if not config.paths.custom_folders:
        return _fallback("no custom folders defined")
    if proposal_provider is None:
        return _fallback("custom routing needs an LLM proposal provider")

    catalog = [(f.path.as_posix(), f.description) for f in config.paths.custom_folders]
    allowed_paths = [path for path, _ in catalog]
    try:
        proposal = proposal_provider.propose_stage(
            note_path=note_path,
            note_text=text,
            stage="assign-folder",
            allowed_folders=catalog,
        )
    except Exception as exc:  # provider/transport failure
        return _fallback(f"custom routing failed: {exc}")

    validation = validate_stage_proposal(
        "assign-folder", proposal, allowed_folders=allowed_paths
    )
    if not validation.valid:
        return _fallback("model folder proposal was invalid")

    folder = validation.proposal.get("folder", "")
    confidence = validation.proposal.get("confidence")
    warnings = validation.proposal.get("warnings", [])
    if not folder:
        return _fallback("model did not select a custom folder")
    if (
        config.llm_confidence_threshold is not None
        and isinstance(confidence, (int, float))
        and confidence < config.llm_confidence_threshold
    ) or warnings:
        record_model_block(
            config.vault_root,
            note_path,
            stage="assign-folder",
            proposal=validation.proposal,
            reason="custom folder assignment requires review (low confidence or warnings)",
            suggested_next_action="Run `vault-agent review-model-blocks --dry-run`, then convert safe items through the proposal review path.",
            proposal_provider=proposal_provider,
        )
        return _fallback("model folder assignment needs review")
    return RouteDecision(Path(folder), "model-assigned custom folder")


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

    domain_folders = config.paths.domain_folders
    if domain in domain_folders:
        root = domain_folders[domain]
        destination = root / _safe_segment(project) if project else root
        return RouteDecision(destination, f"{domain} domain folder")

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
    config: AgentConfig,
    *,
    max_notes: int,
    safe_only: bool = False,
    proposal_provider: Any = None,
) -> tuple[dict[str, Any], list[str]]:
    inbox = config.vault_root / config.paths.inbox_dir
    use_custom = custom_routing_enabled(config)
    operations: list[dict[str, Any]] = []
    warnings: list[str] = []
    planned_dirs: set[Path] = set()
    selected = 0
    for note_path in sorted(inbox.rglob("*.md")) if inbox.exists() else []:
        if selected >= max_notes:
            break
        text = note_path.read_text(encoding="utf-8")
        parsed = parse_note(text)
        relative = note_path.relative_to(config.vault_root)
        if parsed.error:
            warnings.append(f"{relative.as_posix()}: {parsed.error}")
            continue
        if use_custom:
            recorded = routed_destination(config.vault_root, note_path)
            known = {folder.path for folder in config.paths.custom_folders}
            if recorded and Path(recorded) in known:
                decision = RouteDecision(Path(recorded), "recorded model folder assignment")
            else:
                decision = assign_custom_destination(
                    config, proposal_provider, note_path, parsed.frontmatter, text
                )
        else:
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
