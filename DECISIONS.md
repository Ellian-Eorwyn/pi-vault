# Decisions

## 2026-06-26: Note Types Are Data-Driven; Schema Changes Are Guarded; People Are Extracted

Decision: Note types and the `source_kind`/`capture_type` controlled values are now
data-driven from `99 System/0.01 agent/schema.json` rather than hardcoded Python
constants only. Built-in types/values are always merged in and can never be dropped;
approved additions extend the runtime vocabulary once a schema-change proposal is applied
and norms are re-locked. Adding a note type (`propose-note-type`) writes the schema delta,
an on-disk `note-types/<slug>.md` template, and the preferred folder; template application
falls back to that on-disk template for custom types. A deterministic schema-change guard
validates every `schema.json` write (valid JSON, built-ins preserved, internally
consistent) — the schema analogue of the note-body word-preservation guard. People
extraction (`propose-people`, **vault-people** skill) detects people across notes,
deduplicates against existing person notes, classifies each clearly-identified new person
as Contact or Author via the configured backend, and creates person notes with grounded
details and backlinks. The **vault-schema** skill drives schema discussions and note-type
definitions; all model work stays on the configured pi/engine backend and proposal-gated.

Rationale: the user wanted to discuss and evolve the schema (including inventing new note
types) and to turn scattered mentions into real Contacts/Authors. Hardcoded `NOTE_TYPES`
blocked runtime type creation, so the foundation was to make types schema-driven while
keeping the built-in vocabulary inviolable through a guard plus mandatory review. Status
stays fixed because its four values drive control flow.

## 2026-06-26: LLM-Led Note Refinement Is Guarded And Backend-Only

Decision: pi-vault can refine a note's *body* — structure, coherence, skimmability,
and Obsidian Markdown — through a new `refine-body` LLM stage, a `restructure_body`
proposal operation (kind `note-refinement`), the `propose-folder-refinement` engine
command, and the **vault-analysis** skill for chatting about a folder. Two hard rules
bound it: (1) all model work runs through the user-configured pi/engine LLM backend
only — never Claude, Codex, or any third party unless the user explicitly points the
harness there; and (2) a deterministic word-preservation guard (`refine.meaning_preserved`)
compares the prose word multiset before and after and rejects any rewrite that drops
or substitutes the author's words, so wording and meaning never change. Frontmatter is
preserved byte-for-byte, the guard runs at both generation and apply time, and every
change stays proposal-gated, diffable, and git-backed.

Rationale: the user wanted thorough, whole-note analysis that improves structure
without rewriting content, while keeping pi-vault self-hosted and provider-agnostic.
Body rewriting is the one place the model produces note text, so it gets an explicit
deterministic safeguard plus mandatory human diff review rather than trust alone. The
guard is a safeguard, not a proof; the review gate and git rollback cover the residual.

## 2026-06-20: pi Is The Primary Interface; The Python CLI Is The Engine

Decision: pi-vault is a pi-first project. Users and agents interact with the vault by
launching `pi-vault`, which loads the `vault-*` skills and the `vault_status` /
`vault_manage` tools on startup; the `vault_agent` Python CLI (`vault-agent` /
`pi-vault vault …`) is the deterministic engine those skills and tools drive, not the
front door. Docs, the baked-in vault `AGENT_HANDOFF`/`AGENT_CONTRACT` templates, and request
routing all lead with the skills/tools and show engine commands as the layer beneath.

Rationale: the project began as a standalone, framework-agnostic Python CLI aimed at Codex
and other runners. Now that it ships as a pi extension, leading with pi makes the agent
load every skill on launch and interact with the vault more reliably, while the engine keeps
the deterministic, inspectable safety guarantees.

## 2026-06-20: Dev-Control Docs Live At The Repo Root

Decision: The dev-control docs (`START_HERE.md`, `PROJECT_PLAN.md`, `PROJECT_STATUS.md`,
`NEXT_ACTIONS.md`, `DECISIONS.md`, `AGENT_CONTRACT.md`) live at the repo root and guide the
whole pi-first project; the two large architecture specs live under `docs/architecture/`.
The engine-specific `vault-manager/README.md` and `vault-manager/CHANGELOG.md` stay beside
the Python engine they document.

## 2026-06-08: Project State Lives In Files

Decision: Project planning, status, next actions, decisions, and changelog are stored in Markdown files in the project root.

Reason: Future agent sessions should not rely on chat memory or reconstruct the whole plan.

Implications:

- Future sessions should begin with `START_HERE.md`.
- Status updates must be written to files after completed work sessions.
- The original specs remain architecture references, not task trackers.

## 2026-06-08: Markdown For Human-Readable Control Files

Decision: Markdown is used for project-control files and human-readable schema, template, review, retrieval, memory, and documentation surfaces.

Reason: Markdown is readable in Obsidian and easy for humans and agents to inspect.

Implications:

- Planning and review artifacts should stay concise and operational.
- Generated Markdown should identify itself as generated once implementation begins.
- Human-editable Markdown should be clearly marked where needed.

## 2026-06-08: JSON And YAML For Deterministic Machine State

Decision: JSON is preferred for canonical machine-readable state such as manifests, schemas, memory records, and indexes; YAML may be used for human-editable configuration where appropriate.

Reason: The source specs require deterministic, inspectable, local-first state that scripts can validate.

Implications:

- Canonical machine state should not live only in a database or chat transcript.
- Schema validation should happen before file mutation.
- Generated state should be rebuildable where practical.

## 2026-06-08: SQLite Is Optional And Rebuildable

Decision: SQLite may be used only where it adds clear retrieval or indexing value, and it must remain rebuildable from canonical JSON/Markdown.

Reason: The memory specification explicitly makes JSON/Markdown canonical and SQLite disposable.

Implications:

- Do not build SQLite first.
- Deleting SQLite must not lose project or memory state.
- Cache staleness must be detectable.

## 2026-06-08: LLMs Propose, Scripts Apply

Decision: LLMs may classify, summarize, extract, and suggest structured JSON proposals, but deterministic scripts must validate and apply any file changes.

Reason: The specs require safety, determinism, and protection against invalid or invented LLM output.

Implications:

- Invalid JSON must cause no file modifications.
- Unknown properties or values must go to review, not directly into notes.
- LLMs must not directly edit canonical memory or vault notes.

## 2026-06-08: Dry-Run Before Destructive Or Batch Mutation

Decision: Commands that modify vault notes, canonical state, memory, or generated indexes should support dry-run behavior before risky writes.

Reason: The vault must be protected from silent or accidental rewrites.

Implications:

- Build dry-run foundations before note processing.
- Batch commands must be previewable.
- Future task completion should include command evidence when possible.

## 2026-06-08: Local-First And Vault-Native Design

Decision: The system should run locally and store its operative files inside the Obsidian vault, primarily under `00 System/`.

Reason: Both source specs describe a portable, local-first, vault-native management system.

Implications:

- Avoid opaque external state as the source of truth.
- Keep generated retrieval and memory files inspectable.
- Prefer portable scripts and file formats.

## 2026-06-08: Protect User-Authored Notes

Decision: The system must never delete notes or user-authored body text, and it must not silently rename, move, or rewrite notes.

Reason: Data preservation is a mandatory safety rule in the source specs.

Implications:

- Note changes require validation, logging, backups or diffs, and explicit targeting.
- Unknown properties should be flagged instead of removed.
- Body edits should be limited to safe template section insertion when validated.

## 2026-06-08: Retrieval And Memory Layers Stay Distinct

Decision: Vault retrieval and memory retrieval should be linked but not merged.

Reason: The source specs distinguish vault retrieval, which tells agents what notes exist and where to look, from memory, which supplies durable context, preferences, project state, and procedural guidance.

Implications:

- Memory should not duplicate every note in the vault.
- Context packets are the main memory interface for agents.
- Vault indexes remain the main path to note content.

## 2026-06-08: Auto-Accept Memory Starts Disabled

Decision: Automatic acceptance of candidate memories starts disabled.

Reason: The memory spec requires conservative handling, especially for sensitive or temporary information.

Implications:

- Proposed memories should go to review by default.
- Sensitive memories must not be auto-accepted.
- Chat-derived temporary states should not become durable profile facts without review.

## 2026-06-11: Keep Vault Frontmatter Sparse

Decision: Managed vault notes use only the sparse public frontmatter properties `type`, `status`, `domain`, `parent`, `related`, `cover`, `source_kind`, and `capture_type`. Type-specific organization belongs in body templates, links, topic hubs, generated indexes, Bases, dashboards, and agent memory rather than additional YAML properties.

Reason: The user wants properties to remain sparse so agents can apply metadata consistently without turning YAML into the primary ontology of the vault.

Implications:

- Do not add type-specific frontmatter fields for project, claim, concept, meeting, or similar note classes; `source_kind` is the controlled source-medium field and `capture_type` is the controlled ingestion-method field.
- Default controlled values should stay broad and stable; agents should create topic notes rather than new domain values.
- Explicit cleanup commands such as `reconcile` may remove unknown YAML properties only with dry-run support, backups, and logs.

## 2026-06-11: Preserve Legacy Frontmatter By Default

Decision: Legacy or unknown frontmatter properties are preserved by default. The agent may copy configured legacy aliases into sparse core properties, but it only removes unknown properties when `legacy_metadata.preserve_unknown_properties` is explicitly set to `false`.

Reason: Existing vault metadata such as created dates, tags, titles, aliases, source fields, and summaries may still be useful. Broad removal during reconcile is too destructive for real vault onboarding.

Implications:

- Validation should group legacy issues and identify mappable aliases instead of treating every legacy field as an urgent cleanup problem.
- Reconcile should migrate/copy safe aliases into core fields while leaving original metadata in place unless removal is explicitly configured.
- Full vault organization should tune legacy mappings before widening beyond targeted note tests or small batches.

## 2026-06-11: Folder-Agnostic Organization Outside System And Inbox

Decision: Folder placement is advisory outside `00 System` and `01 Inbox`. Ordinary note organization should rely on sparse metadata, links, body sections, generated indexes, Bases, dashboards, and topic hubs, not physical folder location.

Reason: The vault should be manageable from mixed or legacy folder layouts without requiring automatic note moves.

Implications:

- `00 System` is excluded from ordinary reconcile and processing.
- `01 Inbox` is handled by inbox-specific processing, not the whole-vault processing pass.
- The agent must not automatically move or rename notes as part of organization.
- Preferred folders in schema/docs are suggestions for humans and dashboards, not processing requirements.

## 2026-06-11: Agents Propose Reviewable Changes Before Applying

Decision: Agent-framework workflows for schema, index, template, and cleanup changes should use deterministic proposal JSON files under `00 System/0.01 agent/review/proposals/`. `vault-agent review-proposals` validates and renders proposals, and only applies proposals whose status is explicitly `approved`.

Reason: Codex, OpenCode, Hermes, cron jobs, and other runners need one shared mechanism for safe mutation that does not depend on chat history or a specific agent framework.

Implications:

- Agents can propose changes without directly editing user-authored notes.
- Review output lives in `00 System/0.01 agent/review/proposed-changes.md`.
- Applying approved proposals must use safe writes, backups, logs, and path validation.
- Invalid proposals block application until fixed or removed.
- Future ergonomic commands should generate proposal JSON rather than bypassing the review path.

## 2026-06-11: Ergonomic Commands Generate Proposals

Decision: Commands for common user requests, such as creating index notes, proposing canonical property values, refreshing note-type templates, or cleaning up one note's frontmatter, should generate pending proposal JSON rather than applying changes directly.

Reason: Agents need convenience without losing the deterministic review/approval boundary.

Implications:

- `propose-index`, `propose-property`, `propose-template`, and `propose-cleanup` write pending proposals only.
- Users or supervising agents approve by changing proposal `status` to `approved`.
- `review-proposals --apply-approved` remains the mutation boundary.
- Future batch cleanup and schema-chat helpers should follow the same pattern.

## 2026-06-12: Folder Organization Pilots Stay Proposal-Scoped

Decision: Folder-scoped organization, including project dashboards and bulk note metadata cleanup, should be generated as pending `folder-organization` proposals and applied only through `review-proposals`.

Reason: The HoMEDUCS pilot needed broad edits inside one folder, but the safety boundary still mattered: proposals made the mutation inspectable, resumable, backed up, and limited to the target folder plus `00 System` review/log/backup files.

Implications:

- Use `vault-agent propose-folder-organization --folder <folder> --project <name> --domain <domain>` for copied-vault pilots.
- Prefer `--checkpoint` and `--resume` for local LLM-backed batches.
- Use `--remove-legacy` only when the pilot explicitly calls for stripping non-core frontmatter.
- Keep the public note schema sparse; do not add type-specific HoMEDUCS or project fields to YAML.
- Dashboard Bases should include a folder-path fallback filter in addition to `parent` equality during folder pilots.

## 2026-06-12: Local LLM Test Runs Are Serialized And Monitored

Decision: Local LLM-backed processing should send one prompt at a time, wait for completion, and monitor the Backend MoE logs when testing new features.

Reason: The user wants the local llama.cpp backend tested directly and not overloaded by concurrent prompts. The HoMEDUCS pilot showed the Stack Manager logs are the fastest way to confirm serialized behavior and spot non-JSON/thinking output failures.

Implications:

- Use the configured vault LLM provider rather than hard-coded endpoints.
- Monitor progress at `http://llms:8077/`: open Logs, select `Backend MoE`, click `Stream`.
- Confirm `slot id 0` task `release` and `all slots are idle` before sending the next prompt.
- If model output is non-JSON, record the failure, fall back deterministically only where safe, and add parser/prompt regression tests before widening.

## 2026-06-17: Broad Organization Runs Use Locked Vault Norms

Decision: Expensive full-vault or broad folder organization runs should process notes against a generated `norms-lock.json` snapshot of schema, templates, controlled values, legacy aliases, and review gates.

Reason: Codex, OpenCode, Hermes, and other runners need a shared vault-local contract that says which norms were current when a note was classified or cleaned up. A note processed under old schema/template norms should be detectable without adding agent-only fields to note YAML.

Implications:

- `processing-state.json` records the `norms_lock_hash` for completed stages.
- Notes become stale when their content hash changes or the current norms lock hash differs from the ledger.
- Organization pass reports under `00 System/0.01 agent/reports/` explain what changed, what blocked, and what remains.
- The norms lock and reports are generated agent state and should not be modified by ordinary proposal JSON.

## 2026-06-18: Autonomous Runs Apply Only Bounded Safe Non-Schema Changes

Decision: Scheduled maintenance through `autonomous-run` and `hermes-run` may auto-approve and apply only bounded safe proposals with supported operations and an explicit operation limit. Schema changes remain pending for human review unless a future decision changes that policy.

Reason: Git-backed restore points make autonomous maintenance safer, but schema changes alter future vault norms and should still require deliberate approval before a new norms lock is written.

Implications:

- Cron/Hermes jobs should use `autonomous-run --apply-safe --max-notes <n>` or `hermes-run --apply-safe --max-notes <n>` for bounded maintenance.
- Autonomous reports must include rollback hints, report paths, readiness counts, proposal status summaries, and changed files where available.
- `--max-notes` is a total per-vault autonomous-run bound, not one limit for inbox and another for non-inbox notes.
- Unknown-property removal and schema-change proposals stay opt-in and review-gated.

## 2026-06-18: Schema Onboarding Starts From Transcript Files

Decision: The first schema onboarding/revision system is `schema-conversation --conversation-file`, which converts explicit Markdown/JSON/YAML conversation decisions into pending proposals and a summary.

Reason: Transcript files are portable across Codex, OpenCode, Hermes, and other harnesses, and they keep the user-agent schema negotiation inspectable before any canonical schema files change.

Implications:

- The command should generate proposals, not directly edit schema/template files.
- Ambiguous preferences should be clarified in the transcript before proposal generation.
- After approved schema/template changes are applied, run `norms-lock --write` so autonomous jobs use the revised vault rules.

## 2026-06-18: Obsidian Compatibility Is Static-First With Optional Live Checks

Decision: `obsidian-check` always performs static frontmatter and embedded Base validation, while live Obsidian CLI checks are optional unless `--require-live` is passed.

Reason: Unit tests and cron jobs need reliable non-GUI validation, but live Obsidian rendering is still useful when the app is open for dashboard QA.

Implications:

- Static checks must catch malformed frontmatter YAML, canonical property order drift, malformed embedded `base` YAML, unsupported Base views, invalid filter structure, and obvious dashboard link problems.
- `obsidian-check --live-obsidian` may be used as a manual acceptance gate for generated dashboards and Bases.
- Existing vault wikilink warnings do not block autonomous maintenance unless promoted to errors later.

## 2026-06-17: Organization Passes Require Readiness Preflight

Decision: Broad organization work should be preceded by `organization-readiness`, JSON validation groups, and generated-state staleness checks before any real note mutation.

Reason: A lock file alone is not enough to decide whether a vault is safe for an autonomous pass. Agents also need to know whether templates are missing or stale, retrieval output is stale, proposal review output needs regeneration, tracked notes are stale or blocked, and validation groups suggest cleanup proposals before LLM-backed note work.

Implications:

- `status` includes a compact `Ready for organization pass: yes/no/review` line.
- `organization-readiness --json` is the machine-readable preflight for Codex, OpenCode, Hermes, and similar runners.
- `validate --json` exposes grouped validation issues without writing review files.
- `reconcile --dry-run` reports generated-state and lock-aware preflight context while preserving reconcile's existing mutation behavior.
- First real organization passes should start at `--max-notes 1` or `--max-notes 2` and widen only after reports show low blocked or ambiguous rates.

## 2026-06-18: Base Hierarchies Stay Proposal-Scoped And Dashboard-Based

Decision: Hierarchical Bases should be generated as pending `base-hierarchy` proposals containing Markdown dashboard `write_file` operations with embedded Bases, not as direct note edits or new frontmatter fields.

Reason: Bases can filter and display live note sets, but coverage descriptions are prose. Keeping coverage in dashboard Markdown and keeping the live views in embedded Bases preserves sparse metadata while still giving agents and humans a navigable domain/project hierarchy.

Implications:

- Use `vault-agent propose-base-hierarchy` for domain and parent/project dashboard requests.
- `review-proposals --dry-run` and `review-proposals --apply-approved` remain the validation and mutation boundary.
- Do not add properties such as `subdomain`, `project_id`, `coverage`, or `base_group` for this feature.
- Blank or invalid domains are surfaced as "Needs metadata" instead of becoming a generated domain.
- Optional model output may improve labels or coverage wording, but deterministic grouping and validation remain authoritative.

## 2026-06-18: Git Is The Agent Safety Layer, Not Sync

Decision: Vault-agent write commands should use local Git automatically for initialization, pre/post snapshots, change-set metadata, rollback hints, and affected-path restore, while keeping external sync and pushing out of scope by default.

Reason: Backups and logs protect individual writes, but agent-mediated vault work also needs run-level answers to what changed, what state existed before and after, and how to undo one path or one run without raw Git commands.

Implications:

- Mutating commands go through the versioned execution wrapper unless they are dry-runs or read-only reports.
- Git metadata is local by default; `auto_push` remains disabled.
- Change sets live under `00 System/0.01 agent/versioning/` and are represented as structured JSONL plus per-run artifacts.
- Mass edits require explicit opt-in when they exceed configured thresholds.
- Rollback commands restore affected paths from the pre-run commit and avoid full-repo resets by default.

## 2026-06-18: Safe Model-Block Conversion Skips Below-Threshold Output

Decision: `review-model-blocks --approve-safe` converts only blocked model outputs that clear the configured confidence threshold; below-threshold blocks remain pending in the model-block review artifact.

Reason: The command name promises a safety filter. A low-confidence block should not be promoted into the normal proposal queue merely because it was selected with other reviewable blocks.

Implications:

- Dry runs report both convertible and skipped unsafe block counts.
- Skipped blocks are informational and do not make the command fail.
- Human reviewers can still inspect low-confidence blocks and decide whether to handle them manually, but the default safe path leaves them pending.

## 2026-06-20: Vault Paths Are Bootstrapped Per Vault

Decision: `pi-vault` stores the selected system and inbox folders in `.pi-vault/config.yaml`. All other configuration, norms, proposals, reports, indexes, and state remain under the configured system folder.

Reason: Different vaults use different folder conventions, while unattended runs need deterministic paths and must not guess when onboarding has not occurred.

Implications:

- Interactive first launch confirms or creates both folders.
- Noninteractive product commands fail with an actionable error when bootstrap configuration is missing.
- Paths must be vault-relative, remain inside the vault, and keep system and inbox folders distinct.
- `00 System` and `01 Inbox` are defaults and examples, not runtime constants.

## 2026-06-20: Approved Proposals May Create Folders And Move Notes

Decision: Whole-vault organization may use validated `create_directory` and `move_note` proposal operations. Renames are represented as moves with a new basename; automatic deletion remains prohibited.

Reason: Full organization requires physical placement changes, but those changes need the same proposal, review, backup, report, and rollback boundaries as metadata edits.

Implications:

- Preflight rejects protected paths, missing parents, collisions, duplicate targets, and ambiguous inbound wikilinks before mutation.
- Approved moves update unambiguous inbound wikilinks and preserve backups.
- Scheduled auto-approval requires `automation_safe: true`; ambiguous or warning-bearing moves remain pending.

## 2026-06-21: Cross-Product MCP Handoffs Are Deterministic And Pending-Only

Decision: pi-vault and pi-forge communicate through deterministic local stdio MCP workers. pi-forge artifacts may create validated pending `artifact-import` proposals, but MCP tools may not approve or apply them.

Reason: Both interactive products share one local model, and external artifact ingestion must preserve pi-vault's proposal/review/apply boundary.

Implications:

- MCP workers never launch either interactive harness, another agent, or a model request.
- pi-vault owns results it requested from pi-forge and submits them through its local tool; the reverse MCP bridge is only for interactive pi-forge handoff.
- Version 1 accepts UTF-8 Markdown and text only, embeds content and SHA-256 provenance in the proposal, and adds no note frontmatter properties.
- `pi-vault-mcp` exposes only `vault_status` and `vault_submit_artifact`; approval, apply, undo, arbitrary engine commands, and shell execution stay unavailable.

## 2026-06-24: Startup Resumes Vault Context And Schema Authority Comes From The Norms Lock

Decision: Normal interactive launches resume the latest vault-local session and trigger a read-only startup assessment. The bundled schema and templates are provisional until captured by a current `norms-lock.json`; a current lock is exact authority, while drift blocks broad processing until review and re-locking.

Reason: A returning model should recover prior context and current vault state without waiting for a generic first prompt, while a new vault must not mistake repository defaults for user-approved organization rules.

Implications:

- Explicit session flags override automatic continuation.
- Startup may report and offer work but cannot authorize inbox processing, proposal application, or other mutations.
- First-launch sessions stay vault-local and migrate from bootstrap storage after initialization.
- Recommendations based on observed vault practice remain proposal-first and should preserve the intended purpose of the approved schema.

## 2026-06-24: New Vaults Are Dashboard-First And Inbox Sorting Is Confidence-Gated

Decision: New vaults default to `00 Inbox`, `01 Dashboards`, purpose-based content folders, and `99 System`. Dashboards are the primary navigation layer; folders are secondary storage. Existing vaults migrate only through reviewed proposals.

Reason: The normal user workflow is capture into Inbox, automatic bounded organization, and navigation through property-driven dashboards without exposing infrastructure as a primary folder.

Implications:

- Dashboard and content paths are stored in `.pi-vault/config.yaml` and validated as vault-relative layout paths.
- Dashboard regeneration replaces only marked generated sections and preserves curated Markdown.
- Person notes use Contacts or Authors as `parent`; Contacts wins physical placement for dual-role people and Authors remains a related view.
- Safe unattended moves require a current norms lock plus completed warning-free model stages above the confidence threshold.
- Ambiguous routes, missing metadata, collisions, and existing-vault restructuring remain proposal-first.

## 2026-06-26: Embeddings Power Retrieval And Ranking, Never Authority

Decision: Embeddings (Qwen3-Embedding-0.6B at the configured `/v1/embeddings` endpoint) are used only for whole-vault similarity tasks: related-note discovery and semantic search now, with near-duplicate detection, inbox-routing pre-ranking, and content clustering as a phased roadmap. They are disabled by default and never decide constrained-vocabulary values or merge identities on their own.

Reason: The single-note LLM stages cannot see the rest of the vault, so they cannot populate real cross-note `related` links or rank notes by meaning. Similarity is exactly what embeddings are good at, while type/property classification and people identity remain reasoning or rule problems where embeddings add risk, not capability.

Implications:

- The embedding index is derived state: a rebuildable JSON cache keyed by note path and invalidated by the scanner's content hash, stored under the retrieval folder and git-ignored (matching the reserved `retrieval/embedding*/`, `retrieval/vector*/`, and `*.sqlite` patterns).
- Similarity is computed in a mean-centered space (the corpus mean embedding is stored in the index and subtracted before ranking) to counter the model's high baseline cosine; centering activates only above a minimum corpus size and falls back to raw cosine for tiny vaults. Defaults were calibrated against the Memex test vault.
- No new runtime dependency: requests use `urllib` and similarity is pure-Python cosine; no vector database or ANN library at vault scale.
- `propose-related-links` is append-only and proposal-first; it never removes links and applies only through `review-proposals`. `vault-search` is read-only.
- The full plan and deferred phases live in `docs/architecture/embeddings-roadmap.md`.
