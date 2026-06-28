# pi-vault model eval suite

A token-lean benchmark for deciding **which served models are safe to run**. It
compares the main instruction models (Qwen3.6-27B vs 35B-A3B, q4 vs q6) and the
embedding models (Qwen3-Embedding-4B vs 0.6B, q4 vs q6) against frozen,
Claude-authored gold fixtures over the Memex test vault.

Claude is the capable reference: it authored the fixtures once. Every model run is
graded against them, so routine runs spend **zero judge tokens**. The constrained
stages (classification, folder/hub, people) and the embedding metrics are graded
fully automatically; summaries use cosine-to-reference and refinement uses exact
word-preservation. A finalists-only Claude rubric (`judge/`) is optional.

The suite **reuses the production code paths** in `vault_agent` — the real stage
prompts, validators, embedding client, and ranking/centering — so it measures what
ships. Notes are fed with their folder neutralised (basename under `01 Inbox/`) so
a model cannot read the answer off the directory.

## Layout

```
evals/
  configs/        main_models.yaml, embeddings.yaml   (endpoints, model keys, VRAM)
  fixtures/       gold_notes.json, retrieval_gold.json (the frozen gold set)
  graders/        constrained, summary, refine, people, retrieval  (pure, tested)
  runners/        run_main.py, run_embeddings.py
  judge/          claude_rubric.py   (optional, finalists-only)
  report.py       aggregate results/*.json -> leaderboard.md
  results/        per-run JSON + leaderboard (git-ignored)
```

## Running

Run everything from the `vault-manager/` directory.

### Embeddings (both models, one pass)

Both embedding endpoints are served at once:

```bash
python -m evals.runners.run_embeddings            # corpus target 150 by default
```

Writes `results/embeddings.json`. Reports Recall@k / MRR / nDCG, related-link
precision, duplicate detection, per-model **threshold recalibration**, and
cross-model agreement (Jaccard@5, Spearman) of the 0.6B model vs the 4B reference.
Add a quant variant by serving it and appending an entry to `embeddings.yaml`.

### Main models (one at a time, manual switch)

Only one large model fits in VRAM. Serve a model, run the matching key, switch,
repeat — order does not matter, results accumulate:

```bash
python -m evals.runners.run_main --model qwen3.6-27b-q6     # currently served
# switch the served model to 27B q4, then:
python -m evals.runners.run_main --model qwen3.6-27b-q4
# switch to 35B-A3B q6 ... then q4, running the matching key each time
```

Each writes `results/main_<key>.json` with per-stage accuracy/F1, summary cosine,
refine preservation, JSON-validity and first-pass rates, speed
(tokens/s, median/p90 per note-stage), and **context usage** — the per-request
prompt+completion high-water mark, so you can see whether the full 262k window is
needed or a 128k window would suffice. `--limit N` evaluates the first N notes for
a quick smoke; `--embed-url` (default `http://llms:8005`) supplies the embedder for
summary cosine.

Record each model's VRAM by hand (`nvidia-smi` while it is served) in
`main_models.yaml` / `embeddings.yaml`; it shows up in the leaderboard.

### Leaderboard

```bash
python -m evals.report
```

Aggregates whatever result files exist into `results/leaderboard.md` (and `.json`):
the main-model table with a composite quality score, a q4-vs-q6 diff per
architecture, the embedding table with recommended thresholds, and a plain-language
recommendation.

## Verifying the suite itself

```bash
python -m unittest tests.test_evals_graders     # offline grader unit tests
```

## Expanding the gold set

`fixtures/gold_notes.json` ships a stratified starter set covering every note type.
Add entries in the same shape (path + `labels` + optional `summary`/`refine`/
`person_kind`/`hub`) to grow toward ~45 notes for tighter confidence intervals;
add queries/related-pairs to `retrieval_gold.json` the same way. No code changes
needed — referenced paths are pulled into the embedding corpus automatically.

## Notes on thresholds

The engine ships embedding thresholds tuned on the 4B model. The 0.6B model has a
different cosine distribution, so the suite reports each model against the shipped
defaults **and** recomputes recommended `min_similarity` / `related_min_similarity`
from that model's own random-pair vs nearest-neighbor statistics. Judge the 0.6B
model on its recalibrated thresholds, not the 4B defaults.
