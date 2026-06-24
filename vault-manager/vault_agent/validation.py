"""Vault validation and review queue rendering."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .config import AgentConfig
from .generated_state import generated_state_issues, template_schema_issues
from .legacy import mapped_controlled_value, mapped_property_for
from .logging_utils import append_log
from .paths import review_path
from .scanner import scan_vault
from .schema import COMMON_PROPERTIES, NOTE_TYPES
from .safety import write_text_safely


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    path: str
    message: str


def validate_entries(
    entries: list[dict[str, Any]], config: AgentConfig | None = None
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for entry in entries:
        path = entry["path"]
        if entry.get("frontmatter_error"):
            issues.append(ValidationIssue("error", path, entry["frontmatter_error"]))
        for key in entry.get("frontmatter", {}):
            if key not in COMMON_PROPERTIES:
                if key == "cssclasses" and entry.get("type") == "index":
                    continue
                mapped = mapped_property_for(key, config) if config else None
                if mapped:
                    issues.append(
                        ValidationIssue(
                            "info",
                            path,
                            f"legacy property `{key}` can map to `{mapped}`",
                        )
                    )
                else:
                    issues.append(ValidationIssue("warning", path, f"unknown property `{key}`"))
        _validate_allowed(issues, path, "type", entry.get("type"), config)
        _validate_allowed(issues, path, "status", entry.get("status"), config)
        _validate_allowed(issues, path, "domain", entry.get("domain"), config)
        _validate_allowed(issues, path, "source_kind", entry.get("source_kind"), config)
        _validate_allowed(issues, path, "capture_type", entry.get("capture_type"), config)
        related = entry.get("related")
        if related is not None and not isinstance(related, list):
            issues.append(ValidationIssue("warning", path, "`related` should be a list"))
    return issues


def validate_vault(config: AgentConfig) -> list[ValidationIssue]:
    result = scan_vault(config.vault_root)
    issues = validate_entries(result.entries, config)
    for issue in template_schema_issues(config):
        issues.append(ValidationIssue(issue.severity, issue.path, issue.message))
    for issue in generated_state_issues(config):
        issues.append(ValidationIssue(issue.severity, issue.path, issue.message))
    return issues


def render_needs_review(issues: list[ValidationIssue]) -> str:
    lines = ["# Needs Review", ""]
    if not issues:
        lines.append("No validation issues found.")
    for issue in issues:
        lines.append(f"- **{issue.severity}** `{issue.path}`: {issue.message}")
    return "\n".join(lines) + "\n"


def render_processing_errors(issues: list[ValidationIssue]) -> str:
    errors = [issue for issue in issues if issue.severity == "error"]
    lines = ["# Processing Errors", ""]
    if not errors:
        lines.append("No processing errors found.")
    for issue in errors:
        lines.append(f"- `{issue.path}`: {issue.message}")
    return "\n".join(lines) + "\n"


def run_validate(config: AgentConfig, *, json_output: bool = False) -> tuple[int, str]:
    result = scan_vault(config.vault_root)
    issues = validate_entries(result.entries, config)
    for issue in template_schema_issues(config):
        issues.append(ValidationIssue(issue.severity, issue.path, issue.message))
    for issue in generated_state_issues(config):
        issues.append(ValidationIssue(issue.severity, issue.path, issue.message))
    errors = [issue for issue in issues if issue.severity == "error"]
    if json_output:
        return (
            1 if errors else 0,
            json.dumps(
                {
                    "generated_by": "vault-agent",
                    "notes": len(result.entries),
                    "issues": len(issues),
                    "errors": len(errors),
                    "groups": issue_groups(issues),
                },
                indent=2,
                sort_keys=True,
            ),
        )
    if config.dry_run:
        return (
            1 if errors else 0,
            "vault-agent validate dry run\n"
            f"Issues: {len(issues)}\n"
            f"Errors: {len(errors)}\n"
            + _render_issue_groups(issues)
            + "\nNo files were changed.",
        )

    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    write_text_safely(
        review_path(config.vault_root, "needs-review.md"),
        render_needs_review(issues),
        backup_root=backup_root,
    )
    write_text_safely(
        review_path(config.vault_root, "processing-errors.md"),
        render_processing_errors(issues),
        backup_root=backup_root,
    )
    append_log(config.vault_root, "validate", [f"issues {len(issues)}", f"errors {len(errors)}"])
    return (
        1 if errors else 0,
        f"vault-agent validate complete\nIssues: {len(issues)}\nErrors: {len(errors)}\nReview files updated.",
    )


def _validate_allowed(
    issues: list[ValidationIssue],
    path: str,
    key: str,
    value: Any,
    config: AgentConfig | None = None,
) -> None:
    if value is None:
        return
    allowed = COMMON_PROPERTIES[key].get("allowed")
    if not allowed:
        return
    if value not in allowed:
        mapped = mapped_controlled_value(key, value, config) if config else None
        if mapped and mapped in allowed:
            issues.append(
                ValidationIssue(
                    "info",
                    path,
                    f"legacy {key} `{value}` can map to `{mapped}`",
                )
            )
            return
        message = f"unknown {key} `{value}`" if key == "type" else f"invalid {key} `{value}`"
        issues.append(ValidationIssue("warning", path, message))


def _render_issue_groups(issues: list[ValidationIssue], *, limit: int = 12) -> str:
    if not issues:
        return ""
    grouped: dict[tuple[str, str], int] = {}
    for issue in issues:
        key = (issue.severity, issue.message)
        grouped[key] = grouped.get(key, 0) + 1
    lines = ["", "Top issue groups:"]
    ranked = sorted(grouped.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    for (severity, message), count in ranked[:limit]:
        lines.append(f"- {count}x **{severity}** {message}")
    if len(ranked) > limit:
        lines.append(f"- ... {len(ranked) - limit} more group(s)")
    return "\n".join(lines)


def issue_groups(issues: list[ValidationIssue], *, limit: int = 12) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], int] = {}
    for issue in issues:
        key = (issue.severity, issue.message)
        grouped[key] = grouped.get(key, 0) + 1
    ranked = sorted(grouped.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    return [
        {"severity": severity, "message": message, "count": count}
        for (severity, message), count in ranked[:limit]
    ]
