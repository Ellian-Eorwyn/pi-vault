#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]-}" ]]; then
	SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
fi

if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/scripts/pi-vault-uninstall.sh" ]]; then
	exec "$SCRIPT_DIR/scripts/pi-vault-uninstall.sh" --source-dir "$SCRIPT_DIR" "$@"
fi

INSTALL_DIR="${PI_VAULT_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/pi-vault}"
SOURCE_DIR="$INSTALL_DIR/repository"

if [[ -f "$SOURCE_DIR/scripts/pi-vault-uninstall.sh" ]]; then
	exec "$SOURCE_DIR/scripts/pi-vault-uninstall.sh" --source-dir "$SOURCE_DIR" "$@"
fi

echo "Cannot locate pi-vault-uninstall.sh. Run uninstall.sh from a pi-vault checkout." >&2
exit 1
