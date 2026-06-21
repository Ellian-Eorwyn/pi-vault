---
name: vault-schema
description: Plan or revise a pi-vault schema and organization norms. Use when the user asks to add note types, properties, controlled values, templates, folder rules, tags, links, indexes, dashboards, or automation policy.
---

# Vault Schema

1. Read the vault purpose, current conventions, schema, templates, and norms-lock status.
2. Prefer links, note names, or views over adding metadata. Add a property only when it powers durable retrieval, filtering, sorting, grouping, or display.
3. Clarify ambiguous preferences before generating changes.
4. Submit schema, template, and navigation changes as pending proposals. Schema changes are never unattended safe approvals.
5. Validate the proposal, obtain approval, apply deterministically, rewrite the norms lock, and revalidate representative notes and Bases.

## Topic hubs (organizational scheme)

Specific topics (e.g. Therapy, Journaling, a project) are not property values — they are approved **topic hubs**: navigation notes that other notes point to through `parent`. The hub registry lives in the schema (`schema.json` `topic_hubs`, mirrored in `0.02 templates/0.023 topic hubs.md`) and is the controlled vocabulary for `parent`.

- Surface candidate hubs from the vault's own content with `propose-topic-hubs` (one domain at a time), review them with the user, approve only the useful ones, then re-lock norms.
- Treat folders as a categorization signal, not a dependency: dashboards filter on `parent`, so notes can be re-foldered freely.

Preserve the approved property order and existing user-authored content. Do not silently expand controlled vocabularies or invent hubs outside the approved registry.
