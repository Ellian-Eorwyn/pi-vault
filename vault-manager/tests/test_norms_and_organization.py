import contextlib
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from vault_agent.cli import main
from vault_agent.config import load_config
from vault_agent.norms import build_norms_lock
from vault_agent.organize_pass import run_organize_vault_pass
from vault_agent.processing_state import mark_stage, stage_complete


class RecordingPropertyProvider:
    def __init__(self):
        self.active = False
        self.calls = []

    def propose_stage(self, *, note_path, note_text, stage):
        if self.active:
            raise AssertionError("LLM calls must not overlap")
        self.active = True
        self.calls.append((note_path.name, stage))
        proposal = {
            "status": "active",
            "domain": "personal",
            "parent": "",
            "related": [],
            "cover": "",
            "source_kind": "",
            "capture_type": "manual",
            "confidence": 0.95,
            "warnings": [],
        }
        self.active = False
        return proposal


class NormsAndOrganizationTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def config_for(self, directory):
        return load_config(
            Namespace(
                vault_root=directory,
                config=None,
                dry_run=False,
                verbose=False,
            )
        )

    def test_norms_lock_hash_is_stable_and_changes_with_template(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            templates = root / "99 System" / "0.02 templates" / "note-types"
            templates.mkdir(parents=True)
            template = templates / "note.md"
            template.write_text("---\ntype: template\n---\n# Note\n", encoding="utf-8")
            config = self.config_for(directory)

            first = build_norms_lock(config)
            second = build_norms_lock(config)
            template.write_text("---\ntype: template\n---\n# Changed\n", encoding="utf-8")
            changed = build_norms_lock(config)

        self.assertEqual(first["lock_hash"], second["lock_hash"])
        self.assertNotEqual(first["lock_hash"], changed["lock_hash"])

    def test_processing_state_detects_content_and_lock_staleness(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "note.md"
            note.write_text("# Note\n", encoding="utf-8")

            mark_stage(root, note, stage="frontmatter-shape", status="complete", norms_lock_hash="a")
            self.assertTrue(
                stage_complete(root, note, "frontmatter-shape", norms_lock_hash="a")
            )
            self.assertFalse(
                stage_complete(root, note, "frontmatter-shape", norms_lock_hash="b")
            )
            note.write_text("# Note\n\nChanged.\n", encoding="utf-8")
            self.assertFalse(
                stage_complete(root, note, "frontmatter-shape", norms_lock_hash="a")
            )

    def test_norms_lock_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, output = self.run_cli(
                ["--vault-root", directory, "norms-lock", "--dry-run"]
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("norms-lock dry run", output)
            self.assertFalse(
                (Path(directory) / "99 System" / "0.01 agent" / "norms-lock.json").exists()
            )

    def test_organize_vault_pass_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Loose" / "note.md"
            note.parent.mkdir()
            note.write_text("# Note\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "organize-vault-pass",
                    "--dry-run",
                    "--create-lock",
                    "--max-notes",
                    "1",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("organize-vault-pass dry run", output)
            self.assertIn("Would process: 1", output)
            self.assertEqual(note.read_text(encoding="utf-8"), "# Note\n")
            self.assertFalse((root / "99 System").exists())

    def test_organize_vault_pass_writes_report_and_lock_aware_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Loose" / "note.md"
            note.parent.mkdir()
            note.write_text("# Note\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "organize-vault-pass",
                    "--create-lock",
                    "--max-notes",
                    "1",
                    "--stage",
                    "frontmatter-shape",
                ]
            )
            state = json.loads(
                (root / "99 System" / "0.01 agent" / "processing-state.json").read_text(
                    encoding="utf-8"
                )
            )
            lock = json.loads(
                (root / "99 System" / "0.01 agent" / "norms-lock.json").read_text(
                    encoding="utf-8"
                )
            )
            reports = list((root / "99 System" / "0.01 agent" / "reports").glob("organization-run-*.json"))

        self.assertEqual(exit_code, 0)
        self.assertIn("organize-vault-pass complete", output)
        self.assertEqual(
            state["notes"]["Loose/note.md"]["norms_lock_hash"],
            lock["lock_hash"],
        )
        self.assertEqual(len(reports), 1)

    def test_organize_vault_pass_serializes_llm_batch_by_queue_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            loose = root / "Loose"
            loose.mkdir()
            for name in ("a.md", "b.md"):
                (loose / name).write_text(
                    "---\ntype: note\n---\n# Note\n",
                    encoding="utf-8",
                )
            config = self.config_for(directory)
            provider = RecordingPropertyProvider()

            exit_code, output = run_organize_vault_pass(
                config,
                proposal_provider=provider,
                max_notes=2,
                stage="property-values",
                create_lock=True,
            )
            reports = sorted(
                (root / "99 System" / "0.01 agent" / "reports").glob(
                    "organization-run-*.json"
                )
            )
            report = json.loads(reports[-1].read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("LLM prompts: serialized one note stage at a time", output)
        self.assertEqual(provider.calls, [("a.md", "property-values"), ("b.md", "property-values")])
        self.assertEqual(report["processed_stages"], 2)
        self.assertTrue(report["llm_prompts_serialized"])
        self.assertEqual(
            [item["queue_position"] for item in report["processed"]],
            [1, 2],
        )
        self.assertEqual(
            [item["path"] for item in report["processed"]],
            ["Loose/a.md", "Loose/b.md"],
        )

    def test_organization_readiness_json_reports_preflight_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Loose" / "note.md"
            note.parent.mkdir()
            note.write_text("# Note\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "organization-readiness", "--json"]
            )
            report = json.loads(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["readiness"], "no")
        self.assertEqual(report["norms_lock"]["status"], "missing")
        self.assertEqual(report["candidate_stages"]["count"], 1)
        self.assertIn("cleanup_queue", report)
        self.assertIn("generated_state", report)

    def test_validate_json_reports_issue_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "legacy.md"
            note.write_text("---\nlegacy: true\n---\n# Legacy\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "validate", "--dry-run", "--json"]
            )
            report = json.loads(output)

        self.assertEqual(exit_code, 0)
        self.assertGreater(report["issues"], 0)
        self.assertIn("groups", report)
        self.assertTrue(any(group["count"] >= 1 for group in report["groups"]))

    def test_reconcile_dry_run_includes_lock_aware_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Loose" / "note.md"
            note.parent.mkdir()
            note.write_text("# Note\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "reconcile", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Preflight:", output)
        self.assertIn("Norms lock: missing", output)
        self.assertIn("Cleanup proposal opportunities:", output)

    def test_propose_cleanup_queue_writes_valid_bounded_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(2):
                note = root / f"legacy-{index}.md"
                note.write_text(
                    "---\ntype: journal\nstatus: raw\ndomains: [personal]\nlegacy: old\n---\n# Legacy\n",
                    encoding="utf-8",
                )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-cleanup-queue",
                    "--max-items",
                    "1",
                    "--remove-unknown",
                ]
            )
            proposal_path = (
                root
                / "99 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "cleanup-queue-vault.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            review_exit, review_output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Cleanup operations: 1", output)
        self.assertEqual(len(proposal["operations"]), 1)
        self.assertEqual(proposal["operations"][0]["set"]["type"], "daily")
        self.assertIn("legacy", proposal["operations"][0]["remove"])
        self.assertEqual(review_exit, 0)
        self.assertIn("Validation: passed", review_output)


if __name__ == "__main__":
    unittest.main()
