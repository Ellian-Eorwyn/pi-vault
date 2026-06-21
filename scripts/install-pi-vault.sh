#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_root="${PI_VAULT_HOME:-$HOME/.pi-vault/runtime}"
venv="$runtime_root/venv"

command -v node >/dev/null || { echo "pi-vault requires Node.js 22.19 or newer" >&2; exit 1; }
command -v npm >/dev/null || { echo "pi-vault requires npm" >&2; exit 1; }
command -v python3 >/dev/null || { echo "pi-vault requires Python 3.11 or newer" >&2; exit 1; }

python3 -m venv "$venv"
"$venv/bin/python" -m pip install --disable-pip-version-check "$repo_root/vault-manager"

cd "$repo_root"
npm install --ignore-scripts
npm run build --workspace @earendil-works/pi-coding-agent
npm install --global --ignore-scripts "$repo_root/packages/coding-agent"

echo "Installed pi-vault and pi-vault-mcp. Run pi-vault from an Obsidian vault."
