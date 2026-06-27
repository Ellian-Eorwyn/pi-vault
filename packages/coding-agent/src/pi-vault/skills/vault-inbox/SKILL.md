---
name: vault-inbox
description: Inspect and process the configured inbox of a pi-vault managed Obsidian vault. Use for inbox triage, scheduled maintenance, classification, metadata, summaries, templates, duplicate review, moves, renames, and unresolved-item reporting.
---

# Vault Inbox

1. Run status and confirm the configured inbox path and current norms lock.
2. Preview the bounded queue. Do not process outside the configured inbox.
3. Apply deterministic shaping first. Run semantic stages serially with `vault_process_notes` `scope: "inbox"` (one `stage` per run, `useLlm` when a provider is enabled).
4. After type/domain/parent values are current, run `vault_organize_propose` `operation: "inbox-sort"` (`safeOnly: true` for unattended runs). Route people to Contacts or Authors, organizations to Organizations, sources to Sources, work notes to their project, administrative notes by purpose, and remaining knowledge to Thoughts.
5. Allow scheduled runs to apply only bounded moves backed by a current norms lock and completed warning-free `classify-type` and `property-values` stages above the confidence threshold. Leave ambiguity, collisions, stale state, and model blocks pending.
6. Rebuild retrieval and report processed notes, remaining notes, proposals, blocked items, changed files, and rollback command.

Never delete an inbox note or overwrite a destination note.
