---
name: vault-onboarding
description: Initialize a new or existing Obsidian vault for pi-vault. Use when the vault has no .pi-vault/config.yaml, when the user wants to choose system and inbox folders, or when purpose, schema, folder, property, tag, and link norms must be planned before organization.
---

# Vault Onboarding

1. Confirm the vault root and selected system and inbox folders. Never infer a different root silently.
2. Run `vault_status`. If initialization is needed, use the interactive onboarding flow or `pi-vault vault init`.
3. Scan without changing ordinary notes. Describe observed folders, frontmatter, tags, links, indexes, and inconsistencies.
4. If `schema_state` is `provisional`, present the bundled schema and templates only as a starting point. Compare them with observed vault practice and ask the user to decide durable purpose, retrieval priorities, ignored paths, folder depth, note types, properties, tags, links, and automation limits.
5. Convert explicit decisions into pending proposals. Do not directly rewrite canonical schema or templates.
6. Show the proposal review, apply only approved changes, write the norms lock, rebuild retrieval, and run Obsidian validation.

Keep all vault-specific policy and generated state inside the selected system folder. Treat `.pi-vault/config.yaml` only as the bootstrap locator. Do not enforce provisional defaults on existing notes. A current norms lock is authoritative; a drifted lock blocks broad processing until reviewed and replaced.
