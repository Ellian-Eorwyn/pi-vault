#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]-}" ]]; then
	SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
fi

# Run from an existing checkout: install straight from it, no download.
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/scripts/pi-vault-install.sh" ]]; then
	exec "$SCRIPT_DIR/scripts/pi-vault-install.sh" --source-dir "$SCRIPT_DIR" "$@"
fi

# Bootstrap (typically `curl ... | bash`): fetch the source as a tarball into a
# plain directory so the installed copy never becomes a Git repository. The
# fetch helpers are inlined here because this script must stand alone when piped.

pv_repo_slug() {
	if [[ -n "${PI_VAULT_GITHUB_REPO:-}" ]]; then
		printf '%s\n' "$PI_VAULT_GITHUB_REPO"
		return 0
	fi
	local url="${PI_VAULT_REPOSITORY:-}"
	if [[ "$url" == *github.com* ]]; then
		local slug="${url#*github.com}"
		slug="${slug#[:/]}"
		slug="${slug%.git}"
		if [[ -n "$slug" ]]; then
			printf '%s\n' "$slug"
			return 0
		fi
	fi
	printf '%s\n' "Ellian-Eorwyn/pi-vault"
}

pv_curl() {
	local token="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
	if [[ -n "$token" ]]; then
		curl -fsSL -H "Authorization: Bearer $token" "$@"
	else
		curl -fsSL "$@"
	fi
}

pv_resolve_sha() {
	local slug="$1" ref="$2" sha
	sha="$(pv_curl -H 'Accept: application/vnd.github.sha' \
		"https://api.github.com/repos/$slug/commits/$ref" 2>/dev/null || true)"
	if [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
		printf '%s\n' "$sha"
		return 0
	fi
	return 1
}

main() {
	local install_dir source_dir slug ref sha fetch_ref tmp_tar
	install_dir="${PI_VAULT_INSTALL_DIR:-$HOME/.pi-vault}"
	source_dir="$install_dir/repository"

	command -v curl >/dev/null 2>&1 || { echo "pi-vault requires curl." >&2; exit 1; }
	command -v tar >/dev/null 2>&1 || { echo "pi-vault requires tar." >&2; exit 1; }

	if [[ -e "$source_dir" ]]; then
		echo "Install checkout already exists: $source_dir" >&2
		echo "Run pi-vault-update, or remove the checkout before reinstalling." >&2
		exit 1
	fi

	slug="$(pv_repo_slug)"
	ref="${PI_VAULT_REF:-main}"
	sha="$(pv_resolve_sha "$slug" "$ref" || true)"
	fetch_ref="${sha:-$ref}"

	tmp_tar="$(mktemp "${TMPDIR:-/tmp}/pi-vault-source.XXXXXX.tar.gz")"
	trap 'rm -f "$tmp_tar"' EXIT
	echo "Fetching pi-vault ${sha:-$ref} from $slug..."
	pv_curl -o "$tmp_tar" "https://codeload.github.com/$slug/tar.gz/$fetch_ref"

	mkdir -p "$source_dir"
	tar -xzf "$tmp_tar" -C "$source_dir" --strip-components=1
	rm -f "$tmp_tar"
	trap - EXIT

	local install_args=(--source-dir "$source_dir")
	if [[ -n "$sha" ]]; then
		install_args+=(--new-head "$sha")
	fi
	exec "$source_dir/scripts/pi-vault-install.sh" "${install_args[@]}" "$@"
}

main "$@"
