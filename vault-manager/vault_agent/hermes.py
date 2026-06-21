"""Hermes directory maintenance orchestration."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .autonomous import run_autonomous
from .config import AgentConfig
from .execution import execute_versioned
from .paths import paths_for


def run_hermes(
    config: AgentConfig,
    *,
    hermes_root: Path,
    max_notes: int | None = None,
    max_proposal_operations: int = 10,
    apply_safe: bool = False,
    mass_edit: bool = False,
) -> tuple[int, str]:
    hermes_root = hermes_root.expanduser().resolve()
    if not hermes_root.exists() or not hermes_root.is_dir():
        return 1, f"vault-agent hermes-run failed\nHermes root is not a directory: {hermes_root}"

    candidates = [path for path in sorted(hermes_root.iterdir()) if path.is_dir()]
    lines = ["vault-agent hermes-run", f"Hermes root: {hermes_root}", ""]
    failures = 0
    for vault_root in candidates:
        vault_config = replace(
            config, vault_root=vault_root, paths=paths_for(vault_root)
        )
        lines.append(f"## {vault_root.name}")
        if _has_path_conflict(vault_root):
            lines.append("- skipped: unsafe path conflict in required system folders")
            failures += 1
            continue
        vault_lines: list[str] = []

        def _run_one_vault() -> int:
            return _run_autonomous_for_vault(
                vault_config,
                lines=vault_lines,
                max_notes=max_notes,
                max_proposal_operations=max_proposal_operations,
                apply_safe=apply_safe,
            )

        if config.dry_run:
            code = _run_one_vault()
        else:
            code = execute_versioned(
                vault_config,
                task_name="hermes-run",
                command_args=["vault-agent", "hermes-run", "--hermes-root", str(hermes_root)],
                mass_edit=mass_edit,
                expected_changed_files=(max_notes or vault_config.max_notes) * 2 + 10,
                operation=_run_one_vault,
            )
        lines.extend(vault_lines)
        if code != 0:
            failures += 1
        lines.append("")
    if not candidates:
        lines.append("No vault directories found.")
    return (1 if failures else 0), "\n".join(lines).rstrip()


def _has_path_conflict(vault_root: Path) -> bool:
    vault_paths = paths_for(vault_root)
    system = vault_root / vault_paths.system_dir
    inbox = vault_root / vault_paths.inbox_dir
    return (system.exists() and not system.is_dir()) or (inbox.exists() and not inbox.is_dir())


def _run_maintenance_for_vault(
    vault_config: AgentConfig, *, lines: list[str], max_notes: int | None
) -> int:
    return _run_autonomous_for_vault(
        vault_config,
        lines=lines,
        max_notes=max_notes,
        max_proposal_operations=10,
        apply_safe=False,
    )


def _run_autonomous_for_vault(
    vault_config: AgentConfig,
    *,
    lines: list[str],
    max_notes: int | None,
    max_proposal_operations: int,
    apply_safe: bool,
) -> int:
    code, output = run_autonomous(
        vault_config,
        max_notes=max_notes or vault_config.max_notes,
        max_proposal_operations=max_proposal_operations,
        stage="frontmatter-shape" if not vault_config.llm_enabled else None,
        create_lock=True,
        apply_safe=apply_safe,
        report_format="both",
    )
    for line in output.splitlines():
        if line.startswith("vault-agent autonomous-run"):
            lines.append(f"- autonomous-run: {'ok' if code == 0 else 'failed'}")
        elif line.startswith("Report "):
            lines.append(f"- {line}")
        elif line.startswith("Undo:"):
            lines.append(f"- {line}")
    return code
