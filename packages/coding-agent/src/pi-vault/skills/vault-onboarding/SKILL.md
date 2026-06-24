---
name: vault-onboarding
description: Initialize a new or existing Obsidian vault for pi-vault. Use when the vault has no .pi-vault/config.yaml, when the user wants to choose system and inbox folders, or when purpose, schema, folder, property, tag, and link norms must be planned before organization.
---

# Vault Onboarding

1. Confirm the vault root and selected system and inbox folders. Never infer a different root silently.
2. Scan without changing ordinary notes (`vault-agent suggest-layout` runs a read-only scan). Describe observed folders, frontmatter, tags, links, indexes, and inconsistencies.
3. Decide the folder layout before creating anything. The default folder structure is only a suggestion: run `vault-agent suggest-layout` to propose a layout that mirrors the user's existing folders, mapping them onto pi-vault's built-in content roles and turning any unmatched top-level folder into a user-defined `domain_folders` entry (a routable domain). Present the proposed outline (`.pi-vault/layout-suggestion.yaml`), let the user edit it freely — they can rename roles, add or remove their own domain folders — then run `vault-agent apply-layout` to write it to `.pi-vault/config.yaml`.
4. Run `vault_status`. If initialization is needed, run `pi-vault vault init` (or `vault-agent init`), which now builds the approved layout from the bootstrap config rather than forcing defaults. Existing folders are preserved. Each `domain_folders` entry becomes canonical: notes whose `domain` matches the key route into that folder, it gets its own dashboard, and the domain is a valid schema value.
   - For a fully custom structure, the outline also has a `custom_folders` list (arbitrary, possibly nested paths, each with a description) and a `routing` block. Set `routing.mode: custom` to let the model sort notes into those folders during normal processing using the descriptions as hints; `routing.fallback: deterministic` keeps the type/domain routing as a safety net when the model is unsure. Custom folders are created with their own dashboards and all moves stay proposal-gated.
5. If `schema_state` is `provisional`, present the bundled schema and templates only as a starting point. Compare them with observed vault practice and ask the user to decide durable purpose, retrieval priorities, ignored paths, folder depth, note types, properties, tags, links, and automation limits.
6. Convert explicit decisions into pending proposals. Do not directly rewrite canonical schema or templates.
7. Show the proposal review, apply only approved changes, write the norms lock, rebuild retrieval, and run Obsidian validation.

Keep all vault-specific policy and generated state inside the selected system folder. Treat `.pi-vault/config.yaml` only as the bootstrap locator. Do not enforce provisional defaults on existing notes. A current norms lock is authoritative; a drifted lock blocks broad processing until reviewed and replaced.
