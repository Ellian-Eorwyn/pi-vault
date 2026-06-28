"""Grade summary-stage output.

Quality without a judge: semantic closeness to a reference summary (cosine in an
embedding space) plus the engine's own length contract (1-3 sentences, <=1000
chars). The embedding function is injected so the same grader works with a real
EmbeddingClient or the deterministic FakeEmbeddingClient in tests.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from vault_agent.embeddings import cosine

_SENTENCE_RE = re.compile(r"[.!?]+(?:\s|$)")


def sentence_count(text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    parts = [p for p in _SENTENCE_RE.split(text) if p.strip()]
    return max(1, len(parts))


def length_ok(summary: str, *, min_sentences: int = 1, max_sentences: int = 3,
              max_chars: int = 1000) -> bool:
    if not summary or not summary.strip():
        return False
    if len(summary) > max_chars:
        return False
    return min_sentences <= sentence_count(summary) <= max_sentences


def grade_summaries(
    items: list[dict[str, Any]],
    embed: Callable[[list[str]], list[list[float]]],
) -> dict[str, Any]:
    """Grade summaries against references.

    ``items``: ``[{"path", "pred", "ref"}]``. ``embed`` maps a list of texts to
    vectors (batched once for efficiency). Returns per-note cosine + length flag
    and aggregate means.
    """
    scored = [it for it in items if isinstance(it.get("pred"), str) and it["pred"].strip()]
    texts: list[str] = []
    for it in scored:
        texts.append(it["pred"])
        texts.append(it["ref"])
    vectors = embed(texts) if texts else []

    per_note = []
    sims: list[float] = []
    length_flags: list[bool] = []
    for index, it in enumerate(scored):
        pred_vec = vectors[2 * index]
        ref_vec = vectors[2 * index + 1]
        sim = cosine(pred_vec, ref_vec)
        ok = length_ok(it["pred"])
        sims.append(sim)
        length_flags.append(ok)
        per_note.append(
            {
                "path": it.get("path"),
                "cosine": round(sim, 4),
                "length_ok": ok,
                "sentences": sentence_count(it["pred"]),
                "chars": len(it["pred"]),
            }
        )

    n_total = len(items)
    n_scored = len(scored)
    return {
        "n": n_total,
        "n_scored": n_scored,
        "produced_rate": round(n_scored / n_total, 4) if n_total else 0.0,
        "mean_cosine": round(sum(sims) / len(sims), 4) if sims else 0.0,
        "length_ok_rate": round(sum(length_flags) / len(length_flags), 4) if length_flags else 0.0,
        "per_note": per_note,
    }
