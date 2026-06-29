# Embedding pass index (2026-06-28)

All passes: 150-note corpus, 19 related-pairs, 14 queries. 4B served at q4/q6
(metric-identical); 0.6B KV-cache type noted per file.

| file | 4B | 0.6B KV | lexical boost | related top_k | related floor |
|---|---|---|---|---|---|
| embeddings_pass0_06b-q8kv.json | q4 | q8 | off | 5 | 0.50 |
| embeddings_pass1_baseline.json | q6 | f16 | off | 5 | 0.50 |
| embeddings_pass2_lexboost.json | q6 | f16 | on | 5 | 0.50 |
| embeddings_pass3_precision.json | q6 | f16 | on | 3 | 0.55 |

(embeddings_4b-q4_baseline.json == pass0; kept for backward reference.)

Findings: f16 KV ~ no gain over q8 (revert to q8 for VRAM). Lexical boost helps 4B
MRR, slightly hurts 0.6B (MRR gap is model-intrinsic). related top_k=3 + floor 0.55
makes tuned 0.6B beat untuned 4B on related-links; residual gap to tuned 4B ~0.04.
