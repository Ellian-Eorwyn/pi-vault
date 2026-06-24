import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from vault_agent.cli import main
from vault_agent.config import load_config
from vault_agent.layout_routing import build_inbox_sort_proposal
from vault_agent.llm import (
    JsonFileProposalProvider,
    _stage_prompt,
    validate_stage_proposal,
)
from vault_agent.paths import build_paths, paths_for, render_bootstrap


class AssignFolderStageTests(unittest.TestCase):
    def test_validator_accepts_listed_folder(self):
        result = validate_stage_proposal(
            "assign-folder",
            {"folder": "Areas/Health", "confidence": 0.9, "warnings": []},
            allowed_folders=["Areas/Health", "Resources/Books"],
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.proposal["folder"], "Areas/Health")

    def test_validator_rejects_unlisted_folder(self):
        result = validate_stage_proposal(
            "assign-folder",
            {"folder": "Random/Place", "confidence": 0.9, "warnings": []},
            allowed_folders=["Areas/Health"],
        )
        self.assertFalse(result.valid)

    def test_prompt_includes_catalog(self):
        prompt = _stage_prompt(
            note_path=Path("n.md"),
            note_text="body",
            stage="assign-folder",
            max_chars=1000,
            allowed_folders=[("Areas/Health", "fitness and medical")],
        )
        self.assertIn("Areas/Health", prompt)
        self.assertIn("fitness and medical", prompt)


class CustomFolderPathTests(unittest.TestCase):
    def test_build_paths_round_trips_custom_folders(self):
        paths = build_paths(
            "99 System",
            "00 Inbox",
            "01 Dashboards",
            None,
            None,
            [{"path": "Areas/Health", "description": "fitness"}],
        )
        self.assertEqual(paths.custom_folders[0].path.as_posix(), "Areas/Health")
        self.assertEqual(paths.custom_folders[0].description, "fitness")

    def test_build_paths_rejects_reserved_collision(self):
        with self.assertRaises(ValueError):
            build_paths(
                "99 System", "00 Inbox", "01 Dashboards", None, None,
                [{"path": "00 Inbox/Sub"}],
            )

    def test_build_paths_rejects_duplicate_custom_folders(self):
        with self.assertRaises(ValueError):
            build_paths(
                "99 System", "00 Inbox", "01 Dashboards", None, None,
                [{"path": "Areas/Health"}, {"path": "Areas/Health"}],
            )


class CustomRoutingEndToEndTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(args)
        return code, stdout.getvalue()

    def _bootstrap(self, root: Path, *, mode: str) -> None:
        paths = build_paths(
            "99 System",
            "00 Inbox",
            "01 Dashboards",
            None,
            None,
            [
                {"path": "Areas/Health", "description": "fitness, medical, nutrition"},
                {"path": "Resources/Books", "description": "book notes"},
            ],
        )
        bootstrap = render_bootstrap(paths, routing={"mode": mode, "fallback": "deterministic"})
        (root / ".pi-vault").mkdir(parents=True, exist_ok=True)
        (root / ".pi-vault" / "config.yaml").write_text(bootstrap, encoding="utf-8")

    def _provider(self, root: Path, folder: str, confidence: float) -> JsonFileProposalProvider:
        path = root / "stub.json"
        path.write_text(
            json.dumps({"folder": folder, "confidence": confidence, "warnings": []}),
            encoding="utf-8",
        )
        return JsonFileProposalProvider(path)

    def test_init_creates_custom_folders_and_dashboards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bootstrap(root, mode="custom")
            code, _ = self.run_cli(["--vault-root", directory, "init"])
            self.assertEqual(code, 0)
            self.assertTrue((root / "Areas" / "Health").is_dir())
            self.assertTrue((root / "Areas" / "Health" / "Health.md").is_file())
            self.assertTrue((root / "Resources" / "Books" / "Books.md").is_file())
            # routing mode flows into config.
            config = load_config(argparse.Namespace(vault_root=root))
            self.assertEqual(config.routing_mode, "custom")
            self.assertEqual(paths_for(root).custom_folders[0].path.as_posix(), "Areas/Health")

    def test_model_sorts_into_custom_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bootstrap(root, mode="custom")
            self.run_cli(["--vault-root", directory, "init"])
            (root / "00 Inbox" / "run.md").write_text(
                "---\ntype: note\n---\n# Morning run\n", encoding="utf-8"
            )
            config = load_config(argparse.Namespace(vault_root=root))
            provider = self._provider(root, "Areas/Health", 0.95)
            proposal, _warnings = build_inbox_sort_proposal(
                config, max_notes=5, proposal_provider=provider
            )
            moves = [op for op in proposal["operations"] if op["op"] == "move_note"]
            self.assertEqual(moves[0]["destination"], "Areas/Health/run.md")

    def test_low_confidence_falls_back_to_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bootstrap(root, mode="custom")
            self.run_cli(["--vault-root", directory, "init"])
            (root / "00 Inbox" / "thought.md").write_text(
                "---\ntype: note\n---\n# A stray thought\n", encoding="utf-8"
            )
            config = load_config(argparse.Namespace(vault_root=root))
            provider = self._provider(root, "Areas/Health", 0.1)
            proposal, _warnings = build_inbox_sort_proposal(
                config, max_notes=5, proposal_provider=provider
            )
            moves = [op for op in proposal["operations"] if op["op"] == "move_note"]
            # Deterministic fallback routes a plain note to Thoughts, not the custom folder.
            self.assertTrue(moves)
            self.assertTrue(moves[0]["destination"].startswith("06 Thoughts"))

    def test_deterministic_mode_ignores_custom_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bootstrap(root, mode="deterministic")
            self.run_cli(["--vault-root", directory, "init"])
            (root / "00 Inbox" / "n.md").write_text(
                "---\ntype: source\nsource_kind: book\n---\n# Book\n", encoding="utf-8"
            )
            config = load_config(argparse.Namespace(vault_root=root))
            # Provider would steer to Areas/Health, but deterministic mode ignores it.
            provider = self._provider(root, "Areas/Health", 0.95)
            proposal, _warnings = build_inbox_sort_proposal(
                config, max_notes=5, proposal_provider=provider
            )
            moves = [op for op in proposal["operations"] if op["op"] == "move_note"]
            self.assertTrue(moves[0]["destination"].startswith("07 Sources"))


if __name__ == "__main__":
    unittest.main()
