import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import yaml

from vault_agent.base_hierarchy import build_base_hierarchy_plan
from vault_agent.config import load_config
from vault_agent.cli import main
from vault_agent.proposals import generate_base_hierarchy, generate_folder_organization_proposal


class FailingProposalProvider:
    def __init__(self):
        self.calls = 0

    def propose_stage(self, *, note_path, note_text, stage):
        del note_path, note_text, stage
        self.calls += 1
        raise ValueError("backend unavailable")


class WarningProposalProvider:
    def __init__(self):
        self.calls = 0

    def propose_stage(self, *, note_path, note_text, stage):
        del note_path, note_text
        self.calls += 1
        self.stage = stage
        return {
            "note_type": "person",
            "confidence": 0.9,
            "warnings": ["ambiguous but reviewable"],
        }


class BaseHierarchyProvider:
    def __init__(self):
        self.prompt = ""

    def propose_base_hierarchy(self, *, prompt):
        self.prompt = prompt
        return {
            "domains": {
                "work": {
                    "label": "Work Lab",
                    "coverage": "Covers current project work and supporting references.",
                }
            },
            "parents": {
                "[[Example]]": {
                    "label": "Example Project",
                    "coverage": "Covers notes attached to the Example project.",
                }
            },
        }


class ProposalGeneratorTests(unittest.TestCase):
    def run_cli(self, args):
        import contextlib
        import io

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_propose_index_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-index",
                    "--index-type",
                    "type",
                    "--value",
                    "project",
                    "--dry-run",
                ]
            )
            proposals = (
                Path(directory)
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("proposal dry run", output)
        self.assertIn("Project Index", output)
        self.assertFalse(proposals.exists())

    def test_propose_index_writes_pending_valid_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-index",
                    "--index-type",
                    "type",
                    "--value",
                    "source",
                    "--title",
                    "Source Library",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "index-source-library.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            review_exit, review_output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("proposal complete", output)
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(proposal["kind"], "index-note")
        self.assertEqual(proposal["operations"][0]["path"], "Indexes/Source-Library.md")
        self.assertIn('type == "source"', proposal["operations"][0]["content"])
        self.assertEqual(review_exit, 0)
        self.assertIn("Validation: passed", review_output)

    def test_propose_property_writes_pending_schema_change_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-property",
                    "--property",
                    "domain",
                    "--value",
                    "legal",
                    "--description",
                    "Legal, compliance, and contracts.",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "property-domain-legal.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            schema = json.loads(proposal["operations"][0]["content"])
            review_exit, review_output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("proposal complete", output)
        self.assertEqual(proposal["kind"], "schema-change")
        self.assertEqual(proposal["status"], "pending")
        self.assertIn("legal", schema["core_properties"]["domain"]["allowed"])
        self.assertIn("Legal, compliance, and contracts.", proposal["operations"][1]["content"])
        self.assertIn("# Obsidian Vault Metadata Schema", proposal["operations"][1]["content"])
        self.assertIn("## Proposed Additions", proposal["operations"][1]["content"])
        self.assertEqual(review_exit, 0)
        self.assertIn("Validation: passed", review_output)

    def test_propose_property_preserves_current_property_values_doc(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            property_values = (
                root / "00 System" / "0.02 templates" / "0.021 property values.md"
            )
            property_values.parent.mkdir(parents=True)
            property_values.write_text(
                "# Property Values\n\nHuman note that should stay.\n",
                encoding="utf-8",
            )

            exit_code, _output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-property",
                    "--property",
                    "domain",
                    "--value",
                    "legal",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "property-domain-legal.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("Human note that should stay.", proposal["operations"][1]["content"])
        self.assertIn("## Proposed Additions", proposal["operations"][1]["content"])

    def test_propose_property_rejects_existing_value(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-property",
                    "--property",
                    "domain",
                    "--value",
                    "work",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("already exists", output)

    def test_propose_template_writes_pending_template_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-template",
                    "--note-type",
                    "meeting",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "template-meeting.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            review_exit, review_output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("proposal complete", output)
        self.assertEqual(proposal["kind"], "template-change")
        self.assertEqual(
            proposal["operations"][0]["path"],
            "00 System/0.02 templates/note-types/meeting.md",
        )
        self.assertIn("## Agenda", proposal["operations"][0]["content"])
        self.assertEqual(review_exit, 0)
        self.assertIn("Validation: passed", review_output)

    def test_propose_cleanup_writes_frontmatter_cleanup_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "legacy.md"
            note.write_text(
                "---\ntype: journal\nstatus: raw\ndomains: [personal]\nlegacy: old\n---\n# Legacy\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-cleanup",
                    "--note",
                    "legacy.md",
                    "--remove-unknown",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "cleanup-legacy.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            operation = proposal["operations"][0]
            review_exit, review_output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("proposal complete", output)
        self.assertEqual(proposal["kind"], "cleanup")
        self.assertEqual(operation["set"]["type"], "daily")
        self.assertEqual(operation["set"]["status"], "active")
        self.assertEqual(operation["set"]["domain"], "personal")
        self.assertIn("legacy", operation["remove"])
        self.assertIn("domains", operation["remove"])
        self.assertEqual(review_exit, 0)
        self.assertIn("Validation: passed", review_output)

    def test_propose_cleanup_rejects_note_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            note = Path(directory) / "clean.md"
            note.write_text(
                "---\ntype: note\nstatus: active\ndomain: meta\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Clean\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "propose-cleanup", "--note", "clean.md"]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("no cleanup changes found", output)

    def test_base_hierarchy_plan_counts_domains_and_metadata_gaps(self):
        entries = [
            {
                "path": "Projects/Example.md",
                "title": "Example",
                "type": "project",
                "status": "active",
                "domain": "work",
                "parent": "",
                "frontmatter_error": None,
                "system_template": False,
            },
            {
                "path": "Projects/Example/Note.md",
                "title": "Note",
                "type": "note",
                "status": "active",
                "domain": "work",
                "parent": "[[Example]]",
                "frontmatter_error": None,
                "system_template": False,
            },
            {
                "path": "Loose.md",
                "title": "Loose",
                "type": "note",
                "status": "active",
                "domain": "",
                "parent": "",
                "frontmatter_error": None,
                "system_template": False,
            },
            {
                "path": "00 System/0.02 templates/note-types/note.md",
                "title": "Template",
                "type": "template",
                "status": "active",
                "domain": "meta",
                "parent": "",
                "frontmatter_error": None,
                "system_template": True,
            },
        ]

        plan = build_base_hierarchy_plan(entries, min_child_notes=2)

        self.assertEqual(plan.total_notes, 3)
        self.assertEqual(len(plan.domains), 1)
        self.assertEqual(plan.domains[0].domain, "work")
        self.assertEqual(plan.domains[0].count, 2)
        self.assertEqual(plan.domains[0].parent_groups[0].key, "[[Example]]")
        self.assertEqual([entry["path"] for entry in plan.needs_metadata], ["Loose.md"])

    def test_propose_base_hierarchy_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Work.md").write_text(
                "---\ntype: project\nstatus: active\ndomain: work\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Work\n",
                encoding="utf-8",
            )
            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-base-hierarchy",
                    "--dry-run",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "base-hierarchy.json"
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("proposal dry run", output)
        self.assertIn("No files were changed.", output)
        self.assertFalse(proposal_path.exists())

    def test_propose_base_hierarchy_writes_valid_reviewable_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Projects").mkdir()
            (root / "Projects" / "Example.md").write_text(
                "---\ntype: project\nstatus: active\ndomain: work\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Example\n",
                encoding="utf-8",
            )
            (root / "Projects" / "Research.md").write_text(
                "---\ntype: source\nstatus: active\ndomain: work\nparent: \"[[Example]]\"\nrelated: []\ncover:\nsource_kind: report\ncapture_type:\n---\n# Research\n",
                encoding="utf-8",
            )
            (root / "Loose.md").write_text(
                "---\ntype: note\nstatus: active\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Loose\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "propose-base-hierarchy"]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "base-hierarchy.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            review_exit, review_output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Domains: 1", output)
        self.assertIn("Parent/project dashboards: 1", output)
        self.assertIn("Needs metadata: 1", output)
        self.assertEqual(proposal["kind"], "base-hierarchy")
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(proposal["operations"][0]["path"], "Indexes/Base Hierarchy/Vault Domains.md")
        self.assertTrue(all(operation["op"] == "write_file" for operation in proposal["operations"]))
        self.assertEqual(review_exit, 0)
        self.assertIn("Validation: passed", review_output)
        for operation in proposal["operations"]:
            _assert_base_blocks_parse(self, operation["content"])
        joined = "\n".join(op["content"] for op in proposal["operations"])
        self.assertIn("cssclasses:", joined)
        self.assertIn("displayName:", joined)
        self.assertIn("sort:", joined)

    def test_base_hierarchy_apply_writes_dashboards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Project.md").write_text(
                "---\ntype: project\nstatus: active\ndomain: work\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Project\n",
                encoding="utf-8",
            )
            self.run_cli(["--vault-root", directory, "propose-base-hierarchy"])
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "base-hierarchy.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            proposal["status"] = "approved"
            proposal_path.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            primary_exists = (root / "Indexes" / "Base Hierarchy" / "Vault Domains.md").exists()
            domain_exists = (root / "Indexes" / "Base Hierarchy" / "Work.md").exists()

        self.assertEqual(exit_code, 0)
        self.assertIn("Applied: 1", output)
        self.assertTrue(primary_exists)
        self.assertTrue(domain_exists)

    def test_base_hierarchy_accepts_optional_llm_coverage_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Example.md").write_text(
                "---\ntype: project\nstatus: active\ndomain: work\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Example\n",
                encoding="utf-8",
            )
            config = load_config(
                Namespace(
                    vault_root=directory,
                    config=None,
                    dry_run=True,
                    verbose=False,
                )
            )
            provider = BaseHierarchyProvider()

            proposal, errors, stats = generate_base_hierarchy(
                config=config,
                proposal_provider=provider,
                llm_limit=1,
            )

        self.assertEqual(errors, [])
        self.assertTrue(stats["llm_used"])
        self.assertIn("Covers current project work", proposal["operations"][1]["content"])
        self.assertIn("Work Lab", proposal["operations"][1]["content"])
        self.assertIn("work", provider.prompt)

    def test_propose_folder_organization_writes_valid_project_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Projects" / "Example"
            folder.mkdir(parents=True)
            note = folder / "Meeting.md"
            note.write_text(
                "---\ntype: meeting\nstatus: complete\ndomains: [work]\ntags: [example]\n---\n# Meeting\n\nAgenda\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-folder-organization",
                    "--folder",
                    "Projects/Example",
                    "--project",
                    "Example",
                    "--domain",
                    "work",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "folder-organization-example.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            review_exit, review_output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Notes organized: 1", output)
        self.assertEqual(proposal["kind"], "folder-organization")
        self.assertEqual(proposal["operations"][0]["op"], "organize_note")
        self.assertEqual(proposal["operations"][0]["set"]["status"], "completed")
        self.assertEqual(proposal["operations"][0]["set"]["parent"], "[[Example]]")
        self.assertEqual(proposal["operations"][0]["set"]["domain"], "work")
        self.assertEqual(proposal["operations"][-1]["op"], "write_file")
        self.assertIn("```base", proposal["operations"][-1]["content"])
        self.assertIn('file.path.contains("Projects/Example")', proposal["operations"][-1]["content"])
        self.assertEqual(review_exit, 0)
        self.assertIn("Validation: passed", review_output)

    def test_folder_organization_apply_appends_template_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Projects" / "Example"
            folder.mkdir(parents=True)
            note = folder / "Task.md"
            note.write_text(
                "---\ntype: inbox\nstatus: raw\ndomains: [work]\ntags: [example]\n---\nOriginal body.\n",
                encoding="utf-8",
            )
            self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-folder-organization",
                    "--folder",
                    "Projects/Example",
                    "--project",
                    "Example",
                    "--domain",
                    "work",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "folder-organization-example.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            proposal["status"] = "approved"
            proposal_path.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            organized = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Applied: 1", output)
        self.assertIn("type: note", organized)
        self.assertIn("status: active", organized)
        self.assertIn('parent: "[[Example]]"', organized)
        self.assertIn("Original body.", organized)
        self.assertIn("## Summary", organized)

    def test_propose_folder_organization_can_explicitly_overwrite_existing_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Projects" / "Example"
            folder.mkdir(parents=True)
            (folder / "Note.md").write_text("---\ntype: note\n---\n# Note\n", encoding="utf-8")
            args = [
                "--vault-root",
                directory,
                "propose-folder-organization",
                "--folder",
                "Projects/Example",
                "--project",
                "Example",
                "--domain",
                "work",
            ]
            first_exit, _first_output = self.run_cli(args)
            second_exit, second_output = self.run_cli(args)
            overwrite_exit, overwrite_output = self.run_cli(args + ["--overwrite-proposal"])

        self.assertEqual(first_exit, 0)
        self.assertEqual(second_exit, 1)
        self.assertIn("proposal already exists", second_output)
        self.assertEqual(overwrite_exit, 0)
        self.assertIn("proposal complete", overwrite_output)

    def test_propose_folder_organization_checkpoint_writes_final_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Projects" / "Example"
            folder.mkdir(parents=True)
            (folder / "Note.md").write_text("---\ntype: note\n---\n# Note\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-folder-organization",
                    "--folder",
                    "Projects/Example",
                    "--project",
                    "Example",
                    "--domain",
                    "work",
                    "--checkpoint",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "folder-organization-example.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertIn("[1/1] Projects/Example/Note.md", output)
        self.assertEqual(proposal["operations"][-1]["op"], "write_file")

    def test_folder_organization_excludes_dashboard_from_source_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Projects" / "Example"
            folder.mkdir(parents=True)
            (folder / "Note.md").write_text("---\ntype: note\n---\n# Note\n", encoding="utf-8")
            (folder / "Example-Dashboard.md").write_text(
                "---\ntype: index\n---\n# Dashboard\n", encoding="utf-8"
            )

            exit_code, _output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-folder-organization",
                    "--folder",
                    "Projects/Example",
                    "--project",
                    "Example",
                    "--domain",
                    "work",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "folder-organization-example.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            organize_paths = [
                operation["path"]
                for operation in proposal["operations"]
                if operation["op"] == "organize_note"
            ]

        self.assertEqual(exit_code, 0)
        self.assertEqual(organize_paths, ["Projects/Example/Note.md"])

    def test_folder_organization_resume_reuses_checkpoint_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Projects" / "Example"
            folder.mkdir(parents=True)
            (folder / "A.md").write_text("---\ntype: note\n---\n# A\n", encoding="utf-8")
            (folder / "B.md").write_text("---\ntype: note\n---\n# B\n", encoding="utf-8")
            proposals = root / "00 System" / "0.01 agent" / "review" / "proposals"
            proposals.mkdir(parents=True)
            (proposals / "folder-organization-example.json").write_text(
                json.dumps(
                    {
                        "id": "folder-organization-example",
                        "title": "Organize `Example` folder",
                        "kind": "folder-organization",
                        "status": "pending",
                        "operations": [
                            {
                                "op": "organize_note",
                                "path": "Projects/Example/A.md",
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
                                "summary": "",
                                "apply_template": True,
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
                    "propose-folder-organization",
                    "--folder",
                    "Projects/Example",
                    "--project",
                    "Example",
                    "--domain",
                    "work",
                    "--checkpoint",
                    "--resume",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("skipped Projects/Example/A.md", output)
        self.assertIn("[2/2] Projects/Example/B.md", output)

    def test_folder_organization_counts_failed_llm_attempts_against_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Projects" / "Example"
            folder.mkdir(parents=True)
            for name in ("A.md", "B.md"):
                (folder / name).write_text(
                    "---\ntype: note\nstatus: raw\ndomains: [work]\ntags: []\n---\n# Note\n",
                    encoding="utf-8",
                )
            config = load_config(
                Namespace(
                    vault_root=directory,
                    config=None,
                    dry_run=True,
                    verbose=False,
                )
            )
            provider = FailingProposalProvider()

            _proposal, errors, stats = generate_folder_organization_proposal(
                config=config,
                folder="Projects/Example",
                project="Example",
                domain="work",
                proposal_provider=provider,
                llm_limit=1,
            )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(stats["llm_notes"], 0)
        self.assertEqual(len(errors), 1)
        self.assertIn("backend unavailable", errors[0])

    def test_folder_organization_accepts_warning_llm_type_for_reviewable_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Projects" / "Example"
            folder.mkdir(parents=True)
            (folder / "A.md").write_text(
                "---\ntype: note\nstatus: raw\ndomains: [work]\ntags: []\n---\n# Note\n",
                encoding="utf-8",
            )
            config = load_config(
                Namespace(
                    vault_root=directory,
                    config=None,
                    dry_run=True,
                    verbose=False,
                )
            )
            provider = WarningProposalProvider()

            proposal, errors, stats = generate_folder_organization_proposal(
                config=config,
                folder="Projects/Example",
                project="Example",
                domain="work",
                proposal_provider=provider,
                llm_limit=1,
            )

        self.assertEqual(errors, [])
        self.assertEqual(provider.calls, 1)
        self.assertEqual(provider.stage, "classify-type")
        self.assertEqual(stats["llm_notes"], 1)
        self.assertEqual(proposal["operations"][0]["set"]["type"], "person")

    def test_folder_organization_remove_legacy_generates_non_core_removals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Projects" / "Example"
            folder.mkdir(parents=True)
            (folder / "A.md").write_text(
                "---\ntype: note\nstatus: raw\ndomains: [work]\ntitle: A\nsummary: Old\n---\n# Note\n",
                encoding="utf-8",
            )
            config = load_config(
                Namespace(
                    vault_root=directory,
                    config=None,
                    dry_run=True,
                    verbose=False,
                )
            )

            proposal, errors, _stats = generate_folder_organization_proposal(
                config=config,
                folder="Projects/Example",
                project="Example",
                domain="work",
                remove_legacy=True,
            )

        self.assertEqual(errors, [])
        self.assertEqual(
            proposal["operations"][0]["remove"],
            ["domains", "summary", "title"],
        )


def _base_blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() == "```base":
            index += 1
            block: list[str] = []
            while index < len(lines) and lines[index].strip() != "```":
                block.append(lines[index])
                index += 1
            blocks.append("\n".join(block))
        index += 1
    return blocks


def _assert_base_blocks_parse(test_case: unittest.TestCase, markdown: str) -> None:
    blocks = _base_blocks(markdown)
    test_case.assertGreaterEqual(len(blocks), 1)
    for block in blocks:
        loaded = yaml.safe_load(block)
        test_case.assertIsInstance(loaded, dict)
        test_case.assertIn("views", loaded)
        view_types = {view.get("type") for view in loaded.get("views", [])}
        test_case.assertTrue(view_types & {"cards", "table"})


if __name__ == "__main__":
    unittest.main()
