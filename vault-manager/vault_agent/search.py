"""Read-only semantic vault search over the embedding index.

Gives the agent a real retrieval tool: embed a free-text query and rank notes by
cosine similarity. This complements the deterministic Markdown retrieval files
(vault map, catalog, property index, summary brief) rather than replacing them.
Search never writes; if the index is missing it reports how to build it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .embedding_index import index_records, load_index, query
from .embeddings import EmbeddingClient
from .frontmatter import parse_note

DEFAULT_SNIPPET_CHARS = 200


def run_search(
    config: AgentConfig,
    *,
    query_text: str,
    top_k: int | None = None,
    json_output: bool = False,
    client: EmbeddingClient | None = None,
) -> tuple[int, str]:
    """Rank vault notes against a free-text query using the embedding index."""
    query_text = (query_text or "").strip()
    if not query_text:
        return 1, "vault-agent vault-search failed\nError: a non-empty query is required."
    if client is None:
        return (
            1,
            "vault-agent vault-search failed\n"
            "Error: semantic search needs embeddings; set `embeddings.enabled: true` "
            "and an `embedding_base_url` in the config.",
        )

    index = load_index(config)
    records = index_records(index)
    if not records:
        return (
            1,
            "vault-agent vault-search failed\n"
            "Error: the embedding index is empty. Run `vault-agent embed-index` first.",
        )

    limit = top_k if top_k is not None else config.embeddings_top_k
    try:
        query_vector = client.embed_one(query_text)
    except ValueError as exc:
        return 1, f"vault-agent vault-search failed\nError: {exc}"

    ranked = query(config, query_vector, top_k=limit, index=index)
    titles = {record["path"]: record.get("title") for record in records}

    results: list[dict[str, Any]] = []
    for path, score in ranked:
        results.append(
            {
                "path": path,
                "title": titles.get(path) or Path(path).stem,
                "score": round(score, 4),
                "snippet": _snippet(config.vault_root / path),
            }
        )

    if json_output:
        payload = {"query": query_text, "top_k": limit, "results": results}
        return 0, json.dumps(payload, indent=2, sort_keys=True)

    if not results:
        return 0, f"vault-agent vault-search complete\nNo matches for: {query_text}"
    lines = [f"vault-agent vault-search results for: {query_text}", ""]
    for item in results:
        lines.append(f"- [{item['score']:.4f}] {item['title']} ({item['path']})")
        if item["snippet"]:
            lines.append(f"    {item['snippet']}")
    return 0, "\n".join(lines)


def _snippet(path: Path, *, chars: int = DEFAULT_SNIPPET_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    parsed = parse_note(text)
    body = (parsed.body if parsed.body else text).strip()
    snippet = " ".join(body.split())[:chars]
    return snippet
