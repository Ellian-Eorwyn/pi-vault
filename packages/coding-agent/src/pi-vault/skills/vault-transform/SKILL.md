---
name: vault-transform
description: Drive the full end-to-end transformation of a pi-vault Obsidian vault from unorganized to beautifully structured. Use when the user wants to organize, set up, or overhaul their whole vault — establish a schema, build dashboards, organize folders, assign properties and types, route the inbox, and clean up — rather than a single bounded task.
---

# Vault Transform

This is the orchestration playbook for taking a vault from messy to beautiful. It sequences
the per-domain skills and the typed `vault_*` tools into one reviewed, checkpointed pipeline.
Everything stays proposal-first, bounded, and git-backed: you generate proposals, **stop and
let the user review**, then apply only approved work. Never run the whole pipeline
unattended.

## Operating rules

- Work through the phases in order. Do not start a mutating phase until the prior phase's
  proposals are reviewed and applied (or explicitly skipped).
- After every `vault_*_propose` / `vault_process_notes` call, summarize what was proposed and
  **gate on the user** before `vault_review_apply` `operation: "apply-approved"`.
- Keep batches small (`maxNotes`) until review queues are clean; broad `vault_process_notes`
  runs require `maxNotes`. Raise batch size only after a clean review.
- Treat `vault_status` / `vault_readiness` as read-only context, never as approval to mutate.
- One semantic `stage` per LLM processing run; let the engine sequence stages across runs.

## Phases

1. **Assess.** Run `vault_status` and `vault_readiness` (`report: "readiness"`). Read the
   vault purpose/conventions from the injected context. Report current health, note count,
   schema state (provisional / locked / drifted), and inbox backlog. Propose a plan and get
   the user's goals for the vault before changing anything.

2. **Initialize (only if needed).** If there is no `.pi-vault/config.yaml`, use the
   **vault-onboarding** skill to choose system/inbox folders and scaffold the vault, then
   `vault_maintain` `operation: "scan"`.

3. **Schema.** Use the **vault-schema** skill to talk through the schema with the user, then
   author it through `vault_schema_propose` (`property`, `note-type`, `template`,
   `topic-hubs`, or `schema-conversation`). Review and apply. Lock it with `vault_maintain`
   `operation: "write-norms-lock"`. **Checkpoint:** a current norms lock must exist before any
   broad organization — `vault_readiness` should stop reporting `drifted`.

4. **Dashboards.** Generate the dashboard-first layer with `vault_organize_propose`
   (`base-hierarchy`, and `vault-layout` for migrating an existing vault). Dashboards are the
   primary navigation layer; review the generated Bases and coverage prose with the user
   before applying.

5. **Folder organization.** For each meaningful area, `vault_organize_propose`
   `operation: "folder-organization"` (scoped by `folder`, with `project`/`domain`). Review
   and apply per folder. Notes may appear in multiple dashboards without being moved or
   duplicated.

6. **Properties, types, hubs, folders.** Run bounded semantic passes with
   `vault_process_notes` (`scope: "vault"` or `"organize-pass"`, `useLlm: true`), one `stage`
   at a time: `classify-type` → `property-values` → `assign-hub` → `assign-folder` →
   `summary`. Small `maxNotes` first; review the stage proposals (`vault_review_apply`
   `operation: "review"`, and `review-blocks` for blocked model output) before applying.

7. **Inbox.** Use the **vault-inbox** skill: bounded `vault_process_notes` `scope: "inbox"`
   classification, then `vault_organize_propose` `operation: "inbox-sort"` (`safeOnly: true`)
   for deterministic destinations. Apply only current, warning-free, high-confidence routes.

8. **Cleanup.** `vault_organize_propose` `operation: "cleanup-queue"` for frontmatter
   normalization, and `vault_content_propose` `operation: "people"` to build Contacts/Authors.
   Review and apply.

9. **Finalize.** `vault_retrieval` `operation: "rebuild-retrieval"`, then `vault_readiness`
   `report: "obsidian"` and a validation pass. Report the run IDs, changed files, remaining
   pending proposals, and the `vault_recovery` undo path for each applied run.

## Recovery

If any applied phase looks wrong, stop and use the **vault-recovery** skill / `vault_recovery`
to undo the specific run before continuing.
