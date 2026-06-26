# Changelog

## 2026-06-26

- Retuned embedding retrieval for the Qwen3-Embedding-4B local backend: index caches now store backend model metadata so alias-preserving model upgrades force re-embedding, `embeddings.batch_size` is configurable, related-link and duplicate thresholds are split from the search floor, and `vault-search` uses a bounded title/path lexical boost on top of centered cosine.
- Added a shared embedding foundation (`embeddings.py`, `embedding_index.py`) using the OpenAI-compatible `/v1/embeddings` endpoint (default `http://llms:8005`, model `embed`), with no new runtime dependency: requests use `urllib` and similarity is pure-Python cosine. The index is a rebuildable JSON cache keyed by note path and invalidated by the scanner content hash, written under `retrieval/embedding/index.json` and git-ignored.
- Added an `embeddings:` config block (`enabled` default false, `top_k`, `min_similarity`, `excerpt_chars`); deterministic runs are unaffected when disabled.
- Added `embed-index` to build/refresh the index; `rebuild-retrieval` also refreshes it when embeddings are enabled.
- Added `propose-related-links`: embedding nearest-neighbor discovery that emits an append-only `related-links` proposal of `update_frontmatter` operations, applied only through `review-proposals` (never removes existing links).
- Added `vault-search`: read-only semantic search over the embedding index returning ranked path, title, score, and snippet, with `--json`.
- Computed similarity in a mean-centered space (corpus mean stored in the index and subtracted before ranking) to counter Qwen3's high baseline cosine; on the Memex test vault this roughly doubled neighbor-vs-random separation and demoted spurious cross-topic matches. Centering falls back to raw cosine below ~25 notes. Calibrated defaults to `min_similarity: 0.55` (centered) and `excerpt_chars: 6000`.
- Made the embedding client resilient to per-input token caps: it splits oversized batches to isolate the offending input and truncates it by the server-reported token ratio before retrying, instead of failing a whole-vault embed.
- Documented the embeddings approach and phased roadmap in `docs/architecture/embeddings-roadmap.md` and `DECISIONS.md`.
- Added unit tests for the embedding client (mocked transport), cosine/ranking, incremental index rebuild, the related-links proposal shape, and search ranking.

## 2026-06-25

- Added editable Markdown vault defaults at `0.024 vault defaults.md`, covering sparse core properties, controlled values, folder structure, dashboard structure, dashboard regeneration rules, agent rules, and schema-change policy.
- Added `vault-agent export-schema-defaults --output <path>` and `vault-agent import-schema-defaults --schema-file <path>` so onboarding can round-trip defaults through a human-edited Markdown contract and generate pending review proposals only.
- Updated domain validation to honor additional domain values from vault-local `schema.json`, keeping imported domain additions consistent after approved schema proposals are applied.
- Added regressions for default export content, untouched round-trip import, edited domain/folder proposals, malformed import failure with no proposal, applied domain validation, and the init/export/import/review/Obsidian-check smoke flow.
- Verified with `python3 -m unittest discover -s tests` running 208 tests and `npm run check`.

## 2026-06-24

- Replaced the new-vault defaults with `00 Inbox`, `01 Dashboards`, purpose-based content folders, and `99 System`; bootstrap/status output now includes validated dashboard and content paths.
- Added preserved-curation dashboard shells, dashboard-root hierarchy generation, deterministic destination routing, `inbox-sort` and `vault-layout` proposal kinds, `propose-inbox-sort`, and `propose-vault-layout`.
- Added safe unattended inbox routing gates requiring a current norms lock and completed warning-free high-confidence classification/property stages; ambiguous and colliding routes remain pending.
- Added dashboard-first routing/migration regressions and clean external-vault smoke verification with 0 validation issues and `obsidian-check --json` at 0 errors and 0 warnings.
- Added dashboard-first starter conventions and vault-local agent instructions with an adaptable nested Home/Domain/Project/People/Source/Maintenance topology, curated Markdown plus embedded Bases, multi-dashboard note membership, and curated-section preservation.
- Expanded read-only status output with provisional/locked/drifted schema state, previous scan time, new and changed inbox files, grouped validation issues, generated-state details, pending proposals, blocked/stale processing, and the latest organization report.
- Clarified initialized-vault guidance so bundled schema/templates remain provisional until approved and captured by `norms-lock.json`.
- Added status regressions for lock lifecycle, manifest deltas, pending proposals, and missing or corrupt prior state.

## 2026-06-20

- Integrated vault-manager as the deterministic sidecar for the new pi-vault application and removed its nested repository boundary.
- Added vault-local `.pi-vault/config.yaml` bootstrap selection for arbitrary system and inbox folders; parameterized scanning, processing, proposals, reports, retrieval, norms, validation, and versioning paths.
- Added durable vault-purpose and vault-conventions starter files, machine-readable status output, and exact PyYAML dependency pinning.
- Added validated `create_directory` and `move_note` proposal operations with transaction preflight, protected-path and collision checks, ambiguous basename-link rejection, inbound wikilink rewrites, backups, and Git-backed rollback.
- Added custom-path and move/rename regression coverage; verified with `python3 -m unittest discover -s tests` running 157 tests.

## 2026-06-18

- Proved the model-block review loop in `test_vaults/Memex` with a fresh tiny `autonomous-run --create-lock --use-llm --stage classify-type --max-notes 2`; the run produced 2 blocked model proposals, completed retrieval/validation, and exited review-required with rollback run id `95cbdb5a594a4118a2ebcd94b614b7dc`.
- Tightened `review-model-blocks --approve-safe` so below-threshold model blocks are reported as skipped and remain pending instead of being promoted into normal proposal JSON.
- Converted only the safe Memex block into pending proposal `model-block-01-inbox-new-images-md-classify-type.json`; left the low-confidence `01 Inbox/Untitled 1 copy.md` block pending for human review; `review-proposals --dry-run` validated the queue with 0 invalid proposals and no note mutation.
- Verified static Obsidian QA stayed at 0 errors and 22 warnings.
- Verified with `python3 -m unittest discover -s tests` running 153 tests.

- Added `vault-agent review-model-blocks` plus `model-blocked-proposals.json` / `.md` review artifacts so warning-bearing or near-threshold staged LLM output can be inspected and converted into normal pending review proposals without mutating notes directly.
- Updated `organize-vault-pass` and `autonomous-run` reports to surface blocked model proposal counts, review artifact paths, and top block reasons; autonomous runs now distinguish review-required model blocks from generic command failure.
- Added tests proving blocked model proposals do not mutate notes, dry-run review writes nothing, safe conversion creates pending proposal JSON, and `review-proposals --dry-run` validates the converted proposal.
- Verified with `python3 -m unittest discover -s tests` running 152 tests.

- Added `vault-agent autonomous-run` for bounded safe scheduled maintenance with readiness preflight, norms-lock handling, cleanup proposal generation, safe non-schema proposal approval/application, bounded organization passes, retrieval rebuilds, Markdown/JSON reports, and rollback hints.
- Updated `vault-agent hermes-run` so each discovered vault uses the same autonomous maintenance routine and report contract.
- Added `vault-agent schema-conversation --conversation-file` for transcript-file schema onboarding/revision that writes pending schema/index/template proposals plus a review summary, without direct schema mutation.
- Added `vault-agent obsidian-check` for static frontmatter YAML/order validation, embedded Base YAML/view/filter validation, dashboard wikilink warnings, and optional live Obsidian CLI checks.
- Fixed vault Git detection so nested copied/test vaults do not use the parent project repository as their versioning root.
- Smoke-tested `test_vaults/Memex`: `autonomous-run --dry-run --max-notes 2 --create-lock --apply-safe` made no writes; `obsidian-check --json` reported 0 errors and 22 existing wikilink warnings; live `autonomous-run --create-lock --use-llm --stage classify-type --max-notes 2` reached the local model, processed 2 stages, changed 1 note, and blocked 1 warning-bearing near-threshold proposal.
- Verified with `python3 -m unittest discover -s tests` running 150 tests.

- Added Git-backed versioning as a first-class local safety layer with `vault-agent version init/status/log/show/diff/changed-files/restore/undo-run`.
- Added reusable versioning and execution services for Git initialization, managed `.gitignore` blocks, pre/post snapshots, change-set JSONL, run artifacts, rollback hints, dirty-state policy, and mass-edit gating.
- Wrapped mutating vault commands in the versioned execution path while keeping dry-run/read-only commands snapshot-free; `hermes-run` now versions each scheduled vault pass at the vault level.
- Added conservative `versioning:` config defaults, starter vault docs, README guidance, and agent contract recovery commands.
- Added tests for Git init, separate Git dirs, managed ignores, wrapper snapshots, no-op/failure metadata, dirty policy refusal, mass-edit flags, changed-file inspection, path restore, and undo-run behavior.
- Verified with `python3 -m unittest discover -s tests` running 143 tests.

- Added `vault-agent propose-base-hierarchy` to generate a pending `base-hierarchy` proposal for domain and parent/project dashboard notes with embedded Bases.
- Added deterministic hierarchy planning that excludes system/templates/malformed notes, groups populated domains, surfaces blank or invalid domains as "Needs metadata", and keeps coverage prose in Markdown dashboard bodies.
- Added optional LLM coverage wording support through the configured provider, with invalid or unavailable model output falling back to deterministic summaries.
- Updated proposal review validation, README, agent contract docs, and initialized-vault starter guidance for the new proposal kind and command.
- Smoke-tested `test_vaults/Memex`: dry-run reported 3 domains, 14 parent/project dashboards, and 958 notes needing metadata; generated `base-hierarchy.json` only; `review-proposals --dry-run` validated it with 0 invalid proposals.
- Verified with `python3 -m unittest discover -s tests` running 135 tests.

## 2026-06-17

- Made LLM-backed `organize-vault-pass` batches explicitly serialized and auditable: dry-run and completion output now state `LLM prompts: serialized one note stage at a time`.
- Organization report JSON now includes `llm_prompts_serialized`, and each processed item records its `queue_position`; Markdown reports render the same queue order.
- Added regression coverage proving a two-note `property-values` batch calls the proposal provider in queue order without overlapping model calls.
- Updated README, agent contract starter guidance, and project-control docs to use stage-scoped serialized batches such as `organize-vault-pass --stage classify-type --max-notes 5 --use-llm`.
- Verified the next Memex dry-run shape with `organize-vault-pass --dry-run --stage classify-type --max-notes 3 --use-llm`, which selected three classification candidates and reported serialized LLM prompting.
- Verified with `python3 -m unittest discover -s tests` running 130 tests.

- Ran the first safe bounded Memex organization pilot in `test_vaults/Memex`.
- Wrote a current Memex norms lock at `00 System/0.01 agent/norms-lock.json` with lock hash `32d9e490686c9b55aa07a7c954d7223a79ef6d90035b61e3970bbdca6fede34a`.
- Refreshed proposal review output using `review-proposals` after confirming `review-proposals --dry-run` validates but does not rewrite stale review output.
- Generated `cleanup-queue-vault.json` with `propose-cleanup-queue --max-items 5 --overwrite-proposal`; verified it had 5 bounded `update_frontmatter` operations, set only schema-approved fields, and used `"remove": []` so unknown legacy fields were preserved.
- Approved and applied only the new cleanup queue proposal with `review-proposals --apply-approved`; validation changed from 8237 issues after lock creation to 8232 issues, with 0 errors.
- Ran a targeted LLM-backed organization pass: `organize-vault-pass --note "01 Inbox/Important Concepts.md" --stage property-values --max-notes 1 --use-llm`; it processed 1 stage, changed 1 note, blocked 0 stages, and wrote `00 System/0.01 agent/reports/organization-run-20260617-224737.md` plus JSON.
- Verified `processing-state.json` records the active `norms_lock_hash` for `01 Inbox/Important Concepts.md`, rebuilt retrieval for 1040 notes, confirmed readiness remains `review`, and verified with `python3 -m unittest discover -s tests` running 129 tests.

- Added `vault-agent organization-readiness` with human and JSON output for lock status, candidate stages, validation groups, cleanup opportunities, generated-state staleness, stale/blocked tracked notes, and latest organization reports.
- Added `validate --json` plus template/schema consistency and generated-state staleness checks for norms locks, retrieval files, proposal review output, missing templates, and invalid template frontmatter.
- Enhanced `reconcile --dry-run` with a lock-aware generated-state preflight while preserving existing reconcile write behavior.
- Hardened OpenAI-compatible JSON handling with shared balanced-object extraction, one repair prompt, and structured final failure records for full-note and stage-specific model calls.
- Updated `status`, README, agent contract, initialized-vault starter guidance, and project-control files with the readiness-first organization workflow.
- Verified with `python3 -m unittest discover -s tests` running 129 tests.

- Added `vault-agent norms-lock` to generate a vault-local `norms-lock.json` snapshot of schema, templates, controlled values, legacy aliases, review settings, and a stable lock hash.
- Added lock-aware processing ledger behavior so completed stages can be treated as stale when note content or the current norms lock changes.
- Added `vault-agent organize-vault-pass` for bounded lock-aware organization passes with Markdown and JSON reports under `00 System/0.01 agent/reports/`.
- Added `vault-agent propose-cleanup-queue` to generate bounded cleanup proposals from validation groups while preserving the `review-proposals` mutation boundary.
- Updated `status`, README, agent contract, and initialized-vault starter guidance to surface norms locks, stale/blocked tracked notes, and organization reports.
- Verified with `python3 -m unittest discover -s tests` running 126 tests.

## 2026-06-12

- Added `vault-agent propose-folder-organization` for folder-scoped organization proposals with sparse metadata cleanup, optional local LLM classification, checkpoint/resume, optional legacy-property removal, and dashboard generation.
- Added `folder-organization` proposal review/application support with `organize_note` operations, backups, logs, malformed-frontmatter repair, template section insertion, and dashboard `write_file` operations.
- Updated HoMEDUCS dashboard generation so embedded Bases include folder-path fallback filters as well as `parent` filters.
- Hardened YAML/frontmatter and LLM handling by quoting special scalar values, accepting `complete -> completed`, using a configured `max_input_tokens` budget for folder-organization prompts, adding `max_tokens`, and parsing the first balanced JSON object from local-model responses.
- Ran the HoMEDUCS pilot in `test_vaults/Memex/05 Projects/EEI/3.01 HoMEDUCS`: 60 notes received sparse core metadata, legacy frontmatter was stripped, `Vinod Narayanan.md` became `type: person`, and `HoMEDUCS-Dashboard.md` was rebuilt.
- Monitored the local LLM at `http://llms:8077/` with Logs > Backend MoE > Stream and confirmed serialized single-slot processing.
- Updated repo handoff docs and initialized-vault starter guidance with the folder-pilot and local LLM monitoring workflow.
- Verified with `python3 -m unittest discover -s tests` running 103 tests.

## 2026-06-11

- Added `vault-agent propose-template` to generate pending `template-change` proposals for note-type template refreshes.
- Added `vault-agent propose-cleanup` to generate pending one-note `cleanup` proposals for sparse frontmatter repair, legacy alias copying, and optional unknown-property removal.
- Updated `propose-property` to use the current vault schema/property-values files when present, preserving existing human edits in property docs while appending proposed additions.
- Updated `review-proposals` so the persisted `proposed-changes.md` reflects final `applied` statuses after approved proposals are applied.
- Piloted the proposal workflow in the copied Memex vault by applying a `legal` domain proposal, Work domain index, person template refresh, and conservative cleanup for `06 People/Irina Krishpinovich.md`.
- Verified with `python3 -m unittest discover -s tests` running 90 tests.

## 2026-06-11

- Added `vault-agent propose-index` to generate pending `index-note` proposals for type, domain, project, and parent dashboards without hand-written JSON.
- Added `vault-agent propose-property` to generate pending `schema-change` proposals for new controlled property values.
- Proposal generators write into `00 System/0.01 agent/review/proposals/` and validate through `review-proposals --dry-run`.
- Verified with `python3 -m unittest discover -s tests` running 86 tests.

## 2026-06-11

- Added `vault-agent review-proposals` for deterministic proposal validation/rendering and approved proposal application.
- Added vault-local proposal directories under `00 System/0.01 agent/review/proposals/` plus `proposed-changes.md` review output.
- Added proposal operations for safe `write_file` and sparse `update_frontmatter` changes with validation, backups, logs, and applied-state marking.
- Documented the proposal workflow in `README.md`, repo-level `AGENT_CONTRACT.md`, and initialized vault-local `AGENT_CONTRACT.md`.
- Verified with `python3 -m unittest discover -s tests` running 82 tests.

## 2026-06-11

- Added a framework-agnostic `AGENT_CONTRACT.md` for Codex/OpenCode/Hermes/cron-style runners, and included matching `00 System/0.01 agent/AGENT_CONTRACT.md` starter content in initialized vaults.
- Ran a temporary copied-vault Hermes pilot covering dry-run, interrupted write recovery, legacy YAML dates, deterministic no-LLM scheduled maintenance, section-level template application, and retrieval rebuild.
- Fixed scanner manifest rendering for PyYAML date values such as `created: 2026-01-01` by normalizing frontmatter into JSON-safe values.
- Updated `hermes-run` so no-LLM scheduled maintenance only runs deterministic processing stages and subcommand failures contribute to the overall exit code.
- Verified with `python3 -m unittest discover -s tests` running 77 tests.

## 2026-06-11

- Updated `hermes-run` to run and report separate bounded `process-inbox` and `process-vault` passes, keeping `00 System` and `01 Inbox` out of ordinary whole-vault processing.
- Expanded template application so missing `##` sections are appended as full rich template blocks with tables, callouts, checklists, and placeholders instead of heading-only stubs.
- Tuned legacy metadata mappings for `area`/`areas`/`domains`, `source`/`source_type`/`publication_type`, and `tags`/`topic`/`topics`, while preserving original legacy fields by default.
- Added `README.md` and starter `00 System/0.01 agent/AGENT_HANDOFF.md` handoff documentation.
- Verified with `python3 -m unittest discover -s tests` running 75 tests.

## 2026-06-11

- Updated the canonical sparse metadata schema to `type`, `status`, `domain`, `parent`, `related`, `cover`, `source_kind`, and `capture_type`.
- Added controlled `capture_type` values: voice, meeting, chat, imported, and manual.
- Reordered generated frontmatter, schema docs, templates, proposal validation, scanner output, and reconcile defaults to match the canonical property order.
- Refreshed the ignored Memex test vault's generated schema and template files, and added `capture_type` to the two active pilot inbox notes.
- Verified with `python3 -m unittest discover -s tests` running 70 tests.

## 2026-06-11

- Added exact-note targeting with `--note` for process commands so pilots can address a specific Markdown file instead of relying on queue order.
- Added missing-core/stale stage detection so completed ledger stages do not hide currently missing required sparse keys.
- Added config-driven legacy metadata aliases for type/status/source_kind/property mappings, default preservation of unknown properties, and opt-in unknown-property removal.
- Added grouped validation dry-run summaries and distinct info-level reporting for legacy values that can be mapped.
- Added review gating for warning-bearing or near-threshold model proposals.
- Ran the targeted Memex `property-values` write test on `01 Inbox/Important Concepts.md`; it filled the missing `source_kind`, created a backup, logged the command, and updated the processing ledger.
- Verified with `python3 -m unittest discover -s tests` running 70 tests.

## 2026-06-11

- Added optional `source_kind` to the sparse default metadata schema with canonical values: book, article, report, policy, standard, website, dataset, video, podcast, interview, transcript, presentation, and manual.
- Updated starter schema docs, templates, validation, reconcile defaults, scanner metadata, status checks, processing stages, and LLM proposal validation to include `source_kind`.
- Verified with `python3 -m unittest discover -s tests` running 64 tests.

## 2026-06-11

- Replaced the starter controlled vocabulary while keeping sparse frontmatter: type values are now project, source, person, organization, meeting, task, note, index, daily, template, and system; status values are active, someday, completed, and archived; domain values are broad stable life areas.
- Added recommended topic hubs and agent rules to generated system files so agents use topic notes as the primary ontology instead of expanding metadata.
- Added validation for controlled domain values and tests proving `vault-agent init` writes the default vocabulary/norm files.
- Verified with `python3 -m unittest discover -s tests` running 54 tests.
- Added per-type Markdown body templates with sparse YAML, useful callouts, tables, checklists, and model-facing sections for project, source, person, organization, meeting, task, note, index, daily, template, and system notes.
- Refreshed `test_vaults/Memex/00 System/0.02 templates/note-types/` to contain only the current eleven templates and updated its schema/property/norm files from the repo defaults.
- Added template tests for sparse YAML and type-specific body scaffolds.
- Verified with `python3 -m unittest discover -s tests` running 57 tests.
- Added plugin-free embedded Bases index templates for domain dashboards, parent-filtered dashboards, type-filtered object collections, and cover galleries, following Obsidian's YAML Bases syntax and table/cards view patterns.
- Wired `00 System/0.02 templates/indexes/` into `vault-agent init` and refreshed the ignored Memex test vault with the same index templates.
- Added tests that parse embedded base blocks as YAML and verify they reference only sparse metadata plus Obsidian file/this properties.
- Verified with `python3 -m unittest discover -s tests` running 59 tests.
- Split note processing into explicit stages: `frontmatter-shape`, `classify-type`, `property-values`, `template-body`, and `summary`.
- Added `--stage` to `process-next` and `process-inbox`; when omitted, the agent runs only the next needed stage.
- Added `processing-state.json` as an agent ledger for per-note stage completion.
- Added narrow LLM prompts and validators so type classification, property-value filling, and summary writing happen in separate model calls.
- Updated deterministic frontmatter shaping so it adds accepted keys without inferring semantic values.
- Fixed summary-only writes so body changes are saved even when frontmatter is unchanged.
- Verified with `python3 -m unittest discover -s tests` running 53 tests.
- Added an OpenAI-compatible chat-completions proposal provider for local llama.cpp/OpenAI-style LLM backends.
- Added LLM config fields for `base_url`, `model`, `api_key`, `timeout_seconds`, `max_input_chars`, `embedding_base_url`, and `embedding_model`.
- Updated starter config defaults for the local Tailscale setup: chat endpoint `http://llms:8008`, model id `code`, embedding endpoint `http://llms:8005`, and embedding model id `embed`.
- Configured the ignored local `test_vaults/Memex` vault for one-note LLM test passes.
- Added a provider request/response unit test using a mocked OpenAI-compatible chat response.
- Verified the local Tailscale backend with a no-write proposal smoke test on `test_vaults/Memex/01 Inbox/Important Concepts.md`; the proposal validated successfully.
- Verified with `python3 -m unittest discover -s tests` running 48 tests.
- Ran the first one-note Memex write test through the local LLM provider on `01 Inbox/Important Concepts.md`; the note was classified, summarized, backed up, and logged.
- Fixed inbox processing so blank-but-present core YAML values count as processed metadata and proposal processing canonicalizes frontmatter to schema-approved properties.
- Added regression tests for proposal frontmatter cleanup and blank core metadata detection.
- Verified with `python3 -m unittest discover -s tests` running 50 tests.
- Added PyYAML-backed frontmatter parsing and canonical frontmatter rendering.
- Added `PyYAML>=6.0` as a runtime dependency.
- Added canonical schema helpers for accepted frontmatter properties and stable property order.
- Updated `vault-agent reconcile` to remove unknown frontmatter properties automatically, preserve accepted values, add missing core fields, report removals in dry-run/completion output, and skip malformed YAML without editing notes.
- Added config-file loading for `auto_process` and `llm` settings, plus starter config defaults for provider, confidence threshold, max notes, and runtime limits.
- Added a configured LLM provider placeholder that fails closed until a live provider is implemented.
- Added confidence-threshold blocking for proposal-based processing.
- Added frontmatter, reconcile, workflow, config, and low-confidence proposal tests.
- Verified with `python3 -m unittest discover -s tests` running 47 tests.
- Established the default note metadata schema as the sparse core property set.
- Updated starter schema files and note-type templates to use only approved sparse frontmatter properties.
- Updated scan, validate, retrieval, status, reconcile, and proposal processing to stop writing agent-internal fields such as `note_id`, `processing_status`, `domains`, `projects`, or frontmatter `summary`.
- Proposal summaries are now written into the note body under `## Summary`.
- Verified with `python3 -m unittest discover -s tests`.

## 2026-06-10

- Added starter schema, human-readable schema/property/folder files, and note-type templates.
- Implemented non-dry-run `vault-agent init` with no-overwrite starter file creation.
- Added atomic text writes, backups for modified files, and daily command logging.
- Added deterministic `scan`, `validate`, `rebuild-retrieval`, `status`, `process-next`, `process-inbox`, and `hermes-run` implementations.
- Kept v1 organization inbox-only: notes are not moved or renamed.
- Added workflow tests for scan exclusions, validation queues, inbox processing/backups, retrieval rebuild, and Hermes dry-run.
- Added structured LLM proposal validation with `--proposal-file`; valid proposals can classify/summarize and mark one inbox note `processed`, while invalid proposals make no edits.
- Added content-based whole-vault `reconcile` for schema-approved missing property defaults and missing template sections, and included it in `hermes-run`.
- Verified with `python3 -m unittest discover -s tests`.

## 2026-06-08

- Created project-control layer.
- Added `CODEX_START_HERE.md`.
- Added `PROJECT_PLAN.md`.
- Added `PROJECT_STATUS.md`.
- Added `NEXT_ACTIONS.md`.
- Added `DECISIONS.md`.
- Added `CHANGELOG.md`.
- Added initial Python CLI skeleton with no-op command routing.
- Added `pyproject.toml`, `vault_agent/`, and `tests/test_cli.py`.
- Verified CLI smoke behavior with `python3 -m vault_agent --help`, `python3 -m vault_agent scan`, `python3 -m vault_agent memory --help`, and `python3 -m unittest discover -s tests`.
- Added shared CLI config loading for resolved vault root, optional config path, dry-run, and verbose flags.
- Wired shared config into main and memory placeholder commands.
- Added config unit tests and CLI smoke tests for dry-run and verbose behavior.
- Verified config behavior with `python3 -m unittest discover -s tests`, `python3 -m vault_agent --help`, `python3 -m vault_agent scan --dry-run`, and `python3 -m vault_agent --verbose scan`.
- Added preview-only `vault-agent init --dry-run` output for required agent, retrieval, template, inbox, and trash paths.
- Added existing/create status labels to the init preview.
- Kept non-dry-run `vault-agent init` non-mutating until safe creation helpers exist.
- Verified init preview behavior with `python3 -m unittest discover -s tests`, `python3 -m vault_agent init --dry-run`, and `python3 -m vault_agent --vault-root /tmp/example-vault init --dry-run`.
- Added `vault_agent/safety.py` with no-overwrite creation planning and application helpers.
- Added backup-plan paths for existing starter files and conflict detection for path-type mismatches.
- Updated `vault-agent init --dry-run` to use the shared safety planner.
- Added safety tests for creating missing items, preserving existing files, backup planning, and conflicts.
- Verified safety helpers with `python3 -m unittest discover -s tests` and `python3 -m vault_agent init --dry-run`.
