"""Embedding-backed related-note discovery.

The single-note LLM stage cannot populate `related` with real cross-note links
because it never sees the rest of the vault. This module computes nearest
neighbors from the embedding index and proposes append-only `update_frontmatter`
operations that add `[[wikilink]]` values to each note's `related` list. It is
proposal-first: nothing is applied here, and existing links are never removed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .embedding_index import build_or_refresh_index, center
from .embeddings import EmbeddingClient, rank
from .logging_utils import append_log
from .safety import atomic_write_text
from .scanner import scan_vault

_SKIP_TYPES = {"index", "system", "template", "daily"}


def run_propose_related_links(
    config: AgentConfig,
    *,
    max_notes: int | None = None,
    top_k: int | None = None,
    min_similarity: float | None = None,
    client: EmbeddingClient | None = None,
) -> tuple[int, str]:
    """Generate a `related-links` proposal from embedding nearest neighbors."""
    if client is None:
        return (
            1,
            "vault-agent propose-related-links failed\n"
            "Error: related-link discovery needs embeddings; set `embeddings.enabled: true` "
            "and an `embedding_base_url` in the config.",
        )

    limit = max_notes if max_notes is not None else max(config.max_notes, 5)
    neighbors = top_k if top_k is not None else config.embeddings_top_k
    threshold = (
        min_similarity if min_similarity is not None else config.embeddings_min_similarity
    )

    try:
        index_result = build_or_refresh_index(config, client, dry_run=config.dry_run)
    except ValueError as exc:
        return 1, f"vault-agent propose-related-links failed\nError: {exc}"

    mean = index_result.mean if index_result.centered else None
    vector_records = [
        {"path": r["path"], "vector": center(r["vector"], mean)}
        for r in index_result.records
        if r.get("vector")
    ]
    vector_paths = {r["path"] for r in vector_records}

    scan = scan_vault(config.vault_root)
    entries = {entry["path"]: entry for entry in scan.entries}

    # Targets we never suggest linking to (templates, malformed notes, un-embedded).
    disallowed: set[str] = set()
    for path, entry in entries.items():
        if path not in vector_paths or entry.get("system_template") or entry.get(
            "frontmatter_error"
        ):
            disallowed.add(path)

    operations: list[dict[str, Any]] = []
    selected: list[str] = []
    for path in sorted(entries):
        if len(selected) >= limit:
            break
        entry = entries[path]
        if path in disallowed:
            continue
        if str(entry.get("type") or "").strip() in _SKIP_TYPES:
            continue

        existing_related = _string_list(entry.get("related"))
        known_names = {_link_name(link) for link in existing_related}
        parent_name = _link_name(str(entry.get("parent") or ""))
        if parent_name:
            known_names.add(parent_name)
        known_names.add(Path(path).stem.lower())

        ranked = rank(
            _vector_for(vector_records, path),
            vector_records,
            top_k=neighbors,
            min_similarity=threshold,
            exclude_paths=disallowed | {path},
        )
        additions: list[str] = []
        for neighbor_path, _score in ranked:
            stem = Path(neighbor_path).stem
            if stem.lower() in known_names:
                continue
            link = f"[[{stem}]]"
            if link in additions:
                continue
            additions.append(link)
            known_names.add(stem.lower())
        if not additions:
            continue

        operations.append(
            {
                "op": "update_frontmatter",
                "path": path,
                "set": {"related": existing_related + additions},
                "remove": [],
            }
        )
        selected.append(path)

    proposal = {
        "id": "related-links",
        "title": "Add embedding-discovered related links",
        "kind": "related-links",
        "status": "pending",
        "automation_safe": False,
        "summary": (
            f"Append nearest-neighbor related links to {len(selected)} note(s) "
            f"(top {neighbors}, min similarity {threshold})."
        ),
        "operations": operations,
    }

    if not config.dry_run and operations:
        proposal_dir = config.vault_root / config.paths.review_dir / "proposals"
        proposal_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            proposal_dir / "related-links.json",
            json.dumps(proposal, indent=2, sort_keys=True) + "\n",
        )
        append_log(
            config.vault_root,
            "propose-related-links",
            [f"notes {len(selected)}", f"embedded {index_result.embedded}"],
        )

    lines = [
        "vault-agent propose-related-links " + ("dry run" if config.dry_run else "complete"),
        f"Notes embedded this run: {index_result.embedded} (reused {index_result.reused})",
        f"Notes with proposed related links: {len(selected)}",
    ]
    for path in selected:
        lines.append(f"- {path}")
    if config.dry_run:
        lines.append("No files were changed.")
    elif operations:
        lines.append("Run `vault-agent review-proposals --dry-run` to inspect the proposal.")
    else:
        lines.append("No related links to propose above the similarity threshold.")
    return 0, "\n".join(lines)


def _vector_for(records: list[dict[str, Any]], path: str) -> list[float]:
    for record in records:
        if record.get("path") == path:
            vector = record.get("vector")
            return vector if isinstance(vector, list) else []
    return []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _link_name(value: str) -> str:
    text = value.strip()
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    text = text.split("|", 1)[0].split("#", 1)[0].split("/", 1)[-1]
    return text.strip().lower()
