#!/usr/bin/env bash
set -euo pipefail

SOURCE_PATH="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE_PATH" ]]; do
	SOURCE_PATH_DIR="$(cd -P "$(dirname "$SOURCE_PATH")" && pwd)"
	SOURCE_PATH="$(readlink "$SOURCE_PATH")"
	if [[ "$SOURCE_PATH" != /* ]]; then
		SOURCE_PATH="$SOURCE_PATH_DIR/$SOURCE_PATH"
	fi
done
SOURCE_DIR="$(cd -P "$(dirname "$SOURCE_PATH")" && pwd)"

usage() {
	cat <<'EOF'
Usage: pi-vault-update

Updates the pi-vault checkout and installation. Pulls the latest revision,
then rebuilds the CLI and Python engine only when their sources changed.
EOF
}

while (($#)); do
	case "$1" in
		--help|-h) usage; exit 0 ;;
		*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
	shift
done

if [[ ! -d "$SOURCE_DIR/.git" ]]; then
	echo "pi-vault update requires a git checkout: $SOURCE_DIR" >&2
	exit 1
fi

if [[ -n "$(git -C "$SOURCE_DIR" status --porcelain --untracked-files=no)" ]]; then
	echo "pi-vault has local tracked changes; update aborted." >&2
	exit 1
fi

OLD_HEAD="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
git -C "$SOURCE_DIR" pull --ff-only

exec "$SOURCE_DIR/scripts/pi-vault-install.sh" --source-dir "$SOURCE_DIR" --update --old-head "$OLD_HEAD"
