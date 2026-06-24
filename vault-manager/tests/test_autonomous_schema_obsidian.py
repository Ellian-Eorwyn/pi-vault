import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from vault_agent.cli import main


class AutonomousSchemaObsidianTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_autonomous_run_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Loose").mkdir()
            (root / "Loose" / "note.md").write_text("# Note\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "autonomous-run",
                    "--dry-run",
                    "--max-notes",
                    "1",
                    "--create-lock",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent autonomous-run dry run", output)
        self.assertIn("No files were changed.", output)
        self.assertFalse((root / "99 System").exists())

    def test_autonomous_run_writes_versioned_report_with_rollback_hint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Loose").mkdir()
            note = root / "Loose" / "note.md"
            note.write_text("# Note\n\nBody.\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "autonomous-run",
                    "--create-lock",
                    "--apply-safe",
                    "--stage",
                    "frontmatter-shape",
                    "--max-notes",
                    "1",
                ]
            )
            reports = sorted(
                (root / "99 System" / "0.01 agent" / "reports").glob(
                    "autonomous-run-*.json"
                )
            )
            report = json.loads(reports[-1].read_text(encoding="utf-8"))
            note_text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent autonomous-run complete", output)
        self.assertTrue(report["version_run_id"])
        self.assertIn("version undo-run", report["rollback"]["undo_command"])
        self.assertIn("Loose/note.md", report["changed_files"])
        self.assertIn("type:", note_text)

    def test_autonomous_run_applies_safe_proposals_but_defers_schema_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposals = root / "99 System" / "0.01 agent" / "review" / "proposals"
            proposals.mkdir(parents=True)
            (proposals / "index-note.json").write_text(
                json.dumps(
                    {
                        "id": "index-note",
                        "title": "Note Index",
                        "kind": "index-note",
                        "status": "pending",
                        "operations": [
                            {
                                "op": "write_file",
                                "path": "Indexes/Note.md",
                                "if_exists": "overwrite",
                                "content": "# Note Index\n",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (proposals / "property-domain-legal.json").write_text(
                json.dumps(
                    {
                        "id": "property-domain-legal",
                        "title": "Add legal domain",
                        "kind": "schema-change",
                        "status": "pending",
                        "operations": [
                            {
                                "op": "write_file",
                                "path": "99 System/0.01 agent/schema.json",
                                "if_exists": "overwrite",
                                "content": "{}\n",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, _output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "autonomous-run",
                    "--create-lock",
                    "--apply-safe",
                    "--max-notes",
                    "1",
                ]
            )
            safe = json.loads((proposals / "index-note.json").read_text(encoding="utf-8"))
            schema = json.loads(
                (proposals / "property-domain-legal.json").read_text(encoding="utf-8")
            )
            index_exists = (root / "Indexes" / "Note.md").exists()

            self.assertEqual(exit_code, 0)
            self.assertEqual(safe["status"], "applied")
            self.assertEqual(schema["status"], "pending")
            self.assertTrue(index_exists)

    def test_schema_conversation_generates_pending_proposals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "schema-chat.md"
            transcript.write_text(
                "User: add domain legal - Legal, compliance, and contracts.\n"
                "User: create index for domain legal\n"
                "User: refresh meeting template\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "schema-conversation",
                    "--conversation-file",
                    str(transcript),
                    "--include-current-schema-summary",
                ]
            )
            proposal_dir = root / "99 System" / "0.01 agent" / "review" / "proposals"
            property_exists = (proposal_dir / "property-domain-legal.json").exists()
            index_exists = (proposal_dir / "index-legal-domain.json").exists()
            template_exists = (proposal_dir / "template-meeting.json").exists()
            summary_exists = (
                root / "99 System" / "0.01 agent" / "review" / "schema-conversation-summary.md"
            ).exists()

            self.assertEqual(exit_code, 0)
            self.assertIn("schema-conversation complete", output)
            self.assertTrue(property_exists)
            self.assertTrue(index_exists)
            self.assertTrue(template_exists)
            self.assertTrue(summary_exists)

    def test_obsidian_check_reports_base_yaml_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Dashboard.md"
            note.write_text(
                "---\nstatus: active\ntype: index\n---\n# Dashboard\n\n```base\nviews: [\n```\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "obsidian-check"]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("base block 1 YAML error", output)
        self.assertIn("core frontmatter properties are not in canonical", output)

    def test_obsidian_check_accepts_valid_embedded_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Dashboard.md"
            note.write_text(
                "---\ntype: index\nstatus: active\ndomain: meta\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Dashboard\n\n"
                "```base\n"
                "filters:\n"
                "  and:\n"
                "    - 'file.ext == \"md\"'\n"
                "views:\n"
                "  - type: table\n"
                "    name: Notes\n"
                "    order:\n"
                "      - file.name\n"
                "```\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "obsidian-check"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Errors: 0", output)

    def test_obsidian_check_accepts_rich_base_and_flags_bad_sort(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "Good.md"
            good.write_text(
                "---\ntype: index\nstatus: active\ndomain: meta\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Good\n\n"
                "```base\n"
                "filters:\n"
                "  and:\n"
                "    - 'file.ext == \"md\"'\n"
                "properties:\n"
                "  file.name:\n"
                "    displayName: Name\n"
                "views:\n"
                "  - type: cards\n"
                "    name: Cards\n"
                "    groupBy:\n"
                "      property: type\n"
                "      direction: ASC\n"
                "    sort:\n"
                "      - property: file.name\n"
                "        direction: ASC\n"
                "    order:\n"
                "      - file.name\n"
                "```\n",
                encoding="utf-8",
            )
            good_exit, good_output = self.run_cli(["--vault-root", directory, "obsidian-check"])

            good.unlink()
            bad = root / "Bad.md"
            bad.write_text(
                "---\ntype: index\nstatus: active\ndomain: meta\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Bad\n\n"
                "```base\n"
                "views:\n"
                "  - type: table\n"
                "    name: Notes\n"
                "    sort:\n"
                "      - direction: ASC\n"
                "    order:\n"
                "      - file.name\n"
                "```\n",
                encoding="utf-8",
            )
            bad_exit, bad_output = self.run_cli(["--vault-root", directory, "obsidian-check"])

        self.assertEqual(good_exit, 0)
        self.assertIn("Errors: 0", good_output)
        self.assertEqual(bad_exit, 1)
        self.assertIn("sort entries must map", bad_output)


if __name__ == "__main__":
    unittest.main()
