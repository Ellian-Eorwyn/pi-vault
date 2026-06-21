"""Inbox-only deterministic processing."""

from __future__ import annotations

import time
from pathlib import Path

from .config import AgentConfig
from .frontmatter import parse_note, render_note
from .logging_utils import append_log
from .llm import ProposalProvider, validate_proposal, validate_stage_proposal
from .model_blocks import record_model_block
from .paths import paths_for
from .processing_state import mark_stage, stage_complete
from .safety import write_text_safely
from .scanner import scan_vault
from .schema import (
    CORE_PROPERTY_ORDER,
    NOTE_TYPES,
    accepted_properties_for,
    approved_hubs_for,
    default_schema,
    ordered_properties_for,
)
from .templates import append_missing_headings

PROCESSING_STAGES = (
    "frontmatter-shape",
    "classify-type",
    "property-values",
    "template-body",
    "assign-hub",
    "summary",
)


def _load_vault_schema(vault_root: Path) -> dict:
    """Load the vault's approved schema, preferring the locked norms snapshot."""
    from .norms import load_norms_lock

    lock = load_norms_lock(vault_root)
    if isinstance(lock, dict) and isinstance(lock.get("schema"), dict):
        return lock["schema"]
    import json

    path = vault_root / paths_for(vault_root).agent_dir / "schema.json"
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass
    return default_schema()


def select_next_inbox_note(
    vault_root: Path, *, stage: str | None = None, norms_lock_hash: str | None = None
) -> tuple[Path, str] | None:
    return select_next_note(
        vault_root, stage=stage, scope="inbox", norms_lock_hash=norms_lock_hash
    )


def select_target_note(
    vault_root: Path,
    note: str,
    *,
    stage: str | None = None,
    scope: str = "inbox",
    norms_lock_hash: str | None = None,
) -> tuple[Path, str] | None:
    note_path = _resolve_target_note(vault_root, note)
    relative = note_path.relative_to(vault_root)
    vault_paths = paths_for(vault_root)
    if scope == "inbox" and not relative.is_relative_to(vault_paths.inbox_dir):
        return None
    if scope == "vault" and _skip_vault_processing_entry(
        {}, relative, system_dir=vault_paths.system_dir, inbox_dir=vault_paths.inbox_dir
    ):
        return None
    parsed = parse_note(note_path.read_text(encoding="utf-8"))
    if parsed.error:
        return None
    entry = {"path": relative.as_posix(), "frontmatter": parsed.frontmatter}
    next_stage = stage or _next_needed_stage(
        vault_root, note_path, entry, norms_lock_hash=norms_lock_hash
    )
    if not next_stage:
        return None
    if stage and not _stage_needed(
        vault_root, note_path, entry, stage, norms_lock_hash=norms_lock_hash
    ):
        return None
    return note_path, next_stage


def select_next_note(
    vault_root: Path,
    *,
    stage: str | None = None,
    scope: str = "inbox",
    norms_lock_hash: str | None = None,
) -> tuple[Path, str] | None:
    result = scan_vault(vault_root)
    vault_paths = paths_for(vault_root)
    for entry in result.entries:
        path = Path(entry["path"])
        if scope == "inbox" and not path.is_relative_to(vault_paths.inbox_dir):
            continue
        if scope == "vault" and _skip_vault_processing_entry(
            entry,
            path,
            system_dir=vault_paths.system_dir,
            inbox_dir=vault_paths.inbox_dir,
        ):
            continue
        if entry.get("frontmatter_error"):
            continue
        next_stage = stage or _next_needed_stage(
            vault_root, vault_root / path, entry, norms_lock_hash=norms_lock_hash
        )
        if not next_stage:
            continue
        if stage and not _stage_needed(
            vault_root, vault_root / path, entry, stage, norms_lock_hash=norms_lock_hash
        ):
            continue
        return vault_root / path, next_stage
    return None


def next_needed_stage(
    vault_root: Path,
    note_path: Path,
    entry: dict,
    *,
    stage: str | None = None,
    norms_lock_hash: str | None = None,
) -> str | None:
    if stage:
        return (
            stage
            if _stage_needed(
                vault_root, note_path, entry, stage, norms_lock_hash=norms_lock_hash
            )
            else None
        )
    return _next_needed_stage(vault_root, note_path, entry, norms_lock_hash=norms_lock_hash)


def run_process_next(
    config: AgentConfig,
    *,
    proposal_provider: ProposalProvider | None = None,
    stage: str | None = None,
    note: str | None = None,
) -> tuple[int, str]:
    try:
        selected = (
            select_target_note(config.vault_root, note, stage=stage, scope="inbox")
            if note
            else select_next_inbox_note(config.vault_root, stage=stage)
        )
    except ValueError as exc:
        return 1, f"vault-agent process-next failed\nError: {exc}"
    if selected is None:
        if note:
            return 0, f"vault-agent process-next complete\nNo requested inbox stage needs processing: {note}"
        return 0, "vault-agent process-next complete\nNo inbox notes need processing."
    note_path, selected_stage = selected
    relative = note_path.relative_to(config.vault_root).as_posix()
    if config.dry_run:
        return (
            0,
            "vault-agent process-next dry run\n"
            f"Would process `{relative}`.\n"
            f"Stage: {selected_stage}\n"
            "No files were changed.",
        )

    result = process_note(
        config.vault_root,
        note_path,
        proposal_provider=proposal_provider,
        confidence_threshold=config.llm_confidence_threshold,
        preserve_unknown_properties=config.preserve_unknown_properties,
        review_on_warnings=config.review_on_warnings,
        warning_confidence_margin=config.warning_confidence_margin,
        stage=selected_stage,
    )
    append_log(
        config.vault_root,
        "process-next",
        [
            f"processed {relative}",
            f"stage {selected_stage}",
            f"mode {result.mode}",
            f"changed {result.changed}",
            f"errors {len(result.errors)}",
        ],
    )
    if result.errors:
        return (
            1,
            "vault-agent process-next failed\n"
            f"Processed: {relative}\n"
            + "\n".join(f"Error: {error}" for error in result.errors),
        )
    return (
        0,
        "vault-agent process-next complete\n"
        f"Processed: {relative}\n"
        f"Stage: {selected_stage}\n"
        f"Mode: {result.mode}\n"
        f"Changed: {result.changed}",
    )


def run_process_inbox(
    config: AgentConfig,
    *,
    max_notes: int | None = None,
    max_runtime_minutes: int | None = None,
    proposal_provider: ProposalProvider | None = None,
    stage: str | None = None,
    note: str | None = None,
) -> tuple[int, str]:
    processed: list[str] = []
    started = time.monotonic()
    limit = max_notes if max_notes is not None else 5
    runtime_seconds = (max_runtime_minutes if max_runtime_minutes is not None else 10) * 60
    if proposal_provider and limit != 1:
        return (
            1,
            "vault-agent process-inbox failed\n"
            "--proposal-file can only be used when --max-notes 1.",
        )

    while len(processed) < limit and time.monotonic() - started < runtime_seconds:
        try:
            selected = (
                select_target_note(config.vault_root, note, stage=stage, scope="inbox")
                if note
                else select_next_inbox_note(config.vault_root, stage=stage)
            )
        except ValueError as exc:
            return 1, f"vault-agent process-inbox failed\nError: {exc}"
        if selected is None:
            break
        note_path, selected_stage = selected
        relative = note_path.relative_to(config.vault_root).as_posix()
        if config.dry_run:
            processed.append(f"{relative} ({selected_stage})")
            break
        result = process_note(
            config.vault_root,
            note_path,
            proposal_provider=proposal_provider,
            confidence_threshold=config.llm_confidence_threshold,
            preserve_unknown_properties=config.preserve_unknown_properties,
            review_on_warnings=config.review_on_warnings,
            warning_confidence_margin=config.warning_confidence_margin,
            stage=selected_stage,
        )
        if result.errors:
            append_log(
                config.vault_root,
                "process-inbox",
                [f"stopped at {relative}", f"errors {len(result.errors)}"],
            )
            return (
                1,
                "vault-agent process-inbox failed\n"
                f"Stopped at: {relative}\n"
                + "\n".join(f"Error: {error}" for error in result.errors),
            )
        processed.append(relative)

    if config.dry_run:
        return (
            0,
            "vault-agent process-inbox dry run\n"
            + (f"Would process: {processed[0]}\n" if processed else "No inbox notes need processing.\n")
            + "No files were changed.",
        )
    append_log(config.vault_root, "process-inbox", [f"processed {len(processed)} note(s)"])
    return 0, f"vault-agent process-inbox complete\nProcessed: {len(processed)}"


def run_process_vault(
    config: AgentConfig,
    *,
    max_notes: int | None = None,
    max_runtime_minutes: int | None = None,
    proposal_provider: ProposalProvider | None = None,
    stage: str | None = None,
    note: str | None = None,
) -> tuple[int, str]:
    processed: list[str] = []
    started = time.monotonic()
    limit = max_notes if max_notes is not None else 5
    runtime_seconds = (max_runtime_minutes if max_runtime_minutes is not None else 10) * 60
    if proposal_provider and limit != 1:
        return (
            1,
            "vault-agent process-vault failed\n"
            "--proposal-file can only be used when --max-notes 1.",
        )

    while len(processed) < limit and time.monotonic() - started < runtime_seconds:
        try:
            selected = (
                select_target_note(config.vault_root, note, stage=stage, scope="vault")
                if note
                else select_next_note(config.vault_root, stage=stage, scope="vault")
            )
        except ValueError as exc:
            return 1, f"vault-agent process-vault failed\nError: {exc}"
        if selected is None:
            break
        note_path, selected_stage = selected
        relative = note_path.relative_to(config.vault_root).as_posix()
        if config.dry_run:
            processed.append(f"{relative} ({selected_stage})")
            break
        result = process_note(
            config.vault_root,
            note_path,
            proposal_provider=proposal_provider,
            confidence_threshold=config.llm_confidence_threshold,
            preserve_unknown_properties=config.preserve_unknown_properties,
            review_on_warnings=config.review_on_warnings,
            warning_confidence_margin=config.warning_confidence_margin,
            stage=selected_stage,
        )
        if result.errors:
            mark_stage(
                config.vault_root,
                note_path,
                stage=selected_stage,
                status="blocked",
                errors=result.errors,
            )
            append_log(
                config.vault_root,
                "process-vault",
                [f"stopped at {relative}", f"errors {len(result.errors)}"],
            )
            return (
                1,
                "vault-agent process-vault failed\n"
                f"Stopped at: {relative}\n"
                + "\n".join(f"Error: {error}" for error in result.errors),
            )
        processed.append(f"{relative} ({selected_stage})")

    if config.dry_run:
        return (
            0,
            "vault-agent process-vault dry run\n"
            + (f"Would process: {processed[0]}\n" if processed else "No vault notes need processing.\n")
            + "No files were changed.",
        )
    append_log(config.vault_root, "process-vault", [f"processed {len(processed)} note stage(s)"])
    if not processed:
        return 0, "vault-agent process-vault complete\nNo vault notes need processing."
    return 0, f"vault-agent process-vault complete\nProcessed: {len(processed)}"


class ProcessResult:
    def __init__(self, *, changed: bool, mode: str, errors: list[str] | None = None) -> None:
        self.changed = changed
        self.mode = mode
        self.errors = errors or []


def process_note(
    vault_root: Path,
    note_path: Path,
    *,
    proposal_provider: ProposalProvider | None = None,
    confidence_threshold: float | None = None,
    preserve_unknown_properties: bool = True,
    review_on_warnings: bool = True,
    warning_confidence_margin: float = 0.05,
    stage: str | None = None,
    norms_lock_hash: str | None = None,
) -> ProcessResult:
    stage = stage or "frontmatter-shape"
    text = note_path.read_text(encoding="utf-8")
    parsed = parse_note(text)
    if parsed.error:
        return ProcessResult(changed=False, mode="blocked", errors=[parsed.error])
    frontmatter = dict(parsed.frontmatter)
    body = parsed.body
    confidence: float | None = None
    warnings: list[str] = []

    if stage == "frontmatter-shape":
        _apply_shape_defaults(frontmatter)
        mode = "frontmatter-shaped"
    elif stage == "template-body":
        if frontmatter.get("type") not in NOTE_TYPES:
            return ProcessResult(
                changed=False,
                mode="blocked",
                errors=["template-body requires a schema-approved type"],
            )
        body = _apply_template_body_for_type(body, frontmatter.get("type"))
        mode = "template-ready"
    elif stage == "assign-hub":
        from .topic_hubs import folder_hub_match

        domain = frontmatter.get("domain")
        if not isinstance(domain, str) or not domain:
            return ProcessResult(
                changed=False, mode="blocked", errors=["assign-hub requires a schema-approved domain"]
            )
        approved = approved_hubs_for(domain, _load_vault_schema(vault_root))
        if not approved:
            return ProcessResult(
                changed=False, mode="blocked", errors=[f"no approved hubs for domain `{domain}`"]
            )
        try:
            relative = note_path.resolve().relative_to(vault_root.resolve()).as_posix()
        except ValueError:
            relative = note_path.name
        chosen = ""
        if proposal_provider is not None:
            try:
                proposal = _stage_proposal(
                    proposal_provider, stage, note_path, text, allowed_hubs=approved
                )
            except Exception as exc:
                return ProcessResult(changed=False, mode="blocked", errors=[str(exc)])
            validation = validate_stage_proposal(stage, proposal, allowed_hubs=approved)
            if not validation.valid:
                return ProcessResult(changed=False, mode="blocked", errors=validation.errors)
            confidence = validation.proposal.get("confidence")
            warnings = validation.proposal.get("warnings", [])
            if (
                confidence_threshold is not None
                and confidence is not None
                and confidence < confidence_threshold
            ) or _requires_human_review(
                confidence=confidence,
                confidence_threshold=confidence_threshold,
                warnings=warnings,
                review_on_warnings=review_on_warnings,
                warning_confidence_margin=warning_confidence_margin,
            ):
                reason = "assign-hub proposal requires review (low/near-threshold confidence or warnings)"
                record_model_block(
                    vault_root,
                    note_path,
                    stage=stage,
                    proposal=validation.proposal,
                    reason=reason,
                    suggested_next_action="Run `vault-agent review-model-blocks --dry-run`, then convert safe items through the proposal review path.",
                    proposal_provider=proposal_provider,
                )
                return ProcessResult(changed=False, mode="blocked", errors=[reason])
            chosen = validation.proposal.get("parent", "")
        if not chosen:
            match = folder_hub_match(relative, approved)
            chosen = f"[[{match}]]" if match else ""
        if not chosen:
            return ProcessResult(
                changed=False, mode="skipped", errors=["no approved hub matched this note"]
            )
        frontmatter["parent"] = chosen
        mode = "hub-assigned"
    else:
        if not proposal_provider:
            return ProcessResult(
                changed=False,
                mode="blocked",
                errors=[f"stage `{stage}` requires an LLM proposal provider"],
            )
        try:
            proposal = _stage_proposal(proposal_provider, stage, note_path, text)
        except Exception as exc:
            return ProcessResult(changed=False, mode="blocked", errors=[str(exc)])
        validation = validate_stage_proposal(stage, proposal)
        if not validation.valid:
            return ProcessResult(changed=False, mode="blocked", errors=validation.errors)
        confidence = validation.proposal.get("confidence")
        warnings = validation.proposal.get("warnings", [])
        if (
            confidence_threshold is not None
            and confidence is not None
            and confidence < confidence_threshold
        ):
            reason = f"confidence {confidence} is below threshold {confidence_threshold}"
            record_model_block(
                vault_root,
                note_path,
                stage=stage,
                proposal=validation.proposal,
                reason=reason,
                suggested_next_action="Review the model output and convert it to a normal proposal only if it is correct.",
                proposal_provider=proposal_provider,
            )
            return ProcessResult(
                changed=False,
                mode="blocked",
                errors=[reason],
            )
        if _requires_human_review(
            confidence=confidence,
            confidence_threshold=confidence_threshold,
            warnings=warnings,
            review_on_warnings=review_on_warnings,
            warning_confidence_margin=warning_confidence_margin,
        ):
            reason = "proposal requires review because confidence is near threshold or warnings were returned"
            record_model_block(
                vault_root,
                note_path,
                stage=stage,
                proposal=validation.proposal,
                reason=reason,
                suggested_next_action="Run `vault-agent review-model-blocks --dry-run`, then convert safe items through the proposal review path.",
                proposal_provider=proposal_provider,
            )
            return ProcessResult(
                changed=False,
                mode="blocked",
                errors=[reason],
            )
        if stage == "classify-type":
            frontmatter["type"] = validation.proposal["note_type"]
            mode = "type-classified"
        elif stage == "property-values":
            if frontmatter.get("type") not in NOTE_TYPES:
                return ProcessResult(
                    changed=False,
                    mode="blocked",
                    errors=["property-values requires a schema-approved type"],
                )
            _apply_property_values(frontmatter, validation.proposal)
            mode = "properties-filled"
        elif stage == "summary":
            body = _apply_summary(parsed.body, validation.proposal["summary"])
            mode = "summarized"
        else:
            return ProcessResult(changed=False, mode="blocked", errors=[f"unknown stage `{stage}`"])

    frontmatter = _canonical_frontmatter(
        frontmatter,
        frontmatter.get("type"),
        preserve_unknown_properties=preserve_unknown_properties,
    )
    new_text = render_note(
        frontmatter,
        body,
        property_order=ordered_properties_for(frontmatter.get("type")),
    )
    if new_text == text:
        mark_stage(
            vault_root,
            note_path,
            stage=stage,
            status="complete",
            norms_lock_hash=norms_lock_hash,
            confidence=confidence,
            warnings=warnings,
        )
        return ProcessResult(changed=False, mode=mode)
    backup_root = vault_root / paths_for(vault_root).agent_dir / "backups"
    write_text_safely(note_path, new_text, backup_root=backup_root)
    mark_stage(
        vault_root,
        note_path,
        stage=stage,
        status="complete",
        norms_lock_hash=norms_lock_hash,
        confidence=confidence,
        warnings=warnings,
    )
    return ProcessResult(changed=True, mode=mode)


def _apply_valid_proposal(frontmatter: dict, proposal: dict) -> None:
    frontmatter["type"] = proposal["note_type"]
    frontmatter["status"] = proposal["status"]
    frontmatter["domain"] = proposal["domain"]
    frontmatter["parent"] = proposal["parent"]
    frontmatter["related"] = proposal["related"]
    frontmatter["cover"] = proposal["cover"]
    frontmatter["source_kind"] = proposal["source_kind"]
    frontmatter["capture_type"] = proposal["capture_type"]


def _apply_shape_defaults(frontmatter: dict) -> None:
    frontmatter.setdefault("type", "")
    frontmatter.setdefault("status", "")
    frontmatter.setdefault("domain", "")
    frontmatter.setdefault("parent", "")
    frontmatter.setdefault("related", [])
    frontmatter.setdefault("cover", "")
    frontmatter.setdefault("source_kind", "")
    frontmatter.setdefault("capture_type", "")


def _apply_property_values(frontmatter: dict, proposal: dict) -> None:
    frontmatter["status"] = proposal["status"]
    frontmatter["domain"] = proposal["domain"]
    frontmatter["parent"] = proposal["parent"]
    frontmatter["related"] = proposal["related"]
    frontmatter["cover"] = proposal["cover"]
    frontmatter["source_kind"] = proposal["source_kind"]
    frontmatter["capture_type"] = proposal["capture_type"]


def _has_core_metadata(entry: dict) -> bool:
    frontmatter = entry.get("frontmatter", {})
    return all(key in frontmatter for key in CORE_PROPERTY_ORDER)


def _next_needed_stage(
    vault_root: Path,
    note_path: Path,
    entry: dict,
    *,
    norms_lock_hash: str | None = None,
) -> str | None:
    for stage in PROCESSING_STAGES:
        if _stage_needed(vault_root, note_path, entry, stage, norms_lock_hash=norms_lock_hash):
            return stage
    return None


def _stage_needed(
    vault_root: Path,
    note_path: Path,
    entry: dict,
    stage: str,
    *,
    norms_lock_hash: str | None = None,
) -> bool:
    frontmatter = entry.get("frontmatter", {})
    completed = stage_complete(vault_root, note_path, stage, norms_lock_hash=norms_lock_hash)
    if stage == "frontmatter-shape":
        accepted = accepted_properties_for(frontmatter.get("type"))
        has_unknown = any(key not in accepted for key in frontmatter)
        return (not completed and has_unknown) or not _has_core_metadata(entry)
    if stage == "classify-type":
        if completed:
            return False
        return not frontmatter.get("type") or frontmatter.get("type") not in NOTE_TYPES
    if stage == "property-values":
        if frontmatter.get("type") not in NOTE_TYPES:
            return False
        keys = ("status", "domain", "parent", "related", "cover", "source_kind", "capture_type")
        if completed:
            return any(key not in frontmatter for key in keys)
        return any(key not in frontmatter or frontmatter.get(key) in (None, "") for key in keys)
    if stage == "template-body":
        if completed:
            return False
        note_type = frontmatter.get("type")
        if not note_type or note_type not in NOTE_TYPES:
            return False
        parsed = parse_note(note_path.read_text(encoding="utf-8"))
        _body, headings = append_missing_headings(parsed.body, note_type)
        return bool(headings)
    if stage == "assign-hub":
        if completed:
            return False
        domain = frontmatter.get("domain")
        if not isinstance(domain, str) or not domain:
            return False
        if frontmatter.get("parent") not in (None, ""):
            return False
        return bool(approved_hubs_for(domain, _load_vault_schema(vault_root)))
    if stage == "summary":
        if completed:
            return False
        return bool(frontmatter.get("type")) and _summary_missing(
            note_path.read_text(encoding="utf-8")
        )
    return False


def _canonical_frontmatter(
    frontmatter: dict, note_type: str | None, *, preserve_unknown_properties: bool = True
) -> dict:
    accepted = accepted_properties_for(note_type)
    ordered = ordered_properties_for(note_type)
    canonical = {}
    for key in ordered:
        if key in frontmatter and key in accepted:
            canonical[key] = frontmatter[key]
    if preserve_unknown_properties:
        for key in sorted(frontmatter):
            if key not in canonical:
                canonical[key] = frontmatter[key]
    return canonical


def _stage_proposal(
    proposal_provider: ProposalProvider,
    stage: str,
    note_path: Path,
    text: str,
    *,
    allowed_hubs: list[str] | None = None,
) -> dict:
    propose_stage = getattr(proposal_provider, "propose_stage", None)
    if callable(propose_stage):
        kwargs: dict = {"note_path": note_path, "note_text": text, "stage": stage}
        if allowed_hubs is not None:
            kwargs["allowed_hubs"] = allowed_hubs
        return propose_stage(**kwargs)
    return proposal_provider.propose(note_path=note_path, note_text=text)


def _apply_template_body_for_type(body: str, note_type: str | None) -> str:
    if not note_type or note_type not in NOTE_TYPES:
        return body
    new_body, _headings = append_missing_headings(body, note_type)
    return new_body


def _skip_vault_processing_entry(
    entry: dict, path: Path, *, system_dir: Path, inbox_dir: Path
) -> bool:
    if entry.get("system_template"):
        return True
    return path.is_relative_to(system_dir) or path.is_relative_to(inbox_dir)


def _summary_missing(text: str) -> bool:
    parsed = parse_note(text)
    lines = parsed.body.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "## Summary":
            for cursor in range(index + 1, len(lines)):
                if lines[cursor].startswith("## "):
                    return True
                if lines[cursor].strip():
                    return False
            return True
    return True


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


def _resolve_target_note(vault_root: Path, note: str) -> Path:
    target = Path(note).expanduser()
    if not target.is_absolute():
        target = vault_root / target
    target = target.resolve()
    root = vault_root.resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"target note is outside vault root: {note}")
    if not target.is_file():
        raise ValueError(f"target note does not exist: {note}")
    if target.suffix.lower() != ".md":
        raise ValueError(f"target note is not a Markdown file: {note}")
    return target


def _requires_human_review(
    *,
    confidence: float | None,
    confidence_threshold: float | None,
    warnings: list[str],
    review_on_warnings: bool,
    warning_confidence_margin: float,
) -> bool:
    if review_on_warnings and warnings:
        return True
    if confidence is None or confidence_threshold is None:
        return False
    return confidence <= confidence_threshold + warning_confidence_margin
