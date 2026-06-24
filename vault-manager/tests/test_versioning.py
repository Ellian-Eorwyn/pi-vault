import contextlib
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from vault_agent.cli import main
from vault_agent.config import load_config
from vault_agent.execution import execute_versioned
from vault_agent.safety import atomic_write_text
from vault_agent.versioning import (
    CHANGE_SET_LOG,
    changed_files,
    ensure_initialized,
    recent_commits,
    status,
)


class VersioningTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def config_for(self, directory, config_path=None, dry_run=False):
        return load_config(
            Namespace(
                vault_root=directory,
                config=str(config_path) if config_path else None,
                dry_run=dry_run,
                verbose=False,
            )
        )

    def read_change_sets(self, root):
        path = Path(root) / CHANGE_SET_LOG
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_version_init_preserves_user_gitignore_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".gitignore").write_text("Custom.md\n", encoding="utf-8")

            exit_code, output = self.run_cli(["--vault-root", directory, "version", "init"])
            gitignore = (root / ".gitignore").read_text(encoding="utf-8")
            info = status(root)

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent version init complete", output)
        self.assertTrue(info.initialized)
        self.assertIn("Custom.md", gitignore)
        self.assertIn("BEGIN vault-agent managed ignores", gitignore)
        self.assertIn("99 System/0.01 agent/versioning/run.lock", gitignore)

    def test_separate_git_dir_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.yaml"
            separate = root / ".external-git"
            config.write_text(
                "versioning:\n"
                "  enabled: true\n"
                "  auto_init: true\n"
                f"  separate_git_dir: {separate}\n",
                encoding="utf-8",
            )

            exit_code, _output = self.run_cli(
                ["--vault-root", directory, "--config", str(config), "version", "init"]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(separate.is_dir())
            self.assertTrue((root / ".git").is_file())

    def test_nested_vault_does_not_use_parent_git_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            self.run_cli(["--vault-root", directory, "version", "init"])
            vault = parent / "nested-vault"
            vault.mkdir()
            (vault / "note.md").write_text("# Nested\n", encoding="utf-8")

            exit_code, output = self.run_cli(["--vault-root", str(vault), "version", "init"])
            parent_info = status(parent)
            vault_info = status(vault)
            nested_git_exists = (vault / ".git").exists()

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent version init complete", output)
        self.assertTrue(parent_info.initialized)
        self.assertTrue(vault_info.initialized)
        self.assertTrue(nested_git_exists)

    def test_execute_versioned_creates_change_set_and_clean_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config_for(directory)

            def write_file():
                atomic_write_text(root / "note.md", "# Note\n")
                return 0

            exit_code = execute_versioned(
                config,
                task_name="mock-write",
                command_args=["vault-agent", "mock-write"],
                operation=write_file,
            )
            records = self.read_change_sets(root)
            info = status(root)
            commits = recent_commits(root, limit=5)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["task_name"], "mock-write")
        self.assertIn("note.md", records[0]["changed_files"])
        self.assertFalse(info.dirty)
        self.assertTrue(any("vault-agent: post mock-write" in item["subject"] for item in commits))
        self.assertTrue(any("vault-agent: metadata mock-write" in item["subject"] for item in commits))

    def test_no_post_snapshot_when_command_makes_no_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config_for(directory)

            exit_code = execute_versioned(
                config,
                task_name="noop",
                command_args=["vault-agent", "noop"],
                operation=lambda: 0,
            )
            records = self.read_change_sets(root)

        self.assertEqual(exit_code, 0)
        self.assertEqual(records[0]["changed_files"], [])
        self.assertEqual(records[0]["status"], "success")

    def test_failed_task_preserves_pre_snapshot_and_logs_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config_for(directory)

            def fail_after_write():
                atomic_write_text(root / "partial.md", "# Partial\n")
                return 1

            exit_code = execute_versioned(
                config,
                task_name="failing-task",
                command_args=["vault-agent", "failing-task"],
                operation=fail_after_write,
            )
            records = self.read_change_sets(root)

        self.assertEqual(exit_code, 1)
        self.assertEqual(records[0]["status"], "failed")
        self.assertTrue(records[0]["pre_commit"])
        self.assertIn("partial.md", records[0]["changed_files"])

    def test_dirty_before_write_refuse_policy_blocks_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text(
                "versioning:\n"
                "  dirty_before_write_policy: refuse\n",
                encoding="utf-8",
            )
            init_exit, _ = self.run_cli(
                ["--vault-root", directory, "--config", str(config_path), "version", "init"]
            )
            (root / "uncommitted.md").write_text("# User change\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "--config", str(config_path), "scan"]
            )

        self.assertEqual(init_exit, 0)
        self.assertEqual(exit_code, 1)
        self.assertIn("dirty_before_write_policy is refuse", output)

    def test_mass_edit_threshold_blocks_before_processing_and_flag_allows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.yaml"
            config_path.write_text(
                "versioning:\n"
                "  mass_edit_threshold_files: 1\n",
                encoding="utf-8",
            )
            (root / "Loose").mkdir()
            (root / "Loose" / "a.md").write_text("# A\n", encoding="utf-8")
            (root / "Loose" / "b.md").write_text("# B\n", encoding="utf-8")

            blocked_exit, blocked_output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "--config",
                    str(config_path),
                    "process-vault",
                    "--stage",
                    "frontmatter-shape",
                    "--max-notes",
                    "2",
                ]
            )
            allowed_exit, allowed_output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "--config",
                    str(config_path),
                    "process-vault",
                    "--stage",
                    "frontmatter-shape",
                    "--max-notes",
                    "2",
                    "--mass-edit",
                ]
            )

        self.assertEqual(blocked_exit, 1)
        self.assertIn("mass edit threshold exceeded", blocked_output)
        self.assertEqual(allowed_exit, 0)
        self.assertIn("Processed: 2", allowed_output)

    def test_undo_run_restores_note_with_unicode_filename(self):
        # Regression: git octal-escapes non-ASCII paths in `diff --name-status`,
        # which previously broke restore/undo for vaults with accented filenames.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Loose").mkdir()
            note = root / "Loose" / "Café’s Über Notes.md"
            original = "# Café\n\nBody.\n"
            note.write_text(original, encoding="utf-8")

            process_exit, _ = self.run_cli(
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
            run_id = self.read_change_sets(root)[0]["run_id"]
            changed_exit, changed_output = self.run_cli(
                ["--vault-root", directory, "version", "changed-files", run_id]
            )
            undo_exit, undo_output = self.run_cli(
                ["--vault-root", directory, "version", "undo-run", run_id]
            )
            final_text = note.read_text(encoding="utf-8")

        self.assertEqual(process_exit, 0)
        self.assertEqual(changed_exit, 0)
        # raw UTF-8 path, not octal-escaped
        self.assertIn("Café’s Über Notes.md", changed_output)
        self.assertEqual(undo_exit, 0)
        self.assertIn("Restored paths:", undo_output)
        self.assertEqual(final_text, original)

    def test_restore_path_and_undo_run_restore_pre_run_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Loose").mkdir()
            note = root / "Loose" / "note.md"
            original = "# Note\n\nBody.\n"
            note.write_text(original, encoding="utf-8")

            process_exit, _ = self.run_cli(
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
            run_id = self.read_change_sets(root)[0]["run_id"]
            changed_exit, changed_output = self.run_cli(
                ["--vault-root", directory, "version", "changed-files", run_id]
            )
            restore_all_exit, restore_all_output = self.run_cli(
                ["--vault-root", directory, "version", "restore", run_id, "--all"]
            )
            restore_exit, restore_output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "version",
                    "restore",
                    run_id,
                    "--path",
                    "Loose/note.md",
                ]
            )
            note.write_text("---\ntype: note\n---\n# Changed\n", encoding="utf-8")
            undo_exit, undo_output = self.run_cli(
                ["--vault-root", directory, "version", "undo-run", run_id]
            )
            final_text = note.read_text(encoding="utf-8")

        self.assertEqual(process_exit, 0)
        self.assertEqual(changed_exit, 0)
        self.assertIn("Loose/note.md", changed_output)
        self.assertEqual(restore_all_exit, 1)
        self.assertIn("requires --force", restore_all_output)
        self.assertEqual(restore_exit, 0)
        self.assertIn("Restored paths: 1", restore_output)
        self.assertEqual(undo_exit, 0)
        self.assertIn("Restored paths:", undo_output)
        self.assertEqual(final_text, original)


if __name__ == "__main__":
    unittest.main()
