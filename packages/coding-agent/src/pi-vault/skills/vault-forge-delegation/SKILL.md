---
name: vault-forge-delegation
description: Delegate deterministic transcription and file conversion to pi-forge, then optionally submit completed text artifacts as pending vault proposals.
---

# Vault Forge Delegation

Use `forge_transcribe` for one recording and `forge_convert_files` for supported
file conversion. Ask for missing required paths, recording type, conversion
target, output root, or publication metadata. Calls are synchronous; wait for
the structured result before continuing.

Treat `status` as authoritative. Report the run directory, relevant artifacts,
counts, warnings, and structured errors. Do not treat partial files as success,
install dependencies through the bridge, or retry without user approval.

For a completed `.md` or `.txt` artifact under the configured forge output root,
use `vault_submit_artifact` to create a validated pending proposal. Include the
pi-forge task ID and operation. Report the proposal path and destination, and
state that the artifact is not integrated until it is explicitly reviewed,
approved, and applied through pi-vault.
