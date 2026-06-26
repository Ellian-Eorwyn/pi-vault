# pi-vault

pi-vault is an Obsidian vault agent built on the [pi agent harness](https://github.com/earendil-works/pi). It combines pi's interactive model session with a deterministic Python engine for vault scanning, schema and norms management, reviewable proposals, bounded inbox maintenance, whole-note analysis and guarded note-body refinement, Obsidian validation, reports, and Git-backed rollback.

## Install

macOS and Linux, from a checkout:

```bash
./install.sh
```

Or bootstrap without a checkout (clones into `~/.local/share/pi-vault/repository`):

```bash
curl -fsSL https://raw.githubusercontent.com/Ellian-Eorwyn/pi-vault/main/install.sh | bash
```

The installer builds the Node harness, creates a managed Python environment under `~/.pi-vault/runtime/venv`, and symlinks `pi-vault`, `pi-vault-mcp`, and `pi-vault-update` into `~/.local/bin`. Add that directory to `PATH` if it is not already present.

New installations default to the OpenAI-compatible `code` model at `http://llms:8008/v1`, with a 262,144-token context window and 32,768-token maximum output. The defaults are written to `~/.pi-vault/agent/models.json` and `settings.json` only when those files do not already exist. Edit those files to use another backend or model.

## Update

```bash
pi-vault-update
```

Updates pull the latest revision and rebuild the CLI or Python engine only when their sources changed.

## Uninstall

Preview a complete local uninstall:

```bash
./uninstall.sh --dry-run
```

Then remove the managed checkout, launchers, runtime, caches, settings, credentials, and sessions:

```bash
./uninstall.sh
```

Use `--yes` for noninteractive removal or `--keep-state` to preserve runtime and agent state. The uninstaller never deletes the development checkout it is launched from.

## First launch

Open a terminal at an Obsidian vault root and run:

```bash
pi-vault
```

When `.pi-vault/config.yaml` is missing, the interactive extension offers the dashboard-first defaults, customization, or cancellation. It creates `00 Inbox`, `01 Dashboards`, the default content folders, and `99 System`, then scans and starts schema/purpose onboarding. The bootstrap remains inside the vault:

```yaml
version: 1
system_dir: "99 System"
inbox_dir: "00 Inbox"
dashboards_dir: "01 Dashboards"
content_dirs:
  people: "02 People"
  contacts: "02 People/02.01 Contacts"
  authors: "02 People/02.02 Authors"
  organizations: "03 Organizations"
  work: "04 Work"
  administrative: "05 Administrative"
  health: "05 Administrative/05.01 Health"
  home: "05 Administrative/05.02 Home"
  finance: "05 Administrative/05.03 Finance"
  travel: "05 Administrative/05.04 Travel"
  administrative_general: "05 Administrative/05.05 General"
  thoughts: "06 Thoughts"
  sources: "07 Sources"
integrations:
  pi_forge:
    command: "/Users/you/.local/bin/pi-forge-mcp"
    read_roots:
      - "/Users/you/Documents/Recordings"
    output_root: "/Users/you/Documents/Forge Output"
```

Detailed purpose, conventions, schema, templates, generated retrieval data, reports, proposals, and versioning metadata live under the selected system folder.

`01 Dashboards/Home.md` is the primary navigation surface. Dashboard notes combine preserved curated Markdown with managed embedded Bases. Folder placement remains secondary, while bounded inbox sorting proposes deterministic destinations and may apply only current, warning-free, high-confidence moves.

Interactive launches from the vault root or any descendant resolve to the same vault root and resume the latest vault-local session unless an explicit session option is supplied. Session transcripts and debug logs are stored under `<system folder>/0.01 agent/`; first-launch transcripts use `.pi-vault/onboarding-sessions/` until the selected system folder is available, then migrate on the next launch. Each startup runs a read-only assessment and asks the model to summarize prior work, health, schema state, inbox changes, pending review, and concrete next actions. pi-vault ignores project `.pi` prompt/config overlays and loads the bundled vault skills plus purpose, conventions, contract, schema, norms lock, template norms, and retrieval context directly from the configured system folder. `~/.pi-vault/agent` remains a vault-neutral hub for model credentials, model definitions, UI settings, and reusable resources.

Schema state is explicit: `provisional` means no norms lock exists and bundled schema/templates are only onboarding defaults; `locked` means the current schema and norms must be followed exactly; `drifted` means current files differ from the lock and broad processing must wait for review. Recommendations remain proposal-first in every state.

Before broad organization, pi-vault scans existing conventions, plans norms with the user, generates reviewable proposals, and writes a norms lock only after approval.

The optional pi-forge integration exposes sequential transcription and conversion tools. Completed Markdown or text artifacts can be submitted with `vault_submit_artifact`; submission creates a validated pending proposal and never approves, applies, or edits an inbox note directly. The restricted `pi-vault-mcp --vault-root <vault> --read-root <forge-output>` server provides the same pending-only handoff to pi-forge.

## Automation

```bash
pi-vault vault init --system-dir "99 System" --inbox-dir "00 Inbox"
pi-vault vault status --json
pi-vault vault propose-inbox-sort --max-notes 2 --safe-only
pi-vault vault propose-vault-layout --dry-run
pi-vault vault maintain --max-notes 2
pi-vault vault review
pi-vault vault undo <run-id>
pi-vault vault hermes-run --root /path/to/vault-parent --max-notes 2 --apply-safe
```

Uninitialized noninteractive commands fail with an initialization instruction. Scheduled maintenance is bounded, serial, report-driven, and leaves ambiguous, low-confidence, warning-bearing, or schema-changing work pending for review.

## Safety model

- Vault-specific policy stays in the vault.
- Models produce structured proposals; deterministic code validates and applies them.
- All model inference runs through the user-configured pi/engine LLM backend; pi-vault never calls Claude, Codex, or any third-party model unless you explicitly point the harness at that provider's API.
- Moves and renames use `move_note` operations with collision checks, inbound wikilink updates, backups, and versioned rollback.
- Note-body refinement reformats only: a deterministic word-preservation guard rejects any rewrite that drops or substitutes the author's words, frontmatter is preserved byte-for-byte, and wording and meaning never change.
- Notes are never deleted automatically.
- Broad work requires current locked norms and readiness checks.
- Every write run records changed files and an undo command.

## Development

```bash
npm install --ignore-scripts
npm run check
(cd vault-manager && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests)
./test.sh
```

The TypeScript packages remain close to upstream pi so upstream changes can be merged without moving vault behavior into the harness core. The vault engine lives in `vault-manager/` and is bundled as a Python sidecar.

### Project docs

These pi-first dev-control docs live at the repo root and guide ongoing development:

- [`START_HERE.md`](START_HERE.md) — session startup protocol and operating rules.
- [`PROJECT_STATUS.md`](PROJECT_STATUS.md) — current focus and completed work.
- [`NEXT_ACTIONS.md`](NEXT_ACTIONS.md) — the working task queue.
- [`PROJECT_PLAN.md`](PROJECT_PLAN.md) — long-lived implementation plan.
- [`DECISIONS.md`](DECISIONS.md) — architecture decision log.
- [`AGENT_CONTRACT.md`](AGENT_CONTRACT.md) — the operating contract for working in a managed vault (pi-first, with the engine commands beneath).
- [`docs/architecture/`](docs/architecture/) — the source architecture and memory-layer specifications.
- [`vault-manager/README.md`](vault-manager/README.md) — the deterministic Python engine pi drives.

## License

MIT. The pi harness foundation is derived from the upstream pi project and retains its license and attribution.
