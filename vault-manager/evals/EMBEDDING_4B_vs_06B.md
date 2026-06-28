# Embedding model choice: Qwen3-Embedding 4B vs 0.6B

Practical comparison for pi-vault, from the eval suite on the Memex vault
(150-note corpus, 14 search queries, 19 related-link pairs, 2026-06-28).
4B measured at **q4**; 0.6B at **q8**. Each evaluated at its own best related-link
threshold (see the threshold sweep in `run_embeddings --related-sweep`).

## The numbers

| | 4B (q4) | 0.6B (q8) | gap |
|---|---|---|---|
| Model VRAM (GGUF) | ~2.5 GB | ~0.6–0.7 GB* | **0.6B saves ~1.8 GB** |
| Indexing throughput | 5.4 notes/s | 9.0 notes/s | **0.6B ~1.7× faster** |
| Vector dims (index size) | 2560 | 1024 | 0.6B index ~2.5× smaller (MBs — negligible) |
| **Recall@5** (right note in top-5) | 0.857 | 0.857 | **tied** |
| MRR (rank of first hit) | 0.75 | 0.679 | 4B +0.07 |
| nDCG@10 (ranking quality) | 0.773 | 0.735 | 4B +0.04 |
| Related-links F1 (own best floor) | 0.46 @0.50 | 0.457 @0.55 | ~tied |
| Related-links precision @0.50 | 0.316 | 0.281 | 4B a bit cleaner |
| Duplicate detection | 1.0 | 1.0 | tied |
| Agreement vs 4B | — | Jaccard@5 0.66, Spearman 0.90 | ~⅓ of top-5 neighbours differ |

\* 0.6B GGUF size isn't exposed by its endpoint; ~0.6–0.7 GB is the expected q8
footprint. 4B-q4 reports 2.49 GB (q6 is 3.3 GB for **zero** quality gain — see below).

## What each is better at

**4B advantages**
- Sharper *ranking*: higher MRR/nDCG — it puts the single best match nearer the top.
- Cleaner auto-related-links: higher precision at the same recall (fewer spurious
  suggestions appended to notes).
- These matter most for "find THE answer / rank it first" and precision-sensitive
  automation.

**0.6B advantages**
- Frees ~1.8 GB VRAM — the original goal (room for other uses).
- ~1.7× faster indexing and search.
- **Ties 4B on Recall@5**: the relevant note lands in the top-5 just as often.
- Smaller index.

**0.6B disadvantages**
- The right note sits a bit lower in the list on average (the MRR/nDCG gap).
- Lower related-link precision → more noise to review.
- Its top-5 neighbour set overlaps 4B's only ~66%.

## Is 4B worth the VRAM?

For these workloads, **mostly no** — the 4B's extra ~1.8 GB buys a modest ranking
edge, not a recall edge. Decision by use case:

- **Semantic search** (you skim several top results): 0.6B is effectively
  equivalent (Recall@5 tied). The MRR gap costs at most ~1 scroll position.
  **0.6B is the better deal.**
- **Auto-proposed related links** (precision matters, links get written): 4B's
  higher precision is a real, if small, edge. Keep 4B here *if* you have the VRAM;
  otherwise 0.6B at floor ~0.55 is acceptable with light review.

If you keep 4B, use **q4, not q6** — q6 is identical on every metric at the locked
0.50 floor and costs +0.8 GB VRAM and ~11% throughput.

## Can configuration make them equivalent?

Largely, yes — two of the three gaps are closable without changing the model:

1. **Related-links precision/recall** → per-model threshold. The sweep shows 0.6B
   peaks at ~0.55 vs 4B at ~0.50; set each model's `related_min_similarity` to its
   own optimum and the related-links F1 gap nearly vanishes (0.457 vs 0.462).
2. **Search ranking (MRR/nDCG)** → the engine already applies a title/path
   **lexical boost** (`search._hybrid_rank`) that compensates for entity/project
   queries, and since 0.6B ties at Recall@5, a slightly larger `top_k` (e.g. 8
   instead of 5) surfaces the same notes. Together these neutralise most of the
   practical ranking gap for interactive search.
3. **Intrinsic ranking sharpness** — the residual MRR/nDCG difference is the model
   itself; no config removes it. It's small (~0.04–0.07) and only bites when you
   look at *one* result rather than a short list.

## Recommendation

Given the goal of freeing VRAM: **0.6B (q8) is worth adopting for search**, with
`related_min_similarity ≈ 0.55` and `top_k` bumped to ~8. Keep **4B (q4)** only if
auto-related-link precision turns out to matter in practice; never run 4B at q6.

Caveats: small eval set (150 corpus / 14 queries / 19 pairs); embedding-quality
gaps can widen at full-vault scale or on harder queries. Expand the gold set and
re-run before fully committing.

## Can config close the gap? (pass experiments, 2026-06-28)

Four saved passes (`results/embeddings_pass*.json`, indexed in
`results/PASSES_INDEX.md`) tested whether config — not a bigger model — lets 0.6B
match 4B on related-links precision and search MRR.

**0.6B KV cache q8 → f16:** Recall@5 0.857 → 0.893 (~half a query), MRR/nDCG/related
unchanged, throughput 9.0 → 8.4 n/s. Negligible quality for extra VRAM — **keep q8**.

**Lexical boost (search MRR lever):** helped 4B (MRR 0.750 → 0.774, nDCG 0.773 →
0.802) but slightly *hurt* 0.6B (MRR 0.679 → 0.667). It widens the gap rather than
closing it — the MRR difference is **model-intrinsic, not config-fixable**. It
barely matters in practice: 0.6B leads on Recall@5 (0.893 vs 0.857), so the right
note is in the top-5 as often; it just sits ~1 slot lower.

**Related-links precision (top_k 5→3, floor 0.50→0.55):** lifts both models —
4B P 0.316 → 0.417 (F1 0.462 → 0.526); 0.6B P 0.281 → 0.378 (F1 0.423 → 0.483).
**Tuned 0.6B beats *untuned* 4B** (F1 0.483 vs 0.462) and sits within ~0.04 of a
tuned 4B. So config **effectively closes the related-precision gap.**

**Conclusion:** related-links precision is matchable by config; search MRR is a
small intrinsic gap offset by 0.6B's equal/better top-5 recall. For a 0.6B
deployment: KV cache q8, related-links `top_k` 3 + `related_min_similarity` ~0.55.
