# Project Plan

Long-lived implementation plan for pi-vault, the Obsidian vault management, retrieval, and memory agent. pi is the primary interface; the `vault_agent` Python CLI is the engine pi drives. The architecture references remain:

- `docs/architecture/Obsidian Vault Management and Retrieval Agent.md`
- `docs/architecture/Obsidian Vault Agent- Memory Layer Implementation Specification.md`

Use this file as a task tracker. Do not paste large source-spec sections here.

## Project-Control Layer

Status: Complete

### Goal

Create durable planning, status, decision, and handoff files so future agent sessions can resume work without relying on chat history.

### Design Notes

The control layer is Markdown in the project root. It is separate from the vault agent runtime files that will later live under `00 System/0.01 agent/`.

### Tasks

- [x] Create `START_HERE.md`. Evidence: file created on 2026-06-08.
- [x] Create `PROJECT_PLAN.md`. Evidence: file created on 2026-06-08.
- [x] Create `PROJECT_STATUS.md`. Evidence: file created on 2026-06-08.
- [x] Create `NEXT_ACTIONS.md`. Evidence: file created on 2026-06-08.
- [x] Create `DECISIONS.md`. Evidence: file created on 2026-06-08.
- [x] Create `CHANGELOG.md`. Evidence: file created on 2026-06-08.

### Acceptance Criteria

- [x] Future sessions have a single entry point. Evidence: `START_HERE.md`.
- [x] Plan, status, queue, decisions, and history are separated. Evidence: six project-control files.
- [x] No implementation code is created in this first pass. Evidence: only Markdown control files added.

### Files Likely Involved

- `START_HERE.md`
- `PROJECT_PLAN.md`
- `PROJECT_STATUS.md`
- `NEXT_ACTIONS.md`
- `DECISIONS.md`
- `CHANGELOG.md`

## CLI Foundation

Status: Complete

### Goal

Establish the command-line entry point and basic module layout for `vault-agent` without unsafe vault mutations.

### Design Notes

Prefer Python unless a stronger local reason appears. The CLI should eventually support `init`, `scan`, `validate`, `process-next`, `process-inbox`, `reconcile`, `review-proposals`, `rebuild-retrieval`, `status`, and `memory` subcommands.

### Tasks

- [x] Choose package layout matching the source specs. Evidence: added `vault_agent/` package on 2026-06-08.
- [x] Add a CLI entry point with no-op/help behavior. Evidence: added `vault_agent/cli.py`, `vault_agent/__main__.py`, and `pyproject.toml`; verified with `python3 -m vault_agent --help`.
- [x] Add shared config loading for vault root, config path, dry-run, and verbose output. Evidence: added `vault_agent/config.py`, wired shared config into placeholder handlers, and verified with `python3 -m unittest discover -s tests`, `python3 -m vault_agent scan --dry-run`, and `python3 -m vault_agent --verbose scan`.
- [x] Add placeholder command routing for required main commands. Evidence: `python3 -m vault_agent --help` lists main commands and `python3 -m vault_agent scan` reports no files changed.
- [x] Add placeholder command routing for required memory commands. Evidence: `python3 -m vault_agent memory --help` lists memory subcommands.
- [x] Add deterministic proposal review command. Evidence: `vault-agent review-proposals` validates/renders proposal JSON and applies approved proposals with backups/logging; verified with `python3 -m unittest discover -s tests`.

### Acceptance Criteria

- [x] CLI help lists planned commands. Evidence: `python3 -m vault_agent --help` and `python3 -m vault_agent memory --help`.
- [x] No command mutates vault notes yet. Evidence: placeholder handlers report `No files were changed`; verified with `python3 -m vault_agent scan`.
- [x] Tests or smoke checks verify the entry point starts. Evidence: `python3 -m unittest discover -s tests` ran 3 tests successfully.

### Files Likely Involved

- `vault_agent/cli.py`
- `vault_agent/config.py`
- `pyproject.toml`
- `tests/`
- `README.md`

## Agent Folder Structure

Status: In progress

### Goal

Implement `vault-agent init` to create the required vault-native folder structure and starter files safely.

### Design Notes

Runtime files belong inside `00 System/0.01 agent/`. Human-editable schema and templates belong in `00 System/0.02 templates/`. The system must not overwrite user-edited files without backup.

### Tasks

- [x] Define required folder tree for `00 System/0.01 agent/`. Evidence: added directory specs in `vault_agent/init.py`.
- [x] Define required folder tree for `00 System/0.02 templates/`. Evidence: added template directory specs in `vault_agent/init.py`.
- [x] Define `00 System/0.99 trash/` and `01 Inbox/` creation rules. Evidence: included both folders in `vault-agent init --dry-run` output.
- [x] Implement dry-run output for planned folder/file creation. Evidence: verified with `python3 -m vault_agent init --dry-run` and `python3 -m vault_agent --vault-root /tmp/example-vault init --dry-run`.
- [x] Implement safe creation with no overwrite unless backed up. Evidence: added `vault_agent/safety.py` with no-overwrite creation planning, existing-file preservation, conflict detection, and backup-plan paths; verified with `python3 -m unittest discover -s tests`.
- [x] Add generated/human-editable headers where appropriate. Evidence: starter Markdown files include system frontmatter and generated retrieval files have explicit titles.

### Acceptance Criteria

- [x] `vault-agent init --dry-run` shows planned changes only. Evidence: `python3 -m unittest discover -s tests` includes non-mutation checks for empty and partially initialized vault roots.
- [x] `vault-agent init` creates missing folders and starter files. Evidence: `tests/test_cli.py`.
- [x] Existing files are preserved or backed up. Evidence: no-overwrite creation tests and safe write helpers.
- [x] System files are distinguishable from ordinary notes. Evidence: system frontmatter and `00 System/` paths.

### Files Likely Involved

- `vault_agent/cli.py`
- `vault_agent/config.py`
- `vault_agent/safety.py`
- `00 System/0.01 agent/config.yaml`
- `00 System/0.01 agent/schema.json`
- `00 System/0.02 templates/`

## Schema Design

Status: In progress

### Goal

Create the machine-readable schema for note types, sparse core properties, controlled values, folder norms, and versioning.

### Design Notes

The starter note types are project, source, person, organization, meeting, task, note, index, daily, template, and system. The default public note metadata schema is intentionally sparse: `type`, `status`, `domain`, `parent`, `related`, `cover`, `source_kind`, and `capture_type`. Unknown properties and values should be validated and reviewed; `reconcile` may remove unknown properties during explicit cleanup with backups and logs.

### Tasks

- [x] Define `schema.json` structure and versioning. Evidence: `vault_agent/schema.py`.
- [x] Add sparse core properties. Evidence: `CORE_PROPERTIES` in `vault_agent/schema.py`.
- [x] Keep note metadata sparse and avoid type-specific frontmatter properties. Evidence: default schema accepts only the sparse core properties, with controlled values for `type`, `status`, `domain`, `source_kind`, and `capture_type`.
- [x] Add folder norms in machine-readable form. Evidence: `default_schema()` includes `folder_norms` derived from note type preferred folders.
- [x] Mirror schema in human-readable Markdown files. Evidence: starter file rendering in `vault_agent/starter_files.py`.
- [ ] Define deprecation fields for future schema changes.

### Acceptance Criteria

- [x] Schema can be loaded and validated. Evidence: starter schema generation and validator tests use `vault_agent/schema.py`.
- [x] Required properties and allowed values are explicit. Evidence: `schema.json` includes allowed values for `type`, `status`, `domain`, `source_kind`, and `capture_type`; all frontmatter keys remain optional.
- [x] Schema version is recorded. Evidence: `SCHEMA_VERSION` is written into `schema.json`.
- [ ] Human-readable schema files match machine-readable schema.

### Files Likely Involved

- `vault_agent/schema.py`
- `00 System/0.01 agent/schema.json`
- `00 System/0.02 templates/0.020 vault schema.md`
- `00 System/0.02 templates/0.021 property values.md`
- `00 System/0.02 templates/0.022 folder norms.md`

## Template Management

Status: In progress

### Goal

Create one useful Markdown template per note type and manage template versions safely.

### Design Notes

Templates must preserve user body text when applied. Missing sections may be inserted only if absent. Existing frontmatter values should be preserved unless invalid or empty. Templates may be visually rich in the note body, but YAML must stay limited to the eight sparse properties.

### Tasks

- [ ] Define template file format and version fields.
- [x] Create starter templates for all starter note types. Evidence: `starter_templates()` in `vault_agent/schema.py`.
- [x] Add useful body scaffolds for each current note type. Evidence: `TEMPLATE_BODIES` provides per-type callouts, headings, tables, and checklists without extra YAML.
- [x] Add index templates with embedded Bases. Evidence: `index_base_templates()` provides domain, parent-dashboard, object-collection, and cover-gallery templates using only sparse properties.
- [x] Validate that templates reference only schema-approved properties. Evidence: `tests/test_templates.py` verifies sparse frontmatter and rejects common extra YAML fields.
- [x] Add safe section insertion rules. Evidence: `append_missing_headings()` now appends full missing `##` section blocks from starter templates while preserving existing sections; template/reconcile/workflow tests prove idempotency and body preservation.
- [ ] Track template versions in manifest/state.

### Acceptance Criteria

- [x] Every starter note type has a template. Evidence: `starter_templates()` generates one template for each `NOTE_TYPES` entry.
- [x] Template validation catches unknown properties. Evidence: `tests/test_templates.py` checks every starter template against `CORE_PROPERTY_ORDER`.
- [x] Applying a template is idempotent in dry-run tests. Evidence: template section insertion reports/appends only absent `##` sections and repeated application does not duplicate sections.
- [x] Template application never removes user body text. Evidence: workflow and proposal tests assert original body content remains.

### Files Likely Involved

- `vault_agent/templates.py`
- `00 System/0.02 templates/note-types/*.md`
- `00 System/0.02 templates/indexes/*.md`
- `tests/test_templates.py`

## Vault Scanning And Manifest Generation

Status: In progress

### Goal

Scan the vault and maintain deterministic machine-readable state about notes without modifying note content.

### Design Notes

Scan excludes `00 System/0.01 agent/`, `00 System/0.99 trash/`, `.git/`, and `.obsidian/`. Templates in `00 System/0.02 templates/` are included as system/template files but not processed as ordinary notes. Hashes are preferred over modified times for staleness.

### Tasks

- [x] Implement Markdown file discovery with exclusions. Evidence: `vault_agent/scanner.py`.
- [x] Extract path, title, size, timestamps, hashes, and frontmatter status. Evidence: manifest entries in `vault_agent/scanner.py`.
- [x] Generate stable manifest entries. Evidence: deterministic path sorting in scanner tests.
- [x] Avoid adding IDs during scan unless explicitly configured. Evidence: scan writes state only.
- [x] Update `state.json` with scan metadata. Evidence: `render_state`.
- [x] Generate `01 vault-map.md` and `02 note-catalog.md`. Evidence: `run_scan`.

### Acceptance Criteria

- [x] `vault-agent scan --dry-run` reports discovered notes without writing. Evidence: CLI tests.
- [x] `vault-agent scan` writes manifest/state/catalog files only. Evidence: workflow tests.
- [x] System and trash folders are excluded from ordinary processing. Evidence: workflow tests.
- [x] Repeated scans are deterministic when files do not change. Evidence: sorted scanner output.

### Files Likely Involved

- `vault_agent/scanner.py`
- `vault_agent/manifest.py`
- `vault_agent/frontmatter.py`
- `00 System/0.01 agent/manifest.json`
- `00 System/0.01 agent/state.json`
- `00 System/0.01 agent/retrieval/01 vault-map.md`
- `00 System/0.01 agent/retrieval/02 note-catalog.md`

## Locked Norms And Organization Reports

Status: In progress

### Goal

Let pi (and any other runner) establish the current vault canon, lock it into generated agent state, process notes against that lock, and report what was done or still needs review.

### Design Notes

The lock is generated machine state under `00 System/0.01 agent/`. It snapshots schema, template hashes, controlled values, legacy alias config, and review gates. The lock hash is recorded in `processing-state.json` so notes become stale when content or norms change. Organization reports are generated Markdown/JSON artifacts, not note frontmatter.

### Tasks

- [x] Add `vault-agent norms-lock` for generated vault-local norms snapshots. Evidence: added `vault_agent/norms.py`, wired CLI help, and verified with `python3 -m vault_agent --vault-root /private/tmp/vault-agent-smoke norms-lock --dry-run`.
- [x] Record norms lock hashes in the processing ledger. Evidence: updated `vault_agent/processing_state.py` and `vault_agent/processor.py`; tests prove content and lock changes make stages stale.
- [x] Add bounded `vault-agent organize-vault-pass` with Markdown/JSON reports. Evidence: added `vault_agent/organize_pass.py`; workflow tests prove report writing and lock-aware state updates.
- [x] Add `vault-agent propose-cleanup-queue` for bounded validation-group cleanup proposals. Evidence: added generator/CLI support and tests proving generated proposals validate through `review-proposals --dry-run`.
- [x] Surface lock/report status to other agents. Evidence: `status` reports provisional/locked/drifted schema state, previous scan time, inbox deltas, validation groups, pending proposals, stale/blocked work, and latest reports; README, `AGENT_CONTRACT.md`, and initialized-vault starter guidance define the same lifecycle.
- [x] Add readiness-first organization preflight. Evidence: added `vault-agent organization-readiness`, `validate --json`, generated-state/template checks, and `reconcile --dry-run` preflight output.

### Acceptance Criteria

- [x] Dry-runs do not mutate vault files. Evidence: CLI tests for `norms-lock --dry-run` and `organize-vault-pass --dry-run`.
- [x] Real organization passes write reports and logs through existing safety helpers. Evidence: workflow tests and passing full suite.
- [x] Proposal-backed cleanup remains behind `review-proposals`. Evidence: cleanup queue produces pending proposal JSON only.
- [x] Agents can inspect readiness as JSON before broad passes. Evidence: CLI tests cover `organization-readiness --json` and `validate --json`.
- [ ] Complete a copied-vault or Memex dry-run pilot and record before/after issue counts.

### Files Likely Involved

- `vault_agent/norms.py`
- `vault_agent/organize_pass.py`
- `vault_agent/processing_state.py`
- `vault_agent/proposals.py`
- `vault_agent/readiness.py`
- `vault_agent/generated_state.py`
- `00 System/0.01 agent/norms-lock.json`
- `00 System/0.01 agent/reports/`

## Frontmatter And Property Handling

Status: In progress

### Goal

Parse, validate, and safely update YAML frontmatter while preserving user-authored body text.

### Design Notes

If YAML parsing fails, no edits may be applied. Unknown properties are flagged by validation and removed during explicit `reconcile` cleanup with backups/logs. Only schema-approved values may be applied.

### Tasks

- [x] Implement frontmatter parser/writer. Evidence: `vault_agent/frontmatter.py` uses PyYAML for parsing and canonical rendering.
- [x] Preserve body text byte-for-byte except approved insertions. Evidence: parser separates frontmatter/body, and tests cover body preservation during processing/reconcile.
- [ ] Add stable note IDs only during explicit processing operations.
- [x] Validate common properties. Evidence: `vault_agent/validation.py` reports unknown properties, unknown types, invalid status/domain values, malformed frontmatter, and invalid `related`.
- [x] Validate controlled values without type-specific properties. Evidence: `vault_agent/validation.py` validates allowed `type`, `status`, `domain`, `source_kind`, and `capture_type` values while preserving the sparse schema.
- [x] Detect malformed YAML and route to review. Evidence: `parse_note()` surfaces YAML errors and validation/reconcile tests skip malformed notes without edits.

### Acceptance Criteria

- [x] Malformed YAML blocks edits. Evidence: reconcile and proposal processing return/skip without writing on parser errors.
- [x] Unknown properties are reported and cleanup removes them only during explicit reconcile. Evidence: validation reports unknown properties; reconcile reports and removes them with backups.
- [x] Valid updates preserve existing body text. Evidence: workflow and reconcile tests.
- [x] Tests cover empty, missing, and malformed frontmatter. Evidence: `tests/test_frontmatter.py`.

### Files Likely Involved

- `vault_agent/frontmatter.py`
- `vault_agent/validation.py`
- `vault_agent/safety.py`
- `tests/test_frontmatter.py`

## Validation And Review Queues

Status: In progress

### Goal

Validate vault notes, schemas, templates, summaries, IDs, and retrieval outputs without LLM use by default.

### Design Notes

Validation results should go to review files. It should detect invalid properties, values, types, duplicate IDs, missing IDs, stale summaries, stale processed notes, missing templates, malformed YAML, oversize notes, and out-of-date retrieval indexes.

### Tasks

- [x] Implement validation command. Evidence: `vault_agent/validation.py` and CLI handler.
- [x] Write `needs-review.md`. Evidence: `run_validate()`.
- [x] Write `processing-errors.md`. Evidence: `run_validate()`.
- [ ] Write `proposed-values.md` format.
- [x] Distinguish warnings, blockers, and errors. Evidence: validation issue severities distinguish warnings and errors; processing errors are rendered separately.
- [x] Add validation tests for safety-critical cases. Evidence: workflow tests cover malformed frontmatter and unknown values.

### Acceptance Criteria

- [x] `vault-agent validate` does not modify notes. Evidence: validation writes review files only.
- [x] Review files are deterministic and readable. Evidence: rendered Markdown review queues.
- [x] Invalid schema/template/note cases are reported clearly. Evidence: validation tests assert issue text.
- [x] Tests verify that invalid input prevents edits. Evidence: malformed frontmatter and invalid proposal tests.

### Files Likely Involved

- `vault_agent/validation.py`
- `00 System/0.01 agent/review/needs-review.md`
- `00 System/0.01 agent/review/proposed-values.md`
- `00 System/0.01 agent/review/processing-errors.md`
- `tests/test_validation.py`

## Deterministic Writes, Backups, Logging, And Rollback

Status: In progress

### Goal

Provide safe write primitives for all future commands that modify files.

### Design Notes

Before modifying a note or canonical state file, create a backup or diff. Use atomic writes. Every modifying command must log actions.

### Tasks

- [x] Implement atomic write helper. Evidence: `write_text_safely()` writes through temporary files before replacement.
- [x] Implement backup helper. Evidence: `write_text_safely()` creates backups before replacing existing files.
- [x] Implement backup path planning for no-overwrite creation. Evidence: `vault_agent/safety.py` plans backup paths for existing files and preserves them during creation; actual backup copying before overwrites remains future work.
- [x] Implement daily command logs. Evidence: `vault_agent/logging_utils.py` and modifying commands append logs.
- [ ] Add rollback or recovery guidance.
- [x] Require dry-run support for batch operations. Evidence: scan, validate, process-inbox, reconcile, and Hermes dry-run paths.

### Acceptance Criteria

- [x] Writes use temporary files followed by replace. Evidence: `write_text_safely()`.
- [x] Backups are created before note changes. Evidence: workflow/reconcile tests assert backup files.
- [x] Logs include command, timestamp, and result details. Evidence: `append_log()` and command integrations.
- [x] Failed writes preserve originals. Evidence: atomic replacement pattern avoids partial writes.

### Files Likely Involved

- `vault_agent/safety.py`
- `vault_agent/logging_utils.py`
- `00 System/0.01 agent/backups/`
- `00 System/0.01 agent/logs/YYYY-MM-DD.md`

## Retrieval Files And Indexes

Status: In progress

### Goal

Generate progressive-disclosure retrieval files from manifest, frontmatter, summaries, and state.

### Design Notes

Agents should begin with shallow generated files, then open standard/deep summaries, then full notes only when necessary. Retrieval generation should work without LLM summaries where possible.

### Tasks

- [x] Generate `00 retrieval-readme.md`. Evidence: starter files include retrieval instructions.
- [x] Generate `03 property-index.md`. Evidence: `vault_agent/retrieval.py`.
- [x] Generate `04 summary-brief.md`. Evidence: `vault_agent/retrieval.py`.
- [ ] Generate indexes by type, domain, project, and status.
- [ ] Generate standard summary group files.
- [ ] Generate deep summary files only for configured note types.
- [ ] Detect stale summaries with source hashes.

### Acceptance Criteria

- [x] `vault-agent rebuild-retrieval` regenerates retrieval Markdown deterministically. Evidence: workflow tests.
- [ ] Retrieval files cite note IDs and paths.
- [ ] Stale or missing summaries are flagged.
- [x] Retrieval rebuild does not call the LLM unless explicitly requested. Evidence: retrieval implementation is deterministic.

### Files Likely Involved

- `vault_agent/retrieval.py`
- `vault_agent/summaries.py`
- `00 System/0.01 agent/retrieval/`

## LLM Proposal Interface

Status: In progress

### Goal

Add a backend-agnostic LLM interface that returns structured JSON proposals only.

### Design Notes

The LLM must not directly rewrite files. It should receive one bounded note or source at a time, the allowed schema, relevant templates, and instructions to avoid invented values.

### Tasks

- [x] Define LLM provider abstraction. Evidence: `ProposalProvider` in `vault_agent/llm.py`.
- [x] Load provider config from `config.yaml`. Evidence: `AgentConfig` loads enabled/provider/base URL/model/timeouts and embedding endpoint metadata.
- [x] Build bounded note excerpting for large notes. Evidence: `OpenAICompatibleProposalProvider` truncates prompt input with `max_input_chars`.
- [x] Define JSON proposal schema for note processing. Evidence: `validate_proposal` in `vault_agent/llm.py`.
- [x] Validate JSON proposals before any file change. Evidence: invalid proposal test leaves the note unchanged.
- [x] Repair or record invalid model JSON consistently. Evidence: shared provider path extracts a balanced object, sends one repair prompt, and raises a structured failure record after repair failure.
- [x] Fail gracefully when LLM config is absent. Evidence: default provider is disabled/`none`, so non-LLM processing remains local.

### Acceptance Criteria

- [x] Invalid JSON causes no modifications. Evidence: provider/validation tests.
- [x] Unknown properties or values are rejected or queued. Evidence: unknown proposal keys and unknown note type are rejected.
- [x] One note body is processed per LLM context. Evidence: `process_note()` calls one provider for one selected note.
- [x] Non-JSON or thinking-text model output does not silently pass. Evidence: retry/failure tests assert repair prompt behavior and structured failure details.
- [x] Non-LLM commands work without LLM configuration. Evidence: full test suite runs without provider credentials.

### Files Likely Involved

- `vault_agent/llm.py`
- `vault_agent/processor.py`
- `vault_agent/config.py`
- `tests/test_llm_proposals.py`

## Process-Next Workflow

Status: In progress

### Goal

Process exactly one candidate note, apply validated deterministic changes, update summaries and state, then exit.

### Design Notes

Priority is unprocessed inbox notes, stale inbox notes, unprocessed elsewhere, stale elsewhere, and needs-review only if configured. State must be updated after the note.

Processing is staged so each command performs one narrow job: frontmatter shape, type classification, property values, template body, or summary.

### Tasks

- [x] Select one candidate from manifest/state. Evidence: `select_next_inbox_note()` selects one eligible inbox note from scan results.
- [x] Build bounded prompt input. Evidence: provider receives one selected note text.
- [x] Request structured LLM proposal. Evidence: JSON-file provider path.
- [x] Validate proposal against schema/templates. Evidence: proposal validator checks note types, statuses, lists, and summary.
- [x] Apply safe frontmatter and heading updates. Evidence: process applies validated frontmatter only.
- [x] Generate brief and standard summaries. Evidence: validated proposal summary is written under `## Summary`; richer summary files remain future work.
- [x] Track per-note stage completion. Evidence: `processing-state.json` records stage status for each processed note.
- [x] Keep model tasks separated by stage. Evidence: `classify-type`, `property-values`, and `summary` use separate prompts and validators.
- [ ] Generate deep summaries for configured types.
- [ ] Update manifest, state, retrieval, and logs.

### Acceptance Criteria

- [x] Command processes exactly one note. Evidence: `process-next` uses one selected note.
- [x] Existing body text is preserved. Evidence: workflow and proposal tests.
- [x] Invalid proposals produce no edits. Evidence: `tests/test_llm_proposals.py`.
- [x] Processed note metadata and hashes are updated. Evidence: proposal path updates sparse metadata and body summary; hashes update on next scan.
- [x] Every modification is logged and backed up. Evidence: process-next/process-inbox write through safe backup path and append logs.

### Files Likely Involved

- `vault_agent/processor.py`
- `vault_agent/frontmatter.py`
- `vault_agent/templates.py`
- `vault_agent/summaries.py`
- `vault_agent/retrieval.py`

## Process-Inbox Workflow

Status: In progress

### Goal

Process multiple inbox notes one at a time, with fresh context and state updates after each note.

### Design Notes

Never batch multiple note bodies into one LLM prompt. Support `--max-notes`, `--max-runtime-minutes`, and `--dry-run`.

### Tasks

- [x] Implement inbox candidate loop. Evidence: `run_process_inbox()`.
- [x] Enforce one-note context per processing call. Evidence: loop calls `process_note()` per selected note and proposal-file mode requires `--max-notes 1`.
- [x] Support max note and max runtime limits. Evidence: CLI/config options and `run_process_inbox()`.
- [ ] Persist state after each note.
- [ ] Stop cleanly on errors and log partial progress.

### Acceptance Criteria

- [x] Dry-run shows planned first candidate. Evidence: process-inbox dry-run output.
- [x] Each note is processed independently. Evidence: per-note loop.
- [x] A failure does not corrupt later candidates. Evidence: loop stops on errors and invalid proposals do not edit notes.
- [x] Logs identify processed and errored notes. Evidence: process-inbox logging.

### Files Likely Involved

- `vault_agent/processor.py`
- `vault_agent/cli.py`
- `tests/test_process_inbox.py`

## Reconcile Workflow

Status: In progress

### Goal

Check processed notes against current schema, templates, and summaries without fully reprocessing everything.

### Design Notes

Reconcile should identify notes needing frontmatter repair, summary regeneration, template section insertion, review, or no action.

### Tasks

- [ ] Detect schema-version staleness.
- [ ] Detect template-version staleness.
- [ ] Detect stale summaries.
- [x] Produce action plan in dry-run. Evidence: `vault-agent reconcile --dry-run`.
- [x] Apply safe deterministic repairs when requested. Evidence: `vault_agent/reconcile.py`.

### Acceptance Criteria

- [ ] Reconcile does not reprocess all notes by default.
- [x] Dry-run identifies needed actions. Evidence: `tests/test_reconcile.py`.
- [x] Applied repairs are backed up, logged, and validated. Evidence: safe write/log path in `run_reconcile`.

### Files Likely Involved

- `vault_agent/reconcile.py`
- `vault_agent/validation.py`
- `vault_agent/summaries.py`

## Review And Approval Workflow

Status: In progress

### Goal

Allow any agent framework to propose schema, index, template, and cleanup changes without directly mutating vault notes or system files.

### Design Notes

Proposal JSON files live under `00 System/0.01 agent/review/proposals/`. `vault-agent review-proposals` validates proposals, renders `proposed-changes.md`, and applies only proposals marked `approved`. Applied proposals are marked `applied`.

### Tasks

- [x] Define proposal file location and review output file. Evidence: initialized `review/proposals/` and `review/proposed-changes.md`.
- [x] Validate proposal structure, kind, operation names, paths, and sparse frontmatter values. Evidence: `vault_agent/review.py` and `tests/test_review_proposals.py`.
- [x] Apply approved file writes and frontmatter updates with backups/logs. Evidence: `write_file` and `update_frontmatter` operations with safe writes.
- [x] Block application when any proposal in the queue is invalid. Evidence: invalid queue test.
- [x] Add proposal templates/examples for common request types. Evidence: `AGENT_CONTRACT.md`, vault-local `AGENT_CONTRACT.md`, and README include proposal examples and generator commands.
- [x] Add dedicated commands that generate proposal JSON for index notes and canonical property changes. Evidence: `propose-index` and `propose-property` write pending proposal JSON validated by `review-proposals`.
- [x] Add dedicated commands that generate proposal JSON for template-change and cleanup requests. Evidence: `propose-template` and `propose-cleanup` generate pending proposals validated by `review-proposals`; verified with `python3 -m unittest discover -s tests`.
- [x] Add a dedicated command for hierarchical Bases dashboards. Evidence: `propose-base-hierarchy` writes a pending `base-hierarchy` proposal with domain and parent/project dashboard `write_file` operations; Memex smoke validation passed through `review-proposals --dry-run`.

### Acceptance Criteria

- [x] Dry-run renders proposals without writing.
- [x] Approved proposals are applied deterministically.
- [x] Invalid proposals prevent application.
- [x] Applied proposals are marked to avoid repeated application.
- [x] Common index and controlled-property requests can generate proposal files without hand-written JSON.
- [x] Template-change and cleanup requests can generate proposal files without hand-written JSON.
- [x] Hierarchical Bases dashboards can generate proposal files without hand-written JSON.

### Files Likely Involved

- `vault_agent/review.py`
- `vault_agent/proposals.py`
- `vault_agent/cli.py`
- `00 System/0.01 agent/review/proposals/*.json`
- `00 System/0.01 agent/review/proposed-changes.md`
- `tests/test_review_proposals.py`

## Schema-Chat And Proposed Values Review

Status: Not started

### Goal

Allow user-guided schema, template, property, value, and folder norm changes through structured proposals and deterministic application.

### Design Notes

The model may only propose structured change plans. The script must validate, preview, ask for explicit approval, back up files, apply targeted changes, increment versions, validate, log, and mark affected notes stale when needed.

### Tasks

- [ ] Define schema-change proposal schemas.
- [ ] Implement `schema-chat` or alias.
- [ ] Implement approval preview with default no.
- [ ] Implement targeted schema/template/property/value updates.
- [ ] Implement deprecation instead of deletion.
- [ ] Implement `review-proposed-values`.

### Acceptance Criteria

- [ ] Ordinary note processing never silently adds values.
- [ ] Schema-chat never edits ordinary notes.
- [ ] New values and note types update JSON and Markdown schema files.
- [ ] Template revisions increment template versions.
- [ ] Validation runs after approved changes.
- [ ] Affected notes are marked stale when needed.

### Files Likely Involved

- `vault_agent/schema_chat.py`
- `vault_agent/schema.py`
- `vault_agent/templates.py`
- `00 System/0.01 agent/review/proposed-values.md`

## Memory Folder Structure

Status: Not started

### Goal

Implement `vault-agent memory init` to create the dedicated memory subtree and starter files.

### Design Notes

Memory lives under `00 System/0.01 agent/memory/`. Canonical state is JSON and Markdown. SQLite is optional and rebuildable.

### Tasks

- [ ] Define required memory folder tree.
- [ ] Create starter memory config, schema, state, manifest, and logs.
- [ ] Create profile, chats, episodes, semantic, procedural, projects, temporal, retrieval, review, backups, db, and scripts folders.
- [ ] Add generated and human-editable file headers.
- [ ] Preserve existing memory files with backups.

### Acceptance Criteria

- [ ] `vault-agent memory init --dry-run` shows planned changes only.
- [ ] `vault-agent memory init` creates the memory structure.
- [ ] Existing human-edited memory files are not overwritten.

### Files Likely Involved

- `vault_agent/memory/`
- `00 System/0.01 agent/memory/config.memory.yaml`
- `00 System/0.01 agent/memory/memory-schema.json`
- `00 System/0.01 agent/memory/memory-state.json`
- `00 System/0.01 agent/memory/`

## Memory Schema, State, And Manifest

Status: Not started

### Goal

Define canonical memory record structure, IDs, statuses, source references, temporal fields, review status, and hashes.

### Design Notes

The memory system must keep separate what happened, what was inferred, what is currently true, what is useful to retrieve, and what the user approved.

### Tasks

- [ ] Define canonical memory schema.
- [ ] Define episode schema.
- [ ] Define chat manifest schema.
- [ ] Implement stable ID counters.
- [ ] Implement memory hash calculation.
- [ ] Add validation for provenance and required fields.

### Acceptance Criteria

- [ ] Memory records require source references.
- [ ] Duplicate IDs are detected.
- [ ] Invalid statuses and sensitivity values are rejected.
- [ ] Hashes support stale detection.

### Files Likely Involved

- `vault_agent/memory_schema.py`
- `vault_agent/memory_store.py`
- `00 System/0.01 agent/memory/semantic/memories.json`
- `00 System/0.01 agent/memory/episodes/episodes.json`
- `00 System/0.01 agent/memory/memory-state.json`

## Chat Ingestion And Episode Layer

Status: Not started

### Goal

Ingest chat exports into episodes first, then candidate memories, preserving provenance and avoiding broad unsupported claims.

### Design Notes

Chats go into `memory/chats/inbox/`. Valid chats move to `processed/`; malformed chats move to `review/`. Episodes are append-only event records and are not automatically current facts.

### Tasks

- [ ] Define Markdown and JSON chat input formats.
- [ ] Validate chat structure.
- [ ] Update chat manifest.
- [ ] Move valid and invalid chats to appropriate folders.
- [ ] Extract episode records without LLM.
- [ ] Queue candidate memory extraction when configured.

### Acceptance Criteria

- [ ] Malformed chat files are reviewed, not discarded.
- [ ] Episodes include source references and hashes.
- [ ] Chat ingestion supports dry-run.
- [ ] Chat processing is logged.

### Files Likely Involved

- `vault_agent/memory_ingest_chat.py`
- `vault_agent/memory_scan.py`
- `00 System/0.01 agent/memory/chats/`
- `00 System/0.01 agent/memory/episodes/episodes.json`

## Memory Extraction, Review, And Consolidation

Status: Not started

### Goal

Use LLMs only to propose candidate memories and patches, then validate and apply deterministic changes after review.

### Design Notes

Default auto-accept is disabled. Sensitive memories require review. Candidate memories lacking source references or making unsupported broad claims must be rejected or queued.

### Tasks

- [ ] Define memory proposal schema.
- [ ] Implement LLM candidate extraction from one bounded source at a time.
- [ ] Write proposed memories to review files.
- [ ] Implement memory review accept/reject/edit/list behavior.
- [ ] Implement consolidation patch schema.
- [ ] Implement contradiction and temporal refresh queues.

### Acceptance Criteria

- [ ] LLMs never directly write canonical memory.
- [ ] Sensitive memory is never auto-accepted.
- [ ] Accepted memories are validated and logged.
- [ ] Contradictions are recorded instead of silently overwritten.

### Files Likely Involved

- `vault_agent/memory_extract.py`
- `vault_agent/memory_consolidate.py`
- `vault_agent/memory_validate.py`
- `00 System/0.01 agent/memory/review/proposed-memories.md`
- `00 System/0.01 agent/memory/review/contradictions.md`

## Memory Retrieval And Context Packets

Status: Not started

### Goal

Regenerate memory retrieval files and compact context packets from canonical memory records.

### Design Notes

Context packets are the main agent interface. Agents should not need raw memory JSON for ordinary work. Expired, superseded, rejected, and unrelated sensitive memories should be excluded by default.

### Tasks

- [ ] Generate memory retrieval readme.
- [ ] Generate memory map, catalog, brief, and packet list.
- [ ] Generate context packets for default, research, writing, coding, health, and work.
- [ ] Generate indexes by entity, domain, project, type, status, and validity.
- [ ] Implement `memory retrieve` with query, project, domain, packet, token limit, and JSON output.

### Acceptance Criteria

- [ ] `vault-agent memory rebuild` does not call the LLM.
- [ ] Retrieval output explains why memories were selected.
- [ ] Expired and superseded memories are excluded by default.
- [ ] Context packets are deterministic from canonical records.

### Files Likely Involved

- `vault_agent/memory_retrieve.py`
- `vault_agent/memory_render.py`
- `00 System/0.01 agent/memory/retrieval/`

## Optional SQLite And Embeddings

Status: Not started

### Goal

Add optional rebuildable indexes for faster retrieval without making SQLite canonical.

### Design Notes

Canonical memory remains JSON and Markdown. SQLite and embedding caches may be deleted and rebuilt from canonical files.

### Tasks

- [ ] Define SQLite schema.
- [ ] Implement rebuild from canonical memory JSON.
- [ ] Add FTS fallback retrieval.
- [ ] Optionally add embeddings cache.
- [ ] Validate cache staleness.

### Acceptance Criteria

- [ ] Deleting SQLite does not lose canonical memory.
- [ ] Rebuild recreates tables and FTS index.
- [ ] Retrieval works without SQLite.

### Files Likely Involved

- `vault_agent/memory_db.py`
- `00 System/0.01 agent/memory/db/memory.sqlite`
- `00 System/0.01 agent/memory/db/embeddings.jsonl`

## Tests

Status: Not started

### Goal

Cover safety-critical behavior, deterministic output, validation, dry-runs, and idempotency.

### Design Notes

Tests should scale with risk. Prioritize no data loss, no invalid edits, no duplicate headings, malformed YAML protection, backup/log creation, and deterministic regeneration.

### Tasks

- [ ] Add fixtures for small test vaults.
- [ ] Test init idempotency and backups.
- [ ] Test scan exclusions and hash behavior.
- [ ] Test validation failures.
- [ ] Test frontmatter preservation.
- [ ] Test retrieval rebuild determinism.
- [ ] Test memory schema validation.
- [ ] Test dry-run behavior for batch operations.

### Acceptance Criteria

- [ ] Safety-critical commands have tests.
- [ ] Tests can run without network access.
- [ ] Tests do not require an LLM provider.
- [ ] Failure cases prove no modifications occurred.

### Files Likely Involved

- `tests/`
- `tests/fixtures/`
- `pyproject.toml`

## Documentation

Status: In progress

### Goal

Document setup, commands, safety model, generated files, human-editable files, and recovery workflows.

### Design Notes

Documentation should keep the specs as architecture references and explain day-to-day operation concisely.

### Tasks

- [x] Add user-facing README. Evidence: `README.md`.
- [x] Document CLI commands and dry-run behavior. Evidence: `README.md`.
- [x] Document generated vs human-editable files. Evidence: `README.md`, `AGENT_CONTRACT.md`, and generated `00 System/0.01 agent/AGENT_HANDOFF.md` / `AGENT_CONTRACT.md` starter content.
- [x] Document backups, logs, and recovery. Evidence: `README.md`, `AGENT_HANDOFF.md`, and `AGENT_CONTRACT.md`.
- [x] Document framework-agnostic agent startup and request routing. Evidence: repo-level `AGENT_CONTRACT.md` and initialized vault-local `00 System/0.01 agent/AGENT_CONTRACT.md`.
- [ ] Document memory retrieval startup order.
- [ ] Document limitations and deferred features.

### Acceptance Criteria

- [x] A future session can install/run commands from docs. Evidence: `README.md` includes editable install and direct module commands.
- [x] A user can identify which files are safe to edit. Evidence: README, handoff, and contract distinguish `00 System`, templates, generated state, and ordinary notes.
- [x] Recovery from failed writes is documented. Evidence: README names backups and logs.

### Files Likely Involved

- `README.md`
- `AGENT_CONTRACT.md`
- `00 System/0.01 agent/retrieval/00 retrieval-readme.md`
- `00 System/0.01 agent/memory/retrieval/00 memory-retrieval-readme.md`
