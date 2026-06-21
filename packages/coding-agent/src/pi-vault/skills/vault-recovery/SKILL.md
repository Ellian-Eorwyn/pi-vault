---
name: vault-recovery
description: Inspect and recover versioned pi-vault changes. Use when the user wants to see what a maintenance run changed, restore one path, undo a run, diagnose a partial failure, or verify Git-backed vault safety.
---

# Vault Recovery

1. Run status and inspect the target run metadata and diff before restoring anything.
2. Prefer path-level restore when only one result is wrong.
3. Use run undo only for paths recorded in that run. Do not reset the entire vault.
4. Treat protected paths and full restores as explicit user decisions.
5. After recovery, rerun status, validation, and retrieval rebuild if note locations or contents changed.
6. Report restored and unresolved paths precisely.

Do not push, rewrite history, or use destructive Git cleanup commands.
