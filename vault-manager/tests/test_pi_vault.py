import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from vault_agent.cli import main


class PiVaultBootstrapTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_custom_system_and_inbox_paths_drive_all_generated_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "init",
                    "--system-dir",
                    "System",
                    "--inbox-dir",
                    "Capture",
                ]
            )
            bootstrap = yaml.safe_load(
                (root / ".pi-vault" / "config.yaml").read_text(encoding="utf-8")
            )
            (root / "Capture" / "note.md").write_text("# Captured\n", encoding="utf-8")
            scan_code, _scan_output = self.run_cli(["--vault-root", directory, "scan"])
            status_code, status_output = self.run_cli(
                ["--vault-root", directory, "status", "--json"]
            )
            status = json.loads(status_output)
            manifest = json.loads(
                (root / "System" / "0.01 agent" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            default_system_exists = (root / "00 System").exists()
            default_inbox_exists = (root / "01 Inbox").exists()
            purpose_exists = (root / "System" / "0.01 agent" / "vault-purpose.md").is_file()
            conventions_exists = (
                root / "System" / "0.01 agent" / "vault-conventions.md"
            ).is_file()

        self.assertEqual(code, 0, output)
        self.assertEqual(scan_code, 0)
        self.assertEqual(status_code, 0)
        self.assertEqual(bootstrap["system_dir"], "System")
        self.assertEqual(bootstrap["inbox_dir"], "Capture")
        self.assertEqual(status["system_dir"], "System")
        self.assertEqual(status["inbox_dir"], "Capture")
        manifest_paths = [item["path"] for item in manifest["notes"]]
        self.assertIn("Capture/note.md", manifest_paths)
        self.assertTrue(
            all(
                path == "Capture/note.md" or path.startswith("System/0.02 templates/")
                for path in manifest_paths
            )
        )
        self.assertFalse(default_system_exists)
        self.assertFalse(default_inbox_exists)
        self.assertTrue(purpose_exists)
        self.assertTrue(conventions_exists)

    def test_invalid_nested_bootstrap_paths_are_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "init",
                    "--system-dir",
                    "Workspace",
                    "--inbox-dir",
                    "Workspace/Inbox",
                ]
            )
            paths = list(Path(directory).iterdir())

        self.assertEqual(code, 1)
        self.assertIn("distinct, non-nested folders", output)
        self.assertEqual(paths, [])


class MoveProposalTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def write_proposal(self, root: Path, data: dict):
        path = root / "00 System" / "0.01 agent" / "review" / "proposals" / "move.json"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def test_move_note_creates_destination_and_rewrites_inbound_wikilinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_cli(["--vault-root", directory, "init"])
            (root / "01 Inbox" / "Old.md").write_text("# Old\n", encoding="utf-8")
            (root / "Reference.md").write_text(
                "[[Old]] [[01 Inbox/Old#Section|Alias]] ![[Old]]\n",
                encoding="utf-8",
            )
            self.write_proposal(
                root,
                {
                    "id": "move",
                    "title": "Move captured note",
                    "kind": "folder-organization",
                    "status": "approved",
                    "operations": [
                        {"op": "create_directory", "path": "Notes"},
                        {
                            "op": "move_note",
                            "path": "01 Inbox/Old.md",
                            "destination": "Notes/New.md",
                            "update_links": True,
                        },
                    ],
                },
            )
            code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            reference = (root / "Reference.md").read_text(encoding="utf-8")
            source_exists = (root / "01 Inbox" / "Old.md").exists()
            destination_exists = (root / "Notes" / "New.md").exists()

        self.assertEqual(code, 0, output)
        self.assertFalse(source_exists)
        self.assertTrue(destination_exists)
        self.assertIn("[[New]]", reference)
        self.assertIn("[[Notes/New#Section|Alias]]", reference)
        self.assertIn("![[New]]", reference)

    def test_move_preflight_prevents_partial_application_on_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_cli(["--vault-root", directory, "init"])
            (root / "01 Inbox" / "One.md").write_text("# One\n", encoding="utf-8")
            (root / "01 Inbox" / "Two.md").write_text("# Two\n", encoding="utf-8")
            (root / "Existing.md").write_text("# Existing\n", encoding="utf-8")
            self.write_proposal(
                root,
                {
                    "id": "move",
                    "title": "Conflicting moves",
                    "kind": "folder-organization",
                    "status": "approved",
                    "operations": [
                        {
                            "op": "move_note",
                            "path": "01 Inbox/One.md",
                            "destination": "One.md",
                        },
                        {
                            "op": "move_note",
                            "path": "01 Inbox/Two.md",
                            "destination": "Existing.md",
                        },
                    ],
                },
            )
            code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            one_exists = (root / "01 Inbox" / "One.md").exists()
            two_exists = (root / "01 Inbox" / "Two.md").exists()
            moved_exists = (root / "One.md").exists()

        self.assertEqual(code, 1)
        self.assertIn("destination already exists", output)
        self.assertTrue(one_exists)
        self.assertTrue(two_exists)
        self.assertFalse(moved_exists)


if __name__ == "__main__":
    unittest.main()
