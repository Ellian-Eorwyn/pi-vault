import io
import json
import tempfile
import unittest
import urllib.error
from argparse import Namespace
from pathlib import Path
from unittest import mock

from vault_agent import embeddings
from vault_agent.config import load_config
from vault_agent.embedding_index import (
    MIN_CENTER_NOTES,
    build_or_refresh_index,
    center,
    index_records,
    load_index,
    mean_vector,
)
from vault_agent.embeddings import EmbeddingClient, cosine, rank
from vault_agent.related_links import run_propose_related_links
from vault_agent.search import run_search

# A tiny fixed vocabulary so bag-of-words vectors yield meaningful cosine values.
_VOCAB = ["garden", "pond", "fish", "water", "python", "code", "money", "budget"]


class FakeEmbeddingClient:
    """Deterministic bag-of-words embeddings over a fixed vocabulary."""

    model = "fake-embed"

    def __init__(self):
        self.calls = 0
        self.embedded_texts: list[str] = []

    def embed(self, texts):
        self.calls += 1
        self.embedded_texts.extend(texts)
        return [self._vector(text) for text in texts]

    def embed_one(self, text):
        return self.embed([text])[0]

    @staticmethod
    def _vector(text):
        lowered = text.lower()
        return [float(lowered.count(word)) for word in _VOCAB]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._payload


class CosineRankTests(unittest.TestCase):
    def test_cosine_basic(self):
        self.assertAlmostEqual(cosine([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(cosine([1.0, 0.0], [0.0, 1.0]), 0.0)
        self.assertEqual(cosine([0.0, 0.0], [1.0, 1.0]), 0.0)
        self.assertEqual(cosine([1.0], [1.0, 2.0]), 0.0)

    def test_rank_orders_and_filters(self):
        records = [
            {"path": "a.md", "vector": [1.0, 0.0]},
            {"path": "b.md", "vector": [0.9, 0.1]},
            {"path": "c.md", "vector": [0.0, 1.0]},
        ]
        ranked = rank([1.0, 0.0], records, top_k=2)
        self.assertEqual([path for path, _ in ranked], ["a.md", "b.md"])

        excluded = rank([1.0, 0.0], records, top_k=5, exclude_paths={"a.md"})
        self.assertEqual([path for path, _ in excluded][0], "b.md")

        thresholded = rank([1.0, 0.0], records, top_k=5, min_similarity=0.5)
        self.assertNotIn("c.md", [path for path, _ in thresholded])


class EmbeddingClientTests(unittest.TestCase):
    def test_preserves_order_from_index(self):
        payload = {
            "data": [
                {"embedding": [0.0, 1.0], "index": 1},
                {"embedding": [1.0, 0.0], "index": 0},
            ]
        }
        client = EmbeddingClient(base_url="http://x", model="m")
        with mock.patch(
            "vault_agent.embeddings.urllib.request.urlopen",
            return_value=_FakeResponse(payload),
        ):
            vectors = client.embed(["first", "second"])
        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0]])

    def test_batches_requests(self):
        calls = []

        def fake_urlopen(request, timeout=None):
            body = json.loads(request.data.decode("utf-8"))
            calls.append(len(body["input"]))
            data = [
                {"embedding": [float(i)], "index": i}
                for i in range(len(body["input"]))
            ]
            return _FakeResponse({"data": data})

        client = EmbeddingClient(base_url="http://x", model="m", batch_size=2)
        with mock.patch(
            "vault_agent.embeddings.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            vectors = client.embed(["a", "b", "c"])
        self.assertEqual(calls, [2, 1])
        self.assertEqual(len(vectors), 3)

    def test_recovers_from_token_limit(self):
        # Simulate a server with a 10-"token" (char) per-input cap that rejects
        # oversized inputs the way llama.cpp does.
        limit = 10

        def fake_urlopen(request, timeout=None):
            body = json.loads(request.data.decode("utf-8"))
            inputs = body["input"]
            for text in inputs:
                if len(text) > limit:
                    raise urllib.error.HTTPError(
                        "http://x/v1/embeddings",
                        500,
                        "Internal Server Error",
                        {},
                        io.BytesIO(
                            json.dumps(
                                {
                                    "error": {
                                        "message": (
                                            f"input ({len(text)} tokens) is too large "
                                            f"to process. increase the physical batch "
                                            f"size (current batch size: {limit})"
                                        )
                                    }
                                }
                            ).encode("utf-8")
                        ),
                    )
            data = [{"embedding": [float(len(t))], "index": i} for i, t in enumerate(inputs)]
            return _FakeResponse({"data": data})

        client = EmbeddingClient(base_url="http://x", model="m", batch_size=8)
        with mock.patch(
            "vault_agent.embeddings.urllib.request.urlopen", side_effect=fake_urlopen
        ):
            vectors = client.embed(["short", "x" * 40, "ok"])
        # All three resolve to a vector; the oversized one is truncated, not failed.
        self.assertEqual(len(vectors), 3)
        self.assertTrue(all(len(v) == 1 for v in vectors))

    def test_client_from_config_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(
                Namespace(vault_root=directory, config=None, dry_run=False, verbose=False)
            )
        self.assertIsNone(embeddings.embedding_client_from_config(config))


class EmbeddingIndexTests(unittest.TestCase):
    def _config(self, directory):
        return load_config(
            Namespace(vault_root=directory, config=None, dry_run=False, verbose=False)
        )

    def _seed(self, root: Path):
        notes = root / "06 Thoughts"
        notes.mkdir(parents=True)
        (notes / "a.md").write_text(
            "---\ntype: note\n---\n# Garden\n\ngarden pond fish\n", encoding="utf-8"
        )
        (notes / "b.md").write_text(
            "---\ntype: note\n---\n# Pond\n\ngarden pond fish water\n", encoding="utf-8"
        )
        (notes / "c.md").write_text(
            "---\ntype: note\n---\n# Code\n\npython code money budget\n", encoding="utf-8"
        )

    def test_incremental_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._seed(root)
            config = self._config(directory)
            client = FakeEmbeddingClient()

            first = build_or_refresh_index(config, client)
            self.assertEqual(first.total, 3)
            self.assertEqual(first.embedded, 3)
            self.assertEqual(first.reused, 0)

            index = load_index(config)
            self.assertEqual(len(index_records(index)), 3)
            self.assertEqual(index["model"], "fake-embed")

            # Unchanged rebuild reuses every vector (no new embed calls needed).
            client2 = FakeEmbeddingClient()
            second = build_or_refresh_index(config, client2)
            self.assertEqual(second.embedded, 0)
            self.assertEqual(second.reused, 3)
            self.assertEqual(client2.calls, 0)

            # Change one note -> only it is re-embedded.
            (root / "06 Thoughts" / "a.md").write_text(
                "---\ntype: note\n---\n# Garden\n\ngarden pond fish water budget\n",
                encoding="utf-8",
            )
            client3 = FakeEmbeddingClient()
            third = build_or_refresh_index(config, client3)
            self.assertEqual(third.embedded, 1)
            self.assertEqual(third.reused, 2)

            # Delete a note -> it is dropped from the index.
            (root / "06 Thoughts" / "c.md").unlink()
            client4 = FakeEmbeddingClient()
            fourth = build_or_refresh_index(config, client4)
            self.assertEqual(fourth.total, 2)
            self.assertEqual(fourth.removed, 1)


class CenteringTests(unittest.TestCase):
    def test_mean_vector_and_center(self):
        self.assertIsNone(mean_vector([]))
        self.assertEqual(mean_vector([[2.0, 4.0], [4.0, 8.0]]), [3.0, 6.0])
        self.assertEqual(center([3.0, 6.0], [1.0, 2.0]), [2.0, 4.0])
        # A None or mismatched mean is the identity transform.
        self.assertEqual(center([1.0, 2.0], None), [1.0, 2.0])
        self.assertEqual(center([1.0, 2.0], [1.0]), [1.0, 2.0])

    def _config(self, directory):
        return load_config(
            Namespace(vault_root=directory, config=None, dry_run=False, verbose=False)
        )

    def test_small_vault_falls_back_to_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes = root / "06 Thoughts"
            notes.mkdir(parents=True)
            for i in range(3):
                (notes / f"n{i}.md").write_text(
                    f"---\ntype: note\n---\n# N{i}\n\ngarden pond fish\n",
                    encoding="utf-8",
                )
            config = self._config(directory)
            result = build_or_refresh_index(config, FakeEmbeddingClient())
            index = load_index(config)
        self.assertLess(result.total, MIN_CENTER_NOTES)
        self.assertFalse(result.centered)
        self.assertIsNone(result.mean)
        self.assertFalse(index["centered"])
        self.assertIsNone(index["mean"])

    def test_large_vault_centers_and_search_ranks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes = root / "06 Thoughts"
            notes.mkdir(parents=True)
            for i in range(MIN_CENTER_NOTES + 5):
                body = "garden pond fish water" if i % 2 == 0 else "python code money budget"
                (notes / f"n{i}.md").write_text(
                    f"---\ntype: note\n---\n# N{i}\n\n{body}\n", encoding="utf-8"
                )
            config = self._config(directory)
            client = FakeEmbeddingClient()
            result = build_or_refresh_index(config, client)
            index = load_index(config)

            self.assertTrue(result.centered)
            self.assertTrue(index["centered"])
            self.assertEqual(len(index["mean"]), len(_VOCAB))

            exit_code, output = run_search(
                config,
                query_text="garden pond fish",
                top_k=3,
                json_output=True,
                client=client,
            )
            payload = json.loads(output)

        self.assertEqual(exit_code, 0)
        # Every top result is a garden-themed (even-indexed) note.
        for hit in payload["results"]:
            stem = hit["path"].rsplit("/", 1)[-1][1:-3]
            self.assertEqual(int(stem) % 2, 0, hit["path"])


class RelatedLinksTests(unittest.TestCase):
    def _config(self, directory):
        return load_config(
            Namespace(vault_root=directory, config=None, dry_run=False, verbose=False)
        )

    def _seed(self, root: Path):
        notes = root / "06 Thoughts"
        notes.mkdir(parents=True)
        (notes / "a.md").write_text(
            "---\ntype: note\nrelated: []\n---\n# Garden\n\ngarden pond fish\n",
            encoding="utf-8",
        )
        (notes / "b.md").write_text(
            "---\ntype: note\nrelated: []\n---\n# Pond\n\ngarden pond fish water\n",
            encoding="utf-8",
        )
        (notes / "c.md").write_text(
            "---\ntype: note\nrelated: []\n---\n# Code\n\npython code money budget\n",
            encoding="utf-8",
        )

    def test_requires_client(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self._config(directory)
            exit_code, output = run_propose_related_links(config, client=None)
        self.assertEqual(exit_code, 1)
        self.assertIn("embeddings", output)

    def test_proposes_append_only_related_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._seed(root)
            config = self._config(directory)
            exit_code, output = run_propose_related_links(
                config, client=FakeEmbeddingClient(), min_similarity=0.5
            )
            proposal = json.loads(
                (
                    root
                    / "99 System"
                    / "0.01 agent"
                    / "review"
                    / "proposals"
                    / "related-links.json"
                ).read_text()
            )

        self.assertEqual(exit_code, 0, output)
        self.assertEqual(proposal["kind"], "related-links")
        ops = {op["path"]: op for op in proposal["operations"]}
        # The two similar notes link each other; the dissimilar note gets nothing.
        self.assertIn("06 Thoughts/a.md", ops)
        self.assertIn("06 Thoughts/b.md", ops)
        self.assertNotIn("06 Thoughts/c.md", ops)
        self.assertIn("[[b]]", ops["06 Thoughts/a.md"]["set"]["related"])
        self.assertEqual(ops["06 Thoughts/a.md"]["op"], "update_frontmatter")
        self.assertEqual(ops["06 Thoughts/a.md"]["remove"], [])

    def test_existing_related_preserved_and_not_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes = root / "06 Thoughts"
            notes.mkdir(parents=True)
            (notes / "a.md").write_text(
                "---\ntype: note\nrelated: [\"[[b]]\"]\n---\n# Garden\n\ngarden pond fish\n",
                encoding="utf-8",
            )
            (notes / "b.md").write_text(
                "---\ntype: note\nrelated: []\n---\n# Pond\n\ngarden pond fish water\n",
                encoding="utf-8",
            )
            config = self._config(directory)
            run_propose_related_links(
                config, client=FakeEmbeddingClient(), min_similarity=0.5
            )
            proposal_path = (
                root
                / "99 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "related-links.json"
            )
            proposal = json.loads(proposal_path.read_text())
            ops = {op["path"]: op for op in proposal["operations"]}

        # a.md already links b -> a should not appear (no new additions for it).
        self.assertNotIn("06 Thoughts/a.md", ops)


class SearchTests(unittest.TestCase):
    def _config(self, directory):
        return load_config(
            Namespace(vault_root=directory, config=None, dry_run=False, verbose=False)
        )

    def _seed(self, root: Path):
        notes = root / "06 Thoughts"
        notes.mkdir(parents=True)
        (notes / "garden.md").write_text(
            "---\ntype: note\n---\n# Garden\n\ngarden pond fish water\n", encoding="utf-8"
        )
        (notes / "finance.md").write_text(
            "---\ntype: note\n---\n# Finance\n\npython code money budget\n", encoding="utf-8"
        )

    def test_requires_index(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self._config(directory)
            exit_code, output = run_search(
                config, query_text="garden", client=FakeEmbeddingClient()
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("embed-index", output)

    def test_ranks_relevant_note_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._seed(root)
            config = self._config(directory)
            client = FakeEmbeddingClient()
            build_or_refresh_index(config, client)
            exit_code, output = run_search(
                config,
                query_text="garden pond",
                top_k=2,
                json_output=True,
                client=client,
            )
            payload = json.loads(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["results"][0]["path"], "06 Thoughts/garden.md")
        self.assertGreater(payload["results"][0]["score"], payload["results"][1]["score"])


if __name__ == "__main__":
    unittest.main()
