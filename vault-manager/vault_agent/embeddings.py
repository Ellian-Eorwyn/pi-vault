"""Embedding client and pure-Python similarity helpers.

This is the shared foundation for embedding-backed features (related-note
discovery, semantic search, and the deferred roadmap phases). It mirrors the
HTTP/error-handling shape of the chat provider in ``llm.py`` but talks to an
OpenAI-compatible ``/v1/embeddings`` endpoint. There is no new runtime
dependency: requests use ``urllib`` and ranking is plain Python.
"""

from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from typing import Any, Iterable

DEFAULT_BATCH_SIZE = 64

# Some embedding servers cap tokens per input (the physical/ubatch size). When a
# single input exceeds that cap the server reports the token counts; we parse them
# to truncate proportionally and retry instead of failing the whole run.
_TOO_LARGE_RE = re.compile(r"input \((\d+) tokens\).*batch size: (\d+)", re.IGNORECASE)
_MAX_TRUNCATION_RETRIES = 6


class _InputTooLarge(Exception):
    def __init__(self, tokens: int | None, limit: int | None) -> None:
        super().__init__("embedding input exceeds the server token limit")
        self.tokens = tokens
        self.limit = limit


class EmbeddingClient:
    """Minimal OpenAI-compatible embeddings client."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: int = 120,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.batch_size = max(1, batch_size)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text, preserving order."""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def embed_one(self, text: str) -> list[float]:
        vectors = self.embed([text])
        if not vectors:
            raise ValueError("embedding request returned no vectors")
        return vectors[0]

    def model_identity(self) -> dict[str, Any]:
        """Best-effort backend metadata for cache invalidation.

        Local servers often keep a stable public model id such as ``embed`` while
        swapping the underlying GGUF. When `/v1/models` exposes dimensions or
        parameter counts, store them in the index so a model upgrade invalidates
        stale vectors even if the configured alias is unchanged.
        """
        request = urllib.request.Request(
            f"{self.base_url}/v1/models",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            return {"id": self.model}
        return _model_identity_from_payload(payload, self.model)

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        """Embed a batch, recovering from per-input token-limit rejections.

        On a "too large" rejection we split multi-item batches to isolate the
        offending input, then truncate that single input proportionally to the
        server-reported token counts and retry. This keeps a few dense notes from
        failing a whole-vault embed.
        """
        try:
            return self._post(batch)
        except _InputTooLarge as exc:
            if len(batch) > 1:
                mid = len(batch) // 2
                return self._embed_batch(batch[:mid]) + self._embed_batch(batch[mid:])
            return [self._embed_truncated(batch[0], exc)]

    def _embed_truncated(self, text: str, exc: _InputTooLarge) -> list[float]:
        tokens, limit = exc.tokens, exc.limit
        for _ in range(_MAX_TRUNCATION_RETRIES):
            if tokens and limit and tokens > 0:
                ratio = (limit / tokens) * 0.9
            else:
                ratio = 0.5
            new_len = max(1, min(len(text) - 1, int(len(text) * ratio)))
            text = text[:new_len]
            try:
                return self._post([text])[0]
            except _InputTooLarge as retry:
                tokens, limit = retry.tokens, retry.limit
        raise ValueError("embedding input remained too large after truncation")

    def _post(self, inputs: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": inputs}
        request = urllib.request.Request(
            f"{self.base_url}/v1/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            exc.close()
            match = _TOO_LARGE_RE.search(body)
            if match:
                raise _InputTooLarge(int(match.group(1)), int(match.group(2))) from exc
            raise ValueError(
                f"embedding request failed with HTTP {exc.code}: {body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"embedding request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ValueError("embedding request timed out") from exc
        return _vectors_from_payload(response_payload, expected=len(inputs))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


def embedding_client_from_config(config: Any) -> EmbeddingClient | None:
    """Build the configured embedding client, or None when embeddings are off."""
    if not getattr(config, "embeddings_enabled", False):
        return None
    base_url = getattr(config, "embedding_base_url", None)
    if not base_url:
        return None
    model = getattr(config, "embedding_model", None) or "embed"
    return EmbeddingClient(
        base_url=base_url,
        model=model,
        api_key=getattr(config, "llm_api_key", None),
        timeout_seconds=int(getattr(config, "llm_timeout_seconds", 120)),
        batch_size=int(getattr(config, "embeddings_batch_size", DEFAULT_BATCH_SIZE)),
    )


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 for zero vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def rank(
    query_vector: list[float],
    records: Iterable[dict[str, Any]],
    *,
    top_k: int,
    min_similarity: float | None = None,
    exclude_paths: set[str] | None = None,
) -> list[tuple[str, float]]:
    """Rank ``records`` (each with ``path`` and ``vector``) against a query vector.

    Returns ``(path, score)`` tuples sorted by descending score then path,
    truncated to ``top_k``. Records below ``min_similarity`` are dropped.
    """
    excluded = exclude_paths or set()
    scored: list[tuple[str, float]] = []
    for record in records:
        path = record.get("path")
        vector = record.get("vector")
        if not isinstance(path, str) or not isinstance(vector, list):
            continue
        if path in excluded:
            continue
        score = cosine(query_vector, vector)
        if min_similarity is not None and score < min_similarity:
            continue
        scored.append((path, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    if top_k > 0:
        return scored[:top_k]
    return scored


def _vectors_from_payload(payload: Any, *, expected: int) -> list[list[float]]:
    if not isinstance(payload, dict):
        raise ValueError("embedding response was not a JSON object")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("embedding response missing `data` list")
    ordered: list[tuple[int, list[float]]] = []
    for position, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError("embedding response item was not an object")
        vector = item.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise ValueError("embedding response item missing `embedding`")
        index = item.get("index")
        order = index if isinstance(index, int) else position
        ordered.append((order, [float(value) for value in vector]))
    ordered.sort(key=lambda pair: pair[0])
    vectors = [vector for _, vector in ordered]
    if len(vectors) != expected:
        raise ValueError(
            f"embedding response returned {len(vectors)} vectors for {expected} inputs"
        )
    return vectors


def _model_identity_from_payload(payload: Any, model: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"id": model}
    candidates = payload.get("data")
    if not isinstance(candidates, list):
        candidates = payload.get("models")
    if not isinstance(candidates, list):
        return {"id": model}

    selected: dict[str, Any] | None = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        aliases = candidate.get("aliases")
        names = {
            str(candidate.get("id", "")),
            str(candidate.get("model", "")),
            str(candidate.get("name", "")),
        }
        if isinstance(aliases, list):
            names.update(str(alias) for alias in aliases)
        if model in names:
            selected = candidate
            break
    if selected is None:
        return {"id": model}

    meta = selected.get("meta")
    if not isinstance(meta, dict):
        meta = selected.get("details")
    if not isinstance(meta, dict):
        meta = {}

    identity: dict[str, Any] = {
        "id": str(selected.get("id") or selected.get("model") or selected.get("name") or model)
    }
    for source_key, target_key in (
        ("model", "model"),
        ("name", "name"),
        ("n_embd", "dimensions"),
        ("n_ctx", "context"),
        ("n_params", "parameters"),
        ("size", "size"),
        ("digest", "digest"),
    ):
        value = selected.get(source_key, meta.get(source_key))
        if value not in (None, ""):
            identity[target_key] = value
    return identity
