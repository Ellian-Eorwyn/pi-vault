"""Transcript-file schema onboarding and revision proposal generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import AgentConfig
from .proposals import (
    generate_index_proposal,
    generate_property_proposal,
    generate_template_proposal,
)
from .safety import atomic_write_text
from .schema import COMMON_PROPERTIES, NOTE_TYPES


SUMMARY_PATH = Path("99 System") / "0.01 agent" / "review" / "schema-conversation-summary.md"


@dataclass(frozen=True)
class ConversationDecision:
    kind: str
    values: dict[str, str]
    source: str


def run_schema_conversation(
    config: AgentConfig,
    *,
    conversation_file: str,
    overwrite_proposal: bool = False,
    include_current_schema_summary: bool = False,
) -> tuple[int, str]:
    source_path = Path(conversation_file).expanduser()
    if not source_path.is_absolute():
        source_path = config.vault_root / source_path
    if not source_path.exists():
        return 1, f"vault-agent schema-conversation failed\nError: conversation file not found: {source_path}"
    text, errors = _load_conversation(source_path)
    if errors:
        return 1, "vault-agent schema-conversation failed\n" + "\n".join(f"Error: {error}" for error in errors)

    decisions = parse_conversation_decisions(text)
    proposals, proposal_errors = proposals_from_decisions(config, decisions)
    if proposal_errors:
        return 1, "vault-agent schema-conversation failed\n" + "\n".join(f"Error: {error}" for error in proposal_errors)
    if not proposals:
        return 1, "vault-agent schema-conversation failed\nError: no explicit schema, index, or template decisions found"

    if config.dry_run:
        lines = [
            "vault-agent schema-conversation dry run",
            f"Conversation: {source_path}",
            f"Decisions: {len(decisions)}",
            f"Would write proposals: {len(proposals)}",
            "No files were changed.",
        ]
        for proposal in proposals:
            lines.append(f"- {proposal['id']}: {proposal['title']}")
        return 0, "\n".join(lines)

    proposal_dir = config.vault_root / config.paths.review_dir / "proposals"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for proposal in proposals:
        path = proposal_dir / f"{proposal['id']}.json"
        if path.exists() and not overwrite_proposal:
            return 1, f"vault-agent schema-conversation failed\nError: proposal already exists: {path}"
        atomic_write_text(path, json.dumps(proposal, indent=2) + "\n")
        written.append(path)

    summary = render_schema_conversation_summary(
        config,
        conversation=source_path,
        decisions=decisions,
        proposals=proposals,
        include_current_schema_summary=include_current_schema_summary,
    )
    summary_path = config.vault_root / config.paths.review_dir / "schema-conversation-summary.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(summary_path, summary)
    lines = [
        "vault-agent schema-conversation complete",
        f"Conversation: {source_path}",
        f"Decisions: {len(decisions)}",
        f"Proposals written: {len(written)}",
        f"Summary: {summary_path}",
        "Review with `vault-agent review-proposals --dry-run`.",
    ]
    return 0, "\n".join(lines)


def parse_conversation_decisions(text: str) -> list[ConversationDecision]:
    decisions: list[ConversationDecision] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().strip("-* ")
        if not line:
            continue
        normalized = re.sub(r"\s+", " ", line)
        domain = _match_property_decision(normalized, "domain")
        if domain:
            decisions.append(domain)
            continue
        source_kind = _match_property_decision(normalized, "source_kind")
        if source_kind:
            decisions.append(source_kind)
            continue
        capture_type = _match_property_decision(normalized, "capture_type")
        if capture_type:
            decisions.append(capture_type)
            continue
        index = _match_index_decision(normalized)
        if index:
            decisions.append(index)
            continue
        template = _match_template_decision(normalized)
        if template:
            decisions.append(template)
    return _dedupe(decisions)


def proposals_from_decisions(
    config: AgentConfig, decisions: list[ConversationDecision]
) -> tuple[list[dict[str, Any]], list[str]]:
    proposals: list[dict[str, Any]] = []
    errors: list[str] = []
    for decision in decisions:
        if decision.kind == "property":
            proposal, proposal_errors = generate_property_proposal(
                config=config,
                property_name=decision.values["property"],
                allowed_value=decision.values["value"],
                description=decision.values.get("description") or None,
            )
            if proposal_errors:
                errors.extend(proposal_errors)
            else:
                proposal["summary"] += f" Source: {decision.source}"
                proposals.append(proposal)
        elif decision.kind == "index":
            try:
                proposals.append(
                    generate_index_proposal(
                        index_type=decision.values["index_type"],
                        filter_value=decision.values["value"],
                        title=decision.values.get("title") or None,
                        overwrite=True,
                    )
                )
            except ValueError as exc:
                errors.append(str(exc))
        elif decision.kind == "template":
            proposal, proposal_errors = generate_template_proposal(
                config=config,
                note_type=decision.values["note_type"], overwrite=True
            )
            if proposal_errors:
                errors.extend(proposal_errors)
            else:
                proposals.append(proposal)
    return proposals, errors


def render_schema_conversation_summary(
    config: AgentConfig,
    *,
    conversation: Path,
    decisions: list[ConversationDecision],
    proposals: list[dict[str, Any]],
    include_current_schema_summary: bool,
) -> str:
    lines = [
        "# Schema Conversation Summary",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Conversation file: `{conversation}`",
        f"- Proposals generated: {len(proposals)}",
        "",
        "## Decisions Extracted",
        "",
    ]
    for decision in decisions:
        lines.append(f"- `{decision.kind}` {json.dumps(decision.values, sort_keys=True)}")
    lines.extend(["", "## Proposed Changes", ""])
    for proposal in proposals:
        lines.append(f"- `{proposal['id']}` ({proposal['kind']}): {proposal['title']}")
    lines.extend(
        [
            "",
            "## Canonicalization",
            "",
            "These proposals do not change the active vault rules until reviewed, approved, and applied. After approval, run `vault-agent norms-lock --write` so future autonomous runs use the revised schema/template snapshot.",
            "",
        ]
    )
    if include_current_schema_summary:
        lines.extend(["## Current Schema Summary", ""])
        for property_name, spec in COMMON_PROPERTIES.items():
            allowed = spec.get("allowed")
            if allowed:
                lines.append(f"- `{property_name}`: {', '.join(f'`{value}`' for value in allowed)}")
            else:
                lines.append(f"- `{property_name}`: {spec.get('type', 'value')}")
        lines.append("")
    return "\n".join(lines)


def _load_conversation(path: Path) -> tuple[str, list[str]]:
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            return _conversation_json_to_text(data), []
        if path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return _conversation_json_to_text(data), []
        return path.read_text(encoding="utf-8"), []
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        return "", [str(exc)]


def _conversation_json_to_text(data: Any) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        chunks: list[str] = []
        for item in data:
            if isinstance(item, dict):
                role = item.get("role") or item.get("speaker") or "entry"
                content = item.get("content") or item.get("text") or ""
                chunks.append(f"{role}: {content}")
            else:
                chunks.append(str(item))
        return "\n".join(chunks)
    if isinstance(data, dict):
        if isinstance(data.get("messages"), list):
            return _conversation_json_to_text(data["messages"])
        return "\n".join(f"{key}: {value}" for key, value in data.items())
    return str(data)


def _match_property_decision(line: str, property_name: str) -> ConversationDecision | None:
    if property_name not in COMMON_PROPERTIES or "allowed" not in COMMON_PROPERTIES[property_name]:
        return None
    aliases = {
        "domain": r"domain",
        "source_kind": r"source[_ -]?kind|source kind",
        "capture_type": r"capture[_ -]?type|capture type",
    }
    pattern = aliases[property_name]
    match = re.search(
        rf"(?:add|create|use|new|canonical)\s+(?:a\s+)?{pattern}\s*(?:value)?\s*(?:called|named|of|:)?\s*`?([a-z][a-z0-9_-]*)`?(?:\s*[-:]\s*(.+))?",
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            rf"{pattern}\s*[:=]\s*`?([a-z][a-z0-9_-]*)`?(?:\s*[-:]\s*(.+))?",
            line,
            flags=re.IGNORECASE,
        )
    if not match:
        return None
    value = match.group(1).strip().lower()
    description = (match.group(2) or "").strip()
    return ConversationDecision(
        "property",
        {"property": property_name, "value": value, "description": description},
        line,
    )


def _match_index_decision(line: str) -> ConversationDecision | None:
    match = re.search(
        r"(?:create|add|build|generate)\s+(?:an?\s+)?(?:index|dashboard)\s+(?:for|of)\s+(type|domain|parent|project)\s+`?([^`]+?)`?$",
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    index_type = match.group(1).lower()
    value = match.group(2).strip()
    return ConversationDecision("index", {"index_type": index_type, "value": value}, line)


def _match_template_decision(line: str) -> ConversationDecision | None:
    match = re.search(
        r"(?:refresh|update|revise)\s+(?:the\s+)?`?([a-z][a-z0-9_-]*)`?\s+template",
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    note_type = match.group(1).lower()
    if note_type not in NOTE_TYPES:
        return None
    return ConversationDecision("template", {"note_type": note_type}, line)


def _dedupe(decisions: list[ConversationDecision]) -> list[ConversationDecision]:
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    deduped: list[ConversationDecision] = []
    for decision in decisions:
        key = (decision.kind, tuple(sorted(decision.values.items())))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(decision)
    return deduped
