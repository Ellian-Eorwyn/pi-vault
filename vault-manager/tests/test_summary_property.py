"""When the vault declares `summary` as a frontmatter property, the summary stage
writes it to frontmatter (for Bases previews) instead of the note body."""

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


class SummaryProvider:
    def propose_stage(self, *, note_path, note_text, stage):
        del note_path, note_text, stage
        return {"summary": "A crisp one-line preview.", "confidence": 0.9, "warnings": []}


def _config(directory: str):
    return load_config(Namespace(vault_root=directory, config=None, dry_run=False, verbose=False))


def _write_schema(cfg, *, with_summary_property: bool) -> None:
    schema = default_schema()
    if with_summary_property:
        schema["core_properties"]["summary"] = {"type": "string", "required": False}
        schema["common_properties"] = schema["core_properties"]
        schema["property_definitions"]["summary"] = "One-line preview for Bases."
    agent_dir = cfg.vault_root / cfg.paths.agent_dir
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")


NOTE = "---\ntype: note\nstatus: active\ndomain: meta\n---\n\n# A note\n\nBody text.\n"


class SummaryPropertyRoutingTests(unittest.TestCase):
    def test_summary_written_to_frontmatter_when_declared(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg, with_summary_property=True)
            note_path = cfg.vault_root / "06 Thoughts" / "note.md"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(NOTE, encoding="utf-8")

            result = process_note(
                cfg.vault_root, note_path, proposal_provider=SummaryProvider(), stage="summary"
            )
            self.assertTrue(result.changed)
            parsed = parse_note(note_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed.frontmatter.get("summary"), "A crisp one-line preview.")
            self.assertNotIn("## Summary", parsed.body)

    def test_summary_written_to_body_when_not_declared(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg, with_summary_property=False)
            note_path = cfg.vault_root / "06 Thoughts" / "note.md"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(NOTE, encoding="utf-8")

            result = process_note(
                cfg.vault_root, note_path, proposal_provider=SummaryProvider(), stage="summary"
            )
            self.assertTrue(result.changed)
            parsed = parse_note(note_path.read_text(encoding="utf-8"))
            self.assertNotIn("summary", parsed.frontmatter)
            self.assertIn("## Summary", parsed.body)


if __name__ == "__main__":
    unittest.main()
