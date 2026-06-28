"""Shared helpers for the pi-vault model eval suite.

This package evaluates the *served* local models against frozen, Claude-authored
gold fixtures. It deliberately reuses the production code paths in ``vault_agent``
(the real stage prompts, validators, embedding client, and ranking) so it measures
what ships rather than a re-implementation.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

# Make ``vault_agent`` importable when scripts are run from anywhere.
EVALS_DIR = Path(__file__).resolve().parent
VAULT_MANAGER_DIR = EVALS_DIR.parent
if str(VAULT_MANAGER_DIR) not in sys.path:
    sys.path.insert(0, str(VAULT_MANAGER_DIR))

from vault_agent.frontmatter import parse_note  # noqa: E402

FIXTURES_DIR = EVALS_DIR / "fixtures"
CONFIGS_DIR = EVALS_DIR / "configs"
RESULTS_DIR = EVALS_DIR / "results"
DEFAULT_VAULT = VAULT_MANAGER_DIR / "test_vaults" / "Memex"

# The constrained vocabularies live in the production schema module; import them so
# the suite and the engine can never drift.
from vault_agent.schema import (  # noqa: E402
    COMMON_PROPERTIES,
    NOTE_TYPES,
    RECOMMENDED_TOPIC_HUBS,
)

ALLOWED_TYPES = [v for v in NOTE_TYPES]
ALLOWED_STATUS = [v for v in COMMON_PROPERTIES["status"]["allowed"] if v]
ALLOWED_DOMAIN = [v for v in COMMON_PROPERTIES["domain"]["allowed"] if v]
ALLOWED_SOURCE_KIND = [v for v in COMMON_PROPERTIES["source_kind"]["allowed"] if v]
ALLOWED_CAPTURE_TYPE = [v for v in COMMON_PROPERTIES["capture_type"]["allowed"] if v]


# --------------------------------------------------------------------------- IO


def load_json(path: Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def load_yaml(path: Path) -> Any:
    import yaml

    with Path(path).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# ------------------------------------------------------------------ vault notes


def read_note(vault_root: Path, rel_path: str) -> tuple[str, str, dict[str, Any]]:
    """Return ``(title, body, frontmatter)`` for a vault-relative note path.

    ``body`` excludes the YAML frontmatter, so feeding it to a model never leaks
    the existing (untrusted) labels. ``title`` falls back to the filename stem.
    """
    text = (Path(vault_root) / rel_path).read_text(encoding="utf-8")
    parsed = parse_note(text)
    title = ""
    if parsed.has_frontmatter and isinstance(parsed.frontmatter.get("title"), str):
        title = parsed.frontmatter["title"].strip()
    if not title:
        title = Path(rel_path).stem
    body = parsed.body if parsed.has_frontmatter else text
    return title, body, dict(parsed.frontmatter)


def neutral_path(rel_path: str) -> Path:
    """A leak-proof path for the model: basename under a neutral inbox folder.

    The real directory (``06 People/...``) would otherwise hand the model the
    answer for type/folder classification. We keep the filename (a legitimate
    production signal) but strip the revealing folder.
    """
    return Path("01 Inbox") / Path(rel_path).name


def note_for_model(vault_root: Path, rel_path: str) -> tuple[Path, str]:
    """Return ``(neutral_path, model_text)`` to feed a stage prompt.

    The model text is ``title\\n\\nbody`` so the title signal survives the folder
    neutralisation. Frontmatter is already stripped by :func:`read_note`.
    """
    title, body, _ = read_note(vault_root, rel_path)
    text = f"{title}\n\n{body}".strip() if title else body
    return neutral_path(rel_path), text


# ------------------------------------------------------------------ statistics


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def list_notes(vault_root: Path) -> list[str]:
    """Vault-relative paths of all markdown notes, excluding Obsidian/system dirs."""
    root = Path(vault_root)
    skip = {".obsidian", ".git", ".trash"}
    out = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part in skip for part in rel.parts):
            continue
        out.append(rel.as_posix())
    return out


def sample_corpus(vault_root: Path, referenced: list[str], *, target: int = 150,
                  seed: int = 17) -> list[str]:
    """A deterministic retrieval corpus that always contains every referenced note.

    Mean-centering needs >=25 notes, and recall metrics need realistic distractors,
    so we pad the referenced set with a stable random sample up to ``target``.
    """
    import random

    referenced = [p for p in referenced if (Path(vault_root) / p).exists()]
    chosen = list(dict.fromkeys(referenced))
    pool = [p for p in list_notes(vault_root) if p not in set(chosen)]
    rng = random.Random(seed)
    rng.shuffle(pool)
    for path in pool:
        if len(chosen) >= target:
            break
        chosen.append(path)
    return sorted(chosen)


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (pct in [0, 100])."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    frac = rank - low
    return ordered[low] * (1 - frac) + ordered[high] * frac
