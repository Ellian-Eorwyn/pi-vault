"""Preview and apply vault-agent initialization plans."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AgentConfig
from .dashboard_layout import dashboard_directories
from .logging_utils import append_log
from .safety import CreationItem, apply_creation_plan, plan_creation
from .starter_files import starter_file_contents
from .paths import BOOTSTRAP_DIR, BOOTSTRAP_FILE, render_bootstrap


@dataclass(frozen=True)
class InitItem:
    kind: str
    path: Path
    description: str


SYSTEM_DIRECTORY_SPECS = (
    (".", "system area for agent files, templates, and trash"),
    ("0.01 agent", "agent runtime state"),
    ("0.01 agent/logs", "daily command logs"),
    ("0.01 agent/backups", "future backups before writes"),
    ("0.01 agent/scripts", "vault-local helper scripts"),
    ("0.01 agent/reports", "generated organization pass reports"),
    ("0.01 agent/review", "review queues and processing errors"),
    ("0.01 agent/review/proposals", "deterministic proposal JSON files"),
    ("0.01 agent/retrieval", "generated retrieval guides and indexes"),
    (
        "0.01 agent/retrieval/summaries-standard",
        "standard generated summaries",
    ),
    (
        "0.01 agent/retrieval/summaries-standard/by-type",
        "summaries grouped by note type",
    ),
    (
        "0.01 agent/retrieval/summaries-standard/by-domain",
        "summaries grouped by domain",
    ),
    (
        "0.01 agent/retrieval/summaries-standard/by-project",
        "summaries grouped by project",
    ),
    (
        "0.01 agent/retrieval/summaries-standard/by-status",
        "summaries grouped by status",
    ),
    ("0.01 agent/retrieval/deep-summaries", "deep note summaries"),
    ("0.01 agent/retrieval/indexes", "generated retrieval indexes"),
    (
        "0.01 agent/retrieval/indexes/by-type",
        "indexes grouped by note type",
    ),
    (
        "0.01 agent/retrieval/indexes/by-domain",
        "indexes grouped by domain",
    ),
    (
        "0.01 agent/retrieval/indexes/by-project",
        "indexes grouped by project",
    ),
    (
        "0.01 agent/retrieval/indexes/by-status",
        "indexes grouped by status",
    ),
    ("0.02 templates", "human-editable schema and templates"),
    ("0.02 templates/note-types", "note type templates"),
    ("0.02 templates/indexes", "index and dashboard templates"),
    ("0.99 trash", "vault trash area excluded from processing"),
)

FILE_SPECS = (
    ("99 System/0.01 agent/config.yaml", "human-editable agent config"),
    ("99 System/0.01 agent/AGENT_HANDOFF.md", "agent handoff instructions"),
    ("99 System/0.01 agent/AGENT_CONTRACT.md", "framework-agnostic agent contract"),
    ("99 System/0.01 agent/schema.json", "machine-readable vault schema"),
    ("99 System/0.01 agent/manifest.json", "generated note manifest"),
    ("99 System/0.01 agent/state.json", "agent processing state"),
    ("99 System/0.01 agent/review/needs-review.md", "notes needing user review"),
    (
        "99 System/0.01 agent/review/proposed-values.md",
        "schema values proposed for review",
    ),
    (
        "99 System/0.01 agent/review/proposed-changes.md",
        "deterministic proposals pending review",
    ),
    (
        "99 System/0.01 agent/review/processing-errors.md",
        "validation and processing errors",
    ),
    (
        "99 System/0.01 agent/retrieval/00 retrieval-readme.md",
        "instructions for retrieval-first vault use",
    ),
    ("99 System/0.01 agent/retrieval/01 vault-map.md", "generated vault map"),
    ("99 System/0.01 agent/retrieval/02 note-catalog.md", "generated note catalog"),
    (
        "99 System/0.01 agent/retrieval/03 property-index.md",
        "generated property index",
    ),
    (
        "99 System/0.01 agent/retrieval/04 summary-brief.md",
        "generated summary brief",
    ),
    (
        "99 System/0.01 agent/retrieval/stale-summaries.md",
        "summary refresh queue",
    ),
    (
        "99 System/0.01 agent/retrieval/retrieval-log.md",
        "retrieval rebuild log",
    ),
    (
        "99 System/0.02 templates/0.020 vault schema.md",
        "human-readable vault schema",
    ),
    (
        "99 System/0.02 templates/0.021 property values.md",
        "human-readable property values",
    ),
    (
        "99 System/0.02 templates/0.022 folder norms.md",
        "human-readable folder norms",
    ),
)

def build_init_plan(config: AgentConfig) -> list[InitItem]:
    items: list[InitItem] = []
    for path, description in _directory_specs(config):
        items.append(InitItem("directory", config.vault_root / path, description))
    for path, description in _file_specs(config):
        items.append(InitItem("file", config.vault_root / path, description))
    return items


def build_init_creation_items(config: AgentConfig) -> list[CreationItem]:
    items: list[CreationItem] = []
    contents = starter_file_contents(
        system_dir=config.paths.system_dir,
        inbox_dir=config.paths.inbox_dir,
        dashboards_dir=config.paths.dashboards_dir,
        content_dirs=config.paths.content_dirs,
        domain_folders=config.paths.domain_folders,
        custom_folders=config.paths.custom_folders,
    )
    for path, description in _directory_specs(config):
        items.append(CreationItem("directory", config.vault_root / path, description))
    for path, description in _file_specs(config):
        content = (
            render_bootstrap(config.paths)
            if path == BOOTSTRAP_FILE.as_posix()
            else contents.get(path, "")
        )
        items.append(
            CreationItem(
                "file",
                config.vault_root / path,
                description,
                content=content,
            )
        )
    return items


def render_init_dry_run(config: AgentConfig) -> str:
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    plan = plan_creation(build_init_creation_items(config), backup_root)
    directories = [item for item in plan if item.item.kind == "directory"]
    files = [item for item in plan if item.item.kind == "file"]

    lines = [
        "vault-agent init dry run",
        f"Vault root: {config.vault_root}",
        "No files were changed.",
        "",
        "Directories:",
    ]
    lines.extend(_render_items(config.vault_root, directories))
    lines.extend(["", "Starter files:"])
    lines.extend(_render_items(config.vault_root, files))
    return "\n".join(lines)


def apply_init(config: AgentConfig) -> tuple[int, str]:
    backup_root = config.vault_root / config.paths.agent_dir / "backups"
    plan = plan_creation(build_init_creation_items(config), backup_root)
    conflicts = [item for item in plan if item.action == "conflict"]
    if conflicts:
        lines = ["vault-agent init blocked by path conflicts", ""]
        lines.extend(_render_items(config.vault_root, conflicts))
        return 1, "\n".join(lines)

    apply_creation_plan(plan)
    created = [item for item in plan if item.action in {"create_directory", "create_file"}]
    preserved = [item for item in plan if item.action in {"exists", "preserve_file"}]
    append_log(
        config.vault_root,
        "init",
        [
            f"created {len(created)} item(s)",
            f"preserved {len(preserved)} existing item(s)",
        ],
    )
    lines = [
        "vault-agent init complete",
        f"Vault root: {config.vault_root}",
        f"Created: {len(created)}",
        f"Preserved: {len(preserved)}",
    ]
    return 0, "\n".join(lines)


def _render_items(vault_root: Path, items: list) -> list[str]:
    lines: list[str] = []
    for planned in items:
        item = planned.item
        status = _status_label(planned.action)
        description = item.description
        if planned.backup_path:
            backup_path = planned.backup_path.relative_to(vault_root)
            description = f"{description}; preserve existing, backup would be {backup_path}"
        lines.append(f"- [{status}] {item.path.relative_to(vault_root)} - {description}")
    return lines


def _status_label(action: str) -> str:
    if action in {"create_directory", "create_file"}:
        return "create"
    if action == "preserve_file":
        return "exists"
    return action


def _directory_specs(config: AgentConfig) -> tuple[tuple[str, str], ...]:
    system = config.paths.system_dir
    specs = [(BOOTSTRAP_DIR.as_posix(), "pi-vault bootstrap configuration")]
    specs.extend(
        ((system / path).as_posix(), description)
        for path, description in SYSTEM_DIRECTORY_SPECS
    )
    specs.append((config.paths.inbox_dir.as_posix(), "intake folder for unprocessed notes"))
    specs.extend(
        (path.as_posix(), "dashboard-first user-facing vault structure")
        for path in dashboard_directories(config.paths)
    )
    return tuple(specs)


def _file_specs(config: AgentConfig) -> tuple[tuple[str, str], ...]:
    contents = starter_file_contents(
        system_dir=config.paths.system_dir,
        inbox_dir=config.paths.inbox_dir,
        dashboards_dir=config.paths.dashboards_dir,
        content_dirs=config.paths.content_dirs,
        domain_folders=config.paths.domain_folders,
        custom_folders=config.paths.custom_folders,
    )
    descriptions = dict(FILE_SPECS)
    specs: list[tuple[str, str]] = [
        (BOOTSTRAP_FILE.as_posix(), "vault-local system and inbox folder selection")
    ]
    for path in contents:
        default_path = path.replace(config.paths.system_dir.as_posix(), "99 System", 1)
        description = descriptions.get(default_path)
        if description is None and "/note-types/" in path:
            description = "starter note-type template"
        if description is None and "/indexes/" in path:
            description = "starter index template"
        specs.append((path, description or "starter agent file"))
    return tuple(specs)
