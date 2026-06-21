Obsidian Vault Agent: Memory Layer Implementation Specification

Purpose

Build a local-first memory layer inside the Obsidian vault that allows agents to retrieve, update, audit, and consolidate user/vault memory without scanning the whole vault or relying on opaque external state.

The memory layer should support:

1. Stable user/profile memory.
2. Project memory.
3. Vault-derived note memory.
4. Chat-derived memory.
5. Episodic memory.
6. Procedural memory for agent behavior.
7. Temporal validity and stale-memory handling.
8. Human-readable Markdown summaries.
9. Machine-readable JSON state.
10. Optional SQLite indexes for fast retrieval.
11. Scheduled consolidation by tools such as Hermes, OpenClaw, cron, launchd, Codex, OpenCode, or Claude Code.

The memory layer must be conservative. It should prefer traceable, narrow, revisable memories over broad inferred claims.

⸻

1. Folder Structure

Extend the existing agent folder with a dedicated memory/ subtree.

00 System/
  0.01 agent/
    memory/
      00 memory-readme.md
      config.memory.yaml
      memory-schema.json
      memory-state.json
      memory-manifest.json
      memory-log.md
      profile/
        00 current-profile.md
        01 stable-preferences.md
        02 active-projects.md
        03 procedural-instructions.md
        04 constraints.md
        profile.json
      chats/
        inbox/
        processed/
        summaries/
        manifests/
        review/
      episodes/
        by-date/
        by-source/
        episode-index.md
        episodes.json
      semantic/
        memories.json
        memory-catalog.md
        by-entity/
        by-domain/
        by-project/
        by-type/
      procedural/
        agent-behavior.md
        retrieval-rules.md
        writing-style.md
        tool-use-rules.md
        procedural.json
      projects/
        project-memory.md
        by-project/
      temporal/
        active.md
        expired.md
        superseded.md
        needs-refresh.md
        temporal-index.json
      retrieval/
        00 memory-retrieval-readme.md
        01 memory-map.md
        02 memory-catalog.md
        03 memory-brief.md
        04 memory-context-packets.md
        indexes/
          by-entity/
          by-domain/
          by-project/
          by-type/
          by-status/
          by-validity/
        context-packets/
          default.md
          research.md
          writing.md
          coding.md
          health.md
          work.md
      review/
        proposed-memories.md
        needs-review.md
        contradictions.md
        proposed-forgetting.md
        sensitive-memory-review.md
        rejected-memories.md
      backups/
      logs/
      db/
        memory.sqlite
        README.md
      scripts/
        memory_cli.py
        memory_schema.py
        memory_store.py
        memory_scan.py
        memory_ingest_chat.py
        memory_extract.py
        memory_consolidate.py
        memory_retrieve.py
        memory_validate.py
        memory_render.py
        memory_db.py
        memory_safety.py

Canonical state should live in .json and .md.

SQLite may exist at:

00 System/0.01 agent/memory/db/memory.sqlite

but it must be rebuildable from canonical JSON/Markdown.

⸻

2. Core Design Principle

The memory layer should not be a black box.

Use this hierarchy:

Raw inputs
  ↓
Episodes
  ↓
Candidate memories
  ↓
Validated memory records
  ↓
Profile/project/procedural summaries
  ↓
Retrieval context packets

Each layer should be independently inspectable.

Do not allow the LLM to directly write canonical memory. The LLM may only propose memory changes. Scripts validate and apply.

⸻

3. Memory Types

Use strict memory types.

memory_types:
  - profile
  - preference
  - constraint
  - project
  - episode
  - semantic
  - procedural
  - relationship
  - source-derived
  - vault-derived
  - chat-derived
  - temporal
  - contradiction

Type Definitions

profile

Stable, high-level user context.

Example:

User is a sociology PhD candidate at UC Davis.

Use sparingly.

preference

A stable or recurring preference.

Example:

User prefers concise, analytically dense responses.

constraint

A durable constraint that should affect future behavior.

Example:

User prefers local-first systems using Markdown, JSON, and Python when feasible.

project

A memory about an active or dormant project.

Example:

User is building a local-first Obsidian vault management and retrieval agent.

episode

A specific event, conversation, or dated occurrence.

Example:

On 2026-06-08, user asked for a memory layer specification for the Obsidian vault agent.

semantic

A general fact distilled from repeated interactions or documents.

Example:

The vault agent should use deterministic scripts for file modification and LLMs only for narrow proposals.

procedural

Instructions about how agents should behave.

Example:

When retrieving vault context, start with memory and retrieval indexes before opening full notes.

relationship

Information about people, organizations, collaborators, advisors, institutions, or tools in relation to the user.

source-derived

Memory extracted from a source note, PDF, article, report, or literature note.

vault-derived

Memory extracted from the Obsidian vault.

chat-derived

Memory extracted from chat logs placed in memory/chats/inbox/.

temporal

A memory whose truth depends strongly on time.

Example:

User is preparing for surgery on 2026-06-09.

This should expire or require refresh after the relevant date.

contradiction

A record of conflicting memories that require reconciliation.

⸻

4. Canonical Memory Record Schema

Each memory must be stored as a JSON object in:

00 System/0.01 agent/memory/semantic/memories.json

or another type-specific JSON file if the implementation chooses to shard memory by type.

Recommended canonical schema:

{
  "id": "mem_20260608_000001",
  "type": "project",
  "claim": "User is building a local-first Obsidian vault management and retrieval agent.",
  "summary": "The user is designing a conservative Obsidian-based system where scripts manage schema, templates, manifests, summaries, retrieval indexes, and memory while LLMs only produce validated proposals.",
  "status": "active",
  "source_kind": "chat",
  "source_refs": [
    {
      "source_id": "chat_20260608_001",
      "path": "00 System/0.01 agent/memory/chats/processed/chat_20260608_001.md",
      "turn_ids": ["u_001"]
    }
  ],
  "entities": [
    "Obsidian",
    "vault-agent",
    "memory layer",
    "Codex",
    "OpenCode",
    "Hermes",
    "OpenClaw"
  ],
  "domains": [
    "computing",
    "personal-knowledge-management",
    "local-first-ai"
  ],
  "projects": [
    "obsidian-vault-agent"
  ],
  "valid_from": "2026-06-08",
  "valid_until": null,
  "created_at": "2026-06-08T13:00:00-07:00",
  "updated_at": "2026-06-08T13:00:00-07:00",
  "last_accessed_at": null,
  "access_count": 0,
  "confidence": "high",
  "importance": "high",
  "sensitivity": "low",
  "stability": "medium",
  "review_status": "unreviewed",
  "derived_from": [],
  "supersedes": [],
  "superseded_by": [],
  "contradicts": [],
  "related_memories": [],
  "retrieval_hints": [
    "Use when helping with Obsidian vault architecture.",
    "Use when designing agent memory systems.",
    "Use when writing Codex/OpenCode implementation instructions."
  ],
  "do_not_use_when": [
    "Do not use for unrelated casual questions."
  ],
  "hash": "sha256-of-normalized-record"
}

⸻

5. Required Memory Fields

Every canonical memory record must include:

required_fields:
  - id
  - type
  - claim
  - status
  - source_kind
  - source_refs
  - created_at
  - updated_at
  - confidence
  - importance
  - sensitivity
  - review_status
  - hash

Allowed statuses:

memory_statuses:
  - active
  - dormant
  - expired
  - superseded
  - archived
  - rejected
  - needs_review

Allowed confidence values:

confidence:
  - low
  - medium
  - high

Allowed importance values:

importance:
  - low
  - medium
  - high
  - critical

Allowed sensitivity values:

sensitivity:
  - low
  - medium
  - high
  - restricted

Allowed stability values:

stability:
  - fleeting
  - temporary
  - medium
  - durable

⸻

6. Memory IDs

Use stable memory IDs.

Recommended format:

mem_YYYYMMDD_NNNNNN

Example:

mem_20260608_000001

Do not reuse IDs.

Maintain ID counters in:

00 System/0.01 agent/memory/memory-state.json

Example:

{
  "schema_version": "0.1.0",
  "last_memory_id": 143,
  "last_episode_id": 28,
  "last_chat_id": 12,
  "last_consolidation": "2026-06-08T13:00:00-07:00",
  "last_retrieval_rebuild": "2026-06-08T13:00:00-07:00"
}

⸻

7. Chat Ingestion

Chats should be written to:

00 System/0.01 agent/memory/chats/inbox/

Use one Markdown or JSON file per chat export.

Recommended Markdown format:

---
chat_id: chat_20260608_001
source: chatgpt
created: 2026-06-08T13:00:00-07:00
processed: false
hash: ""
---
# Chat: Obsidian Memory Layer
## Turn u_001
Role: user
<message>
## Turn a_001
Role: assistant
<message>

Recommended JSON format:

{
  "chat_id": "chat_20260608_001",
  "source": "chatgpt",
  "created": "2026-06-08T13:00:00-07:00",
  "processed": false,
  "turns": [
    {
      "turn_id": "u_001",
      "role": "user",
      "content": "..."
    },
    {
      "turn_id": "a_001",
      "role": "assistant",
      "content": "..."
    }
  ]
}

The ingestion script should:

1. Validate chat file structure.
2. Compute hash.
3. Create a chat manifest entry.
4. Move valid chats to chats/processed/.
5. Move malformed chats to chats/review/.
6. Extract episodes.
7. Optionally request LLM-proposed candidate memories.
8. Validate proposals.
9. Queue uncertain memories for review.

⸻

8. Chat Manifest

Maintain:

00 System/0.01 agent/memory/chats/manifests/chat-manifest.json

Schema:

{
  "chats": [
    {
      "chat_id": "chat_20260608_001",
      "path": "00 System/0.01 agent/memory/chats/processed/chat_20260608_001.md",
      "source": "chatgpt",
      "created": "2026-06-08T13:00:00-07:00",
      "processed_at": "2026-06-08T13:05:00-07:00",
      "hash": "abc123",
      "turn_count": 12,
      "memory_extraction_status": "processed",
      "episode_count": 4,
      "candidate_memory_count": 7,
      "accepted_memory_count": 3,
      "needs_review_count": 2
    }
  ]
}

⸻

9. Episode Layer

Episodes are append-only records of events, not stable beliefs.

Store canonical episode records in:

00 System/0.01 agent/memory/episodes/episodes.json

Example:

{
  "id": "ep_20260608_000001",
  "type": "chat_turn",
  "title": "User requested Obsidian memory layer implementation details",
  "summary": "User asked for an implementation plan for a memory layer inside the Obsidian vault agent, including chat ingestion, JSON/Markdown state, optional SQLite, and scheduled consolidation.",
  "source_kind": "chat",
  "source_refs": [
    {
      "chat_id": "chat_20260608_001",
      "turn_ids": ["u_001"]
    }
  ],
  "timestamp": "2026-06-08T13:00:00-07:00",
  "entities": [
    "Obsidian",
    "vault-agent",
    "memory",
    "Hermes",
    "OpenClaw"
  ],
  "projects": [
    "obsidian-vault-agent"
  ],
  "domains": [
    "computing"
  ],
  "importance": "high",
  "sensitivity": "low",
  "derived_memories": [
    "mem_20260608_000001"
  ],
  "hash": "sha256"
}

Rules:

1. Episodes are never overwritten except for metadata correction.
2. If an episode was mis-summarized, create a corrected version and mark the earlier record as superseded.
3. Episodes can support memory claims, but should not themselves be treated as always-current facts.

⸻

10. Candidate Memory Extraction

LLMs may propose candidate memories but may not directly apply them.

Candidate memory proposals should go to:

00 System/0.01 agent/memory/review/proposed-memories.md

and optionally:

00 System/0.01 agent/memory/review/proposed-memories.json

LLM output schema:

{
  "source_id": "chat_20260608_001",
  "candidate_memories": [
    {
      "type": "project",
      "claim": "User is building a local-first Obsidian vault management and retrieval agent.",
      "summary": "The user is designing a vault-native system for schema management, templating, retrieval indexes, and memory.",
      "confidence": "high",
      "importance": "high",
      "sensitivity": "low",
      "stability": "medium",
      "entities": ["Obsidian", "vault-agent"],
      "domains": ["computing", "personal-knowledge-management"],
      "projects": ["obsidian-vault-agent"],
      "valid_from": "2026-06-08",
      "valid_until": null,
      "retrieval_hints": [
        "Use when helping with the vault-agent architecture."
      ],
      "do_not_use_when": [
        "Do not use for unrelated general questions."
      ],
      "reason": "The user explicitly described this as an active system they are building."
    }
  ],
  "proposed_forgetting": [],
  "possible_contradictions": [],
  "warnings": []
}

The validator must reject candidates that:

1. Lack a source reference.
2. Use unknown memory types.
3. Use invalid confidence/importance/sensitivity values.
4. Make overly broad psychological or identity claims.
5. Convert temporary states into durable profile facts.
6. Contain sensitive memory without explicit user request or review.
7. Include unsupported claims not grounded in the source.
8. Duplicate an existing memory without declaring a merge/supersession relation.

⸻

11. Memory Consolidation

Implement a consolidation command:

vault-agent memory consolidate

Suggested options:

vault-agent memory consolidate --chats
vault-agent memory consolidate --vault
vault-agent memory consolidate --projects
vault-agent memory consolidate --profile
vault-agent memory consolidate --all
vault-agent memory consolidate --dry-run
vault-agent memory consolidate --since 2026-06-01

Consolidation should:

1. Read unprocessed chats.
2. Read stale vault-derived summaries.
3. Read current memory records.
4. Generate candidate additions, revisions, expirations, and contradictions.
5. Validate all proposed changes.
6. Apply deterministic changes.
7. Queue uncertain changes for review.
8. Rebuild memory retrieval files.
9. Log all actions.

Consolidation should produce patches, not full rewrites.

Example patch:

{
  "patch_id": "patch_20260608_000001",
  "operations": [
    {
      "op": "add_memory",
      "memory": {
        "id": "mem_20260608_000001",
        "type": "project",
        "claim": "User is building a local-first Obsidian vault management and retrieval agent."
      }
    },
    {
      "op": "expire_memory",
      "memory_id": "mem_20260601_000004",
      "reason": "The date-specific context is now past."
    }
  ]
}

Allowed operations:

memory_patch_operations:
  - add_memory
  - update_memory
  - expire_memory
  - supersede_memory
  - archive_memory
  - reject_memory
  - mark_needs_review
  - add_contradiction
  - resolve_contradiction
  - increment_access
  - update_profile_summary
  - update_project_summary

⸻

12. Temporal Validity

Every memory should be evaluated for temporal validity.

Use these fields:

{
  "valid_from": "2026-06-08",
  "valid_until": null,
  "temporal_status": "current",
  "refresh_after": "2026-07-08",
  "expiry_reason": null
}

Allowed temporal statuses:

temporal_status:
  - current
  - future
  - expired
  - uncertain
  - timeless

Rules:

1. Memories with explicit dates should receive valid_from and, where appropriate, valid_until.
2. Surgery, travel, deadlines, temporary symptoms, current emotional states, and active logistics should usually get expiry dates.
3. Durable preferences should not expire automatically, but may receive refresh_after.
4. Old project states should be marked needs-refresh if not accessed or confirmed after a configured interval.
5. Expired memories should not be retrieved unless historical context is requested.

⸻

13. Contradiction Handling

Contradictions should be explicit, not silently overwritten.

Store contradictions in:

00 System/0.01 agent/memory/review/contradictions.md

and optionally:

00 System/0.01 agent/memory/review/contradictions.json

Example contradiction record:

{
  "id": "con_20260608_000001",
  "memory_ids": [
    "mem_20260601_000010",
    "mem_20260608_000003"
  ],
  "description": "One memory says the user wants a fully Markdown/JSON-only memory system; another allows SQLite as useful.",
  "possible_resolution": "Treat Markdown/JSON as canonical and SQLite as a rebuildable cache.",
  "status": "resolved",
  "resolved_by": "deterministic_rule",
  "resolved_at": "2026-06-08T13:00:00-07:00"
}

Resolution rules:

1. If both memories can be true in different scopes, narrow their scopes.
2. If one is newer and directly supersedes the other, mark the older memory superseded.
3. If the contradiction is sensitive or ambiguous, queue for human review.
4. If the contradiction is merely an apparent tension, create a synthesized memory.

⸻

14. Profile Memory

Profile memory should be compact and manually reviewable.

Canonical Markdown:

00 System/0.01 agent/memory/profile/00 current-profile.md

This file should not be a giant biography. It should be a retrieval aid.

Recommended structure:

# Current Profile Memory
Generated from reviewed memory records.
Last updated: 2026-06-08T13:00:00-07:00
## Stable Context
- User is a sociology PhD candidate at UC Davis.
- User works with Obsidian, local LLMs, and local-first automation.
## Communication Preferences
- Prefer concise, precise, analytically dense responses.
- Prefer practical implementation details over vague brainstorming.
## Active Projects
- Obsidian vault management and retrieval agent.
- Local-first memory and retrieval architecture.
- Dissertation work involving epistemology, STS, feminist epistemology, Buddhist philosophy, and TTRPGs.
## Durable Constraints
- Prefer Markdown, JSON, YAML, Python, and local-first systems.
- Prefer deterministic scripts for file modification.
- Prefer LLMs only for bounded classification, extraction, summarization, and proposal generation.
## Use With Care
- Health-related memories may be time-sensitive and should not be overgeneralized.
- Temporary distress, deadlines, surgery preparation, and acute logistics should not be treated as stable identity.

Also maintain machine-readable profile:

00 System/0.01 agent/memory/profile/profile.json

The profile should be regenerated from selected active memories, not hand-inferred from raw chats alone.

⸻

15. Project Memory

Project memory should be organized by project.

Folder:

00 System/0.01 agent/memory/projects/by-project/

Example:

00 System/0.01 agent/memory/projects/by-project/obsidian-vault-agent.md

Project memory format:

# Project Memory: obsidian-vault-agent
Project ID: obsidian-vault-agent
Status: active
Last updated: 2026-06-08T13:00:00-07:00
## Goal
Build a conservative, local-first Obsidian vault management system that supports schema management, note processing, retrieval indexes, and agent-readable memory.
## Design Commitments
- Vault-native.
- Markdown/JSON canonical state.
- Optional SQLite cache.
- LLMs propose; scripts validate and apply.
- No deletion of user-authored note content.
- Progressive retrieval.
- Inspectable memory.
## Current Architecture
- `00 System/0.01 agent/` contains machine-readable state.
- `00 System/0.02 templates/` contains human-editable templates and schema documentation.
- `retrieval/` contains vault maps, catalogs, summaries, and indexes.
- `memory/` contains profile, project, semantic, episodic, procedural, and temporal memory.
## Open Questions
- Whether to use SQLite by default or only when enabled.
- How much memory consolidation should run automatically versus require review.
- How aggressive expiry should be for temporary project states.
## Related Memories
- mem_20260608_000001 — User is building a local-first Obsidian vault management and retrieval agent.

⸻

16. Procedural Memory

Procedural memory stores how agents should act.

Folder:

00 System/0.01 agent/memory/procedural/

Files:

agent-behavior.md
retrieval-rules.md
writing-style.md
tool-use-rules.md
procedural.json

Example retrieval-rules.md:

# Procedural Memory: Retrieval Rules
## Default Retrieval Order
1. Read `00 System/0.01 agent/memory/retrieval/00 memory-retrieval-readme.md`.
2. Read the relevant memory context packet.
3. Read `memory/retrieval/03 memory-brief.md`.
4. Read project memory if the query maps to an active project.
5. Read vault retrieval files:
   - `retrieval/01 vault-map.md`
   - `retrieval/02 note-catalog.md`
   - `retrieval/04 summary-brief.md`
6. Open standard or deep summaries for selected candidate notes.
7. Open full notes only when necessary.
## Rules
- Do not scan the whole vault first.
- Do not use expired memories as current.
- Prefer memories with source references and high confidence.
- Treat health, identity, relationship, and temporary emotional-state memories cautiously.
- If memory conflicts with the current user message, trust the current user message and mark memory for review.

Procedural memories should be few, stable, and manually reviewable.

⸻

17. Memory Retrieval System

Create:

00 System/0.01 agent/memory/retrieval/

00 memory-retrieval-readme.md

# Memory Retrieval Instructions for Agents
Do not scan the whole vault first.
Start here:
1. `01 memory-map.md` — overview of memory folders and counts.
2. `02 memory-catalog.md` — compact list of active memories.
3. `03 memory-brief.md` — one-line summaries of active memories.
4. `04 memory-context-packets.md` — available prebuilt context packets.
5. `context-packets/` — task-specific compact memory packets.
6. `indexes/` — memory grouped by entity, domain, project, type, status, and validity.
7. `profile/00 current-profile.md` — compact reviewed user profile.
8. `projects/by-project/` — project-specific memory.
9. Full memory JSON only if necessary.
Rules:
- Prefer active and reviewed memories.
- Do not treat expired, superseded, or rejected memories as current.
- Use source references when making claims based on memory.
- If a current user message contradicts memory, prefer the current message and flag memory for review.
- Do not edit memory during retrieval.

01 memory-map.md

Generated file containing:

# Memory Map
Last rebuilt: timestamp
## Counts
| Category | Count |
|---|---:|
| Active memories | X |
| Dormant memories | X |
| Expired memories | X |
| Superseded memories | X |
| Needs review | X |
| Episodes | X |
| Processed chats | X |
| Unprocessed chats | X |
## Memory Folders
tree here
## Active Projects
- obsidian-vault-agent
- dissertation
- data-centers
## High-Level Retrieval Advice
Start with profile and project memory. Use semantic memories only after selecting a relevant domain or project.

02 memory-catalog.md

# Memory Catalog
| ID | Type | Claim | Status | Confidence | Importance | Validity | Projects | Updated |
|---|---|---|---|---|---|---|---|---|
| mem_20260608_000001 | project | User is building a local-first Obsidian vault management and retrieval agent. | active | high | high | current | obsidian-vault-agent | 2026-06-08 |

03 memory-brief.md

# Memory Brief
## mem_20260608_000001
Type: project  
Status: active  
Projects: obsidian-vault-agent  
Summary: User is designing a local-first Obsidian vault agent with schema, retrieval, and memory layers using deterministic scripts plus bounded LLM proposals.

04 memory-context-packets.md

# Memory Context Packets
Available packets:
- `context-packets/default.md` — general user/project context.
- `context-packets/research.md` — academic/research context.
- `context-packets/writing.md` — writing style and drafting context.
- `context-packets/coding.md` — coding, local LLM, Obsidian, automation context.
- `context-packets/health.md` — guarded, time-sensitive health context.
- `context-packets/work.md` — UC Davis/data-center/work project context.

⸻

18. Context Packets

Context packets are compact, generated Markdown files for agents.

They should be small enough to load into most LLM prompts.

Folder:

00 System/0.01 agent/memory/retrieval/context-packets/

Example:

# Context Packet: coding
Generated: 2026-06-08T13:00:00-07:00
## Use For
Use this packet when the user asks about coding, local tooling, Obsidian automation, local LLMs, retrieval systems, scripts, or agent architecture.
## Relevant Stable Context
- User prefers local-first systems.
- User prefers Python unless another tool is clearly better.
- User uses Obsidian, BBEdit, local LLMs, and command-line tools.
- User prefers deterministic scripts for file modification and LLMs for bounded proposals.
## Active Projects
### obsidian-vault-agent
User is building an Obsidian vault management system with schema, templates, manifests, retrieval indexes, and memory.
## Procedural Preferences
- Give implementation-ready details.
- Favor modular files and clear command behavior.
- Include safety rules and acceptance criteria.
- Avoid vague architectural handwaving.
## Relevant Memory IDs
- mem_20260608_000001

Context packet generation should be deterministic from active memory records.

Do not hand-edit generated context packets unless the file explicitly says it is human-editable.

⸻

19. Vault-Derived Memory

The memory layer should be able to ingest from the existing vault retrieval layer.

Inputs:

00 System/0.01 agent/manifest.json
00 System/0.01 agent/retrieval/02 note-catalog.md
00 System/0.01 agent/retrieval/04 summary-brief.md
00 System/0.01 agent/retrieval/summaries-standard/
00 System/0.01 agent/retrieval/deep-summaries/

Command:

vault-agent memory ingest-vault

Behavior:

1. Read note manifest and summaries.
2. Identify project notes, index notes, literature notes, concept notes, and claim notes.
3. Generate or update vault-derived memories only when a note summary indicates durable relevance.
4. Do not create a memory for every note by default.
5. Prefer project-level and domain-level memory over duplicating the retrieval index.
6. Store source references to note IDs and note paths.
7. Mark stale if source note body hash or summary hash changes.

Vault-derived memory should avoid duplicating the retrieval system. Its purpose is not to remember every note. Its purpose is to remember what kinds of knowledge and projects exist in the vault.

⸻

20. Memory Commands

Extend the main CLI with memory subcommands.

vault-agent memory init
vault-agent memory scan
vault-agent memory validate
vault-agent memory ingest-chat
vault-agent memory ingest-vault
vault-agent memory extract
vault-agent memory consolidate
vault-agent memory rebuild
vault-agent memory retrieve
vault-agent memory status
vault-agent memory expire
vault-agent memory review

memory init

Creates memory folder structure and starter files.

Must not overwrite human-edited files without backup.

memory scan

Scans memory folders, updates memory manifest, checks for malformed records.

Does not modify canonical memories except manifest/state.

memory validate

Checks:

* malformed memory JSON
* missing required fields
* invalid memory types
* invalid statuses
* invalid confidence/importance/sensitivity values
* missing source refs
* duplicate memory IDs
* stale hashes
* expired memories still marked active
* superseded memories still retrieved
* profile summary out of date
* context packets out of date
* SQLite cache out of date
* sensitive memories lacking review
* memories with no provenance

memory ingest-chat

Processes files in:

memory/chats/inbox/

For each chat:

1. Validate structure.
2. Create chat manifest entry.
3. Create episode records.
4. Ask LLM for candidate memory proposals if configured.
5. Validate proposals.
6. Apply high-confidence, low-sensitivity memories if auto-accept rules allow.
7. Queue other proposals for review.
8. Move chat to processed/.
9. Update retrieval files.

memory ingest-vault

Reads vault summaries and creates/updates vault-derived memories.

Should be conservative.

memory extract

Runs LLM candidate extraction from a specific source.

Examples:

vault-agent memory extract --chat chat_20260608_001
vault-agent memory extract --note n000143
vault-agent memory extract --file "path/to/file.md"

memory consolidate

Runs consolidation over existing memory.

Tasks:

* merge duplicate memories
* expire stale temporal memories
* identify contradictions
* update project memory
* update profile memory
* update procedural summaries
* update context packets

memory rebuild

Regenerates all memory retrieval Markdown files and optional SQLite cache from canonical JSON.

Should not call the LLM.

memory retrieve

Returns a compact context packet.

Examples:

vault-agent memory retrieve --query "build Obsidian memory layer"
vault-agent memory retrieve --project obsidian-vault-agent
vault-agent memory retrieve --packet coding
vault-agent memory retrieve --domain computing --max-tokens 2000

Output should include selected memories and reasons.

memory status

Prints:

Total memories: X
Active: X
Dormant: X
Expired: X
Superseded: X
Needs review: X
Episodes: X
Chats unprocessed: X
Contradictions open: X
Profile stale: true/false
Context packets stale: true/false
SQLite cache stale: true/false
Last consolidation: timestamp

memory expire

Expires memories by ID, query, or rule.

Examples:

vault-agent memory expire --id mem_20260608_000001
vault-agent memory expire --older-than 180d --status dormant
vault-agent memory expire --temporal-past

Should support dry-run.

memory review

Applies user-approved proposed memories.

Examples:

vault-agent memory review --list
vault-agent memory review --accept memprop_20260608_000001
vault-agent memory review --reject memprop_20260608_000002
vault-agent memory review --edit memprop_20260608_000003

⸻

21. Auto-Accept Rules

Default should be conservative.

Auto-accept only when all are true:

auto_accept_memory:
  enabled: false
  allow_types:
    - project
    - preference
    - procedural
    - vault-derived
  max_sensitivity: low
  min_confidence: high
  require_source_refs: true
  reject_identity_claims: true
  reject_health_claims: true
  reject_relationship_claims: true
  reject_temporary_emotional_states: true

Recommended default:

auto_accept_memory:
  enabled: false

If enabled later, restrict it to low-sensitivity project/procedural memories.

⸻

22. Sensitive Memory Policy

Sensitive memories require review unless explicitly user-requested.

Sensitive categories:

sensitive_memory_categories:
  - health
  - mental-health
  - identity
  - relationships
  - legal
  - finances
  - precise-location
  - political-beliefs
  - religious-identity
  - trauma

Rules:

1. Do not auto-accept sensitive memories.
2. Do not turn temporary distress into durable profile memory.
3. Do not infer identity claims beyond what the user explicitly says.
4. Do not store precise addresses or private identifiers unless explicitly requested.
5. Health memories should be scoped and temporal.
6. Sensitive memories should have sensitivity: high or restricted.
7. Sensitive memories should be excluded from default context packets unless directly relevant.

⸻

23. Forgetting and Expiry

Memory should support forgetting without destroying auditability unless the user requests deletion.

Statuses:

active: usable now
dormant: retained but not normally retrieved
expired: no longer current
superseded: replaced by newer memory
archived: retained as history
rejected: proposed but not accepted
needs_review: blocked pending human review
deleted: removed by explicit user request

The system should distinguish:

1. Expire: no longer current, retained historically.
2. Archive: retained but not retrieved by default.
3. Supersede: replaced by a newer memory.
4. Reject: proposed memory was not accepted.
5. Delete: remove from canonical files only after explicit user command.

Deletion should create a tombstone unless configured otherwise:

{
  "id": "mem_20260608_000001",
  "status": "deleted",
  "deleted_at": "2026-06-08T13:00:00-07:00",
  "deletion_reason": "user_requested",
  "claim_hash": "sha256"
}

Do not preserve sensitive deleted content in tombstones unless explicitly configured.

⸻

24. Retrieval Scoring

Memory retrieval should use hybrid scoring.

Inputs:

1. semantic similarity
2. exact keyword/entity match
3. project match
4. domain match
5. recency
6. temporal validity
7. confidence
8. importance
9. review status
10. sensitivity
11. access frequency
12. explicit pinning

Recommended scoring model:

score =
  0.30 semantic_similarity
+ 0.20 entity_or_keyword_overlap
+ 0.15 project_match
+ 0.10 domain_match
+ 0.10 importance
+ 0.05 confidence
+ 0.05 recency_or_refresh
+ 0.05 pinned
- 0.50 if expired
- 0.70 if superseded
- 1.00 if rejected
- 0.30 if sensitive and not directly relevant
- 0.20 if unreviewed and confidence is not high

If no embedding backend is configured, fallback retrieval should use:

1. project match
2. domain match
3. full-text search
4. entity overlap
5. recency
6. importance

⸻

25. Optional SQLite Layer

SQLite is optional but useful.

Rule:

Canonical memory lives in JSON and Markdown.
SQLite is a rebuildable index/cache.

Path:

00 System/0.01 agent/memory/db/memory.sqlite

Tables:

CREATE TABLE memories (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  claim TEXT NOT NULL,
  summary TEXT,
  status TEXT NOT NULL,
  confidence TEXT NOT NULL,
  importance TEXT NOT NULL,
  sensitivity TEXT NOT NULL,
  stability TEXT,
  review_status TEXT NOT NULL,
  valid_from TEXT,
  valid_until TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_accessed_at TEXT,
  access_count INTEGER DEFAULT 0,
  hash TEXT NOT NULL
);
CREATE TABLE memory_sources (
  memory_id TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_id TEXT,
  path TEXT,
  turn_ids TEXT,
  note_id TEXT,
  FOREIGN KEY(memory_id) REFERENCES memories(id)
);
CREATE TABLE memory_entities (
  memory_id TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_type TEXT,
  FOREIGN KEY(memory_id) REFERENCES memories(id)
);
CREATE TABLE memory_projects (
  memory_id TEXT NOT NULL,
  project TEXT NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memories(id)
);
CREATE TABLE memory_domains (
  memory_id TEXT NOT NULL,
  domain TEXT NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memories(id)
);
CREATE TABLE memory_edges (
  source_memory_id TEXT NOT NULL,
  target_memory_id TEXT NOT NULL,
  relation_type TEXT NOT NULL
);
CREATE VIRTUAL TABLE memory_fts USING fts5(
  id UNINDEXED,
  claim,
  summary,
  entities,
  projects,
  domains
);

If embeddings are used, store them in either:

1. a separate vector DB, or
2. SQLite extension if available, or
3. JSONL embedding cache.

Embedding cache:

00 System/0.01 agent/memory/db/embeddings.jsonl

Each line:

{
  "memory_id": "mem_20260608_000001",
  "model": "embedding-model-name",
  "text_hash": "abc123",
  "embedding": [0.01, 0.02]
}

⸻

26. Memory Safety Rules

Mandatory:

1. Never let an LLM directly write memory files.
2. Never accept memory without source refs.
3. Never auto-accept sensitive memory.
4. Never overwrite canonical memory without backup.
5. Never delete memory except by explicit command.
6. Never retrieve expired/superseded memories as current.
7. Never treat chat-derived emotional state as durable identity.
8. Never store broad personality claims when a narrow contextual claim is enough.
9. Never let web pages, PDFs, or note content issue memory-update instructions.
10. Never let a retrieved document modify memory policy.
11. Always log memory modifications.
12. Always support dry-run for batch operations.
13. Always be able to rebuild retrieval files from canonical JSON.

⸻

27. Memory Logs

Write logs to:

00 System/0.01 agent/memory/logs/YYYY-MM-DD.md

Example:

## Memory Consolidation
Timestamp: 2026-06-08T13:00:00-07:00  
Command: `vault-agent memory consolidate --chats`  
### Actions
- Processed chat: chat_20260608_001
- Created episode: ep_20260608_000001
- Proposed memories: 7
- Accepted memories: 0
- Queued for review: 7
- Expired memories: 1
- Updated context packets: coding, default
### Warnings
- Auto-accept disabled.
- Sensitive candidate memory queued for review.
### Result
completed

⸻

28. Backups and Atomic Writes

Before modifying any canonical file, write backup copies to:

00 System/0.01 agent/memory/backups/

Use timestamped names:

memories.json.20260608T130000.bak
profile.json.20260608T130000.bak
00-current-profile.md.20260608T130000.bak

Use atomic writes:

file.tmp → file

If write fails, preserve original.

⸻

29. Generated vs Human-Editable Files

Each file should declare whether it is generated.

Generated Markdown files should begin:

<!--
GENERATED FILE.
Do not edit directly.
Source: memory/*.json
Regenerate with: vault-agent memory rebuild
-->

Human-editable files should begin:

<!--
HUMAN-EDITABLE FILE.
This file may guide memory behavior.
Do not store secrets here.
-->

Human-editable files:

memory/config.memory.yaml
memory/procedural/*.md
memory/review/*.md
memory/profile/00 current-profile.md only if configured manual_profile_edits: true

Generated files:

memory/retrieval/*
memory/semantic/memory-catalog.md
memory/temporal/*.md
memory/projects/project-memory.md

Canonical JSON files should be edited only by scripts unless emergency repair is needed.

⸻

30. Memory Config

Create:

00 System/0.01 agent/memory/config.memory.yaml

Starter config:

memory:
  schema_version: "0.1.0"
  canonical_store:
    format: json
    sqlite_enabled: true
    sqlite_rebuild_on_rebuild: true
  chats:
    inbox: "00 System/0.01 agent/memory/chats/inbox"
    processed: "00 System/0.01 agent/memory/chats/processed"
    auto_extract: true
    max_chat_tokens: 64000
  extraction:
    llm_required: true
    max_input_tokens: 64000
    temperature: 0.1
    candidate_limit_per_chat: 20
    candidate_limit_per_note: 10
  auto_accept_memory:
    enabled: false
    allow_types:
      - project
      - procedural
      - preference
      - vault-derived
    min_confidence: high
    max_sensitivity: low
    require_source_refs: true
  temporal:
    expire_past_events: true
    default_refresh_after_days: 90
    project_refresh_after_days: 60
    temporary_memory_default_days: 14
  retrieval:
    default_max_memories: 20
    default_max_tokens: 2000
    include_unreviewed: false
    include_sensitive_by_default: false
    include_expired_by_default: false
    build_context_packets: true
    packets:
      - default
      - research
      - writing
      - coding
      - health
      - work
  sensitivity:
    require_review_for:
      - health
      - mental-health
      - identity
      - relationships
      - legal
      - finances
      - precise-location
      - political-beliefs
      - religious-identity
      - trauma
  llm:
    provider: openai-compatible
    base_url: "http://localhost:11434/v1"
    model: "local-model-name"
    max_input_tokens: 64000
    temperature: 0.1
  embeddings:
    enabled: false
    provider: openai-compatible
    base_url: "http://localhost:11434/v1"
    model: "embedding-model-name"

⸻

31. LLM Prompt for Memory Extraction

The LLM should receive only one bounded source at a time.

Prompt contract:

You are extracting candidate long-term memories from one source.
You must return valid JSON only.
You may propose memories, but you do not decide what is stored.
The script will validate your proposal.
Rules:
- Do not invent facts.
- Do not create broad personality claims from isolated events.
- Do not turn temporary emotional states into durable traits.
- Do not create sensitive memories unless clearly relevant and explicitly supported.
- Prefer narrow, scoped, temporal claims.
- Include source-grounded reasons.
- If unsure, lower confidence or set needs_review.
- If a memory is temporary, include valid_until or refresh_after.
- If an existing memory should be changed, propose a patch.
- Do not include secrets.
- Do not modify files.

Required input:

1. source metadata
2. existing relevant memories
3. allowed memory schema
4. source content or excerpt
5. current date
6. output JSON schema

⸻

32. LLM Prompt for Memory Consolidation

The consolidation LLM should not see the whole memory store.

It should see:

1. candidate new memories
2. top similar existing memories
3. potentially contradicted memories
4. temporal candidates needing refresh
5. schema

It should return patches only.

Output:

{
  "patches": [
    {
      "op": "supersede_memory",
      "old_memory_id": "mem_20260601_000004",
      "new_memory": {
        "type": "temporal",
        "claim": "..."
      },
      "reason": "Newer source updates the project status."
    }
  ],
  "needs_review": [],
  "warnings": []
}

⸻

33. Retrieval Output Format

vault-agent memory retrieve should output Markdown by default.

Example:

# Retrieved Memory Context
Query: build Obsidian memory layer  
Generated: 2026-06-08T13:00:00-07:00  
## Selected Context
### mem_20260608_000001 — project
User is building a local-first Obsidian vault management and retrieval agent.
Why retrieved: project/entity match; high importance; current.
Source: `memory/chats/processed/chat_20260608_001.md`
### mem_20260608_000002 — procedural
When modifying vault files, LLMs should only produce JSON proposals and scripts should validate and apply changes.
Why retrieved: procedural rule relevant to implementation.
Source: `memory/procedural/agent-behavior.md`
## Notes
Expired and superseded memories were excluded.
Sensitive memories were excluded because the query did not require them.

Optional JSON output:

vault-agent memory retrieve --query "..." --json

⸻

34. Integration With Main Vault Retrieval

The memory layer and retrieval layer should be linked but not merged.

Main retrieval answers:

What notes exist?
What do they contain?
Where should an agent look?

Memory answers:

What durable context should an agent know before helping?
What projects are active?
What preferences and constraints govern behavior?
What prior decisions affect this task?

Recommended agent startup order:

1. Read memory/retrieval/00 memory-retrieval-readme.md
2. Read memory/retrieval/context-packets/default.md
3. If task-specific, read relevant context packet
4. Read main retrieval/00 retrieval-readme.md
5. Read main retrieval/02 note-catalog.md or 04 summary-brief.md
6. Read project/domain indexes
7. Open selected summaries
8. Open full notes only if needed

⸻

35. Cron / Scheduled Jobs

Suggested scheduled commands:

Every 15 minutes

vault-agent memory ingest-chat --max-files 5

Hourly

vault-agent memory consolidate --chats --dry-run

or, if trusted:

vault-agent memory consolidate --chats

Daily

vault-agent scan
vault-agent validate
vault-agent rebuild-retrieval
vault-agent memory ingest-vault
vault-agent memory consolidate --all
vault-agent memory rebuild

Weekly

vault-agent memory validate
vault-agent memory expire --temporal-past
vault-agent memory consolidate --profile --projects
vault-agent memory rebuild

Default should avoid unsupervised high-risk writes. Cron jobs should be conservative unless explicitly configured.

⸻

36. Acceptance Criteria for Memory Layer

The memory layer is successful when:

1. vault-agent memory init creates the required memory structure.
2. Chats can be dropped into memory/chats/inbox/.
3. vault-agent memory ingest-chat creates episodes and candidate memories.
4. Candidate memories are validated before storage.
5. Sensitive memories are queued for review.
6. Memory records include source references.
7. Memory records include temporal validity fields.
8. Expired memories are excluded from default retrieval.
9. Superseded memories are excluded from default retrieval.
10. vault-agent memory rebuild regenerates Markdown retrieval files from JSON.
11. SQLite can be deleted and rebuilt from canonical files.
12. vault-agent memory retrieve returns a compact context packet.
13. Generated profile/project/procedural summaries are inspectable.
14. Contradictions are recorded rather than silently overwritten.
15. Every memory modification is logged.
16. Backups are created before canonical files are changed.
17. The system supports dry-run for batch operations.
18. Agents can use memory without scanning the whole vault.
19. The memory layer does not duplicate the entire vault retrieval index.
20. The memory system remains readable and useful even without SQLite.

⸻

37. Minimum Viable Implementation Order

Build in this order:

1. memory init
2. canonical memory schema
3. memory state and manifest
4. memory validate
5. chat inbox format
6. chat manifest
7. episode extraction without LLM
8. memory proposal schema
9. LLM memory extraction
10. proposed-memory review queue
11. canonical memory writer with backups and atomic writes
12. memory retrieval Markdown generation
13. context packet generation
14. project/profile summary generation
15. optional SQLite rebuild
16. retrieval scoring
17. temporal expiry
18. contradiction detection
19. scheduled consolidation
20. tests

⸻

38. Recommended MVP Scope

For the first working version, implement only:

vault-agent memory init
vault-agent memory validate
vault-agent memory ingest-chat
vault-agent memory rebuild
vault-agent memory retrieve
vault-agent memory status

Initial memory files:

memory/semantic/memories.json
memory/episodes/episodes.json
memory/profile/profile.json
memory/chats/manifests/chat-manifest.json
memory/retrieval/02 memory-catalog.md
memory/retrieval/03 memory-brief.md
memory/retrieval/context-packets/default.md
memory/retrieval/context-packets/coding.md

Delay advanced features:

* embeddings
* SQLite
* contradiction resolver
* automatic forgetting
* vault-derived memory
* deep project consolidation
* cron auto-accept

The MVP should first prove that memory can be safely ingested, reviewed, rebuilt, and retrieved.

⸻

39. Non-Negotiable Design Rule

The memory system must maintain a distinction between:

What happened
What was inferred
What is currently true
What is useful to retrieve
What the user explicitly approved

If those collapse into one undifferentiated “memory,” the system will eventually become stale, creepy, or wrong.

Keep the layers separate.

A few design choices I’d treat as settled:

* Markdown/JSON should be canonical. SQLite is useful, but it should be disposable.
* Chats should become episodes first, memories second. Otherwise every emotionally intense or temporary conversation risks becoming a durable “fact.”
* Context packets are the key agent interface. Most agents should not touch raw memory JSON unless doing maintenance.
* Auto-accept should start disabled. You can loosen it later for low-sensitivity project/procedural memory.
* Memory should not duplicate vault retrieval. Vault retrieval tells the agent where knowledge is. Memory tells the agent what durable context matters before acting.

The main architectural move is this: put memory/ beside retrieval/, not inside it. Retrieval is about the vault’s notes; memory is about durable agent context, prior decisions, and temporal continuity. They should cross-reference each other, but they should not become the same subsystem.