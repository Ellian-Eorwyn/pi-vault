---
name: vault-people
description: Extract people from a pi-vault Obsidian vault into deduplicated person notes. Use when the user wants to build Contacts and Authors notes from mentions across their notes, with details derived from those notes and backlinks to where each person appears.
---

# Vault People

Use this to turn people mentioned across the vault into individual `person` notes,
sorted into Contacts and Authors, without duplicates, all through reviewable proposals.

1. Read the vault purpose and conventions and confirm the People layout: contacts live
   under the configured `contacts` folder (default `02 People/02.01 Contacts`) and
   authors under `authors` (default `02 People/02.02 Authors`). `parent: [[Contacts]]`
   and `parent: [[Authors]]` are what route a person note to each folder.
2. Confirm scope with the user: the whole vault or one folder, and roughly how many
   people to process this pass.
3. Run `propose-people` (optionally `--folder <path>` and `--max-people <n>`), or
   `vault_manage` with `action: "people"`. The engine:
   - detects person mentions deterministically,
   - deduplicates against existing person notes by normalized name (never recreating
     one — it extends `related` backlinks instead),
   - classifies each clearly-identified new person as Contact or Author and drafts their
     details using the vault's configured LLM backend, grounded only in the mentions,
   - leaves ambiguous or single-name mentions for review rather than guessing.
4. Provider boundary: all classification and detail drafting is performed by the
   configured pi/engine backend through `propose-people`. Do not author person notes
   yourself or call any other model. Details must stay grounded in what the notes say;
   never invent biography or contact information.
5. Dry-run the proposal review, walk the user through the proposed Contacts/Authors and
   backlinks, apply only after approval, then rebuild retrieval and report created,
   deduplicated, and blocked people with the run ID and undo command.
