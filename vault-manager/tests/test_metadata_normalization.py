import json
import tempfile
import unittest
from pathlib import Path

from vault_agent.cli import main


class MetadataNormalizationTests(unittest.TestCase):
    def run_cli(self, args):
        import contextlib
        import io

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_propose_metadata_normalization_generates_reviewable_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "legacy.md"
            note.write_text(
                "---\n"
                "title: Legacy Title\n"
                "created: 2024-01-01\n"
                "type: journal\n"
                "status: raw\n"
                "domains: [personal]\n"
                "tags: [alpha, beta]\n"
                'summary: "type: journal status: raw Clean summary."\n'
                "---\n"
                "# Legacy\n\n"
                "Privacy: private\n"
                "Sensitive: false\n"
                "Topics: [[Alpha]]\n\n"
                "Body text.\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-metadata-normalization",
                    "--all",
                    "--max-items",
                    "10",
                ]
            )
            proposal_path = (
                root
                / "99 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "metadata-normalization-001.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            review_code, review_output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("propose-metadata-normalization complete", output)
        self.assertEqual(proposal["kind"], "metadata-normalization")
        self.assertEqual(len(proposal["operations"]), 1)
        operation = proposal["operations"][0]
        self.assertEqual(operation["op"], "normalize_metadata")
        self.assertEqual(operation["set"]["type"], "daily")
        self.assertEqual(operation["set"]["status"], "active")
        self.assertEqual(operation["set"]["domain"], "personal")
        self.assertEqual(operation["set"]["related"], ["alpha", "beta"])
        self.assertIn("created", operation["remove"])
        self.assertIn("summary", operation["remove"])
        self.assertIn("## Summary", operation["body"])
        self.assertNotIn("Privacy:", operation["body"])
        self.assertEqual(review_code, 0)
        self.assertIn("Validation: passed", review_output)

    def test_metadata_normalization_apply_removes_body_detritus(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "legacy.md"
            note.write_text(
                "---\n"
                "title: Legacy Title\n"
                "type: journal\n"
                "status: raw\n"
                "domains: [personal]\n"
                'summary: "Clean summary."\n'
                "---\n"
                "# Legacy\n\n"
                "Privacy: private\n"
                "Sensitive: false\n\n"
                "Body text.\n",
                encoding="utf-8",
            )

            self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-metadata-normalization",
                    "--all",
                ]
            )
            approve_code, approve_output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "review-proposals",
                    "--approve",
                    "metadata-normalization-001",
                    "--approval-note",
                    "Reviewed deterministic metadata cleanup.",
                    "--expected-operations",
                    "1",
                ]
            )
            apply_code, apply_output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "review-proposals",
                    "--apply-approved",
                    "--proposal-id",
                    "metadata-normalization-001",
                ]
            )
            text = note.read_text(encoding="utf-8")

        self.assertEqual(approve_code, 0, approve_output)
        self.assertEqual(apply_code, 0, apply_output)
        self.assertIn("type: daily", text)
        self.assertIn("status: active", text)
        self.assertIn("domain: personal", text)
        self.assertNotIn("title:", text)
        self.assertNotIn("summary:", text)
        self.assertNotIn("Privacy:", text)
        self.assertNotIn("Sensitive:", text)
        self.assertIn("## Summary", text)
        self.assertIn("Clean summary.", text)
        self.assertIn("Body text.", text)

    def test_metadata_normalization_excludes_system_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            system_note = root / "99 System" / "0.02 templates" / "template.md"
            system_note.parent.mkdir(parents=True)
            system_note.write_text(
                "---\ntitle: Template\n---\n# Template\n\nPrivacy: private\n",
                encoding="utf-8",
            )
            content_note = root / "note.md"
            content_note.write_text(
                "---\ntitle: Note\n---\n# Note\n\nPrivacy: private\n",
                encoding="utf-8",
            )

            exit_code, _output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-metadata-normalization",
                    "--all",
                ]
            )
            proposal_path = (
                root
                / "99 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "metadata-normalization-001.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            paths = [operation["path"] for operation in proposal["operations"]]

        self.assertEqual(exit_code, 0)
        self.assertEqual(paths, ["note.md"])


if __name__ == "__main__":
    unittest.main()
