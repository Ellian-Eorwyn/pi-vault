#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR=""
INSTALL_DIR="${PI_VAULT_INSTALL_DIR:-$HOME/.pi-vault}"
BIN_DIR="${PI_VAULT_BIN_DIR:-$INSTALL_DIR/bin}"
RUNTIME_DIR="${PI_VAULT_HOME:-$INSTALL_DIR/runtime}"
AGENT_DIR="${PI_VAULT_CODING_AGENT_DIR:-$INSTALL_DIR/agent}"
NPM_CACHE_DIR="${PI_VAULT_NPM_CACHE:-$RUNTIME_DIR/npm-cache}"
KEEP_STATE=false
DRY_RUN=false
ASSUME_YES=false

LAUNCHERS=(pi-vault pi-vault-mcp pi-vault-update pi-vault-uninstall)
EXPECTED_TARGETS=(pi-vault-run.sh pi-vault-mcp-run.sh update.sh uninstall.sh)

usage() {
	cat <<'EOF'
Usage: uninstall.sh [options]

Removes the pi-vault launchers, managed installation checkout, runtime,
caches, settings, credentials, and sessions. A development checkout is never
deleted.

Options:
  --bin-dir <path>         Launcher directory (default: ~/.pi-vault/bin)
  --install-dir <path>     Managed install root (default: ~/.pi-vault)
  --runtime-dir <path>     Runtime directory (default: ~/.pi-vault/runtime)
  --agent-dir <path>       Agent state directory (default: ~/.pi-vault/agent)
  --npm-cache-dir <path>   npm cache directory (default: runtime/npm-cache)
  --keep-state             Preserve runtime and agent state
  --dry-run                Print the removal plan without changing anything
  --yes, -y                Do not prompt for confirmation
  --source-dir <path>      Running checkout; set automatically by uninstall.sh
EOF
}

while (($#)); do
	case "$1" in
		--bin-dir) BIN_DIR="${2:-}"; shift ;;
		--install-dir) INSTALL_DIR="${2:-}"; shift ;;
		--runtime-dir) RUNTIME_DIR="${2:-}"; shift ;;
		--agent-dir) AGENT_DIR="${2:-}"; shift ;;
		--npm-cache-dir) NPM_CACHE_DIR="${2:-}"; shift ;;
		--source-dir) SOURCE_DIR="${2:-}"; shift ;;
		--keep-state) KEEP_STATE=true ;;
		--dry-run) DRY_RUN=true ;;
		--yes|-y) ASSUME_YES=true ;;
		--help|-h) usage; exit 0 ;;
		*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
	shift
done

canonical() {
	local path="$1"
	if [[ -e "$path" ]]; then
		(cd "$path" 2>/dev/null && pwd -P) || printf '%s' "$path"
	else
		printf '%s' "$path"
	fi
}

is_protected_path() {
	local path="$1"
	[[ -z "$path" ]] && return 0
	case "$path" in
		/|/root|/home|/Users|"$HOME"|/usr|/bin|/etc|/var|/System|/Library|/opt) return 0 ;;
	esac
	return 1
}

is_within() {
	local child="$1"
	local parent="$2"
	[[ "$child" == "$parent" || "$child" == "$parent"/* ]]
}

PLANNED=()
WARNINGS=()
PATHS_TO_REMOVE=()
SUDO_NEEDED=false

note_plan() { PLANNED+=("$1"); }
note_warn() { WARNINGS+=("$1"); }

queue_path() {
	local label="$1"
	local path="$2"
	local canonical_path
	canonical_path="$(canonical "$path")"
	if is_protected_path "$canonical_path"; then
		note_warn "Refusing to remove protected path: $path"
		return
	fi
	PATHS_TO_REMOVE+=("$path")
	note_plan "$label: $path"
}

remove_path() {
	local path="$1"
	if rm -rf -- "$path" 2>/dev/null; then
		return 0
	fi
	SUDO_NEEDED=true
	note_warn "Could not remove $path. Retry with: sudo rm -rf '$path'"
	return 1
}

if [[ -n "$SOURCE_DIR" ]]; then
	SOURCE_DIR="$(canonical "$SOURCE_DIR")"
fi
INSTALL_DIR_CANON="$(canonical "$INSTALL_DIR")"
MANAGED_REPO="$INSTALL_DIR/repository"
MANAGED_REPO_CANON="$(canonical "$MANAGED_REPO")"
RUNTIME_DIR_CANON="$(canonical "$RUNTIME_DIR")"
AGENT_DIR_CANON="$(canonical "$AGENT_DIR")"
NPM_CACHE_DIR_CANON="$(canonical "$NPM_CACHE_DIR")"

for index in "${!LAUNCHERS[@]}"; do
	launcher="$BIN_DIR/${LAUNCHERS[$index]}"
	[[ -L "$launcher" || -e "$launcher" ]] || continue
	if [[ ! -L "$launcher" ]]; then
		note_warn "Skipping $launcher: not a symlink."
		continue
	fi
	target="$(readlink "$launcher" 2>/dev/null || true)"
	if [[ "$(basename "$target")" == "${EXPECTED_TARGETS[$index]}" ]]; then
		queue_path "Remove launcher" "$launcher"
	else
		note_warn "Skipping $launcher: unexpected target $target."
	fi
done

if [[ -d "$MANAGED_REPO" ]]; then
	if [[ ! -f "$MANAGED_REPO/scripts/pi-vault-install.sh" ]]; then
		note_warn "Skipping $MANAGED_REPO: not a managed pi-vault checkout."
	elif [[ -n "$SOURCE_DIR" && "$SOURCE_DIR" != "$MANAGED_REPO_CANON" ]] && is_within "$SOURCE_DIR" "$INSTALL_DIR_CANON"; then
		note_warn "Skipping $INSTALL_DIR: it contains the development checkout $SOURCE_DIR."
	else
		queue_path "Remove managed checkout" "$MANAGED_REPO"
	fi
fi

if [[ "$KEEP_STATE" == false ]]; then
	if [[ -d "$RUNTIME_DIR" ]]; then
		if [[ -f "$RUNTIME_DIR/.pi-vault-build-revision" || -f "$RUNTIME_DIR/venv/pyvenv.cfg" || -d "$RUNTIME_DIR/npm-cache/_cacache" ]]; then
			queue_path "Remove runtime" "$RUNTIME_DIR"
		else
			note_warn "Skipping $RUNTIME_DIR: not recognizable as pi-vault runtime state."
		fi
	fi
	if [[ -d "$AGENT_DIR" ]]; then
		if [[ -f "$AGENT_DIR/models.json" || -f "$AGENT_DIR/settings.json" || -d "$AGENT_DIR/sessions" ]]; then
			queue_path "Remove settings, credentials, and sessions" "$AGENT_DIR"
		else
			note_warn "Skipping $AGENT_DIR: not recognizable as pi-vault agent state."
		fi
	fi
	if [[ -d "$NPM_CACHE_DIR" ]] && ! is_within "$NPM_CACHE_DIR_CANON" "$RUNTIME_DIR_CANON"; then
		if [[ -d "$NPM_CACHE_DIR/_cacache" || -d "$NPM_CACHE_DIR/_logs" ]]; then
			queue_path "Remove npm cache" "$NPM_CACHE_DIR"
		else
			note_warn "Skipping $NPM_CACHE_DIR: not recognizable as an npm cache."
		fi
	fi
elif [[ -d "$RUNTIME_DIR" || -d "$AGENT_DIR" ]]; then
	note_plan "Preserve state: $RUNTIME_DIR and $AGENT_DIR"
fi

if [[ ${#PATHS_TO_REMOVE[@]} -eq 0 ]]; then
	echo "Nothing to uninstall."
	for warning in "${WARNINGS[@]:-}"; do
		[[ -n "$warning" ]] && echo "  - $warning"
	done
	exit 0
fi

echo "pi-vault uninstall plan:"
for item in "${PLANNED[@]}"; do
	echo "  - $item"
done
if [[ ${#WARNINGS[@]} -gt 0 ]]; then
	echo "Notes:"
	for warning in "${WARNINGS[@]}"; do
		echo "  - $warning"
	done
fi

if [[ "$DRY_RUN" == true ]]; then
	echo "Dry run: no changes made."
	exit 0
fi

if [[ "$ASSUME_YES" == false ]]; then
	read -r -p "Proceed? This permanently deletes pi-vault credentials and sessions. [y/N] " reply
	case "$reply" in
		[yY]|[yY][eE][sS]) ;;
		*) echo "Aborted."; exit 1 ;;
	esac
fi

for path in "${PATHS_TO_REMOVE[@]}"; do
	remove_path "$path" && echo "Removed $path" || true
done

STATE_ROOT="$INSTALL_DIR"
if [[ "$KEEP_STATE" == false && -d "$STATE_ROOT" ]]; then
	rmdir "$BIN_DIR" 2>/dev/null || true
	rmdir "$STATE_ROOT" 2>/dev/null || true
fi

echo
echo "pi-vault uninstalled."
if [[ "$KEEP_STATE" == true ]]; then
	echo "  State preserved at: $RUNTIME_DIR and $AGENT_DIR"
fi
if [[ "$SUDO_NEEDED" == true ]]; then
	exit 1
fi
