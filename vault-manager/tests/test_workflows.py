import json
import tempfile
import unittest
from pathlib import Path

from vault_agent.cli import main


class WorkflowTests(unittest.TestCase):
    def run_cli(self, args):
        import contextlib
        import io

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_scan_writes_manifest_and_excludes_agent_trash_and_obsidian(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            (root / "00 Inbox" / "note.md").write_text("# Hello\n", encoding="utf-8")
            (root / ".obsidian").mkdir()
            (root / ".obsidian" / "ignored.md").write_text("# Ignore\n", encoding="utf-8")
            (root / "99 System" / "0.99 trash").mkdir(parents=True)
            (root / "99 System" / "0.99 trash" / "old.md").write_text("# Old\n", encoding="utf-8")

            exit_code, output = self.run_cli(["--vault-root", directory, "scan"])
            manifest = json.loads(
                (root / "99 System" / "0.01 agent" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Discovered notes: 1", output)
        self.assertEqual([note["path"] for note in manifest["notes"]], ["00 Inbox/note.md"])

    def test_scan_serializes_yaml_date_frontmatter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "dated.md"
            note.write_text(
                "---\ncreated: 2026-01-01\n---\n# Dated\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(["--vault-root", directory, "scan"])
            manifest = json.loads(
                (root / "99 System" / "0.01 agent" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Discovered notes: 1", output)
        self.assertEqual(manifest["notes"][0]["frontmatter"]["created"], "2026-01-01")

    def test_validate_reports_malformed_frontmatter_and_unknown_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            (root / "00 Inbox" / "bad.md").write_text(
                "---\ntype: mystery\nstatus: strange\nsource_kind: zine\ncapture_type: email\nunknown: yes\n---\n# Bad\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(["--vault-root", directory, "validate"])
            review = (
                root
                / "99 System"
                / "0.01 agent"
                / "review"
                / "needs-review.md"
            ).read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Issues:", output)
        self.assertIn("unknown type `mystery`", review)
        self.assertIn("invalid status `strange`", review)
        self.assertIn("invalid source_kind `zine`", review)
        self.assertIn("invalid capture_type `email`", review)
        self.assertIn("unknown property `unknown`", review)

    def test_validate_dry_run_groups_legacy_alias_issues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            for index in range(2):
                (root / "00 Inbox" / f"legacy-{index}.md").write_text(
                    "---\ntype: journal\nstatus: raw\ndomains: [personal]\n---\n# Legacy\n",
                    encoding="utf-8",
                )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "validate", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Top issue groups:", output)
        self.assertIn("2x **info** legacy type `journal` can map to `daily`", output)
        self.assertIn("2x **info** legacy property `domains` can map to `domain`", output)

    def test_reconcile_cleans_multiple_notes_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Loose").mkdir()
            (root / "Loose" / "note.md").write_text(
                "---\nlegacy: yes\n---\n# Term\n\nDefinition: a term.\n",
                encoding="utf-8",
            )
            (root / "Loose" / "meeting.md").write_text(
                "---\ntype: meeting\nold: value\n---\n# Sync\n\nAttendees: Ellie\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(["--vault-root", directory, "reconcile"])
            note_text = (root / "Loose" / "note.md").read_text(encoding="utf-8")
            meeting = (root / "Loose" / "meeting.md").read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Applied: 2", output)
        self.assertIn("legacy: true", note_text)
        self.assertIn("type: note", note_text)
        self.assertIn("old: value", meeting)
        self.assertIn("## Summary", meeting)

    def test_process_next_updates_only_inbox_frontmatter_and_backs_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            note = root / "00 Inbox" / "new.md"
            note.write_text("# New\n\nBody stays.\n", encoding="utf-8")

            exit_code, output = self.run_cli(["--vault-root", directory, "process-next"])
            text = note.read_text(encoding="utf-8")
            backups = list((root / "99 System" / "0.01 agent" / "backups").glob("new.md.*.bak"))
            state = json.loads(
                (root / "99 System" / "0.01 agent" / "processing-state.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Processed: 00 Inbox/new.md", output)
        self.assertIn("Stage: frontmatter-shape", output)
        self.assertIn("type:", text)
        self.assertIn("domain:", text)
        self.assertIn("parent:", text)
        self.assertIn("related: []", text)
        self.assertIn("cover:", text)
        self.assertNotIn("processing_status:", text)
        self.assertIn("Body stays.", text)
        self.assertEqual(len(backups), 1)
        self.assertEqual(
            state["notes"]["00 Inbox/new.md"]["stages"]["frontmatter-shape"]["status"],
            "complete",
        )

    def test_process_vault_updates_non_inbox_note_and_skips_system_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Loose").mkdir()
            note = root / "Loose" / "new.md"
            note.write_text("# New\n\nBody stays.\n", encoding="utf-8")
            system_note = root / "99 System" / "0.02 templates" / "note-types" / "note.md"
            system_note.parent.mkdir(parents=True)
            system_note.write_text("# Template\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-vault",
                    "--stage",
                    "frontmatter-shape",
                    "--max-notes",
                    "1",
                ]
            )
            text = note.read_text(encoding="utf-8")
            system_text = system_note.read_text(encoding="utf-8")
            state = json.loads(
                (root / "99 System" / "0.01 agent" / "processing-state.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Processed: 1", output)
        self.assertIn("type:", text)
        self.assertIn("Body stays.", text)
        self.assertEqual(system_text, "# Template\n")
        self.assertEqual(
            state["notes"]["Loose/new.md"]["stages"]["frontmatter-shape"]["status"],
            "complete",
        )

    def test_process_vault_template_body_applies_type_headings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "typed.md"
            note.write_text(
                "---\ntype: note\nstatus: active\ndomain: meta\nparent:\nrelated: []\ncover:\n---\n# Typed\n\nBody.\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-vault",
                    "--stage",
                    "template-body",
                    "--max-notes",
                    "1",
                ]
            )
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Processed: 1", output)
        self.assertIn("## Summary", text)
        self.assertIn("## Main Points", text)
        self.assertIn("## Context", text)
        self.assertIn("## Links", text)
        self.assertIn("## Notes", text)

    def test_process_vault_routes_unknown_existing_type_to_classification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Notes").mkdir()
            note = root / "Notes" / "legacy.md"
            note.write_text(
                "---\ntype: concept\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Legacy\n\nDefinition: old vocabulary.\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "process-vault", "--dry-run"]
            )
            forced_exit, forced_output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-vault",
                    "--stage",
                    "property-values",
                    "--max-notes",
                    "1",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("legacy.md (classify-type)", output)
        self.assertEqual(forced_exit, 0)
        self.assertIn("No vault notes need processing", forced_output)

    def test_blank_core_values_count_as_processed_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            note = root / "00 Inbox" / "done.md"
            note.write_text(
                "---\ntype: note\nstatus: active\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Done\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(["--vault-root", directory, "process-next"])

        self.assertEqual(exit_code, 1)
        self.assertIn("requires an LLM proposal provider", output)

    def test_process_next_dry_run_reports_next_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            (root / "00 Inbox" / "new.md").write_text("# New\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "process-next", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Stage: frontmatter-shape", output)

    def test_rebuild_retrieval_writes_property_index_and_summary_brief(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            (root / "00 Inbox" / "note.md").write_text(
                "---\ntype: note\ndomain: meta\n---\n# Hello\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(["--vault-root", directory, "rebuild-retrieval"])
            property_index = (
                root
                / "99 System"
                / "0.01 agent"
                / "retrieval"
                / "03 property-index.md"
            ).read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Updated retrieval files", output)
        self.assertIn("`note`: 1", property_index)

    def test_hermes_run_dry_run_discovers_vault_directories_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            hermes = Path(directory)
            vault = hermes / "vault-a"
            vault.mkdir()
            (vault / "00 Inbox").mkdir()
            (vault / "00 Inbox" / "note.md").write_text("# Hello\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                ["hermes-run", "--hermes-root", directory, "--dry-run"]
            )

            self.assertFalse((vault / "99 System").exists())

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-a", output)
        self.assertIn("autonomous-run: ok", output)

    def test_hermes_run_processes_inbox_and_vault_notes_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            hermes = Path(directory)
            vault = hermes / "vault-a"
            vault.mkdir()
            (vault / "00 Inbox").mkdir()
            (vault / "00 Inbox" / "capture.md").write_text("# Capture\n", encoding="utf-8")
            loose = vault / "Loose"
            loose.mkdir()
            (loose / "note.md").write_text("# Loose\n\nBody stays.\n", encoding="utf-8")
            system_note = vault / "99 System" / "existing.md"
            system_note.parent.mkdir()
            system_note.write_text("# System\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                ["hermes-run", "--hermes-root", directory, "--max-notes", "2"]
            )
            inbox_text = (vault / "00 Inbox" / "capture.md").read_text(encoding="utf-8")
            loose_text = (loose / "note.md").read_text(encoding="utf-8")
            system_text = system_note.read_text(encoding="utf-8")
            state = json.loads(
                (vault / "99 System" / "0.01 agent" / "processing-state.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("autonomous-run: ok", output)
        self.assertIn("Report json:", output)
        self.assertIn("Undo:", output)
        self.assertIn("type:", inbox_text)
        self.assertIn("type:", loose_text)
        self.assertEqual(system_text, "# System\n")
        self.assertEqual(
            state["notes"]["00 Inbox/capture.md"]["stages"]["frontmatter-shape"]["status"],
            "complete",
        )
        self.assertEqual(
            state["notes"]["Loose/note.md"]["stages"]["frontmatter-shape"]["status"],
            "complete",
        )

    def test_hermes_run_without_llm_skips_model_required_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            hermes = Path(directory)
            vault = hermes / "vault-a"
            vault.mkdir()
            note = vault / "typed.md"
            note.write_text(
                "---\n"
                "type: note\n"
                "status:\n"
                "domain:\n"
                "parent:\n"
                "related: []\n"
                "cover:\n"
                "source_kind:\n"
                "capture_type:\n"
                "---\n"
                "# Typed\n\nBody.\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["hermes-run", "--hermes-root", directory, "--max-notes", "2"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("autonomous-run: ok", output)
        self.assertNotIn("requires an LLM proposal provider", output)


if __name__ == "__main__":
    unittest.main()
