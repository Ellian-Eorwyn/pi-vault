---
name: vault-retrieval
description: Retrieve notes from a pi-vault managed Obsidian vault with minimal context. Use when answering questions from the vault, locating named notes, understanding its structure, or selecting notes before reading full bodies.
---

# Vault Retrieval

1. Run `vault_status` and read the vault purpose and conventions paths supplied in the pi-vault context.
2. Read the generated vault map and summary brief before broad search.
3. Use the note catalog and property index to shortlist by path, title, type, domain, parent, and aliases.
4. Read shortlisted frontmatter before full note bodies.
5. Follow meaningful wikilinks only when they improve the answer.

Do not mutate notes during retrieval. If generated retrieval files are stale, report that and use `vault_manage` with `rebuild-retrieval` only after confirming no organizational write is implied.
