import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from vault_agent.cli import main
from vault_agent.config import load_config


class CliTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_main_help(self):
        exit_code, output = self.run_cli([])

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent", output)
        self.assertIn("process-next", output)
        self.assertIn("memory", output)

    def test_main_command_placeholder_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, output = self.run_cli(["--vault-root", directory, "scan"])

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent scan complete", output)
        self.assertIn("Discovered notes:", output)

    def test_main_command_accepts_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, output = self.run_cli(["--vault-root", directory, "--dry-run", "scan"])

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent scan dry run", output)
        self.assertIn("No files were changed", output)

    def test_main_command_accepts_dry_run_after_command(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, output = self.run_cli(["--vault-root", directory, "scan", "--dry-run"])

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent scan dry run", output)
        self.assertIn("No files were changed", output)

    def test_init_dry_run_reports_planned_setup_without_mutating(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, output = self.run_cli(
                ["--vault-root", directory, "init", "--dry-run"]
            )
            created_paths = list(Path(directory).iterdir())

        self.assertEqual(exit_code, 0)
        self.assertEqual(created_paths, [])
        self.assertIn("vault-agent init dry run", output)
        self.assertIn("No files were changed", output)
        self.assertIn("[create] 99 System/0.01 agent", output)
        self.assertIn("[create] 99 System/0.02 templates", output)
        self.assertIn("[create] 99 System/0.99 trash", output)
        self.assertIn("[create] 00 Inbox", output)
        self.assertIn("[create] 99 System/0.01 agent/config.yaml", output)
        self.assertIn("[create] 99 System/0.01 agent/retrieval/00 retrieval-readme.md", output)

    def test_init_dry_run_reports_existing_paths_without_mutating(self):
        with tempfile.TemporaryDirectory() as directory:
            existing_path = Path(directory) / "99 System" / "0.01 agent"
            existing_path.mkdir(parents=True)

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "init", "--dry-run"]
            )

            self.assertTrue(existing_path.exists())

        self.assertEqual(exit_code, 0)
        self.assertIn("[exists] 99 System", output)
        self.assertIn("[exists] 99 System/0.01 agent", output)
        self.assertIn("No files were changed", output)

    def test_init_dry_run_reports_existing_files_with_backup_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            existing_file = Path(directory) / "99 System" / "0.01 agent" / "config.yaml"
            existing_file.parent.mkdir(parents=True)
            existing_file.write_text("user config\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "init", "--dry-run"]
            )

            self.assertEqual(existing_file.read_text(encoding="utf-8"), "user config\n")

        self.assertEqual(exit_code, 0)
        self.assertIn("[exists] 99 System/0.01 agent/config.yaml", output)
        self.assertIn("preserve existing", output)
        self.assertIn("backups/config.yaml.bak", output)

    def test_init_without_dry_run_creates_starter_files(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, output = self.run_cli(["--vault-root", directory, "init"])
            root = Path(directory)
            self.assertTrue((root / "99 System" / "0.01 agent" / "config.yaml").is_file())
            handoff = root / "99 System" / "0.01 agent" / "AGENT_HANDOFF.md"
            self.assertTrue(handoff.is_file())
            self.assertIn(
                "Move or rename notes only through validated `move_note` proposals",
                handoff.read_text(encoding="utf-8"),
            )
            contract = root / "99 System" / "0.01 agent" / "AGENT_CONTRACT.md"
            self.assertTrue(contract.is_file())
            contract_text = contract.read_text(encoding="utf-8")
            self.assertIn("pi is the primary driver", contract_text)
            self.assertIn("Canonical Property Change Workflow", contract_text)
            self.assertIn("Index Note Workflow", contract_text)
            self.assertIn("Default Dashboard Navigation Model", contract_text)
            self.assertIn("04 Work", contract_text)
            self.assertIn("02.01 Contacts", contract_text)
            self.assertIn("02.02 Authors", contract_text)
            self.assertIn("Scheduled Maintenance Workflow", contract_text)
            self.assertTrue((root / "99 System" / "0.01 agent" / "schema.json").is_file())
            self.assertTrue((root / "99 System" / "0.02 templates" / "note-types" / "note.md").is_file())

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent init complete", output)

    def test_init_writes_sparse_controlled_vocabulary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, _output = self.run_cli(["--vault-root", directory, "init"])
            root = Path(directory)
            schema = json.loads(
                (root / "99 System" / "0.01 agent" / "schema.json").read_text(
                    encoding="utf-8"
                )
            )
            property_values = (
                root / "99 System" / "0.02 templates" / "0.021 property values.md"
            ).read_text(encoding="utf-8")
            folder_norms = (
                root / "99 System" / "0.02 templates" / "0.022 folder norms.md"
            ).read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            schema["core_properties"]["type"]["allowed"],
            [
                "",
                "project",
                "source",
                "person",
                "organization",
                "meeting",
                "task",
                "note",
                "index",
                "daily",
                "template",
                "system",
            ],
        )
        self.assertEqual(
            schema["core_properties"]["status"]["allowed"],
            ["", "active", "someday", "completed", "archived"],
        )
        self.assertIn("technology", schema["core_properties"]["domain"]["allowed"])
        self.assertEqual(
            schema["core_properties"]["source_kind"]["allowed"],
            [
                "",
                "book",
                "article",
                "report",
                "policy",
                "standard",
                "website",
                "dataset",
                "video",
                "podcast",
                "interview",
                "transcript",
                "presentation",
                "manual",
            ],
        )
        self.assertIn("Recommended Topic Hubs", folder_norms)
        self.assertIn("- Agents", folder_norms)
        self.assertIn("Never invent new type values.", folder_norms)
        self.assertIn("## source_kind", property_values)
        self.assertIn("- `manual`", property_values)
        self.assertIn("## capture_type", property_values)
        self.assertIn("- `imported`", property_values)
        self.assertIn("## parent", property_values)
        self.assertIn("cover: https://example.com/image.jpg", property_values)

    def test_verbose_command_prints_config_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, output = self.run_cli(["--vault-root", directory, "--verbose", "scan"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Vault root:", output)
        self.assertIn("Config path: (none)", output)
        self.assertIn("Dry run: False", output)

    def test_memory_command_placeholder_does_not_mutate(self):
        exit_code, output = self.run_cli(["memory", "status"])

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent memory status", output)
        self.assertIn("No files were changed", output)

    def test_memory_command_accepts_dry_run(self):
        exit_code, output = self.run_cli(["--dry-run", "memory", "status"])

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent memory status", output)
        self.assertIn("No files were changed", output)

    def test_memory_command_accepts_dry_run_after_command(self):
        exit_code, output = self.run_cli(["memory", "status", "--dry-run"])

        self.assertEqual(exit_code, 0)
        self.assertIn("vault-agent memory status", output)
        self.assertIn("No files were changed", output)


class ConfigTests(unittest.TestCase):
    def test_config_defaults(self):
        parser = main_parser_for_tests()
        args = parser.parse_args(["scan"])

        config = load_config(args)

        self.assertEqual(config.vault_root, Path.cwd().resolve())
        self.assertIsNone(config.config_path)
        self.assertFalse(config.dry_run)
        self.assertFalse(config.verbose)
        self.assertFalse(config.llm_enabled)
        self.assertEqual(config.llm_provider, "none")
        self.assertEqual(config.llm_base_url, "http://llms:8008")
        self.assertEqual(config.llm_model, "code")
        self.assertIsNone(config.llm_api_key)
        self.assertEqual(config.llm_confidence_threshold, 0.75)
        self.assertEqual(config.llm_timeout_seconds, 120)
        self.assertEqual(config.llm_max_input_tokens, 64000)
        self.assertEqual(config.llm_chars_per_token, 4)
        self.assertEqual(config.llm_max_input_chars, 256000)
        self.assertIsNone(config.embedding_base_url)
        self.assertEqual(config.embedding_model, "embed")
        self.assertEqual(config.max_notes, 5)
        self.assertEqual(config.max_runtime_minutes, 10)
        self.assertTrue(config.preserve_unknown_properties)
        self.assertTrue(config.review_on_warnings)
        self.assertEqual(config.warning_confidence_margin, 0.05)
        self.assertEqual(config.legacy_type_aliases["journal"], "daily")
        self.assertEqual(config.legacy_status_aliases["raw"], "active")
        self.assertEqual(config.legacy_property_aliases["domains"], "domain")
        self.assertEqual(config.legacy_property_aliases["area"], "domain")
        self.assertEqual(config.legacy_property_aliases["areas"], "domain")
        self.assertEqual(config.legacy_property_aliases["publication_type"], "source_kind")
        self.assertEqual(config.legacy_property_aliases["source"], "source_kind")
        self.assertEqual(config.legacy_property_aliases["tags"], "related")
        self.assertEqual(config.legacy_property_aliases["topic"], "related")
        self.assertEqual(config.legacy_property_aliases["topics"], "related")

    def test_config_explicit_options(self):
        parser = main_parser_for_tests()
        with tempfile.TemporaryDirectory() as directory:
            vault_root = Path(directory) / "vault"
            config_path = Path(directory) / "agent.yaml"
            args = parser.parse_args(
                [
                    "--vault-root",
                    str(vault_root),
                    "--config",
                    str(config_path),
                    "--dry-run",
                    "--verbose",
                    "scan",
                ]
            )

            config = load_config(args)

        self.assertEqual(config.vault_root, vault_root.resolve())
        self.assertEqual(config.config_path, config_path.resolve())
        self.assertTrue(config.dry_run)
        self.assertTrue(config.verbose)

    def test_config_file_loading(self):
        parser = main_parser_for_tests()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "agent.yaml"
            config_path.write_text(
                "auto_process:\n  max_notes: 2\n  max_runtime_minutes: 3\nllm:\n  enabled: true\n  provider: openai-compatible\n  base_url: http://llms:8008\n  model: qwen-test\n  confidence_threshold: 0.9\n  timeout_seconds: 30\n  max_input_tokens: 2000\n  chars_per_token: 3\n  max_input_chars: 1200\n  embedding_base_url: http://llms:8005\n  embedding_model: embed-test\nreview:\n  model_warnings_block_writes: false\n  warning_confidence_margin: 0.2\nlegacy_metadata:\n  preserve_unknown_properties: false\n  type_aliases:\n    custom: note\n  status_aliases:\n    queued: someday\n  property_aliases:\n    area: domain\n",
                encoding="utf-8",
            )
            args = parser.parse_args(["--config", str(config_path), "scan"])

            config = load_config(args)

        self.assertEqual(config.max_notes, 2)
        self.assertEqual(config.max_runtime_minutes, 3)
        self.assertTrue(config.llm_enabled)
        self.assertEqual(config.llm_provider, "openai-compatible")
        self.assertEqual(config.llm_base_url, "http://llms:8008")
        self.assertEqual(config.llm_model, "qwen-test")
        self.assertEqual(config.llm_confidence_threshold, 0.9)
        self.assertEqual(config.llm_timeout_seconds, 30)
        self.assertEqual(config.llm_max_input_tokens, 2000)
        self.assertEqual(config.llm_chars_per_token, 3)
        self.assertEqual(config.llm_max_input_chars, 1200)
        self.assertEqual(config.embedding_base_url, "http://llms:8005")
        self.assertEqual(config.embedding_model, "embed-test")
        self.assertFalse(config.review_on_warnings)
        self.assertEqual(config.warning_confidence_margin, 0.2)
        self.assertFalse(config.preserve_unknown_properties)
        self.assertEqual(config.legacy_type_aliases["custom"], "note")
        self.assertEqual(config.legacy_status_aliases["queued"], "someday")
        self.assertEqual(config.legacy_property_aliases["area"], "domain")

    def test_config_token_budget_computes_character_budget(self):
        parser = main_parser_for_tests()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "agent.yaml"
            config_path.write_text(
                "llm:\n  max_input_tokens: 64000\n  chars_per_token: 4\n",
                encoding="utf-8",
            )
            args = parser.parse_args(["--config", str(config_path), "scan"])

            config = load_config(args)

        self.assertEqual(config.llm_max_input_tokens, 64000)
        self.assertEqual(config.llm_chars_per_token, 4)
        self.assertEqual(config.llm_max_input_chars, 256000)


def main_parser_for_tests():
    from vault_agent.cli import build_parser

    return build_parser()


if __name__ == "__main__":
    unittest.main()
