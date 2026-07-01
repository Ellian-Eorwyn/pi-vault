#!/usr/bin/env bash
# Shared helpers for fetching pi-vault source as a tarball (no .git checkout).
#
# The GitHub install and update routes both pull the source as a gzip tarball
# from codeload rather than cloning the repository, so the installed copy is a
# plain directory and never registers as a Git repository. This file is sourced
# by update.sh; install.sh inlines an equivalent minimal copy because it must be
# self-contained when piped from `curl | bash`.

# Print OWNER/REPO for the GitHub source. Honors PI_VAULT_GITHUB_REPO, then a
# github.com URL in PI_VAULT_REPOSITORY, then the project default.
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

# Print the git ref (branch or tag) to install. Defaults to main.
pv_ref() {
	printf '%s\n' "${PI_VAULT_REF:-main}"
}

# curl wrapper that adds a GitHub token when one is available, easing API rate
# limits on shared networks. Extra args and the URL are passed through.
pv_curl() {
	local token="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
	if [[ -n "$token" ]]; then
		curl -fsSL -H "Authorization: Bearer $token" "$@"
	else
		curl -fsSL "$@"
	fi
}

# Resolve a ref to its full commit SHA via the GitHub API. Prints the SHA, or
# nothing (and returns 1) when resolution fails, so callers can fall back to a
# full rebuild against the branch tarball.
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

# Download the source tarball for a ref/SHA to a destination file.
pv_download_tarball() {
	local slug="$1" ref="$2" dest="$3"
	pv_curl -o "$dest" "https://codeload.github.com/$slug/tar.gz/$ref"
}

# Extract a tarball into destdir, stripping the top-level archive directory so
# the source lands directly in destdir. Existing gitignored artifacts
# (node_modules, dist, venv) are preserved.
pv_extract_into() {
	local tarfile="$1" destdir="$2"
	mkdir -p "$destdir"
	tar -xzf "$tarfile" -C "$destdir" --strip-components=1
}

# Write "status<TAB>filename" for every file in the base...head comparison to
# out_file, using the GitHub compare API. Returns 1 (leaving out_file empty)
# when the comparison cannot be retrieved, so callers fall back to a full build.
pv_changed_files() {
	local slug="$1" base="$2" head="$3" out_file="$4" json
	: >"$out_file"
	json="$(pv_curl "https://api.github.com/repos/$slug/compare/$base...$head" 2>/dev/null || true)"
	[[ -n "$json" ]] || return 1
	printf '%s' "$json" | node -e '
		const fs = require("node:fs");
		let raw = "";
		process.stdin.on("data", (c) => { raw += c; });
		process.stdin.on("end", () => {
			let data;
			try { data = JSON.parse(raw); } catch { process.exit(1); }
			const files = Array.isArray(data.files) ? data.files : null;
			if (!files) process.exit(1);
			const lines = files.map((f) => `${f.status}\t${f.filename}`);
			fs.writeFileSync(process.argv[1], lines.join("\n") + (lines.length ? "\n" : ""));
		});
	' "$out_file" || return 1
	return 0
}
