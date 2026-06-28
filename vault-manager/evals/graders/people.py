"""Grade people-related output.

Two independent tasks:
- ``classify-person``: contact vs author for a person note (exact-match, reuses
  the constrained grader).
- people *extraction*: the set of people a model pulls from a note body, scored
  as set precision/recall/F1 against a gold name set (name-normalised).
"""

from __future__ import annotations

import re
from typing import Any

from evals.graders.constrained import grade_field


def grade_classify(items: list[dict[str, Any]]) -> dict[str, Any]:
    """``items``: ``[{"pred", "gold"}]`` with values ``contact``/``author``."""
    return grade_field(items)


def _norm_name(name: str) -> str:
    name = re.sub(r"^\[\[|\]\]$", "", (name or "").strip())
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name


def grade_extraction(items: list[dict[str, Any]]) -> dict[str, Any]:
    """``items``: ``[{"path", "pred": [names], "gold": [names]}]``."""
    tp = fp = fn = 0
    per_note = []
    for it in items:
        pred = {_norm_name(x) for x in (it.get("pred") or []) if _norm_name(x)}
        gold = {_norm_name(x) for x in (it.get("gold") or []) if _norm_name(x)}
        note_tp = len(pred & gold)
        note_fp = len(pred - gold)
        note_fn = len(gold - pred)
        tp += note_tp
        fp += note_fp
        fn += note_fn
        per_note.append(
            {
                "path": it.get("path"),
                "tp": note_tp,
                "fp": note_fp,
                "fn": note_fn,
                "missed": sorted(gold - pred),
                "spurious": sorted(pred - gold),
            }
        )

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "n": len(items),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "per_note": per_note,
    }
