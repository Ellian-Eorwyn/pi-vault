"""Aggregate evals/results/*.json into a single leaderboard.

    python -m evals.report

Reads every main_*.json and embeddings.json present (partial runs are fine) and
writes evals/results/leaderboard.md and leaderboard.json. Surfaces quality,
robustness, speed, and VRAM side-by-side, diffs q4 vs q6 per architecture, and
prints a plain-language "what is safe to run" recommendation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evals.common import RESULTS_DIR, dump_json, load_json


def _g(result: dict, *path, default=None):
    cur: Any = result
    for key in path:
        if not isinstance(cur, dict) or key not in cur or cur[key] is None:
            return default
        cur = cur[key]
    return cur


def _main_row(result: dict) -> dict[str, Any]:
    grades = result.get("grades", {})
    pv = grades.get("property-values", {}) or {}
    return {
        "key": result.get("model_key"),
        "label": result.get("label"),
        "arch": result.get("arch"),
        "quant": result.get("quant"),
        "vram_gb": result.get("vram_gb"),
        "type_acc": _g(grades, "classify-type", "accuracy"),
        "status_acc": _g(pv, "status", "accuracy"),
        "domain_acc": _g(pv, "domain", "accuracy"),
        "source_kind_acc": _g(pv, "source_kind", "accuracy"),
        "folder_acc": _g(grades, "assign-folder", "accuracy"),
        "person_acc": _g(grades, "classify-person", "accuracy"),
        "summary_cos": _g(grades, "summary", "mean_cosine"),
        "refine_preserve": _g(grades, "refine-body", "mean_preservation"),
        "valid_rate": _g(result, "robustness", "valid_rate"),
        "first_pass_json": _g(result, "robustness", "first_pass_json_rate"),
        "tokens_s": _g(result, "speed", "tokens_per_second"),
        "median_s": _g(result, "speed", "median_wall_seconds"),
        "max_ctx": _g(result, "context", "max_total_tokens"),
        "p90_ctx": _g(result, "context", "p90_total_tokens"),
        "window": _g(result, "server_context_tokens"),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".") if value < 1 else f"{value:g}"
    return str(value)


def _composite_quality(row: dict) -> float:
    """Unweighted mean of the available quality signals (0-1)."""
    signals = [
        row.get("type_acc"), row.get("status_acc"), row.get("domain_acc"),
        row.get("folder_acc"), row.get("person_acc"), row.get("summary_cos"),
        row.get("refine_preserve"), row.get("valid_rate"),
    ]
    vals = [s for s in signals if isinstance(s, (int, float))]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def build() -> dict[str, Any]:
    main_rows = []
    for path in sorted(RESULTS_DIR.glob("main_*.json")):
        result = load_json(path)
        row = _main_row(result)
        row["composite_quality"] = _composite_quality(row)
        main_rows.append(row)

    embeddings = None
    emb_path = RESULTS_DIR / "embeddings.json"
    if emb_path.exists():
        embeddings = load_json(emb_path)

    return {"main": main_rows, "embeddings": embeddings}


def _main_table(rows: list[dict]) -> str:
    if not rows:
        return "_No main-model results yet. Run `python -m evals.runners.run_main --model <key>`._\n"
    headers = ["Model", "type", "status", "domain", "folder", "person",
               "sum·cos", "refine", "valid", "json1", "tok/s", "med·s",
               "max·ctx", "VRAM", "Q"]
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in sorted(rows, key=lambda r: -r["composite_quality"]):
        lines.append("| " + " | ".join(_fmt(v) for v in [
            row["label"], row["type_acc"], row["status_acc"], row["domain_acc"],
            row["folder_acc"], row["person_acc"], row["summary_cos"], row["refine_preserve"],
            row["valid_rate"], row["first_pass_json"], row["tokens_s"], row["median_s"],
            row["max_ctx"], row["vram_gb"], row["composite_quality"],
        ]) + " |")
    return "\n".join(lines) + "\n"


def _quant_diff(rows: list[dict]) -> str:
    by_arch: dict[str, dict[str, dict]] = {}
    for row in rows:
        if row.get("arch") and row.get("quant"):
            by_arch.setdefault(row["arch"], {})[row["quant"]] = row
    if not by_arch:
        return ""
    out = ["\n### q4 vs q6 (same architecture)\n"]
    for arch, quants in sorted(by_arch.items()):
        if "q4" in quants and "q6" in quants:
            q4, q6 = quants["q4"], quants["q6"]
            dq = (q4["composite_quality"] - q6["composite_quality"])
            t4, t6 = q4.get("tokens_s"), q6.get("tokens_s")
            speed = f"{t4}/{t6} tok/s" if t4 and t6 else "—"
            verdict = "q4 looks safe" if dq >= -0.02 else "q4 costs quality"
            out.append(f"- **{arch}**: quality q4−q6 = {dq:+.3f} ({verdict}); speed q4/q6 = {speed}")
        else:
            have = ", ".join(sorted(quants))
            out.append(f"- **{arch}**: only {have} run — serve the other quant to compare")
    return "\n".join(out) + "\n"


def _embeddings_section(emb: dict | None) -> str:
    if not emb:
        return "_No embedding results yet. Run `python -m evals.runners.run_embeddings`._\n"
    headers = ["Model", "dims", "R@5", "R@10", "MRR", "nDCG@10", "rel·F1",
               "dup", "notes/s", "rec·min", "rec·rel", "VRAM"]
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for ep in emb["endpoints"]:
        r = ep["retrieval"]
        op = ep["operational"]
        rec = ep["calibration"]["recommended_thresholds"]
        lines.append("| " + " | ".join(_fmt(v) for v in [
            ep["label"], op["dimensions"], r.get("recall@5"), r.get("recall@10"),
            r.get("mrr"), r.get("ndcg@10"), ep["related_links"]["f1"],
            ep["duplicates"]["detection_rate"], op["notes_per_second"],
            rec["min_similarity"], rec["related_min_similarity"], op.get("vram_gb"),
        ]) + " |")
    block = "\n".join(lines) + "\n"
    if emb.get("agreement"):
        block += "\n**Agreement vs 4B reference:**\n"
        for ag in emb["agreement"]:
            block += f"- {ag['model']}: Jaccard@5={ag['jaccard@k']}, Spearman={ag['mean_spearman']} over {ag['common_notes']} notes\n"
    return block


def _recommendation(rows: list[dict], emb: dict | None) -> str:
    out = ["\n## Recommendation\n"]
    if rows:
        best = max(rows, key=lambda r: r["composite_quality"])
        fastest = max((r for r in rows if r.get("tokens_s")), key=lambda r: r["tokens_s"], default=None)
        out.append(f"- Highest quality: **{best['label']}** (Q={best['composite_quality']}).")
        if fastest and fastest["key"] != best["key"]:
            gap = best["composite_quality"] - fastest["composite_quality"]
            out.append(f"- Fastest: **{fastest['label']}** ({fastest['tokens_s']} tok/s), "
                       f"Q gap {gap:+.3f} vs best — "
                       + ("acceptable; prefer it for throughput." if gap <= 0.03 else "meaningful; keep the smarter model for accuracy-critical passes."))
        ctxs = [r["max_ctx"] for r in rows if isinstance(r.get("max_ctx"), (int, float))]
        if ctxs:
            peak = max(ctxs)
            if peak <= 128000:
                verdict = (f"peak {peak} tokens stays under 128k — a **128k context window is "
                           f"sufficient**; the full 262k is not needed for these workloads.")
            elif peak <= 262411:
                verdict = (f"peak {peak} tokens exceeds 128k — keep a window above {peak}; "
                           f"128k would truncate.")
            else:
                verdict = f"peak {peak} tokens exceeds even 262k — inputs are being truncated upstream."
            out.append(f"- Context: {verdict} (Note: gold notes are short; re-check after adding "
                       f"any large notes to the gold set.)")
            windows = sorted({f"{r['label']}@{int(r['window'])}" for r in rows if r.get("window")})
            if windows:
                out.append(f"- Windows tested: {', '.join(windows)}.")
            overflow = [r for r in rows if r.get("window") and isinstance(r.get("max_ctx"), (int, float))
                        and r["max_ctx"] > 0.9 * r["window"]]
            for r in overflow:
                out.append(f"  - ⚠️ **{r['label']}** peaked at {r['max_ctx']} tokens, within 10% of its "
                           f"{int(r['window'])} window — its outputs may be truncated; results suspect.")
    if emb and len(emb["endpoints"]) >= 2 and emb.get("agreement"):
        small = emb["endpoints"][-1]
        ref = emb["endpoints"][0]
        d_recall = (small["retrieval"].get("recall@5") or 0) - (ref["retrieval"].get("recall@5") or 0)
        ag = emb["agreement"][-1]
        safe = d_recall >= -0.05 and ag["jaccard@k"] >= 0.6
        out.append(f"- Embeddings: **{small['label']}** Recall@5 Δ={d_recall:+.3f} vs {ref['label']}, "
                   f"Jaccard@5={ag['jaccard@k']}. "
                   + ("Within tolerance — the smaller model frees VRAM at low cost."
                      if safe else "Below tolerance — keep the 4B model for retrieval quality."))
    return "\n".join(out) + "\n"


def render(data: dict) -> str:
    rows = data["main"]
    emb = data["embeddings"]
    parts = [
        "# pi-vault model leaderboard\n",
        "Quality scores are accuracy/cosine/preservation on the frozen gold set; "
        "`Q` is the unweighted composite. Speed and VRAM are operational. "
        "All main-model numbers come from the same gold fixtures, so rows are comparable "
        "even though models were run at different times.\n",
        "## Main models\n",
        _main_table(rows),
        _quant_diff(rows),
        "## Embedding models\n",
        _embeddings_section(emb),
        _recommendation(rows, emb),
    ]
    return "\n".join(parts)


def main() -> int:
    data = build()
    dump_json(RESULTS_DIR / "leaderboard.json", data)
    md = render(data)
    (RESULTS_DIR / "leaderboard.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"wrote {RESULTS_DIR / 'leaderboard.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
