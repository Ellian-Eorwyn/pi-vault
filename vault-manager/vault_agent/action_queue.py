"""Proposal-first vault maintenance action queue."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .frontmatter import parse_note, render_note
from .llm import ProposalProvider, validate_proposal, validate_stage_proposal
from .paths import REVIEW_DIR
from .proposals import _safe_filename, _slug, _write_proposal
from .scanner import scan_vault
from .schema import (
    COMMON_PROPERTIES,
    DOMAIN_DEFINITIONS,
    NOTE_TYPES,
    STATUS_DEFINITIONS,
    ordered_properties_for,
)


FAILED_CATEGORIZATION_JSON = REVIEW_DIR / "failed-categorization.json"
FAILED_CATEGORIZATION_MD = REVIEW_DIR / "failed-categorization.md"
ACTION_QUEUE_ACTIONS = ("transcript", "people", "categorization")

_SPEAKER_RE = re.compile(r"^\s{0,3}([A-Z][A-Za-z0-9 ._'’-]{0,32}|Speaker \d+):\s+\S", re.MULTILINE)
_FILLER_RE = re.compile(r"\b(um+|uh+|erm|like|you know|i mean|sort of|kind of)\b", re.IGNORECASE)
_CONTEXT_PERSON_RE = re.compile(
    r"\b(?i:met with|meeting with|spoke with|talked to|called|emailed|from|by|with)\s+"
    r"([A-Z][a-z]+(?:[ \t]+(?:[A-Z][a-z]+|[A-Z]\.)){1,3})\b"
)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
_DIRECT_CONTACT_RE = re.compile(
    r"\b(?i:met with|meeting with|spoke with|talked to|called|emailed|interviewed|call with)\b"
)


@dataclass(frozen=True)
class TranscriptScore:
    score: int
    reasons: list[str]


def run_action_plan(
    config: AgentConfig, *, folder: str | None = None, json_output: bool = False
) -> tuple[int, str]:
    plan, errors = build_action_plan(config, folder=folder)
    if errors:
        return 1, "vault-agent action-plan failed\n" + "\n".join(f"Error: {error}" for error in errors)
    if json_output:
        return 0, json.dumps(plan, indent=2, sort_keys=True) + "\n"
    return 0, render_action_plan(plan)


def run_propose_action_queue(
    config: AgentConfig,
    *,
    actions: str,
    folder: str | None = None,
    use_llm: bool = False,
    llm_limit: int = 0,
    max_items: int | None = None,
    overwrite_proposal: bool = False,
    checkpoint: bool = False,
    resume: bool = False,
    proposal_provider: ProposalProvider | None = None,
) -> tuple[int, str]:
    del checkpoint, resume
    requested = _parse_actions(actions)
    if not requested:
        return 1, "vault-agent propose-action-queue failed\nError: no supported actions requested"
    plan, errors = build_action_plan(config, folder=folder)
    if errors:
        return 1, "vault-agent propose-action-queue failed\n" + "\n".join(
            f"Error: {error}" for error in errors
        )
    proposal, proposal_errors = generate_action_queue_proposal(
        config,
        plan,
        requested,
        proposal_provider=proposal_provider if use_llm else None,
        llm_limit=llm_limit,
        max_items=max_items,
    )
    if proposal_errors:
        return 1, "vault-agent propose-action-queue failed\n" + "\n".join(
            f"Error: {error}" for error in proposal_errors
        )
    return _write_proposal(
        config,
        proposal,
        dry_run=config.dry_run,
        overwrite_existing=overwrite_proposal,
    )


def build_action_plan(
    config: AgentConfig, *, folder: str | None = None
) -> tuple[dict[str, Any], list[str]]:
    result = scan_vault(config.vault_root)
    entries, errors = _entries_in_scope(config.vault_root, result.entries, folder)
    if errors:
        return {}, errors
    transcript_candidates = transcript_candidates_for_entries(
        config.vault_root, entries, system_dir=config.paths.system_dir
    )
    person_candidates = person_candidates_for_entries(
        config.vault_root, entries, system_dir=config.paths.system_dir
    )
    categorization_failures = categorization_failures_for_entries(
        entries, system_dir=config.paths.system_dir
    )
    persisted_failures = _load_failed_categorization(config)
    if persisted_failures:
        categorization_failures.extend(persisted_failures)
    proposals = _proposal_summary(config)
    plan = {
        "vault_root": config.vault_root.as_posix(),
        "folder": folder or "",
        "counts": {
            "notes": len(entries),
            "folders": len(result.folders),
            "proposals": proposals["total"],
            "transcript_candidates": len(transcript_candidates),
            "person_candidates": len(person_candidates),
            "person_candidate_kinds": _person_kind_counts(person_candidates),
            "categorization_failures": len(categorization_failures),
        },
        "proposal_queue": proposals,
        "available_actions": [
            {
                "action": "transcript",
                "notes": [item["path"] for item in transcript_candidates],
                "count": len(transcript_candidates),
                "command": _queue_command("transcript", folder),
            },
            {
                "action": "people",
                "notes": sorted(
                    {source for item in person_candidates for source in item["source_notes"]}
                ),
                "count": len(person_candidates),
                "command": _queue_command("people", folder),
            },
            {
                "action": "categorization",
                "notes": [item["path"] for item in categorization_failures],
                "count": len(categorization_failures),
                "command": _queue_command("categorization", folder),
            },
        ],
        "transcript_candidates": transcript_candidates,
        "person_candidates": person_candidates,
        "categorization_failures": categorization_failures,
    }
    return plan, []


def render_action_plan(plan: dict[str, Any]) -> str:
    counts = plan["counts"]
    lines = [
        "vault-agent action-plan",
        f"Vault root: {plan['vault_root']}",
        f"Scope: {plan['folder'] or '(entire vault)'}",
        f"Notes: {counts['notes']}",
        f"Proposal files: {counts['proposals']}",
        f"Transcript candidates: {counts['transcript_candidates']}",
        f"Person candidates: {counts['person_candidates']}",
        f"Categorization failures: {counts['categorization_failures']}",
        "",
        "Available actions:",
    ]
    for action in plan["available_actions"]:
        lines.append(f"- {action['action']}: {action['count']} item(s)")
        if action["count"]:
            lines.append(f"  Command: `{action['command']}`")
    if plan["categorization_failures"]:
        lines.extend(["", "Categorization queue:"])
        for item in plan["categorization_failures"][:12]:
            lines.append(f"- `{item['path']}`: {item['reason']}")
    return "\n".join(lines)


def transcript_score(text: str, frontmatter: dict[str, Any] | None = None) -> TranscriptScore:
    parsed = parse_note(text)
    body = parsed.body
    frontmatter = frontmatter or parsed.frontmatter
    reasons: list[str] = []
    score = 0
    speaker_count = len(_SPEAKER_RE.findall(body))
    if speaker_count >= 2:
        score += 3
        reasons.append(f"{speaker_count} speaker-label lines")
    words = re.findall(r"[A-Za-z']+", body)
    filler_count = len(_FILLER_RE.findall(body))
    filler_rate = filler_count / max(len(words), 1)
    if filler_count >= 4 and filler_rate >= 0.015:
        score += 2
        reasons.append("high filler-word density")
    heading_count = len(re.findall(r"^##?\s+", body, flags=re.MULTILINE))
    if heading_count <= 1 and len(words) >= 120:
        score += 1
        reasons.append("long note with little heading structure")
    if re.search(r"\b(I|we)\s+(was|were|think|feel|guess|said|told|remember)\b", body, re.IGNORECASE):
        score += 1
        reasons.append("first-person conversational narration")
    if frontmatter.get("source_kind") == "transcript":
        score += 3
        reasons.append("source_kind is transcript")
    if frontmatter.get("capture_type") in {"voice", "meeting", "chat"}:
        score += 1
        reasons.append(f"capture_type is {frontmatter.get('capture_type')}")
    return TranscriptScore(score=score, reasons=reasons)


def transcript_candidates_for_entries(
    vault_root: Path,
    entries: list[dict[str, Any]],
    *,
    system_dir: Path = Path("99 System"),
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for entry in entries:
        path = entry["path"]
        if _skip_system_or_template(path, system_dir=system_dir):
            continue
        note_path = vault_root / path
        parsed = parse_note(note_path.read_text(encoding="utf-8"))
        if parsed.error:
            continue
        score = transcript_score(note_path.read_text(encoding="utf-8"), parsed.frontmatter)
        if score.score >= 4:
            candidates.append(
                {
                    "path": path,
                    "score": score.score,
                    "reasons": score.reasons,
                    "suggested_action": "propose transcript cleanup",
                }
            )
    return candidates


def person_candidates_for_entries(
    vault_root: Path,
    entries: list[dict[str, Any]],
    *,
    system_dir: Path = Path("99 System"),
) -> list[dict[str, Any]]:
    existing = _existing_people(vault_root)
    by_name: dict[str, dict[str, Any]] = {}
    for entry in entries:
        path = entry["path"]
        if _skip_system_or_template(path, system_dir=system_dir):
            continue
        note_path = vault_root / path
        parsed = parse_note(note_path.read_text(encoding="utf-8"))
        if parsed.error:
            continue
        mentions = _person_mentions_in_body(parsed.body)
        for mention in mentions:
            name = mention["name"]
            key = normalize_person_name(name)
            if not key:
                continue
            item = by_name.setdefault(
                key,
                {
                    "name": name,
                    "existing_path": existing.get(key, ""),
                    "person_kind": mention["person_kind"],
                    "source_notes": [],
                    "contexts": [],
                    "mention_kinds": [],
                },
            )
            item["person_kind"] = _merge_person_kind(item["person_kind"], mention["person_kind"])
            if mention["person_kind"] not in item["mention_kinds"]:
                item["mention_kinds"].append(mention["person_kind"])
            if path not in item["source_notes"]:
                item["source_notes"].append(path)
            context = mention["context"] or _context_for_name(parsed.body, name)
            if context and context not in item["contexts"]:
                item["contexts"].append(context)
    return sorted(by_name.values(), key=lambda item: normalize_person_name(item["name"]))


def extract_person_names(text: str) -> list[str]:
    names = [mention["name"] for mention in _person_mentions_in_body(text)]
    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = normalize_person_name(name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(name)
    return deduped


def _person_mentions_in_body(text: str) -> list[dict[str, str]]:
    mentions: list[dict[str, str]] = []
    for match in _WIKILINK_RE.findall(text):
        _append_person_mention(
            mentions,
            name=match.strip(),
            person_kind="mentioned_person",
            context="",
        )
    for line in text.splitlines():
        stripped = line.strip()
        speaker = _SPEAKER_RE.match(stripped)
        if speaker:
            _append_person_mention(
                mentions,
                name=speaker.group(1).strip(),
                person_kind="direct_contact",
                context=stripped,
            )
        if "Key thinkers" in stripped:
            _, _, thinkers = stripped.partition(",")
            for item in thinkers.split(","):
                _append_person_mention(
                    mentions,
                    name=item.strip().strip("."),
                    person_kind="referenced_person",
                    context=stripped,
                )
        for match in _CONTEXT_PERSON_RE.finditer(stripped):
            _append_person_mention(
                mentions,
                name=match.group(1).strip(),
                person_kind="direct_contact" if _DIRECT_CONTACT_RE.search(stripped) else "mentioned_person",
                context=stripped,
            )
    return mentions


def _append_person_mention(
    mentions: list[dict[str, str]], *, name: str, person_kind: str, context: str
) -> None:
    cleaned = re.sub(r"\s+", " ", name).strip(" .,:;")
    if not _looks_like_person_name(cleaned):
        return
    mentions.append(
        {
            "name": cleaned,
            "person_kind": person_kind,
            "context": context[:240],
        }
    )


def _merge_person_kind(current: str, incoming: str) -> str:
    priority = {"direct_contact": 3, "referenced_person": 2, "mentioned_person": 1}
    return incoming if priority.get(incoming, 0) > priority.get(current, 0) else current


def _person_kind_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        person_kind = str(candidate.get("person_kind", "mentioned_person"))
        counts[person_kind] = counts.get(person_kind, 0) + 1
    return counts


def normalize_person_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def categorization_failures_for_entries(
    entries: list[dict[str, Any]], *, system_dir: Path = Path("99 System")
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for entry in entries:
        path = entry["path"]
        if _skip_system_or_template(path, system_dir=system_dir):
            continue
        reason = _categorization_issue_for_values(
            note_type=entry.get("type"),
            domain=entry.get("domain"),
            parent=entry.get("parent"),
        )
        if reason:
            failures.append(
                {
                    "path": path,
                    "reason": reason,
                    "suggested_action": "re-examine categorization",
                }
            )
    return failures


def generate_action_queue_proposal(
    config: AgentConfig,
    plan: dict[str, Any],
    actions: list[str],
    *,
    proposal_provider: ProposalProvider | None = None,
    llm_limit: int = 0,
    max_items: int | None = None,
) -> tuple[dict[str, Any], list[str]]:
    operations: list[dict[str, Any]] = []
    summaries: list[str] = []
    if "transcript" in actions:
        transcript_ops = _transcript_operations(
            config,
            _limited(plan["transcript_candidates"], max_items),
            proposal_provider=proposal_provider,
            llm_limit=llm_limit,
        )
        operations.extend(transcript_ops)
        summaries.append(f"{len(transcript_ops)} transcript cleanup operation(s)")
    if "people" in actions:
        people_ops = _people_operations(config, _limited(plan["person_candidates"], max_items))
        operations.extend(people_ops)
        summaries.append(f"{len(people_ops)} people operation(s)")
    if "categorization" in actions:
        category_ops = _categorization_operations(
            config,
            _limited(plan["categorization_failures"], max_items),
            proposal_provider=proposal_provider,
            llm_limit=llm_limit,
        )
        operations.extend(category_ops)
        categorization_edits = [
            operation for operation in category_ops if operation.get("op") == "organize_note"
        ]
        summaries.append(
            f"{len(categorization_edits)} LLM categorization operation(s); categorization queue render"
        )
    if not operations:
        return {}, ["no proposal operations found for requested actions"]
    action_slug = _slug("-".join(actions))
    proposal = {
        "id": f"action-queue-{action_slug}",
        "title": f"Action queue: {', '.join(actions)}",
        "kind": "action-queue",
        "status": "pending",
        "summary": "; ".join(summaries),
        "operations": operations,
    }
    return proposal, []


def _transcript_operations(
    config: AgentConfig,
    candidates: list[dict[str, Any]],
    *,
    proposal_provider: ProposalProvider | None = None,
    llm_limit: int = 0,
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    llm_attempts = 0
    for candidate in candidates:
        path = candidate["path"]
        note_path = config.vault_root / path
        text = note_path.read_text(encoding="utf-8")
        parsed = parse_note(text)
        frontmatter = _sparse_frontmatter(parsed.frontmatter)
        frontmatter["source_kind"] = "transcript"
        if not frontmatter.get("capture_type"):
            frontmatter["capture_type"] = "meeting" if "speaker-label lines" in " ".join(candidate["reasons"]) else "voice"
        llm_summary = ""
        if proposal_provider and llm_attempts < llm_limit:
            llm_attempts += 1
            llm_summary = _llm_summary_for_transcript(
                proposal_provider=proposal_provider,
                note_path=note_path,
                note_text=text,
                candidate=candidate,
            )
        content = render_note(
            frontmatter,
            _transcript_cleanup_body(parsed.body, path, summary=llm_summary),
            property_order=ordered_properties_for(frontmatter.get("type")),
        )
        operations.append(
            {
                "op": "write_file",
                "path": path,
                "if_exists": "overwrite",
                "content": content,
            }
        )
    return operations


def _people_operations(config: AgentConfig, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    existing = _existing_people(config.vault_root)
    people_index: dict[str, dict[str, str]] = {
        key: {"path": path, "person_kind": "existing_person", "name": Path(path).stem}
        for key, path in existing.items()
    }
    for candidate in candidates:
        name = candidate["name"]
        key = normalize_person_name(name)
        path = existing.get(key) or f"People/{_safe_filename(name)}.md"
        people_index[key] = {
            "path": path,
            "person_kind": str(candidate.get("person_kind", "mentioned_person")),
            "name": name,
        }
        content = _person_note_content(config.vault_root, candidate, path)
        operations.append(
            {
                "op": "write_file",
                "path": path,
                "if_exists": "overwrite",
                "content": content,
            }
        )
    if candidates:
        operations.append(
            {
                "op": "write_file",
                "path": "People/INDEX.md",
                "if_exists": "overwrite",
                "content": _people_index_content(people_index),
            }
        )
    return operations


def _categorization_operations(
    config: AgentConfig,
    failures: list[dict[str, Any]],
    *,
    proposal_provider: ProposalProvider | None = None,
    llm_limit: int = 0,
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    llm_attempts = 0
    for failure in failures:
        if proposal_provider and llm_attempts < llm_limit:
            llm_attempts += 1
            operation, error = _llm_categorization_operation(
                config=config,
                failure=failure,
                proposal_provider=proposal_provider,
            )
            if operation:
                operations.append(operation)
                continue
            unresolved.append({**failure, "llm_error": error or "LLM categorization failed"})
        else:
            unresolved.append(failure)
    queue = unresolved
    operations.extend(
        [
            {
                "op": "write_file",
                "path": (config.paths.review_dir / "failed-categorization.json").as_posix(),
                "if_exists": "overwrite",
                "content": json.dumps({"failures": queue}, indent=2) + "\n",
            },
            {
                "op": "write_file",
                "path": (config.paths.review_dir / "failed-categorization.md").as_posix(),
                "if_exists": "overwrite",
                "content": _failed_categorization_markdown(queue),
            },
        ]
    )
    return operations


def _llm_categorization_operation(
    *,
    config: AgentConfig,
    failure: dict[str, Any],
    proposal_provider: ProposalProvider,
) -> tuple[dict[str, Any] | None, str | None]:
    path = failure["path"]
    note_path = config.vault_root / path
    if not note_path.exists():
        return None, "target note missing"
    text = note_path.read_text(encoding="utf-8")
    try:
        proposal = proposal_provider.propose(
            note_path=note_path,
            note_text=_categorization_context(failure) + "\n\n" + text,
        )
    except Exception as exc:
        return _llm_staged_categorization_operation(
            config=config,
            failure=failure,
            proposal_provider=proposal_provider,
            fallback_reason=str(exc),
        )
    validation = validate_proposal(proposal)
    if not validation.valid:
        return _llm_staged_categorization_operation(
            config=config,
            failure=failure,
            proposal_provider=proposal_provider,
            fallback_reason="; ".join(validation.errors),
        )
    normalized = validation.proposal
    confidence = normalized.get("confidence")
    if (
        confidence is not None
        and confidence < config.llm_confidence_threshold
    ):
        return _llm_staged_categorization_operation(
            config=config,
            failure=failure,
            proposal_provider=proposal_provider,
            fallback_reason=f"confidence {confidence} is below threshold {config.llm_confidence_threshold}",
        )
    if config.review_on_warnings and normalized.get("warnings"):
        return _llm_staged_categorization_operation(
            config=config,
            failure=failure,
            proposal_provider=proposal_provider,
            fallback_reason="model returned warnings: " + "; ".join(normalized["warnings"]),
        )
    set_values = {
        "type": normalized["note_type"],
        "status": normalized["status"],
        "domain": normalized["domain"],
        "parent": normalized["parent"],
        "related": normalized["related"],
        "cover": normalized["cover"],
        "source_kind": normalized["source_kind"],
        "capture_type": normalized["capture_type"],
    }
    resolution_error = _categorization_issue_for_values(
        note_type=set_values["type"],
        domain=set_values["domain"],
        parent=set_values["parent"],
    )
    if resolution_error:
        return _llm_staged_categorization_operation(
            config=config,
            failure=failure,
            proposal_provider=proposal_provider,
            fallback_reason=f"model proposal did not resolve categorization failure: {resolution_error}",
        )
    return (
        {
            "op": "organize_note",
            "path": path,
            "set": set_values,
            "remove": [],
            "summary": normalized["summary"],
            "apply_template": True,
        },
        None,
    )


def _llm_staged_categorization_operation(
    *,
    config: AgentConfig,
    failure: dict[str, Any],
    proposal_provider: ProposalProvider,
    fallback_reason: str,
) -> tuple[dict[str, Any] | None, str | None]:
    path = failure["path"]
    note_path = config.vault_root / path
    text = note_path.read_text(encoding="utf-8")
    contextual_text = _categorization_context(failure) + "\n\n" + text
    try:
        type_proposal = proposal_provider.propose_stage(
            note_path=note_path,
            note_text=contextual_text,
            stage="classify-type",
        )
        type_validation = validate_stage_proposal("classify-type", type_proposal)
        if not type_validation.valid:
            return None, f"{fallback_reason}; staged classify-type failed: {'; '.join(type_validation.errors)}"
        type_error = _stage_gate_error(config, type_validation.proposal)
        if type_error:
            return None, f"{fallback_reason}; staged classify-type failed: {type_error}"

        property_proposal = proposal_provider.propose_stage(
            note_path=note_path,
            note_text=contextual_text,
            stage="property-values",
        )
        property_validation = validate_stage_proposal("property-values", property_proposal)
        if not property_validation.valid:
            return None, f"{fallback_reason}; staged property-values failed: {'; '.join(property_validation.errors)}"
        property_error = _stage_gate_error(config, property_validation.proposal)
        if property_error:
            return None, f"{fallback_reason}; staged property-values failed: {property_error}"

        summary_proposal = proposal_provider.propose_stage(
            note_path=note_path,
            note_text=contextual_text,
            stage="summary",
        )
        summary_validation = validate_stage_proposal("summary", summary_proposal)
        if not summary_validation.valid:
            return None, f"{fallback_reason}; staged summary failed: {'; '.join(summary_validation.errors)}"
        summary_error = _stage_gate_error(config, summary_validation.proposal)
        if summary_error:
            return None, f"{fallback_reason}; staged summary failed: {summary_error}"
    except Exception as exc:
        return None, f"{fallback_reason}; staged fallback failed: {exc}"

    properties = property_validation.proposal
    set_values = {
        "type": type_validation.proposal["note_type"],
        "status": properties["status"],
        "domain": properties["domain"],
        "parent": properties["parent"],
        "related": properties["related"],
        "cover": properties["cover"],
        "source_kind": properties["source_kind"],
        "capture_type": properties["capture_type"],
    }
    resolution_error = _categorization_issue_for_values(
        note_type=set_values["type"],
        domain=set_values["domain"],
        parent=set_values["parent"],
    )
    if resolution_error:
        return (
            None,
            f"{fallback_reason}; staged proposal did not resolve categorization failure: {resolution_error}",
        )
    return (
        {
            "op": "organize_note",
            "path": path,
            "set": set_values,
            "remove": [],
            "summary": summary_validation.proposal["summary"],
            "apply_template": True,
        },
        None,
    )


def _stage_gate_error(config: AgentConfig, proposal: dict[str, Any]) -> str | None:
    confidence = proposal.get("confidence")
    if confidence is not None and confidence < config.llm_confidence_threshold:
        return f"confidence {confidence} is below threshold {config.llm_confidence_threshold}"
    warnings = proposal.get("warnings", [])
    if config.review_on_warnings and warnings:
        return "model returned warnings: " + "; ".join(warnings)
    return None


def _categorization_context(failure: dict[str, Any]) -> str:
    type_lines = [
        f"- {name}: {spec['description']}" for name, spec in sorted(NOTE_TYPES.items())
    ]
    status_lines = [
        f"- {name}: {description}" for name, description in STATUS_DEFINITIONS.items()
    ]
    domain_lines = [
        f"- {name}: {description}" for name, description in DOMAIN_DEFINITIONS.items()
    ]
    source_kinds = ", ".join(COMMON_PROPERTIES["source_kind"]["allowed"])
    capture_types = ", ".join(COMMON_PROPERTIES["capture_type"]["allowed"])
    return (
        "Categorize this Obsidian note for a proposal-first vault cleanup pass.\n"
        f"Current failure reason: {failure['reason']}\n\n"
        "Use only these note types and definitions:\n"
        + "\n".join(type_lines)
        + "\n\nUse only these statuses and definitions:\n"
        + "\n".join(status_lines)
        + "\n\nUse only these domains and definitions:\n"
        + "\n".join(domain_lines)
        + "\n\nAllowed source_kind values: "
        + source_kinds
        + "\nAllowed capture_type values: "
        + capture_types
        + "\nThe proposal must resolve the current failure. If choosing project, source, meeting, or task, provide a clear parent wikilink; otherwise choose a type that does not require parent. Prefer empty related over invented links. Return the full vault-agent proposal JSON."
    )


def _categorization_issue_for_values(
    *, note_type: Any, domain: Any, parent: Any
) -> str:
    allowed_domains = COMMON_PROPERTIES["domain"]["allowed"]
    if note_type not in NOTE_TYPES:
        return f"unknown or missing type `{note_type or ''}`"
    if domain not in (None, "") and domain not in allowed_domains:
        return f"invalid domain `{domain}`"
    if note_type in {"project", "source", "meeting", "task"} and not parent:
        return f"{note_type} note has no parent"
    return ""


def _llm_summary_for_transcript(
    *,
    proposal_provider: ProposalProvider,
    note_path: Path,
    note_text: str,
    candidate: dict[str, Any],
) -> str:
    try:
        proposal = proposal_provider.propose_stage(
            note_path=note_path,
            note_text=(
                "Summarize this likely transcript cleanup candidate. "
                f"Detection reasons: {', '.join(candidate['reasons'])}\n\n"
                + note_text
            ),
            stage="summary",
        )
    except Exception as exc:
        candidate["llm_error"] = str(exc)
        return ""
    validation = validate_stage_proposal("summary", proposal)
    if not validation.valid:
        candidate["llm_error"] = "; ".join(validation.errors)
        return ""
    return validation.proposal["summary"]


def _transcript_cleanup_body(body: str, path: str, *, summary: str = "") -> str:
    original = body.strip()
    narrative = _clean_transcript_text(original)
    summary = summary or _first_sentence(narrative) or f"Transcript-style note from `{path}` pending human review."
    title = _first_heading(original) or Path(path).stem
    return (
        f"# {title}\n\n"
        "## Summary\n\n"
        f"{summary}\n\n"
        "## Cleaned Narrative\n\n"
        f"{narrative}\n\n"
        "## Verbatim Transcript\n\n"
        f"{original}\n"
    )


def _clean_transcript_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = re.sub(r"^\s*([A-Z][A-Za-z0-9 ._'’-]{0,32}|Speaker \d+):\s*", "", line)
        stripped = _FILLER_RE.sub("", stripped)
        stripped = re.sub(r"\s{2,}", " ", stripped).strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return "\n\n".join(lines).strip() or text.strip()


def _person_note_content(vault_root: Path, candidate: dict[str, Any], path: str) -> str:
    target = vault_root / path
    person_kind = str(candidate.get("person_kind", "mentioned_person"))
    source_lines = [
        f"- [[{Path(source).with_suffix('').as_posix()}]]"
        for source in candidate["source_notes"]
    ]
    context_lines = [f"- {_clean_context_line(context)}" for context in candidate["contexts"][:5]]
    mention_block = "\n".join(source_lines) or "- "
    context_block = "\n".join(context_lines) or "- "
    if target.exists():
        text = target.read_text(encoding="utf-8")
        parsed = parse_note(text)
        body = parsed.body.rstrip()
        section = _person_context_heading(person_kind)
        addition = f"\n\n## {section}\n\n{context_block}\n\n## Source Mentions\n\n{mention_block}\n"
        return render_note(
            _sparse_frontmatter(parsed.frontmatter, note_type="person"),
            body + addition,
            property_order=ordered_properties_for("person"),
        )
    frontmatter = _sparse_frontmatter({}, note_type="person")
    body = _new_person_body(candidate, person_kind, context_block, mention_block)
    return render_note(frontmatter, body, property_order=ordered_properties_for("person"))


def _new_person_body(
    candidate: dict[str, Any],
    person_kind: str,
    context_block: str,
    mention_block: str,
) -> str:
    if person_kind == "direct_contact":
        return f"""# {candidate['name']}

## Summary

Direct contact or conversation participant mentioned in vault notes.

## Contact Details

| Field | Value |
| --- | --- |
| Role / Relationship |  |
| Organization |  |
| Email / Phone / Handle |  |
| Last Interaction |  |

## Notes From Interactions

{context_block}

## Source Mentions

{mention_block}

## Related

- 
"""
    if person_kind == "referenced_person":
        return f"""# {candidate['name']}

## Summary

Referenced thinker, author, scholar, or public figure mentioned in vault notes.

## Reference Context

{context_block}

## Source Mentions

{mention_block}

## Related

- 
"""
    body = f"""# {candidate['name']}

## Summary

Person mentioned in vault notes.

## Context

| Field | Value |
| --- | --- |
| Role / Relationship |  |
| Organization |  |

## Mention Context

{context_block}

## Source Mentions

{mention_block}

## Related

- 
"""
    return body


def _person_context_heading(person_kind: str) -> str:
    if person_kind == "direct_contact":
        return "Notes From Interactions"
    if person_kind == "referenced_person":
        return "Reference Context"
    return "Mention Context"


def _clean_context_line(context: str) -> str:
    return re.sub(r"^[-*]\s+", "", context.strip())


def _people_index_content(people_index: dict[str, dict[str, str]]) -> str:
    frontmatter = _sparse_frontmatter({}, note_type="index")
    groups = [
        ("direct_contact", "Direct Contacts"),
        ("referenced_person", "Referenced People"),
        ("mentioned_person", "Mentioned People"),
        ("existing_person", "Existing People"),
    ]
    lines = ["# People Index", ""]
    for person_kind, heading in groups:
        rows = [
            item["path"]
            for item in people_index.values()
            if item.get("person_kind") == person_kind
        ]
        lines.extend([f"## {heading}", ""])
        if rows:
            for path in sorted(rows, key=str.lower):
                name = next(
                    item.get("name", Path(path).stem)
                    for item in people_index.values()
                    if item["path"] == path
                )
                lines.append(f"- [[{Path(path).with_suffix('').as_posix()}|{name}]]")
        else:
            lines.append("- None")
        lines.append("")
    body = "\n".join(lines).rstrip() + "\n"
    return render_note(frontmatter, body, property_order=ordered_properties_for("index"))


def _failed_categorization_markdown(failures: list[dict[str, Any]]) -> str:
    lines = ["# Failed Categorization", ""]
    if not failures:
        lines.append("No failed categorization items found.")
    for failure in failures:
        lines.append(f"- `{failure['path']}`: {failure['reason']}")
    return "\n".join(lines) + "\n"


def _sparse_frontmatter(frontmatter: dict[str, Any], note_type: str | None = None) -> dict[str, Any]:
    note_type = note_type or (frontmatter.get("type") if frontmatter.get("type") in NOTE_TYPES else "note")
    status = frontmatter.get("status") if frontmatter.get("status") in COMMON_PROPERTIES["status"]["allowed"] else "active"
    domain = frontmatter.get("domain") if frontmatter.get("domain") in COMMON_PROPERTIES["domain"]["allowed"] else ""
    related = frontmatter.get("related") if isinstance(frontmatter.get("related"), list) else []
    source_kind = frontmatter.get("source_kind") if frontmatter.get("source_kind") in COMMON_PROPERTIES["source_kind"]["allowed"] else ""
    capture_type = frontmatter.get("capture_type") if frontmatter.get("capture_type") in COMMON_PROPERTIES["capture_type"]["allowed"] else ""
    return {
        "type": note_type,
        "status": status or "active",
        "domain": domain or "",
        "parent": frontmatter.get("parent") if isinstance(frontmatter.get("parent"), str) else "",
        "related": related,
        "cover": frontmatter.get("cover") if isinstance(frontmatter.get("cover"), str) else "",
        "source_kind": source_kind or "",
        "capture_type": capture_type or "",
    }


def _entries_in_scope(vault_root: Path, entries: list[dict[str, Any]], folder: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    if not folder:
        return entries, []
    target = Path(folder)
    if target.is_absolute() or ".." in target.parts:
        return [], ["folder must be relative to vault root and cannot contain parent references"]
    absolute = (vault_root / target).resolve()
    if not absolute.is_dir() or not absolute.is_relative_to(vault_root.resolve()):
        return [], [f"folder does not exist: {folder}"]
    scoped = [entry for entry in entries if Path(entry["path"]).is_relative_to(target)]
    return scoped, []


def _proposal_summary(config: AgentConfig) -> dict[str, Any]:
    directory = config.vault_root / config.paths.review_dir / "proposals"
    statuses: dict[str, int] = {}
    total = 0
    if directory.exists():
        for path in directory.glob("*.json"):
            total += 1
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                status = data.get("status", "invalid")
            except json.JSONDecodeError:
                status = "invalid"
            statuses[str(status)] = statuses.get(str(status), 0) + 1
    return {"total": total, "statuses": statuses}


def _parse_actions(actions: str) -> list[str]:
    parsed = []
    for action in actions.split(","):
        normalized = action.strip().lower()
        if normalized in ACTION_QUEUE_ACTIONS and normalized not in parsed:
            parsed.append(normalized)
    return parsed


def _limited(items: list[dict[str, Any]], max_items: int | None) -> list[dict[str, Any]]:
    if max_items is None or max_items <= 0:
        return items
    return items[:max_items]


def _queue_command(action: str, folder: str | None) -> str:
    command = f"vault-agent propose-action-queue --actions {action}"
    if folder:
        command += f" --folder {folder}"
    return command


def _skip_system_or_template(path: str, *, system_dir: Path) -> bool:
    return Path(path).is_relative_to(system_dir)


def _existing_people(vault_root: Path) -> dict[str, str]:
    people: dict[str, str] = {}
    people_dir = vault_root / "People"
    if not people_dir.exists():
        return people
    for path in people_dir.glob("*.md"):
        if path.name == "INDEX.md":
            continue
        relative = path.relative_to(vault_root).as_posix()
        people[normalize_person_name(path.stem)] = relative
    return people


def _looks_like_person_name(name: str) -> bool:
    if not name or len(name) > 80:
        return False
    words = name.split()
    if len(words) < 2:
        return False
    blocked = {
        "Action Queue",
        "Cleaned Narrative",
        "Failed Categorization",
        "People Index",
        "Project Status",
        "Source Mentions",
        "Verbatim Transcript",
    }
    if name in blocked:
        return False
    return all(word[:1].isupper() for word in words if word)


def _context_for_name(body: str, name: str) -> str:
    for line in body.splitlines():
        if name in line:
            return line.strip()[:240]
    return ""


def _load_failed_categorization(config: AgentConfig) -> list[dict[str, Any]]:
    path = config.vault_root / config.paths.review_dir / "failed-categorization.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    failures = data.get("failures", [])
    return [item for item in failures if isinstance(item, dict)]


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _first_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    match = re.match(r"(.{20,240}?[.!?])(?:\s|$)", cleaned)
    return match.group(1) if match else cleaned[:220]
