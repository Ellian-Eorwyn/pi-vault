# Project Status

Last updated: 2026-06-26

## Current Focus

The pi tool surface is the primary interface: eleven focused, typed `vault_*` tools (`vault_status`, `vault_readiness`, `vault_search`, `vault_retrieval`, `vault_schema_propose`, `vault_content_propose`, `vault_organize_propose`, `vault_process_notes`, `vault_maintain`, `vault_review_apply`, `vault_recovery`) drive the `vault-agent` engine, and the `vault-transform` skill sequences them end to end from a messy vault to an organized one. New vaults stay dashboard-first and proposal-gated; the engine's LLM/embeddings are enabled by default and tuned for a single-slot Qwen3.6-27B + Qwen3-Embedding-4B backend.

## Completed

- Replaced the broad `vault_manage` god-tool with eleven first-class typed pi tools plus structured `--json` engine output, added the `vault-transform` orchestration skill, removed the deprecated shim, and tuned engine defaults (enabled LLM/embeddings, single-slot-aware batch/timeout limits, kept confidence and word-preservation guards strict) for the Qwen3.6-27B + Qwen3-Embedding-4B backend. The proposal→review→apply boundary, all guards, and graceful deterministic degradation are preserved. Verified with 28 pi-vault vitest cases, 264 Python tests, and `npm run check`.
- Implemented the complete dashboard-first default layout, configurable bootstrap paths, preserved-curation dashboard shells, domain hierarchy output under `01 Dashboards`, deterministic purpose-based routing, safe-only inbox sorting, and proposal-first existing-vault migration. Clean external initialization reports 0 validation issues and `obsidian-check --json` reports 0 errors/0 warnings.
- Added editable Markdown vault defaults: initialized vaults now include `99 System/0.02 templates/0.024 vault defaults.md`, `export-schema-defaults` writes a portable schema/layout contract, and `import-schema-defaults` converts edited defaults into a pending `schema-change` proposal without mutating active schema files. Verified with 208 Python tests and `npm run check`.
- Added streamlined startup/onboarding: automatic vault-local continuation with explicit flag precedence, bootstrap session persistence/migration, one-step default/custom folder selection, automatic read-only model briefs, expanded status/inbox deltas, and provisional/locked/drifted schema semantics.
- Added deterministic bidirectional pi-forge/pi-vault MCP integration: sequential native forge tools, proposal-first `.md`/`.txt` artifact import with SHA-256 provenance, restricted `pi-vault-mcp`, reverse pi-forge client, and delegation/handoff skills. External submissions remain pending and never auto-approve or apply. Verified with 172 Python tests, focused MCP tests, both repositories' full checks, isolated installs, live sequential local-model calls in both directions, explicit review/apply in a temporary vault, Git change-set evidence, and `obsidian-check --json` with 0 errors and 0 warnings.
- Fixed vault-manager package discovery so the isolated pi-vault installer excludes test and copied-vault directories and successfully builds the bundled Python wheel.

- Integrated vault-manager into pi-vault without a nested Git repository; added configurable system/inbox paths, vault-local purpose/conventions files, JSON status, namespaced automation commands, interactive onboarding, bundled skills/context/tools, a macOS/Linux installer, and 157 passing Python tests plus focused TypeScript extension/package coverage.
- Added validated `create_directory` and `move_note` proposal operations with whole-proposal preflight, protected-path and collision checks, ambiguous-link detection, inbound wikilink updates, backups, and versioned rollback.

- Added Git-backed versioning as a first-class local safety layer: `vault-agent version init/status/log/show/diff/changed-files/restore/undo-run`, reusable versioning helpers, a shared execution wrapper for mutating commands, change-set JSONL, run artifacts, rollback hints, managed `.gitignore`, dirty-state policy, mass-edit gating, and `hermes-run` vault-level versioning. Versioning now treats a vault as initialized only when the Git top-level is the vault root, so nested test/copied vaults do not snapshot the parent project repo. Expanded tests to 150 passing unit/workflow cases.
- Proved the Memex model-block review loop with a fresh tiny `autonomous-run --create-lock --use-llm --stage classify-type --max-notes 2`: the run produced 2 blocked model proposals, `review-model-blocks --dry-run --approve-safe` reported 1 safe conversion and 1 unsafe skip, `review-model-blocks --approve-safe` created only the safe pending proposal for `01 Inbox/New Images.md`, and `review-proposals --dry-run` validated the converted proposal without note mutation. Tightened `--approve-safe` so below-threshold blocks stay pending instead of being promoted. Expanded tests to 153 passing unit/workflow cases.
- Created project-control files.
- Read and synthesized the two source specification documents.
- Refactored the project docs to be pi-first: promoted the dev-control docs (`START_HERE.md`, `PROJECT_*`, `DECISIONS.md`, `NEXT_ACTIONS.md`, `AGENT_CONTRACT.md`) to the repo root, moved the source specification documents under `docs/architecture/`, and reframed the engine README plus the baked-in vault `AGENT_HANDOFF`/`AGENT_CONTRACT` templates so pi (skills + `vault_*` tools) is the primary interface and the Python CLI is the engine.
- Created the initial Python CLI skeleton and package layout.
- Added no-op command routing for main vault commands and memory subcommands.
- Added smoke tests for CLI help and placeholder command behavior.
- Added shared config loading for vault root, config path, dry-run, and verbose options.
- Wired shared config into main and memory placeholder commands.
- Added unit and smoke tests for config loading and dry-run/verbose CLI behavior.
- Added preview-only `vault-agent init --dry-run` for required vault folders and starter files.
- Added tests proving `init --dry-run` reports planned setup without mutating the vault root.
- Added no-overwrite creation helpers for directories and starter files.
- Added backup-plan reporting for existing starter files.
- Added tests for missing paths, existing files, and path-type conflicts.
- Added starter schema, human-readable schema files, starter templates, and non-dry-run `vault-agent init`.
- Established the default note metadata schema as exactly `type`, `status`, `domain`, `parent`, `related`, `cover`, `source_kind`, and `capture_type`.
- Added deterministic scan/manifest/state/catalog generation with dry-run support.
- Added validation review queues for malformed frontmatter and unknown properties/values.
- Added atomic writes, backups for modified files, and daily command logs.
- Added deterministic retrieval rebuild for vault map, catalog, property index, and summary brief.
- Added inbox-only processing that safely adds sparse core metadata without moving or renaming notes.
- Added `vault-agent hermes-run --hermes-root <dir> --max-notes <n> --dry-run` for scheduled bounded maintenance across vault directories.
- Added a structured proposal validator and `--proposal-file` processing path so valid LLM JSON proposals can classify a note and write summaries into the note body.
- Invalid proposals produce no note edits.
- Added whole-vault `reconcile` that applies schema-approved missing property defaults and missing template sections based primarily on note content, not folder location; Hermes scheduled runs include this step.
- Expanded tests to cover scan exclusions, validation queues, inbox processing/backups, retrieval rebuild, and Hermes dry-run.
- Added PyYAML-backed frontmatter parsing/rendering for common Obsidian YAML shapes.
- Added canonical frontmatter cleanup during `reconcile`; unknown properties are removed with backups/logging, while accepted values are preserved.
- Added stable schema property ordering for rendered frontmatter.
- Added config-file loading for `auto_process` and `llm` settings, including max notes, runtime limits, provider name, and confidence threshold.
- Added configured LLM provider support and confidence-threshold gating for proposal processing.
- Expanded tests to 47 passing unit/workflow cases covering YAML parsing, cleanup, config loading, and low-confidence proposal blocking.
- Added an OpenAI-compatible chat completion provider for local llama.cpp/OpenAI-style backends.
- Configured the ignored local test vault `test_vaults/Memex` to use `http://llms:8008` with served model id `code`, plus embedding endpoint metadata at `http://llms:8005` with model id `embed`.
- Verified the local LLM backend with a no-write proposal smoke test on `test_vaults/Memex/01 Inbox/Important Concepts.md`; the returned proposal validated successfully.
- Expanded tests to 48 passing unit/workflow cases covering provider request/response parsing.
- Ran the first one-note Memex write test through the local LLM provider on `01 Inbox/Important Concepts.md`; the note was classified under the previous vocabulary, summarized, backed up, logged, and skipped on the next queue dry-run.
- Fixed a pilot-test bug so blank-but-present core YAML values count as processed metadata and proposal processing canonicalizes frontmatter to schema-approved properties.
- Expanded tests to 50 passing unit/workflow cases covering the pilot-test regression fixes.
- Split note processing into explicit stages so the model does one task at a time: `frontmatter-shape`, `classify-type`, `property-values`, `template-body`, and `summary`.
- Added a per-note processing ledger at `00 System/0.01 agent/processing-state.json`.
- Added stage-specific LLM prompts and validators for type classification, property values, and summary writing.
- Expanded tests to 53 passing unit/workflow cases covering staged processing.
- Replaced the old starter note-type/status vocabulary with the sparse default controlled vocabulary for the test vault: project, source, person, organization, meeting, task, note, index, daily, template, and system types; active, someday, completed, and archived statuses; broad domain values; recommended topic hubs; and agent rules.
- Added validation for controlled `domain` values and expanded init tests to verify generated system files contain the default vocabulary and norms.
- Expanded tests to 54 passing unit/workflow cases.
- Added visually rich, model-usable body templates for every current note type while preserving the sparse YAML schema.
- Refreshed the ignored Memex test vault's note-type templates and schema/norm files to match the repo defaults.
- Expanded tests to 57 passing unit/workflow cases.
- Added plugin-free Bases index templates for domain dashboards, parent-filtered topic/project dashboards, type-filtered object collections, and cover-card galleries using only sparse core metadata and Obsidian file properties.
- Refreshed the ignored Memex test vault's `00 System/0.02 templates/indexes/` files.
- Expanded tests to 59 passing unit/workflow cases.
- Added exact-note processing with `--note`, stale/missing-core stage detection, grouped validation issue summaries, config-driven legacy metadata aliases, default preservation of unknown frontmatter, opt-in unknown-property removal, and model-warning review gating.
- Ran the targeted Memex `property-values` write test on `01 Inbox/Important Concepts.md`; the run filled the missing `source_kind`, wrote a backup, logged the command, and updated `processing-state.json`.
- Expanded tests to 70 passing unit/workflow cases.
- Updated `hermes-run` to report and run both bounded `process-inbox` and bounded `process-vault` passes while keeping `00 System` and `01 Inbox` separate processing scopes.
- Expanded template application so missing `##` sections are appended as full rich template blocks, not heading-only placeholders, while preserving existing body text and avoiding duplicates.
- Tuned legacy metadata aliases for `area`/`areas`/`domains`, `source`/`source_type`/`publication_type`, and `tags`/`topic`/`topics`, with schema-approved normalization and default preservation of original legacy fields.
- Added `README.md` and initialized `00 System/0.01 agent/AGENT_HANDOFF.md` starter content for agent handoff.
- Expanded tests to 75 passing unit/workflow cases.
- Added framework-agnostic `AGENT_CONTRACT.md` guidance for Codex/OpenCode/Hermes/cron-style runners and initialized matching vault-local `00 System/0.01 agent/AGENT_CONTRACT.md` content.
- Ran a temporary copied-vault Hermes pilot. It exposed and verified fixes for YAML date serialization and no-LLM scheduled maintenance behavior.
- Updated `hermes-run` so no-LLM scheduled maintenance only runs deterministic processing stages and subcommand failures affect the overall exit code.
- Expanded tests to 77 passing unit/workflow cases.
- Added `vault-agent review-proposals` so agents can write proposal JSON under `00 System/0.01 agent/review/proposals/`, render `proposed-changes.md`, and apply only approved proposals.
- Added deterministic `write_file` and `update_frontmatter` proposal operations with validation, path safety, backups, logging, and applied-state marking.
- Expanded tests to 82 passing unit/workflow cases.
- Added `vault-agent propose-index` for type, domain, project, and parent index-note proposals.
- Added `vault-agent propose-property` for controlled property value schema-change proposals.
- Expanded tests to 86 passing unit/workflow cases.
- Added `vault-agent propose-template` for note-type template-change proposals.
- Added `vault-agent propose-cleanup` for one-note frontmatter cleanup proposals that can copy legacy aliases into sparse core properties and optionally remove unknown properties after review.
- Updated `propose-property` to preserve current vault schema/property-values content where present instead of replacing property docs wholesale from defaults.
- Updated proposal review rendering so `proposed-changes.md` reflects final `applied` statuses after approved proposals are applied.
- Piloted generated proposals in the copied Memex vault: approved and applied a `legal` domain schema-change, a Work domain index, a person template refresh, and a conservative cleanup for `06 People/Irina Krishpinovich.md`; verified backups, review log entries, applied statuses, and queue validation.
- Expanded tests to 90 passing unit/workflow cases.
- Added `vault-agent propose-folder-organization` for folder-scoped organization proposals that can add sparse metadata, strip approved legacy fields, append template body sections, and propose a dashboard with embedded Bases.
- Added checkpoint/resume support for LLM-backed folder proposal generation so long local-model batches can be recovered safely.
- Hardened local LLM proposal parsing for responses with trailing text and kept folder organization prompts on the configured input cap, now expressed as `max_input_tokens: 64000` with a 4 chars/token estimate.
- Added validation/application support for `folder-organization` proposals and `organize_note` operations, including malformed-frontmatter repair through the review boundary.
- Fixed YAML scalar rendering for special leading characters such as `** HoMEDUCS Scratch`.
- Piloted HoMEDUCS organization in `test_vaults/Memex/05 Projects/EEI/3.01 HoMEDUCS`: 60 notes received sparse core metadata, legacy frontmatter was stripped, `Vinod Narayanan.md` was classified as `person`, and `HoMEDUCS-Dashboard.md` was updated with folder-path-backed Bases filters so views populate even when `parent` is interpreted as a link object.
- Verified local LLM use through `http://llms:8077/` Logs with `Backend MoE` selected and streamed; observed serialized `slot id 0` tasks with `release` and `all slots are idle` before subsequent requests.
- Expanded tests to 103 passing unit/workflow cases.
- Added `vault-agent norms-lock` for generated vault-local schema/template/alias snapshots with stable lock hashes.
- Added lock-aware processing-state behavior so notes are stale when content changes or they were processed under an older norms lock.
- Added `vault-agent organize-vault-pass` for bounded lock-aware full-vault passes, with Markdown and JSON reports under `00 System/0.01 agent/reports/`.
- Added `vault-agent propose-cleanup-queue` for bounded validation-group cleanup proposals that continue to apply only through `review-proposals`.
- Updated `status`, README, repo/vault agent contracts, starter init directories, and generated handoff guidance for locked norms and organization reports.
- Expanded tests to 126 passing unit/workflow cases.
- Added `vault-agent organization-readiness` with JSON output for lock status, candidate stages, validation groups, cleanup opportunities, stale/blocked tracked notes, generated-state staleness, and latest reports.
- Added `validate --json` plus template/schema consistency and generated-state checks for stale norms locks, retrieval files, proposal review output, missing templates, and invalid template frontmatter.
- Enhanced `reconcile --dry-run` with a lock-aware preflight section while keeping reconcile mutation behavior unchanged.
- Hardened the OpenAI-compatible provider with shared JSON-object extraction, one repair prompt, and structured failure records for both full-note and stage-specific proposals.
- Expanded tests to 129 passing unit/workflow cases.
- Ran the first safe bounded Memex organization pilot against `test_vaults/Memex`: wrote the norms lock, refreshed proposal review output, generated and applied a 5-operation cleanup queue proposal without unknown-property removal, ran a targeted one-note LLM-backed `property-values` pass on `01 Inbox/Important Concepts.md`, rebuilt retrieval, and verified with `python3 -m unittest discover -s tests`.
- Memex pilot evidence: lock hash `32d9e490686c9b55aa07a7c954d7223a79ef6d90035b61e3970bbdca6fede34a`; report `test_vaults/Memex/00 System/0.01 agent/reports/organization-run-20260617-224737.md`; validation changed from 8237 issues after lock creation to 8232 after cleanup and remained 8232 after the one-note pass; readiness stayed `review`; blocked stages stayed 0; stale tracked notes dropped from 2 to 1.
- Made larger LLM-backed organization test batches auditable and serialized: `organize-vault-pass` now reports `LLM prompts: serialized one note stage at a time`, records per-item `queue_position`, and includes `llm_prompts_serialized` in JSON/Markdown reports. Added regression coverage proving two `property-values` prompts run in queue order without overlap; expanded tests to 130 passing unit/workflow cases.
- Added `vault-agent propose-base-hierarchy` for proposal-first domain and parent/project dashboard hierarchies with embedded Bases, deterministic coverage summaries, "Needs metadata" reporting for blank/invalid domains, and optional LLM coverage wording fallback.
- Generated `test_vaults/Memex/00 System/0.01 agent/review/proposals/base-hierarchy.json` only, without applying it; `review-proposals --dry-run` validated 10 queued proposals with 0 invalid proposals, including the new 18-operation base hierarchy proposal.
- Expanded tests to 135 passing unit/workflow cases.
- Added `vault-agent autonomous-run` for bounded safe scheduled maintenance: readiness preflight, norms-lock handling, scan/validate, cleanup proposal generation, optional safe non-schema proposal approval/application, bounded organization pass, retrieval rebuild, Markdown/JSON reports, and version rollback hints.
- Updated `vault-agent hermes-run` to route each discovered vault through the same autonomous maintenance routine instead of a separate duplicated maintenance chain.
- Added `vault-agent schema-conversation --conversation-file` to convert Markdown/JSON/YAML schema onboarding transcripts into pending schema/index/template proposals plus a human-readable summary, without directly mutating canonical schema files.
- Added `vault-agent obsidian-check` for static Obsidian compatibility validation of frontmatter YAML/order, embedded `base` block YAML/view/filter structure, and dashboard wikilinks, with optional live Obsidian CLI checks.
- Expanded tests to 150 passing unit/workflow cases. Memex smoke evidence: `autonomous-run --dry-run --max-notes 2 --create-lock --apply-safe` reported readiness `review` and no writes; `obsidian-check --json` reported 0 errors and 22 existing wikilink warnings in `test_vaults/Memex`; live `autonomous-run --create-lock --use-llm --stage classify-type --max-notes 2` reached the configured local model, processed 2 stages, changed 1 note, and blocked 1 near-threshold/warning-bearing proposal as designed.
- Added `vault-agent review-model-blocks` so warning-bearing or near-threshold staged LLM output is persisted to `00 System/0.01 agent/review/model-blocked-proposals.json` and `.md`, can be dry-run reviewed, and can be converted into normal pending proposal JSON without directly mutating notes.
- Updated organization/autonomous reports to include blocked model proposal counts, review artifact paths, and top block reasons; autonomous runs now surface review-required model blocks distinctly from generic failures. Expanded tests to 152 passing unit/workflow cases.

## In Progress

- None.

## Blocked

- None.

## Next Recommended Step

Publish the repository at its final Git URL, substitute that URL into the documented one-command installer, and run the installer from a clean macOS/Linux account before the first tagged release.

## Known Risks

- The source specs describe both vault retrieval and memory layers; future sessions should avoid merging them into one undifferentiated system.
- Frontmatter parsing now uses PyYAML, but canonical rendering intentionally normalizes comments, key order, and formatting.
- Inbox processing without a proposal adds missing core metadata; with a valid structured proposal it can classify and summarize one note while keeping frontmatter inside the sparse schema.
- A local OpenAI-compatible LLM provider is implemented and verified against the Tailscale llama.cpp backend, but broad vault processing should still use targeted or small batches with review gates.
- Whole-vault reconcile preserves accepted values, preserves unknown properties by default, can migrate configured legacy aliases into core properties, appends missing rich template sections, and skips malformed notes. Moves and renames are separate approved proposal operations.
- The broad inherited pi suite still contains a small set of tests tied to the upstream `pi` identity or timing-sensitive filesystem watchers. Focused pi-vault, package-manager, resource-loader, Python, build, and external-vault smoke checks pass.
- The configured system folder is excluded from ordinary reconcile/processing, and the configured inbox is handled separately from the whole-vault pass.
- No-LLM scheduled Hermes runs are deterministic-only; type classification, semantic property filling, and summary writing require an enabled provider or explicit proposal files.
- The pilot showed review queues still surface intentionally preserved fields like `created` and `summary`; the next production step should make those review decisions easier to accept, ignore, or codify.
- `propose-property` now preserves current vault schema/property-values content where present, but future schema-change tooling should still provide more targeted JSON/Markdown patch operations and deprecation support.
- Hermes scheduled runs are CLI-orchestrated; no filesystem watcher or OS scheduler installation is included.
- The agent must protect user-authored notes, so future broader note mutation still requires explicit targeting, validation, backups, and logs.
- SQLite is optional and must remain a rebuildable cache, not canonical state.
- LLM behavior must stay proposal-only; deterministic scripts must validate and apply changes.
- Model-backed work is now staged; future prompts should stay narrow and stage-specific rather than returning full-note decisions, and warning-bearing proposals require review by default. Valid but blocked staged output is persisted as model-block review artifacts and must still pass through normal proposal review before any note mutation.
- Local LLM-backed organization is serialized by design because the backend serves one capable model on a single inference slot: process one note/stage at a time. `organize-vault-pass --use-llm --max-notes N --stage <semantic-stage>` performs the queue progression automatically inside one run; prefer bounded passes with review checkpoints over large unattended runs.
- The HoMEDUCS pilot proved folder-scoped organization works through proposals, but classification quality is not yet fully autonomous; six of sixty notes fell back deterministically after non-JSON model responses. The shared repair path reduces this failure mode, but broad LLM runs still need report-driven pilots.
- `organize-vault-pass` now provides the lock/report/readiness infrastructure for expensive first passes. The first real Memex pass succeeded at one targeted note/stage with 0 blocked stages; the next test shape is a small stage-scoped serialized LLM batch, not a broad unscoped vault pass.
- `propose-cleanup-queue` generates bounded cleanup proposals from validation groups, but unknown-property removal remains explicit through `--remove-unknown`.
- Dashboard Bases that filter by `parent` should include a folder-path fallback when piloting against Obsidian link-valued properties.
- `propose-base-hierarchy` does not repair metadata; the Memex smoke test still found 958 non-system notes missing an approved domain, so generated hierarchy quality depends on continued cleanup/property-value passes.
- `autonomous-run` intentionally treats `--max-notes` as a total per-vault run bound, not a separate inbox and non-inbox limit.
- Versioning must not use a parent Git repository as the vault repository; nested copied/test vaults should initialize their own vault-root Git repo or configured separate git dir.
- `obsidian-check` is static by default; live rendering and screenshot/DOM verification require Obsidian to be open and `--live-obsidian` to be passed.
- `schema-conversation` is a conservative transcript parser, not a full natural-language ontology designer; ambiguous schema preferences should still be turned into explicit transcript decisions before proposal generation.
- The user wants properties to remain sparse; future template improvements should enrich note bodies, generated indexes, Bases, dashboards, and topic hubs rather than adding type-specific frontmatter fields.
- The two source specs remain in the root; moving them later could break references unless done deliberately.
- `pytest` is not installed in this environment; current tests use `python3 -m unittest discover -s tests`.

## Notes for Next Session

Start with `START_HERE.md`, then take the first unchecked task in `NEXT_ACTIONS.md`. The latest implementation added editable schema-default Markdown export/import; use `export-schema-defaults`, edit the generated Markdown, then run `import-schema-defaults` and `review-proposals --dry-run` before approval. The latest Memex static Obsidian check had 0 errors and 22 existing wikilink warnings. The next live LLM pass should remain tiny and stage-scoped so the scheduler report, model-block review artifacts, version restore hints, and Obsidian validation can be reviewed together.
