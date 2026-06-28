"""Offline unit tests for the eval-suite graders.

These exercise the scoring logic with synthetic inputs only (no model endpoints),
so they run as part of the normal suite: ``python3 -m unittest discover -s tests``.
"""

from __future__ import annotations

import unittest

from evals.graders import constrained, people, refine, retrieval, summary


_VOCAB = ["garden", "pond", "fish", "water", "python", "code", "money", "budget"]


def fake_embed(texts):
    """Deterministic bag-of-words vectors, mirroring tests/test_embeddings.py."""
    return [[float(t.lower().count(word)) for word in _VOCAB] for t in texts]


class ConstrainedTests(unittest.TestCase):
    def test_accuracy_and_macro_f1(self):
        items = [
            {"pred": "note", "gold": "note"},
            {"pred": "note", "gold": "source"},
            {"pred": "person", "gold": "person"},
            {"pred": "person", "gold": "person"},
        ]
        result = constrained.grade_field(items)
        self.assertEqual(result["n"], 4)
        self.assertEqual(result["correct"], 3)
        self.assertAlmostEqual(result["accuracy"], 0.75)
        # person is perfectly predicted -> f1 1.0 for that class
        self.assertEqual(result["per_class"]["person"]["f1"], 1.0)
        self.assertEqual(result["confusion"]["source"]["note"], 1)

    def test_list_and_case_normalisation(self):
        items = [{"pred": ["Work"], "gold": "work"}, {"pred": "  WORK ", "gold": "work"}]
        self.assertEqual(constrained.grade_field(items)["accuracy"], 1.0)

    def test_grade_fields_only_scores_present_gold(self):
        records = [
            {"pred": {"status": "active"}, "gold": {"status": "active"}},
            {"pred": {"status": "archived"}, "gold": {"status": "active", "domain": "work"}},
        ]
        out = constrained.grade_fields(records, ["status", "domain"])
        self.assertEqual(out["status"]["n"], 2)
        self.assertEqual(out["domain"]["n"], 1)


class SummaryTests(unittest.TestCase):
    def test_identical_summary_has_high_cosine(self):
        items = [{"path": "a", "pred": "garden pond fish.", "ref": "garden pond fish."}]
        result = summary.grade_summaries(items, fake_embed)
        self.assertAlmostEqual(result["mean_cosine"], 1.0, places=4)
        self.assertEqual(result["length_ok_rate"], 1.0)

    def test_length_rules(self):
        self.assertTrue(summary.length_ok("One sentence here."))
        self.assertFalse(summary.length_ok("A. B. C. D."))  # 4 sentences
        self.assertFalse(summary.length_ok("x" * 1001))
        self.assertEqual(summary.sentence_count("One. Two! Three?"), 3)

    def test_missing_prediction_lowers_produced_rate(self):
        items = [
            {"path": "a", "pred": "garden", "ref": "garden"},
            {"path": "b", "pred": "", "ref": "pond"},
        ]
        result = summary.grade_summaries(items, fake_embed)
        self.assertEqual(result["produced_rate"], 0.5)
        self.assertEqual(result["n_scored"], 1)


class RefineTests(unittest.TestCase):
    def test_headings_only_preserve_words(self):
        source = "the cat sat on the mat"
        refined = "## Summary\n\nthe cat sat on the mat"
        one = refine.grade_one(source, refined)
        self.assertEqual(one["preservation"], 1.0)
        self.assertEqual(one["added_ratio"], 0.0)  # "summary" is allow-listed

    def test_invented_words_flagged(self):
        source = "the cat sat"
        refined = "the cat sat on a luxurious velvet throne"
        one = refine.grade_one(source, refined)
        self.assertEqual(one["preservation"], 1.0)
        self.assertGreater(one["added_ratio"], 0.0)
        self.assertIn("velvet", one["top_added"])

    def test_dropped_words_lower_preservation(self):
        one = refine.grade_one("the cat sat on the mat", "the cat")
        self.assertLess(one["preservation"], 0.5)


class PeopleTests(unittest.TestCase):
    def test_extraction_prf(self):
        items = [{"path": "a", "pred": ["Alan Meier", "[[Jane Doe]]"], "gold": ["alan meier", "John Roe"]}]
        result = people.grade_extraction(items)
        self.assertEqual(result["tp"], 1)
        self.assertEqual(result["fp"], 1)
        self.assertEqual(result["fn"], 1)
        self.assertAlmostEqual(result["precision"], 0.5)
        self.assertAlmostEqual(result["recall"], 0.5)

    def test_classify_reuses_constrained(self):
        items = [{"pred": "contact", "gold": "contact"}, {"pred": "author", "gold": "contact"}]
        self.assertEqual(people.grade_classify(items)["accuracy"], 0.5)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"path": "d1", "vector": [1.0, 0.0, 0.0]},
            {"path": "d2", "vector": [0.9, 0.1, 0.0]},
            {"path": "d3", "vector": [0.0, 0.0, 1.0]},
        ]
        self.index = retrieval.build_index(self.records)

    def test_centering_threshold(self):
        self.assertFalse(self.index["centered"])
        big = [{"path": f"n{i}", "vector": [float(i), 1.0]} for i in range(30)]
        self.assertTrue(retrieval.build_index(big)["centered"])

    def test_retrieval_metrics(self):
        queries = [{"query": "q", "query_vector": [1.0, 0.0, 0.0], "relevant": ["d1"]}]
        result = retrieval.retrieval_metrics(queries, self.index, ks=(5,))
        self.assertEqual(result["recall@5"], 1.0)
        self.assertEqual(result["mrr"], 1.0)

    def test_related_links(self):
        pairs = [{"path": "d1", "related": ["d2"]}]
        result = retrieval.related_links_metrics(pairs, self.index, top_k=2, min_similarity=0.5)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)

    def test_duplicates(self):
        dup = [{"label": "x", "a_vector": [1.0, 0.0], "b_vector": [1.0, 0.0]}]
        self.assertEqual(retrieval.duplicate_metrics(dup, threshold=0.97)["detection_rate"], 1.0)

    def test_calibrate_keys(self):
        cal = retrieval.calibrate(self.index, sample_pairs=10)
        self.assertEqual(cal["note_count"], 3)
        for key in ("min_similarity", "related_min_similarity", "duplicate_min_similarity"):
            self.assertIn(key, cal["recommended_thresholds"])

    def test_agreement_identical_indexes(self):
        records = [{"path": f"n{i}", "vector": [float(i), 1.0, float(i % 3)]} for i in range(8)]
        idx = retrieval.build_index(records)
        ag = retrieval.agreement(idx, idx, top_k=3)
        self.assertEqual(ag["jaccard@k"], 1.0)
        self.assertEqual(ag["mean_spearman"], 1.0)

    def test_spearman_monotonic(self):
        self.assertEqual(retrieval._spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertEqual(retrieval._spearman([1, 2, 3, 4], [40, 30, 20, 10]), -1.0)


if __name__ == "__main__":
    unittest.main()
