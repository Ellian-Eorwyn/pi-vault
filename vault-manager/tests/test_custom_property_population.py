"""The property-values stage fills user-declared custom properties when the model
returns them (e.g. a free-text field or a list field added via the schema note)."""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from vault_agent.config import load_config
from vault_agent.frontmatter import parse_note
from vault_agent.processor import process_note
from vault_agent.schema import default_schema


class PropertyValuesProvider:
    """Returns a property-values proposal including custom keys."""

    def __init__(self, payload):
        self.payload = payload

    def propose_stage(self, *, note_path, note_text, stage):
        del note_path, note_text
        assert stage == "property-values"
        return dict(self.payload)


def _config(directory: str):
    return load_config(Namespace(vault_root=directory, config=None, dry_run=False, verbose=False))


def _write_schema(cfg) -> None:
    schema = default_schema()
    schema["core_properties"]["reading_time"] = {"type": "string", "required": False}
    schema["core_properties"]["topics"] = {"type": "list", "required": False}
    schema["common_properties"] = schema["core_properties"]
    schema["property_definitions"]["reading_time"] = "Estimated minutes to read."
    schema["property_definitions"]["topics"] = "Salient topics."
    agent_dir = cfg.vault_root / cfg.paths.agent_dir
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")


NOTE = "---\ntype: note\n---\n\n# A note\n\nBody.\n"


class CustomPropertyPopulationTests(unittest.TestCase):
    def test_property_values_stage_fills_custom_properties(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg)
            note_path = cfg.vault_root / "06 Thoughts" / "n.md"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(NOTE, encoding="utf-8")

            provider = PropertyValuesProvider(
                {
                    "status": "active",
                    "domain": "meta",
                    "source_kind": "",
                    "parent": "",
                    "related": [],
                    "cover": "",
                    "capture_type": "",
                    "reading_time": "about 7 minutes",
                    "topics": ["alpha", "beta"],
                    "confidence": 0.95,
                    "warnings": [],
                }
            )
            result = process_note(
                cfg.vault_root, note_path, proposal_provider=provider, stage="property-values"
            )
            self.assertTrue(result.changed, msg=getattr(result, "errors", None))
            parsed = parse_note(note_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed.frontmatter.get("reading_time"), "about 7 minutes")
            self.assertEqual(parsed.frontmatter.get("topics"), ["alpha", "beta"])

    def test_property_values_rejects_unknown_key(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg)
            note_path = cfg.vault_root / "06 Thoughts" / "n.md"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(NOTE, encoding="utf-8")

            provider = PropertyValuesProvider(
                {
                    "status": "active",
                    "domain": "meta",
                    "source_kind": "",
                    "parent": "",
                    "related": [],
                    "cover": "",
                    "capture_type": "",
                    "not_a_real_prop": "x",
                    "confidence": 0.95,
                    "warnings": [],
                }
            )
            result = process_note(
                cfg.vault_root, note_path, proposal_provider=provider, stage="property-values"
            )
            self.assertFalse(result.changed)
            self.assertTrue(any("not_a_real_prop" in e for e in result.errors))


if __name__ == "__main__":
    unittest.main()
