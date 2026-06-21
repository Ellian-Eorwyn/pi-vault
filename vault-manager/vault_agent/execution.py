"""Versioned command execution wrapper."""

from __future__ import annotations

import contextvars
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .config import AgentConfig
from .safety import atomic_write_text
from . import versioning


_ACTIVE_RUN: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "vault_agent_active_version_run", default=None
)


class MassEditBlocked(RuntimeError):
    pass


def active_run_id() -> str | None:
    """Return the current versioned run id when a command is inside the wrapper."""
    return _ACTIVE_RUN.get()


def execute_versioned(
    config: AgentConfig,
    *,
    task_name: str,
    command_args: list[str],
    mass_edit: bool = False,
    expected_changed_files: int | None = None,
    expected_deletions: int | None = None,
    operation: Callable[[], int],
) -> int:
    if config.dry_run or not config.versioning_enabled:
        return operation()
    if _ACTIVE_RUN.get() is not None:
        return operation()
    _check_expected_mass_edit(
        config,
        mass_edit=mass_edit,
        expected_changed_files=expected_changed_files,
        expected_deletions=expected_deletions,
        command_args=command_args,
    )
    run_id = uuid.uuid4().hex
    token = _ACTIVE_RUN.set(run_id)
    try:
        with _vault_lock(config):
            return _execute_locked(
                config,
                task_name=task_name,
                command_args=command_args,
                mass_edit=mass_edit,
                run_id=run_id,
                operation=operation,
            )
    finally:
        _ACTIVE_RUN.reset(token)


def _execute_locked(
    config: AgentConfig,
    *,
    task_name: str,
    command_args: list[str],
    mass_edit: bool,
    run_id: str,
    operation: Callable[[], int],
) -> int:
    started_at = versioning.now_timestamp()
    pre_commit = None
    post_commit = None
    status = "failed"
    exit_code = 1
    error = ""
    versioning.ensure_initialized(config.vault_root, config)
    pre_status = versioning.status(config.vault_root)
    if pre_status.dirty:
        policy = config.versioning_dirty_before_write_policy
        if policy == "refuse":
            raise versioning.VersioningError(
                "working tree is dirty before write and dirty_before_write_policy is refuse"
            )
        if policy == "snapshot":
            dirty_snapshot = versioning.snapshot(
                config.vault_root,
                config,
                phase="pre",
                task_name="dirty-state",
                run_id=run_id,
                metadata={"reason": "dirty-before-write", "task_name": task_name},
            )
            pre_commit = dirty_snapshot.commit
    if pre_commit is None:
        pre_commit = versioning.current_commit(config.vault_root)
    if config.versioning_auto_snapshot_before_write:
        pre_snapshot = versioning.snapshot(
            config.vault_root,
            config,
            phase="pre",
            task_name=task_name,
            run_id=run_id,
            metadata={"run_id": run_id, "task_name": task_name, "command_args": command_args},
            allow_empty=pre_commit is None,
        )
        pre_commit = pre_snapshot.commit
    try:
        exit_code = operation()
        status = "success" if exit_code == 0 else "failed"
    except Exception as exc:
        error = str(exc)
        status = "failed"
        raise
    finally:
        changed_after = versioning.changed_files(config.vault_root)
        deletion_count = sum(1 for item in changed_after if "D" in item.status)
        blocked = _mass_edit_reason(config, len(changed_after), deletion_count, mass_edit)
        if blocked and status == "success":
            status = "failed"
            error = blocked
            exit_code = 1
        if changed_after and config.versioning_auto_snapshot_after_write and not blocked:
            post_snapshot = versioning.snapshot(
                config.vault_root,
                config,
                phase="post",
                task_name=task_name,
                run_id=run_id,
                metadata={
                    "run_id": run_id,
                    "task_name": task_name,
                    "command_args": command_args,
                    "status": status,
                },
            )
            post_commit = post_snapshot.commit
        else:
            post_commit = versioning.current_commit(config.vault_root)
        changed_between = (
            versioning.changed_files(config.vault_root, pre_commit, post_commit)
            if pre_commit and post_commit
            else []
        )
        diff_text = (
            versioning.diff(config.vault_root, from_ref=pre_commit, to_ref=post_commit)
            if pre_commit and post_commit
            else ""
        )
        change_set = _change_set(
            config,
            run_id=run_id,
            task_name=task_name,
            command_args=command_args,
            started_at=started_at,
            pre_commit=pre_commit,
            post_commit=post_commit,
            changed=changed_between,
            status=status,
            exit_code=exit_code,
            error=error,
            diff_summary=versioning.summarize_diff(config.vault_root, pre_commit, post_commit),
        )
        metadata_path, diff_path = versioning.write_run_artifacts(
            config.vault_root, run_id, metadata=change_set, diff_text=diff_text
        )
        change_set["log_file_path"] = metadata_path.relative_to(config.vault_root).as_posix()
        change_set["diff_path"] = diff_path.relative_to(config.vault_root).as_posix()
        versioning.write_change_set(config.vault_root, change_set)
        if config.versioning_auto_snapshot_after_write and versioning.changed_files(config.vault_root):
            versioning.snapshot(
                config.vault_root,
                config,
                phase="metadata",
                task_name=task_name,
                run_id=run_id,
                message=f"vault-agent: metadata {task_name} {run_id}",
                metadata={"run_id": run_id, "task_name": task_name, "status": status},
            )
    if error and status == "failed":
        print(f"vault-agent versioning blocked\nError: {error}")
    return exit_code


def expected_mass_edit(config: AgentConfig, count: int | None) -> int | None:
    return count


def _change_set(
    config: AgentConfig,
    *,
    run_id: str,
    task_name: str,
    command_args: list[str],
    started_at: str,
    pre_commit: str | None,
    post_commit: str | None,
    changed: list[versioning.ChangedFile],
    status: str,
    exit_code: int,
    error: str,
    diff_summary: str,
) -> dict:
    changed_files = [item.path for item in changed]
    created = [item.path for item in changed if "A" in item.status]
    deleted = [item.path for item in changed if "D" in item.status]
    renamed = [
        {"from": item.old_path, "to": item.path}
        for item in changed
        if item.status.startswith("R")
    ]
    return {
        "run_id": run_id,
        "task_name": task_name,
        "started_at": started_at,
        "completed_at": versioning.now_timestamp(),
        "pre_commit": pre_commit,
        "post_commit": post_commit,
        "changed_files": changed_files,
        "created_files": created,
        "deleted_files": deleted,
        "renamed_files": renamed,
        "diff_summary": diff_summary,
        "agent": "vault-agent",
        "tool_name": "vault-agent",
        "model": config.llm_model if config.llm_enabled else None,
        "backend": config.llm_provider if config.llm_enabled else None,
        "status": status,
        "exit_code": exit_code,
        "error": error,
        "command_args": command_args,
        "rollback_hints": {
            "one_path": f"vault-agent --vault-root {config.vault_root} version restore {run_id} --path <path>",
            "all": f"vault-agent --vault-root {config.vault_root} version undo-run {run_id}",
        },
    }


def _check_expected_mass_edit(
    config: AgentConfig,
    *,
    mass_edit: bool,
    expected_changed_files: int | None,
    expected_deletions: int | None,
    command_args: list[str],
) -> None:
    if not config.versioning_require_explicit_mass_edit_flag or mass_edit:
        return
    reason = _mass_edit_reason(
        config, expected_changed_files or 0, expected_deletions or 0, mass_edit
    )
    if reason:
        retry = " ".join(command_args + ["--mass-edit"])
        raise MassEditBlocked(f"{reason}. Retry explicitly with: {retry}")


def _mass_edit_reason(
    config: AgentConfig, changed_files: int, deletions: int, mass_edit: bool
) -> str:
    if not config.versioning_require_explicit_mass_edit_flag or mass_edit:
        return ""
    if changed_files > config.versioning_mass_edit_threshold_files:
        return (
            f"mass edit threshold exceeded: {changed_files} changed files "
            f"> {config.versioning_mass_edit_threshold_files}"
        )
    if deletions > config.versioning_mass_edit_threshold_deletions:
        return (
            f"mass deletion threshold exceeded: {deletions} deletions "
            f"> {config.versioning_mass_edit_threshold_deletions}"
        )
    return ""


@contextmanager
def _vault_lock(config: AgentConfig):
    lockfile = (
        Path(config.versioning_lockfile).expanduser()
        if config.versioning_lockfile
        else config.vault_root / config.paths.agent_dir / "versioning" / "run.lock"
    )
    if not lockfile.is_absolute():
        lockfile = config.vault_root / lockfile
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        atomic_write_text(lockfile, str(os.getpid()))
        yield
    finally:
        os.close(fd)
        lockfile.unlink(missing_ok=True)
