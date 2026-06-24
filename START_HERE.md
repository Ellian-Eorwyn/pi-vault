# Start Here

This repo is **pi-vault**: an Obsidian vault agent built on the pi harness. pi is the
primary interface — you launch `pi-vault` at a vault root, the agent loads the `vault-*`
skills and the `vault_status` / `vault_manage` tools on startup, and those drive a
deterministic Python engine (`vault_agent`) underneath. The Python CLI is the engine, not
the front door.

Do not rely on chat memory. The project folder is the source of truth.

## Architecture references

- `docs/architecture/Obsidian Vault Management and Retrieval Agent.md`
- `docs/architecture/Obsidian Vault Agent- Memory Layer Implementation Specification.md`

## Session Startup Protocol

Read these files in this order:

1. `PROJECT_STATUS.md`
2. `NEXT_ACTIONS.md`
3. `DECISIONS.md`
4. `PROJECT_PLAN.md` only as needed
5. The architecture specs in `docs/architecture/` only when deeper context is required

Startup checklist:

- [ ] Confirm the current focus from `PROJECT_STATUS.md`.
- [ ] Pick the next unchecked task from `NEXT_ACTIONS.md`.
- [ ] Check `DECISIONS.md` before changing architecture.
- [ ] Review relevant acceptance criteria in `PROJECT_PLAN.md`.
- [ ] Prefer the smallest verifiable change that advances the next task.
- [ ] Use dry-run behavior before any change modifies vault files.

## How pi-vault is wired

- The pi extension lives in `packages/coding-agent/src/pi-vault/`. `extension.ts` registers
  the `vault_status` / `vault_manage` tools, exposes the `skills/` directory through the
  harness `resources_discover` event, injects vault context into the system prompt, resumes
  the latest vault-local session, and triggers a read-only startup assessment.
- The deterministic engine lives in `vault-manager/vault_agent/` (Python). pi drives it
  through the `vault_manage` tool and the `pi-vault vault <command>` standalone CLI; the
  build bundles the engine and skills into `dist/`.
- The seven skills (`vault-onboarding`, `vault-retrieval`, `vault-inbox`, `vault-schema`,
  `vault-organization`, `vault-review`, `vault-recovery`) are the routing layer the agent
  uses; each one drives the corresponding engine commands.

## Operating Rules

- Drive the vault through pi's skills and the `vault_status` / `vault_manage` tools first;
  reach for raw `vault-agent` / `pi-vault vault …` commands as the engine layer beneath.
- Avoid re-planning the entire project unless the user asks.
- Continue from the project-control files if they exist.
- Prefer small, verifiable changes.
- Never mark a task complete without evidence (a created file, command output, passing
  test, validated schema, or successful dry-run).
- Record blockers clearly instead of guessing.
- Avoid destructive edits to user-authored vault notes. Never silently rewrite, delete,
  rename, or move user-authored notes.
- Preserve local-first, deterministic, inspectable design principles.
- Keep LLM work bounded to classification, summarization, extraction, or structured
  proposals; let deterministic engine code validate and apply file mutations.
- Send local LLM requests serially: one prompt at a time, then wait for completion before
  the next request.
- Keep canonical project state in files, not chat history.
- Treat a missing norms lock as provisional onboarding state, a current lock as exact
  authority, and a drifted lock as a blocker for broad processing.

## Local LLM Monitoring

When the vault has an openai-compatible local backend enabled, pi configures and drives it
through the engine. Send one prompt at a time and monitor the backend at `http://llms:8077/`:

1. Click `Logs`.
2. Select `Backend MoE`.
3. Click `Stream`.
4. Confirm only one `slot id 0` task is active at a time, and wait for `release` plus
   `all slots are idle` before the next prompt.

If a model returns non-JSON or thinking text, record it, fall back deterministically where
safe, and improve the prompt/parser/tests before widening the batch.

## Implementation Order Preference

Unless the source specs or user say otherwise, build deterministic foundations first:

1. Folder structure
2. Schemas
3. Manifest and scanner
4. Validation
5. Dry-run commands
6. Logging
7. Tests
8. Deterministic file updates
9. Retrieval summaries and indexes
10. LLM-supported classification and summarization
11. User-guided template, property, and value management
12. Scheduled or automated workflows

## Vault Protection Rules

Any code that modifies vault notes must have:

- Dry-run mode
- Clear logging
- Validation
- Backup or rollback strategy
- Tests where practical
- Explicit file targeting

No script should silently rewrite user-authored notes.

## Session Shutdown Protocol

Before ending a completed work session, update:

- `PROJECT_STATUS.md`
- `NEXT_ACTIONS.md`
- `vault-manager/CHANGELOG.md` (engine) and/or `packages/coding-agent/CHANGELOG.md` (harness)
- Relevant checkboxes in `PROJECT_PLAN.md`
- `DECISIONS.md`, if any design decision was made

Do not mark tasks complete unless there is concrete evidence: a created file, modified
file, command output, passing test, validated schema, or successful dry-run.
