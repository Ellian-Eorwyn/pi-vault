import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from vault_agent.cli import main
from vault_agent.config import load_config
from vault_agent.dashboard_layout import dashboard_shell_contents
from vault_agent.paths import build_paths
from vault_agent.schema import AGENT_RULES, CORE_PROPERTY_ORDER
from vault_agent.schema_defaults import (
    parse_vault_defaults_markdown,
    proposal_from_vault_defaults,
    vault_defaults_markdown,
)
from vault_agent.validation import validate_entries


class SchemaDefaultsTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_default_export_contains_schema_layout_dashboard_and_rules(self):
        text = vault_defaults_markdown()

        self.assertIn("# Editable Vault Defaults", text)
        self.assertIn("core_property_order:", text)
        self.assertIn("- type", text)
        self.assertIn("controlled_values:", text)
        self.assertIn("- technology", text)
        self.assertIn("folders:", text)
        self.assertIn("system_dir: 99 System", text)
        self.assertIn("dashboard_structure:", text)
        self.assertIn("01 Dashboards/Home.md", text)
        self.assertIn("dashboard_rules:", text)
        self.assertIn("agent_rules:", text)
        for rule in AGENT_RULES:
            self.assertIn(rule, text)

    def test_default_export_round_trips_to_schema_proposal(self):
        parsed = parse_vault_defaults_markdown(vault_defaults_markdown())
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(_Args(Path(directory)))
            proposal = proposal_from_vault_defaults(config, parsed)

        self.assertEqual(proposal["kind"], "schema-change")
        self.assertEqual(proposal["status"], "pending")
        self.assertIn(
            "99 System/0.01 agent/schema.json",
            [operation.get("path") for operation in proposal["operations"]],
        )
        self.assertIn(
            "99 System/0.02 templates/0.024 vault defaults.md",
            [operation.get("path") for operation in proposal["operations"]],
        )

    def test_import_edited_domain_and_folder_generates_pending_proposal_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, output = self.run_cli(["--vault-root", directory, "init"])
            self.assertEqual(code, 0, output)
            exported = root / "defaults.md"
            code, output = self.run_cli(
                ["--vault-root", directory, "export-schema-defaults", "--output", str(exported)]
            )
            self.assertEqual(code, 0, output)

            data = _blocks(exported.read_text(encoding="utf-8"))
            data["controlled_values"]["domain"].append("legal")
            data["folders"]["domain_folders"] = {"legal": "08 Legal"}
            data["dashboard_structure"] = _dashboard_structure_for(data["folders"])
            edited = _replace_blocks(exported.read_text(encoding="utf-8"), data)
            exported.write_text(edited, encoding="utf-8")

            code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "import-schema-defaults",
                    "--schema-file",
                    str(exported),
                ]
            )
            proposal_path = (
                root
                / "99 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "vault-schema-defaults.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            schema_after_import = json.loads(
                (root / "99 System" / "0.01 agent" / "schema.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(code, 0, output)
        self.assertEqual(proposal["status"], "pending")
        self.assertIn("08 Legal", json.dumps(proposal))
        self.assertNotIn("legal", schema_after_import["core_properties"]["domain"]["allowed"])

    def test_import_rejects_malformed_markdown_without_writing_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad = root / "bad.md"
            bad.write_text("# Bad\n\n```yaml\nunknown_section: true\n```\n", encoding="utf-8")

            code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "import-schema-defaults",
                    "--schema-file",
                    str(bad),
                ]
            )
            proposal_path = (
                root
                / "99 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "vault-schema-defaults.json"
            )

        self.assertEqual(code, 1)
        self.assertIn("unknown YAML section key", output)
        self.assertFalse(proposal_path.exists())

    def test_schema_json_domains_are_accepted_by_validation_after_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, output = self.run_cli(["--vault-root", directory, "init"])
            self.assertEqual(code, 0, output)
            exported = root / "defaults.md"
            code, output = self.run_cli(
                ["--vault-root", directory, "export-schema-defaults", "--output", str(exported)]
            )
            self.assertEqual(code, 0, output)
            data = _blocks(exported.read_text(encoding="utf-8"))
            data["controlled_values"]["domain"].append("legal")
            data["folders"]["domain_folders"] = {"legal": "08 Legal"}
            data["dashboard_structure"] = _dashboard_structure_for(data["folders"])
            exported.write_text(
                _replace_blocks(exported.read_text(encoding="utf-8"), data),
                encoding="utf-8",
            )
            code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "import-schema-defaults",
                    "--schema-file",
                    str(exported),
                ]
            )
            self.assertEqual(code, 0, output)
            proposal_path = (
                root
                / "99 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "vault-schema-defaults.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            proposal["status"] = "approved"
            proposal_path.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
            code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "review-proposals",
                    "--apply-approved",
                    "--mass-edit",
                ]
            )
            self.assertEqual(code, 0, output)
            note = root / "08 Legal" / "Case.md"
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(
                "---\ntype: note\nstatus: active\ndomain: legal\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Case\n",
                encoding="utf-8",
            )
            config = load_config(_Args(root))
            issues = validate_entries(
                [
                    {
                        "path": "08 Legal/Case.md",
                        "frontmatter": {"domain": "legal"},
                        "domain": "legal",
                    }
                ],
                config,
            )

        self.assertEqual([issue.message for issue in issues], [])

    def test_smoke_init_export_import_review_and_obsidian_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code, output = self.run_cli(["--vault-root", directory, "init"])
            self.assertEqual(code, 0, output)
            exported = root / "defaults.md"
            code, output = self.run_cli(
                ["--vault-root", directory, "export-schema-defaults", "--output", str(exported)]
            )
            self.assertEqual(code, 0, output)
            code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "import-schema-defaults",
                    "--schema-file",
                    str(exported),
                    "--dry-run",
                ]
            )
            self.assertEqual(code, 0, output)
            self.assertIn("No files were changed", output)
            code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "import-schema-defaults",
                    "--schema-file",
                    str(exported),
                ]
            )
            self.assertEqual(code, 0, output)
            code, output = self.run_cli(["--vault-root", directory, "review-proposals", "--dry-run"])
            self.assertEqual(code, 0, output)
            code, output = self.run_cli(["--vault-root", directory, "obsidian-check", "--json"])
            self.assertEqual(code, 0, output)
            self.assertTrue(exported.exists())


class _Args:
    def __init__(self, vault_root: Path):
        self.vault_root = vault_root
        self.config = None
        self.dry_run = False
        self.verbose = False


def _blocks(text: str) -> dict:
    parsed = parse_vault_defaults_markdown(text)
    return {
        "core_property_order": parsed["core_property_order"],
        "controlled_values": parsed["controlled_values"],
        "note_type_descriptions": parsed["note_type_descriptions"],
        "status_descriptions": parsed["status_descriptions"],
        "domain_descriptions": parsed["domain_descriptions"],
        "source_kind_descriptions": parsed["source_kind_descriptions"],
        "capture_type_descriptions": parsed["capture_type_descriptions"],
        "folders": parsed["folders"],
        "dashboard_structure": parsed["dashboard_structure"],
        "dashboard_rules": parsed["dashboard_rules"],
        "agent_rules": parsed["agent_rules"],
        "schema_change_policy": parsed["schema_change_policy"],
    }


def _replace_blocks(text: str, data: dict) -> str:
    replacements = [
        {"core_property_order": data["core_property_order"]},
        {"controlled_values": data["controlled_values"]},
        {"note_type_descriptions": data["note_type_descriptions"]},
        {"status_descriptions": data["status_descriptions"]},
        {"domain_descriptions": data["domain_descriptions"]},
        {"source_kind_descriptions": data["source_kind_descriptions"]},
        {"capture_type_descriptions": data["capture_type_descriptions"]},
        {"folders": data["folders"]},
        {"dashboard_structure": data["dashboard_structure"]},
        {"dashboard_rules": data["dashboard_rules"]},
        {"agent_rules": data["agent_rules"]},
        {"schema_change_policy": data["schema_change_policy"]},
    ]
    parts = text.split("```yaml")
    result = [parts[0]]
    for part, replacement in zip(parts[1:], replacements, strict=True):
        _old, rest = part.split("```", 1)
        result.append("```yaml\n" + yaml.safe_dump(replacement, sort_keys=False).rstrip() + "\n```" + rest)
    return "".join(result)


def _dashboard_structure_for(folders: dict) -> dict:
    paths = build_paths(
        folders["system_dir"],
        folders["inbox_dir"],
        folders["dashboards_dir"],
        folders["content_dirs"],
        folders.get("domain_folders"),
        folders.get("custom_folders"),
    )
    return {
        "root": paths.dashboards_dir.as_posix(),
        "entries": [
            {"path": path, "title": Path(path).stem}
            for path in sorted(dashboard_shell_contents(paths))
        ],
    }


if __name__ == "__main__":
    unittest.main()
