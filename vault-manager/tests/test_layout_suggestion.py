import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from vault_agent.cli import main
from vault_agent.layout_suggestion import (
    parse_layout_outline,
    render_layout_outline,
    suggest_layout,
)
from vault_agent.layout_routing import route_note
from vault_agent.config import load_config
from vault_agent.paths import DEFAULT_PATHS, build_paths, paths_for
from vault_agent.scanner import ScanResult
from vault_agent.validation import run_validate


def _entry(path: str, **frontmatter) -> dict:
    entry = {"path": path, "title": Path(path).stem}
    entry.update(frontmatter)
    return entry


class SuggestLayoutTests(unittest.TestCase):
    def test_named_folder_maps_to_role(self):
        scan = ScanResult(
            entries=[_entry("Reading/book.md", type="source")],
            folders=["Reading"],
        )
        suggestion = suggest_layout(scan, DEFAULT_PATHS)
        self.assertEqual(suggestion.content_dirs["sources"].as_posix(), "Reading")
        self.assertEqual(suggestion.domain_folders, {})

    def test_type_dominated_folder_maps_when_name_is_unclear(self):
        scan = ScanResult(
            entries=[
                _entry("Misc/p1.md", type="person"),
                _entry("Misc/p2.md", type="person"),
                _entry("Misc/p3.md", type="note"),
            ],
            folders=["Misc"],
        )
        suggestion = suggest_layout(scan, DEFAULT_PATHS)
        self.assertEqual(suggestion.content_dirs["people"].as_posix(), "Misc")
        self.assertEqual(suggestion.content_dirs["contacts"].as_posix(), "Misc/02.01 Contacts")

    def test_unmatched_folder_becomes_domain(self):
        scan = ScanResult(
            entries=[_entry("Cooking/pasta.md")],
            folders=["Cooking"],
        )
        suggestion = suggest_layout(scan, DEFAULT_PATHS)
        self.assertEqual(
            {d: f.as_posix() for d, f in suggestion.domain_folders.items()},
            {"cooking": "Cooking"},
        )
        # Built-in roles keep their defaults when nothing matches.
        self.assertEqual(suggestion.content_dirs["sources"].as_posix(), "07 Sources")

    def test_contested_role_keeps_busiest_and_demotes_rest_to_domain(self):
        scan = ScanResult(
            entries=[
                _entry("Reading/a.md", type="source"),
                _entry("Reading/b.md", type="source"),
                _entry("Library/c.md", type="source"),
            ],
            folders=["Reading", "Library"],
        )
        suggestion = suggest_layout(scan, DEFAULT_PATHS)
        self.assertEqual(suggestion.content_dirs["sources"].as_posix(), "Reading")
        self.assertEqual(
            {d: f.as_posix() for d, f in suggestion.domain_folders.items()},
            {"library": "Library"},
        )

    def test_outline_round_trip(self):
        scan = ScanResult(
            entries=[
                _entry("Projects/p.md", type="project", domain="work"),
                _entry("Cooking/r.md"),
            ],
            folders=["Projects", "Cooking"],
        )
        suggestion = suggest_layout(scan, DEFAULT_PATHS)
        outline = render_layout_outline(suggestion)
        paths = parse_layout_outline(outline)
        self.assertEqual(paths.content_dirs["work"].as_posix(), "Projects")
        self.assertEqual(
            {d: f.as_posix() for d, f in paths.domain_folders.items()},
            {"cooking": "Cooking"},
        )

    def test_parse_rejects_domain_folder_nested_in_content_dir(self):
        outline = (
            "system_dir: 99 System\n"
            "inbox_dir: 00 Inbox\n"
            "dashboards_dir: 01 Dashboards\n"
            "domain_folders:\n"
            "  cooking: 02 People/Sub\n"
        )
        with self.assertRaises(ValueError):
            parse_layout_outline(outline)

    def test_parse_rejects_content_role_domain_key(self):
        outline = (
            "system_dir: 99 System\n"
            "inbox_dir: 00 Inbox\n"
            "dashboards_dir: 01 Dashboards\n"
            "domain_folders:\n"
            "  work: Work2\n"
        )
        with self.assertRaises(ValueError):
            parse_layout_outline(outline)


class DomainFolderPathTests(unittest.TestCase):
    def test_build_paths_round_trips_domain_folders(self):
        paths = build_paths(
            "99 System", "00 Inbox", "01 Dashboards", None, {"cooking": "Cooking", "music": "Music"}
        )
        self.assertEqual(
            {d: f.as_posix() for d, f in paths.domain_folders.items()},
            {"cooking": "Cooking", "music": "Music"},
        )

    def test_build_paths_rejects_uppercase_domain_key(self):
        with self.assertRaises(ValueError):
            build_paths("99 System", "00 Inbox", "01 Dashboards", None, {"Cooking": "Cooking"})


class LayoutCliTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_suggest_apply_init_flow_creates_routable_domain_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Projects").mkdir()
            (root / "Projects" / "p.md").write_text(
                "---\ntype: project\ndomain: work\n---\n# P\n", encoding="utf-8"
            )
            (root / "Cooking").mkdir()
            (root / "Cooking" / "pasta.md").write_text("# Pasta\n", encoding="utf-8")

            suggest_code, _ = self.run_cli(["--vault-root", directory, "suggest-layout"])
            outline_path = root / ".pi-vault" / "layout-suggestion.yaml"
            self.assertEqual(suggest_code, 0)
            self.assertTrue(outline_path.is_file())

            apply_code, _ = self.run_cli(["--vault-root", directory, "apply-layout"])
            bootstrap = yaml.safe_load(
                (root / ".pi-vault" / "config.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(apply_code, 0)
            self.assertEqual(bootstrap["content_dirs"]["work"], "Projects")
            self.assertEqual(bootstrap["domain_folders"], {"cooking": "Cooking"})

            init_code, _ = self.run_cli(["--vault-root", directory, "init"])
            self.assertEqual(init_code, 0)
            self.assertTrue((root / "Projects").is_dir())
            self.assertTrue((root / "Cooking").is_dir())
            # Custom domain folder gets its own dashboard.
            self.assertTrue((root / "Cooking" / "Cooking.md").is_file())
            # No forced default work folder when the role was remapped.
            self.assertFalse((root / "04 Work").exists())

            # schema.json lists the custom domain as an allowed value.
            schema = json.loads(
                (root / "99 System" / "0.01 agent" / "schema.json").read_text(encoding="utf-8")
            )
            self.assertIn("cooking", schema["core_properties"]["domain"]["allowed"])

            # paths_for round-trips the custom domain folder.
            paths = paths_for(root)
            self.assertEqual(paths.domain_folders["cooking"].as_posix(), "Cooking")

            # A note with the custom domain routes INTO the custom folder.
            config = load_config(argparse.Namespace(vault_root=root))
            decision = route_note(
                config, root / "00 Inbox" / "soup.md", {"type": "note", "domain": "cooking"}
            )
            self.assertEqual(decision.destination_dir.as_posix(), "Cooking")

    def test_validation_accepts_custom_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Cooking").mkdir()
            (root / "Cooking" / "n.md").write_text("# n\n", encoding="utf-8")
            self.run_cli(["--vault-root", directory, "suggest-layout"])
            self.run_cli(["--vault-root", directory, "apply-layout"])
            self.run_cli(["--vault-root", directory, "init"])
            (root / "Cooking" / "soup.md").write_text(
                "---\ntype: note\ndomain: cooking\n---\n# Soup\n", encoding="utf-8"
            )
            self.run_cli(["--vault-root", directory, "scan"])
            config = load_config(argparse.Namespace(vault_root=root))
            _code, output = run_validate(config)
            self.assertNotIn("invalid domain `cooking`", output)

    def test_apply_layout_without_outline_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            code, output = self.run_cli(["--vault-root", directory, "apply-layout"])
            self.assertEqual(code, 1)
            self.assertIn("layout outline not found", output)


if __name__ == "__main__":
    unittest.main()
