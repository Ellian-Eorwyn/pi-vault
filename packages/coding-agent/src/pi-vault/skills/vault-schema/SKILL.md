---
name: vault-schema
description: Discuss, plan, or revise a pi-vault schema and organization norms, including defining brand-new note types. Use when the user wants to improve the schema, add note types, properties, controlled values, templates, folder rules, tags, links, indexes, dashboards, or automation policy.
---

# Vault Schema

The canonical schema note `<system folder>/0.00 Vault Schema.md` is the single, human-editable source of truth for the vault's structure: properties, controlled values, definitions, topic hubs, folder structure, and the read-only reference rules. The user edits it directly. `vault_schema_sync` ingests their edits into `schema.json` (the machine mirror): controlled values, definitions, properties, and hubs sync directly (a value still used by notes is never dropped); Folder Structure edits become a pending folder-change proposal. Run `vault_schema_sync` first whenever `vault_status` reports `schema_note.changed`. Use `vault_schema_propose` (below) only for agent-authored deltas the user asked you to compose, not to bypass their note.

1. Read the vault purpose, current conventions, schema (canonical note + `schema.json`), templates, and norms-lock status.
   - `provisional`: defaults are discussion aids only; infer recommendations from the vault and ask before canonicalizing them.
   - `locked`: follow the locked schema and norms exactly.
   - `drifted`: treat the lock snapshot as authoritative and block broad processing until changes are reviewed and re-locked.
2. Hold a real conversation first: surface what the user wants to improve, weigh options against the *current* schema and the vault's actual contents, and recommend a concrete change set before generating anything. Prefer links, note names, or views over new metadata; add a property only when it powers durable retrieval, filtering, sorting, grouping, or display.
3. Clarify ambiguous preferences before generating changes.
4. Compose the change set through `vault_schema_propose` so deltas are built deterministically, not by hand-writing `schema.json`:
   - New controlled value (`domain`, `source_kind`, `capture_type`): `operation: "property"` with `property` + `value`. `status` and note `type` are not edited this way.
   - New note type: `operation: "note-type"` with `name` + `description` + `folder` (see "Defining a new note type").
   - Templates and hubs: `operation: "template"` (with `noteType`) and `operation: "topic-hubs"`. Indexes use `vault_organize_propose` `operation: "index"`.
5. Schema changes are never unattended safe approvals. Validate the proposal with `vault_review_apply` `operation: "review"`, obtain explicit approval, apply deterministically (`operation: "apply-approved"`), rewrite the norms lock (`vault_maintain` `operation: "write-norms-lock"`), and revalidate representative notes and Bases.

A deterministic guard checks every `schema.json` write: it must stay valid JSON, keep all built-in note types and controlled values, and stay internally consistent. The model proposes; this guard plus review keep the canon safe. Run all inference through the vault's configured pi/engine LLM backend only.

## Defining a new note type

Note types are data-driven: once a type is in `schema.json` (with its on-disk template), classification, validation, routing, and template application accept it immediately.

1. Talk through what the type captures and where its notes should live; draft the template's `##` sections from that description (these sections are the type's "shape").
2. Run `vault_schema_propose` `operation: "note-type"` with the chosen slug, description, and preferred folder. The proposal writes the schema delta, the `note-types/<slug>.md` template, and creates the folder.
3. Refine the generated template body if needed, dry-run review, get approval, apply, and re-lock norms. Then reclassify or reconcile notes that should adopt the new type.

## Topic hubs (organizational scheme)

Specific topics (e.g. Therapy, Journaling, a project) are not property values — they are approved **topic hubs**: navigation notes that other notes point to through `parent`. The hub registry lives in the schema (`schema.json` `topic_hubs`, rendered in the canonical schema note `<system folder>/0.00 Vault Schema.md`) and is the controlled vocabulary for `parent`.

- Surface candidate hubs from the vault's own content with `vault_schema_propose` `operation: "topic-hubs"` (one domain at a time), review them with the user, approve only the useful ones, then re-lock norms.
- Treat folders as a categorization signal, not a dependency: dashboards filter on `parent`, so notes can be re-foldered freely.
- Treat dashboards as the primary user-facing structure. Start planning from Home -> Domains -> domain dashboards -> project/topic dashboards -> notes, with parallel Projects, People, Sources, and Vault maintenance branches; adapt or omit branches based on the vault's approved values and purpose.
- Build each dashboard from curated Markdown orientation and links plus generated Bases filtered by approved sparse properties. Preserve curated sections during regeneration and allow notes to appear in multiple relevant views.

Preserve the approved property order and existing user-authored content. Recommendations may evolve the schema when they remain consistent with its purpose, but they must stay pending until approved, applied, and re-locked. Do not silently expand controlled vocabularies or invent hubs outside the approved registry.
