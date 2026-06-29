"""Static and optional live Obsidian compatibility checks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import AgentConfig
from .frontmatter import parse_note
from .schema import load_schema, property_order_from_schema
from .scanner import scan_vault


BASE_VIEW_TYPES = {"table", "cards", "list", "map"}


@dataclass(frozen=True)
class ObsidianIssue:
    path: str
    severity: str
    message: str


def run_obsidian_check(
    config: AgentConfig,
    *,
    live_obsidian: bool = False,
    require_live: bool = False,
    json_output: bool = False,
) -> tuple[int, str]:
    issues = check_vault(config)
    live = _run_live_check(require_live=require_live) if live_obsidian or require_live else {
        "status": "skipped",
        "message": "live Obsidian checks not requested",
    }
    error_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    if live.get("status") == "failed":
        error_count += 1
    result = {
        "vault_root": config.vault_root.as_posix(),
        "issues": [issue.__dict__ for issue in issues],
        "errors": error_count,
        "warnings": warning_count,
        "live_obsidian": live,
    }
    if json_output:
        return (1 if error_count else 0), json.dumps(result, indent=2, sort_keys=True)
    lines = [
        "vault-agent obsidian-check",
        f"Vault root: {config.vault_root}",
        f"Errors: {error_count}",
        f"Warnings: {warning_count}",
        f"Live Obsidian: {live['status']} - {live['message']}",
    ]
    for issue in issues[:50]:
        lines.append(f"- {issue.severity}: `{issue.path}` {issue.message}")
    if len(issues) > 50:
        lines.append(f"- ...and {len(issues) - 50} more issue(s)")
    return (1 if error_count else 0), "\n".join(lines)


def check_vault(config: AgentConfig) -> list[ObsidianIssue]:
    scan = scan_vault(config.vault_root)
    property_order = property_order_from_schema(load_schema(config.vault_root))
    issues: list[ObsidianIssue] = []
    for entry in scan.entries:
        path = config.vault_root / entry["path"]
        if not path.exists() or path.suffix != ".md":
            continue
        issues.extend(check_markdown_file(config.vault_root, path, property_order=property_order))
    return issues


def check_markdown_file(
    vault_root: Path,
    path: Path,
    *,
    property_order: tuple[str, ...] | None = None,
) -> list[ObsidianIssue]:
    if property_order is None:
        property_order = property_order_from_schema(load_schema(vault_root))
    relative = path.relative_to(vault_root).as_posix()
    text = path.read_text(encoding="utf-8")
    issues: list[ObsidianIssue] = []
    parsed = parse_note(text)
    if parsed.error:
        issues.append(ObsidianIssue(relative, "error", f"frontmatter YAML error: {parsed.error}"))
    elif parsed.has_frontmatter:
        issues.extend(_frontmatter_order_issues(relative, text, parsed.frontmatter, property_order))
    for index, block in enumerate(_base_blocks(text), start=1):
        issues.extend(_base_block_issues(relative, index, block))
    issues.extend(_wikilink_issues(vault_root, relative, text))
    return issues


def _frontmatter_order_issues(
    relative: str, text: str, frontmatter: dict[str, Any], property_order: tuple[str, ...]
) -> list[ObsidianIssue]:
    del frontmatter
    raw = text[4 : text.find("\n---\n", 4)]
    keys: list[str] = []
    for line in raw.splitlines():
        if not line.strip() or line.startswith((" ", "\t", "-")):
            continue
        if ":" not in line:
            continue
        keys.append(line.split(":", 1)[0].strip())
    core_positions = [property_order.index(key) for key in keys if key in property_order]
    if core_positions != sorted(core_positions):
        return [
            ObsidianIssue(
                relative,
                "warning",
                "core frontmatter properties are not in canonical Obsidian/vault-agent order",
            )
        ]
    return []


def _base_blocks(text: str) -> list[str]:
    return [match.group(1) for match in re.finditer(r"```base\s*\n(.*?)```", text, flags=re.DOTALL)]


def _base_block_issues(relative: str, index: int, block: str) -> list[ObsidianIssue]:
    prefix = f"base block {index}"
    try:
        data = yaml.safe_load(block) if block.strip() else None
    except yaml.YAMLError as exc:
        return [ObsidianIssue(relative, "error", f"{prefix} YAML error: {exc}")]
    if not isinstance(data, dict):
        return [ObsidianIssue(relative, "error", f"{prefix} must be a YAML mapping")]
    issues: list[ObsidianIssue] = []
    views = data.get("views")
    if not isinstance(views, list) or not views:
        issues.append(ObsidianIssue(relative, "error", f"{prefix} must define non-empty views"))
    else:
        for view_index, view in enumerate(views, start=1):
            if not isinstance(view, dict):
                issues.append(ObsidianIssue(relative, "error", f"{prefix} view {view_index} must be a mapping"))
                continue
            view_prefix = f"{prefix} view {view_index}"
            view_type = view.get("type")
            if view_type not in BASE_VIEW_TYPES:
                issues.append(ObsidianIssue(relative, "error", f"{view_prefix} has unsupported type `{view_type}`"))
            order = view.get("order", [])
            if order is not None and not isinstance(order, list):
                issues.append(ObsidianIssue(relative, "error", f"{view_prefix} order must be a list"))
            issues.extend(_sort_issues(relative, view_prefix, view.get("sort")))
            issues.extend(_group_by_issues(relative, view_prefix, view.get("groupBy")))
            view_filters = view.get("filters", {})
            if view_filters not in ({}, None) and not isinstance(view_filters, (str, dict)):
                issues.append(ObsidianIssue(relative, "error", f"{view_prefix} filters must be a string or mapping"))
            if isinstance(view_filters, dict):
                issues.extend(_filter_tree_issues(relative, view_prefix, view_filters))
    issues.extend(_properties_issues(relative, prefix, data.get("properties")))
    filters = data.get("filters", {})
    if filters not in ({}, None) and not isinstance(filters, (str, dict)):
        issues.append(ObsidianIssue(relative, "error", f"{prefix} filters must be a string or mapping"))
    if isinstance(filters, dict):
        issues.extend(_filter_tree_issues(relative, prefix, filters))
    return issues


def _sort_issues(relative: str, prefix: str, sort: Any) -> list[ObsidianIssue]:
    if sort in (None, []):
        return []
    if not isinstance(sort, list):
        return [ObsidianIssue(relative, "error", f"{prefix} sort must be a list")]
    issues: list[ObsidianIssue] = []
    for entry in sort:
        if not isinstance(entry, dict) or "property" not in entry:
            issues.append(ObsidianIssue(relative, "error", f"{prefix} sort entries must map `property` (and optional `direction`)"))
            continue
        direction = entry.get("direction", "ASC")
        if direction not in {"ASC", "DESC"}:
            issues.append(ObsidianIssue(relative, "warning", f"{prefix} sort direction `{direction}` should be ASC or DESC"))
    return issues


def _group_by_issues(relative: str, prefix: str, group_by: Any) -> list[ObsidianIssue]:
    if group_by in (None, {}):
        return []
    if not isinstance(group_by, dict) or "property" not in group_by:
        return [ObsidianIssue(relative, "error", f"{prefix} groupBy must map a `property`")]
    direction = group_by.get("direction", "ASC")
    if direction not in {"ASC", "DESC"}:
        return [ObsidianIssue(relative, "warning", f"{prefix} groupBy direction `{direction}` should be ASC or DESC")]
    return []


def _properties_issues(relative: str, prefix: str, properties: Any) -> list[ObsidianIssue]:
    if properties in (None, {}):
        return []
    if not isinstance(properties, dict):
        return [ObsidianIssue(relative, "error", f"{prefix} properties must be a mapping")]
    issues: list[ObsidianIssue] = []
    for key, value in properties.items():
        if not isinstance(value, dict):
            issues.append(ObsidianIssue(relative, "error", f"{prefix} property `{key}` must be a mapping"))
    return issues


def _filter_tree_issues(relative: str, prefix: str, value: Any) -> list[ObsidianIssue]:
    issues: list[ObsidianIssue] = []
    if not isinstance(value, dict):
        return issues
    for key, child in value.items():
        if key not in {"and", "or", "not"}:
            issues.append(ObsidianIssue(relative, "warning", f"{prefix} uses unusual filter key `{key}`"))
            continue
        if not isinstance(child, list):
            issues.append(ObsidianIssue(relative, "error", f"{prefix} filter `{key}` must be a list"))
            continue
        for item in child:
            if not isinstance(item, (str, dict)):
                issues.append(ObsidianIssue(relative, "error", f"{prefix} filter entries must be strings or mappings"))
            elif isinstance(item, dict):
                issues.extend(_filter_tree_issues(relative, prefix, item))
    return issues


def _wikilink_issues(vault_root: Path, relative: str, text: str) -> list[ObsidianIssue]:
    issues: list[ObsidianIssue] = []
    for target in re.findall(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", text):
        if target.startswith(("http://", "https://")):
            continue
        if "/" not in target:
            continue
        candidate = vault_root / (target if target.endswith(".md") else f"{target}.md")
        if not candidate.exists():
            issues.append(ObsidianIssue(relative, "warning", f"wikilink target may not exist: [[{target}]]"))
    return issues


def _run_live_check(*, require_live: bool) -> dict[str, str]:
    if shutil.which("obsidian") is None:
        status = "failed" if require_live else "skipped"
        return {"status": status, "message": "obsidian CLI not found"}
    try:
        result = subprocess.run(
            ["obsidian", "dev:errors"],
            text=True,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        status = "failed" if require_live else "skipped"
        return {"status": status, "message": str(exc)}
    if result.returncode != 0:
        status = "failed" if require_live else "skipped"
        return {"status": status, "message": (result.stderr or result.stdout).strip() or "Obsidian is not available"}
    output = result.stdout.strip()
    return {"status": "ok", "message": output or "no live Obsidian errors reported"}
