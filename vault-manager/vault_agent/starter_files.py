"""Starter file contents for initialized vaults."""

from __future__ import annotations

import json
from pathlib import Path

from .dashboard_layout import dashboard_shell_contents
from .paths import DEFAULT_CONTENT_DIRS, DEFAULT_DASHBOARDS_DIR, VaultPaths
from .schema import (
    default_schema,
    default_schema_json,
    folder_norms_markdown,
    index_base_templates,
    property_values_markdown,
    schema_markdown,
    starter_templates,
    topic_hubs_markdown,
)
from .schema_defaults import vault_defaults_markdown
from .schema_note import SCHEMA_NOTE_NAME, render_schema_note

# Bundled Dashboard++ CSS snippet (TfTHacker, https://tfthacker.com), extended with
# callout and Bases card polish. Generated dashboards set `cssclasses: [dashboard]`,
# which activates this snippet in Reading view.
DASHBOARD_SNIPPET_CSS = """/*
  pi-vault dashboard snippet.
  Activates on notes with `cssclasses: [dashboard]` (set by generated dashboards).
  Based on TfTHacker's Dashboard++ (https://tfthacker.com), extended with callout
  and Bases card polish. Enable under Settings -> Appearance -> CSS snippets.
*/

.dashboard {
  --dashboard-accent: var(--interactive-accent);
}

.dashboard .markdown-preview-section,
.dashboard.markdown-source-view.mod-cm6 .cm-content {
  max-width: 100%;
}

.dashboard .inline-title,
.dashboard .markdown-preview-section .title {
  font-size: 2.1em !important;
  font-weight: 800;
  letter-spacing: 1px;
}

.dashboard h1,
.dashboard h2 {
  border-bottom: 2px solid var(--dashboard-accent);
  padding-bottom: 3px !important;
  margin-top: 1.4em;
}

.dashboard div > ul {
  list-style: none;
  display: flex;
  column-gap: 32px;
  row-gap: 8px;
  flex-flow: row wrap;
  padding-left: 0;
}

.dashboard div > ul > li {
  min-width: 230px;
  width: 22%;
  background: var(--background-secondary);
  border: 1px solid var(--background-modifier-border);
  border-radius: 10px;
  padding: 12px 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.dashboard div > ul > li > .list-bullet {
  display: none !important;
}

.dashboard div > ul > li > ul {
  display: block;
  margin-top: 6px;
}

.dashboard .callout[data-callout="abstract"] {
  border-radius: 12px;
  border-left-width: 6px;
  background: linear-gradient(
    90deg,
    rgba(var(--callout-color), 0.14),
    transparent
  );
}

.dashboard .bases-cards-container .bases-cards-item,
.dashboard .bases-card {
  border-radius: 10px;
  border: 1px solid var(--background-modifier-border);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
  transition: transform 0.08s ease, box-shadow 0.08s ease;
}

.dashboard .bases-cards-container .bases-cards-item:hover,
.dashboard .bases-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.16);
}

.dashboard .bases-table-container th {
  font-weight: 700;
}

@media (max-width: 900px) {
  .dashboard div > ul > li {
    width: 100%;
  }
}
"""

# Enables the bundled snippet for new vaults. init never overwrites an existing
# .obsidian/appearance.json, so vaults with their own appearance config are untouched
# (the user enables the snippet once under Appearance settings).
DASHBOARD_APPEARANCE_JSON = json.dumps({"enabledCssSnippets": ["dashboard"]}, indent=2) + "\n"


def starter_file_contents(
    *,
    system_dir: Path = Path("99 System"),
    inbox_dir: Path = Path("00 Inbox"),
    dashboards_dir: Path = DEFAULT_DASHBOARDS_DIR,
    content_dirs: dict[str, Path] | None = None,
    domain_folders: dict[str, Path] | None = None,
    custom_folders: tuple | list | None = None,
) -> dict[str, str]:
    extra_domains = list(domain_folders or {})
    contents = {
        "99 System/0.01 agent/config.yaml": """# vault-agent configuration
version: 1
auto_process:
  # Inbox and whole-vault processing are both bounded by these limits.
  # Folder placement is advisory outside 99 System and 00 Inbox.
  # Keep batches modest: the LLM runs on a single inference slot, so each note is
  # several serialized calls. Bounded passes with review checkpoints are the pattern.
  max_notes: 10
  max_runtime_minutes: 20
versioning:
  enabled: true
  auto_init: true
  separate_git_dir:
  auto_snapshot_before_write: true
  auto_snapshot_after_write: true
  dirty_before_write_policy: snapshot
  auto_push: false
  remote:
  branch:
  managed_gitignore: true
  commit_author_name:
  commit_author_email:
  lockfile:
  mass_edit_threshold_files: 25
  mass_edit_threshold_deletions: 5
  require_explicit_mass_edit_flag: true
  full_restore_requires_force: true
  ignored_paths: []
  protected_paths: []
llm:
  # Semantic stages (classify-type, property-values, summary, refine, people) run
  # through this single OpenAI-compatible backend. Enabled by default for a working
  # transform; set enabled: false to restrict the engine to deterministic work only.
  enabled: true
  provider: openai-compatible
  base_url: http://llms:8008
  model: code
  confidence_threshold: 0.75
  # A single inference slot serves one capable model, so calls are serialized and
  # the model is thorough; allow generous headroom before timing out.
  timeout_seconds: 180
  # Token-budget cap for note content sent to the model. The local backend has
  # a large context window; the character budget is estimated as
  # max_input_tokens * chars_per_token unless max_input_chars is explicitly set.
  # 64000 (~256k chars) covers any single note; raising it only grows per-call
  # KV-cache on the shared slot, so increase only for unusually large notes.
  max_input_tokens: 64000
  chars_per_token: 4
  # Qwen3-Embedding-0.6B (q8 KV cache). Chosen over the 4B after benchmarking
  # (vault-manager/evals): ties 4B on Recall@5, ~1.7x faster, ~1.8GB less VRAM;
  # the small ranking/precision gap is closed by the tuned thresholds below.
  embedding_base_url: http://llms:8011
  embedding_model: embed
embeddings:
  # Embedding-backed retrieval (related-note discovery, semantic search). Enabled by
  # default; deterministic runs are unaffected if the embedding backend is offline.
  enabled: true
  top_k: 5
  # Similarity is computed in a mean-centered space (the corpus mean is removed
  # to counter Qwen3's high baseline cosine), so 0.55 is a meaningful search floor.
  min_similarity: 0.55
  # Related-link proposals use a stricter floor than search so suggested frontmatter
  # links stay precise. Tuned from a threshold sweep on the eval gold set: 0.65 was
  # starving recall (~0.2); 0.55 maximises F1 for the 0.6B model. For extra
  # precision, run `propose-related-links --top-k 3`.
  related_min_similarity: 0.55
  # Near-duplicate candidates should be much tighter than ordinary neighbors.
  duplicate_min_similarity: 0.97
  # Keep local embedding requests modest when the GPU host is serving other models.
  batch_size: 32
  # Note body chars embedded per note. Each input must fit the embedding server's
  # physical batch (ubatch) token cap; the client truncates oversized inputs.
  excerpt_chars: 6000
review:
  model_warnings_block_writes: true
  warning_confidence_margin: 0.05
legacy_metadata:
  preserve_unknown_properties: true
  type_aliases:
    administrative: system
    draft: note
    inbox: note
    journal: daily
    plan: project
    reference: note
    reflection: note
  status_aliases:
    raw: active
    reference: active
  source_kind_aliases:
    academic paper: article
    paper: article
    web: website
    webpage: website
  property_aliases:
    area: domain
    areas: domain
    domains: domain
    publication_type: source_kind
    source: source_kind
    source_type: source_kind
    tags: related
    topic: related
    topics: related
""",
        "99 System/0.01 agent/vault-purpose.md": """# Vault Purpose

This file is durable, user-maintained policy. pi-vault may create it but must not overwrite it.

## Purpose

Describe what this vault is for and which information matters most.

## Retrieval Priorities

- Prefer precise, source-linked answers.

## Organization Preferences

- Plan broad changes with the user before applying them.

## Ignored Paths

- `.git`
- `.obsidian`
""",
        "99 System/0.01 agent/vault-conventions.md": """# Vault Conventions

This file is durable, user-maintained policy. Until `norms-lock.json` is written, the defaults below are a provisional starting point for onboarding rather than approved rules. After locking, changes require a reviewed proposal and a replacement lock.

## Default Starting Point

- Allowed note types: project, source, person, organization, meeting, task, note, index, daily, template, system
- Approved properties: type, status, domain, parent, related, cover, source_kind, capture_type
- Required properties: keep ordinary-note metadata sparse; require only fields needed by the note type and active views
- Property expansion: add a property only when it powers durable retrieval, filtering, sorting, grouping, or display
- Tags: use only for lightweight cross-cutting labels not represented by properties
- Links: use wikilinks for conceptual, source, parent, peer, decision, and dependency relationships
- Folders: use broad durable locations; prefer shallow branches unless the user approves deeper structure
- Navigation: treat nested dashboards as the primary user-facing structure; combine curated Markdown orientation and child-dashboard links with embedded Bases for live filtering and sorting
- Default dashboard topology: start from Home -> Domains -> domain dashboards -> project/topic dashboards -> notes, with parallel Projects, People, Sources, and Vault maintenance branches; adapt or omit branches based on approved properties and vault purpose
- Dashboard regeneration: preserve curated sections, allow notes in multiple relevant views, and prune empty generated sections

## Observed Inventory

Generated scans may refresh this section without changing the provisional or locked norms above.
""",
        "99 System/0.01 agent/AGENT_HANDOFF.md": """# Agent Handoff

This vault is managed via **pi-vault**. Launch `pi-vault` at this vault root and the agent loads the `vault-*` skills (onboarding, retrieval, inbox, schema, analysis, organization, people, review, recovery, and the `vault-transform` end-to-end playbook) and the typed `vault_*` tools (`vault_status`, `vault_readiness`, `vault_search`, `vault_retrieval`, `vault_schema_propose`, `vault_content_propose`, `vault_organize_propose`, `vault_process_notes`, `vault_maintain`, `vault_review_apply`, `vault_recovery`) on startup — use those first. They drive `vault-agent`, a local-first engine that keeps generated state under `99 System/0.01 agent/` and human-editable templates under `99 System/0.02 templates/`. The `vault-agent` commands below are the engine layer beneath the skills and tools.

## Operating Order

1. Check health with the `vault_status` tool (engine: `vault-agent --vault-root <vault> status`). It reports schema state, prior scan time, inbox changes, validation groups, pending proposals, and the latest organization report.
2. Preview risky work with `--dry-run`.
3. Treat missing-lock schema files as provisional onboarding defaults. Once the user approves the intended schema and templates, write `norms-lock`; follow a current lock exactly and stop broad processing when it is drifted.
4. Run `organization-readiness --json` before any broad organization pass.
5. Run `scan`, `validate`, `reconcile`, bounded `process-inbox` / `process-vault`, or `organize-vault-pass`, then `rebuild-retrieval`.
6. Read review files and organization reports before widening batch sizes.
7. For requested index/schema/template/cleanup/folder-organization/base-hierarchy changes, use the `propose-*` commands, then `review-proposals`.
8. For local LLM-backed tests, keep prompts stage-scoped and serialized; `organize-vault-pass --use-llm --max-notes N --stage <semantic-stage>` prompts one queued note stage at a time.

## Safety Rules

- Move or rename notes only through validated `move_note` proposals with collision checks, link rewrites, backups, and versioned rollback.
- Do not edit files in `99 System` except managed agent/template files.
- Treat `00 Inbox` as the capture queue; other folders are advisory, not semantic truth.
- Keep frontmatter sparse: `type`, `status`, `domain`, `parent`, `related`, `cover`, `source_kind`, and `capture_type`.
- Preserve unknown legacy metadata unless `legacy_metadata.preserve_unknown_properties` is explicitly `false`.
- LLMs propose structured JSON only; deterministic code validates and applies changes.
- Generated reports live under `99 System/0.01 agent/reports/`; use them to explain what was done and what remains.
- Startup assessment is read-only. It may offer to process inbox files or continue prior work, but it does not authorize mutations.

## Local LLM Behavior

The configured backend serves one capable model on a single inference slot, so semantic stages are processed one note/stage at a time by design — this is the expected operating mode, not a limitation. `organize-vault-pass --use-llm --max-notes N --stage <semantic-stage>` performs that sequencing automatically. Keep batches bounded with review checkpoints rather than large unattended runs. Vault-agent does not set a generation-token cap; leave generation limits to the configured backend. If output is non-JSON or thinking text, vault-agent extracts the first balanced JSON object, sends one repair prompt, and records structured failure details when repair fails. To debug a constrained single-slot backend, you can watch its server logs for a `slot id 0` task to release and idle before the next prompt.

## Recovery

Vault-agent uses local Git as a safety and audit layer for write commands. Before editing, run `vault-agent --vault-root <vault> version status`. After a write, inspect `vault-agent --vault-root <vault> version log`, then use `version changed-files <run-id>` or `version diff <run-id>` to inspect the change set. Restore one path with `version restore <run-id> --path <path>` or undo only the affected paths with `version undo-run <run-id>`.

Backups live in `99 System/0.01 agent/backups/`. Daily command logs live in `99 System/0.01 agent/logs/`. Version change-set metadata lives in `99 System/0.01 agent/versioning/`.
""",
        "99 System/0.01 agent/AGENT_CONTRACT.md": """# Agent Contract

pi is the primary driver of this vault: launch `pi-vault` and the agent loads the `vault-*` skills and the typed `vault_*` tools (`vault_status`, `vault_search`, `vault_retrieval`, `vault_schema_propose`, `vault_content_propose`, `vault_organize_propose`, `vault_process_notes`, `vault_maintain`, `vault_review_apply`, `vault_readiness`, `vault_recovery`), which drive the `vault-agent` engine. For a full messy-to-organized overhaul, the `vault-transform` skill sequences them end to end. These rules still apply to any other runner (a scheduler, a cron job, or another agent framework), but pi is the default front end.

## Source Of Truth

- Canonical machine state lives in `99 System/0.01 agent/`.
- Human-editable schema and templates live in `99 System/0.02 templates/`.
- Ordinary notes may live anywhere except `99 System`; folder placement is advisory outside `99 System` and `00 Inbox`.
- Managed frontmatter is sparse: `type`, `status`, `domain`, `parent`, `related`, `cover`, `source_kind`, and `capture_type`.
- Before the first norms lock, the bundled schema and templates are provisional defaults for discussion, not rules to impose on existing notes.

## Startup Sequence

1. Start from the `vault-*` skills and the injected vault context, then read this file and `AGENT_HANDOFF.md`.
2. Check health with the `vault_status` tool (engine: `vault-agent --vault-root <vault> status` and `vault-agent --vault-root <vault> version status`).
3. Interpret `vault_status` schema state: `provisional` means use defaults only to guide onboarding; `locked` means follow the schema exactly; `drifted` means stop broad processing until the differences are reviewed. Write `norms-lock.json` only after confirming schema/templates are intended.
4. Run `vault-agent --vault-root <vault> organization-readiness --json` before any broad organization pass.
5. Consult generated retrieval files before opening many notes:
   - `retrieval/01 vault-map.md`
   - `retrieval/02 note-catalog.md`
   - `retrieval/03 property-index.md`
   - `retrieval/04 summary-brief.md`

## User Request Routing

- Organize this vault: lock norms first, run `organization-readiness --json`, dry-run maintenance, cleanup proposals, then tiny bounded `organize-vault-pass` runs with reports.
- Process the inbox: classify one note/stage at a time, then use `propose-inbox-sort`; only safe-only proposals with current confidence and norms evidence may be approved unattended.
- Adopt the default layout: use `propose-vault-layout` and apply only after explicit review; never move existing notes automatically during migration.
- Change canonical properties: update schema, templates, validators, and docs together.
- Build an index for a type/project/topic: create or update an `index` note using sparse properties, Bases, links, and retrieval files.
- Organize one folder/project: use `propose-folder-organization` to generate a pending proposal with sparse metadata cleanup and a dashboard, then apply only through `review-proposals`.
- Build a hierarchy of Bases: use `propose-base-hierarchy` to generate pending domain and parent/project dashboards with embedded Bases. Keep coverage prose in dashboard Markdown, not frontmatter.
- What can be done here: use `action-plan --json` for transcript cleanup, people extraction, and categorization queues.
- Run queued maintenance: use `propose-action-queue` to generate pending action proposals.
- Extract people: keep sparse person frontmatter and put relationship details in the note body. Treat author and `Key thinkers` lists as referenced people; treat meeting, call, speaker, and direct interaction contexts as direct contacts with contact-detail scaffolding.
- Clean up notes: prefer `reconcile`, `propose-cleanup-queue`, `process-inbox`, `process-vault`, and `organize-vault-pass` in small batches.
- Run recurring maintenance: use `hermes-run` or a scheduler around the CLI with bounded `--max-notes`.
- Propose changes safely: use `propose-index`, `propose-property`, `propose-template`, `propose-cleanup`, `propose-base-hierarchy`, or `propose-folder-organization` when possible; otherwise write JSON proposals under `review/proposals/`, run `review-proposals --dry-run`, then apply only after status is changed to `approved`.

## Default Dashboard Navigation Model

Dashboards are the primary user-facing navigation layer, not optional reports. Use this adaptable starting topology:

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

This is a planning model, not a fixed taxonomy. Derive actual branches from the vault's purpose and approved `domain`, `parent`, `type`, `status`, `source_kind`, and `capture_type` values. Omit empty or irrelevant branches and propose intermediate dashboards when a populated branch becomes difficult to navigate.

Each dashboard should combine curated Markdown orientation, coverage prose, and child-dashboard links with generated embedded Bases. Preserve curated sections during regeneration. Notes may appear in multiple relevant dashboards without duplication or relocation. Surface missing metadata, orphaned notes, pending review, and other useful maintenance state through dashboards when appropriate.

Use `propose-inbox-sort` for bounded deterministic destination proposals and `propose-vault-layout` for existing-vault migration. Safe unattended inbox moves require a current norms lock plus completed warning-free `classify-type` and `property-values` stages above the configured confidence threshold.

## Versioning Protocol

Git is a local safety, audit, rollback, and change-management layer for agent operations. It is not an external sync backend, and vault-agent does not push by default.

Before edits, agents should inspect `vault-agent --vault-root <vault> version status`. Write commands create pre/post snapshots automatically when versioning is enabled. After edits, agents must report the run ID, post-commit hash, changed file count, and rollback command from `vault-agent --vault-root <vault> version log`.

Useful recovery commands:

```bash
vault-agent --vault-root <vault> version show <run-id>
vault-agent --vault-root <vault> version diff <run-id>
vault-agent --vault-root <vault> version changed-files <run-id>
vault-agent --vault-root <vault> version restore <run-id> --path "Notes/Example.md"
vault-agent --vault-root <vault> version undo-run <run-id>
```

Large batches may require `--mass-edit`. Full affected-path restore requires explicit `--force` through `version restore <run-id> --all --force`.

## Review And Approval Workflow

Use proposal JSON for schema, index, template, and cleanup requests. Proposal files live in `review/proposals/`.

Use generators for common requests:

```bash
vault-agent --vault-root <vault> propose-index --index-type type --value project
vault-agent --vault-root <vault> propose-index --index-type domain --value work
vault-agent --vault-root <vault> propose-property --property domain --value legal --description "Legal, compliance, and contracts."
vault-agent --vault-root <vault> propose-template --note-type source
vault-agent --vault-root <vault> propose-cleanup --note "03 Notes/Legacy.md" --remove-unknown
vault-agent --vault-root <vault> propose-cleanup-queue --max-items 10
vault-agent --vault-root <vault> propose-base-hierarchy
vault-agent --vault-root <vault> propose-action-queue --actions transcript,people,categorization --max-items 5
vault-agent --vault-root <vault> propose-folder-organization --folder "05 Projects/Example" --project "Example" --domain work --use-llm --checkpoint
```

Example:

```json
{
  "id": "source-index",
  "title": "Source Index",
  "kind": "index-note",
  "status": "pending",
  "operations": [
    {
      "op": "write_file",
      "path": "Indexes/Sources.md",
      "if_exists": "fail",
      "content": "---\\ntype: index\\nrelated: []\\n---\\n# Sources\\n"
    }
  ]
}
```

Supported kinds: `schema-change`, `index-note`, `template-change`, `cleanup`, `folder-organization`, `base-hierarchy`, `action-queue`.

Supported operations:

- `write_file`: write `.md`, `.json`, `.yaml`, `.yml`, or `.base` files.
- `update_frontmatter`: set sparse core properties and remove approved non-core legacy properties from Markdown notes.
- `organize_note`: apply approved sparse metadata cleanup and template body insertions to Markdown notes.

Validate:

```bash
vault-agent --vault-root <vault> review-proposals --dry-run
```

Apply approved proposals:

```bash
vault-agent --vault-root <vault> review-proposals --apply-approved
```

## Canonical Property Change Workflow

1. Prefer topic notes, `parent`, `related`, Bases, or body sections before adding schema.
2. If schema must change, update machine schema and human-readable schema files together.
3. Update templates and validators in the same change.
4. Run `vault-agent --vault-root <vault> validate --dry-run`.
5. Record the decision.

Agents should propose schema edits as `write_file` operations first. Do not directly mutate canonical schema files unless the proposal is approved and applied by `vault-agent review-proposals --apply-approved`.

## Index Note Workflow

1. Use retrieval files to identify candidate notes.
2. Prefer Bases-backed indexes when the request maps to `type`, `status`, `domain`, `parent`, `related`, or `cover`.
3. Use ordinary Markdown links for curated indexes.
4. Keep index notes typed as `index`.
5. Do not move source notes to make an index work.

Agents should propose index notes as `write_file` operations with `kind: index-note`. Use `if_exists: fail` for new indexes and `if_exists: overwrite` only when intentionally replacing an existing generated or curated index.

## Locked Norms And Organization Reports

Before an expensive vault pass, create a norms lock:

```bash
vault-agent --vault-root <vault> norms-lock --write
vault-agent --vault-root <vault> organization-readiness --json
```

Then run a bounded autonomous pass and Obsidian compatibility check:

```bash
vault-agent --vault-root <vault> autonomous-run --create-lock --apply-safe --stage classify-type --max-notes 2 --use-llm
vault-agent --vault-root <vault> review-model-blocks --dry-run
vault-agent --vault-root <vault> obsidian-check --json
vault-agent --vault-root <vault> validate --dry-run
vault-agent --vault-root <vault> rebuild-retrieval
```

The pass records the `norms_lock_hash` in `processing-state.json` and writes Markdown/JSON reports under `99 System/0.01 agent/reports/`. For LLM-backed batches, pass one explicit semantic stage such as `--stage classify-type` or `--stage property-values`; the command prompts queue item 1, validates/records the result, then prompts queue item 2. Warning-bearing or near-threshold valid model output is persisted under `99 System/0.01 agent/review/model-blocked-proposals.*`; inspect it with `review-model-blocks --dry-run`, convert safe items with `review-model-blocks --approve-safe`, then apply only through `review-proposals`. If schema, templates, or legacy alias rules change, notes processed under an older lock are considered stale and should be revisited in bounded passes.

## Scheduled Maintenance Workflow

Use bounded scheduled jobs and avoid overlapping runs:

```bash
vault-agent --vault-root <vault> autonomous-run --create-lock --apply-safe --max-notes 2
vault-agent --vault-root <ignored-for-hermes-run> hermes-run --hermes-root /path/to/vault-parent --max-notes 2 --apply-safe
```

When LLM processing is disabled, scheduled maintenance should only perform deterministic work: scan, validation, safe cleanup proposal handling, frontmatter shaping, and retrieval rebuild. Type classification, semantic property filling, and summary writing require an enabled provider or explicit proposal files. Use `obsidian-check --live-obsidian` when Obsidian is open and a render smoke test is needed.

## Local LLM Monitoring

The configured backend serves one capable model on a single inference slot, so LLM-backed work is serialized one note/stage at a time by design. `organize-vault-pass --use-llm --max-notes N --stage <semantic-stage>` performs that sequencing automatically inside one run; prefer bounded passes with review checkpoints over large unattended runs. Vault-agent does not set a generation-token cap; leave generation limits to the configured backend. When debugging a constrained single-slot server, you can watch its logs for a `slot id 0` task to release and idle before the next prompt.

If the model returns non-JSON or thinking text, record the failure, fall back deterministically only where safe, and add prompt/parser tests before widening the batch.

## Write Safety

- Always dry-run before broad changes.
- Keep batches small until review queues are clean.
- Never edit malformed notes automatically.
- Never delete notes. Move or rename notes only through approved `move_note` proposal operations.
- Preserve unknown legacy metadata unless explicitly configured otherwise.
- LLM output must be validated structured proposals, not direct file edits.
""",
        "99 System/0.01 agent/schema.json": default_schema_json(extra_domains),
        "99 System/0.01 agent/manifest.json": json.dumps(
            {"generated_by": "vault-agent", "notes": []}, indent=2, sort_keys=True
        )
        + "\n",
        "99 System/0.01 agent/state.json": json.dumps(
            {"generated_by": "vault-agent", "last_scan": None, "processed_notes": {}},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "99 System/0.01 agent/review/needs-review.md": "# Needs Review\n\n",
        "99 System/0.01 agent/review/proposed-values.md": "# Proposed Values\n\n",
        "99 System/0.01 agent/review/proposed-changes.md": "# Proposed Changes\n\nNo proposal files found.\n",
        "99 System/0.01 agent/review/processing-errors.md": "# Processing Errors\n\n",
        "99 System/0.01 agent/retrieval/00 retrieval-readme.md": """# Retrieval Instructions for Agents

Start with generated retrieval files before opening full notes.

1. `01 vault-map.md`
2. `02 note-catalog.md`
3. `03 property-index.md`
4. `04 summary-brief.md`

When embeddings are enabled, use the `vault_search` tool for read-only semantic
ranking. If the index is empty, use `vault_retrieval` `operation: "embed-index"` and
retry. To suggest note connections, use `vault_retrieval` `operation: "related-links"`
and apply only through proposal review (`vault_review_apply`).

Open full notes only after selecting likely candidates. Do not edit notes during retrieval.
""",
        "99 System/0.01 agent/retrieval/01 vault-map.md": "# Vault Map\n\nNot scanned yet.\n",
        "99 System/0.01 agent/retrieval/02 note-catalog.md": "# Note Catalog\n\nNot scanned yet.\n",
        "99 System/0.01 agent/retrieval/03 property-index.md": "# Property Index\n\nNot scanned yet.\n",
        "99 System/0.01 agent/retrieval/04 summary-brief.md": "# Summary Brief\n\nNot scanned yet.\n",
        "99 System/0.01 agent/retrieval/stale-summaries.md": "# Stale Summaries\n\n",
        "99 System/0.01 agent/retrieval/retrieval-log.md": "# Retrieval Log\n\n",
        f"99 System/{SCHEMA_NOTE_NAME}": render_schema_note(default_schema(extra_domains)),
        "99 System/0.02 templates/0.020 vault schema.md": schema_markdown(extra_domains),
        "99 System/0.02 templates/0.021 property values.md": property_values_markdown(extra_domains),
        "99 System/0.02 templates/0.022 folder norms.md": folder_norms_markdown(),
        "99 System/0.02 templates/0.023 topic hubs.md": topic_hubs_markdown(),
        "99 System/0.02 templates/0.024 vault defaults.md": vault_defaults_markdown(
            paths=VaultPaths(
                system_dir=system_dir,
                inbox_dir=inbox_dir,
                dashboards_dir=dashboards_dir,
                content_dirs=dict(content_dirs or DEFAULT_CONTENT_DIRS),
                domain_folders=dict(domain_folders or {}),
                custom_folders=tuple(custom_folders or ()),
            ),
            extra_domains=extra_domains,
        ),
        ".obsidian/snippets/dashboard.css": DASHBOARD_SNIPPET_CSS,
        ".obsidian/appearance.json": DASHBOARD_APPEARANCE_JSON,
    }
    contents.update(starter_templates())
    contents.update(index_base_templates())
    contents.update(
        dashboard_shell_contents(
            VaultPaths(
                system_dir=system_dir,
                inbox_dir=inbox_dir,
                dashboards_dir=dashboards_dir,
                content_dirs=dict(content_dirs or DEFAULT_CONTENT_DIRS),
                domain_folders=dict(domain_folders or {}),
                custom_folders=tuple(custom_folders or ()),
            )
        )
    )
    system_text = system_dir.as_posix()
    inbox_text = inbox_dir.as_posix()
    remapped: dict[str, str] = {}
    for path, content in contents.items():
        mapped_path = _remap_default_path(path, system_dir=system_dir, inbox_dir=inbox_dir)
        remapped[mapped_path] = content.replace("99 System", system_text).replace(
            "00 Inbox", inbox_text
        )
    return remapped


def _remap_default_path(path: str, *, system_dir: Path, inbox_dir: Path) -> str:
    relative = Path(path)
    if relative.is_relative_to(Path("99 System")):
        suffix = relative.relative_to(Path("99 System"))
        return (system_dir / suffix).as_posix()
    if relative.is_relative_to(Path("00 Inbox")):
        suffix = relative.relative_to(Path("00 Inbox"))
        return (inbox_dir / suffix).as_posix()
    return relative.as_posix()
