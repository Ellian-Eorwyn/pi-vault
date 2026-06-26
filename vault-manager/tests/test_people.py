import contextlib
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from vault_agent.cli import main
from vault_agent.config import load_config
from vault_agent.people import run_propose_people


class FakeProvider:
    """Classifies by name so one contact and one author are produced deterministically."""

    def propose_stage(self, *, note_path, note_text, stage, **kwargs):
        if "Darwin" in note_path.as_posix():
            return {"kind": "author", "details": "Naturalist.", "confidence": 0.9, "warnings": []}
        return {"kind": "contact", "details": "Met at the conference.", "confidence": 0.9, "warnings": []}


class PeopleExtractionTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def config_for(self, directory, *, dry_run=False):
        return load_config(
            Namespace(vault_root=directory, config=None, dry_run=dry_run, verbose=False)
        )

    def _seed(self, root: Path) -> None:
        notes = root / "06 Thoughts"
        notes.mkdir(parents=True)
        (notes / "mtg.md").write_text(
            "---\ntype: note\n---\n# Meeting\n\nMet with Jane Smith about the grant.\n",
            encoding="utf-8",
        )
        (notes / "reading.md").write_text(
            "---\ntype: note\n---\n# Reading\n\nKey thinkers, Charles Darwin, who shaped the field.\n",
            encoding="utf-8",
        )

    def test_requires_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config_for(directory)
            exit_code, output = run_propose_people(config, proposal_provider=None)
        self.assertEqual(exit_code, 1)
        self.assertIn("configured LLM backend", output)

    def test_creates_contact_and_author(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._seed(root)
            config = self.config_for(directory)
            exit_code, output = run_propose_people(config, proposal_provider=FakeProvider())
            proposal = json.loads(
                (root / "99 System" / "0.01 agent" / "review" / "proposals" / "people-extraction.json").read_text()
            )
            paths = sorted(op["path"] for op in proposal["operations"])

        self.assertEqual(exit_code, 0, output)
        self.assertEqual(proposal["kind"], "people-extraction")
        self.assertEqual(
            paths,
            ["02 People/02.01 Contacts/Jane Smith.md", "02 People/02.02 Authors/Charles Darwin.md"],
        )

    def test_apply_sets_parent_and_dedups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._seed(root)
            run_propose_people(self.config_for(directory), proposal_provider=FakeProvider())
            proposal_path = root / "99 System" / "0.01 agent" / "review" / "proposals" / "people-extraction.json"
            data = json.loads(proposal_path.read_text())
            data["status"] = "approved"
            proposal_path.write_text(json.dumps(data), encoding="utf-8")
            self.run_cli(["--vault-root", directory, "review-proposals", "--apply-approved"])
            jane = (root / "02 People" / "02.01 Contacts" / "Jane Smith.md").read_text()

            second_dry = self.config_for(directory, dry_run=True)
            _code, second_out = run_propose_people(second_dry, proposal_provider=FakeProvider())

        self.assertIn('parent: "[[Contacts]]"', jane)
        self.assertIn("[[mtg]]", jane)
        self.assertIn("## Mentions", jane)
        self.assertIn("New person notes proposed: 0", second_out)

    def test_single_token_name_goes_to_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes = root / "06 Thoughts"
            notes.mkdir(parents=True)
            (notes / "n.md").write_text(
                "---\ntype: note\n---\n# Note\n\nSpoke with Bob about it.\n",
                encoding="utf-8",
            )
            config = self.config_for(directory)
            exit_code, output = run_propose_people(config, proposal_provider=FakeProvider())
        self.assertIn("New person notes proposed: 0", output)
        self.assertIn("Routed to review", output)


if __name__ == "__main__":
    unittest.main()
