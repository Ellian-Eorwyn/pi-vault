"""Finalists-only Claude rubric for summary faithfulness and refine structure.

Routine runs are decided by the token-free proxies (summary cosine, refine word
preservation). This module is the optional tie-breaker between the 2-3 surviving
candidates: it asks Claude to score a small, capped sample and caches the scores
so they are never recomputed.

It is intentionally NOT wired into run_main. Build the prompts here, run them
through whatever Claude access you have (API, or paste into a session), and drop
the scores into fixtures/judge_cache.json keyed by (model_key, stage, path).

Rubric (1-5):
- summary: faithfulness (no invented facts), coverage of the note's point, concision.
- refine-body: structure/readability improvement, given preservation is already
  machine-verified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.common import FIXTURES_DIR

CACHE_PATH = FIXTURES_DIR / "judge_cache.json"

SUMMARY_RUBRIC = (
    "Score this note summary from 1-5 on faithfulness (no invented facts), "
    "coverage of the note's main point, and concision. Return JSON "
    '{"faithfulness": int, "coverage": int, "concision": int, "note": str}.'
)
REFINE_RUBRIC = (
    "The refined body below already passed an automated exact-word-preservation "
    "check. Score 1-5 how much the Markdown restructuring improves readability "
    'without changing meaning. Return JSON {"structure": int, "note": str}.'
)


def build_prompt(stage: str, *, note_excerpt: str, candidate: str) -> str:
    rubric = SUMMARY_RUBRIC if stage == "summary" else REFINE_RUBRIC
    return f"{rubric}\n\n--- NOTE (excerpt) ---\n{note_excerpt[:2000]}\n\n--- CANDIDATE ---\n{candidate[:2000]}\n"


def load_cache() -> dict[str, Any]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def cache_key(model_key: str, stage: str, path: str) -> str:
    return f"{model_key}::{stage}::{path}"


def save_cache(cache: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8")
