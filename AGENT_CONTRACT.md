# Agent Contract

This document defines the operating contract for working in a vault managed by pi-vault. pi is the primary driver: launch `pi-vault` at the vault root and the agent loads the `vault-*` skills and the `vault_status` / `vault_manage` tools, which drive the `vault-agent` engine underneath. The same contract still applies to any other runner (a scheduler, a cron job, or another agent framework), but pi is the default. Lead with the skills and tools; the raw `vault-agent` / `pi-vault vault …` commands shown below are the engine layer they call.

## Source Of Truth

- Bootstrap paths live in `.pi-vault/config.yaml`; examples below use the defaults `00 System` and `01 Inbox`.
- Canonical machine state lives under the configured system folder at `0.01 agent/`.
- Human-editable schema and templates live under the configured system folder at `0.02 templates/`.
- Ordinary notes may live anywhere except the configured system folder; folder placement is advisory outside the configured system and inbox folders.
- Managed frontmatter is sparse: `type`, `status`, `domain`, `parent`, `related`, `cover`, `source_kind`, and `capture_type`.

## Startup Sequence

1. On launch pi loads the `vault-*` skills and the `vault_status` / `vault_manage` tools and injects vault context into the system prompt; start there.
2. Read `00 System/0.01 agent/AGENT_HANDOFF.md` and `00 System/0.01 agent/AGENT_CONTRACT.md` if present.
3. Check health with the `vault_status` tool (engine: `vault-agent --vault-root <vault> status` and `vault-agent --vault-root <vault> version status`).
4. Read `00 System/0.01 agent/norms-lock.json` if present. If it is missing before broad processing, run `vault-agent --vault-root <vault> norms-lock --write` after confirming schema/templates are the intended defaults.
5. Run `vault-agent --vault-root <vault> organization-readiness --json` before any broad organization pass.
6. Consult generated retrieval files before opening many notes:
   - `00 System/0.01 agent/retrieval/01 vault-map.md`
   - `00 System/0.01 agent/retrieval/02 note-catalog.md`
   - `00 System/0.01 agent/retrieval/03 property-index.md`
   - `00 System/0.01 agent/retrieval/04 summary-brief.md`

## User Request Routing

Each request routes to a pi skill, which drives the engine commands beneath it:

- "Onboard / initialize this vault" → **vault-onboarding** skill: bootstrap `.pi-vault/config.yaml`, scan existing conventions, plan norms with the user (engine: `init`, `scan`, `validate`).
- "Find / retrieve notes" → **vault-retrieval** skill: read the generated vault map, catalog, property index, and summary brief (engine: `status`, retrieval files).
- "Organize this vault" → **vault-organization** skill: lock norms first, run readiness, then bounded stage-scoped passes with reports (engine: `norms-lock`, `organization-readiness --json`, `autonomous-run`, `organize-vault-pass`).
- "Process the inbox" → **vault-inbox** skill: bounded, safe inbox maintenance (engine: `autonomous-run --apply-safe`, `process-inbox`, `rebuild-retrieval`).
- "Change canonical properties / plan schema / templates" → **vault-schema** skill: update schema, templates, validators, and docs together, then validate (engine: `propose-property`, `propose-template`, `validate`).
- "Build an index for a type/project/topic" → **vault-schema** / **vault-organization**: create or update an `index` note using sparse properties, Bases, links, and retrieval files; do not add new YAML fields unless the user approves a schema change (engine: `propose-index`).
- "Build a hierarchy of Bases" → **vault-organization** skill: generate pending domain and parent/project dashboards with embedded Bases; keep coverage prose in Markdown dashboard bodies, not frontmatter (engine: `propose-base-hierarchy`).
- "Organize one project/folder" → **vault-organization** skill: generate a pending proposal with sparse metadata cleanup and a dashboard; keep mutation inside the target folder plus `00 System` review/log/backup files (engine: `propose-folder-organization`).
- "What can be done here?" → **vault-review** skill: list the machine-readable queue of transcript cleanup, people extraction, and categorization actions (engine: `action-plan --json`).
- "Run queued maintenance" → **vault-inbox** / **vault-organization**: generate pending action proposals; for fuzzy categorization use `--use-llm --llm-limit 1 --max-items 1` first, then increase only after review (engine: `propose-action-queue`).
- "Extract people" → **vault-organization** skill: keep sparse person frontmatter and put relationship details in the note body. Treat author and `Key thinkers` lists as referenced people; treat meeting, call, speaker, and direct interaction contexts as direct contacts with contact-detail scaffolding.
- "Clean up notes" → **vault-inbox** / **vault-organization**: prefer `autonomous-run`, `reconcile`, `propose-cleanup-queue`, `process-inbox`, `process-vault`, and `organize-vault-pass` in small batches with backups.
- "Run recurring maintenance" → schedule pi (or a scheduler around `pi-vault vault maintain` / `hermes-run`) with bounded `--max-notes`.
- "Inspect / approve / apply a change" → **vault-review** skill via the `vault_manage` tool: prefer the `propose-*` generators, otherwise write proposal JSON under `00 System/0.01 agent/review/proposals/`, run `review-proposals --dry-run`, optionally `review-proposals --agent-review --approve-safe`, then `review-proposals --apply-approved`.
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

1. Run `scan` or rely on the generator's fresh scan.
2. Run `vault-agent --vault-root <vault> propose-base-hierarchy --dry-run`.
3. If the preview is acceptable, run `vault-agent --vault-root <vault> propose-base-hierarchy`.
4. Review `base-hierarchy.json` and `proposed-changes.md`; edit wording or reject the proposal if the generated coverage summaries are not useful.
5. Approve and apply only through `review-proposals --apply-approved`.

The generator writes dashboard notes with embedded Bases. It does not change note metadata, create new schema fields, move notes, or treat blank/invalid domains as real domains.

## Locked Norms And Organization Reports

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

The pass records the `norms_lock_hash` in `processing-state.json` and writes Markdown/JSON reports under `00 System/0.01 agent/reports/`. For LLM-backed batches, pass one explicit semantic stage such as `--stage classify-type` or `--stage property-values`; the command prompts queue item 1, validates/records the result, then prompts queue item 2. Warning-bearing or near-threshold valid model output is persisted under `00 System/0.01 agent/review/model-blocked-proposals.*`; inspect it with `review-model-blocks --dry-run`, convert safe items with `review-model-blocks --approve-safe`, then apply only through `review-proposals`. If schema, templates, or legacy alias rules change, notes processed under an older lock are considered stale and should be revisited in bounded passes.

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
