Obsidian Vault Management and Retrieval Agent

You are building a local-first Obsidian vault management system. The system should help structure, classify, template, summarize, and index Markdown notes in an Obsidian vault. It must be safe, deterministic where possible, and designed so LLMs only perform narrow classification/summarization tasks while scripts handle validation and file modifications.

The system should be built inside the vault itself, using a 99 System folder. Human-editable schema and templates should live in Markdown. Machine-readable state, manifests, and indexes should live in JSON/YAML/Markdown files inside the agent folder.

The system must never delete user notes or user-written note content. It may update frontmatter, insert missing template headings, create summary/index files, and move files only under explicitly allowed conditions. Anything that would otherwise be removed must instead be moved to an internal trash/quarantine folder for user review.

## Core goals

Build a vault agent that can:

1. Scan an Obsidian vault and maintain a machine-readable manifest of notes.
2. Maintain a strict schema of allowed note types, properties, and property values.
3. Maintain one Markdown template per note type.
4. Process notes one at a time.
5. Assign each note a note type from the allowed list.
6. Apply the corresponding template safely.
7. Fill only schema-approved frontmatter properties with schema-approved values.
8. Generate layered summaries for retrieval.
9. Maintain retrieval indexes by note type, domain, project, and status.
10. Track processed, unprocessed, stale, skipped, errored, and needs-review notes.
11. Prioritize notes in 00 Inbox.
12. Avoid loading the whole vault into LLM context.
13. Cap individual note content passed to an LLM at approximately 64k tokens.
14. Be usable from command line and suitable for scheduled runs through cron, launchd, Codex, opencode, Claude Code, or an agent harness.
15. Preserve all user-authored note body text.

## Required folder structure

Create and maintain the following folder structure if it does not already exist:

text 99 System/   0.01 agent/     config.yaml     schema.json     manifest.json     state.json     logs/     backups/     scripts/     review/       needs-review.md       proposed-values.md       processing-errors.md     retrieval/       00 retrieval-readme.md       01 vault-map.md       02 note-catalog.md       03 property-index.md       04 summary-brief.md       summaries-standard/         by-type/         by-domain/         by-project/         by-status/       deep-summaries/       indexes/         by-type/         by-domain/         by-project/         by-status/       stale-summaries.md       retrieval-log.md   0.02 templates/     0.020 vault schema.md     0.021 property values.md     0.022 folder norms.md     note-types/   0.99 trash/  00 Inbox/

Do not assume other folders exist. The scan command should discover the current folder structure and write it to the vault map.

## Primary commands

Implement a CLI with at least these commands:

bash vault-agent init vault-agent scan vault-agent validate vault-agent process-next vault-agent process-inbox vault-agent reconcile vault-agent rebuild-retrieval vault-agent status

The command may be a Python script, Node script, shell wrapper, or other appropriate local CLI. Prefer Python unless there is a strong reason not to.

## Command behavior

### vault-agent init

Create the system folders and starter files if missing.

It should create:

text 99 System/0.01 agent/config.yaml 99 System/0.01 agent/schema.json 99 System/0.02 templates/0.020 vault schema.md 99 System/0.02 templates/0.021 property values.md 99 System/0.02 templates/0.022 folder norms.md 99 System/0.01 agent/retrieval/00 retrieval-readme.md

It should not overwrite existing user-edited schema/template files without creating a backup.

### vault-agent scan

Scan the vault and update manifest.json, state.json, 01 vault-map.md, and 02 note-catalog.md.

The scan must exclude:

text 99 System/0.01 agent/ 99 System/0.99 trash/ .git/ .obsidian/

The scan should include normal note templates in 99 System/0.02 templates/ as system/template files, but these should not be processed as ordinary notes.

For each Markdown note, record:

yaml id path title type status processing_status created modified size_bytes content_hash frontmatter_hash body_hash schema_version template_version last_processed last_summarized summary_status

Use stable note IDs. If a note has no ID, generate one and add it to frontmatter only during a processing operation, not during scan unless explicitly configured.

Use hashes rather than only modified times to detect changes.

### vault-agent validate

Validate the vault against the schema.

Check for:

- unknown properties
- invalid property values
- missing required properties
- invalid note types
- notes whose template no longer exists
- templates that reference properties not in schema
- malformed YAML frontmatter
- stale summaries
- stale processed notes
- missing note IDs
- duplicated note IDs
- files exceeding the LLM processing size threshold
- retrieval indexes out of date

Write results to:

text 99 System/0.01 agent/review/needs-review.md 99 System/0.01 agent/review/processing-errors.md

Validation should not use the LLM unless explicitly configured.

### vault-agent process-next

Process exactly one note, then exit.

Priority order:

1. Unprocessed notes in 00 Inbox
2. Stale notes in 00 Inbox
3. Unprocessed notes elsewhere
4. Stale notes elsewhere
5. Notes marked needs_review only if configured

A note is stale if:

- its body hash changed since last processing
- its frontmatter hash changed and validation fails
- the schema version changed
- the template version for its type changed
- its summaries are stale

Processing a note should:

1. Load schema and templates.
2. Load manifest/state.
3. Select one candidate note.
4. Read its existing frontmatter and bounded body content.
5. If content exceeds the LLM threshold, use a structured excerpt:
   - title
   - path
   - current frontmatter
   - heading outline
   - first section or first N tokens
   - representative middle excerpts if available
   - final section or final N tokens
6. Ask the LLM for a structured proposal only.
7. Validate the LLM proposal against schema.
8. Apply only safe deterministic changes.
9. Update summaries.
10. Update retrieval indexes.
11. Update manifest/state.
12. Write a log entry.
13. Exit.

The LLM must not directly rewrite the file. It should return a structured JSON proposal, and the script should validate and apply it.

### vault-agent process-inbox

Repeatedly process notes in 00 Inbox, one at a time.

Each note must be processed in a fresh LLM context. Do not batch multiple note bodies into one LLM prompt.

Add options:

bash vault-agent process-inbox --max-notes 20 vault-agent process-inbox --max-runtime-minutes 30 vault-agent process-inbox --dry-run

After each note, state must be updated before moving to the next note.

### vault-agent reconcile

Check already-processed notes against current schema/templates.

It should not fully reprocess everything by default. It should identify notes that need:

- frontmatter repair
- summary regeneration
- template heading insertion
- review
- no action

### vault-agent rebuild-retrieval

Regenerate all retrieval files from manifest, frontmatter, summaries, and deep summary files.

This command should not call the LLM unless summaries are missing or stale and an option is passed.

Suggested options:

bash vault-agent rebuild-retrieval vault-agent rebuild-retrieval --with-summaries vault-agent rebuild-retrieval --brief-only vault-agent rebuild-retrieval --standard vault-agent rebuild-retrieval --deep

### vault-agent status

Print a concise status report:

text Total notes: X Unprocessed: X Stale: X Needs review: X Errors: X Inbox unprocessed: X Summaries stale: X Last scan: timestamp Last processed note: path

## Processing statuses

Use the following strict processing statuses:

yaml processing_status:   - unprocessed   - processed   - stale   - needs_review   - skipped   - error

Definitions:

- unprocessed: never processed.
- processed: processed under the current schema/template and unchanged since.
- stale: note, schema, template, or summary changed since last processing.
- needs_review: LLM confidence was low, schema mismatch occurred, or human decision is needed.
- skipped: intentionally ignored, usually because it is too large, binary-derived, archived, or system-managed.
- error: processing failed.

## Safety rules

These are mandatory.

The system must never:

1. Delete notes.
2. Delete user-authored body text.
3. Overwrite body text.
4. Silently rename or move notes outside approved rules.
5. Invent new properties.
6. Invent new property values and apply them directly.
7. Process multiple note bodies in one LLM context.
8. Process files in 99 System/0.01 agent/ as normal notes.
9. Process files in 99 System/0.99 trash/ as normal notes.
10. Apply edits if YAML parsing fails.
11. Apply edits if the LLM returns invalid JSON.
12. Apply edits if validation fails.
13. Apply edits without logging them.
14. Apply edits without creating a recoverable backup or diff.

The system may:

1. Add missing frontmatter.
2. Add or update allowed frontmatter properties.
3. Add a stable note ID.
4. Insert missing template headings.
5. Add agent-generated summaries to retrieval files.
6. Add review entries.
7. Add proposed property values to a proposal queue.
8. Move files only if explicitly configured and logged.

## No direct LLM file editing

The LLM must only return a JSON proposal.

Example proposal:

json {   "note_id": "n000143",   "note_type": "concept",   "confidence": 0.86,   "frontmatter_updates": {     "type": "concept",     "status": "seed",     "domains": ["epistemology", "sociology-of-knowledge"],     "projects": [],     "processing_status": "processed"   },   "template_to_apply": "concept.md",   "body_insertions": [     {       "location": "after_frontmatter",       "insert_if_missing_heading": "## Summary",       "content": "## Summary\n\n"     }   ],   "brief_summary": "Explains hermeneutical injustice as a gap in shared interpretive resources that affects social intelligibility.",   "standard_summary": {     "summary": "This note discusses hermeneutical injustice as a structural gap in collective interpretive resources that prevents some people from making sense of socially situated experience.",     "key_topics": ["hermeneutical injustice", "feminist epistemology", "social intelligibility"],     "use_when": [       "The user asks about epistemic injustice.",       "The user asks about marginalized knowledge production.",       "The user asks about social conditions of intelligibility."     ],     "do_not_use_when": [       "The user asks only about generic misinformation without a structural epistemic injustice angle."     ],     "related_notes": []   },   "proposed_new_values": {},   "warnings": [] }

The script must validate this proposal before applying it.

## Starter schema

Create a starter schema with these note types:

yaml note_types:   - inbox   - concept   - claim   - source   - literature-note   - project   - task   - meeting   - person   - daily   - writing-fragment   - reference   - index   - system

The schema should support type-specific templates.

## Starter properties

Use these common properties:

yaml common_properties:   id:     type: string     required: true   type:     type: enum     required: true     values_from: note_types   status:     type: enum     required: true     values:       - seed       - active       - dormant       - archived   created:     type: date     required: false   modified:     type: date     required: false   aliases:     type: list     required: false   tags:     type: list     required: false   domains:     type: list_enum     required: false     values:       - epistemology       - sociology-of-knowledge       - feminist-epistemology       - buddhist-philosophy       - science-and-technology-studies       - energy-infrastructure       - data-centers       - ttrpgs       - dissertation       - personal       - administration       - health       - computing       - writing   projects:     type: list     required: false   people:     type: list     required: false   sources:     type: list     required: false   related:     type: list     required: false   confidence:     type: enum     required: false     values:       - low       - medium       - high   review_status:     type: enum     required: false     values:       - unreviewed       - reviewed       - needs_review   processing_status:     type: enum     required: true     values:       - unprocessed       - processed       - stale       - needs_review       - skipped       - error   schema_version:     type: string     required: false   template_version:     type: string     required: false   processed_at:     type: datetime     required: false

Type-specific properties:

yaml source_properties:   source_type:     type: enum     values:       - book       - article       - report       - website       - podcast       - video       - dataset       - other   authors:     type: list   year:     type: string   title:     type: string   publication:     type: string   doi:     type: string   url:     type: string   citekey:     type: string   reading_status:     type: enum     values:       - unread       - reading       - read       - excerpted       - abandoned  concept_properties:   related_concepts:     type: list   origin_sources:     type: list   maturity:     type: enum     values:       - seed       - developing       - stable       - contested  claim_properties:   claim_status:     type: enum     values:       - intuition       - tentative       - supported       - contested       - rejected   supports:     type: list   contradicts:     type: list   evidence_sources:     type: list  project_properties:   project_status:     type: enum     values:       - active       - waiting       - paused       - complete       - abandoned   area:     type: string   next_action:     type: string   deadline:     type: date   stakeholders:     type: list

## Starter templates

Create one Markdown template per note type in:

text 99 System/0.02 templates/note-types/

Each template must contain YAML frontmatter with relevant properties.

Example concept template:

markdown --- id: type: concept status: seed aliases: [] tags: [] domains: [] projects: [] people: [] sources: [] related: [] related_concepts: [] origin_sources: [] maturity: seed confidence: review_status: unreviewed processing_status: unprocessed schema_version: template_version: processed_at: ---  ## Summary  ## Notes  ## Connections  ## Open Questions

Example source template:

markdown --- id: type: source status: seed aliases: [] tags: [] domains: [] projects: [] people: [] sources: [] related: [] source_type: authors: [] year: title: publication: doi: url: citekey: reading_status: unread confidence: review_status: unreviewed processing_status: unprocessed schema_version: template_version: processed_at: ---  ## Citation  ## Summary  ## Notes  ## Key Claims  ## Useful Passages  ## Connections

Do this for each starter note type. Keep templates minimal unless the note type almost always benefits from structure.

## Retrieval system

The retrieval system should be designed for progressive disclosure. An agent should be able to start with a shallow file, identify candidates, then read deeper summaries, then open full notes only when necessary.

Create and maintain:

text 99 System/0.01 agent/retrieval/00 retrieval-readme.md 99 System/0.01 agent/retrieval/01 vault-map.md 99 System/0.01 agent/retrieval/02 note-catalog.md 99 System/0.01 agent/retrieval/03 property-index.md 99 System/0.01 agent/retrieval/04 summary-brief.md 99 System/0.01 agent/retrieval/summaries-standard/by-type/ 99 System/0.01 agent/retrieval/summaries-standard/by-domain/ 99 System/0.01 agent/retrieval/summaries-standard/by-project/ 99 System/0.01 agent/retrieval/summaries-standard/by-status/ 99 System/0.01 agent/retrieval/deep-summaries/ 99 System/0.01 agent/retrieval/indexes/by-type/ 99 System/0.01 agent/retrieval/indexes/by-domain/ 99 System/0.01 agent/retrieval/indexes/by-project/ 99 System/0.01 agent/retrieval/indexes/by-status/

### 00 retrieval-readme.md

This file should instruct future agents how to retrieve vault context.

Include instructions like:

markdown # Retrieval Instructions for Agents  Do not scan the whole vault first.  Start with these files in order:  1. `01 vault-map.md` for folder structure and vault scope. 2. `02 note-catalog.md` for note IDs, paths, note types, titles, statuses, and modified dates. 3. `03 property-index.md` for controlled metadata. 4. `04 summary-brief.md` to identify candidate notes. 5. `summaries-standard/` for medium-depth summaries grouped by type, domain, project, or status. 6. `deep-summaries/` for detailed generated summaries of selected notes. 7. Open full notes only after selecting likely relevant candidates.  Rules: - Prefer notes whose summaries directly match the user query. - Prefer current notes over archived notes unless historical context is requested. - Do not load full notes unless necessary. - Do not edit notes during retrieval. - Cite note paths when using vault content.

### 01 vault-map.md

Generated from scan. Include:

- folder tree
- counts by folder
- counts by note type
- counts by processing status
- excluded folders
- last scan timestamp

### 02 note-catalog.md

A compact table of notes:

markdown | ID | Path | Title | Type | Status | Domains | Projects | Modified | Processing | |---|---|---|---|---|---|---|---|---|

### 03 property-index.md

Group notes by controlled property values:

markdown # Property Index  ## domains  ### epistemology - n000143 — [[path/to/note|Title]]  ### buddhist-philosophy - n000233 — [[path/to/note|Title]]  ## projects  ### dissertation - n000410 — [[path/to/note|Title]]  ## status  ### active - n000410 — [[path/to/note|Title]]

### 04 summary-brief.md

One short entry per note:

markdown ## n000143 — Title  Path: path/to/note.md   Type: concept   Domains: epistemology, sociology-of-knowledge   Projects: dissertation   Summary: One-sentence summary.

### Standard summaries

Create standard summaries grouped four ways:

text summaries-standard/by-type/concept.md summaries-standard/by-type/source.md summaries-standard/by-domain/epistemology.md summaries-standard/by-project/dissertation.md summaries-standard/by-status/active.md

Each standard summary entry should include:

markdown ## n000143 — Title  Path: path/to/note.md   Type: concept   Status: active   Domains: epistemology, sociology-of-knowledge   Projects: dissertation   Source hash: abc123   Summary updated: timestamp  ### Summary  100–250 word summary.  ### Key Topics  - topic 1 - topic 2  ### Use When  - use case 1 - use case 2  ### Do Not Use When  - exclusion 1  ### Related Notes  - n000144 — Title

### Deep summaries

Create one file per note:

text deep-summaries/n000143.md

Each deep summary should include:

markdown # n000143 — Title  Path: path/to/note.md Type: concept Status: active Domains: epistemology, sociology-of-knowledge Projects: dissertation Source body hash: abc123 Source frontmatter hash: def456 Summary updated: timestamp  ## Short Summary  ## Detailed Summary  ## Key Claims  ## Key Terms  ## Important Passages / Anchors  ## Related Notes  ## Retrieval Hints  ## Open Questions

Do not create deep summaries for every note unless configured. Default:

yaml deep_summary_types:   - concept   - claim   - source   - literature-note   - project   - writing-fragment

## Retrieval indexes

Maintain indexes by type, domain, project, and status.

### By type

text indexes/by-type/concept.md indexes/by-type/source.md indexes/by-type/claim.md

Each should list note IDs, titles, paths, domains, projects, status, and brief summary.

### By domain

text indexes/by-domain/epistemology.md indexes/by-domain/buddhist-philosophy.md indexes/by-domain/energy-infrastructure.md

Each should group notes by type:

markdown # Domain Index: epistemology  ## Concepts  - n000143 — [[path/to/note|Title]] — brief summary  ## Sources  - n000144 — [[path/to/note|Title]] — brief summary  ## Claims  - n000188 — [[path/to/note|Title]] — brief summary

### By project

text indexes/by-project/dissertation.md indexes/by-project/data-centers.md

Each should group by status and type.

### By status

text indexes/by-status/active.md indexes/by-status/seed.md indexes/by-status/archived.md indexes/by-status/needs_review.md

Each should group by type and domain.

## Summary generation policy

During process-next and process-inbox, generate:

- brief summary: always
- standard summary: always for processed notes
- deep summary: only for configured note types

Brief summaries should be one sentence.

Standard summaries should be retrieval-oriented, not decorative. They should include:

- what the note is about
- key topics
- why it matters
- when to use it
- when not to use it
- related notes if obvious

Deep summaries should include more detail but should not replace the full note.

Summaries should be regenerated if:

- note body hash changed
- relevant frontmatter changed
- schema version changed in a way that affects retrieval
- summary format changed

Each summary must record source hashes so staleness can be detected.

## Proposed values queue

If the LLM encounters a value that seems useful but is not allowed by the schema, it must not add it to the note.

Instead, append it to:

text 99 System/0.01 agent/review/proposed-values.md

Format:

markdown ## Proposed value  Property: domains   Proposed value: pragmatism   Source note: n000143 — path/to/note.md   Reason: The note substantially discusses pragmatist theories of truth.   Status: pending

## Review queue

Any uncertain note should be marked needs_review.

Add entries to:

text 99 System/0.01 agent/review/needs-review.md

Use this format:

markdown ## n000143 — Title  Path: path/to/note.md   Reason: Low confidence note type classification.   Suggested type: concept   Alternative types: claim, literature-note   Action needed: User should confirm note type.

## Logs

Every command that modifies files must log actions to:

text 99 System/0.01 agent/logs/YYYY-MM-DD.md

Each processed note should log:

markdown ## Processed: n000143 — Title  Path: path/to/note.md Timestamp: timestamp  Actions: - Assigned type: concept - Updated frontmatter: type, status, domains - Inserted missing heading: ## Summary - Generated brief summary - Generated standard summary - Generated deep summary - Updated retrieval indexes  Warnings: - none  Result: - processed

## Backups and atomic writes

Before modifying a note, create a backup or diff in:

text 99 System/0.01 agent/backups/

Use atomic writes:

text file.md.tmp → file.md manifest.json.tmp → manifest.json state.json.tmp → state.json

If writing fails, preserve the original.

## LLM provider abstraction

Implement an abstraction layer so the system can use different LLM backends.

Supported initial options:

yaml llm:   provider: openai-compatible   base_url: http://localhost:11434/v1   model: local-model-name   max_input_tokens: 64000   temperature: 0.1

The code should be backend-agnostic where practical.

If no LLM is configured, the system should still support:

bash vault-agent init vault-agent scan vault-agent validate vault-agent rebuild-retrieval vault-agent status

Processing commands should fail gracefully with a clear message if LLM access is required but unavailable.

## LLM prompt requirements

When processing one note, the LLM prompt should include:

1. Role: classify and summarize one Obsidian note.
2. Schema: allowed note types, allowed properties, allowed values.
3. Relevant template list.
4. Current file path.
5. Current frontmatter.
6. Bounded body content or structured excerpt.
7. Instruction to return valid JSON only.
8. Instruction not to invent properties or values.
9. Instruction to propose new values separately.
10. Instruction not to rewrite note body.
11. Instruction to use needs_review when uncertain.

The LLM should not see unrelated full notes during process-next.

## Template application rules

When applying a template:

1. Preserve existing frontmatter values unless invalid or empty.
2. Add missing template properties.
3. Fill properties only with allowed values.
4. Do not remove unknown existing user properties automatically; instead flag them in validation.
5. Do not remove body text.
6. Insert missing headings only if they do not already exist.
7. Insert headings at safe locations, usually after frontmatter or at the end.
8. Do not reorder the user’s existing body by default.

## Moving notes

Default behavior: do not move notes.

Optional behavior may be added later:

yaml move_processed_inbox_notes: false

If enabled, only move notes out of 00 Inbox when:

- note type confidence is high
- target folder is defined in folder norms
- target file path does not conflict
- move is logged
- old path and new path are recorded in manifest

Never move notes from outside 00 Inbox automatically unless explicitly configured.

## Folder norms

Maintain human-readable folder norms in:

text 99 System/0.02 templates/0.022 folder norms.md

Also store machine-readable folder norms in schema.json or config.yaml.

Example:

yaml folder_norms:   concept:     preferred_folders:       - "02 Notes/Concepts"   source:     preferred_folders:       - "03 Sources"   project:     preferred_folders:       - "04 Projects"   writing-fragment:     preferred_folders:       - "05 Writing"   daily:     preferred_folders:       - "07 Daily"

## Implementation requirements

Use clear, maintainable code.

Prefer modules like:

text vault_agent/   cli.py   config.py   schema.py   manifest.py   scanner.py   frontmatter.py   templates.py   processor.py   llm.py   summaries.py   retrieval.py   validation.py   logging_utils.py   safety.py

Include:

- README with usage instructions
- example config
- dry-run mode
- error handling
- schema validation
- tests for safety-critical behavior

## Minimum viable implementation

Build in this order:

1. init
2. scan
3. status
4. schema/template creation
5. frontmatter parser/writer
6. validate
7. retrieval file generation without LLM
8. LLM proposal interface
9. process-next
10. summary generation
11. retrieval indexes by type/domain/project/status
12. process-inbox
13. reconcile
14. tests and documentation

## Acceptance criteria

The implementation is successful when:

1. Running vault-agent init creates the required structure.
2. Running vault-agent scan creates a manifest and note catalog.
3. Running vault-agent validate identifies invalid properties/values without modifying notes.
4. Running vault-agent process-next processes only one note.
5. Each processed note receives a valid note type from the schema.
6. The corresponding template is safely applied.
7. No existing body text is deleted.
8. No notes are deleted.
9. Invalid LLM output causes no file modifications.
10. Summaries are created and updated.
11. Retrieval indexes are generated by type, domain, project, and status.
12. Summary staleness is detected by hashes.
13. The agent can retrieve candidate notes from retrieval files without scanning the whole vault.
14. Every modification is logged.
15. Backups or diffs are created before note modifications.
16. The system can run repeatedly without duplicating headings or corrupting frontmatter.
17. The system handles large notes by excerpting or marking them for review rather than loading the entire file.
18. System files are not processed as ordinary notes.

Build this as a conservative, safe, local-first vault management system. Prioritize data preservation, transparency, and deterministic behavior over cleverness.

Long-term feature: interactive schema and template editor

Add a long-term feature that lets the user chat with a model to add, revise, deprecate, or explain vault schema elements, including:

* note types
* templates
* properties
* accepted property values
* folder norms
* retrieval index rules
* summary generation rules

This feature should be implemented as an interactive command:

vault-agent schema-chat

Optional aliases:

vault-agent edit-schema
vault-agent schema-wizard

The purpose is to let the user describe desired changes in natural language while the system ensures those changes are written to the correct files in the exact required formats.

Core principle

The schema-chat model must not directly edit arbitrary vault files.

It may only propose structured schema/template changes. A deterministic script must validate and apply those changes.

Use this pattern:

user request → model proposes structured change plan → validator checks it → user approves → script applies changes → logs update

Files the schema editor may update

The schema editor may update only these files unless explicitly extended later:

99 System/0.01 agent/schema.json
99 System/0.01 agent/config.yaml
99 System/0.02 templates/0.020 vault schema.md
99 System/0.02 templates/0.021 property values.md
99 System/0.02 templates/0.022 folder norms.md
99 System/0.02 templates/note-types/*.md
99 System/0.01 agent/review/proposed-values.md
99 System/0.01 agent/logs/YYYY-MM-DD.md

It must not edit ordinary notes.

Supported schema-chat actions

Support these actions:

schema_chat_actions:
  - add_note_type
  - revise_note_type
  - deprecate_note_type
  - add_property
  - revise_property
  - deprecate_property
  - add_property_value
  - revise_property_value
  - deprecate_property_value
  - add_template
  - revise_template
  - add_folder_norm
  - revise_folder_norm
  - explain_schema
  - show_schema
  - validate_requested_change

Required behavior

When the user asks to add or change something, the schema-chat command should:

1. Load current schema.json.
2. Load current Markdown schema files.
3. Load current templates.
4. Identify the requested change.
5. Check whether the requested item already exists.
6. Check whether the change conflicts with existing note types, properties, values, or templates.
7. Generate a structured change proposal.
8. Show the proposal to the user in readable form.
9. Ask for explicit approval before applying.
10. Apply changes deterministically after approval.
11. Update both machine-readable and human-readable schema files.
12. Update or create relevant templates.
13. Run validation.
14. Log every changed file and every schema element added/revised/deprecated.
15. If needed, mark affected notes as stale so they can be reconciled later.

No silent schema mutation

The system must never silently add new properties or values during ordinary note processing.

During process-next or process-inbox, unknown but useful values should still go to:

99 System/0.01 agent/review/proposed-values.md

The user may later approve them through:

vault-agent schema-chat

or a future command:

vault-agent review-proposed-values

Structured change proposal format

The model must return JSON only.

Example for adding a property value:

{
  "action": "add_property_value",
  "property": "domains",
  "value": "pragmatism",
  "label": "Pragmatism",
  "reason": "The user wants to classify notes related to pragmatist theories of truth, inquiry, and practice.",
  "files_to_update": [
    "99 System/0.01 agent/schema.json",
    "99 System/0.02 templates/0.021 property values.md",
    "99 System/0.02 templates/0.020 vault schema.md"
  ],
  "affected_templates": [],
  "affected_notes_query": {
    "property": "domains",
    "old_value": null,
    "new_value": "pragmatism"
  },
  "requires_retrieval_rebuild": true,
  "requires_reconcile": false,
  "warnings": []
}

Example for adding a new note type:

{
  "action": "add_note_type",
  "note_type": {
    "id": "argument",
    "label": "Argument",
    "description": "A note that develops a structured argument with premises, objections, evidence, and implications.",
    "required_properties": [
      "id",
      "type",
      "status",
      "domains",
      "projects",
      "claim_status",
      "processing_status"
    ],
    "optional_properties": [
      "supports",
      "contradicts",
      "evidence_sources",
      "related",
      "confidence",
      "review_status"
    ],
    "preferred_folders": [
      "02 Notes/Arguments"
    ],
    "template_path": "99 System/0.02 templates/note-types/argument.md"
  },
  "template": {
    "frontmatter": {
      "id": null,
      "type": "argument",
      "status": "seed",
      "aliases": [],
      "tags": [],
      "domains": [],
      "projects": [],
      "people": [],
      "sources": [],
      "related": [],
      "claim_status": "tentative",
      "supports": [],
      "contradicts": [],
      "evidence_sources": [],
      "confidence": null,
      "review_status": "unreviewed",
      "processing_status": "unprocessed",
      "schema_version": null,
      "template_version": null,
      "processed_at": null
    },
    "body": "## Argument\n\n## Premises\n\n## Evidence\n\n## Objections\n\n## Implications\n\n## Open Questions\n"
  },
  "files_to_update": [
    "99 System/0.01 agent/schema.json",
    "99 System/0.02 templates/0.020 vault schema.md",
    "99 System/0.02 templates/0.022 folder norms.md",
    "99 System/0.02 templates/note-types/argument.md"
  ],
  "requires_retrieval_rebuild": true,
  "requires_reconcile": true,
  "warnings": [
    "This overlaps somewhat with the existing note type `claim`; user approval is required."
  ]
}

Human-readable approval view

Before applying a change, show the user a concise preview.

Example:

Proposed schema change:
Action: Add note type
New note type: argument
Template: 99 System/0.02 templates/note-types/argument.md
Preferred folder: 02 Notes/Arguments
Files to update:
- schema.json
- 0.020 vault schema.md
- 0.022 folder norms.md
- note-types/argument.md
Potential overlap:
- Existing type `claim` may already cover some of this use case.
Apply this change? [y/N]

Default answer must be no.

Schema editing safety rules

The schema-chat feature must never:

1. Delete existing schema elements outright.
2. Delete templates outright.
3. Remove accepted values outright.
4. Rewrite the entire schema file if a targeted edit is possible.
5. Apply changes without user approval.
6. Apply changes if validation fails.
7. Edit ordinary notes directly.
8. Rename existing note types without creating a migration plan.
9. Change meanings of existing values without warning.
10. Break existing processed notes without marking them stale or needing review.

Instead of deleting, use deprecation.

Deprecation model

When the user wants to remove a property, value, or note type, mark it deprecated.

Example:

deprecated_values:
  domains:
    old-value:
      deprecated_at: 2026-06-08T00:00:00
      replacement: new-value
      reason: "User consolidated domain values."

For note types:

deprecated_note_types:
  old-type:
    deprecated_at: 2026-06-08T00:00:00
    replacement: new-type
    reason: "User consolidated overlapping note types."

Then reconcile should identify affected notes and propose safe updates.

Formatting knowledge

The schema-chat model must be given exact formatting instructions for all schema files before proposing changes.

It should know:

* how note types are represented in schema.json
* how properties are represented in schema.json
* how values are represented in schema.json
* how folder norms are represented
* how templates are structured
* how Markdown schema files mirror machine-readable schema
* where to append proposed values
* where to log changes

The model should not infer formatting from memory. The command should always load current schema/template files before asking the model for a proposal.

Change application

After approval, the deterministic script should:

1. Backup every file to be changed.
2. Apply targeted changes.
3. Format JSON/YAML consistently.
4. Update Markdown schema files.
5. Create or revise templates as needed.
6. Increment schema version.
7. Increment affected template versions.
8. Run vault-agent validate.
9. Run vault-agent rebuild-retrieval if needed.
10. Mark affected notes as stale if needed.
11. Write a log entry.

Schema versioning

Maintain a schema version in schema.json.

Example:

schema_version: 1.3.0

Increment rules:

* patch version: adding a value, clarifying description, fixing formatting
* minor version: adding a property, adding a note type, adding template structure
* major version: renaming/removing/deprecating central properties or changing note type semantics

Template versioning

Each template should have a version.

Example in template frontmatter:

template_name: concept
template_version: concept@1.1.0

When schema-chat revises a template, increment the template version and mark notes using older versions as stale.

Proposed values review

Add a command:

vault-agent review-proposed-values

This should read:

99 System/0.01 agent/review/proposed-values.md

For each pending value, allow the user to:

[a] approve
[r] reject
[e] edit
[s] skip
[q] quit

Approved values should be added through the same schema-chat validation and application path.

Rejected values should remain in the file but be marked:

Status: rejected

Example user interactions

User says:

Add a new domain for pragmatism.

System should propose adding pragmatism to the allowed values for domains, update property values Markdown, update schema JSON, rebuild affected retrieval indexes, and log the change.

User says:

I need a new note type for structured arguments.

System should detect overlap with claim, propose either expanding claim or adding a new argument note type, show the difference, and ask for approval.

User says:

Remove the domain personal.

System should propose deprecating personal, not deleting it, and ask whether to set a replacement value.

User says:

Make source notes include a section for methods.

System should propose revising the source template, incrementing the source template version, and marking existing source notes as stale for template reconciliation.

Acceptance criteria for schema-chat

This feature is complete when:

1. The user can request a new property value in natural language.
2. The system proposes the exact files and schema records to update.
3. The system asks for approval before applying.
4. The system updates both machine-readable and human-readable schema files.
5. The system can create a new note type and corresponding template.
6. The system can revise an existing template.
7. The system deprecates rather than deletes.
8. The system logs every change.
9. The system validates after changes.
10. The system marks affected notes stale when needed.
11. The system never edits ordinary notes during schema-chat.
12. Invalid or conflicting changes are rejected or sent back for user clarification.

The key thing is to frame this as schema governance, not “let the model edit the schema.” Models are good at interpreting your intent; they are not good at being the sole guardian of a growing ontology.