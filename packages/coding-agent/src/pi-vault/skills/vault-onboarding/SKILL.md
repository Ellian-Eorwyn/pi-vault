---
name: vault-onboarding
description: Initialize a new or existing Obsidian vault for pi-vault. Use when the vault has no .pi-vault/config.yaml, when the user wants to choose system and inbox folders, or when purpose, schema, folder, property, tag, and link norms must be planned before organization.
---

# Vault Onboarding

1. Confirm the vault root and selected system and inbox folders. Never infer a different root silently.
2. Scan without changing ordinary notes (`vault-agent suggest-layout` runs a read-only scan). Describe observed folders, frontmatter, tags, links, indexes, and inconsistencies.
3. Decide the folder layout before creating anything. The default folder structure is only a suggestion: run `vault-agent suggest-layout` to propose a layout that mirrors the user's existing folders, mapping them onto pi-vault's content roles and keeping unmatched top-level folders as unmanaged `extra_folders`. Present the proposed outline (`.pi-vault/layout-suggestion.yaml`), let the user edit it freely, then run `vault-agent apply-layout` to write it to `.pi-vault/config.yaml`.
4. Run `vault_status`. If initialization is needed, run `pi-vault vault init` (or `vault-agent init`), which now builds the approved layout from the bootstrap config rather than forcing defaults. Existing folders are preserved; `extra_folders` are created but left unmanaged (never an automatic routing or dashboard target).
5. If `schema_state` is `provisional`, present the bundled schema and templates only as a starting point. Compare them with observed vault practice and ask the user to decide durable purpose, retrieval priorities, ignored paths, folder depth, note types, properties, tags, links, and automation limits.
6. Convert explicit decisions into pending proposals. Do not directly rewrite canonical schema or templates.
7. Show the proposal review, apply only approved changes, write the norms lock, rebuild retrieval, and run Obsidian validation.

Keep all vault-specific policy and generated state inside the selected system folder. Treat `.pi-vault/config.yaml` only as the bootstrap locator. Do not enforce provisional defaults on existing notes. A current norms lock is authoritative; a drifted lock blocks broad processing until reviewed and replaced.
