"""People extraction: build deduplicated person notes from vault mentions.

Mentions are detected deterministically (reusing the existing detectors), each clearly
identified new person is classified contact-vs-author and drafted by the configured LLM
backend, and the result is a reviewable `people-extraction` proposal. Existing person
notes are never recreated; their backlinks are extended instead. Everything stays
proposal-gated and git-backed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .action_queue import _person_mentions_in_body, normalize_person_name
from .config import AgentConfig
from .frontmatter import parse_note, render_note
from .llm import ProposalProvider, validate_stage_proposal
from .logging_utils import append_log
from .paths import paths_for
from .safety import atomic_write_text
from .scanner import scan_vault
from .schema import ordered_properties_for


def run_propose_people(
    config: AgentConfig,
    *,
    folder: str | None = None,
    max_people: int | None = None,
    proposal_provider: ProposalProvider | None = None,
) -> tuple[int, str]:
    """Generate a `people-extraction` proposal for a folder or the whole vault."""
    if proposal_provider is None:
        return (
            1,
            "vault-agent propose-people failed\n"
            "Error: people extraction needs the configured LLM backend; enable `llm` in the config.",
        )
    limit = max_people if max_people is not None else max(config.max_notes, 5)
    system_dir = paths_for(config.vault_root).system_dir
    folder_prefix = folder.strip("/") if folder else None

    result = scan_vault(config.vault_root)
    existing = _existing_person_notes(config, result.entries)
    candidates = _aggregate_candidates(
        config, result.entries, system_dir=system_dir, folder_prefix=folder_prefix
    )

    operations: list[dict[str, Any]] = []
    created: list[str] = []
    linked: list[str] = []
    blocked: list[dict[str, str]] = []
    review: list[str] = []
    for candidate in candidates:
        if len(created) >= limit:
            break
        name = candidate["name"]
        key = normalize_person_name(name)
        if key in existing:
            op = _backlink_operation(config, existing[key], candidate["source_links"])
            if op is not None:
                operations.append(op)
                linked.append(name)
            continue
        if not _clearly_identified(name):
            review.append(name)
            continue
        try:
            raw = proposal_provider.propose_stage(
                note_path=Path(name),
                note_text=_classification_context(candidate),
                stage="classify-person",
            )
        except ValueError as exc:
            blocked.append({"name": name, "reason": str(exc)})
            continue
        validation = validate_stage_proposal("classify-person", raw)
        if not validation.valid:
            blocked.append({"name": name, "reason": "; ".join(validation.errors)})
            continue
        confidence = validation.proposal.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < config.llm_confidence_threshold:
            blocked.append({"name": name, "reason": "classification confidence below threshold"})
            continue
        kind = validation.proposal["kind"]
        folder_key = "contacts" if kind == "contact" else "authors"
        destination = Path(config.paths.content_dirs[folder_key]) / f"{name}.md"
        if (config.vault_root / destination).exists():
            review.append(name)
            continue
        operations.append(
            {
                "op": "write_file",
                "path": destination.as_posix(),
                "if_exists": "fail",
                "content": _person_note_content(
                    name=name,
                    kind=kind,
                    details=validation.proposal.get("details", ""),
                    source_links=candidate["source_links"],
                ),
            }
        )
        created.append(name)

    proposal = {
        "id": "people-extraction",
        "title": "Extract people into Contacts and Authors",
        "kind": "people-extraction",
        "status": "pending",
        "automation_safe": False,
        "summary": f"Create {len(created)} person note(s) and extend {len(linked)} existing one(s).",
        "operations": operations,
    }

    if not config.dry_run and operations:
        proposal_dir = config.vault_root / config.paths.review_dir / "proposals"
        proposal_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            proposal_dir / "people-extraction.json",
            json.dumps(proposal, indent=2, sort_keys=True) + "\n",
        )
        append_log(
            config.vault_root,
            "propose-people",
            [f"created {len(created)}", f"linked {len(linked)}", f"blocked {len(blocked)}"],
        )

    lines = [
        "vault-agent propose-people " + ("dry run" if config.dry_run else "complete"),
        f"Candidate people: {len(candidates)}",
        f"New person notes proposed: {len(created)}",
        f"Existing notes to backlink: {len(linked)}",
        f"Blocked by model/guard: {len(blocked)}",
        f"Routed to review (ambiguous or existing file): {len(review)}",
    ]
    for person in created:
        lines.append(f"- create `{person}`")
    for item in blocked:
        lines.append(f"- blocked `{item['name']}`: {item['reason']}")
    if config.dry_run:
        lines.append("No files were changed.")
    elif operations:
        lines.append("Run `vault-agent review-proposals --dry-run` to inspect the proposal.")
    else:
        lines.append("No new people to propose.")
    return (1 if blocked else 0), "\n".join(lines)


def _aggregate_candidates(
    config: AgentConfig,
    entries: list[dict[str, Any]],
    *,
    system_dir: Path,
    folder_prefix: str | None,
) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for entry in entries:
        relative = Path(entry["path"])
        if entry.get("system_template") or relative.is_relative_to(system_dir):
            continue
        if entry.get("frontmatter_error"):
            continue
        posix = relative.as_posix()
        if folder_prefix and not posix.startswith(folder_prefix.rstrip("/") + "/"):
            continue
        if entry.get("type") == "person":
            continue
        parsed = parse_note((config.vault_root / relative).read_text(encoding="utf-8"))
        if parsed.error:
            continue
        for mention in _person_mentions_in_body(parsed.body):
            name = mention["name"]
            key = normalize_person_name(name)
            if not key:
                continue
            item = by_name.setdefault(
                key,
                {"name": name, "source_notes": [], "source_links": [], "contexts": []},
            )
            if posix not in item["source_notes"]:
                item["source_notes"].append(posix)
                item["source_links"].append(f"[[{relative.stem}]]")
            if mention["context"] and mention["context"] not in item["contexts"]:
                item["contexts"].append(mention["context"])
    return sorted(by_name.values(), key=lambda item: normalize_person_name(item["name"]))


def _existing_person_notes(
    config: AgentConfig, entries: list[dict[str, Any]]
) -> dict[str, str]:
    people: dict[str, str] = {}
    for entry in entries:
        if entry.get("type") != "person":
            continue
        relative = entry["path"]
        title = entry.get("title") or Path(relative).stem
        people[normalize_person_name(str(title))] = relative
        people.setdefault(normalize_person_name(Path(relative).stem), relative)
    return people


def _backlink_operation(
    config: AgentConfig, relative: str, source_links: list[str]
) -> dict[str, Any] | None:
    path = config.vault_root / relative
    if not path.is_file():
        return None
    parsed = parse_note(path.read_text(encoding="utf-8"))
    if parsed.error:
        return None
    existing = parsed.frontmatter.get("related")
    existing_list = [str(item) for item in existing] if isinstance(existing, list) else []
    additions = [link for link in source_links if link not in existing_list]
    if not additions:
        return None
    return {
        "op": "update_frontmatter",
        "path": relative,
        "set": {"related": existing_list + additions},
        "remove": [],
    }


def _classification_context(candidate: dict[str, Any]) -> str:
    lines = [f"Person: {candidate['name']}", "", "Mentions:"]
    for context in candidate["contexts"][:20]:
        lines.append(f"- {context}")
    if not candidate["contexts"]:
        lines.append(f"- mentioned in {len(candidate['source_notes'])} note(s) without extra context")
    return "\n".join(lines)


def _clearly_identified(name: str) -> bool:
    # Require at least a first and last name so single-token mentions go to review.
    return len([token for token in name.split() if token]) >= 2


def _person_note_content(
    *, name: str, kind: str, details: str, source_links: list[str]
) -> str:
    parent = "[[Contacts]]" if kind == "contact" else "[[Authors]]"
    frontmatter = {
        "type": "person",
        "status": "active",
        "domain": "",
        "parent": parent,
        "related": list(source_links),
        "cover": "",
        "source_kind": "",
        "capture_type": "",
    }
    summary = details.strip()
    mentions = "\n".join(f"- {link}" for link in source_links) or "- "
    body = f"# {name}\n\n## Summary\n\n{summary}\n\n## Mentions\n\n{mentions}\n"
    return render_note(frontmatter, body, property_order=ordered_properties_for("person"))
