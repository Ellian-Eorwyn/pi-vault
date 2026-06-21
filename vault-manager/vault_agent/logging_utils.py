"""Command log helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .paths import agent_path
from .safety import atomic_write_text


def append_log(vault_root: Path, command: str, lines: list[str]) -> None:
    logs_dir = agent_path(vault_root, "logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = logs_dir / f"{today}.md"
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else f"# {today}\n"
    timestamp = datetime.now().isoformat(timespec="seconds")
    entry = [existing.rstrip(), "", f"## {timestamp} `{command}`", ""]
    entry.extend(f"- {line}" for line in lines)
    atomic_write_text(log_path, "\n".join(entry) + "\n")
