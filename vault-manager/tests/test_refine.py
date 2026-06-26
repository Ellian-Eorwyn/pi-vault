import contextlib
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from vault_agent.cli import main
from vault_agent.config import load_config
from vault_agent.llm import JsonFileProposalProvider, validate_stage_proposal
from vault_agent.refine import content_words, meaning_preserved, run_propose_folder_refinement


class MeaningGuardTests(unittest.TestCase):
    def test_reflow_and_formatting_preserved(self):
        old = "Alpha beta gamma. Delta epsilon."
        new = "## Heading\n\n- Alpha **beta** gamma.\n- Delta *epsilon*.\n"
        ok, report = meaning_preserved(old, new)
        self.assertTrue(ok, report)

    def test_ordered_to_bullets_not_flagged(self):
        old = "1. first item\n2. second item\n"
        new = "- first item\n- second item\n"
        ok, report = meaning_preserved(old, new)
        self.assertTrue(ok, report)

    def test_dropped_sentence_blocked(self):
        old = "Alpha beta gamma. Delta epsilon zeta."
        new = "Alpha beta gamma."
        ok, report = meaning_preserved(old, new)
        self.assertFalse(ok)
        self.assertGreater(report["dropped_count"], 0)
        self.assertIn("delta", report["dropped"])

    def test_paraphrase_blocked(self):
        old = "The cat sat on the mat."
        new = "The feline rested on the rug."
        ok, report = meaning_preserved(old, new)
        self.assertFalse(ok)
        self.assertIn("cat", report["dropped"])

    def test_large_insertion_blocked(self):
        old = "Alpha beta gamma."
        new = "Alpha beta gamma. " + " ".join(f"extra{index}" for index in range(30))
        ok, report = meaning_preserved(old, new)
        self.assertFalse(ok)
        self.assertGreater(report["added_count"], 0)

    def test_heading_label_within_budget(self):
        old = "Alpha beta gamma delta epsilon."
        new = "## Summary\n\nAlpha beta gamma delta epsilon.\n"
        ok, report = meaning_preserved(old, new)
        self.assertTrue(ok, report)

    def test_content_words_ignores_structural_tokens(self):
        words = content_words("# Title\n\n- [[Wiki Link]] and `code`\n")
        self.assertEqual(words["wiki"], 1)
        self.assertEqual(words["link"], 1)
        self.assertEqual(words["code"], 1)
        self.assertEqual(words["title"], 1)


class RefineStageValidationTests(unittest.TestCase):
    def test_valid_body(self):
        validation = validate_stage_proposal(
            "refine-body", {"body": "## H\n\ntext", "confidence": 0.9, "warnings": []}
        )
        self.assertTrue(validation.valid, validation.errors)
        self.assertEqual(validation.proposal["body"], "## H\n\ntext")

    def test_missing_body_rejected(self):
        validation = validate_stage_proposal("refine-body", {"confidence": 0.5})
        self.assertFalse(validation.valid)

    def test_empty_body_rejected(self):
        validation = validate_stage_proposal("refine-body", {"body": "   "})
        self.assertFalse(validation.valid)

    def test_unknown_key_rejected(self):
        validation = validate_stage_proposal(
            "refine-body", {"body": "x", "status": "active"}
        )
        self.assertFalse(validation.valid)


class ApplyRestructureBodyTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def _write_proposal(self, root: Path, body: str) -> None:
        proposals = root / "99 System" / "0.01 agent" / "review" / "proposals"
        proposals.mkdir(parents=True)
        (proposals / "refine.json").write_text(
            json.dumps(
                {
                    "id": "refine-note",
                    "title": "Refine note",
                    "kind": "note-refinement",
                    "status": "approved",
                    "operations": [
                        {"op": "restructure_body", "path": "note.md", "body": body}
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_apply_rewrites_body_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "note.md"
            note.write_text(
                "---\ntype: note\nstatus: active\n---\n\nAlpha beta gamma. Delta epsilon.\n",
                encoding="utf-8",
            )
            self._write_proposal(root, "## Notes\n\n- Alpha beta gamma.\n- Delta epsilon.\n")

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            text = note.read_text(encoding="utf-8")
            backups = list(
                (root / "99 System" / "0.01 agent" / "backups").glob("note.md.*.bak")
            )

        self.assertEqual(exit_code, 0, output)
        self.assertIn("Applied: 1", output)
        self.assertTrue(text.startswith("---\ntype: note\nstatus: active\n---\n"))
        self.assertIn("- Alpha beta gamma.", text)
        self.assertIn("## Notes", text)
        self.assertEqual(len(backups), 1)

    def test_apply_blocks_meaning_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "note.md"
            original = "---\ntype: note\n---\n\nAlpha beta gamma. Delta epsilon zeta.\n"
            note.write_text(original, encoding="utf-8")
            self._write_proposal(root, "## Trimmed\n\nAlpha beta gamma.\n")

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            text = note.read_text(encoding="utf-8")

        self.assertNotEqual(exit_code, 0)
        self.assertIn("would change wording", output)
        self.assertEqual(text, original)


class FolderRefinementGeneratorTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def config_for(self, directory):
        return load_config(
            Namespace(vault_root=directory, config=None, dry_run=False, verbose=False)
        )

    def test_generator_writes_guarded_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "06 Thoughts"
            folder.mkdir(parents=True)
            (folder / "idea.md").write_text(
                "---\ntype: note\n---\n\nAlpha beta gamma. Delta epsilon.\n",
                encoding="utf-8",
            )
            self.run_cli(["--vault-root", directory, "norms-lock", "--write"])
            provider_file = root / "stage.json"
            provider_file.write_text(
                json.dumps(
                    {
                        "body": "## Notes\n\n- Alpha beta gamma.\n- Delta epsilon.\n",
                        "confidence": 0.9,
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )
            config = self.config_for(directory)
            exit_code, output = run_propose_folder_refinement(
                config,
                folder="06 Thoughts",
                proposal_provider=JsonFileProposalProvider(provider_file),
            )
            proposals = list(
                (root / "99 System" / "0.01 agent" / "review" / "proposals").glob("*.json")
            )
            proposal = json.loads(proposals[0].read_text(encoding="utf-8")) if proposals else {}

        self.assertEqual(exit_code, 0, output)
        self.assertIn("Proposed refinements: 1", output)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposal["kind"], "note-refinement")
        self.assertEqual(proposal["operations"][0]["op"], "restructure_body")

    def test_generator_blocks_meaning_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "06 Thoughts"
            folder.mkdir(parents=True)
            (folder / "idea.md").write_text(
                "---\ntype: note\n---\n\nAlpha beta gamma. Delta epsilon zeta.\n",
                encoding="utf-8",
            )
            self.run_cli(["--vault-root", directory, "norms-lock", "--write"])
            provider_file = root / "stage.json"
            provider_file.write_text(
                json.dumps({"body": "Alpha beta gamma.", "confidence": 0.9, "warnings": []}),
                encoding="utf-8",
            )
            config = self.config_for(directory)
            exit_code, output = run_propose_folder_refinement(
                config,
                folder="06 Thoughts",
                proposal_provider=JsonFileProposalProvider(provider_file),
            )
            proposals = list(
                (root / "99 System" / "0.01 agent" / "review" / "proposals").glob("*.json")
            )

        self.assertNotEqual(exit_code, 0)
        self.assertIn("Blocked", output)
        self.assertEqual(len(proposals), 0)

    def test_missing_lock_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "06 Thoughts"
            folder.mkdir(parents=True)
            (folder / "idea.md").write_text("---\ntype: note\n---\n\nBody.\n", encoding="utf-8")
            provider_file = root / "stage.json"
            provider_file.write_text(json.dumps({"body": "Body."}), encoding="utf-8")
            config = self.config_for(directory)
            exit_code, output = run_propose_folder_refinement(
                config,
                folder="06 Thoughts",
                proposal_provider=JsonFileProposalProvider(provider_file),
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("missing norms lock", output)


if __name__ == "__main__":
    unittest.main()
