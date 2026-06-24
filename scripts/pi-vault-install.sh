#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR=""
OLD_HEAD=""
UPDATE=false
BIN_DIR="${PI_VAULT_BIN_DIR:-$HOME/.local/bin}"
RUNTIME_DIR="${PI_VAULT_HOME:-$HOME/.pi-vault/runtime}"
NPM_CACHE_DIR="${PI_VAULT_NPM_CACHE:-$RUNTIME_DIR/npm-cache}"
VENV_DIR="$RUNTIME_DIR/venv"
AGENT_DIR="${PI_VAULT_CODING_AGENT_DIR:-$HOME/.pi-vault/agent}"

usage() {
	cat <<'EOF'
Usage: scripts/pi-vault-install.sh --source-dir <path> [options]

Options:
  --bin-dir <path>       Launcher directory (default: ~/.local/bin)
  --runtime-dir <path>   Managed state directory (venv, npm cache)
  --update               Update an existing installation
  --old-head <commit>    Previous revision used to detect changes
EOF
}

while (($#)); do
	case "$1" in
		--source-dir) SOURCE_DIR="${2:-}"; shift ;;
		--bin-dir) BIN_DIR="${2:-}"; shift ;;
		--runtime-dir) RUNTIME_DIR="${2:-}"; VENV_DIR="$RUNTIME_DIR/venv"; shift ;;
		--old-head) OLD_HEAD="${2:-}"; shift ;;
		--update) UPDATE=true ;;
		--help|-h) usage; exit 0 ;;
		*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
	shift
done

if [[ -z "$SOURCE_DIR" || ! -f "$SOURCE_DIR/package.json" ]]; then
	echo "A valid --source-dir is required." >&2
	exit 1
fi

SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
rm -rf -- "$SOURCE_DIR/.claude" "$SOURCE_DIR/.codex"
command -v node >/dev/null 2>&1 || { echo "pi-vault requires Node.js 22.19 or newer." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "pi-vault requires npm." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "pi-vault requires Python 3.11 or newer." >&2; exit 1; }

node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 19)) process.exit(1)' || {
	echo "pi-vault requires Node.js 22.19 or newer; found $(node --version)." >&2
	exit 1
}

NEEDS_BUILD=true
NEEDS_INSTALL=true
NEEDS_PYTHON=true
BUILD_REVISION_FILE="$RUNTIME_DIR/.pi-vault-build-revision"
COMPARE_REVISION="$OLD_HEAD"
if [[ -f "$BUILD_REVISION_FILE" ]]; then
	COMPARE_REVISION="$(<"$BUILD_REVISION_FILE")"
fi

if [[ "$UPDATE" == true && -n "$COMPARE_REVISION" && -d "$SOURCE_DIR/.git" ]]; then
	CHANGED_FILES="$(git -C "$SOURCE_DIR" diff --name-only "$COMPARE_REVISION" HEAD)"
	CORE_FILES="$(grep -E '^(packages/|package(-lock)?\.json$|tsconfig)' <<<"$CHANGED_FILES" || true)"
	if [[ -z "$CORE_FILES" ]]; then
		NEEDS_BUILD=false
		NEEDS_INSTALL=false
	elif ! grep -Eq '(^|/)package(-lock)?\.json$' <<<"$CORE_FILES"; then
		NEEDS_INSTALL=false
	fi
	if ! grep -Eq '^vault-manager/' <<<"$CHANGED_FILES"; then
		NEEDS_PYTHON=false
	fi
fi

# Always rebuild or reinstall when the expected artifacts are missing.
if [[ ! -f "$SOURCE_DIR/packages/coding-agent/dist/cli.js" ]]; then
	NEEDS_BUILD=true
fi
if [[ ! -d "$SOURCE_DIR/node_modules" ]]; then
	NEEDS_INSTALL=true
fi
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
	NEEDS_PYTHON=true
fi

mkdir -p "$BIN_DIR" "$RUNTIME_DIR"
node "$SOURCE_DIR/scripts/pi-vault-ensure-defaults.mjs" "$SOURCE_DIR" "$AGENT_DIR"

if [[ "$NEEDS_INSTALL" == true ]]; then
	npm_config_cache="$NPM_CACHE_DIR" npm --prefix "$SOURCE_DIR" ci --ignore-scripts
fi

if [[ "$NEEDS_BUILD" == true ]]; then
	# Use build:install so the committed generated model registries are reused.
	# The normal ai build regenerates them from upstream APIs, which would dirty
	# the installed Git checkout and make pi-vault-update refuse the next pull.
	npm --prefix "$SOURCE_DIR" run build:install
fi

if [[ "$NEEDS_PYTHON" == true ]]; then
	python3 -m venv "$VENV_DIR"
	"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check "$SOURCE_DIR/vault-manager"
fi

if [[ -d "$SOURCE_DIR/.git" ]]; then
	git -C "$SOURCE_DIR" rev-parse HEAD >"$BUILD_REVISION_FILE"
fi

ln -sfn "$SOURCE_DIR/scripts/pi-vault-run.sh" "$BIN_DIR/pi-vault"
ln -sfn "$SOURCE_DIR/scripts/pi-vault-mcp-run.sh" "$BIN_DIR/pi-vault-mcp"
ln -sfn "$SOURCE_DIR/update.sh" "$BIN_DIR/pi-vault-update"
ln -sfn "$SOURCE_DIR/uninstall.sh" "$BIN_DIR/pi-vault-uninstall"

echo "pi-vault is installed."
echo "  CLI: $BIN_DIR/pi-vault"
echo "  MCP: $BIN_DIR/pi-vault-mcp"
echo "  Updater: $BIN_DIR/pi-vault-update"
echo "  Uninstaller: $BIN_DIR/pi-vault-uninstall"
echo "  Runtime: $RUNTIME_DIR"
echo "Run pi-vault from an Obsidian vault root."
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
	echo "Add $BIN_DIR to PATH before running pi-vault."
fi
