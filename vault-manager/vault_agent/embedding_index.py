"""Rebuildable embedding index over vault notes.

The index is a JSON cache under the agent retrieval folder, keyed by note path
and invalidated by the same content hash the scanner computes. It is fully
rebuildable from the vault (canonical Markdown stays the source of truth) and is
git-ignored by the versioning layer, so it is treated as derived state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .embeddings import EmbeddingClient, rank
from .frontmatter import parse_note
from .safety import write_text_safely
from .scanner import scan_vault

INDEX_DIRNAME = "embedding"
INDEX_FILENAME = "index.json"

DEFAULT_EXCERPT_CHARS = 6000

# Below this note count, mean-centering is degenerate (e.g. two notes become
# antipodal), so we fall back to raw cosine. Above it, centering removes the
# corpus mean to counter the model's high baseline cosine and sharpen ranking.
MIN_CENTER_NOTES = 25


@dataclass(frozen=True)
class IndexResult:
    total: int
    embedded: int
    reused: int
    removed: int
    records: list[dict[str, Any]]
    mean: list[float] | None = None
    centered: bool = False


def index_path(config: AgentConfig) -> Path:
    return config.vault_root / config.paths.retrieval_dir / INDEX_DIRNAME / INDEX_FILENAME


def load_index(config: AgentConfig) -> dict[str, Any]:
    path = index_path(config)
    if not path.exists():
        return {"generated_by": "vault-agent", "model": None, "notes": []}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"generated_by": "vault-agent", "model": None, "notes": []}
    if not isinstance(loaded, dict):
        return {"generated_by": "vault-agent", "model": None, "notes": []}
    loaded.setdefault("notes", [])
    if not isinstance(loaded["notes"], list):
        loaded["notes"] = []
    return loaded


def index_records(index: dict[str, Any]) -> list[dict[str, Any]]:
    notes = index.get("notes")
    return [note for note in notes if isinstance(note, dict)] if isinstance(notes, list) else []


def mean_vector(vectors: list[list[float]]) -> list[float] | None:
    """Component-wise mean of equal-length vectors, or None when empty."""
    if not vectors:
        return None
    dims = len(vectors[0])
    totals = [0.0] * dims
    for vector in vectors:
        for i in range(dims):
            totals[i] += vector[i]
    count = float(len(vectors))
    return [total / count for total in totals]


def center(vector: list[float], mean: list[float] | None) -> list[float]:
    """Subtract the corpus mean from a vector; identity when mean is None."""
    if not mean or len(mean) != len(vector):
        return vector
    return [value - mean[i] for i, value in enumerate(vector)]


def query(
    config: AgentConfig,
    query_vector: list[float],
    *,
    top_k: int,
    min_similarity: float | None = None,
    exclude_paths: set[str] | None = None,
    index: dict[str, Any] | None = None,
) -> list[tuple[str, float]]:
    loaded = index if index is not None else load_index(config)
    records = index_records(loaded)
    mean = loaded.get("mean") if loaded.get("centered") else None
    if mean:
        records = [
            {"path": record["path"], "vector": center(record["vector"], mean)}
            for record in records
            if isinstance(record.get("vector"), list)
        ]
        query_vector = center(query_vector, mean)
    return rank(
        query_vector,
        records,
        top_k=top_k,
        min_similarity=min_similarity,
        exclude_paths=exclude_paths,
    )


def embedding_text(title: str, body: str, *, excerpt_chars: int) -> str:
    """Build the text embedded for a note: title plus a bounded body excerpt."""
    excerpt = body.strip()[: max(0, excerpt_chars)]
    title = (title or "").strip()
    if title and excerpt:
        return f"{title}\n\n{excerpt}"
    return title or excerpt


def build_or_refresh_index(
    config: AgentConfig,
    client: EmbeddingClient,
    *,
    dry_run: bool = False,
) -> IndexResult:
    """Embed new/changed notes, reuse unchanged vectors, drop deleted notes."""
    excerpt_chars = getattr(config, "embeddings_excerpt_chars", DEFAULT_EXCERPT_CHARS)
    loaded_index = load_index(config)
    model_identity = _client_model_identity(client)
    existing = {}
    if _index_matches_model(loaded_index, client, model_identity):
        existing = {
            record["path"]: record
            for record in index_records(loaded_index)
            if isinstance(record.get("path"), str)
        }

    scan = scan_vault(config.vault_root)
    records: list[dict[str, Any]] = []
    pending: list[tuple[int, str]] = []  # (record index, text to embed)
    embedded = 0
    reused = 0

    for entry in scan.entries:
        path = entry["path"]
        content_hash = entry.get("hash")
        if entry.get("frontmatter_error"):
            # Still index by title so malformed notes remain searchable.
            pass
        prior = existing.get(path)
        if (
            prior
            and prior.get("content_hash") == content_hash
            and isinstance(prior.get("vector"), list)
        ):
            records.append(
                {
                    "path": path,
                    "title": entry.get("title") or Path(path).stem,
                    "content_hash": content_hash,
                    "vector": prior["vector"],
                }
            )
            reused += 1
            continue
        title = entry.get("title") or Path(path).stem
        body = _note_body(config.vault_root / path)
        text = embedding_text(title, body, excerpt_chars=excerpt_chars)
        record = {
            "path": path,
            "title": title,
            "content_hash": content_hash,
            "vector": [],
        }
        records.append(record)
        pending.append((len(records) - 1, text))

    if pending:
        vectors = client.embed([text for _, text in pending])
        for (record_index, _), vector in zip(pending, vectors):
            records[record_index]["vector"] = vector
        embedded = len(pending)

    removed = len([path for path in existing if path not in {r["path"] for r in records}])
    dimensions = len(records[0]["vector"]) if records and records[0]["vector"] else None
    vectors = [r["vector"] for r in records if r.get("vector")]
    centered = len(vectors) >= MIN_CENTER_NOTES
    mean = mean_vector(vectors) if centered else None
    index = {
        "generated_by": "vault-agent",
        "model": client.model,
        "model_identity": model_identity,
        "dimensions": dimensions,
        "note_count": len(records),
        "centered": centered,
        "mean": mean,
        "notes": records,
    }

    if not dry_run:
        backup_root = config.vault_root / config.paths.agent_dir / "backups"
        write_text_safely(
            index_path(config),
            json.dumps(index, indent=2, sort_keys=True) + "\n",
            backup_root=backup_root,
        )

    return IndexResult(
        total=len(records),
        embedded=embedded,
        reused=reused,
        removed=removed,
        records=records,
        mean=mean,
        centered=centered,
    )


def _note_body(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    parsed = parse_note(text)
    return parsed.body if parsed.body else text


def _client_model_identity(client: EmbeddingClient) -> dict[str, Any]:
    identity_method = getattr(client, "model_identity", None)
    if callable(identity_method):
        identity = identity_method()
        if isinstance(identity, dict):
            return identity
    return {"id": client.model}


def _index_matches_model(
    index: dict[str, Any],
    client: EmbeddingClient,
    model_identity: dict[str, Any],
) -> bool:
    return index.get("model") == client.model and index.get("model_identity") == model_identity
