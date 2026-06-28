"""Grade refine-body output against the engine's hard rule.

`refine-body` may only add Markdown structural tokens and short heading labels;
it must reuse the author's exact words and invent nothing. We measure that
directly and token-free:

- ``preservation``: fraction of the source's word occurrences that survive in the
  refined body (multiset recall). 1.0 means every original word is still present.
- ``added_ratio``: fraction of refined words that are NOT in the source, after
  removing a small allow-list of structural heading words the rule permits. High
  values flag paraphrase/invention.

These are proxies; a finalists-only Claude rubric (judge/claude_rubric.py) can be
layered on top for structure quality, but routine runs need no tokens.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_WORD_RE = re.compile(r"[a-z0-9']+")

# Short labels the rule explicitly allows a model to add as headings.
_ALLOWED_ADDED = {
    "summary", "notes", "overview", "details", "context", "background",
    "links", "related", "tasks", "actions", "references", "key", "points",
    "todo", "log", "agenda", "decisions", "questions",
}


def words(text: str) -> Counter:
    return Counter(_WORD_RE.findall((text or "").lower()))


def grade_one(source_body: str, refined_body: str) -> dict[str, Any]:
    src = words(source_body)
    ref = words(refined_body)
    total_src = sum(src.values())
    total_ref = sum(ref.values())

    preserved = sum(min(src[w], ref[w]) for w in src)
    preservation = preserved / total_src if total_src else 1.0

    added = Counter()
    for w, count in ref.items():
        extra = count - src.get(w, 0)
        if extra > 0 and w not in _ALLOWED_ADDED:
            added[w] += extra
    added_total = sum(added.values())
    added_ratio = added_total / total_ref if total_ref else 0.0

    return {
        "preservation": round(preservation, 4),
        "added_ratio": round(added_ratio, 4),
        "src_words": total_src,
        "ref_words": total_ref,
        "top_added": [w for w, _ in added.most_common(8)],
    }


def grade_refine(items: list[dict[str, Any]]) -> dict[str, Any]:
    """``items``: ``[{"path", "source", "pred"}]`` (pred is the refined body)."""
    scored = [it for it in items if isinstance(it.get("pred"), str) and it["pred"].strip()]
    per_note = []
    preservations: list[float] = []
    added_ratios: list[float] = []
    clean = 0  # preservation >= 0.98 and added_ratio <= 0.05
    for it in scored:
        one = grade_one(it["source"], it["pred"])
        one["path"] = it.get("path")
        per_note.append(one)
        preservations.append(one["preservation"])
        added_ratios.append(one["added_ratio"])
        if one["preservation"] >= 0.98 and one["added_ratio"] <= 0.05:
            clean += 1

    n_total = len(items)
    n_scored = len(scored)
    return {
        "n": n_total,
        "n_scored": n_scored,
        "produced_rate": round(n_scored / n_total, 4) if n_total else 0.0,
        "mean_preservation": round(sum(preservations) / len(preservations), 4) if preservations else 0.0,
        "mean_added_ratio": round(sum(added_ratios) / len(added_ratios), 4) if added_ratios else 0.0,
        "clean_rate": round(clean / n_scored, 4) if n_scored else 0.0,
        "per_note": per_note,
    }
