import contextlib
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from vault_agent.cli import main
from vault_agent.config import load_config
from vault_agent.organize_pass import run_organize_vault_pass


class WarningTypeProvider:
    def propose_stage(self, *, note_path, note_text, stage):
        return {
            "note_type": "meeting",
            "confidence": 0.91,
            "warnings": ["title is ambiguous"],
        }


class LowConfidenceTypeProvider:
    def propose_stage(self, *, note_path, note_text, stage):
        return {
            "note_type": "note",
            "confidence": 0.65,
            "warnings": ["unclear primary subject"],
        }


class ModelBlockTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def config_for(self, directory, *, dry_run=False):
        return load_config(
            Namespace(
                vault_root=directory,
                config=None,
                dry_run=dry_run,
                verbose=False,
            )
        )

    def test_warning_stage_writes_model_block_artifacts_without_mutating_note(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Loose" / "ambiguous.md"
            note.parent.mkdir()
            original = "# Ambiguous meeting notes\n\nDiscussed dates.\n"
            note.write_text(original, encoding="utf-8")
            config = self.config_for(directory)

            exit_code, output = run_organize_vault_pass(
                config,
                proposal_provider=WarningTypeProvider(),
                max_notes=1,
                stage="classify-type",
                create_lock=True,
            )
            blocks_path = root / "99 System" / "0.01 agent" / "review" / "model-blocked-proposals.json"
            blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
            reports = sorted(
                (root / "99 System" / "0.01 agent" / "reports").glob(
                    "organization-run-*.json"
                )
            )
            report = json.loads(reports[-1].read_text(encoding="utf-8"))

            self.assertEqual(exit_code, 1)
            self.assertIn("Blocked model proposals: 1", output)
            self.assertEqual(note.read_text(encoding="utf-8"), original)
            self.assertEqual(blocks["blocked"][0]["note_path"], "Loose/ambiguous.md")
            self.assertEqual(blocks["blocked"][0]["proposed_values"], {"type": "meeting"})
            self.assertEqual(report["model_blocks"]["count"], 1)
            self.assertIn(
                "proposal requires review because confidence is near threshold or warnings were returned",
                report["model_blocks"]["top_reasons"],
            )

    def test_review_model_blocks_dry_run_and_conversion_to_pending_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Loose" / "ambiguous.md"
            note.parent.mkdir()
            original = "# Ambiguous meeting notes\n\nDiscussed dates.\n"
            note.write_text(original, encoding="utf-8")
            config = self.config_for(directory)
            run_organize_vault_pass(
                config,
                proposal_provider=WarningTypeProvider(),
                max_notes=1,
                stage="classify-type",
                create_lock=True,
            )

            dry_exit, dry_output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "review-model-blocks",
                    "--dry-run",
                    "--note",
                    "Loose/ambiguous.md",
                    "--stage",
                    "classify-type",
                    "--approve-safe",
                ]
            )
            proposal_path = (
                root
                / "99 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "model-block-loose-ambiguous-md-classify-type.json"
            )
            self.assertFalse(proposal_path.exists())

            convert_exit, convert_output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "review-model-blocks",
                    "--note",
                    "Loose/ambiguous.md",
                    "--stage",
                    "classify-type",
                    "--approve-safe",
                ]
            )
            review_exit, review_output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))

            self.assertEqual(dry_exit, 0)
            self.assertIn("No files were changed.", dry_output)
            self.assertEqual(convert_exit, 0)
            self.assertIn("Created review proposals: 1", convert_output)
            self.assertEqual(proposal["status"], "pending")
            self.assertEqual(proposal["operations"][0]["op"], "update_frontmatter")
            self.assertEqual(proposal["operations"][0]["set"], {"type": "meeting"})
            self.assertEqual(note.read_text(encoding="utf-8"), original)
            self.assertEqual(review_exit, 0)
            self.assertIn("Validation: passed", review_output)

    def test_approve_safe_skips_below_threshold_model_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Loose" / "unclear.md"
            note.parent.mkdir()
            original = "# Unclear capture\n\nMixed notes and pasted email.\n"
            note.write_text(original, encoding="utf-8")
            config = self.config_for(directory)
            run_organize_vault_pass(
                config,
                proposal_provider=LowConfidenceTypeProvider(),
                max_notes=1,
                stage="classify-type",
                create_lock=True,
            )

            convert_exit, convert_output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "review-model-blocks",
                    "--approve-safe",
                ]
            )
            proposal_path = (
                root
                / "99 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "model-block-loose-unclear-md-classify-type.json"
            )
            blocks_path = root / "99 System" / "0.01 agent" / "review" / "model-blocked-proposals.json"
            blocks = json.loads(blocks_path.read_text(encoding="utf-8"))

            self.assertEqual(convert_exit, 0)
            self.assertIn("Created review proposals: 0", convert_output)
            self.assertIn("Skipped unsafe proposals: 1", convert_output)
            self.assertIn("Skipped: model-block-loose-unclear-md-classify-type", convert_output)
            self.assertFalse(proposal_path.exists())
            self.assertEqual(blocks["blocked"][0]["status"], "pending")
            self.assertEqual(note.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
