"""Whole-vault conservative template and property reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .frontmatter import parse_note, render_note
from .generated_state import generated_state_report
from .legacy import apply_legacy_mappings
from .logging_utils import append_log
from .readiness import build_readiness_report
from .safety import write_text_safely
from .scanner import discover_markdown
from .schema import NOTE_TYPES, accepted_properties_for, ordered_properties_for
from .templates import append_missing_headings


@dataclass
class ReconcilePlanItem:
    path: Path
    property_updates: dict[str, Any] = field(default_factory=dict)
    removed_properties: list[str] = field(default_factory=list)
    headings_to_add: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
    review_note: str | None = None

    @property
    def has_changes(self) -> bool:
        return bool(self.property_updates or self.removed_properties or self.headings_to_add)


def build_reconcile_plan(
    config: AgentConfig, *, properties_only: bool = False
) -> list[ReconcilePlanItem]:
    plan: list[ReconcilePlanItem] = []
    for note_path in discover_markdown(config.vault_root):
        relative = note_path.relative_to(config.vault_root)
        if relative.is_relative_to(config.paths.system_dir) or relative.is_relative_to(
            config.paths.inbox_dir
        ):
            continue
        text = note_path.read_text(encoding="utf-8")
        parsed = parse_note(text)
        item = ReconcilePlanItem(relative)
        if parsed.error:
            item.skipped_reason = parsed.error
            plan.append(item)
            continue

        original_frontmatter = dict(parsed.frontmatter)
        frontmatter = apply_legacy_mappings(original_frontmatter, config)
        note_type = frontmatter.get("type")
        inferred_type = infer_type_from_content(
            relative, parsed.body, inbox_dir=config.paths.inbox_dir
        )
        if frontmatter != original_frontmatter:
            for key, value in frontmatter.items():
                if original_frontmatter.get(key) != value:
                    item.property_updates[key] = value

        if not note_type and inferred_type:
            item.property_updates["type"] = inferred_type
            note_type = inferred_type
        elif not note_type:
            item.review_note = "could not infer note type; template sections not applied"
        elif note_type and note_type not in NOTE_TYPES:
            item.skipped_reason = f"unknown type `{note_type}`"
            plan.append(item)
            continue

        accepted = accepted_properties_for(note_type)
        if not config.preserve_unknown_properties:
            item.removed_properties = sorted(key for key in frontmatter if key not in accepted)
        for key, value in _missing_property_defaults(relative, frontmatter, note_type).items():
            item.property_updates.setdefault(key, value)

        if note_type in NOTE_TYPES and not properties_only:
            _new_body, headings = append_missing_headings(parsed.body, note_type)
            item.headings_to_add = headings
        plan.append(item)
    return plan


def run_reconcile(config: AgentConfig, *, properties_only: bool = False) -> tuple[int, str]:
    plan = build_reconcile_plan(config, properties_only=properties_only)
    changed = [item for item in plan if item.has_changes]
    skipped = [item for item in plan if item.skipped_reason]
    if config.dry_run:
        return 0, _render_reconcile_report(
            "vault-agent reconcile dry run",
            changed,
            skipped,
            changed_files=False,
            preflight=_reconcile_preflight(config, plan),
        )

    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    applied = 0
    for item in changed:
        note_path = config.vault_root / item.path
        text = note_path.read_text(encoding="utf-8")
        parsed = parse_note(text)
        if parsed.error:
            continue
        frontmatter = dict(parsed.frontmatter)
        frontmatter.update(item.property_updates)
        note_type = frontmatter.get("type")
        frontmatter = _canonical_frontmatter(
            frontmatter,
            note_type,
            preserve_unknown_properties=config.preserve_unknown_properties,
        )
        body = parsed.body
        if note_type in NOTE_TYPES and not properties_only:
            body, _headings = append_missing_headings(body, note_type)
        new_text = render_note(
            frontmatter, body, property_order=ordered_properties_for(note_type)
        )
        if new_text != text:
            write_text_safely(note_path, new_text, backup_root=backup_root)
            applied += 1

    append_log(
        config.vault_root,
        "reconcile",
        [f"applied {applied} note(s)", f"skipped {len(skipped)} note(s)"],
    )
    return 0, _render_reconcile_report(
        "vault-agent reconcile complete", changed, skipped, changed_files=True, applied=applied
    )


def _missing_property_defaults(
    relative: Path, frontmatter: dict[str, Any], note_type: str | None
) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    if "status" not in frontmatter:
        defaults["status"] = ""
    if "domain" not in frontmatter:
        defaults["domain"] = ""
    if "parent" not in frontmatter:
        defaults["parent"] = ""
    if "related" not in frontmatter:
        defaults["related"] = []
    if "cover" not in frontmatter:
        defaults["cover"] = ""
    if "source_kind" not in frontmatter:
        defaults["source_kind"] = ""
    if "capture_type" not in frontmatter:
        defaults["capture_type"] = ""
    return defaults


def _canonical_frontmatter(
    frontmatter: dict[str, Any],
    note_type: str | None,
    *,
    preserve_unknown_properties: bool = True,
) -> dict[str, Any]:
    accepted = accepted_properties_for(note_type)
    ordered = ordered_properties_for(note_type)
    canonical: dict[str, Any] = {}
    for key in ordered:
        if key in frontmatter and key in accepted:
            canonical[key] = frontmatter[key]
    for key in sorted(frontmatter):
        if key in accepted and key not in canonical:
            canonical[key] = frontmatter[key]
    if preserve_unknown_properties:
        for key in sorted(frontmatter):
            if key not in canonical:
                canonical[key] = frontmatter[key]
    return canonical


def infer_type_from_content(
    relative: Path, body: str, *, inbox_dir: Path = Path("01 Inbox")
) -> str | None:
    """Infer a note type from title/body content using conservative signals."""
    text = f"{relative.stem}\n{body}".lower()
    first_heading = _first_heading(body).lower()
    scores = {note_type: 0 for note_type in NOTE_TYPES}

    if _contains_any(text, ["attendees", "agenda", "meeting notes", "minutes"]):
        scores["meeting"] += 3
    if _contains_any(text, ["author:", "doi:", "isbn:", "citation", "bibliography", "abstract"]):
        scores["source"] += 3
    if _contains_any(text, ["milestone", "project goal", "roadmap", "deliverable"]):
        scores["project"] += 3
    if _contains_any(text, ["- [ ]", "todo", "due:", "next action"]):
        scores["task"] += 3
    if _contains_any(text, ["email:", "phone:", "contact", "met at"]):
        scores["person"] += 3
    if _contains_any(text, ["claim:", "thesis:", "i argue", "therefore", "because"]):
        scores["note"] += 2
    if _contains_any(text, ["definition", "concept", "means that", "refers to"]):
        scores["note"] += 2
    if _contains_any(text, ["draft", "paragraph", "scene", "essay fragment"]):
        scores["note"] += 2
    if _looks_like_daily(relative.stem) or _contains_any(first_heading, ["daily note", "journal"]):
        scores["daily"] += 3
    if _contains_any(first_heading, ["index", "map of content", "moc"]):
        scores["index"] += 3

    best_type = max(scores, key=lambda note_type: scores[note_type])
    best_score = scores[best_type]
    if best_score >= 3:
        return best_type
    if best_score >= 2 and list(scores.values()).count(best_score) == 1:
        return best_type
    if relative.is_relative_to(inbox_dir):
        return "note"
    return None


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def _looks_like_daily(name: str) -> bool:
    parts = name.replace("_", "-").split("-")
    return (
        len(parts) >= 3
        and len(parts[0]) == 4
        and parts[0].isdigit()
        and parts[1].isdigit()
        and parts[2].isdigit()
    )


def _render_reconcile_report(
    title: str,
    changed: list[ReconcilePlanItem],
    skipped: list[ReconcilePlanItem],
    *,
    changed_files: bool,
    applied: int | None = None,
    preflight: list[str] | None = None,
) -> str:
    lines = [
        title,
        f"Notes with planned changes: {len(changed)}",
        f"Skipped notes: {len(skipped)}",
    ]
    review = [item for item in changed if item.review_note]
    if review:
        lines.append(f"Needs review: {len(review)}")
    if applied is not None:
        lines.append(f"Applied: {applied}")
    if not changed_files:
        lines.append("No files were changed.")
    if preflight:
        lines.extend(["", "Preflight:"])
        lines.extend(preflight)
    if changed:
        lines.extend(["", "Planned changes:"])
        for item in changed[:50]:
            pieces = []
            if item.property_updates:
                pieces.append("properties: " + ", ".join(sorted(item.property_updates)))
            if item.removed_properties:
                pieces.append("remove properties: " + ", ".join(item.removed_properties))
            if item.headings_to_add:
                pieces.append("sections: " + ", ".join(item.headings_to_add))
            lines.append(f"- `{item.path.as_posix()}` - {'; '.join(pieces)}")
    if review:
        lines.extend(["", "Needs review:"])
        for item in review[:50]:
            lines.append(f"- `{item.path.as_posix()}` - {item.review_note}")
    if skipped:
        lines.extend(["", "Skipped:"])
        for item in skipped[:50]:
            lines.append(f"- `{item.path.as_posix()}` - {item.skipped_reason}")
    return "\n".join(lines)


def _reconcile_preflight(config: AgentConfig, plan: list[ReconcilePlanItem]) -> list[str]:
    generated = generated_state_report(config)
    readiness = build_readiness_report(config)
    malformed = [item for item in plan if item.skipped_reason]
    template_sections = sum(1 for item in plan if item.headings_to_add)
    core_metadata = sum(1 for item in plan if item.property_updates)
    return [
        f"- Norms lock: {generated['norms_lock']['status']}",
        f"- Retrieval state: {generated['retrieval']['status']}",
        f"- Proposal review state: {generated['proposal_review']['status']}",
        f"- Malformed or skipped notes: {len(malformed)}",
        f"- Notes needing template sections: {template_sections}",
        f"- Notes needing core metadata/defaults: {core_metadata}",
        f"- Cleanup proposal opportunities: {readiness['cleanup_queue']['total']}",
        f"- Stale tracked notes: {readiness['processing_state']['stale']}",
        f"- Blocked tracked notes: {readiness['processing_state']['blocked']}",
    ]
