import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from vault_agent.cli import main
from vault_agent.config import load_config
from vault_agent.layout_routing import build_inbox_sort_proposal, route_note
from vault_agent.norms import current_lock_hash, run_norms_lock
from vault_agent.processing_state import mark_stage
from vault_agent.review import _merge_generated_section


class DashboardLayoutTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def config(self, root: Path):
        return load_config(argparse.Namespace(vault_root=root))

    def test_init_creates_dashboard_first_layout_and_bootstrap_map(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, output = self.run_cli(["--vault-root", directory, "init"])
            bootstrap = (root / ".pi-vault" / "config.yaml").read_text(encoding="utf-8")

            expected = [
                "00 Inbox",
                "01 Dashboards/Home.md",
                "02 People/02.01 Contacts/Contacts.md",
                "02 People/02.02 Authors/Authors.md",
                "03 Organizations/Organizations.md",
                "04 Work/Work.md",
                "05 Administrative/05.01 Health",
                "05 Administrative/05.02 Home",
                "05 Administrative/05.03 Finance",
                "05 Administrative/05.04 Travel",
                "05 Administrative/05.05 General",
                "06 Thoughts/Thoughts.md",
                "07 Sources/Sources.md",
                "99 System/0.01 agent",
            ]

            self.assertEqual(code, 0, output)
            for relative in expected:
                self.assertTrue((root / relative).exists(), relative)
            self.assertIn('system_dir: 99 System', bootstrap)
            self.assertIn('inbox_dir: 00 Inbox', bootstrap)
            self.assertIn('dashboards_dir: 01 Dashboards', bootstrap)
            self.assertIn('contacts: 02 People/02.01 Contacts', bootstrap)

    def test_route_precedence_and_person_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            note = root / "00 Inbox" / "Example.md"

            contact = route_note(
                config,
                note,
                {"type": "person", "domain": "work", "parent": "[[Contacts]]", "related": ["[[Authors]]"]},
            )
            author = route_note(
                config,
                note,
                {"type": "person", "domain": "academic", "parent": "[[Authors]]"},
            )
            source = route_note(config, note, {"type": "source", "domain": "work", "parent": "[[A]]"})
            work = route_note(config, note, {"type": "meeting", "domain": "work", "parent": "[[A]]"})
            health = route_note(config, note, {"type": "note", "domain": "health", "parent": ""})
            thought_project = route_note(
                config, note, {"type": "project", "domain": "philosophy", "parent": ""}
            )

            self.assertEqual(contact.destination_dir, Path("02 People/02.01 Contacts"))
            self.assertEqual(author.destination_dir, Path("02 People/02.02 Authors"))
            self.assertEqual(source.destination_dir, Path("07 Sources"))
            self.assertEqual(work.destination_dir, Path("04 Work/A"))
            self.assertEqual(health.destination_dir, Path("05 Administrative/05.01 Health"))
            self.assertEqual(thought_project.destination_dir, Path("06 Thoughts/philosophy/Example"))

    def test_safe_inbox_sort_requires_current_confident_model_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_cli(["--vault-root", directory, "init"])
            note = root / "00 Inbox" / "Contact.md"
            note.write_text(
                "---\ntype: person\nstatus: active\ndomain: personal\nparent: '[[Contacts]]'\nrelated: []\ncover:\nsource_kind:\ncapture_type: manual\n---\n# Contact\n",
                encoding="utf-8",
            )
            config = self.config(root)

            unsafe, _warnings = build_inbox_sort_proposal(config, max_notes=1, safe_only=True)
            self.assertEqual(unsafe["operations"], [])

            run_norms_lock(config, write=True, force=True)
            lock_hash = current_lock_hash(root)
            mark_stage(
                root,
                note,
                stage="classify-type",
                status="complete",
                norms_lock_hash=lock_hash,
                confidence=0.95,
            )
            mark_stage(
                root,
                note,
                stage="property-values",
                status="complete",
                norms_lock_hash=lock_hash,
                confidence=0.95,
            )
            safe, warnings = build_inbox_sort_proposal(config, max_notes=1, safe_only=True)

            self.assertEqual(warnings, [])
            self.assertTrue(safe["automation_safe"])
            self.assertEqual(safe["operations"][-1]["op"], "move_note")
            self.assertEqual(
                safe["operations"][-1]["destination"],
                "02 People/02.01 Contacts/Contact.md",
            )

    def test_layout_migration_is_proposal_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".pi-vault").mkdir()
            (root / ".pi-vault" / "config.yaml").write_text(
                "version: 1\nsystem_dir: Legacy System\ninbox_dir: Legacy Inbox\n",
                encoding="utf-8",
            )
            code, output = self.run_cli(
                ["--vault-root", directory, "propose-vault-layout", "--dry-run"]
            )

            self.assertEqual(code, 0, output)
            self.assertIn("No files were changed", output)
            self.assertFalse((root / "01 Dashboards").exists())
            self.assertFalse((root / "Legacy System" / "0.01 agent" / "review").exists())

    def test_layout_migration_blocks_pending_folder_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposals = root / "99 System" / "0.01 agent" / "review" / "proposals"
            proposals.mkdir(parents=True)
            (proposals / "vault-folder-structure.json").write_text(
                json.dumps(
                    {
                        "id": "vault-folder-structure",
                        "kind": "schema-change",
                        "status": "pending",
                        "operations": [
                            {
                                "op": "write_file",
                                "path": ".pi-vault/config.yaml",
                                "if_exists": "overwrite",
                                "content": "version: 1\nsystem_dir: 99 System\ninbox_dir: 00 Inbox\n",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            code, output = self.run_cli(
                ["--vault-root", directory, "propose-vault-layout", "--dry-run"]
            )

        self.assertEqual(code, 1)
        self.assertIn("pending folder proposal", output)

    def test_approved_layout_migration_moves_only_routable_existing_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".pi-vault").mkdir()
            (root / ".pi-vault" / "config.yaml").write_text(
                "version: 1\nsystem_dir: Legacy System\ninbox_dir: Legacy Inbox\n",
                encoding="utf-8",
            )
            (root / "Legacy").mkdir()
            (root / "Legacy" / "Acme.md").write_text(
                "---\ntype: organization\nstatus: active\ndomain: work\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Acme\n",
                encoding="utf-8",
            )
            code, output = self.run_cli(["--vault-root", directory, "propose-vault-layout"])
            proposal_path = (
                root
                / "Legacy System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "vault-layout.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))

            self.assertEqual(code, 0, output)
            self.assertEqual(proposal["status"], "pending")
            self.assertFalse(proposal["automation_safe"])
            create_directories = [
                operation.get("path")
                for operation in proposal["operations"]
                if operation.get("op") == "create_directory"
            ]
            self.assertIn("03 Organizations", create_directories)
            self.assertIn("07 Sources", create_directories)
            self.assertIn(
                "03 Organizations/Acme.md",
                [operation.get("destination") for operation in proposal["operations"]],
            )

            proposal["status"] = "approved"
            proposal_path.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
            apply_code, apply_output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "review-proposals",
                    "--apply-approved",
                    "--mass-edit",
                ]
            )

            self.assertEqual(apply_code, 0, apply_output)
            self.assertTrue((root / "03 Organizations" / "Acme.md").exists())
            self.assertFalse((root / "Legacy" / "Acme.md").exists())

    def test_generated_section_merge_preserves_curated_markdown(self):
        existing = "# Home\n\nMy curated text.\n\n<!-- pi-vault:generated:start -->old<!-- pi-vault:generated:end -->\n"
        generated = "# Home\n\n<!-- pi-vault:generated:start -->new<!-- pi-vault:generated:end -->\n"

        merged = _merge_generated_section(existing, generated)

        self.assertIn("My curated text.", merged)
        self.assertIn("new", merged)
        self.assertNotIn("old", merged)


if __name__ == "__main__":
    unittest.main()
