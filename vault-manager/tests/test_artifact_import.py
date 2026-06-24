import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from vault_agent.cli import main


class ArtifactImportTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def initialized_vault(self, root: Path, *, custom_paths: bool = False) -> None:
        args = ["--vault-root", str(root), "init"]
        if custom_paths:
            args.extend(["--system-dir", "System", "--inbox-dir", "Capture"])
        code, output = self.run_cli(args)
        self.assertEqual(code, 0, output)

    def submit(self, vault: Path, source: Path, root: Path, *extra: str):
        return self.run_cli(
            [
                "--vault-root",
                str(vault),
                "submit-artifact",
                "--source-path",
                str(source),
                "--read-root",
                str(root),
                "--source-task-id",
                "task-123",
                "--source-operation",
                "transcribe",
                "--json",
                *extra,
            ]
        )

    def test_markdown_creates_valid_pending_proposal_with_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            artifacts = base / "artifacts"
            vault.mkdir()
            artifacts.mkdir()
            self.initialized_vault(vault, custom_paths=True)
            review_path = vault / "System/0.01 agent/review/proposed-changes.md"
            review_before = review_path.read_text(encoding="utf-8")
            source = artifacts / "transcript.md"
            source.write_text("# Transcript\n\nOriginal.\n", encoding="utf-8")

            code, output = self.submit(vault, source, artifacts, "--title", "Lecture")
            result = json.loads(output)
            proposal = json.loads((vault / result["proposalPath"]).read_text(encoding="utf-8"))

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "pending_review")
            self.assertEqual(result["destinationPath"], "Capture/transcript.md")
            self.assertTrue(result["reviewValid"])
            self.assertEqual(proposal["status"], "pending")
            self.assertEqual(proposal["kind"], "artifact-import")
            self.assertEqual(proposal["provenance"]["source_task_id"], "task-123")
            self.assertEqual(proposal["operations"][0]["content"], "# Transcript\n\nOriginal.\n")
            self.assertFalse((vault / "Capture" / "transcript.md").exists())
            self.assertEqual(review_path.read_text(encoding="utf-8"), review_before)
            self.assertFalse((vault / "System/0.01 agent/tmp").exists())

    def test_text_normalizes_destination_to_markdown_without_changing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            artifacts = base / "artifacts"
            vault.mkdir()
            artifacts.mkdir()
            self.initialized_vault(vault)
            source = artifacts / "notes.txt"
            source.write_text("plain text\n", encoding="utf-8")

            code, output = self.submit(vault, source, artifacts)
            result = json.loads(output)
            proposal = json.loads((vault / result["proposalPath"]).read_text(encoding="utf-8"))

            self.assertEqual(code, 0)
            self.assertEqual(result["destinationPath"], "00 Inbox/notes.md")
            self.assertEqual(proposal["operations"][0]["content"], "plain text\n")

    def test_binary_format_is_rejected_without_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            artifacts = base / "artifacts"
            vault.mkdir()
            artifacts.mkdir()
            self.initialized_vault(vault)
            source = artifacts / "document.pdf"
            source.write_bytes(b"%PDF")

            code, output = self.submit(vault, source, artifacts)
            result = json.loads(output)

            self.assertEqual(code, 1)
            self.assertEqual(result["error"]["code"], "unsupported_artifact_format")
            self.assertEqual(list((vault / "99 System/0.01 agent/review/proposals").glob("import-*.json")), [])

    def test_source_outside_root_and_symlink_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            allowed = base / "allowed"
            outside = base / "outside"
            vault.mkdir()
            allowed.mkdir()
            outside.mkdir()
            self.initialized_vault(vault)
            source = outside / "secret.md"
            source.write_text("secret\n", encoding="utf-8")

            outside_code, outside_output = self.submit(vault, source, allowed)
            link = allowed / "escape.md"
            os.symlink(source, link)
            link_code, link_output = self.submit(vault, link, allowed)

            self.assertEqual(outside_code, 1)
            self.assertEqual(json.loads(outside_output)["error"]["code"], "source_outside_read_roots")
            self.assertEqual(link_code, 1)
            self.assertEqual(json.loads(link_output)["error"]["code"], "source_outside_read_roots")

    def test_existing_destination_is_warning_only_and_never_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            artifacts = base / "artifacts"
            vault.mkdir()
            artifacts.mkdir()
            self.initialized_vault(vault)
            destination = vault / "00 Inbox" / "same.md"
            destination.write_text("existing\n", encoding="utf-8")
            source = artifacts / "same.md"
            source.write_text("incoming\n", encoding="utf-8")

            code, output = self.submit(vault, source, artifacts)
            result = json.loads(output)

            self.assertEqual(code, 0)
            self.assertTrue(result["warnings"])
            self.assertEqual(destination.read_text(encoding="utf-8"), "existing\n")


if __name__ == "__main__":
    unittest.main()
