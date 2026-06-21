"""Generated-state and readiness helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .frontmatter import parse_note
from .norms import build_norms_lock, load_norms_lock, norms_lock_path
from .paths import paths_for
from .schema import CORE_PROPERTY_ORDER, NOTE_TYPES, index_base_templates


@dataclass(frozen=True)
class GeneratedStateIssue:
    severity: str
    path: str
    message: str


def generated_state_report(config: AgentConfig) -> dict[str, Any]:
    """Return a compact generated-state staleness report."""
    vault_root = config.vault_root
    lock = load_norms_lock(vault_root)
    expected_lock = build_norms_lock(config)
    lock_hash = lock.get("lock_hash") if lock else None
    expected_hash = expected_lock["lock_hash"]
    lock_status = "missing"
    if lock_hash:
        lock_status = "current" if lock_hash == expected_hash else "stale"

    retrieval = _retrieval_state(vault_root)
    proposal_review = _proposal_review_state(vault_root)
    reports = sorted((vault_root / config.paths.agent_dir / "reports").glob("organization-run-*.md"))
    return {
        "norms_lock": {
            "status": lock_status,
            "path": norms_lock_path(vault_root).relative_to(vault_root).as_posix(),
            "lock_hash": lock_hash or "",
            "expected_hash": expected_hash,
        },
        "retrieval": retrieval,
        "proposal_review": proposal_review,
        "organization_reports": {
            "count": len(reports),
            "latest": reports[-1].relative_to(vault_root).as_posix() if reports else "",
        },
    }


def generated_state_issues(config: AgentConfig) -> list[GeneratedStateIssue]:
    report = generated_state_report(config)
    issues: list[GeneratedStateIssue] = []
    lock = report["norms_lock"]
    if lock["status"] != "current":
        issues.append(
            GeneratedStateIssue(
                "warning",
                lock["path"],
                f"norms lock is {lock['status']}",
            )
        )
    for path, state in report["retrieval"]["files"].items():
        if state != "current":
            issues.append(GeneratedStateIssue("warning", path, f"retrieval file is {state}"))
    if report["proposal_review"]["status"] == "stale":
        issues.append(
            GeneratedStateIssue(
                "warning",
                (config.paths.review_dir / "proposed-changes.md").as_posix(),
                "proposal review output is stale",
            )
        )
    return issues


def template_schema_issues(config: AgentConfig) -> list[GeneratedStateIssue]:
    vault_root = config.vault_root
    issues: list[GeneratedStateIssue] = []
    for note_type in sorted(NOTE_TYPES):
        relative = config.paths.template_dir / "note-types" / f"{note_type}.md"
        path = vault_root / relative
        if not path.exists():
            issues.append(
                GeneratedStateIssue("warning", relative.as_posix(), "missing note-type template")
            )
            continue
        parsed = parse_note(path.read_text(encoding="utf-8"))
        if parsed.error:
            issues.append(GeneratedStateIssue("error", relative.as_posix(), parsed.error))
            continue
        for key in parsed.frontmatter:
            if key not in CORE_PROPERTY_ORDER:
                issues.append(
                    GeneratedStateIssue(
                        "warning",
                        relative.as_posix(),
                        f"template frontmatter has unknown property `{key}`",
                    )
                )
        if parsed.frontmatter.get("type") != note_type:
            issues.append(
                GeneratedStateIssue(
                    "warning",
                    relative.as_posix(),
                    f"template type `{parsed.frontmatter.get('type')}` does not match `{note_type}`",
                )
            )
    for relative_text in sorted(index_base_templates()):
        relative = config.paths.template_dir / Path(relative_text).relative_to(
            Path("00 System/0.02 templates")
        )
        if not (vault_root / relative).exists():
            issues.append(
                GeneratedStateIssue("warning", relative.as_posix(), "missing index template")
            )
    return issues


def _retrieval_state(vault_root: Path) -> dict[str, Any]:
    vault_paths = paths_for(vault_root)
    manifest = vault_root / vault_paths.agent_dir / "manifest.json"
    expected = [
        vault_paths.retrieval_dir / "01 vault-map.md",
        vault_paths.retrieval_dir / "02 note-catalog.md",
        vault_paths.retrieval_dir / "03 property-index.md",
        vault_paths.retrieval_dir / "04 summary-brief.md",
    ]
    files: dict[str, str] = {}
    manifest_mtime = manifest.stat().st_mtime if manifest.exists() else 0
    for relative in expected:
        path = vault_root / relative
        if not path.exists():
            files[relative.as_posix()] = "missing"
        elif manifest_mtime and path.stat().st_mtime < manifest_mtime:
            files[relative.as_posix()] = "stale"
        else:
            files[relative.as_posix()] = "current"
    status = "current" if all(value == "current" for value in files.values()) else "stale"
    return {"status": status, "files": files}


def _proposal_review_state(vault_root: Path) -> dict[str, Any]:
    review_dir = paths_for(vault_root).review_dir
    proposals = vault_root / review_dir / "proposals"
    review = vault_root / review_dir / "proposed-changes.md"
    proposal_files = sorted(proposals.glob("*.json")) if proposals.exists() else []
    if not proposal_files:
        return {"status": "current", "proposal_count": 0}
    if not review.exists():
        return {"status": "missing", "proposal_count": len(proposal_files)}
    newest = max(path.stat().st_mtime for path in proposal_files)
    return {
        "status": "stale" if review.stat().st_mtime < newest else "current",
        "proposal_count": len(proposal_files),
    }


def json_dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"
