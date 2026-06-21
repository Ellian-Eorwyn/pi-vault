"""Git-backed safety and rollback helpers for vault-agent."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .paths import AGENT_DIR, paths_for
from .safety import atomic_write_text


MANAGED_GITIGNORE_BEGIN = "# BEGIN vault-agent managed ignores"
MANAGED_GITIGNORE_END = "# END vault-agent managed ignores"
CHANGE_SET_LOG = AGENT_DIR / "versioning" / "change-sets.jsonl"
RUN_DIR = AGENT_DIR / "versioning" / "runs"


class VersioningError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChangedFile:
    status: str
    path: str
    old_path: str | None = None


@dataclass(frozen=True)
class VersionStatus:
    initialized: bool
    dirty: bool
    current_commit: str | None
    branch: str | None
    changed_files: list[ChangedFile]


@dataclass(frozen=True)
class Snapshot:
    commit: str | None
    created: bool
    message: str


def ensure_initialized(vault_path: Path, config: AgentConfig) -> bool:
    vault_path = vault_path.resolve()
    vault_path.mkdir(parents=True, exist_ok=True)
    initialized = is_initialized(vault_path)
    if not initialized:
        if not config.versioning_auto_init:
            raise VersioningError("vault is not Git-initialized and versioning.auto_init is false")
        args = ["init"]
        separate = _resolve_optional_path(vault_path, config.versioning_separate_git_dir)
        if separate is not None:
            separate.parent.mkdir(parents=True, exist_ok=True)
            args.extend(["--separate-git-dir", str(separate)])
        _git(vault_path, args)
    if config.versioning_managed_gitignore:
        update_managed_gitignore(vault_path, config)
    return True


def is_initialized(vault_path: Path) -> bool:
    vault_path = vault_path.resolve()
    result = _git(vault_path, ["rev-parse", "--show-toplevel"], check=False)
    if result.returncode != 0:
        return False
    try:
        top_level = Path(result.stdout.strip()).resolve()
    except OSError:
        return False
    return top_level == vault_path


def status(vault_path: Path) -> VersionStatus:
    if not is_initialized(vault_path):
        return VersionStatus(False, False, None, None, [])
    return VersionStatus(
        initialized=True,
        dirty=bool(changed_files(vault_path)),
        current_commit=current_commit(vault_path),
        branch=current_branch(vault_path),
        changed_files=changed_files(vault_path),
    )


def snapshot(
    vault_path: Path,
    config: AgentConfig,
    *,
    phase: str,
    task_name: str,
    run_id: str | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
    allow_empty: bool = False,
) -> Snapshot:
    ensure_initialized(vault_path, config)
    files = changed_files(vault_path)
    if not files and not allow_empty:
        return Snapshot(current_commit(vault_path), False, message or "",)
    _git(vault_path, ["add", "-A"])
    commit_message = message or f"vault-agent: {phase} {task_name}"
    if run_id:
        commit_message = f"{commit_message} {run_id}"
    body = json.dumps(metadata or {}, indent=2, sort_keys=True)
    args = ["commit", "--allow-empty" if allow_empty else "--no-verify", "-m", commit_message]
    if allow_empty:
        args = ["commit", "--allow-empty", "-m", commit_message]
    else:
        args = ["commit", "--no-verify", "-m", commit_message]
    if body != "{}":
        args.extend(["-m", body])
    result = _git(vault_path, args, check=False, env=_author_env(config))
    if result.returncode != 0:
        text = (result.stderr or result.stdout).strip()
        if "nothing to commit" in text:
            return Snapshot(current_commit(vault_path), False, commit_message)
        raise VersioningError(text or "git commit failed")
    return Snapshot(current_commit(vault_path), True, commit_message)


def diff(
    vault_path: Path,
    *,
    from_ref: str | None = None,
    to_ref: str | None = None,
    paths: list[str] | None = None,
    stat: bool = False,
) -> str:
    args = ["diff"]
    if stat:
        args.append("--stat")
    if from_ref and to_ref:
        args.append(f"{from_ref}..{to_ref}")
    elif from_ref:
        args.append(from_ref)
    if paths:
        args.append("--")
        args.extend(paths)
    return _git(vault_path, args).stdout


def changed_files(
    vault_path: Path, from_ref: str | None = None, to_ref: str | None = None
) -> list[ChangedFile]:
    if not is_initialized(vault_path):
        return []
    if from_ref or to_ref:
        ref = f"{from_ref or 'HEAD'}..{to_ref or 'HEAD'}"
        output = _git(vault_path, ["diff", "--name-status", ref]).stdout
        return _parse_name_status(output)
    output = _git(vault_path, ["status", "--porcelain=v1", "-z"]).stdout
    return _parse_porcelain(output)


def restore(
    vault_path: Path,
    *,
    commit: str,
    paths: list[str],
    force: bool = False,
    protected_paths: list[str] | None = None,
) -> list[str]:
    if not paths:
        raise VersioningError("at least one path is required for restore")
    protected = protected_paths or []
    blocked = [path for path in paths if _is_protected(path, protected)]
    if blocked and not force:
        raise VersioningError(
            "restore targets protected paths; retry with --force: " + ", ".join(blocked)
        )
    _git(vault_path, ["checkout", commit, "--", *paths])
    return paths


def recent_commits(vault_path: Path, limit: int = 20) -> list[dict[str, str]]:
    if not is_initialized(vault_path):
        return []
    output = _git(
        vault_path,
        ["log", f"--max-count={limit}", "--pretty=format:%H%x00%h%x00%ci%x00%s"],
    ).stdout
    commits: list[dict[str, str]] = []
    for line in output.splitlines():
        parts = line.split("\x00")
        if len(parts) == 4:
            commits.append(
                {"commit": parts[0], "short": parts[1], "timestamp": parts[2], "subject": parts[3]}
            )
    return commits


def current_commit(vault_path: Path) -> str | None:
    result = _git(vault_path, ["rev-parse", "HEAD"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def current_branch(vault_path: Path) -> str | None:
    result = _git(vault_path, ["branch", "--show-current"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def update_managed_gitignore(vault_path: Path, config: AgentConfig) -> None:
    defaults = [
        ".DS_Store",
        "Thumbs.db",
        "*~",
        "*.tmp",
        "*.temp",
        ".~*",
        ".env",
        ".env.*",
        "*.key",
        "*.pem",
        "*.token",
        "*token*",
        (config.paths.agent_dir / "logs").as_posix() + "/",
        (config.paths.agent_dir / "backups").as_posix() + "/",
        (config.paths.agent_dir / "versioning/run.lock").as_posix(),
        (config.paths.agent_dir / "cache").as_posix() + "/",
        (config.paths.retrieval_dir / "vector*/").as_posix(),
        (config.paths.retrieval_dir / "embedding*/").as_posix(),
        "*.sqlite",
        "*.sqlite3",
        "*.db",
    ]
    lines = defaults + list(config.versioning_ignored_paths)
    block = "\n".join([MANAGED_GITIGNORE_BEGIN, *lines, MANAGED_GITIGNORE_END, ""])
    path = vault_path / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if MANAGED_GITIGNORE_BEGIN in existing and MANAGED_GITIGNORE_END in existing:
        before, rest = existing.split(MANAGED_GITIGNORE_BEGIN, 1)
        _old, after = rest.split(MANAGED_GITIGNORE_END, 1)
        content = before.rstrip() + "\n\n" + block + after.lstrip("\n")
    else:
        content = existing.rstrip() + ("\n\n" if existing.strip() else "") + block
    if content != existing:
        atomic_write_text(path, content)


def write_change_set(vault_path: Path, change_set: dict[str, Any]) -> Path:
    path = vault_path / paths_for(vault_path).agent_dir / "versioning/change-sets.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_write_text(path, existing + json.dumps(change_set, sort_keys=True) + "\n")
    return path


def load_change_sets(vault_path: Path) -> list[dict[str, Any]]:
    path = vault_path / paths_for(vault_path).agent_dir / "versioning/change-sets.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def find_change_set(vault_path: Path, run_id: str) -> dict[str, Any] | None:
    for record in reversed(load_change_sets(vault_path)):
        if record.get("run_id") == run_id:
            return record
    return None


def write_run_artifacts(
    vault_path: Path, run_id: str, *, metadata: dict[str, Any], diff_text: str
) -> tuple[Path, Path]:
    directory = vault_path / paths_for(vault_path).agent_dir / "versioning/runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    metadata_path = directory / "change-set.json"
    diff_path = directory / "diff.patch"
    atomic_write_text(metadata_path, json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    atomic_write_text(diff_path, diff_text)
    return metadata_path, diff_path


def summarize_diff(vault_path: Path, from_ref: str | None, to_ref: str | None) -> str:
    if not from_ref or not to_ref:
        return ""
    return diff(vault_path, from_ref=from_ref, to_ref=to_ref, stat=True)


def now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_name_status(output: str) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    for line in output.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        status_code = parts[0]
        if status_code.startswith("R") and len(parts) >= 3:
            files.append(ChangedFile("R", parts[2], parts[1]))
        elif len(parts) >= 2:
            files.append(ChangedFile(status_code[:1], parts[1]))
    return files


def _parse_porcelain(output: str) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    records = [record for record in output.split("\0") if record]
    index = 0
    while index < len(records):
        record = records[index]
        code = record[:2]
        path = record[3:]
        if code.startswith("R") and index + 1 < len(records):
            old_path = path
            index += 1
            files.append(ChangedFile("R", records[index], old_path))
        else:
            files.append(ChangedFile(code.strip() or "?", path))
        index += 1
    return files


def _git(
    vault_path: Path,
    args: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    # core.quotepath=false keeps non-ASCII paths (accents, curly quotes) raw instead of
    # octal-escaped+quoted, so paths recorded from `diff --name-status` round-trip back
    # through `checkout`/`restore`/`undo-run` for vaults with Unicode filenames.
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=vault_path,
        text=True,
        capture_output=True,
        env=run_env,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise VersioningError(message or f"git {' '.join(args)} failed")
    return result


def _author_env(config: AgentConfig) -> dict[str, str]:
    env: dict[str, str] = {}
    if config.versioning_commit_author_name:
        env["GIT_AUTHOR_NAME"] = config.versioning_commit_author_name
        env["GIT_COMMITTER_NAME"] = config.versioning_commit_author_name
    if config.versioning_commit_author_email:
        env["GIT_AUTHOR_EMAIL"] = config.versioning_commit_author_email
        env["GIT_COMMITTER_EMAIL"] = config.versioning_commit_author_email
    if not config.versioning_commit_author_name:
        env["GIT_AUTHOR_NAME"] = "vault-agent"
        env["GIT_COMMITTER_NAME"] = "vault-agent"
    if not config.versioning_commit_author_email:
        env["GIT_AUTHOR_EMAIL"] = "vault-agent@local"
        env["GIT_COMMITTER_EMAIL"] = "vault-agent@local"
    return env


def _resolve_optional_path(vault_path: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else vault_path / path


def _is_protected(path: str, protected_paths: list[str]) -> bool:
    normalized = Path(path).as_posix().strip("/")
    for protected in protected_paths:
        prefix = Path(protected).as_posix().strip("/")
        if normalized == prefix or normalized.startswith(prefix.rstrip("/") + "/"):
            return True
    return False
