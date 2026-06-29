"""Reprocessing gate: a note carrying a value or property outside the approved
schema is re-triggered for realignment, while a fully-aligned note converges
(never loops)."""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import yaml

from vault_agent.config import load_config
from vault_agent.processing_state import mark_stage
from vault_agent.processor import PROCESSING_STAGES, _stage_needed
from vault_agent.schema import default_schema

FULL = {
    "type": "note",
    "status": "active",
    "domain": "meta",
    "parent": "[[X]]",
    "related": ["[[Y]]"],
    "cover": "c.png",
    "source_kind": "book",
    "capture_type": "manual",
    "summary": "s",
}


def _config(directory: str):
    return load_config(Namespace(vault_root=directory, config=None, dry_run=False, verbose=False))


def _write_schema(cfg, *, preserve=True) -> None:
    schema = default_schema()
    schema["core_properties"]["summary"] = {"type": "string", "required": False}
    schema["common_properties"] = schema["core_properties"]
    schema["property_definitions"]["summary"] = "Preview."
    agent_dir = cfg.vault_root / cfg.paths.agent_dir
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    if not preserve:
        cfg_path = agent_dir / "config.yaml"
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        data = data or {}
        data.setdefault("legacy_metadata", {})["preserve_unknown_properties"] = False
        cfg_path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _completed_note(cfg, name: str, frontmatter: dict) -> tuple[Path, dict]:
    note_path = cfg.vault_root / "Notes" / f"{name}.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n# t\n", encoding="utf-8")
    for stage in PROCESSING_STAGES:
        mark_stage(cfg.vault_root, note_path, stage=stage, status="complete")
    return note_path, {"path": note_path.relative_to(cfg.vault_root).as_posix(), "frontmatter": frontmatter}


def _needed(cfg, note_path, entry):
    return [s for s in PROCESSING_STAGES if _stage_needed(cfg.vault_root, note_path, entry, s)]


class RealignGateTests(unittest.TestCase):
    def test_fully_aligned_completed_note_needs_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg)
            path, entry = _completed_note(cfg, "ok", dict(FULL))
            self.assertEqual(_needed(cfg, path, entry), [])

    def test_unapproved_value_retriggers_property_values(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg)
            path, entry = _completed_note(cfg, "baddomain", {**FULL, "domain": "madeupdomain"})
            self.assertIn("property-values", _needed(cfg, path, entry))

    def test_unapproved_type_retriggers_classify_type(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg)
            path, entry = _completed_note(cfg, "badtype", {**FULL, "type": "notarealtype"})
            self.assertIn("classify-type", _needed(cfg, path, entry))

    def test_approved_custom_property_does_not_flag_frontmatter_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg)  # summary is declared/approved
            path, entry = _completed_note(cfg, "summ", dict(FULL))
            self.assertNotIn("frontmatter-shape", _needed(cfg, path, entry))

    def test_unapproved_property_kept_when_preserving(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg, preserve=True)
            path, entry = _completed_note(cfg, "bogus", {**FULL, "bogusprop": "x"})
            self.assertNotIn("frontmatter-shape", _needed(cfg, path, entry))

    def test_unapproved_property_stripped_when_not_preserving(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg, preserve=False)
            path, entry = _completed_note(cfg, "bogus", {**FULL, "bogusprop": "x"})
            self.assertIn("frontmatter-shape", _needed(cfg, path, entry))


if __name__ == "__main__":
    unittest.main()
