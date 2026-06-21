---
name: vault-organization
description: Plan and execute bounded organization of a pi-vault managed Obsidian vault. Use for whole-vault cleanup, folder redesign, metadata normalization, moves, renames, links, indexes, dashboards, or organization from scratch.
---

# Vault Organization

1. Read vault-local purpose and conventions, then run status and organization readiness.
2. Stop if norms are missing or stale; complete onboarding or schema review first.
3. Present a concise organization plan before proposing broad changes.
4. Keep folders shallow and durable; use wikilinks for relationships, sparse properties for views, and indexes or Bases for navigation.
5. Establish the organizational scheme before dashboards: surface topic hubs from the notes with `propose-topic-hubs`, get them approved, then assign each note to an approved hub with the `assign-hub` stage (which sets `parent`). Hubs are the controlled vocabulary for `parent`; never invent one.
6. Generate proposals for metadata, templates, directories, note moves or renames, links, indexes, and dashboards. Build domain dashboards from the approved hubs and prune empty sections. Never delete notes.
7. Dry-run the proposal review. Apply only approved or explicitly automation-safe bounded operations.
8. Process semantic work serially, one note and one stage at a time; record each result before applying.
9. Rebuild retrieval, run validation and Obsidian checks, then report changed files, unresolved review items, run ID, and undo command.
