"""Grade embedding-model retrieval quality and characterise its similarity space.

Everything operates on vectors so it is testable with the deterministic
FakeEmbeddingClient. It reuses the production ranking/centering helpers
(`rank`, `cosine`, `center`, `mean_vector`, `MIN_CENTER_NOTES`) so the metrics
reflect how the engine actually retrieves.

Provides:
- in-memory index build with the same >=25-note mean-centering rule
- Recall@k / MRR / nDCG@k for text queries with gold-relevant notes
- related-links precision/recall above a similarity threshold
- duplicate-pair detection rate
- per-model threshold *recalibration* (random-pair vs nearest-neighbor stats),
  so a model with a different cosine distribution is judged on its own scale
- cross-model agreement (Jaccard@k, Spearman) over a shared note set
"""

from __future__ import annotations

import math
import random
from typing import Any

from vault_agent.embeddings import cosine, rank
from vault_agent.embedding_index import MIN_CENTER_NOTES, center, mean_vector


# ----------------------------------------------------------------- index build


def build_index(records: list[dict[str, Any]]) -> dict[str, Any]:
    """``records``: ``[{"path", "vector"}]``. Applies the engine's centering rule."""
    vectors = [r["vector"] for r in records if r.get("vector")]
    centered = len(vectors) >= MIN_CENTER_NOTES
    mean = mean_vector(vectors) if centered else None
    dims = len(vectors[0]) if vectors else 0
    return {
        "records": records,
        "mean": mean,
        "centered": centered,
        "dimensions": dims,
        "note_count": len(records),
    }


def _ranking_records(index: dict[str, Any]) -> list[dict[str, Any]]:
    mean = index.get("mean") if index.get("centered") else None
    out = []
    for record in index["records"]:
        vector = record.get("vector")
        if not isinstance(vector, list):
            continue
        out.append({"path": record["path"], "vector": center(vector, mean) if mean else vector})
    return out


def _center_query(index: dict[str, Any], query_vector: list[float]) -> list[float]:
    mean = index.get("mean") if index.get("centered") else None
    return center(query_vector, mean) if mean else query_vector


def neighbors(
    index: dict[str, Any],
    query_vector: list[float],
    *,
    top_k: int,
    min_similarity: float | None = None,
    exclude_paths: set[str] | None = None,
) -> list[tuple[str, float]]:
    return rank(
        _center_query(index, query_vector),
        _ranking_records(index),
        top_k=top_k,
        min_similarity=min_similarity,
        exclude_paths=exclude_paths or set(),
    )


# --------------------------------------------------------------- query metrics


def _dcg(relevances: list[int]) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))


def retrieval_metrics(
    queries: list[dict[str, Any]],
    index: dict[str, Any],
    *,
    ks: tuple[int, ...] = (5, 10),
    titles: dict[str, str] | None = None,
    lexical: bool = False,
) -> dict[str, Any]:
    """``queries``: ``[{"query", "query_vector", "relevant": [paths]}]``.

    When ``lexical`` is set (and ``titles`` provided), candidates are re-ranked
    with the production title/path lexical boost (``vault_agent.search._hybrid_rank``),
    matching how the engine's vault-search actually ranks results.
    """
    max_k = max(ks)
    recall_hits = {k: [] for k in ks}
    ndcg_scores = {k: [] for k in ks}
    rr: list[float] = []
    per_query = []

    hybrid_rank = None
    if lexical and titles:
        from vault_agent.search import _hybrid_rank as hybrid_rank  # noqa: N813

    for q in queries:
        relevant = set(q.get("relevant") or [])
        if not relevant:
            continue
        if hybrid_rank is not None:
            # Mirror search.run_search: pull a wider candidate pool, then re-rank.
            candidates = neighbors(index, q["query_vector"], top_k=max(max_k * 5, 20))
            reranked = hybrid_rank(q.get("query", ""), candidates, titles, limit=max_k)
            ranked_paths = [item["path"] for item in reranked]
        else:
            ranked = neighbors(index, q["query_vector"], top_k=max_k)
            ranked_paths = [path for path, _ in ranked]

        first_rank = next((i + 1 for i, p in enumerate(ranked_paths) if p in relevant), None)
        rr.append(1.0 / first_rank if first_rank else 0.0)

        row = {"query": q.get("query"), "first_rank": first_rank}
        for k in ks:
            top = ranked_paths[:k]
            hits = sum(1 for p in top if p in relevant)
            recall = hits / len(relevant)
            recall_hits[k].append(recall)
            rels = [1 if p in relevant else 0 for p in top]
            ideal = sorted([1] * min(len(relevant), k) + [0] * k, reverse=True)[:k]
            idcg = _dcg(ideal)
            ndcg = _dcg(rels) / idcg if idcg else 0.0
            ndcg_scores[k].append(ndcg)
            row[f"recall@{k}"] = round(recall, 4)
        per_query.append(row)

    def avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    out: dict[str, Any] = {"n": len(per_query), "mrr": avg(rr), "per_query": per_query}
    for k in ks:
        out[f"recall@{k}"] = avg(recall_hits[k])
        out[f"ndcg@{k}"] = avg(ndcg_scores[k])
    return out


# ----------------------------------------------------------------- related links


def related_links_metrics(
    pairs: list[dict[str, Any]],
    index: dict[str, Any],
    *,
    top_k: int = 5,
    min_similarity: float = 0.65,
) -> dict[str, Any]:
    """``pairs``: ``[{"path", "related": [paths]}]`` using each note as its own query."""
    by_path = {r["path"]: r for r in index["records"]}
    tp = fp = fn = 0
    per_note = []
    for pair in pairs:
        path = pair["path"]
        gold = set(pair.get("related") or [])
        record = by_path.get(path)
        if record is None or not record.get("vector") or not gold:
            continue
        found = neighbors(
            index,
            record["vector"],
            top_k=top_k,
            min_similarity=min_similarity,
            exclude_paths={path},
        )
        found_paths = {p for p, _ in found}
        note_tp = len(found_paths & gold)
        note_fp = len(found_paths - gold)
        note_fn = len(gold - found_paths)
        tp += note_tp
        fp += note_fp
        fn += note_fn
        per_note.append(
            {
                "path": path,
                "found": [p for p, _ in found],
                "missed": sorted(gold - found_paths),
            }
        )

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "n": len(per_note),
        "top_k": top_k,
        "min_similarity": min_similarity,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "per_note": per_note,
    }


# -------------------------------------------------------------------- duplicates


def duplicate_metrics(
    dup_pairs: list[dict[str, Any]],
    *,
    threshold: float = 0.97,
) -> dict[str, Any]:
    """``dup_pairs``: ``[{"a_vector", "b_vector", "label"}]`` of known near-dupes.

    Duplicate surfacing in the engine is raw-cosine based (near-identical text
    sits at the top regardless of centering), so detection uses raw cosine.
    """
    detected = 0
    per_pair = []
    sims: list[float] = []
    for pair in dup_pairs:
        sim = cosine(pair["a_vector"], pair["b_vector"])
        sims.append(sim)
        hit = sim >= threshold
        detected += int(hit)
        per_pair.append({"label": pair.get("label"), "cosine": round(sim, 4), "detected": hit})
    n = len(dup_pairs)
    return {
        "n": n,
        "threshold": threshold,
        "detection_rate": round(detected / n, 4) if n else 0.0,
        "mean_cosine": round(sum(sims) / len(sims), 4) if sims else 0.0,
        "per_pair": per_pair,
    }


# ----------------------------------------------------------------- calibration


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank_pos = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank_pos)
    high = math.ceil(rank_pos)
    if low == high:
        return ordered[int(rank_pos)]
    frac = rank_pos - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def calibrate(index: dict[str, Any], *, sample_pairs: int = 2000, seed: int = 17) -> dict[str, Any]:
    """Characterise the similarity space and recommend per-model thresholds.

    Computes random-pair and nearest-neighbor cosine distributions in both raw
    and centered spaces. The engine ranks in the centered space, so recommended
    thresholds are derived there: a high random-pair percentile as the search
    floor, a higher one for related-link precision, and the nearest-neighbor
    distribution to anchor the duplicate cut.
    """
    records = [r for r in index["records"] if r.get("vector")]
    paths = [r["path"] for r in records]
    raw_by_path = {r["path"]: r["vector"] for r in records}
    centered = _ranking_records(index)
    cen_by_path = {r["path"]: r["vector"] for r in centered}
    n = len(records)

    rng = random.Random(seed)
    raw_random: list[float] = []
    cen_random: list[float] = []
    if n >= 2:
        for _ in range(sample_pairs):
            a, b = rng.sample(paths, 2)
            raw_random.append(cosine(raw_by_path[a], raw_by_path[b]))
            cen_random.append(cosine(cen_by_path[a], cen_by_path[b]))

    raw_nn: list[float] = []
    cen_nn: list[float] = []
    for path in paths:
        top = rank(
            cen_by_path[path],
            [{"path": p, "vector": v} for p, v in cen_by_path.items()],
            top_k=1,
            exclude_paths={path},
        )
        if top:
            cen_nn.append(top[0][1])
            raw_nn.append(cosine(raw_by_path[path], raw_by_path[top[0][0]]))

    def stats(values: list[float]) -> dict[str, float]:
        return {
            "median": round(_percentile(values, 50), 4),
            "p95": round(_percentile(values, 95), 4),
            "p99": round(_percentile(values, 99), 4),
        }

    cen_random_p99 = _percentile(cen_random, 99)
    cen_random_p95 = _percentile(cen_random, 95)
    cen_nn_p25 = _percentile(cen_nn, 25)
    recommended = {
        # Floor for search candidates: above almost all random pairs.
        "min_similarity": round(max(0.0, cen_random_p95), 2),
        # Tighter floor for related-link proposals (precision over recall),
        # but never above where real neighbors live.
        "related_min_similarity": round(max(cen_random_p99, min(cen_nn_p25, cen_random_p99 + 0.1)), 2),
        # Raw-cosine duplicate cut stays high; report empirical near-dupe anchor.
        "duplicate_min_similarity": 0.97,
    }
    return {
        "note_count": n,
        "centered": index.get("centered", False),
        "raw_random": stats(raw_random),
        "centered_random": stats(cen_random),
        "raw_nearest": stats(raw_nn),
        "centered_nearest": stats(cen_nn),
        "centered_separation": round(_percentile(cen_nn, 50) - _percentile(cen_random, 50), 4),
        "recommended_thresholds": recommended,
    }


# ------------------------------------------------------------------- agreement


def _spearman(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        result = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg_rank = (i + j) / 2.0
            for k in range(i, j + 1):
                result[order[k]] = avg_rank
            i = j + 1
        return result

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    deny = math.sqrt(sum((b - my) ** 2 for b in ry))
    return round(num / (denx * deny), 4) if denx and deny else 0.0


def agreement(index_a: dict[str, Any], index_b: dict[str, Any], *, top_k: int = 5) -> dict[str, Any]:
    """Compare two models over their shared note set: neighbor overlap + ranking."""
    paths_a = {r["path"] for r in index_a["records"] if r.get("vector")}
    paths_b = {r["path"] for r in index_b["records"] if r.get("vector")}
    common = sorted(paths_a & paths_b)
    if len(common) < 3:
        return {"common_notes": len(common), "jaccard@k": 0.0, "mean_spearman": 0.0}

    cen_a = {r["path"]: r["vector"] for r in _ranking_records(index_a)}
    cen_b = {r["path"]: r["vector"] for r in _ranking_records(index_b)}
    common_set = set(common)

    jaccards: list[float] = []
    spearmans: list[float] = []
    for path in common:
        others = [p for p in common if p != path]

        def scores(vec_by_path):
            q = vec_by_path[path]
            return {p: cosine(q, vec_by_path[p]) for p in others}

        sa = scores(cen_a)
        sb = scores(cen_b)
        top_a = {p for p, _ in sorted(sa.items(), key=lambda kv: -kv[1])[:top_k]}
        top_b = {p for p, _ in sorted(sb.items(), key=lambda kv: -kv[1])[:top_k]}
        union = top_a | top_b
        if union:
            jaccards.append(len(top_a & top_b) / len(union))
        spearmans.append(_spearman([sa[p] for p in others], [sb[p] for p in others]))

    return {
        "common_notes": len(common),
        "top_k": top_k,
        "jaccard@k": round(sum(jaccards) / len(jaccards), 4) if jaccards else 0.0,
        "mean_spearman": round(sum(spearmans) / len(spearmans), 4) if spearmans else 0.0,
    }
