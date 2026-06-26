"""Read-only semantic vault search over the embedding index.

Gives the agent a real retrieval tool: embed a free-text query and rank notes by
cosine similarity. This complements the deterministic Markdown retrieval files
(vault map, catalog, property index, summary brief) rather than replacing them.
Search never writes; if the index is missing it reports how to build it.
"""

from __future__ import annotations

import json
import re
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

    candidate_limit = max(limit * 5, limit, 20)
    ranked = query(config, query_vector, top_k=candidate_limit, index=index)
    titles = {record["path"]: record.get("title") for record in records}
    ranked_results = _hybrid_rank(query_text, ranked, titles, limit=limit)

    results: list[dict[str, Any]] = []
    for item in ranked_results:
        path = item["path"]
        results.append(
            {
                "path": path,
                "title": titles.get(path) or Path(path).stem,
                "score": round(float(item["score"]), 4),
                "semantic_score": round(float(item["semantic_score"]), 4),
                "lexical_boost": round(float(item["lexical_boost"]), 4),
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


def _hybrid_rank(
    query_text: str,
    ranked: list[tuple[str, float]],
    titles: dict[str, Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path, semantic_score in ranked:
        title = str(titles.get(path) or Path(path).stem)
        lexical_boost = _lexical_boost(query_text, title=title, path=path)
        results.append(
            {
                "path": path,
                "score": semantic_score + lexical_boost,
                "semantic_score": semantic_score,
                "lexical_boost": lexical_boost,
            }
        )
    results.sort(
        key=lambda item: (
            -float(item["score"]),
            -float(item["semantic_score"]),
            str(item["path"]),
        )
    )
    return results[:limit]


def _lexical_boost(query_text: str, *, title: str, path: str) -> float:
    query_tokens = _tokens(query_text)
    if not query_tokens:
        return 0.0

    title_tokens = set(_tokens(title))
    path_tokens = set(_tokens(path))
    target_tokens = title_tokens | path_tokens
    target_text = _normalized_text(f"{title} {path}")
    query_text_normalized = _normalized_text(query_text)

    boost = 0.0
    exact_matches = len([token for token in query_tokens if token in target_tokens])
    title_matches = len([token for token in query_tokens if token in title_tokens])
    boost += min(0.12, exact_matches * 0.025)
    boost += min(0.06, title_matches * 0.02)

    query_compact = "".join(query_tokens)
    target_compact = "".join(_tokens(f"{title} {path}"))
    if len(query_compact) >= 8 and query_compact in target_compact:
        boost += 0.08
    if len(target_text) >= 8 and target_text in query_text_normalized:
        boost += 0.04
    return min(boost, 0.2)


def _tokens(text: str) -> list[str]:
    expanded = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    candidates = re.findall(r"[A-Za-z0-9]+", expanded.lower())
    stopwords = {"and", "for", "the", "with", "into", "from", "this", "that"}
    return [candidate for candidate in candidates if len(candidate) >= 3 and candidate not in stopwords]


def _normalized_text(text: str) -> str:
    return " ".join(_tokens(text))


def _snippet(path: Path, *, chars: int = DEFAULT_SNIPPET_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    parsed = parse_note(text)
    body = (parsed.body if parsed.body else text).strip()
    snippet = " ".join(body.split())[:chars]
    return snippet
