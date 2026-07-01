import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from vault_agent.cli import main
from vault_agent.config import load_config
from vault_agent.norms import run_norms_lock
from vault_agent.status import build_status


class PiVaultBootstrapTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def load_test_config(self, root: Path):
        return load_config(argparse.Namespace(vault_root=root))

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
            default_system_exists = (root / "99 System").exists()
            default_inbox_exists = (root / "00 Inbox").exists()
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
        self.assertIn("01 Dashboards/Home.md", manifest_paths)
        self.assertFalse(any(path.startswith("System/0.01 agent/") for path in manifest_paths))
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

    def test_status_reports_schema_state_and_inbox_changes_without_scanning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_cli(["--vault-root", directory, "init"])
            inbox = root / "00 Inbox"
            (inbox / "changed.md").write_text("# Before\n", encoding="utf-8")
            self.run_cli(["--vault-root", directory, "scan"])
            state_path = root / "99 System" / "0.01 agent" / "state.json"
            manifest_path = root / "99 System" / "0.01 agent" / "manifest.json"
            state_before = state_path.read_text(encoding="utf-8")
            manifest_before = manifest_path.read_text(encoding="utf-8")
            previous_scan = json.loads(state_before)["last_scan"]
            (inbox / "changed.md").write_text("# After\n", encoding="utf-8")
            (inbox / "new.md").write_text("# New\n", encoding="utf-8")

            provisional = build_status(self.load_test_config(root))
            state_after = state_path.read_text(encoding="utf-8")
            manifest_after = manifest_path.read_text(encoding="utf-8")
            config = self.load_test_config(root)
            run_norms_lock(config, write=True, force=True)
            locked = build_status(config)
            schema_path = root / "99 System" / "0.01 agent" / "schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["test_drift"] = True
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            drifted = build_status(config)

        self.assertEqual(provisional["schema_state"], "provisional")
        self.assertEqual(state_after, state_before)
        self.assertEqual(manifest_after, manifest_before)
        self.assertEqual(provisional["previous_scan"], previous_scan)
        self.assertEqual(provisional["inbox_changes"]["new"], ["00 Inbox/new.md"])
        self.assertEqual(
            provisional["inbox_changes"]["changed"], ["00 Inbox/changed.md"]
        )
        self.assertEqual(locked["schema_state"], "locked")
        self.assertEqual(drifted["schema_state"], "drifted")

    def test_status_tolerates_corrupt_previous_state_and_lists_pending_proposals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_cli(["--vault-root", directory, "init"])
            agent_dir = root / "99 System" / "0.01 agent"
            (agent_dir / "manifest.json").write_text("not json", encoding="utf-8")
            (agent_dir / "state.json").write_text("not json", encoding="utf-8")
            proposal = agent_dir / "review" / "proposals" / "pending.json"
            proposal.write_text(
                json.dumps({"id": "pending", "status": "pending"}), encoding="utf-8"
            )

            status = build_status(self.load_test_config(root))

        self.assertEqual(status["previous_scan"], "")
        self.assertEqual(
            status["pending_proposals"],
            {"count": 1, "files": ["pending.json"], "ids": ["pending"]},
        )


class MoveProposalTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def write_proposal(self, root: Path, data: dict):
        path = root / "99 System" / "0.01 agent" / "review" / "proposals" / "move.json"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def test_move_note_creates_destination_and_rewrites_inbound_wikilinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_cli(["--vault-root", directory, "init"])
            (root / "00 Inbox" / "Old.md").write_text("# Old\n", encoding="utf-8")
            (root / "Reference.md").write_text(
                "[[Old]] [[00 Inbox/Old#Section|Alias]] ![[Old]]\n",
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
                            "path": "00 Inbox/Old.md",
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
            source_exists = (root / "00 Inbox" / "Old.md").exists()
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
            (root / "00 Inbox" / "One.md").write_text("# One\n", encoding="utf-8")
            (root / "00 Inbox" / "Two.md").write_text("# Two\n", encoding="utf-8")
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
                            "path": "00 Inbox/One.md",
                            "destination": "One.md",
                        },
                        {
                            "op": "move_note",
                            "path": "00 Inbox/Two.md",
                            "destination": "Existing.md",
                        },
                    ],
                },
            )
            code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            one_exists = (root / "00 Inbox" / "One.md").exists()
            two_exists = (root / "00 Inbox" / "Two.md").exists()
            moved_exists = (root / "One.md").exists()

        self.assertEqual(code, 1)
        self.assertIn("destination already exists", output)
        self.assertTrue(one_exists)
        self.assertTrue(two_exists)
        self.assertFalse(moved_exists)


if __name__ == "__main__":
    unittest.main()
