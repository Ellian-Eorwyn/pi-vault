# Agent Contract

This document defines the operating contract for working in a vault managed by pi-vault. pi is the primary driver: launch `pi-vault` at the vault root and the agent loads the `vault-*` skills and the `vault_*` tools (`vault_status`, `vault_readiness`, `vault_search`, `vault_retrieval`, `vault_schema_propose`, `vault_content_propose`, `vault_maintain`, `vault_review_apply`, `vault_recovery`), which drive the `vault-agent` engine underneath. The same contract still applies to any other runner (a scheduler, a cron job, or another agent framework), but pi is the default. Lead with the skills and tools; the raw `vault-agent` / `pi-vault vault …` commands shown below are the engine layer they call.

## Source Of Truth

- Bootstrap paths live in `.pi-vault/config.yaml`; examples below use the defaults `99 System` and `00 Inbox`.
- Canonical machine state lives under the configured system folder at `0.01 agent/`.
- Interactive session transcripts and debug logs live under the configured system folder at `0.01 agent/`; they are never shared between vaults through the global pi-vault profile.
- Human-editable schema and templates live under the configured system folder at `0.02 templates/`.
- Ordinary notes may live anywhere except the configured system folder; folder placement is advisory outside the configured system and inbox folders.
- Managed frontmatter is sparse: `type`, `status`, `domain`, `parent`, `related`, `cover`, `source_kind`, and `capture_type`.

## Startup Sequence

1. On launch from the vault root or any descendant, pi-vault resolves the vault root, resumes the latest vault-local session unless explicitly overridden, loads the `vault-*` skills and the `vault_*` tools, and injects purpose, conventions, contract, schema, norms lock, template norms, and retrieval context into the system prompt; start there.
2. Treat the automatic startup assessment as read-only context. Summarize prior work, health, schema state, inbox changes, and pending review, then offer specific next actions without treating it as mutation approval.
3. Read `99 System/0.01 agent/AGENT_HANDOFF.md` and `99 System/0.01 agent/AGENT_CONTRACT.md` if present.
4. Check health with the `vault_status` tool (engine: `vault-agent --vault-root <vault> status` and `vault-agent --vault-root <vault> version status`).
5. Interpret schema state before processing: `provisional` means defaults are discussion aids only; `locked` means follow the current schema exactly; `drifted` blocks broad processing until review and re-locking.
6. Run `vault-agent --vault-root <vault> organization-readiness --json` before any broad organization pass.
7. Consult generated retrieval files before opening many notes:
   - `99 System/0.01 agent/retrieval/01 vault-map.md`
   - `99 System/0.01 agent/retrieval/02 note-catalog.md`
   - `99 System/0.01 agent/retrieval/03 property-index.md`
   - `99 System/0.01 agent/retrieval/04 summary-brief.md`
   - When embeddings are enabled, use the `vault_search` tool for read-only semantic ranking by meaning; build the index first with `vault_retrieval` `operation: "embed-index"` if it is empty.

## User Request Routing

Each request routes to a pi skill, which drives the engine commands beneath it:

- "Transform / organize my whole vault / set it up from scratch / make it beautiful" → **vault-transform** skill: the end-to-end playbook that sequences onboarding → schema → norms lock → dashboards → folder organization → property/type/hub passes → inbox → cleanup → retrieval rebuild → validation, with a review checkpoint between every mutating phase.
- "Onboard / initialize this vault" → **vault-onboarding** skill: bootstrap `.pi-vault/config.yaml`, scan existing conventions, plan norms with the user (engine: `init`, `scan`, `validate`).
- "Find / retrieve notes" → **vault-retrieval** skill: read the generated vault map, catalog, property index, and summary brief, and use semantic search when embeddings are enabled (tool: `vault_search`; engine: `vault-search`).
- "Suggest related links / connect related notes" → **vault-retrieval** / **vault-organization**: propose embedding-discovered `related` links append-only, then review and apply (tools: `vault_retrieval` `operation: "embed-index"` and `"related-links"`, then `vault_review_apply` `operation: "review"`; engine: `embed-index`, `propose-related-links`, `review-proposals`).
- "Organize this vault" → **vault-organization** skill: lock norms first, run readiness, then bounded stage-scoped passes with reports (tools: `vault_maintain` `operation: "write-norms-lock"`, `vault_readiness`, `vault_organize_propose`, `vault_process_notes`; engine: `norms-lock`, `organization-readiness --json`, `organize-vault-pass`).
- "Process the inbox" → **vault-inbox** skill: bounded classification followed by deterministic destination proposals; apply only current, warning-free, high-confidence routes automatically (tools: `vault_process_notes` `scope: "inbox"`, `vault_organize_propose` `operation: "inbox-sort"`; engine: `process-inbox`, `propose-inbox-sort`).
- "Adopt the default layout" → **vault-organization** skill: generate and review a dashboard-first migration without moving existing notes automatically (tool: `vault_organize_propose` `operation: "vault-layout"`; engine: `propose-vault-layout`).
- "Change canonical properties / plan schema / templates / discuss schema improvements" → **vault-schema** skill: talk through the change against the live vault, then update schema, templates, validators, and docs together and validate (tool: `vault_schema_propose` `operation: "property"|"template"`; engine: `propose-property`, `propose-template`, `validate`).
- "Define a new note type" → **vault-schema** skill: draft the type's template sections from what it captures, then add it data-drivenly so classification, routing, and template application accept it (tool: `vault_schema_propose` `operation: "note-type"`, then re-lock norms).
- "Extract people / build Contacts and Authors" → **vault-people** skill: detect people across notes, deduplicate against existing person notes, classify each into Contacts or Authors with the configured backend, and create person notes with backlinks (engine: `propose-people`).
- "Build an index for a type/project/topic" → **vault-schema** / **vault-organization**: create or update an `index` note using sparse properties, Bases, links, and retrieval files; do not add new YAML fields unless the user approves a schema change (engine: `propose-index`).
- "Build a hierarchy of Bases" → **vault-organization** skill: generate pending domain and parent/project dashboards with embedded Bases; keep coverage prose in Markdown dashboard bodies, not frontmatter (tool: `vault_organize_propose` `operation: "base-hierarchy"`; engine: `propose-base-hierarchy`).
- "Organize one project/folder" → **vault-organization** skill: generate a pending proposal with sparse metadata cleanup and a dashboard; keep mutation inside the target folder plus `99 System` review/log/backup files (tool: `vault_organize_propose` `operation: "folder-organization"`; engine: `propose-folder-organization`).
- "Analyze / refine this folder; clean up the notes themselves" → **vault-analysis** skill: read whole notes in one folder for context, apply schema-compliant defaults and renames, and refine note bodies for structure, skimmability, and Obsidian Markdown without changing wording or meaning, all through reviewable proposals (engine: `organize-vault-pass --folder`, `propose-folder-refinement`).
- "What can be done here?" → **vault-review** skill: list the machine-readable queue of transcript cleanup, people extraction, and categorization actions (engine: `action-plan --json`).
- "Run queued maintenance" → **vault-inbox** / **vault-organization**: generate pending action proposals; for fuzzy categorization use `--use-llm --llm-limit 1 --max-items 1` first, then increase only after review (engine: `propose-action-queue`).
- "Extract people" → **vault-organization** skill: keep sparse person frontmatter and put relationship details in the note body. Treat author and `Key thinkers` lists as referenced people; treat meeting, call, speaker, and direct interaction contexts as direct contacts with contact-detail scaffolding.
- "Clean up notes" → **vault-inbox** / **vault-organization**: prefer `autonomous-run`, `reconcile`, `propose-cleanup-queue`, `process-inbox`, `process-vault`, and `organize-vault-pass` in small batches with backups.
- "Run recurring maintenance" → schedule pi (or a scheduler around `pi-vault vault maintain` / `hermes-run`) with bounded `--max-notes`.
- "Inspect / approve / apply a change" → **vault-review** skill via the `vault_review_apply` tool: prefer the `propose-*` generators (`vault_schema_propose`, `vault_content_propose`, `vault_retrieval`), otherwise write proposal JSON under `99 System/0.01 agent/review/proposals/`, run `vault_review_apply` `operation: "review"` (engine `review-proposals --dry-run`), optionally `review-proposals --agent-review --approve-safe`, then `vault_review_apply` `operation: "apply-approved"`.
- "Undo / recover a change" → **vault-recovery** skill: inspect and roll back versioned runs (engine: `version status`, `version diff`, `version undo-run`).

## Versioning Protocol

Vault-agent treats Git as a local safety, audit, rollback, and change-management layer for agent operations. It is not an external sync system and does not push by default.

Before edits, check:

```bash
vault-agent --vault-root <vault> version status
```

Write commands automatically checkpoint before and after changes when versioning is enabled. After edits, report the run ID, post-commit hash, changed files, and rollback command from:

```bash
vault-agent --vault-root <vault> version log
vault-agent --vault-root <vault> version show <run-id>
vault-agent --vault-root <vault> version changed-files <run-id>
vault-agent --vault-root <vault> version diff <run-id>
```

Restore one path or undo only the affected paths from a run:

```bash
vault-agent --vault-root <vault> version restore <run-id> --path "Notes/Example.md"
vault-agent --vault-root <vault> version undo-run <run-id>
```

Large changes may require `--mass-edit`. Full affected-path restore requires `version restore <run-id> --all --force`.

## Review And Approval Workflow

Agents should not directly mutate notes for schema, index, template, or cleanup requests when the change can be represented as a proposal.

Use generators for common requests:

```bash
vault-agent --vault-root <vault> propose-index --index-type type --value project
vault-agent --vault-root <vault> propose-index --index-type domain --value work
vault-agent --vault-root <vault> propose-property --property domain --value legal --description "Legal, compliance, and contracts."
vault-agent --vault-root <vault> propose-template --note-type source
vault-agent --vault-root <vault> propose-cleanup --note "03 Notes/Legacy.md" --remove-unknown
vault-agent --vault-root <vault> propose-cleanup-queue --max-items 10
vault-agent --vault-root <vault> propose-base-hierarchy
vault-agent --vault-root <vault> propose-folder-organization --folder "05 Projects/Example" --project "Example" --domain work --use-llm --checkpoint
```

Example proposal:

```json
{
  "id": "source-index",
  "title": "Source Index",
  "kind": "index-note",
  "status": "pending",
  "summary": "Create a source index note.",
  "operations": [
    {
      "op": "write_file",
      "path": "Indexes/Sources.md",
      "if_exists": "fail",
      "content": "---\ntype: index\nrelated: []\n---\n# Sources\n"
    }
  ]
}
```

Supported proposal kinds are `schema-change`, `index-note`, `template-change`, `cleanup`, `folder-organization`, `base-hierarchy`, and `action-queue`.

Supported operations:

- `write_file`: writes `.md`, `.json`, `.yaml`, `.yml`, or `.base` files. Existing files require `if_exists: overwrite`.
- `update_frontmatter`: sets sparse core properties and removes approved non-core legacy properties from Markdown notes.
- `organize_note`: applies approved sparse metadata cleanup and template body insertions to Markdown notes.
- `create_directory`: creates an approved vault-relative directory outside the configured system folder.
- `move_note`: moves or renames an approved Markdown note and updates unambiguous inbound wikilinks. It cannot move notes into or out of the configured system folder.

Validate/render proposals:

```bash
vault-agent --vault-root <vault> review-proposals --dry-run
```

Apply approved proposals:

```bash
vault-agent --vault-root <vault> review-proposals --apply-approved
```

The apply step only applies proposals with `status: approved`; after success, it marks them `applied`.

## Canonical Property Change Workflow

1. Identify whether the request truly needs a schema change or can be represented with topic notes, `parent`, `related`, Bases, or body sections.
2. If a schema change is needed, update the machine schema and human-readable schema files together.
3. Update templates and validators in the same change.
4. Run `vault-agent --vault-root <vault> validate --dry-run`.
5. Run tests in the source repo when changing code.
6. Record the decision in the project or vault decision log.
7. Prefer the review proposal workflow over direct mutation when another agent will approve the change.

## Index Note Workflow

1. Use existing retrieval files to identify candidate notes.
2. Prefer Bases-backed indexes when the request maps to `type`, `status`, `domain`, `parent`, `related`, or `cover`.
3. Use ordinary Markdown links for curated indexes.
4. Keep index notes typed as `index`.
5. Do not move source notes to make an index work.
6. Prefer `kind: index-note` proposals for generated or requested index creation.

## Base Hierarchy Workflow

Dashboards are the primary user-facing navigation layer, not optional reports. Use this as an adaptable starting topology:

```text
00 Inbox
01 Dashboards
├── Home
├── Domains
├── Projects
├── People
├── Organizations
├── Sources
└── Vault Maintenance
02 People
├── 02.01 Contacts
└── 02.02 Authors
03 Organizations
04 Work
05 Administrative
├── 05.01 Health
├── 05.02 Home
├── 05.03 Finance
├── 05.04 Travel
└── 05.05 General
06 Thoughts
07 Sources
99 System
```

This is a planning model, not a fixed taxonomy. Derive actual branches from the vault's purpose and approved `domain`, `parent`, `type`, `status`, `source_kind`, and `capture_type` values. Omit empty or irrelevant branches and propose new intermediate dashboards when a populated branch becomes difficult to navigate.

Each dashboard should combine curated Markdown orientation, coverage prose, and child-dashboard links with generated embedded Bases. Preserve curated sections during regeneration. Notes may appear in multiple relevant dashboards without being duplicated or moved. Dashboard proposals should also surface missing metadata, orphaned notes, pending review, or other maintenance state when useful.

1. Run `scan` or rely on the generator's fresh scan.
2. Run `vault-agent --vault-root <vault> propose-base-hierarchy --dry-run`.
3. If the preview is acceptable, run `vault-agent --vault-root <vault> propose-base-hierarchy`.
4. Review `base-hierarchy.json` and `proposed-changes.md`; edit wording or reject the proposal if the generated coverage summaries are not useful.
5. Approve and apply only through `review-proposals --apply-approved`.

The generator writes dashboard notes with embedded Bases. It does not change note metadata, create new schema fields, move notes, or treat blank/invalid domains as real domains.

Use `propose-inbox-sort` for bounded deterministic destination proposals and `propose-vault-layout` for existing-vault migration. Safe unattended inbox moves require a current norms lock plus completed warning-free `classify-type` and `property-values` stages above the configured confidence threshold.

## Locked Norms And Organization Reports

Without `norms-lock.json`, the bundled schema and templates are only a default starting point for onboarding and must not be imposed on existing notes. A current lock is authoritative and must be followed exactly. If current files drift from the lock, keep the locked snapshot authoritative and block broad processing until the differences are reviewed. The model may recommend proposal-first changes based on observed vault practice when they preserve the intended purpose of the schema.

Before an expensive vault pass, create a norms lock:

```bash
vault-agent --vault-root <vault> norms-lock --write
vault-agent --vault-root <vault> organization-readiness --json
```

Then run a bounded autonomous pass and static Obsidian compatibility check:

```bash
vault-agent --vault-root <vault> autonomous-run --create-lock --apply-safe --stage classify-type --max-notes 2 --use-llm
vault-agent --vault-root <vault> review-model-blocks --dry-run
vault-agent --vault-root <vault> obsidian-check --json
vault-agent --vault-root <vault> validate --dry-run
vault-agent --vault-root <vault> rebuild-retrieval
```

The pass records the `norms_lock_hash` in `processing-state.json` and writes Markdown/JSON reports under `99 System/0.01 agent/reports/`. For LLM-backed batches, pass one explicit semantic stage such as `--stage classify-type` or `--stage property-values`; the command prompts queue item 1, validates/records the result, then prompts queue item 2. Warning-bearing or near-threshold valid model output is persisted under `99 System/0.01 agent/review/model-blocked-proposals.*`; inspect it with `review-model-blocks --dry-run`, convert safe items with `review-model-blocks --approve-safe`, then apply only through `review-proposals`. If schema, templates, or legacy alias rules change, notes processed under an older lock are considered stale and should be revisited in bounded passes.

## Scheduled Maintenance Workflow

For cron, launchd, Hermes, or any other scheduler, use a bounded command shape:

```bash
vault-agent --vault-root <vault> autonomous-run --create-lock --apply-safe --max-notes 2
vault-agent --vault-root <ignored-for-hermes-run> hermes-run --hermes-root /path/to/vault-parent --max-notes 2 --apply-safe
```

Schedulers should capture stdout/stderr and should not run overlapping jobs for the same vault. Autonomous runs may apply bounded safe non-schema proposals and should leave schema-change proposals pending.

When LLM processing is disabled, scheduled maintenance should only perform deterministic work: scan, validation, safe cleanup proposal handling, frontmatter shaping, and retrieval rebuild. Type classification, semantic property filling, and summary writing require an enabled provider or explicit proposal files.

After scheduled dashboard or metadata changes, run:

```bash
vault-agent --vault-root <vault> obsidian-check --json
```

Use `obsidian-check --live-obsidian` when Obsidian is open and a visual/render smoke test is needed.

## Model Provider Boundary

pi-vault performs all model inference through the user-configured pi/engine LLM
backend only — the provider set under `llm` in the vault-agent config (`provider`,
`base_url`, `model`). It does not call Claude, Codex, Gemini, or any third-party model
unless the user explicitly points the harness at that provider's API. Every
LLM-authored change (classification, property values, summaries, and note-body
refinement) is produced by that configured backend, returned as a validated
structured proposal, and applied by deterministic code — never by an outside model
and never as direct file edits.

Note types and controlled values are data-driven from `99 System/0.01 agent/schema.json`:
built-in types and values are always present, and approved additions (a new note type via
`propose-note-type`, or a new `domain`/`source_kind`/`capture_type` via `propose-property`)
extend them at runtime once applied and re-locked. A deterministic guard validates every
`schema.json` write before it is applied — it must stay valid JSON, keep every built-in note
type and controlled value, and remain internally consistent — so the model can extend the
canon but never corrupt or shrink it. People extraction (`propose-people`) creates
deduplicated `person` notes routed to Contacts or Authors with details drafted by the
configured backend strictly from existing mentions.

Note-body refinement (`propose-folder-refinement`, the **vault-analysis** skill) lets
the configured backend reformat a note's body for structure and Obsidian Markdown.
It must never change wording or meaning: a deterministic word-preservation guard
compares the prose word multiset before and after and rejects any rewrite that drops
or substitutes the author's words (allowed budgets are configurable under `refine` in
the config). Frontmatter is preserved byte-for-byte. The guard runs both when the
proposal is generated and again at apply time; blocked rewrites are reported with a
word-diff rather than applied.

## Local LLM Monitoring

When testing local LLM-backed behavior, use the configured vault provider and send one prompt at a time. Monitor `http://llms:8077/`: click Logs, select `Backend MoE`, click `Stream`, and watch for a single `slot id 0` task. Wait for `release` and `all slots are idle` before sending another prompt. `organize-vault-pass --use-llm --max-notes N --stage <semantic-stage>` performs that sequencing automatically inside one run. Vault-agent does not set a generation-token cap; leave generation limits to the configured backend.

If the model returns non-JSON or thinking text, the provider extracts the first balanced JSON object, sends one repair prompt, and records structured failure details if repair fails. Keep failures in processing state and organization reports, fall back deterministically only where safe, and add prompt/parser tests before widening the batch.

## Write Safety

- Always dry-run before broad changes.
- Keep batches small until review queues are clean.
- Never edit malformed notes automatically.
- Never delete notes automatically.
- Move or rename notes only through validated, explicitly approved `move_note` proposals. Scheduled auto-approval additionally requires `automation_safe: true`.
- Preserve unknown legacy metadata unless explicitly configured otherwise.
- LLM output must be validated structured proposals, not direct file edits.
- Refine note bodies only through `note-refinement` proposals; the word-preservation guard must pass, frontmatter stays byte-identical, and wording and meaning are never changed.
- Extend the schema only through reviewed proposals; the schema-change guard must pass, and built-in note types and controlled values are never dropped.
- Create person notes only through `people-extraction` proposals; never recreate an existing person, and ground all drafted details in the notes that mention them.
- Run all model inference through the configured pi/engine LLM backend; never route note content to a third-party model unless the user explicitly configured it.
