"""Dashboard-request table: render/parse, candidate refresh (with check preservation),
sync into schema.json, and building the checked dashboards."""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from vault_agent.config import load_config
from vault_agent.dashboard_table import candidate_rows, refresh_dashboard_table
from vault_agent.proposals import generate_requested_dashboards_proposal
from vault_agent.review import Proposal, _validate_proposal, apply_proposal
from vault_agent.schema import default_schema
from vault_agent.schema_note import (
    parse_dashboard_requests,
    render_dashboard_table,
    render_schema_note,
    schema_note_path,
    sync_schema_from_note,
)


def _config(directory: str):
    return load_config(Namespace(vault_root=directory, config=None, dry_run=False, verbose=False))


def _init(cfg) -> None:
    agent_dir = cfg.vault_root / cfg.paths.agent_dir
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "schema.json").write_text(json.dumps(default_schema()), encoding="utf-8")
    note = schema_note_path(cfg)
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(render_schema_note(default_schema()), encoding="utf-8")


def _add_notes(cfg) -> None:
    work = cfg.vault_root / "Work"
    work.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (work / f"w{i}.md").write_text(
            '---\ntype: note\nstatus: active\ndomain: work\nparent: "[[Heat Pump Repair]]"\n---\n# w\n',
            encoding="utf-8",
        )
    (work / "lonely.md").write_text(
        "---\ntype: note\nstatus: active\ndomain: travel\n---\n# l\n", encoding="utf-8"
    )


class RenderParseTests(unittest.TestCase):
    def test_table_round_trip(self):
        rows = [
            {"property": "domain", "value": "work", "count": 3, "enabled": True},
            {"property": "type", "value": "source", "count": 2, "enabled": False},
        ]
        table = "\n".join(render_dashboard_table(rows))
        self.assertEqual(parse_dashboard_requests(table), [{"property": "domain", "value": "work"}])


class CandidateTests(unittest.TestCase):
    def test_counts_and_min_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _init(cfg)
            _add_notes(cfg)
            rows = candidate_rows(cfg, min_count=2)
            keys = {(r["property"], r["value"]): r["count"] for r in rows}
            self.assertEqual(keys.get(("domain", "work")), 3)
            self.assertEqual(keys.get(("parent", "Heat Pump Repair")), 3)
            self.assertNotIn(("domain", "travel"), keys)  # below min_count

    def test_checked_below_threshold_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _init(cfg)
            _add_notes(cfg)
            rows = candidate_rows(cfg, min_count=2, keep={("domain", "travel")})
            self.assertIn(("domain", "travel"), {(r["property"], r["value"]) for r in rows})


class RefreshTests(unittest.TestCase):
    def test_refresh_populates_and_preserves_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _init(cfg)
            _add_notes(cfg)
            note = schema_note_path(cfg)

            self.assertTrue(refresh_dashboard_table(cfg).changed)
            text = note.read_text(encoding="utf-8")
            self.assertIn("| domain | work | 3 |", text.replace("  ", " "))

            # user checks the work row
            note.write_text(
                text.replace("|   | domain | work | 3 |", "| x | domain | work | 3 |"),
                encoding="utf-8",
            )
            # refresh again -> check preserved
            refresh_dashboard_table(cfg)
            self.assertIn(
                {"property": "domain", "value": "work"},
                parse_dashboard_requests(note.read_text(encoding="utf-8")),
            )


class SyncAndBuildTests(unittest.TestCase):
    def test_sync_records_requests_and_build_creates_dashboards(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = _config(directory)
            _init(cfg)
            _add_notes(cfg)
            note = schema_note_path(cfg)
            refresh_dashboard_table(cfg)
            text = note.read_text(encoding="utf-8")
            text = text.replace("|   | domain | work | 3 |", "| x | domain | work | 3 |")
            text = text.replace(
                "|   | parent | Heat Pump Repair | 3 |", "| x | parent | Heat Pump Repair | 3 |"
            )
            note.write_text(text, encoding="utf-8")

            sync_schema_from_note(cfg)
            schema = json.loads(
                (cfg.vault_root / cfg.paths.agent_dir / "schema.json").read_text(encoding="utf-8")
            )
            requests = {(r["property"], r["value"]) for r in schema["dashboard_requests"]}
            self.assertEqual(requests, {("domain", "work"), ("parent", "Heat Pump Repair")})

            proposal, errors = generate_requested_dashboards_proposal(cfg)
            self.assertEqual(errors, [])
            self.assertEqual(len(proposal["operations"]), 2)
            self.assertEqual(_validate_proposal(Proposal(Path("x"), proposal)), [])
            self.assertEqual(apply_proposal(cfg, Proposal(Path("x"), proposal)), [])

            parent_dash = (
                cfg.vault_root
                / cfg.paths.dashboards_dir
                / "Requested"
                / "parent-heat-pump-repair.md"
            )
            self.assertTrue(parent_dash.exists())
            content = parent_dash.read_text(encoding="utf-8")
            self.assertIn('parent == "[[Heat Pump Repair]]" or parent == "Heat Pump Repair"', content)


if __name__ == "__main__":
    unittest.main()
