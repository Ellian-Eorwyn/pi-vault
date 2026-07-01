#!/usr/bin/env bash
set -euo pipefail

# Resolve through the launcher symlink to the real script location.
SOURCE_PATH="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE_PATH" ]]; do
	SOURCE_PATH_DIR="$(cd -P "$(dirname "$SOURCE_PATH")" && pwd)"
	SOURCE_PATH="$(readlink "$SOURCE_PATH")"
	if [[ "$SOURCE_PATH" != /* ]]; then
		SOURCE_PATH="$SOURCE_PATH_DIR/$SOURCE_PATH"
	fi
done
SOURCE_DIR="$(cd -P "$(dirname "$SOURCE_PATH")" && pwd)"

# The whole body runs inside main() so the update keeps working even though it
# overwrites this very file: bash parses the function fully before running it.
main() {
	local runtime_dir revision_file slug ref old_sha new_sha fetch_ref
	local tmp_tar tmp_changed tmp_plain

	usage() {
		cat <<'EOF'
Usage: pi-vault-update

Updates the pi-vault installation. Fetches the latest source as a tarball and
rebuilds the CLI and Python engine only when their sources changed. The
installed copy stays a plain directory, not a Git checkout.
EOF
	}

	while (($#)); do
		case "$1" in
			--help|-h) usage; exit 0 ;;
			*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
		esac
		shift
	done

	if [[ ! -f "$SOURCE_DIR/package.json" || ! -f "$SOURCE_DIR/scripts/pi-vault-install.sh" ]]; then
		echo "pi-vault update requires an installed checkout: $SOURCE_DIR" >&2
		exit 1
	fi

	command -v curl >/dev/null 2>&1 || { echo "pi-vault requires curl." >&2; exit 1; }
	command -v tar >/dev/null 2>&1 || { echo "pi-vault requires tar." >&2; exit 1; }

	# shellcheck source=scripts/pi-vault-fetch.sh
	source "$SOURCE_DIR/scripts/pi-vault-fetch.sh"

	runtime_dir="${PI_VAULT_HOME:-${PI_VAULT_INSTALL_DIR:-$HOME/.pi-vault}/runtime}"
	revision_file="$runtime_dir/.pi-vault-build-revision"
	slug="$(pv_repo_slug)"
	ref="$(pv_ref)"

	# Base revision for the change comparison: the recorded build revision, or a
	# git HEAD when migrating a legacy clone.
	old_sha=""
	if [[ -f "$revision_file" ]]; then
		old_sha="$(<"$revision_file")"
	elif [[ -d "$SOURCE_DIR/.git" ]]; then
		old_sha="$(git -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null || true)"
	fi

	new_sha="$(pv_resolve_sha "$slug" "$ref" || true)"
	if [[ -n "$new_sha" && "$new_sha" == "$old_sha" && ! -d "$SOURCE_DIR/.git" ]]; then
		echo "pi-vault is already up to date ($new_sha)."
		exit 0
	fi

	fetch_ref="${new_sha:-$ref}"
	tmp_tar="$(mktemp "${TMPDIR:-/tmp}/pi-vault-source.XXXXXX.tar.gz")"
	tmp_changed="$(mktemp "${TMPDIR:-/tmp}/pi-vault-changed.XXXXXX")"
	tmp_plain="$(mktemp "${TMPDIR:-/tmp}/pi-vault-changed-plain.XXXXXX")"
	trap 'rm -f "$tmp_tar" "$tmp_changed" "$tmp_plain"' EXIT

	echo "Fetching pi-vault ${new_sha:-$ref} from $slug..."
	pv_download_tarball "$slug" "$fetch_ref" "$tmp_tar"

	# Compute the changed-file list before touching the checkout. Falls back to a
	# full rebuild when either revision is unknown or the compare is unavailable.
	local have_changes=false
	if [[ -n "$old_sha" && -n "$new_sha" && "$old_sha" != "$new_sha" ]]; then
		if pv_changed_files "$slug" "$old_sha" "$new_sha" "$tmp_changed"; then
			have_changes=true
		fi
	fi

	# Overlay the new source, preserving gitignored artifacts (node_modules,
	# dist, venv) so the incremental build logic still applies.
	pv_extract_into "$tmp_tar" "$SOURCE_DIR"

	if [[ "$have_changes" == true ]]; then
		# Drop files deleted upstream, then hand the installer the plain list.
		while IFS=$'\t' read -r status path; do
			[[ "$status" == "removed" && -n "$path" ]] || continue
			rm -f -- "$SOURCE_DIR/$path"
		done <"$tmp_changed"
		cut -f2 "$tmp_changed" >"$tmp_plain"
	fi

	# Migrate a legacy git clone into a plain directory so it stops registering
	# as a repository.
	if [[ -d "$SOURCE_DIR/.git" ]]; then
		echo "Converting installed checkout to a plain directory (removing .git)."
		rm -rf -- "$SOURCE_DIR/.git"
	fi

	local install_args=(--source-dir "$SOURCE_DIR" --update)
	if [[ "$have_changes" == true ]]; then
		install_args+=(--changed-files "$tmp_plain")
	fi
	if [[ -n "$new_sha" ]]; then
		install_args+=(--new-head "$new_sha")
	fi

	# exec replaces this process, so the EXIT trap won't run: clear the temp
	# files it would have removed, but keep the plain list the installer reads.
	rm -f "$tmp_tar" "$tmp_changed"
	exec "$SOURCE_DIR/scripts/pi-vault-install.sh" "${install_args[@]}"
}

main "$@"
