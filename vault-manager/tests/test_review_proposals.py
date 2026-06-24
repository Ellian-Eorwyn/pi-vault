import json
import tempfile
import unittest
from pathlib import Path

from vault_agent.cli import main


class ReviewProposalTests(unittest.TestCase):
    def run_cli(self, args):
        import contextlib
        import io

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_review_proposals_dry_run_renders_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposals = root / "99 System" / "0.01 agent" / "review" / "proposals"
            proposals.mkdir(parents=True)
            (proposals / "index.json").write_text(
                json.dumps(
                    {
                        "id": "project-index",
                        "title": "Project Index",
                        "kind": "index-note",
                        "status": "pending",
                        "summary": "Create a project index.",
                        "operations": [
                            {
                                "op": "write_file",
                                "path": "Indexes/Projects.md",
                                "content": "---\ntype: index\n---\n# Projects\n",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("review-proposals dry run", output)
        self.assertIn("Project Index", output)
        self.assertIn("Validation: passed", output)
        self.assertFalse((root / "99 System" / "0.01 agent" / "review" / "proposed-changes.md").exists())

    def test_apply_approved_index_note_proposal_marks_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposals = root / "99 System" / "0.01 agent" / "review" / "proposals"
            proposals.mkdir(parents=True)
            proposal_path = proposals / "index.json"
            proposal_path.write_text(
                json.dumps(
                    {
                        "id": "source-index",
                        "title": "Source Index",
                        "kind": "index-note",
                        "status": "approved",
                        "operations": [
                            {
                                "op": "write_file",
                                "path": "Indexes/Sources.md",
                                "content": "---\ntype: index\nrelated: []\n---\n# Sources\n",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            index_text = (root / "Indexes" / "Sources.md").read_text(encoding="utf-8")
            updated_proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            review = (
                root / "99 System" / "0.01 agent" / "review" / "proposed-changes.md"
            ).read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Applied: 1", output)
        self.assertIn("# Sources", index_text)
        self.assertEqual(updated_proposal["status"], "applied")
        self.assertIn("Source Index", review)
        self.assertIn("- Status: `applied`", review)

    def test_apply_approved_frontmatter_cleanup_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "note.md"
            note.write_text(
                "---\ntype: note\nlegacy: old\n---\n# Note\n\nBody.\n",
                encoding="utf-8",
            )
            proposals = root / "99 System" / "0.01 agent" / "review" / "proposals"
            proposals.mkdir(parents=True)
            (proposals / "cleanup.json").write_text(
                json.dumps(
                    {
                        "id": "cleanup-note",
                        "kind": "cleanup",
                        "status": "approved",
                        "operations": [
                            {
                                "op": "update_frontmatter",
                                "path": "note.md",
                                "set": {"status": "active", "domain": "meta"},
                                "remove": ["legacy"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            text = note.read_text(encoding="utf-8")
            backups = list(
                (root / "99 System" / "0.01 agent" / "backups").glob("note.md.*.bak")
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Applied: 1", output)
        self.assertIn("type: note\nstatus: active\ndomain: meta", text)
        self.assertNotIn("legacy:", text)
        self.assertIn("Body.", text)
        self.assertEqual(len(backups), 1)

    def test_organize_note_can_replace_malformed_frontmatter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "bad.md"
            note.write_text(
                "---\ntitle: ** Bad\n---\nOriginal body.\n",
                encoding="utf-8",
            )
            proposals = root / "99 System" / "0.01 agent" / "review" / "proposals"
            proposals.mkdir(parents=True)
            (proposals / "organize.json").write_text(
                json.dumps(
                    {
                        "id": "organize-bad",
                        "kind": "folder-organization",
                        "status": "approved",
                        "operations": [
                            {
                                "op": "organize_note",
                                "path": "bad.md",
                                "set": {
                                    "type": "note",
                                    "status": "active",
                                    "domain": "work",
                                    "parent": "[[Example]]",
                                    "related": [],
                                    "cover": "",
                                    "source_kind": "",
                                    "capture_type": "",
                                },
                                "remove": [],
                                "summary": "Clean summary.",
                                "apply_template": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Applied: 1", output)
        self.assertIn("type: note", text)
        self.assertIn('parent: "[[Example]]"', text)
        self.assertIn("Original body.", text)
        self.assertIn("## Summary", text)
        self.assertIn("Clean summary.", text)

    def test_invalid_queue_blocks_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposals = root / "99 System" / "0.01 agent" / "review" / "proposals"
            proposals.mkdir(parents=True)
            (proposals / "approved.json").write_text(
                json.dumps(
                    {
                        "id": "approved",
                        "kind": "index-note",
                        "status": "approved",
                        "operations": [
                            {
                                "op": "write_file",
                                "path": "Indexes/Approved.md",
                                "content": "# Approved\n",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (proposals / "invalid.json").write_text(
                json.dumps(
                    {
                        "id": "invalid",
                        "kind": "index-note",
                        "status": "approved",
                        "operations": [{"op": "delete_file", "path": "note.md"}],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid proposals must be fixed", output)
        self.assertFalse((root / "Indexes" / "Approved.md").exists())

    def test_agent_review_dry_run_recommends_safe_pending_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposals = root / "99 System" / "0.01 agent" / "review" / "proposals"
            proposals.mkdir(parents=True)
            (proposals / "index.json").write_text(
                json.dumps(
                    {
                        "id": "project-index",
                        "title": "Project Index",
                        "kind": "index-note",
                        "status": "pending",
                        "operations": [
                            {
                                "op": "write_file",
                                "path": "Indexes/Projects.md",
                                "content": "# Projects\n",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "review-proposals",
                    "--agent-review",
                    "--approve-safe",
                    "--dry-run",
                ]
            )
            proposal = json.loads((proposals / "index.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("Would approve safe pending proposals: 1", output)
        self.assertIn("Decision: `approve`", output)
        self.assertEqual(proposal["status"], "pending")

    def test_agent_review_approve_safe_marks_bounded_pending_proposal_approved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposals = root / "99 System" / "0.01 agent" / "review" / "proposals"
            proposals.mkdir(parents=True)
            proposal_path = proposals / "index.json"
            proposal_path.write_text(
                json.dumps(
                    {
                        "id": "project-index",
                        "title": "Project Index",
                        "kind": "index-note",
                        "status": "pending",
                        "operations": [
                            {
                                "op": "write_file",
                                "path": "Indexes/Projects.md",
                                "content": "# Projects\n",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "review-proposals",
                    "--agent-review",
                    "--approve-safe",
                ]
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            review = (
                root / "99 System" / "0.01 agent" / "review" / "agent-review.md"
            ).read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Agent approved: 1", output)
        self.assertEqual(proposal["status"], "approved")
        self.assertEqual(proposal["approved_by"], "vault-agent review-proposals --agent-review --approve-safe")
        self.assertIn("Decision: `defer`", review)

    def test_dry_run_rejects_escaping_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposals = root / "99 System" / "0.01 agent" / "review" / "proposals"
            proposals.mkdir(parents=True)
            (proposals / "escape.json").write_text(
                json.dumps(
                    {
                        "id": "escape",
                        "kind": "index-note",
                        "status": "pending",
                        "operations": [
                            {
                                "op": "write_file",
                                "path": "../outside.md",
                                "content": "# Outside\n",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("path cannot contain parent directory references", output)


if __name__ == "__main__":
    unittest.main()
