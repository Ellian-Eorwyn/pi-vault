"""Deterministic Markdown scanning and manifest rendering."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .frontmatter import parse_note
from .logging_utils import append_log
from .paths import paths_for
from .safety import write_text_safely


EXCLUDED_PARTS = {".git", ".obsidian"}


@dataclass(frozen=True)
class ScanResult:
    entries: list[dict[str, Any]]
    folders: list[str]


def discover_markdown(vault_root: Path) -> list[Path]:
    vault_paths = paths_for(vault_root)
    paths: list[Path] = []
    for path in vault_root.rglob("*.md"):
        relative = path.relative_to(vault_root)
        parts = relative.parts
        if any(part in EXCLUDED_PARTS for part in parts):
            continue
        if _is_under(relative, vault_paths.agent_dir):
            continue
        if _is_under(relative, vault_paths.trash_dir):
            continue
        paths.append(path)
    return sorted(paths, key=lambda p: p.relative_to(vault_root).as_posix().lower())


def scan_vault(vault_root: Path) -> ScanResult:
    vault_paths = paths_for(vault_root)
    entries: list[dict[str, Any]] = []
    folders: set[str] = set()
    for path in discover_markdown(vault_root):
        relative = path.relative_to(vault_root)
        if relative.parent != Path("."):
            folders.add(relative.parent.as_posix())
        text = path.read_text(encoding="utf-8")
        parsed = parse_note(text)
        frontmatter = _json_safe(parsed.frontmatter)
        stat = path.stat()
        entries.append(
            {
                "path": relative.as_posix(),
                "title": _title_for(path, parsed.body),
                "type": frontmatter.get("type"),
                "status": frontmatter.get("status"),
                "domain": frontmatter.get("domain"),
                "parent": frontmatter.get("parent"),
                "related": frontmatter.get("related"),
                "cover": frontmatter.get("cover"),
                "source_kind": frontmatter.get("source_kind"),
                "capture_type": frontmatter.get("capture_type"),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "frontmatter_error": parsed.error,
                "frontmatter": frontmatter,
                "system_template": _is_under(relative, vault_paths.template_dir),
            }
        )
    return ScanResult(entries, sorted(folders))


def render_manifest(result: ScanResult) -> str:
    return json.dumps(
        {"generated_by": "vault-agent", "notes": result.entries},
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_state(result: ScanResult) -> str:
    return json.dumps(
        {
            "generated_by": "vault-agent",
            "last_scan": datetime.now(timezone.utc).isoformat(),
            "note_count": len(result.entries),
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_vault_map(result: ScanResult) -> str:
    lines = ["# Vault Map", "", f"Notes discovered: {len(result.entries)}", "", "## Folders", ""]
    lines.extend(f"- `{folder}`" for folder in result.folders)
    if not result.folders:
        lines.append("- No folders discovered.")
    return "\n".join(lines) + "\n"


def render_note_catalog(result: ScanResult) -> str:
    lines = [
        "# Note Catalog",
        "",
        "| Path | Type | Status | Domain | Parent |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in result.entries:
        lines.append(
            "| {path} | {type} | {status} | {domain} | {parent} |".format(
                path=entry["path"],
                type=entry.get("type") or "",
                status=entry.get("status") or "",
                domain=entry.get("domain") or "",
                parent=entry.get("parent") or "",
            )
        )
    return "\n".join(lines) + "\n"


def run_scan(config: AgentConfig) -> tuple[int, str]:
    result = scan_vault(config.vault_root)
    if config.dry_run:
        return 0, f"vault-agent scan dry run\nDiscovered notes: {len(result.entries)}\nNo files were changed."

    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    writes = {
        config.paths.agent_dir / "manifest.json": render_manifest(result),
        config.paths.agent_dir / "state.json": render_state(result),
        config.paths.retrieval_dir / "01 vault-map.md": render_vault_map(result),
        config.paths.retrieval_dir / "02 note-catalog.md": render_note_catalog(result),
    }
    for relative, content in writes.items():
        write_text_safely(config.vault_root / relative, content, backup_root=backup_root)
    append_log(config.vault_root, "scan", [f"discovered {len(result.entries)} note(s)"])
    return 0, f"vault-agent scan complete\nDiscovered notes: {len(result.entries)}\nUpdated generated state and catalog files."


def _title_for(path: Path, body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _is_under(path: Path, parent: Path) -> bool:
    return path == parent or path.is_relative_to(parent)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
