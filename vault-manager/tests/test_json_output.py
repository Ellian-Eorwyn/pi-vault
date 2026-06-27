import contextlib
import io
import json
import tempfile
import unittest

from vault_agent.cli import main


class JsonOutputTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_propose_command_emits_structured_json(self):
        with tempfile.TemporaryDirectory() as directory:
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
                    "--json",
                ]
            )
        self.assertEqual(exit_code, 0)
        data = json.loads(output.strip())
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["kind"], "index-note")
        self.assertEqual(data["proposal_status"], "pending")
        self.assertGreaterEqual(data["operations"], 1)
        self.assertTrue(data["path"].endswith(".json"))

    def test_propose_command_dry_run_json_does_not_write(self):
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
                    "--json",
                ]
            )
        self.assertEqual(exit_code, 0)
        data = json.loads(output.strip())
        self.assertEqual(data["status"], "dry-run")
        self.assertEqual(data["kind"], "index-note")

    def test_process_command_emits_run_summary_json(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-vault",
                    "--max-notes",
                    "1",
                    "--json",
                ]
            )
        data = json.loads(output.strip())
        self.assertEqual(data["scope"], "vault")
        self.assertIn(data["status"], ("ok", "error"))
        self.assertEqual(data["exit_code"], exit_code)
        self.assertIn("output", data)


if __name__ == "__main__":
    unittest.main()
