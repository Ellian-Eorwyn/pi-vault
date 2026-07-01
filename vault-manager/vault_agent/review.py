"""Deterministic review and approval workflow for agent proposals."""

from __future__ import annotations

import json
import re
import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .dashboard_layout import GENERATED_END, GENERATED_START
from .frontmatter import parse_note, render_note
from .logging_utils import append_log
from .paths import REVIEW_DIR
from .refine import meaning_preserved
from .safety import atomic_write_text, backup_file, write_text_safely
from .schema import (
    COMMON_PROPERTIES,
    CORE_PROPERTY_ORDER,
    NOTE_TYPES,
    allowed_note_types,
    ordered_properties_for,
)
from .templates import append_missing_headings


PROPOSAL_DIR = REVIEW_DIR / "proposals"
PROPOSED_CHANGES = REVIEW_DIR / "proposed-changes.md"
AGENT_REVIEW = REVIEW_DIR / "agent-review.md"
ALLOWED_KINDS = {
    "action-queue",
    "artifact-import",
    "schema-change",
    "index-note",
    "template-change",
    "cleanup",
    "folder-organization",
    "base-hierarchy",
    "inbox-sort",
    "vault-layout",
    "note-refinement",
    "people-extraction",
    "property-remap",
    "metadata-normalization",
}
ALLOWED_WRITE_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".base"}


@dataclass
class Proposal:
    path: Path
    data: dict[str, Any]
    errors: list[str] = field(default_factory=list)

    @property
    def proposal_id(self) -> str:
        value = self.data.get("id")
        return value if isinstance(value, str) and value.strip() else self.path.stem

    @property
    def status(self) -> str:
        value = self.data.get("status", "pending")
        return value if isinstance(value, str) else "invalid"

    @property
    def title(self) -> str:
        value = self.data.get("title")
        return value if isinstance(value, str) and value.strip() else self.proposal_id


def run_review_proposals(
    config: AgentConfig,
    *,
    apply_approved: bool = False,
    agent_review: bool = False,
    approve_safe: bool = False,
    approve_id: str | None = None,
    approval_note: str | None = None,
    expected_operations: int | None = None,
    max_operations: int = 25,
    include_schema: bool = False,
    proposal_id: str | None = None,
    proposal_dir: str | None = None,
) -> tuple[int, str]:
    directory = _proposal_directory(config, proposal_dir)
    proposals = load_proposals(directory)
    selected_id = proposal_id or approve_id
    selected = _filter_proposals(proposals, selected_id)
    reviewed = 0
    newly_approved = 0
    explicitly_approved = 0
    review_lines: list[str] = []
    explicit_errors = _explicit_approval_errors(
        proposals,
        approve_id=approve_id,
        approval_note=approval_note,
        expected_operations=expected_operations,
    )
    if selected_id and not selected and not approve_id:
        explicit_errors.append(f"proposal not found: {selected_id}")

    if agent_review:
        review_lines = render_agent_review(
            selected,
            max_operations=max_operations,
            include_schema=include_schema,
        )
        reviewed = len(selected)
        if approve_safe and not config.dry_run:
            for proposal in selected:
                if proposal.status != "pending" or proposal.errors:
                    continue
                decision, _reason = agent_review_decision(
                    proposal,
                    max_operations=max_operations,
                    include_schema=include_schema,
                )
                if decision != "approve":
                    continue
                _mark_approved(proposal)
                newly_approved += 1
            proposals = load_proposals(directory)
            selected = _filter_proposals(proposals, selected_id)

    if approve_id and not config.dry_run and not explicit_errors:
        proposal = _proposal_by_id(proposals, approve_id)
        if proposal is not None:
            _mark_explicitly_approved(
                proposal,
                approval_note=approval_note or "",
                expected_operations=expected_operations,
            )
            explicitly_approved = 1
        proposals = load_proposals(directory)
        selected = _filter_proposals(proposals, selected_id)

    invalid = [proposal for proposal in selected if proposal.errors]
    approved = [
        proposal
        for proposal in selected
        if not proposal.errors and proposal.status == "approved"
    ]

    if config.dry_run:
        lines = [
            "vault-agent review-proposals dry run",
            f"Proposal directory: {directory}",
            f"Proposals: {len(selected)}" if selected_id else f"Proposals: {len(proposals)}",
            f"Invalid: {len(invalid)}",
            f"Approved: {len(approved)}",
        ]
        if selected_id:
            lines.append(f"Proposal filter: {selected_id}")
        if approve_id:
            lines.append(f"Would explicitly approve proposal: {approve_id}")
        if explicit_errors:
            lines.extend(f"Error: {error}" for error in explicit_errors)
        if apply_approved:
            lines.append(f"Would apply approved proposals: {len(approved)}")
        if agent_review:
            lines.append(f"Would render agent review for proposals: {reviewed}")
            if approve_safe:
                would_approve = sum(
                    1
                    for proposal in selected
                    if proposal.status == "pending"
                    and not proposal.errors
                    and agent_review_decision(
                        proposal,
                        max_operations=max_operations,
                        include_schema=include_schema,
                    )[0]
                    == "approve"
                )
                lines.append(f"Would approve safe pending proposals: {would_approve}")
        lines.append("No files were changed.")
        if agent_review and review_lines:
            lines.extend(["", "\n".join(review_lines).rstrip()])
        if proposals:
            displayed = selected if selected_id else proposals
            lines.extend(["", render_proposed_changes(displayed).rstrip()])
        return (1 if invalid or explicit_errors else 0), "\n".join(lines)

    backup_root = config.vault_root / config.paths.agent_dir / "backups"

    applied = 0
    apply_errors: list[str] = list(explicit_errors)
    if apply_approved and invalid:
        apply_errors.append("invalid proposals must be fixed or removed before applying approved proposals")
    elif apply_approved:
        for proposal in approved:
            errors = apply_proposal(config, proposal)
            if errors:
                apply_errors.extend(f"{proposal.path.name}: {error}" for error in errors)
                continue
            _mark_applied(proposal)
            applied += 1

    final_report = render_proposed_changes(load_proposals(directory))
    write_text_safely(
        config.vault_root / config.paths.review_dir / "proposed-changes.md",
        final_report,
        backup_root=backup_root,
    )
    if agent_review:
        write_text_safely(
            config.vault_root / config.paths.review_dir / "agent-review.md",
            "\n".join(
                render_agent_review(
                    load_proposals(directory),
                    max_operations=max_operations,
                    include_schema=include_schema,
                )
            )
            + "\n",
            backup_root=backup_root,
        )

    append_log(
        config.vault_root,
        "review-proposals",
        [
            f"proposals {len(proposals)}",
            f"invalid {len(invalid)}",
            f"approved {len(approved)}",
            f"agent reviewed {reviewed}",
            f"agent approved {newly_approved}",
            f"explicit approved {explicitly_approved}",
            f"applied {applied}",
            f"errors {len(apply_errors)}",
        ],
    )
    lines = [
        "vault-agent review-proposals complete",
        f"Proposals: {len(selected)}" if selected_id else f"Proposals: {len(proposals)}",
        f"Invalid: {len(invalid)}",
        f"Approved: {len(approved)}",
        f"Agent reviewed: {reviewed}",
        f"Agent approved: {newly_approved}",
        f"Explicit approved: {explicitly_approved}",
        f"Applied: {applied}",
        "Review file updated.",
    ]
    if selected_id:
        lines.append(f"Proposal filter: {selected_id}")
    if apply_errors:
        lines.extend(f"Error: {error}" for error in apply_errors)
    return (1 if invalid or apply_errors else 0), "\n".join(lines)


def load_proposals(directory: Path) -> list[Proposal]:
    if not directory.exists():
        return []
    proposals: list[Proposal] = []
    for path in sorted(directory.glob("*.json")):
        proposals.append(_load_proposal(path))
    return proposals


def _filter_proposals(proposals: list[Proposal], proposal_id: str | None) -> list[Proposal]:
    if proposal_id is None:
        return proposals
    return [proposal for proposal in proposals if proposal.proposal_id == proposal_id]


def _proposal_by_id(proposals: list[Proposal], proposal_id: str) -> Proposal | None:
    for proposal in proposals:
        if proposal.proposal_id == proposal_id:
            return proposal
    return None


def _explicit_approval_errors(
    proposals: list[Proposal],
    *,
    approve_id: str | None,
    approval_note: str | None,
    expected_operations: int | None,
) -> list[str]:
    if approve_id is None:
        return []
    errors: list[str] = []
    note = approval_note.strip() if isinstance(approval_note, str) else ""
    if not note:
        errors.append("--approval-note is required with --approve")
    if expected_operations is None:
        errors.append("--expected-operations is required with --approve")
    elif expected_operations < 0:
        errors.append("--expected-operations must be non-negative")
    proposal = _proposal_by_id(proposals, approve_id)
    if proposal is None:
        errors.append(f"proposal not found: {approve_id}")
        return errors
    if proposal.errors:
        errors.extend(f"{proposal.path.name}: {error}" for error in proposal.errors)
    if proposal.status != "pending":
        errors.append(f"proposal {approve_id} status is {proposal.status}, not pending")
    operations = proposal.data.get("operations")
    operation_count = len(operations) if isinstance(operations, list) else 0
    if expected_operations is not None and expected_operations != operation_count:
        errors.append(
            f"proposal {approve_id} has {operation_count} operation(s), expected {expected_operations}"
        )
    return errors


def render_proposed_changes(proposals: list[Proposal]) -> str:
    lines = ["# Proposed Changes", ""]
    if not proposals:
        lines.append("No proposal files found.")
        return "\n".join(lines) + "\n"

    for proposal in proposals:
        lines.extend(
            [
                f"## {proposal.title}",
                "",
                f"- File: `{proposal.path.name}`",
                f"- ID: `{proposal.proposal_id}`",
                f"- Kind: `{proposal.data.get('kind', '')}`",
                f"- Status: `{proposal.status}`",
            ]
        )
        summary = proposal.data.get("summary")
        if isinstance(summary, str) and summary.strip():
            lines.append(f"- Summary: {summary.strip()}")
        operations = proposal.data.get("operations")
        if isinstance(operations, list):
            lines.append(f"- Operations: {len(operations)}")
            for operation in operations:
                if isinstance(operation, dict):
                    lines.append(
                        f"  - `{operation.get('op', '')}` `{operation.get('path', '')}`"
                    )
        if proposal.errors:
            lines.append("- Validation: failed")
            lines.extend(f"  - {error}" for error in proposal.errors)
        else:
            lines.append("- Validation: passed")
        lines.append("")
    return "\n".join(lines)


def render_agent_review(
    proposals: list[Proposal],
    *,
    max_operations: int = 25,
    include_schema: bool = False,
) -> list[str]:
    lines = ["# Agent Proposal Review", ""]
    if not proposals:
        lines.append("No proposal files found.")
        return lines
    for proposal in proposals:
        decision, reason = agent_review_decision(
            proposal,
            max_operations=max_operations,
            include_schema=include_schema,
        )
        lines.extend(
            [
                f"## {proposal.title}",
                "",
                f"- File: `{proposal.path.name}`",
                f"- Status: `{proposal.status}`",
                f"- Kind: `{proposal.data.get('kind', '')}`",
                f"- Decision: `{decision}`",
                f"- Reason: {reason}",
                "",
            ]
        )
    return lines


def agent_review_decision(
    proposal: Proposal,
    *,
    max_operations: int = 25,
    include_schema: bool = False,
) -> tuple[str, str]:
    if proposal.errors:
        return "defer", "proposal validation failed"
    if proposal.status != "pending":
        return "defer", f"proposal status is {proposal.status}"
    kind = proposal.data.get("kind")
    if kind == "schema-change" and not include_schema:
        return "defer", "schema changes require explicit include-schema"
    operations = proposal.data.get("operations")
    if not isinstance(operations, list) or not operations:
        return "defer", "proposal has no operations"
    if len(operations) > max_operations:
        return "defer", f"operation count {len(operations)} exceeds limit {max_operations}"
    for operation in operations:
        if not isinstance(operation, dict):
            return "defer", "operation is not an object"
        op = operation.get("op")
        path = operation.get("path", "")
        if op not in {
            "write_file",
            "update_frontmatter",
            "organize_note",
            "create_directory",
            "move_note",
        }:
            return "defer", f"unsupported operation {op}"
        if op in {"create_directory", "move_note"} and proposal.data.get(
            "automation_safe"
        ) is not True:
            return "defer", f"{op} requires explicit automation_safe approval"
    return "approve", "valid bounded proposal with supported operations"


def apply_proposal(config: AgentConfig, proposal: Proposal) -> list[str]:
    operations = proposal.data.get("operations")
    if not isinstance(operations, list):
        return ["operations must be a list"]
    errors = _preflight_operations(config, operations)
    if errors:
        return errors
    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            errors.append(f"operation {index} must be an object")
            continue
        op = operation.get("op")
        if op == "write_file":
            errors.extend(_apply_write_file(config, operation))
        elif op == "update_frontmatter":
            errors.extend(_apply_update_frontmatter(config, operation))
        elif op == "organize_note":
            errors.extend(_apply_organize_note(config, operation))
        elif op == "create_directory":
            errors.extend(_apply_create_directory(config, operation))
        elif op == "move_note":
            errors.extend(_apply_move_note(config, operation))
        elif op == "restructure_body":
            errors.extend(_apply_restructure_body(config, operation))
        elif op == "add_property_aliases":
            errors.extend(_apply_add_property_aliases(config, operation))
        elif op == "normalize_metadata":
            errors.extend(_apply_normalize_metadata(config, operation))
        else:
            errors.append(f"operation {index} has unsupported op `{op}`")
    return errors


def _apply_add_property_aliases(config: AgentConfig, operation: dict[str, Any]) -> list[str]:
    aliases = operation.get("aliases")
    if not isinstance(aliases, dict) or not aliases:
        return ["add_property_aliases requires a non-empty `aliases` object"]
    cfg_path = config.vault_root / config.paths.agent_dir / "config.yaml"
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    except (OSError, yaml.YAMLError) as exc:
        return [f"could not read {cfg_path.name}: {exc}"]
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return [f"{cfg_path.name} is not a mapping"]
    legacy = data.setdefault("legacy_metadata", {})
    if not isinstance(legacy, dict):
        return [f"{cfg_path.name} legacy_metadata is not a mapping"]
    prop_aliases = legacy.setdefault("property_aliases", {})
    if not isinstance(prop_aliases, dict):
        return [f"{cfg_path.name} legacy_metadata.property_aliases is not a mapping"]
    for old, target in aliases.items():
        if isinstance(old, str) and isinstance(target, str) and old and target:
            prop_aliases[old] = target
    write_text_safely(cfg_path, yaml.safe_dump(data, sort_keys=False))
    return []


def _load_proposal(path: Path) -> Proposal:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Proposal(path, {}, [f"could not read proposal JSON: {exc}"])
    proposal = Proposal(path, data if isinstance(data, dict) else {})
    proposal.errors.extend(_validate_proposal(proposal))
    return proposal


def _validate_proposal(proposal: Proposal) -> list[str]:
    data = proposal.data
    errors: list[str] = []
    if not isinstance(data, dict) or not data:
        return ["proposal must be a JSON object"]
    if proposal.status not in {"pending", "approved", "rejected", "applied"}:
        errors.append("status must be pending, approved, rejected, or applied")
    if data.get("kind") not in ALLOWED_KINDS:
        errors.append("kind must be one of: " + ", ".join(sorted(ALLOWED_KINDS)))
    if data.get("kind") == "artifact-import":
        errors.extend(_validate_artifact_provenance(data.get("provenance")))
    operations = data.get("operations")
    if not isinstance(operations, list) or not operations:
        errors.append("operations must be a non-empty list")
        return errors
    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            errors.append(f"operation {index} must be an object")
            continue
        op = operation.get("op")
        if op == "write_file":
            errors.extend(_validate_write_file(operation, index))
        elif op == "update_frontmatter":
            errors.extend(_validate_update_frontmatter(operation, index))
        elif op == "organize_note":
            errors.extend(_validate_organize_note(operation, index))
        elif op == "create_directory":
            errors.extend(_validate_create_directory(operation, index))
        elif op == "move_note":
            errors.extend(_validate_move_note(operation, index))
        elif op == "restructure_body":
            errors.extend(_validate_restructure_body(operation, index))
        elif op == "add_property_aliases":
            errors.extend(_validate_add_property_aliases(operation, index))
        elif op == "normalize_metadata":
            errors.extend(_validate_normalize_metadata(operation, index))
        else:
            errors.append(f"operation {index} has unsupported op `{op}`")
    return errors


def _validate_add_property_aliases(operation: dict[str, Any], index: int) -> list[str]:
    aliases = operation.get("aliases")
    if not isinstance(aliases, dict) or not aliases:
        return [f"operation {index} add_property_aliases requires a non-empty `aliases` object"]
    errors: list[str] = []
    for old, target in aliases.items():
        if not isinstance(old, str) or not old:
            errors.append(f"operation {index} alias key must be a non-empty string")
        if not isinstance(target, str) or not target:
            errors.append(f"operation {index} alias target must be a non-empty string")
    return errors


def _validate_artifact_provenance(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["artifact-import provenance must be an object"]
    errors: list[str] = []
    source_path = value.get("source_path")
    if not isinstance(source_path, str) or not Path(source_path).is_absolute():
        errors.append("artifact-import provenance source_path must be absolute")
    source_sha256 = value.get("source_sha256")
    if not isinstance(source_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None:
        errors.append("artifact-import provenance source_sha256 must be lowercase SHA-256")
    for key in ("source_task_id", "source_operation"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            errors.append(f"artifact-import provenance {key} must be a string or null")
    return errors


def _validate_write_file(operation: dict[str, Any], index: int) -> list[str]:
    errors: list[str] = []
    path = operation.get("path")
    if not isinstance(path, str) or not path.strip():
        errors.append(f"operation {index} path is required")
    else:
        path_error = _validate_relative_path(path, index)
        if path_error:
            errors.append(path_error)
        elif Path(path).suffix not in ALLOWED_WRITE_SUFFIXES:
            errors.append(f"operation {index} path has unsupported suffix")
    if not isinstance(operation.get("content"), str):
        errors.append(f"operation {index} content must be a string")
    if operation.get("if_exists", "fail") not in {"fail", "overwrite"}:
        errors.append(f"operation {index} if_exists must be fail or overwrite")
    if not isinstance(operation.get("merge_generated", False), bool):
        errors.append(f"operation {index} merge_generated must be boolean")
    return errors


def _validate_update_frontmatter(operation: dict[str, Any], index: int) -> list[str]:
    errors: list[str] = []
    path = operation.get("path")
    if not isinstance(path, str) or not path.strip():
        errors.append(f"operation {index} path is required")
    else:
        path_error = _validate_relative_path(path, index)
        if path_error:
            errors.append(path_error)
        elif Path(path).suffix != ".md":
            errors.append(f"operation {index} update_frontmatter path must be Markdown")
    set_values = operation.get("set", {})
    if not isinstance(set_values, dict):
        errors.append(f"operation {index} set must be an object")
    else:
        for key, value in set_values.items():
            # Concrete approval against the vault's schema (built-in + custom properties)
            # happens at apply time; here we only require a property-slug key, and we still
            # value-validate the built-in controlled properties.
            if not isinstance(key, str) or re.fullmatch(r"[a-z][a-z0-9_-]*", key) is None:
                errors.append(f"operation {index} set key `{key}` must be a property slug")
                continue
            allowed = COMMON_PROPERTIES.get(key, {}).get("allowed")
            if allowed and value not in allowed:
                errors.append(f"operation {index} invalid {key} `{value}`")
            if key == "related" and not isinstance(value, list):
                errors.append(f"operation {index} related must be a list")
    remove = operation.get("remove", [])
    if not isinstance(remove, list):
        errors.append(f"operation {index} remove must be a list")
    else:
        for key in remove:
            if not isinstance(key, str):
                errors.append(f"operation {index} remove entries must be strings")
            elif key in COMMON_PROPERTIES:
                errors.append(f"operation {index} cannot remove core property `{key}`")
    return errors


def _validate_organize_note(operation: dict[str, Any], index: int) -> list[str]:
    errors = _validate_update_frontmatter(operation, index)
    apply_template = operation.get("apply_template", False)
    if not isinstance(apply_template, bool):
        errors.append(f"operation {index} apply_template must be boolean")
    summary = operation.get("summary", "")
    if not isinstance(summary, str):
        errors.append(f"operation {index} summary must be a string")
    note_type = operation.get("set", {}).get("type")
    # The concrete allowed-type check (built-in or schema-defined) runs at apply time
    # where the vault root is available; here we only require a non-empty type string.
    if apply_template and (not isinstance(note_type, str) or not note_type):
        errors.append(f"operation {index} apply_template requires a type")
    return errors


def _validate_create_directory(operation: dict[str, Any], index: int) -> list[str]:
    path = operation.get("path")
    if not isinstance(path, str) or not path.strip():
        return [f"operation {index} path is required"]
    path_error = _validate_relative_path(path, index)
    if path_error:
        return [path_error]
    if operation.get("if_exists", "preserve") not in {"fail", "preserve"}:
        return [f"operation {index} if_exists must be fail or preserve"]
    return []


def _validate_move_note(operation: dict[str, Any], index: int) -> list[str]:
    errors: list[str] = []
    source = operation.get("path")
    destination = operation.get("destination")
    for label, value in (("path", source), ("destination", destination)):
        if not isinstance(value, str) or not value.strip():
            errors.append(f"operation {index} {label} is required")
            continue
        path_error = _validate_relative_path(value, index)
        if path_error:
            errors.append(path_error.replace(" path ", f" {label} ", 1))
        elif Path(value).suffix.lower() != ".md":
            errors.append(f"operation {index} {label} must be Markdown")
    if isinstance(source, str) and isinstance(destination, str) and source == destination:
        errors.append(f"operation {index} destination must differ from path")
    if not isinstance(operation.get("update_links", True), bool):
        errors.append(f"operation {index} update_links must be boolean")
    return errors


def _validate_restructure_body(operation: dict[str, Any], index: int) -> list[str]:
    errors: list[str] = []
    path = operation.get("path")
    if not isinstance(path, str) or not path.strip():
        errors.append(f"operation {index} path is required")
    else:
        path_error = _validate_relative_path(path, index)
        if path_error:
            errors.append(path_error)
        elif Path(path).suffix != ".md":
            errors.append(f"operation {index} restructure_body path must be Markdown")
    body = operation.get("body")
    if not isinstance(body, str) or not body.strip():
        errors.append(f"operation {index} body must be a non-empty string")
    return errors


def _validate_normalize_metadata(operation: dict[str, Any], index: int) -> list[str]:
    errors = _validate_update_frontmatter(operation, index)
    body = operation.get("body")
    if body is not None and not isinstance(body, str):
        errors.append(f"operation {index} body must be a string")
    return errors


def _apply_write_file(config: AgentConfig, operation: dict[str, Any]) -> list[str]:
    try:
        path = _resolve_vault_path(config.vault_root, operation["path"])
    except ValueError as exc:
        return [str(exc)]
    allowed_error = _write_allowed(config, path.relative_to(config.vault_root))
    if allowed_error:
        return [allowed_error]
    if path.exists() and operation.get("if_exists", "fail") == "fail":
        return [f"target already exists: {operation['path']}"]
    content = operation["content"]
    if path.exists() and operation.get("merge_generated", False):
        content = _merge_generated_section(path.read_text(encoding="utf-8"), content)
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    write_text_safely(path, content, backup_root=backup_root)
    return []


def _merge_generated_section(existing: str, generated: str) -> str:
    if GENERATED_START not in existing or GENERATED_END not in existing:
        return generated
    if GENERATED_START not in generated or GENERATED_END not in generated:
        return generated
    replacement = generated.split(GENERATED_START, 1)[1].split(GENERATED_END, 1)[0]
    before, remainder = existing.split(GENERATED_START, 1)
    _old, after = remainder.split(GENERATED_END, 1)
    return before + GENERATED_START + replacement + GENERATED_END + after


def _apply_update_frontmatter(config: AgentConfig, operation: dict[str, Any]) -> list[str]:
    try:
        path = _resolve_vault_path(config.vault_root, operation["path"])
    except ValueError as exc:
        return [str(exc)]
    relative = path.relative_to(config.vault_root)
    if relative.is_relative_to(config.paths.system_dir):
        return [f"update_frontmatter cannot target {config.paths.system_dir}"]
    if not path.exists():
        return [f"target note does not exist: {operation['path']}"]
    text = path.read_text(encoding="utf-8")
    parsed = parse_note(text)
    if parsed.error:
        return [parsed.error]
    frontmatter = dict(parsed.frontmatter)
    for key in operation.get("remove", []):
        frontmatter.pop(key, None)
    frontmatter.update(operation.get("set", {}))
    rendered = render_note(
        frontmatter,
        parsed.body,
        property_order=ordered_properties_for(frontmatter.get("type")),
    )
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    if rendered != text:
        write_text_safely(path, rendered, backup_root=backup_root)
    return []


def _apply_normalize_metadata(config: AgentConfig, operation: dict[str, Any]) -> list[str]:
    try:
        path = _resolve_vault_path(config.vault_root, operation["path"])
    except ValueError as exc:
        return [str(exc)]
    relative = path.relative_to(config.vault_root)
    if relative.is_relative_to(config.paths.system_dir):
        return [f"normalize_metadata cannot target {config.paths.system_dir}"]
    if not path.exists():
        return [f"target note does not exist: {operation['path']}"]
    text = path.read_text(encoding="utf-8")
    parsed = parse_note(text)
    if parsed.error:
        return [parsed.error]
    frontmatter = dict(parsed.frontmatter)
    for key in operation.get("remove", []):
        frontmatter.pop(key, None)
    frontmatter.update(operation.get("set", {}))
    body = operation.get("body", parsed.body)
    rendered = render_note(
        frontmatter,
        body,
        property_order=ordered_properties_for(frontmatter.get("type")),
    )
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    if rendered != text:
        write_text_safely(path, rendered, backup_root=backup_root)
    return []


def _apply_organize_note(config: AgentConfig, operation: dict[str, Any]) -> list[str]:
    try:
        path = _resolve_vault_path(config.vault_root, operation["path"])
    except ValueError as exc:
        return [str(exc)]
    relative = path.relative_to(config.vault_root)
    if relative.is_relative_to(config.paths.system_dir):
        return [f"organize_note cannot target {config.paths.system_dir}"]
    if not path.exists():
        return [f"target note does not exist: {operation['path']}"]
    text = path.read_text(encoding="utf-8")
    parsed = parse_note(text)
    if parsed.error and not parsed.has_frontmatter:
        return [parsed.error]
    frontmatter = {} if parsed.error else dict(parsed.frontmatter)
    for key in operation.get("remove", []):
        frontmatter.pop(key, None)
    frontmatter.update(operation.get("set", {}))
    body = parsed.body
    note_type = frontmatter.get("type")
    if operation.get("apply_template", False) and note_type in allowed_note_types(config.vault_root):
        body, _headings = append_missing_headings(body, note_type, vault_root=config.vault_root)
    summary = operation.get("summary", "").strip()
    if summary:
        body = _apply_summary(body, summary)
    rendered = render_note(
        frontmatter,
        body,
        property_order=ordered_properties_for(note_type),
    )
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    if rendered != text:
        write_text_safely(path, rendered, backup_root=backup_root)
    return []


def _apply_restructure_body(config: AgentConfig, operation: dict[str, Any]) -> list[str]:
    try:
        path = _resolve_vault_path(config.vault_root, operation["path"])
    except ValueError as exc:
        return [str(exc)]
    relative = path.relative_to(config.vault_root)
    if relative.is_relative_to(config.paths.system_dir):
        return [f"restructure_body cannot target {config.paths.system_dir}"]
    if not path.exists():
        return [f"target note does not exist: {operation['path']}"]
    text = path.read_text(encoding="utf-8")
    parsed = parse_note(text)
    if parsed.error:
        return [parsed.error]
    new_body = operation["body"]
    # Final, apply-time meaning gate (defense in depth): never let a body rewrite
    # drop or substitute the author's words, even if the proposal was hand-edited.
    ok, guard = meaning_preserved(
        parsed.body,
        new_body,
        max_added=config.refine_max_added_words,
        allow_dropped=config.refine_allow_dropped_words,
    )
    if not ok:
        detail = json.dumps({"dropped": guard["dropped"], "added": guard["added"]}, sort_keys=True)
        return [f"restructure_body would change wording for {operation['path']}: {detail}"]
    # Preserve the existing frontmatter block byte-for-byte; only the body changes.
    prefix = text[: len(text) - len(parsed.body)]
    rendered = prefix + new_body
    if not rendered.endswith("\n"):
        rendered += "\n"
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    if rendered != text:
        write_text_safely(path, rendered, backup_root=backup_root)
    return []


def _apply_summary(body: str, summary: str) -> str:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "## Summary":
            next_heading = len(lines)
            for cursor in range(index + 1, len(lines)):
                if lines[cursor].startswith("## "):
                    next_heading = cursor
                    break
            replacement = lines[: index + 1] + ["", summary, ""] + lines[next_heading:]
            return "\n".join(replacement).rstrip() + "\n"
    return body.rstrip() + "\n\n## Summary\n\n" + summary + "\n"


def _proposal_directory(config: AgentConfig, proposal_dir: str | None) -> Path:
    if proposal_dir:
        path = Path(proposal_dir).expanduser()
        return path if path.is_absolute() else config.vault_root / path
    return config.vault_root / config.paths.review_dir / "proposals"


def _resolve_vault_path(vault_root: Path, path: str) -> Path:
    target = Path(path)
    if target.is_absolute():
        raise ValueError(f"path must be relative to vault root: {path}")
    resolved = (vault_root / target).resolve()
    root = vault_root.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes vault root: {path}")
    return resolved


def _write_allowed(config: AgentConfig, relative: Path) -> str | None:
    if ".git" in relative.parts:
        return "writes under .git are not allowed"
    if relative.is_relative_to(config.paths.agent_dir / "backups"):
        return "writes under agent backups are not allowed"
    if relative.is_relative_to(config.paths.agent_dir / "logs"):
        return "writes under agent logs are not allowed"
    protected_agent_files = {
        config.paths.agent_dir / "manifest.json",
        config.paths.agent_dir / "norms-lock.json",
        config.paths.agent_dir / "state.json",
        config.paths.agent_dir / "processing-state.json",
    }
    if relative in protected_agent_files:
        return f"writes to generated agent state are not allowed: {relative.as_posix()}"
    if relative.is_relative_to(config.paths.retrieval_dir):
        return "writes under generated retrieval files are not allowed"
    if relative.is_relative_to(config.paths.agent_dir / "reports"):
        return "writes under generated report files are not allowed"
    return None


def _validate_relative_path(path: str, index: int) -> str | None:
    target = Path(path)
    if target.is_absolute():
        return f"operation {index} path must be relative to vault root"
    if ".." in target.parts:
        return f"operation {index} path cannot contain parent directory references"
    return None


def _mark_applied(proposal: Proposal) -> None:
    data = dict(proposal.data)
    data["status"] = "applied"
    data["applied_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_text(proposal.path, json.dumps(data, indent=2) + "\n")


def _mark_approved(proposal: Proposal) -> None:
    data = dict(proposal.data)
    data["status"] = "approved"
    data["approved_at"] = datetime.now(timezone.utc).isoformat()
    data["approved_by"] = "vault-agent review-proposals --agent-review --approve-safe"
    atomic_write_text(proposal.path, json.dumps(data, indent=2) + "\n")


def _mark_explicitly_approved(
    proposal: Proposal,
    *,
    approval_note: str,
    expected_operations: int | None,
) -> None:
    data = dict(proposal.data)
    data["status"] = "approved"
    data["approved_at"] = datetime.now(timezone.utc).isoformat()
    data["approved_by"] = "vault-agent review-proposals --approve"
    data["approval_note"] = approval_note
    if expected_operations is not None:
        data["expected_operations"] = expected_operations
    atomic_write_text(proposal.path, json.dumps(data, indent=2) + "\n")


def _validate_schema_json_write(content: str) -> list[str]:
    """Deterministic guard on model-authored `schema.json` writes.

    Ensures the new schema is well-formed, keeps every built-in note type, and is
    internally consistent (allowed types are defined and vice versa, custom type names
    are safe slugs). This is the schema analogue of the note-body word-preservation
    guard: a backstop so a model can extend the vault canon but never corrupt it.
    """
    try:
        schema = json.loads(content)
    except json.JSONDecodeError as exc:
        return [f"schema.json is not valid JSON: {exc}"]
    if not isinstance(schema, dict):
        return ["schema.json must be a JSON object"]
    errors: list[str] = []
    note_types = schema.get("note_types")
    if not isinstance(note_types, dict):
        errors.append("schema.json note_types must be an object")
        note_types = {}
    core = schema.get("core_properties")
    type_spec = core.get("type") if isinstance(core, dict) else None
    type_allowed = type_spec.get("allowed") if isinstance(type_spec, dict) else None
    if not isinstance(core, dict):
        errors.append("schema.json core_properties must be an object")
    if not isinstance(type_allowed, list):
        errors.append("schema.json core_properties.type.allowed must be a list")
        type_allowed = []
    missing_builtin = sorted(t for t in NOTE_TYPES if t not in note_types)
    if missing_builtin:
        errors.append(
            "schema.json must keep built-in note types: " + ", ".join(missing_builtin)
        )
    for value in type_allowed:
        if isinstance(value, str) and value and value not in note_types:
            errors.append(f"schema.json type `{value}` is allowed but not defined in note_types")
    for name in note_types:
        if not isinstance(name, str) or not name:
            errors.append("schema.json note_types keys must be non-empty strings")
            continue
        if name not in type_allowed:
            errors.append(f"schema.json note_type `{name}` is missing from core_properties.type.allowed")
        if name not in NOTE_TYPES and re.fullmatch(r"[a-z][a-z0-9_-]*", name) is None:
            errors.append(f"schema.json custom note_type `{name}` must be a lowercase slug")
    return errors


def _preflight_operations(
    config: AgentConfig, operations: list[dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    planned_directories: set[Path] = set()
    destinations: set[Path] = set()
    write_targets: set[Path] = set()
    for index, operation in enumerate(operations, start=1):
        op = operation.get("op")
        if op in {
            "write_file",
            "update_frontmatter",
            "organize_note",
            "restructure_body",
            "normalize_metadata",
        }:
            relative = Path(operation["path"])
            target = config.vault_root / relative
            allowed_error = _write_allowed(config, relative)
            if allowed_error:
                errors.append(f"operation {index} {allowed_error}")
            if relative in write_targets:
                errors.append(f"operation {index} duplicates target: {relative.as_posix()}")
            if relative in destinations:
                errors.append(
                    f"operation {index} conflicts with move destination: {relative.as_posix()}"
                )
            write_targets.add(relative)
            if op == "write_file":
                if target.exists() and operation.get("if_exists", "fail") == "fail":
                    errors.append(f"operation {index} target already exists: {relative.as_posix()}")
                if relative == config.paths.agent_dir / "schema.json":
                    errors.extend(
                        f"operation {index} {message}"
                        for message in _validate_schema_json_write(operation.get("content", ""))
                    )
            else:
                if relative.is_relative_to(config.paths.system_dir):
                    errors.append(f"operation {index} cannot edit notes under the system folder")
                if not target.is_file():
                    errors.append(f"operation {index} target note does not exist: {relative.as_posix()}")
        if op == "create_directory":
            relative = Path(operation["path"])
            if relative.is_relative_to(config.paths.system_dir):
                errors.append(f"operation {index} cannot create directories under the system folder")
                continue
            target = config.vault_root / relative
            if target.exists() and not target.is_dir():
                errors.append(f"operation {index} target exists and is not a directory")
            elif target.exists() and operation.get("if_exists", "preserve") == "fail":
                errors.append(f"operation {index} directory already exists: {relative.as_posix()}")
            planned_directories.add(relative)
        elif op == "move_note":
            source = Path(operation["path"])
            destination = Path(operation["destination"])
            if source.is_relative_to(config.paths.system_dir) or destination.is_relative_to(
                config.paths.system_dir
            ):
                errors.append(f"operation {index} cannot move notes into or out of the system folder")
                continue
            source_path = config.vault_root / source
            destination_path = config.vault_root / destination
            if not source_path.is_file():
                errors.append(f"operation {index} source note does not exist: {source.as_posix()}")
            if destination_path.exists() or destination in destinations or destination in write_targets:
                errors.append(f"operation {index} destination already exists: {destination.as_posix()}")
            parent = destination.parent
            if not (config.vault_root / parent).is_dir() and parent not in planned_directories:
                errors.append(f"operation {index} destination directory does not exist: {parent.as_posix()}")
            destinations.add(destination)
            if operation.get("update_links", True) and _has_ambiguous_simple_links(
                config, source
            ):
                errors.append(
                    f"operation {index} has ambiguous basename wikilinks for {source.stem}; use path-qualified links first"
                )
    return errors


def _apply_create_directory(
    config: AgentConfig, operation: dict[str, Any]
) -> list[str]:
    path = config.vault_root / operation["path"]
    path.mkdir(parents=True, exist_ok=operation.get("if_exists", "preserve") == "preserve")
    return []


def _apply_move_note(config: AgentConfig, operation: dict[str, Any]) -> list[str]:
    source = config.vault_root / operation["path"]
    destination = config.vault_root / operation["destination"]
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    backup_file(source, backup_root)
    source_relative = source.relative_to(config.vault_root)
    destination_relative = destination.relative_to(config.vault_root)
    source.replace(destination)
    if operation.get("update_links", True):
        _rewrite_inbound_wikilinks(
            config,
            source=source_relative,
            destination=destination_relative,
            backup_root=backup_root,
        )
    return []


WIKILINK_PATTERN = re.compile(
    r"(?P<prefix>!?\[\[)(?P<target>[^\]|#]+)(?P<heading>#[^\]|]+)?(?P<alias>\|[^\]]+)?\]\]"
)


def _rewrite_inbound_wikilinks(
    config: AgentConfig,
    *,
    source: Path,
    destination: Path,
    backup_root: Path,
) -> None:
    old_path = source.with_suffix("").as_posix()
    new_path = destination.with_suffix("").as_posix()
    old_name = source.stem
    new_name = destination.stem

    def replace_link(match: re.Match[str]) -> str:
        target = match.group("target")
        replacement = None
        if target == old_path:
            replacement = new_path
        elif target == old_name:
            replacement = new_name
        if replacement is None:
            return match.group(0)
        return (
            match.group("prefix")
            + replacement
            + (match.group("heading") or "")
            + (match.group("alias") or "")
            + "]]"
        )

    for note in sorted(config.vault_root.rglob("*.md")):
        relative = note.relative_to(config.vault_root)
        if ".git" in relative.parts or relative.is_relative_to(config.paths.system_dir):
            continue
        text = note.read_text(encoding="utf-8")
        rewritten = WIKILINK_PATTERN.sub(replace_link, text)
        if rewritten != text:
            write_text_safely(note, rewritten, backup_root=backup_root)


def _has_ambiguous_simple_links(config: AgentConfig, source: Path) -> bool:
    same_name = [
        path
        for path in config.vault_root.rglob(source.name)
        if not path.relative_to(config.vault_root).is_relative_to(config.paths.system_dir)
    ]
    if len(same_name) <= 1:
        return False
    simple_pattern = re.compile(rf"!?\[\[{re.escape(source.stem)}(?:#|\||\]\])")
    return any(
        simple_pattern.search(path.read_text(encoding="utf-8"))
        for path in config.vault_root.rglob("*.md")
        if not path.relative_to(config.vault_root).is_relative_to(config.paths.system_dir)
    )
