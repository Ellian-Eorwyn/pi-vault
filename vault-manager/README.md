# vault-manager (engine)

`vault-manager` is the deterministic Python **engine** that powers pi-vault. It provides the
`vault-agent` CLI for local-first Obsidian vault maintenance: it initializes vault-native
agent files, scans notes, validates sparse metadata, applies conservative template sections,
rebuilds retrieval indexes, and runs bounded processing passes with backups and logs.

**pi drives this engine.** The primary way to use it is to launch `pi-vault` at a vault
root: the agent loads the `vault-*` skills and the `vault_status` / `vault_manage` tools on
startup and calls the commands below on your behalf. The `vault-agent` CLI and the
`pi-vault vault <command>` wrapper documented here are the engine layer beneath those skills
and tools — useful for automation, scripting, and development. See the repo-root
`START_HERE.md` and `AGENT_CONTRACT.md` for the pi-first operating contract.

The system, inbox, dashboard, and content folders are selected in vault-local `.pi-vault/config.yaml`. New vaults default to `00 Inbox`, `01 Dashboards`, purpose-based content folders, and `99 System`. Dashboards are the primary navigation layer; folder placement is secondary. Approved proposals may create directories and move or rename notes with collision checks, wikilink updates, backups, and rollback; notes are never deleted automatically.

The engine itself stays runner-agnostic: every operating rule is discoverable in
`99 System/0.01 agent/`, so a scheduler, cron job, or another agent framework can drive it
too — but pi is the default front end.

## Install

From this repository:

```bash
python3 -m pip install -e .
```

The only runtime dependency is `PyYAML`.

You can also run without installing:

```bash
python3 -m vault_agent --help
```

## First Run On A Vault

Always start with a copied or versioned vault for broad processing.

```bash
vault-agent --vault-root /path/to/vault init --dry-run
vault-agent --vault-root /path/to/vault init --system-dir "99 System" --inbox-dir "00 Inbox"
vault-agent --vault-root /path/to/vault scan
vault-agent --vault-root /path/to/vault validate --dry-run
vault-agent --vault-root /path/to/vault norms-lock --dry-run
vault-agent --vault-root /path/to/vault organization-readiness --json
vault-agent --vault-root /path/to/vault reconcile --dry-run
```

When the dry-run output is acceptable, run bounded write passes:

```bash
vault-agent --vault-root /path/to/vault version init
vault-agent --vault-root /path/to/vault version status
vault-agent --vault-root /path/to/vault norms-lock --write
vault-agent --vault-root /path/to/vault organization-readiness --json
vault-agent --vault-root /path/to/vault propose-cleanup-queue --max-items 10
vault-agent --vault-root /path/to/vault propose-inbox-sort --max-notes 5 --safe-only
vault-agent --vault-root /path/to/vault propose-vault-layout --dry-run
vault-agent --vault-root /path/to/vault review-proposals --dry-run
vault-agent --vault-root /path/to/vault autonomous-run --create-lock --apply-safe --stage classify-type --max-notes 2 --use-llm
vault-agent --vault-root /path/to/vault review-model-blocks --dry-run
vault-agent --vault-root /path/to/vault obsidian-check --json
vault-agent --vault-root /path/to/vault validate --dry-run
vault-agent --vault-root /path/to/vault rebuild-retrieval
```

For model-backed test batches, pass one explicit semantic stage such as `--stage classify-type` or `--stage property-values`. `organize-vault-pass` walks the selected queue in order and calls the configured model for one note stage at a time; it does not issue parallel LLM requests. Reports include queue positions and whether LLM prompts were serialized.

## Commands

- `init`: writes `.pi-vault/config.yaml` and creates the selected system/inbox folders, agent state, review queues, retrieval files, and templates without overwriting existing files.
- `scan`: writes a deterministic manifest and catalog.
- `validate`: reports malformed frontmatter, unknown values, mappable legacy metadata, template/schema consistency, and stale generated state; use `--json` for agent-readable groups.
- `reconcile`: applies missing sparse properties and missing template sections without moving notes.
- `norms-lock`: creates a generated snapshot of current schema, templates, allowed values, and legacy alias rules.
- `organization-readiness`: reports lock status, candidate stages, validation groups, cleanup opportunities, stale tracked notes, blocked stages, and the latest organization report.
- `organize-vault-pass`: runs a bounded lock-aware organization pass and writes Markdown/JSON reports with queue positions and serialized-LLM evidence.
- `autonomous-run`: runs bounded safe scheduled maintenance for one vault, writes Markdown/JSON audit reports, and includes version rollback hints.
- `action-plan`: reports proposal-first maintenance queues and machine-readable action options.
- `propose-index`: generates a pending proposal for a type/domain/project/parent index note.
- `propose-property`: generates a pending proposal for a new controlled property value.
- `propose-template`: generates a pending proposal to refresh a note-type template.
- `propose-cleanup`: generates a pending proposal to clean up one note's frontmatter.
- `propose-cleanup-queue`: generates a bounded pending cleanup proposal from validation groups.
- `propose-action-queue`: generates pending proposals for transcript cleanup, people notes, and categorization queues; use `--use-llm --llm-limit 1 --max-items 1` for serialized model-backed categorization.
- `propose-folder-organization`: generates a pending proposal to organize one folder and create/update a dashboard.
- `propose-base-hierarchy`: generates a pending proposal for domain and parent/project dashboards with embedded Bases.
- `propose-inbox-sort`: generates bounded deterministic move proposals for processed inbox notes; `--safe-only` requires current, warning-free, high-confidence processing evidence.
- `propose-vault-layout`: generates a pending migration proposal for the dashboard-first folders and navigation shells without moving existing notes automatically.
- `review-proposals`: validates proposal JSON files, can render `--agent-review`, can mark bounded safe proposals with `--approve-safe`, and applies proposals marked `approved`.
- `review-model-blocks`: renders warning-bearing or near-threshold model stage outputs and can convert selected safe items into normal pending review proposals.
- `process-next`: processes one eligible inbox note stage.
- `process-inbox`: processes a bounded inbox batch.
- `process-vault`: processes a bounded non-system, non-inbox vault batch.
- `rebuild-retrieval`: regenerates vault map, catalog, property index, and summary brief; also refreshes the embedding index when `embeddings.enabled` is set.
- `embed-index`: builds or incrementally refreshes the rebuildable embedding index over vault notes (requires `embeddings.enabled` and an `embedding_base_url`).
- `propose-related-links`: generates an append-only pending proposal that adds embedding-discovered `related` wikilinks to a bounded batch of notes; applied only through `review-proposals`.
- `vault-search`: read-only semantic search over the embedding index, returning ranked path, title, score, and snippet (`--json` for machine-readable output).
- `status`: reports agent health, queue status, lock state, stale/blocked tracked notes, latest organization report, and whether the vault is ready for an organization pass.
- `hermes-run`: runs bounded maintenance across vault directories in a Hermes root.
- `schema-conversation`: turns an explicit schema/onboarding transcript into pending schema/index/template proposals and a review summary.
- `obsidian-check`: statically validates frontmatter YAML/order, embedded Base blocks, and dashboard links; optionally runs live Obsidian CLI checks.
- `version`: initializes local Git safety, lists agent runs, shows diffs, lists changed files, restores one path, and undoes affected paths from a run.

People action proposals distinguish direct contacts from referenced people in note bodies and `People/INDEX.md`. `Key thinkers` and author-like lists become referenced people; meeting, call, speaker, and direct interaction contexts become direct contacts with contact-detail scaffolding. These distinctions stay out of ordinary note frontmatter.

## Agent Framework Contract

New vaults include:

- `99 System/0.01 agent/AGENT_HANDOFF.md`
- `99 System/0.01 agent/AGENT_CONTRACT.md`

Any agent framework should start by reading those files, then `status`, then generated retrieval files. The contract defines how to route common user requests:

- organize a vault with readiness checks, dry-run maintenance, cleanup proposals, and bounded write passes
- lock current vault norms before broad processing and report what each organization pass did
- change canonical properties by updating schema, templates, validators, and docs together
- build index notes using sparse properties, Bases, links, and retrieval files
- run scheduled maintenance through bounded `autonomous-run` or `hermes-run`

For changes that need review, agents write JSON files under:

```text
99 System/0.01 agent/review/proposals/
```

Then validate:

```bash
vault-agent --vault-root /path/to/vault review-proposals --dry-run
```

After a human or supervising agent changes `status` to `approved`, apply deterministically:

```bash
vault-agent --vault-root /path/to/vault review-proposals --apply-approved
```

Supported proposal kinds are `schema-change`, `index-note`, `template-change`, `cleanup`, `folder-organization`, `base-hierarchy`, and `action-queue`. Supported operations include `write_file`, `update_frontmatter`, and `organize_note`.

For common cases, agents do not need to hand-author JSON:

```bash
vault-agent --vault-root /path/to/vault propose-index --index-type type --value project
vault-agent --vault-root /path/to/vault propose-index --index-type domain --value work
vault-agent --vault-root /path/to/vault propose-property --property domain --value legal --description "Legal, compliance, and contracts."
vault-agent --vault-root /path/to/vault propose-template --note-type source
vault-agent --vault-root /path/to/vault propose-cleanup --note "03 Notes/Legacy.md" --remove-unknown
vault-agent --vault-root /path/to/vault propose-cleanup-queue --max-items 10
vault-agent --vault-root /path/to/vault propose-folder-organization --folder "05 Projects/Example" --project "Example" --domain work --use-llm --checkpoint
vault-agent --vault-root /path/to/vault propose-base-hierarchy
```

The repo root keeps the pi-first operating contract in `AGENT_CONTRACT.md`.

## Metadata Schema

Managed YAML stays sparse:

```yaml
---
type:
status:
domain:
parent:
related: []
cover:
source_kind:
capture_type:
---
```

Allowed `type` values are `project`, `source`, `person`, `organization`, `meeting`, `task`, `note`, `index`, `daily`, `template`, and `system`.

Specific topics should be ordinary notes and links, not new frontmatter fields.

## Safety Model

- Dry-run exists for risky operations.
- Git-backed versioning is enabled by default as a local safety, audit, rollback, and change-management layer. It does not replace external sync and does not push by default.
- Mutating `vault-agent` commands automatically create pre/post snapshots, record change-set JSONL, and expose rollback hints under `99 System/0.01 agent/versioning/`.
- Mass edits over configured thresholds require an explicit `--mass-edit` flag.
- Writes use backups under `99 System/0.01 agent/backups/`.
- Command logs live under `99 System/0.01 agent/logs/`.
- Malformed YAML blocks edits to that note.
- Unknown legacy metadata is preserved by default.
- LLMs return structured JSON proposals only; deterministic code validates and applies approved fields.
- Invalid LLM JSON is retried once through a repair prompt; persistent failures are recorded with structured attempt details.
- Warning-bearing or near-threshold model proposals are review-gated by default.
- Valid model proposals blocked by warning/threshold gates are persisted under `99 System/0.01 agent/review/model-blocked-proposals.*`; use `review-model-blocks --dry-run` before converting them into normal proposal JSON.
- Broad organization passes record the active `norms-lock.json` hash in `processing-state.json` and write reports under `99 System/0.01 agent/reports/`.

## LLM Setup

LLM processing is disabled by default in `99 System/0.01 agent/config.yaml`.

For an OpenAI-compatible local backend:

```yaml
llm:
  enabled: true
  provider: openai-compatible
  base_url: http://llms:8008
  model: code
  confidence_threshold: 0.75
  max_input_tokens: 64000
  chars_per_token: 4
```

Without an enabled provider, deterministic stages such as `frontmatter-shape`, `template-body`, scan, validate, reconcile, and retrieval rebuild still work. Type classification, property-value filling, and summary writing require a provider or a `--proposal-file`.

## Embeddings

Embedding-backed retrieval is optional and disabled by default. It uses an OpenAI-compatible `/v1/embeddings` endpoint for whole-vault similarity tasks (related-note discovery and semantic search). The index is a rebuildable JSON cache keyed by note path and invalidated by the scanner content hash; it is git-ignored. There is no new runtime dependency: requests use `urllib` and similarity is pure-Python cosine.

```yaml
llm:
  embedding_base_url: http://llms:8005
  embedding_model: embed
embeddings:
  enabled: true
  top_k: 5
  min_similarity: 0.55
  related_min_similarity: 0.65
  duplicate_min_similarity: 0.97
  batch_size: 32
  excerpt_chars: 6000
```

With embeddings enabled, build the index with `embed-index` (or rely on `rebuild-retrieval`), then use `propose-related-links` for append-only related-link proposals and `vault-search "<query>"` for read-only semantic search. See `docs/architecture/embeddings-roadmap.md` for the phased plan (near-duplicate detection, routing pre-ranking, content clustering).

The embedding server must allow each input's full token count in one physical batch. For an OpenAI-compatible llama.cpp server, set the batch sizes to at least the largest excerpt you embed (e.g. `-ub 2048 -b 2048`); the client truncates any input the server still rejects, so it degrades gracefully on smaller limits. `embeddings.batch_size` controls how many notes are sent per HTTP request; keep it modest on shared GPU hosts.

Similarity is computed in a **mean-centered** space: Qwen3-Embedding has a high raw baseline cosine, so the engine subtracts the corpus mean embedding before ranking. On a ~1100-note Memex vault with Qwen3-Embedding-4B, random centered pairs had median similarity near zero while nearest neighbors had median similarity around 0.70. In that centered space `min_similarity: 0.55` is a search floor, `related_min_similarity: 0.65` is the default for reviewable related-link proposals, and `duplicate_min_similarity: 0.97` is reserved for near-duplicate candidates. Centering needs a minimum corpus size (about 25 notes); smaller vaults fall back to raw cosine automatically.

When testing local LLM-backed features, monitor `http://llms:8077/`: open Logs, select `Backend MoE`, click `Stream`, and confirm one `slot id 0` task completes with `release` and `all slots are idle` before the next request starts. Keep prompts serialized and stage-specific. `organize-vault-pass --use-llm --max-notes N --stage <semantic-stage>` automatically prompts the next queued note after the previous note stage returns and is validated. `max_input_tokens` is enforced through an estimated character budget of `max_input_tokens * chars_per_token`; set `max_input_chars` only for an explicit legacy override. Vault-agent does not set a generation-token cap; leave generation limits to the configured backend. If the model returns non-JSON or thinking text, record the failure, fall back deterministically only where safe, and improve parser/prompt tests before widening the batch.

For scheduler-shaped LLM tests, prefer:

```bash
vault-agent --vault-root /path/to/vault autonomous-run --create-lock --apply-safe --use-llm --stage classify-type --max-notes 2
```

Review the generated autonomous report, `version diff <run-id>`, and `obsidian-check --json` output before widening the batch.
If the run reports blocked model proposals, inspect them with `review-model-blocks --dry-run`; convert safe items with `review-model-blocks --approve-safe`, then apply only through the normal `review-proposals` path.

## Recovery

To inspect or roll back a versioned agent run:

```bash
vault-agent --vault-root /path/to/vault version log
vault-agent --vault-root /path/to/vault version show <run-id>
vault-agent --vault-root /path/to/vault version diff <run-id>
vault-agent --vault-root /path/to/vault version changed-files <run-id>
vault-agent --vault-root /path/to/vault version restore <run-id> --path "Notes/Example.md"
vault-agent --vault-root /path/to/vault version undo-run <run-id>
```

`undo-run` restores only paths touched by that run from the pre-run commit. Full affected-path restore uses `version restore <run-id> --all --force`.

Backups are still kept for file-level inspection. To recover from an unwanted write manually, inspect the matching backup in:

```text
99 System/0.01 agent/backups/
```

Use the daily log in:

```text
99 System/0.01 agent/logs/
```

to identify which command made the change.

## Current Limitations

- The CLI does not install an OS scheduler or filesystem watcher.
- Moves and renames require validated `move_note` proposals; automatic destination selection and duplicate resolution remain review-dependent.
- Schema onboarding is transcript-file driven and proposal-only; ambiguous user preferences still need to be clarified before generation.
- Full autonomous processing should stay bounded and reviewed until the vault-specific legacy mappings are tuned.
- Full-vault organization still needs report-driven Memex pilots before unattended broad use; serialized stage-scoped batches are the next test shape.
- SQLite and the deeper memory layer remain optional/deferred; JSON and Markdown are canonical.
