"""Evaluate every served embedding model in a single pass.

Both embedding models are served at once, so this builds one controlled corpus
and runs it through each endpoint:

    python -m evals.runners.run_embeddings

For each model it reports retrieval quality (Recall@k / MRR / nDCG), related-link
precision, duplicate detection, a per-model threshold recalibration, and
operational cost (dimensions, index size, throughput). It also reports
cross-model agreement (the cheaper model vs the 4B reference). Reuses the
production embedding client and ranking/centering helpers.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from evals.common import (
    CONFIGS_DIR,
    DEFAULT_VAULT,
    FIXTURES_DIR,
    RESULTS_DIR,
    dump_json,
    load_json,
    load_yaml,
    read_note,
    sample_corpus,
)
from evals.graders import retrieval
from vault_agent.embeddings import EmbeddingClient
from vault_agent.embedding_index import DEFAULT_EXCERPT_CHARS, embedding_text


def _referenced_paths(gold_notes: dict, retrieval_gold: dict) -> list[str]:
    refs: set[str] = set()
    for note in gold_notes.get("notes", []):
        refs.add(note["path"])
    for q in retrieval_gold.get("queries", []):
        refs.update(q.get("relevant", []))
    for pair in retrieval_gold.get("related_pairs", []):
        refs.add(pair["path"])
        refs.update(pair.get("related", []))
    for dup in retrieval_gold.get("duplicates", []):
        for key in ("a_path", "b_path"):
            if dup.get(key):
                refs.add(dup[key])
    return sorted(refs)


def _corpus_texts(vault_root: Path, corpus: list[str], excerpt_chars: int) -> tuple[list[str], dict[str, str]]:
    texts = []
    titles: dict[str, str] = {}
    for rel in corpus:
        title, body, _ = read_note(vault_root, rel)
        titles[rel] = title
        texts.append(embedding_text(title, body, excerpt_chars=excerpt_chars))
    return texts, titles


def _dup_text(vault_root: Path, dup: dict, side: str) -> str:
    path = dup.get(f"{side}_path")
    if path:
        title, body, _ = read_note(vault_root, path)
        return embedding_text(title, body, excerpt_chars=DEFAULT_EXCERPT_CHARS)
    return dup.get(f"{side}_text", "")


def evaluate_endpoint(endpoint: dict, *, vault_root: Path, corpus: list[str],
                      corpus_texts: list[str], titles: dict[str, str], retrieval_gold: dict,
                      thresholds: dict, excerpt_chars: int,
                      sweep_floors: list[float] | None = None,
                      lexical: bool = False, related_topk: int = 5,
                      related_floor: float | None = None) -> dict[str, Any]:
    client = EmbeddingClient(
        base_url=endpoint["base_url"],
        model=endpoint.get("model", "embed"),
        timeout_seconds=int(endpoint.get("timeout_seconds", 120)),
        batch_size=int(endpoint.get("batch_size", 32)),
    )

    start = time.monotonic()
    vectors = client.embed(corpus_texts)
    embed_seconds = time.monotonic() - start

    records = [{"path": rel, "title": titles.get(rel, ""), "vector": vec}
               for rel, vec in zip(corpus, vectors)]
    index = retrieval.build_index(records)
    dims = index["dimensions"]
    identity = client.model_identity()

    # Queries
    query_texts = [q["query"] for q in retrieval_gold.get("queries", [])]
    query_vectors = client.embed(query_texts) if query_texts else []
    queries = [
        {"query": q["query"], "query_vector": qv, "relevant": q.get("relevant", [])}
        for q, qv in zip(retrieval_gold.get("queries", []), query_vectors)
    ]
    retr = retrieval.retrieval_metrics(queries, index, ks=(5, 10), titles=titles, lexical=lexical)

    related_floor_used = related_floor if related_floor is not None else thresholds["related_min_similarity"]
    related = retrieval.related_links_metrics(
        retrieval_gold.get("related_pairs", []),
        index,
        top_k=related_topk,
        min_similarity=related_floor_used,
    )

    # Duplicates
    dup_pairs = []
    for dup in retrieval_gold.get("duplicates", []):
        a_text = _dup_text(vault_root, dup, "a")
        b_text = _dup_text(vault_root, dup, "b")
        if not a_text or not b_text:
            continue
        av, bv = client.embed([a_text, b_text])
        dup_pairs.append({"label": dup.get("label"), "a_vector": av, "b_vector": bv})
    dupes = retrieval.duplicate_metrics(dup_pairs, threshold=thresholds["duplicate_min_similarity"])

    # Threshold sweep reuses the already-built index (no re-embedding), so the
    # related-links F1 response curve is cheap to trace across floors.
    related_sweep = []
    for floor in sweep_floors or []:
        m = retrieval.related_links_metrics(
            retrieval_gold.get("related_pairs", []), index, top_k=related_topk, min_similarity=floor
        )
        related_sweep.append(
            {"floor": floor, "precision": m["precision"], "recall": m["recall"],
             "f1": m["f1"], "n": m["n"]}
        )

    calibration = retrieval.calibrate(index)

    index_size = sum(len(v) for v in vectors) * 8  # float64 estimate, bytes
    operational = {
        "dimensions": dims,
        "model_identity": identity,
        "corpus_notes": len(corpus),
        "embed_seconds": round(embed_seconds, 2),
        "notes_per_second": round(len(corpus) / embed_seconds, 2) if embed_seconds else 0.0,
        "vector_bytes_estimate": index_size,
        "vram_gb": endpoint.get("vram_gb"),
    }

    return {
        "key": endpoint["key"],
        "label": endpoint.get("label", endpoint["key"]),
        "base_url": endpoint["base_url"],
        "params": {"lexical_boost": lexical, "related_topk": related_topk,
                   "related_floor": related_floor_used},
        "retrieval": retr,
        "related_links": related,
        "related_sweep": related_sweep,
        "duplicates": dupes,
        "calibration": calibration,
        "operational": operational,
        "_index": index,  # kept for agreement; stripped before writing
    }


def run(vault_root: Path, *, corpus_target: int,
        sweep_floors: list[float] | None = None,
        lexical: bool = False, related_topk: int = 5,
        related_floor: float | None = None) -> dict[str, Any]:
    cfg = load_yaml(CONFIGS_DIR / "embeddings.yaml")
    gold_notes = load_json(FIXTURES_DIR / "gold_notes.json")
    retrieval_gold = load_json(FIXTURES_DIR / "retrieval_gold.json")
    thresholds = cfg["default_thresholds"]
    excerpt_chars = int(cfg.get("excerpt_chars", DEFAULT_EXCERPT_CHARS))

    referenced = _referenced_paths(gold_notes, retrieval_gold)
    corpus = sample_corpus(vault_root, referenced, target=corpus_target)
    corpus_texts, titles = _corpus_texts(vault_root, corpus, excerpt_chars)

    endpoints = []
    for endpoint in cfg["endpoints"]:
        merged = {"timeout_seconds": cfg.get("timeout_seconds", 120),
                  "batch_size": cfg.get("batch_size", 32), **endpoint}
        print(f"-- embedding {len(corpus)} notes via {merged['label']} ({merged['base_url']}) ...")
        endpoints.append(
            evaluate_endpoint(
                merged,
                vault_root=vault_root,
                corpus=corpus,
                corpus_texts=corpus_texts,
                titles=titles,
                retrieval_gold=retrieval_gold,
                thresholds=thresholds,
                excerpt_chars=excerpt_chars,
                sweep_floors=sweep_floors,
                lexical=lexical,
                related_topk=related_topk,
                related_floor=related_floor,
            )
        )

    # Cross-model agreement vs the first endpoint (the 4B reference).
    agreements = []
    if len(endpoints) >= 2:
        ref = endpoints[0]
        for other in endpoints[1:]:
            ag = retrieval.agreement(ref["_index"], other["_index"], top_k=5)
            ag["reference"] = ref["key"]
            ag["model"] = other["key"]
            agreements.append(ag)

    for endpoint in endpoints:
        endpoint.pop("_index", None)

    return {
        "kind": "embeddings",
        "corpus_notes": len(corpus),
        "default_thresholds": thresholds,
        "pass_params": {"lexical_boost": lexical, "related_topk": related_topk,
                        "related_floor": related_floor},
        "endpoints": endpoints,
        "agreement": agreements,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate all served embedding models.")
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT))
    parser.add_argument("--corpus-target", type=int, default=150)
    parser.add_argument("--related-sweep", default="",
                        help="comma-separated floors to sweep related-links F1, e.g. 0.45,0.50,0.55,0.60,0.65")
    parser.add_argument("--tag", default="",
                        help="save to results/embeddings_<tag>.json instead of embeddings.json (preserves passes)")
    parser.add_argument("--lexical-boost", action="store_true",
                        help="apply the production title/path lexical boost to search ranking (affects MRR/nDCG)")
    parser.add_argument("--related-topk", type=int, default=5,
                        help="neighbours considered for related-links (lower = higher precision)")
    parser.add_argument("--related-floor", type=float, default=None,
                        help="override related_min_similarity for this pass (default: config value)")
    args = parser.parse_args()

    sweep_floors = [float(x) for x in args.related_sweep.split(",") if x.strip()] or None
    result = run(Path(args.vault_root), corpus_target=args.corpus_target, sweep_floors=sweep_floors,
                 lexical=args.lexical_boost, related_topk=args.related_topk,
                 related_floor=args.related_floor)
    out_path = RESULTS_DIR / (f"embeddings_{args.tag}.json" if args.tag else "embeddings.json")
    dump_json(out_path, result)

    pp = result["pass_params"]
    print(f"\n== embedding comparison ({result['corpus_notes']} notes) "
          f"[lexical_boost={pp['lexical_boost']} related_topk={pp['related_topk']} "
          f"related_floor={pp['related_floor'] if pp['related_floor'] is not None else 'cfg'}] ==")
    for endpoint in result["endpoints"]:
        r = endpoint["retrieval"]
        op = endpoint["operational"]
        rec = endpoint["calibration"]["recommended_thresholds"]
        print(f"\n{endpoint['label']}  (dims={op['dimensions']})")
        print(f"  Recall@5={r.get('recall@5')}  MRR={r.get('mrr')}  nDCG@10={r.get('ndcg@10')}")
        print(f"  related-links P/R/F1={endpoint['related_links']['precision']}/"
              f"{endpoint['related_links']['recall']}/{endpoint['related_links']['f1']}")
        print(f"  duplicate detection={endpoint['duplicates']['detection_rate']}")
        print(f"  recommended thresholds: min={rec['min_similarity']} related={rec['related_min_similarity']}")
        print(f"  throughput={op['notes_per_second']} notes/s")
    for ag in result["agreement"]:
        print(f"\nagreement {ag['model']} vs {ag['reference']}: "
              f"Jaccard@5={ag['jaccard@k']}  Spearman={ag['mean_spearman']}")

    if sweep_floors and result["endpoints"][0].get("related_sweep"):
        floors = [s["floor"] for s in result["endpoints"][0]["related_sweep"]]
        print("\n== related-links threshold sweep (F1 | recall) ==")
        print("floor              " + "  ".join(f"{f:>11}" for f in floors))
        for ep in result["endpoints"]:
            cells = "  ".join(f"{s['f1']:.2f}|{s['recall']:.2f}" for s in ep["related_sweep"])
            print(f"{ep['label'][:18]:<18} {cells}")
        for ep in result["endpoints"]:
            best = max(ep["related_sweep"], key=lambda s: (s["f1"], s["recall"]))
            print(f"  best {ep['label']}: floor={best['floor']} "
                  f"F1={best['f1']} (P={best['precision']}/R={best['recall']})")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
