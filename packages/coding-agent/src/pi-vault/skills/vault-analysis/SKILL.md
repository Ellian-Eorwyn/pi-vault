---
name: vault-analysis
description: Read a folder or section of a pi-vault Obsidian vault in full and refine it through reviewable proposals. Use to chat about a folder, apply schema-compliant defaults with whole-note context, rename files within the schema, and improve note structure, coherence, skimmability, and Obsidian Markdown formatting without changing wording or meaning.
---

# Vault Analysis

Use this when the user wants to think through, clean up, or refine a specific folder
or section of the vault with full reading of each note, rather than the bounded
inbox pipeline. Everything stays proposal-first, schema-bound, and git-backed.

1. Read the vault-local purpose and conventions, then run `vault_status` and
   organization readiness. Stop if norms are missing or stale; complete onboarding or
   schema review and write the norms lock first.
2. Confirm the scope with the user: one folder (or one note). Read the whole notes in
   that scope for context before suggesting anything. Summarize what the section is,
   how it is organized, and where it diverges from the locked schema and conventions.
3. Stay strictly within the locked schema: only approved properties, values, topic
   hubs, folders, and dashboard structures. Never invent vocabulary. For `parent`, use
   only approved hubs.
4. Propose changes through the engine, never by editing notes yourself:
   - Schema-compliant frontmatter defaults and hub/folder assignment: the
     `classify-type`, `property-values`, and `assign-hub` stages via
     `organize-vault-pass --folder <folder>`.
   - Schema-compliant file renames: `move_note` operations (which rewrite inbound
     wikilinks). Only rename to fit approved conventions, never to restyle a title.
   - Note-internal refinement (structure, coherence, skimmability, Obsidian Markdown):
     `vault_content_propose` with `operation: "refine"` and the `folder` (or `note`),
     which runs `propose-folder-refinement`.
5. Provider boundary — important: all model work, including every note-body rewrite,
   is performed by the vault's configured pi/engine LLM backend through the engine
   commands above. Do not author, rewrite, or reformat note bodies yourself in this
   session, and do not call any other model. You orchestrate and converse; the
   configured backend writes.
6. The refinement engine reformats only. It never changes wording or meaning: a
   deterministic word-preservation guard rejects any rewrite that drops or substitutes
   the author's words, and blocked rewrites are reported with a word-diff instead of
   applied. State this guarantee to the user; never offer to bypass it.
7. Dry-run the proposal review (`vault_review_apply` with `operation: "review"`). Walk
   the user through the diffs. Apply only approved bounded operations
   (`vault_review_apply` with `operation: "apply-approved"`).
8. Rebuild retrieval, run validation and Obsidian checks, then report the changed
   files, any blocked refinements with their word-diff reasons, the run ID, and the
   undo command.
