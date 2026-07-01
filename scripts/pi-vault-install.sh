#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR=""
OLD_HEAD=""
NEW_HEAD=""
CHANGED_FILES_FILE=""
UPDATE=false
INSTALL_DIR="${PI_VAULT_INSTALL_DIR:-$HOME/.pi-vault}"
LEGACY_INSTALL_DIR="${PI_VAULT_LEGACY_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/pi-vault}"
BIN_DIR="${PI_VAULT_BIN_DIR:-$INSTALL_DIR/bin}"
LEGACY_BIN_DIR="${PI_VAULT_LEGACY_BIN_DIR:-$HOME/.local/bin}"
RUNTIME_DIR="${PI_VAULT_HOME:-$INSTALL_DIR/runtime}"
VENV_DIR="$RUNTIME_DIR/venv"
AGENT_DIR="${PI_VAULT_CODING_AGENT_DIR:-$INSTALL_DIR/agent}"
NPM_CACHE_DIR="${PI_VAULT_NPM_CACHE:-$RUNTIME_DIR/npm-cache}"
MIGRATED_FROM="${PI_VAULT_MIGRATED_FROM:-}"
PATH_PROFILE=""
PATH_PROFILE_UPDATED=false

usage() {
	cat <<'EOF'
Usage: scripts/pi-vault-install.sh --source-dir <path> [options]

Options:
  --bin-dir <path>       Launcher directory (default: ~/.pi-vault/bin)
  --runtime-dir <path>   Managed state directory (venv, npm cache)
  --update               Update an existing installation
  --old-head <commit>    Previous revision used to detect changes
  --new-head <commit>    Revision being installed (recorded for updates)
  --changed-files <path> File listing changed paths (tarball updates)
EOF
}

shell_quote() {
	printf "%q" "$1"
}

profile_contains_bin_dir() {
	local file="$1"
	[[ -f "$file" ]] || return 1
	grep -Fq "$BIN_DIR" "$file"
}

select_shell_profile() {
	local shell_name
	shell_name="$(basename "${SHELL:-}")"
	case "$shell_name" in
		zsh) printf '%s\n' "$HOME/.zshrc" ;;
		bash)
			if [[ -f "$HOME/.bashrc" ]]; then
				printf '%s\n' "$HOME/.bashrc"
			elif [[ -f "$HOME/.bash_profile" ]]; then
				printf '%s\n' "$HOME/.bash_profile"
			else
				printf '%s\n' "$HOME/.bashrc"
			fi
			;;
		sh)
			if [[ -f "$HOME/.profile" ]]; then
				printf '%s\n' "$HOME/.profile"
			else
				printf '%s\n' "$HOME/.profile"
			fi
			;;
		*)
			if [[ -f "$HOME/.zshrc" ]]; then
				printf '%s\n' "$HOME/.zshrc"
			elif [[ -f "$HOME/.bashrc" ]]; then
				printf '%s\n' "$HOME/.bashrc"
			elif [[ -f "$HOME/.profile" ]]; then
				printf '%s\n' "$HOME/.profile"
			else
				printf '%s\n' "$HOME/.zshrc"
			fi
			;;
	esac
}

ensure_path_profile() {
	[[ -n "$HOME" ]] || return 1
	for profile in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"; do
		if profile_contains_bin_dir "$profile"; then
			PATH_PROFILE="$profile"
			return 0
		fi
	done
	PATH_PROFILE="$(select_shell_profile)"
	mkdir -p "$(dirname "$PATH_PROFILE")"
	{
		printf '\n# pi-vault\n'
		printf 'export PATH=%s:$PATH\n' "$(shell_quote "$BIN_DIR")"
	} >>"$PATH_PROFILE"
	PATH_PROFILE_UPDATED=true
	return 0
}

while (($#)); do
	case "$1" in
		--source-dir) SOURCE_DIR="${2:-}"; shift ;;
		--bin-dir) BIN_DIR="${2:-}"; shift ;;
		--runtime-dir) RUNTIME_DIR="${2:-}"; shift ;;
		--old-head) OLD_HEAD="${2:-}"; shift ;;
		--new-head) NEW_HEAD="${2:-}"; shift ;;
		--changed-files) CHANGED_FILES_FILE="${2:-}"; shift ;;
		--update) UPDATE=true ;;
		--help|-h) usage; exit 0 ;;
		*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
	shift
done

VENV_DIR="$RUNTIME_DIR/venv"
NPM_CACHE_DIR="${PI_VAULT_NPM_CACHE:-$RUNTIME_DIR/npm-cache}"

if [[ -z "$SOURCE_DIR" || ! -f "$SOURCE_DIR/package.json" ]]; then
	echo "A valid --source-dir is required." >&2
	exit 1
fi

SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd -P)"

if [[ "$UPDATE" == true && -z "${PI_VAULT_INSTALL_DIR+x}" && -d "$LEGACY_INSTALL_DIR/repository" ]]; then
	LEGACY_REPO="$(cd "$LEGACY_INSTALL_DIR/repository" && pwd -P)"
	mkdir -p "$INSTALL_DIR"
	TARGET_REPO_PARENT="$(cd "$INSTALL_DIR" && pwd -P)"
	TARGET_REPO="$TARGET_REPO_PARENT/repository"
	if [[ "$SOURCE_DIR" == "$LEGACY_REPO" && "$SOURCE_DIR" != "$TARGET_REPO" ]]; then
		if [[ -e "$TARGET_REPO" ]]; then
			echo "Cannot migrate pi-vault checkout: target already exists at $TARGET_REPO" >&2
			echo "Remove it or set PI_VAULT_INSTALL_DIR to keep a custom install root." >&2
			exit 1
		fi
		mv "$SOURCE_DIR" "$TARGET_REPO"
		rmdir "$LEGACY_INSTALL_DIR" 2>/dev/null || true
		export PI_VAULT_MIGRATED_FROM="$SOURCE_DIR"
		REEXEC_ARGS=(--source-dir "$TARGET_REPO" --update)
		if [[ -n "$OLD_HEAD" ]]; then
			REEXEC_ARGS+=(--old-head "$OLD_HEAD")
		fi
		exec "$TARGET_REPO/scripts/pi-vault-install.sh" "${REEXEC_ARGS[@]}"
	fi
fi

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

# Determine which files changed so we only rebuild the affected components.
# Tarball updates pass the list via --changed-files; a development checkout
# (with .git) computes it locally instead.
CHANGED_FILES=""
HAVE_CHANGED_LIST=false
if [[ "$UPDATE" == true ]]; then
	if [[ -n "$CHANGED_FILES_FILE" && -f "$CHANGED_FILES_FILE" ]]; then
		CHANGED_FILES="$(<"$CHANGED_FILES_FILE")"
		HAVE_CHANGED_LIST=true
	elif [[ -d "$SOURCE_DIR/.git" ]]; then
		COMPARE_REVISION="$OLD_HEAD"
		if [[ -f "$BUILD_REVISION_FILE" ]]; then
			COMPARE_REVISION="$(<"$BUILD_REVISION_FILE")"
		fi
		if [[ -n "$COMPARE_REVISION" ]]; then
			CHANGED_FILES="$(git -C "$SOURCE_DIR" diff --name-only "$COMPARE_REVISION" HEAD)"
			HAVE_CHANGED_LIST=true
		fi
	fi
fi

if [[ "$HAVE_CHANGED_LIST" == true ]]; then
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

# Record the installed revision so the next update knows the base for its diff.
NEW_REVISION="$NEW_HEAD"
if [[ -z "$NEW_REVISION" && -d "$SOURCE_DIR/.git" ]]; then
	NEW_REVISION="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
fi
if [[ -n "$NEW_REVISION" ]]; then
	printf '%s\n' "$NEW_REVISION" >"$BUILD_REVISION_FILE"
fi

ln -sfn "$SOURCE_DIR/scripts/pi-vault-run.sh" "$BIN_DIR/pi-vault"
ln -sfn "$SOURCE_DIR/scripts/pi-vault-mcp-run.sh" "$BIN_DIR/pi-vault-mcp"
ln -sfn "$SOURCE_DIR/update.sh" "$BIN_DIR/pi-vault-update"
ln -sfn "$SOURCE_DIR/uninstall.sh" "$BIN_DIR/pi-vault-uninstall"

if [[ -n "$MIGRATED_FROM" && "$LEGACY_BIN_DIR" != "$BIN_DIR" ]]; then
	for launcher in pi-vault pi-vault-mcp pi-vault-update pi-vault-uninstall; do
		legacy_launcher="$LEGACY_BIN_DIR/$launcher"
		if [[ ! -L "$legacy_launcher" ]]; then
			continue
		fi
		legacy_target="$(readlink "$legacy_launcher" 2>/dev/null || true)"
		if [[ "$legacy_target" == "$MIGRATED_FROM/"* ]]; then
			rm -f -- "$legacy_launcher"
		fi
	done
fi

ensure_path_profile || true

echo "pi-vault is installed."
echo "  CLI: $BIN_DIR/pi-vault"
echo "  MCP: $BIN_DIR/pi-vault-mcp"
echo "  Updater: $BIN_DIR/pi-vault-update"
echo "  Uninstaller: $BIN_DIR/pi-vault-uninstall"
echo "  Agent: $AGENT_DIR"
echo "  Runtime: $RUNTIME_DIR"
echo "Run pi-vault from an Obsidian vault root."
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
	if [[ "$PATH_PROFILE_UPDATED" == true ]]; then
		echo "Added $BIN_DIR to PATH in $PATH_PROFILE. Restart the terminal or run: source $PATH_PROFILE"
	elif [[ -n "$PATH_PROFILE" ]]; then
		echo "$BIN_DIR is configured in $PATH_PROFILE. Restart the terminal or run: source $PATH_PROFILE"
	else
		echo "Add $BIN_DIR to PATH before running pi-vault."
	fi
fi
