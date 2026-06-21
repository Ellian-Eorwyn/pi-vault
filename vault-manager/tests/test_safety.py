import tempfile
import unittest
from pathlib import Path

from vault_agent.safety import CreationItem, apply_creation_plan, plan_creation


class SafetyTests(unittest.TestCase):
    def test_plan_creation_marks_missing_directory_and_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = plan_creation(
                [
                    CreationItem("directory", root / "system"),
                    CreationItem("file", root / "system" / "config.yaml"),
                ],
                root / "backups",
            )

        self.assertEqual([item.action for item in plan], ["create_directory", "create_file"])

    def test_apply_creation_plan_creates_missing_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "system" / "config.yaml"
            plan = plan_creation(
                [
                    CreationItem("directory", root / "system"),
                    CreationItem("file", target, content="created\n"),
                ],
                root / "backups",
            )

            apply_creation_plan(plan)

            self.assertTrue((root / "system").is_dir())
            self.assertEqual(target.read_text(encoding="utf-8"), "created\n")

    def test_existing_file_is_preserved_with_backup_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "config.yaml"
            target.write_text("existing\n", encoding="utf-8")

            plan = plan_creation(
                [CreationItem("file", target, content="new\n")],
                root / "backups",
            )
            apply_creation_plan(plan)

            self.assertEqual(plan[0].action, "preserve_file")
            self.assertEqual(plan[0].backup_path, root / "backups" / "config.yaml.bak")
            self.assertEqual(target.read_text(encoding="utf-8"), "existing\n")

    def test_path_type_conflict_is_reported_and_not_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "system"
            target.write_text("not a directory\n", encoding="utf-8")

            plan = plan_creation(
                [CreationItem("directory", target)],
                root / "backups",
            )
            apply_creation_plan(plan)

            self.assertEqual(plan[0].action, "conflict")
            self.assertTrue(target.is_file())

    def test_parent_file_conflict_blocks_child_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "system"
            parent.write_text("not a directory\n", encoding="utf-8")

            plan = plan_creation(
                [CreationItem("file", parent / "config.yaml", content="new\n")],
                root / "backups",
            )
            apply_creation_plan(plan)

            self.assertEqual(plan[0].action, "conflict")
            self.assertEqual(parent.read_text(encoding="utf-8"), "not a directory\n")


if __name__ == "__main__":
    unittest.main()
