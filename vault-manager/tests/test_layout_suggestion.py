import argparse
import contextlib
import io
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
        self.assertEqual(suggestion.extra_folders, [])

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
        # Children are rebuilt under the remapped parent.
        self.assertEqual(suggestion.content_dirs["contacts"].as_posix(), "Misc/02.01 Contacts")

    def test_unmatched_folder_becomes_extra(self):
        scan = ScanResult(
            entries=[_entry("Recipes/pasta.md")],
            folders=["Recipes"],
        )
        suggestion = suggest_layout(scan, DEFAULT_PATHS)
        self.assertEqual([f.as_posix() for f in suggestion.extra_folders], ["Recipes"])
        # Roles keep their defaults when nothing matches.
        self.assertEqual(suggestion.content_dirs["sources"].as_posix(), "07 Sources")

    def test_contested_role_keeps_busiest_and_demotes_rest_to_extra(self):
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
        self.assertEqual([f.as_posix() for f in suggestion.extra_folders], ["Library"])

    def test_outline_round_trip(self):
        scan = ScanResult(
            entries=[
                _entry("Projects/p.md", type="project", domain="work"),
                _entry("Recipes/r.md"),
            ],
            folders=["Projects", "Recipes"],
        )
        suggestion = suggest_layout(scan, DEFAULT_PATHS)
        outline = render_layout_outline(suggestion)
        paths = parse_layout_outline(outline)
        self.assertEqual(paths.content_dirs["work"].as_posix(), "Projects")
        self.assertEqual([f.as_posix() for f in paths.extra_folders], ["Recipes"])

    def test_parse_rejects_extra_folder_nested_in_content_dir(self):
        outline = (
            "system_dir: 99 System\n"
            "inbox_dir: 00 Inbox\n"
            "dashboards_dir: 01 Dashboards\n"
            "extra_folders:\n"
            "  - 02 People/Sub\n"
        )
        with self.assertRaises(ValueError):
            parse_layout_outline(outline)


class ExtraFoldersPathTests(unittest.TestCase):
    def test_build_paths_round_trips_extra_folders(self):
        paths = build_paths(
            "99 System", "00 Inbox", "01 Dashboards", None, ["Recipes", "Garden"]
        )
        self.assertEqual([f.as_posix() for f in paths.extra_folders], ["Recipes", "Garden"])

    def test_build_paths_rejects_duplicate_extra_folders(self):
        with self.assertRaises(ValueError):
            build_paths("99 System", "00 Inbox", "01 Dashboards", None, ["Recipes", "Recipes"])


class LayoutCliTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_suggest_apply_init_flow_creates_custom_and_extra_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Projects").mkdir()
            (root / "Projects" / "p.md").write_text(
                "---\ntype: project\ndomain: work\n---\n# P\n", encoding="utf-8"
            )
            (root / "Recipes").mkdir()
            (root / "Recipes" / "pasta.md").write_text("# Pasta\n", encoding="utf-8")

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
            self.assertEqual(bootstrap["extra_folders"], ["Recipes"])

            init_code, _ = self.run_cli(["--vault-root", directory, "init"])
            self.assertEqual(init_code, 0)
            self.assertTrue((root / "Projects").is_dir())
            self.assertTrue((root / "Recipes").is_dir())
            # No forced default work folder when the role was remapped.
            self.assertFalse((root / "04 Work").exists())

            # paths_for round-trips the unmanaged folder.
            paths = paths_for(root)
            self.assertEqual([f.as_posix() for f in paths.extra_folders], ["Recipes"])

            # Routing never targets an unmanaged extra folder.
            config = load_config(argparse.Namespace(vault_root=root))
            decision = route_note(
                config, root / "note.md", {"type": "note", "domain": "work"}
            )
            destination = decision.destination_dir
            if destination is not None:
                self.assertNotEqual(destination.parts[0], "Recipes")

    def test_apply_layout_without_outline_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            code, output = self.run_cli(["--vault-root", directory, "apply-layout"])
            self.assertEqual(code, 1)
            self.assertIn("layout outline not found", output)


if __name__ == "__main__":
    unittest.main()
