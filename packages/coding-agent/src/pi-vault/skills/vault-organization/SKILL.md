---
name: vault-organization
description: Plan and execute bounded organization of a pi-vault managed Obsidian vault. Use for whole-vault cleanup, folder redesign, metadata normalization, moves, renames, links, indexes, dashboards, or organization from scratch.
---

# Vault Organization

1. Read vault-local purpose and conventions, then run status and organization readiness.
2. Stop if norms are missing or stale; complete onboarding or schema review first.
3. Present a concise organization plan before proposing broad changes.
4. Treat dashboards as the vault's primary navigation layer. Keep folders shallow and durable; use wikilinks for relationships, sparse properties for views, and Markdown dashboards with embedded Bases for navigation.
5. Establish the organizational scheme before dashboards: surface topic hubs from the notes with `vault_schema_propose` `operation: "topic-hubs"`, get them approved, then assign each note to an approved hub with `vault_process_notes` `scope: "organize-pass"`, `stage: "assign-hub"` (which sets `parent`). Hubs are the controlled vocabulary for `parent`; never invent one.
6. Use the vault's configured content roles, which may have been customized during onboarding. The dashboard-first default is `00 Inbox`, `01 Dashboards`, Contacts/Authors under `02 People`, `03 Organizations`, project folders under `04 Work`, purpose-based `05 Administrative` branches, flat `06 Thoughts`, `07 Sources`, and `99 System`. Derive dashboard branches from approved `domain`, `parent`, `type`, `status`, `source_kind`, and `capture_type` values; omit empty or irrelevant branches. Any `domain_folders` declared in `.pi-vault/config.yaml` are user-defined routable domains: a note whose `domain` matches the key belongs in that folder, and each has its own domain dashboard. Treat them like the built-in domain folders. When `routing.mode` is `custom`, the vault also has a `custom_folders` structure that the model sorts notes into during normal inbox processing (deterministic routing remains the fallback); honor those destinations and never move notes out of a folder the model has assigned without cause.
7. Generate proposals with `vault_organize_propose`: `vault-layout` (existing-vault migration), `base-hierarchy` (dashboard/Bases hierarchy), `folder-organization` (one folder + its dashboard), `cleanup-queue` (frontmatter normalization), `inbox-sort`, `index`, and `action-queue`. Combine curated Markdown orientation and child-dashboard links with generated Bases views. A note may appear in multiple relevant dashboards without duplication or relocation. Preserve curated sections when regenerating and prune empty generated sections. Never delete notes.
8. Dry-run the proposal review with `vault_review_apply` `operation: "review"`. Apply only approved or explicitly automation-safe bounded operations via `operation: "apply-approved"`.
9. Process semantic work serially with `vault_process_notes`, one note and one stage at a time; record each result before applying.
10. Rebuild retrieval (`vault_retrieval` `operation: "rebuild-retrieval"`), run validation and `vault_readiness` `report: "obsidian"`, then report changed files, unresolved review items, run ID, and undo command.
