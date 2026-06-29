# pi-vault model leaderboard

Quality scores are accuracy/cosine/preservation on the frozen gold set; 
`Q` is the unweighted composite. Speed and VRAM are operational. 
All main-model numbers come from the same gold fixtures, so rows are comparable 
even though models were run at different times.

## Main models

| Model | type | status | domain | folder | person | sum·cos | refine | valid | json1 | tok/s | med·s | max·ctx | VRAM | Q |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3.6-35B-A3B q4 | 0.684 | 0.895 | 0.579 | 0.737 | 1 | 0.893 | 0.993 | 1 | 1 | 130.1 | 10.338 | 64435 | — | 0.848 |
| Qwen3.6-35B-A3B q6 | — | 0.842 | 0.684 | — | — | — | — | 1 | 1 | 52.1 | 37.443 | 64349 | — | 0.842 |
| Qwen3.6-35B-A3B q6 | 0.684 | 0.842 | 0.579 | 0.737 | 1 | 0.893 | 0.995 | 0.988 | 1 | 124 | 11.177 | 64824 | — | 0.84 |
| Qwen3.6-27B q6 | 0.632 | 0.737 | 0.737 | 0.632 | 1 | 0.902 | 0.993 | 1 | 1 | 53.6 | 28.371 | 64275 | — | 0.829 |
| Qwen3.6-27B q4 | 0.684 | 0.842 | 0.632 | 0.737 | 0.667 | 0.901 | 0.992 | 0.988 | 0.988 | 53.9 | 27.322 | 63469 | — | 0.805 |


### q4 vs q6 (same architecture)

- **27b**: quality q4−q6 = -0.024 (q4 costs quality); speed q4/q6 = 53.9/53.6 tok/s
- **35ba3b**: quality q4−q6 = +0.006 (q4 looks safe); speed q4/q6 = 130.1/52.1 tok/s

## Task models

_No task-model results yet. Run `python -m evals.runners.run_task --model <key>`._


## Embedding models

| Model | dims | R@5 | R@10 | MRR | nDCG@10 | rel·F1 | dup | notes/s | rec·min | rec·rel | VRAM |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3-Embedding-4B | 2560 | 0.857 | 0.929 | 0.75 | 0.773 | 0.462 | 1 | 4.81 | 0.32 | 0.55 | — |
| Qwen3-Embedding-0.6B | 1024 | 0.857 | 0.929 | 0.679 | 0.735 | 0.423 | 1 | 9.23 | 0.33 | 0.58 | — |

**Agreement vs 4B reference:**
- qwen3-embed-0.6b: Jaccard@5=0.6606, Spearman=0.9024 over 150 notes


## Recommendation

- Highest quality: **Qwen3.6-35B-A3B q4** (Q=0.8476).
- Context: peak 64824 tokens stays under 128k — a **128k context window is sufficient**; the full 262k is not needed for these workloads. (Note: gold notes are short; re-check after adding any large notes to the gold set.)
- Windows tested: Qwen3.6-35B-A3B q4@131072, Qwen3.6-35B-A3B q6@131072.
- Embeddings: **Qwen3-Embedding-0.6B** Recall@5 Δ=+0.000 vs Qwen3-Embedding-4B, Jaccard@5=0.6606. Within tolerance — the smaller model frees VRAM at low cost.
