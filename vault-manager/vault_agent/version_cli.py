"""CLI rendering for Git-backed vault versioning."""

from __future__ import annotations

import json
from pathlib import Path

from .config import AgentConfig
from . import versioning


def run_version_init(config: AgentConfig) -> tuple[int, str]:
    versioning.ensure_initialized(config.vault_root, config)
    snap = versioning.snapshot(
        config.vault_root,
        config,
        phase="init",
        task_name="version-init",
        message="vault-agent: version init",
        metadata={"task_name": "version init"},
        allow_empty=versioning.current_commit(config.vault_root) is None,
    )
    return (
        0,
        "vault-agent version init complete\n"
        f"Git initialized: true\n"
        f"Current commit: {snap.commit or '(none)'}",
    )


def run_version_status(config: AgentConfig) -> tuple[int, str]:
    info = versioning.status(config.vault_root)
    lines = [
        "vault-agent version status",
        f"Git initialized: {str(info.initialized).lower()}",
        f"Dirty: {str(info.dirty).lower()}",
        f"Current commit: {info.current_commit or '(none)'}",
        f"Branch: {info.branch or '(none)'}",
        f"Pending changes: {len(info.changed_files)}",
    ]
    for item in info.changed_files:
        if item.old_path:
            lines.append(f"- {item.status} {item.old_path} -> {item.path}")
        else:
            lines.append(f"- {item.status} {item.path}")
    return 0, "\n".join(lines)


def run_version_log(config: AgentConfig, *, limit: int = 20) -> tuple[int, str]:
    records = versioning.load_change_sets(config.vault_root)
    commits = versioning.recent_commits(config.vault_root, limit=limit)
    lines = ["vault-agent version log", "", "Agent runs:"]
    if not records:
        lines.append("- (none)")
    for record in reversed(records[-limit:]):
        lines.append(
            f"- {record.get('run_id')} {record.get('task_name')} "
            f"{record.get('status')} {record.get('post_commit') or '(no post commit)'}"
        )
    lines.extend(["", "Recent commits:"])
    if not commits:
        lines.append("- (none)")
    for commit in commits:
        lines.append(f"- {commit['short']} {commit['timestamp']} {commit['subject']}")
    return 0, "\n".join(lines)


def run_version_show(config: AgentConfig, target: str) -> tuple[int, str]:
    record = versioning.find_change_set(config.vault_root, target)
    if record:
        return 0, json.dumps(record, indent=2, sort_keys=True)
    commits = [
        item
        for item in versioning.recent_commits(config.vault_root, limit=200)
        if item["commit"].startswith(target) or item["short"] == target
    ]
    if not commits:
        return 1, f"vault-agent version show failed\nNo run or commit found: {target}"
    return 0, json.dumps(commits[0], indent=2, sort_keys=True)


def run_version_diff(config: AgentConfig, target: str) -> tuple[int, str]:
    record = versioning.find_change_set(config.vault_root, target)
    if record:
        pre = record.get("pre_commit")
        post = record.get("post_commit")
        if not pre or not post:
            return 0, ""
        return 0, versioning.diff(config.vault_root, from_ref=pre, to_ref=post)
    return 0, versioning.diff(config.vault_root, from_ref=f"{target}^", to_ref=target)


def run_version_changed_files(config: AgentConfig, target: str) -> tuple[int, str]:
    record = versioning.find_change_set(config.vault_root, target)
    if record:
        return 0, "\n".join(record.get("changed_files", []))
    files = versioning.changed_files(config.vault_root, f"{target}^", target)
    return 0, "\n".join(item.path for item in files)


def run_version_restore(
    config: AgentConfig,
    target: str,
    *,
    paths: list[str],
    all_paths: bool = False,
    force: bool = False,
) -> tuple[int, str]:
    record = versioning.find_change_set(config.vault_root, target)
    commit = target
    restore_paths = paths
    if record:
        commit = record.get("pre_commit")
        if not commit:
            return 1, f"vault-agent version restore failed\nRun has no pre-commit: {target}"
        if all_paths:
            if config.versioning_full_restore_requires_force and not force:
                return (
                    1,
                    "vault-agent version restore failed\n"
                    "Restoring all affected paths requires --force.",
                )
            restore_paths = list(record.get("changed_files", []))
    if not restore_paths:
        return 1, "vault-agent version restore failed\nPass --path <path> or --all."
    normalized = [_normalize_path(path) for path in restore_paths]
    created = set(record.get("created_files", [])) if record else set()
    delete_paths = [path for path in normalized if path in created]
    checkout_paths = [path for path in normalized if path not in created]
    _delete_created_paths(config, delete_paths, force=force)
    if checkout_paths:
        versioning.restore(
            config.vault_root,
            commit=commit,
            paths=checkout_paths,
            force=force,
            protected_paths=config.versioning_protected_paths,
        )
    return (
        0,
        "vault-agent version restore complete\n"
        f"Source commit: {commit}\n"
        f"Restored paths: {len(normalized)}",
    )


def run_version_undo_run(config: AgentConfig, run_id: str, *, force: bool = False) -> tuple[int, str]:
    record = versioning.find_change_set(config.vault_root, run_id)
    if not record:
        return 1, f"vault-agent version undo-run failed\nNo run found: {run_id}"
    commit = record.get("pre_commit")
    paths = list(record.get("changed_files", []))
    if not commit:
        return 1, f"vault-agent version undo-run failed\nRun has no pre-commit: {run_id}"
    if not paths:
        return 0, "vault-agent version undo-run complete\nNo affected files to restore."
    created = set(record.get("created_files", []))
    delete_paths = [path for path in paths if path in created]
    checkout_paths = [path for path in paths if path not in created]
    _delete_created_paths(config, delete_paths, force=force)
    if checkout_paths:
        versioning.restore(
            config.vault_root,
            commit=commit,
            paths=checkout_paths,
            force=force,
            protected_paths=config.versioning_protected_paths,
        )
    return (
        0,
        "vault-agent version undo-run complete\n"
        f"Run: {run_id}\n"
        f"Restored paths: {len(paths)}",
    )


def _normalize_path(path: str) -> str:
    target = Path(path)
    if target.is_absolute() or ".." in target.parts:
        raise versioning.VersioningError(f"path must stay relative to vault root: {path}")
    return target.as_posix()


def _delete_created_paths(config: AgentConfig, paths: list[str], *, force: bool) -> None:
    for path in paths:
        if _is_protected(path, config.versioning_protected_paths) and not force:
            raise versioning.VersioningError(
                f"restore targets protected path; retry with --force: {path}"
            )
        target = config.vault_root / path
        if target.is_file() or target.is_symlink():
            target.unlink()


def _is_protected(path: str, protected_paths: list[str]) -> bool:
    normalized = Path(path).as_posix().strip("/")
    for protected in protected_paths:
        prefix = Path(protected).as_posix().strip("/")
        if normalized == prefix or normalized.startswith(prefix.rstrip("/") + "/"):
            return True
    return False
