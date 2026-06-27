---
name: vault-review
description: Inspect, explain, approve, reject, or apply pi-vault proposal and model-block queues. Use when changes are pending, a maintenance run returns review-required, or the user wants an exact preview before vault mutation.
---

# Vault Review

1. Run `vault_review_apply` with `operation: "review"` and inspect every validation error before approval.
2. Explain operations by affected path, including destinations and link rewrites for moves.
3. Defer schema changes, ambiguous model output, collisions, protected paths, low confidence, and unexpectedly broad changes.
4. Mark only user-accepted proposals approved. Applying proposals must remain a separate deterministic step.
5. After apply, run status, validation, Obsidian checks, and retrieval rebuild.
6. Report the version run ID, changed files, remaining proposals, and undo command.

Never edit proposal status or ordinary notes merely to make validation pass.
