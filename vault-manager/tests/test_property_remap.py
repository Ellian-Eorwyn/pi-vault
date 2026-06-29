"""Model-driven property remapping: extended aliases, response validation, and the
end-to-end proposal (record alias + realign notes)."""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import yaml

from vault_agent.config import load_config
from vault_agent.frontmatter import parse_note
from vault_agent.legacy import apply_legacy_mappings, mapped_property_for
from vault_agent.property_remap import (
    generate_property_remap_proposal,
    normalize_remap_response,
)
from vault_agent.review import Proposal, _validate_proposal, apply_proposal
from vault_agent.schema import default_schema


def _config(directory: str):
    return load_config(Namespace(vault_root=directory, config=None, dry_run=False, verbose=False))


def _write_schema(cfg, *, custom=("read_time",)) -> dict:
    schema = default_schema()
    for name in custom:
        schema["core_properties"][name] = {"type": "string", "required": False}
        schema["property_definitions"][name] = f"{name} field."
    schema["common_properties"] = schema["core_properties"]
    agent_dir = cfg.vault_root / cfg.paths.agent_dir
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    return schema


class StubProvider:
    def __init__(self, mappings):
        self.mappings = mappings

    def propose_property_remap(self, *, prompt):
        del prompt
        return {"mappings": dict(self.mappings), "confidence": 0.95, "warnings": []}


class AliasTargetTests(unittest.TestCase):
    def test_alias_can_target_custom_property(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg)
            cfg = dataclasses.replace(
                cfg, legacy_property_aliases={"reading_minutes": "read_time", "area": "domain"}
            )
            out = apply_legacy_mappings({"reading_minutes": "7 min", "area": "work"}, cfg)
            self.assertEqual(out["read_time"], "7 min")  # custom target, copied as-is
            self.assertEqual(out["domain"], "work")  # core target, normalized
            self.assertEqual(mapped_property_for("reading_minutes", cfg), "read_time")


class NormalizeTests(unittest.TestCase):
    def test_rejects_unapproved_and_accepts_drop(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            schema = _write_schema(cfg)
            raw = {
                "mappings": {
                    "reading_minutes": "read_time",   # approved custom
                    "junk": "not_a_property",         # unapproved -> ignored
                    "stale": "",                      # drop
                    "stray": "domain",                # not in unknown set -> ignored
                },
                "confidence": 0.9,
                "warnings": [],
            }
            mappings, conf, warnings = normalize_remap_response(
                raw, {"reading_minutes", "junk", "stale"}, schema
            )
            self.assertEqual(mappings, {"reading_minutes": "read_time", "stale": ""})
            self.assertTrue(any("not_a_property" in w for w in warnings))


class EndToEndTests(unittest.TestCase):
    def test_proposal_records_alias_and_fixes_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg)
            note = cfg.vault_root / "06 Thoughts" / "n.md"
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(
                "---\ntype: note\nstatus: active\ndomain: meta\nreading_minutes: 7 min\nbogus: x\n---\n# n\n",
                encoding="utf-8",
            )
            provider = StubProvider({"reading_minutes": "read_time", "bogus": ""})
            proposal, errors = generate_property_remap_proposal(cfg, proposal_provider=provider)
            self.assertEqual(errors, [])
            self.assertEqual(_validate_proposal(Proposal(Path("x"), proposal)), [])
            self.assertEqual(apply_proposal(cfg, Proposal(Path("x"), proposal)), [])

            fm = parse_note(note.read_text(encoding="utf-8")).frontmatter
            self.assertEqual(fm.get("read_time"), "7 min")
            self.assertNotIn("reading_minutes", fm)
            self.assertNotIn("bogus", fm)

            cfg_data = yaml.safe_load(
                (cfg.vault_root / cfg.paths.agent_dir / "config.yaml").read_text(encoding="utf-8")
            )
            aliases = cfg_data["legacy_metadata"]["property_aliases"]
            self.assertEqual(aliases.get("reading_minutes"), "read_time")
            self.assertNotIn("bogus", aliases)  # drops are not recorded as aliases

    def test_noop_when_nothing_unapproved(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _write_schema(cfg)
            note = cfg.vault_root / "06 Thoughts" / "n.md"
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text("---\ntype: note\nstatus: active\ndomain: meta\n---\n# n\n", encoding="utf-8")
            proposal, errors = generate_property_remap_proposal(
                cfg, proposal_provider=StubProvider({})
            )
            self.assertIsNone(proposal)
            self.assertTrue(any("no unapproved" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
