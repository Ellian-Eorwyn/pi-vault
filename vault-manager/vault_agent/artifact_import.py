"""Proposal-first import of external text artifacts into a configured vault inbox."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .paths import BOOTSTRAP_FILE, load_bootstrap
from .review import load_proposals, run_review_proposals
from .safety import atomic_write_text


SUPPORTED_SUFFIXES = {".md", ".txt"}


class ArtifactImportError(ValueError):
    """Structured artifact-import failure safe to return through MCP."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def submit_artifact(
    config: AgentConfig,
    *,
    source_path: str,
    read_roots: list[str],
    suggested_name: str | None = None,
    title: str | None = None,
    source_task_id: str | None = None,
    source_operation: str | None = None,
) -> dict[str, Any]:
    if load_bootstrap(config.vault_root) is None:
        raise ArtifactImportError(
            "vault_not_initialized",
            f"vault root is missing {BOOTSTRAP_FILE.as_posix()}: {config.vault_root}",
        )
    source = _resolve_source(source_path, read_roots)
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ArtifactImportError(
            "unsupported_artifact_format",
            f"artifact format is not supported for proposal import: {source.suffix or '(none)'}",
        )

    content = source.read_text(encoding="utf-8")
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    destination_name = _destination_name(source, suggested_name)
    destination = config.paths.inbox_dir / destination_name
    proposal_id = _proposal_id(destination.stem, source_sha256)
    proposal = {
        "id": proposal_id,
        "title": title.strip() if title and title.strip() else f"Import {destination.stem}",
        "kind": "artifact-import",
        "status": "pending",
        "summary": f"Import external text artifact into `{destination.as_posix()}` for explicit review.",
        "provenance": {
            "source_path": str(source),
            "source_sha256": source_sha256,
            "source_task_id": source_task_id,
            "source_operation": source_operation,
        },
        "operations": [
            {
                "op": "write_file",
                "path": destination.as_posix(),
                "content": content,
                "if_exists": "fail",
            }
        ],
    }

    temporary_root = config.vault_root / config.paths.agent_dir / "tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix="pi-vault-import-review-", dir=temporary_root
        ) as directory:
            candidate_path = Path(directory) / f"{proposal_id}.json"
            candidate_path.write_text(
                json.dumps(proposal, indent=2) + "\n", encoding="utf-8"
            )
            candidates = load_proposals(Path(directory))
            if len(candidates) != 1 or candidates[0].errors:
                errors = (
                    candidates[0].errors
                    if candidates
                    else ["proposal could not be loaded"]
                )
                raise ArtifactImportError(
                    "proposal_validation_failed", "; ".join(errors)
                )
            review_code, review_output = run_review_proposals(
                replace(config, dry_run=True),
                proposal_dir=directory,
            )
            if review_code != 0:
                raise ArtifactImportError("proposal_review_failed", review_output)
    finally:
        try:
            temporary_root.rmdir()
        except OSError:
            pass

    proposal_path = config.vault_root / config.paths.review_dir / "proposals" / f"{proposal_id}.json"
    if proposal_path.exists():
        raise ArtifactImportError(
            "proposal_already_exists",
            f"pending proposal already exists: {proposal_path}",
        )
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(proposal_path, json.dumps(proposal, indent=2) + "\n")

    warnings: list[str] = []
    if (config.vault_root / destination).exists():
        warnings.append(f"destination already exists and proposal application will fail: {destination.as_posix()}")
    return {
        "schemaVersion": 1,
        "status": "pending_review",
        "sourcePath": str(source),
        "sourceSha256": source_sha256,
        "destinationPath": destination.as_posix(),
        "proposalPath": proposal_path.relative_to(config.vault_root).as_posix(),
        "reviewValid": True,
        "warnings": warnings,
    }


def _resolve_source(source_path: str, read_roots: list[str]) -> Path:
    path = Path(source_path).expanduser()
    if not path.is_absolute():
        raise ArtifactImportError("invalid_source_path", "sourcePath must be absolute")
    try:
        source = path.resolve(strict=True)
    except OSError as exc:
        raise ArtifactImportError("source_not_found", f"cannot resolve sourcePath: {exc}") from exc
    if not source.is_file():
        raise ArtifactImportError("invalid_source_path", f"sourcePath is not a file: {source}")
    if not read_roots:
        raise ArtifactImportError("missing_read_root", "at least one read root is required")
    roots: list[Path] = []
    for value in read_roots:
        root = Path(value).expanduser()
        if not root.is_absolute():
            raise ArtifactImportError("invalid_read_root", f"read root must be absolute: {value}")
        try:
            resolved = root.resolve(strict=True)
        except OSError as exc:
            raise ArtifactImportError("invalid_read_root", f"cannot resolve read root {value}: {exc}") from exc
        if not resolved.is_dir():
            raise ArtifactImportError("invalid_read_root", f"read root is not a directory: {resolved}")
        roots.append(resolved)
    if not any(source.is_relative_to(root) for root in roots):
        raise ArtifactImportError("source_outside_read_roots", f"sourcePath is outside allowed read roots: {source}")
    return source


def _destination_name(source: Path, suggested_name: str | None) -> str:
    raw_name = suggested_name.strip() if suggested_name and suggested_name.strip() else source.name
    if Path(raw_name).name != raw_name or raw_name in {".", ".."}:
        raise ArtifactImportError("invalid_suggested_name", "suggestedName must contain only a filename")
    suffix = Path(raw_name).suffix.lower()
    if source.suffix.lower() == ".txt" and suffix in {"", ".txt"}:
        raw_name = f"{Path(raw_name).stem}.md"
    elif suffix != ".md":
        raise ArtifactImportError("invalid_suggested_name", "suggestedName must end in .md")
    safe = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "-", raw_name).strip(" .")
    if not safe or safe == ".md":
        raise ArtifactImportError("invalid_suggested_name", "suggestedName does not contain a usable filename")
    return safe


def _proposal_id(stem: str, source_sha256: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "artifact"
    return f"import-{slug[:48]}-{source_sha256[:12]}"
