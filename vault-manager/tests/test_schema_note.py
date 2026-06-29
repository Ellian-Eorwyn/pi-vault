"""Tests for the canonical schema note: render/parse, sync, and detection."""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from vault_agent.config import load_config
from vault_agent.schema import default_schema, load_schema
from vault_agent.schema_note import (
    SCHEMA_NOTE_NAME,
    note_changed,
    parse_schema_note,
    render_schema_note,
    schema_note_path,
    sync_schema_from_note,
)
from vault_agent.starter_files import starter_file_contents


class RenderParseTests(unittest.TestCase):
    def test_round_trip_preserves_definitions(self):
        parsed = parse_schema_note(render_schema_note(default_schema()))
        self.assertEqual(parsed["domain"]["work"], "Employment, consulting, professional projects.")
        self.assertEqual(parsed["source_kind"]["book"], "A book or monograph, printed or ebook.")
        self.assertTrue(parsed["note_type"]["project"].startswith("Temporary effort"))
        self.assertEqual(len(parsed["domain"]), 12)

    def test_separator_tolerance_and_prose(self):
        text = (
            "## Domains\n"
            "- work: Employment\n"
            "- academic - Research\n"
            "* craft — Making\n"
            "- finance:Money\n"
            "- `health` — Wellbeing\n"
            "random prose that should be ignored\n"
        )
        parsed = parse_schema_note(text)
        self.assertEqual(
            parsed["domain"],
            {"work": "Employment", "academic": "Research", "craft": "Making",
             "finance": "Money", "health": "Wellbeing"},
        )

    def test_properties_section_round_trip(self):
        parsed = parse_schema_note(render_schema_note(default_schema()))
        self.assertIn("type", parsed["properties"])
        self.assertNotIn("summary", parsed["properties"])  # not a default property
        # `related` is list-typed; its marker round-trips
        self.assertEqual(parsed["properties"]["related"][0], "list")
        self.assertEqual(parsed["properties"]["type"][0], "string")
        self.assertTrue(parsed["properties"]["domain"][1].startswith("Broad area"))

    def test_properties_list_marker_parsing(self):
        text = (
            "## Properties\n"
            "- summary — Bases preview\n"
            "- tags (list) — Free-form tags\n"
            "- aliases (array) — Alternate names\n"
        )
        parsed = parse_schema_note(text)
        self.assertEqual(parsed["properties"]["summary"], ("string", "Bases preview"))
        self.assertEqual(parsed["properties"]["tags"], ("list", "Free-form tags"))
        self.assertEqual(parsed["properties"]["aliases"], ("list", "Alternate names"))

    def test_topic_hubs_parse_per_domain(self):
        text = "## Topic hubs\n### work\n- Career — career stuff\n- Projects\n### health\n- Fitness — exercise\n"
        parsed = parse_schema_note(text)
        self.assertEqual(parsed["topic_hubs"]["work"], [("Career", "career stuff"), ("Projects", "")])
        self.assertEqual(parsed["topic_hubs"]["health"], [("Fitness", "exercise")])


class InitWritesNoteTests(unittest.TestCase):
    def test_starter_files_include_canonical_note(self):
        files = starter_file_contents()
        key = f"99 System/{SCHEMA_NOTE_NAME}"
        self.assertIn(key, files)
        self.assertIn("# Vault Schema", files[key])
        self.assertIn("## Domains", files[key])


class SyncTests(unittest.TestCase):
    def _config(self, directory):
        return load_config(Namespace(vault_root=directory, config=None, dry_run=False, verbose=False))

    def _setup(self, root: Path):
        cfg = self._config(str(root))
        (root / cfg.paths.agent_dir).mkdir(parents=True, exist_ok=True)
        (root / cfg.paths.agent_dir / "schema.json").write_text(
            json.dumps(default_schema()), encoding="utf-8"
        )
        note = schema_note_path(cfg)
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(render_schema_note(default_schema()), encoding="utf-8")
        return cfg, note

    def test_unchanged_is_noop_after_first_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg, _ = self._setup(Path(directory))
            sync_schema_from_note(cfg)
            self.assertFalse(note_changed(cfg))
            result = sync_schema_from_note(cfg)
            self.assertEqual(result.summary, "schema note unchanged")
            self.assertFalse(result.changed)

    def test_add_and_edit_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg, note = self._setup(Path(directory))
            sync_schema_from_note(cfg)
            text = note.read_text(encoding="utf-8").replace(
                "## Domains\n", "## Domains\n- robotics — Robots and automation\n"
            ).replace(
                "- work — Employment, consulting, professional projects.",
                "- work — Paid professional work",
            )
            note.write_text(text, encoding="utf-8")
            self.assertTrue(note_changed(cfg))
            result = sync_schema_from_note(cfg)
            self.assertTrue(result.changed)
            self.assertIn("robotics", result.added["domain"])
            self.assertIn("work", result.edited["domain"])
            schema = load_schema(cfg.vault_root)
            self.assertEqual(schema["domain_definitions"]["robotics"], "Robots and automation")
            self.assertEqual(schema["domain_definitions"]["work"], "Paid professional work")
            self.assertIn("robotics", schema["core_properties"]["domain"]["allowed"])

    def test_in_use_removal_blocked_unused_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg, note = self._setup(root)
            sync_schema_from_note(cfg)
            # a note that uses domain `travel` -> its removal must be blocked
            (root / "Trip.md").write_text(
                "---\ntype: note\ndomain: travel\n---\n# Trip\n", encoding="utf-8"
            )
            # remove both `travel` (in use) and `household` (unused) lines
            text = "\n".join(
                line for line in note.read_text(encoding="utf-8").splitlines()
                if not line.startswith("- travel ") and not line.startswith("- household ")
            ) + "\n"
            note.write_text(text, encoding="utf-8")
            result = sync_schema_from_note(cfg)
            self.assertIn("travel", result.blocked["domain"])
            self.assertIn("household", result.removed["domain"])
            schema = load_schema(cfg.vault_root)
            allowed = schema["core_properties"]["domain"]["allowed"]
            self.assertIn("travel", allowed)        # kept (in use)
            self.assertNotIn("household", allowed)   # removed (unused)

    def test_add_property_applies_to_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg, note = self._setup(Path(directory))
            sync_schema_from_note(cfg)
            text = note.read_text(encoding="utf-8").replace(
                "## Properties\n",
                "## Properties\n- summary — One-line preview for Bases\n- tags (list) — Free-form tags\n",
            )
            note.write_text(text, encoding="utf-8")
            result = sync_schema_from_note(cfg)
            self.assertTrue(result.changed)
            self.assertIn("summary", result.added["properties"])
            self.assertIn("tags", result.added["properties"])
            schema = load_schema(cfg.vault_root)
            self.assertEqual(schema["core_properties"]["summary"]["type"], "string")
            self.assertEqual(schema["core_properties"]["tags"]["type"], "list")
            self.assertEqual(schema["property_definitions"]["summary"], "One-line preview for Bases")

    def test_builtin_property_never_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg, note = self._setup(Path(directory))
            sync_schema_from_note(cfg)
            # drop the `cover` line entirely from the Properties section
            text = "\n".join(
                line for line in note.read_text(encoding="utf-8").splitlines()
                if not line.startswith("- cover ")
            ) + "\n"
            note.write_text(text, encoding="utf-8")
            result = sync_schema_from_note(cfg)
            self.assertNotIn("cover", result.removed.get("properties", []))
            self.assertIn("cover", load_schema(cfg.vault_root)["core_properties"])

    def test_custom_property_removal_blocked_when_in_use(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg, note = self._setup(root)
            # add two custom properties
            text = note.read_text(encoding="utf-8").replace(
                "## Properties\n",
                "## Properties\n- summary — preview\n- legacyprop — old field\n",
            )
            note.write_text(text, encoding="utf-8")
            sync_schema_from_note(cfg)
            # a note still uses `legacyprop`
            (root / "Old.md").write_text(
                "---\ntype: note\nlegacyprop: x\n---\n# Old\n", encoding="utf-8"
            )
            # now remove both custom property lines
            text = "\n".join(
                line for line in note.read_text(encoding="utf-8").splitlines()
                if not line.startswith("- summary ") and not line.startswith("- legacyprop ")
            ) + "\n"
            note.write_text(text, encoding="utf-8")
            result = sync_schema_from_note(cfg)
            self.assertIn("legacyprop", result.blocked["properties"])  # in use -> kept
            self.assertIn("summary", result.removed["properties"])      # unused -> removed
            schema = load_schema(cfg.vault_root)
            self.assertIn("legacyprop", schema["core_properties"])
            self.assertNotIn("summary", schema["core_properties"])

    def test_missing_note_is_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._config(directory)
            result = sync_schema_from_note(cfg)
            self.assertTrue(result.note_missing)
            self.assertFalse(result.changed)


if __name__ == "__main__":
    unittest.main()
