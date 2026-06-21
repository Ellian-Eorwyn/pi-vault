import contextlib
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from vault_agent.cli import main
from vault_agent.config import load_config
from vault_agent.llm import validate_stage_proposal
from vault_agent.norms import current_lock_hash, run_norms_lock
from vault_agent.processor import process_note
from vault_agent.schema import (
    all_hub_names,
    approved_hubs_for,
    default_schema,
    topic_hubs_markdown,
)
from vault_agent.topic_hubs import (
    build_topic_hubs_proposal,
    candidate_hub_for_path,
    cluster_candidate_hubs,
    folder_hub_match,
)


def _entry(path, domain="personal", note_type="note"):
    return {"path": path, "domain": domain, "type": note_type, "frontmatter": {}}


class TopicHubTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_registry_accessors(self):
        schema = default_schema()
        self.assertEqual(approved_hubs_for("personal", schema), [])
        schema["topic_hubs"]["personal"] = [{"name": "Therapy"}, {"name": "Journaling"}]
        self.assertEqual(approved_hubs_for("personal", schema), ["Therapy", "Journaling"])
        self.assertEqual(all_hub_names(schema), {"Therapy", "Journaling"})

    def test_candidate_and_match(self):
        self.assertEqual(
            candidate_hub_for_path("02 Journal/2.02 Therapy/2025-01-01 Therapy.md"), "Therapy"
        )
        self.assertEqual(candidate_hub_for_path("06 People/Jane.md"), "People")
        self.assertEqual(
            folder_hub_match("02 Journal/2.02 Therapy/x.md", ["Therapy", "Journaling"]), "Therapy"
        )
        self.assertEqual(folder_hub_match("99 Misc/x.md", ["Therapy"]), "")

    def test_cluster_candidate_hubs_threshold(self):
        entries = [
            _entry("02 Journal/2.02 Therapy/a.md"),
            _entry("02 Journal/2.02 Therapy/b.md"),
            _entry("02 Journal/2.02 Therapy/c.md"),
            _entry("02 Journal/2.03 Journaling/d.md"),
        ]
        hubs = cluster_candidate_hubs(entries, "personal", min_cluster=3)
        names = [hub["name"] for hub in hubs]
        self.assertIn("Therapy", names)
        self.assertNotIn("Journaling", names)  # only 1 note, below threshold

    def test_build_proposal_registers_hubs(self):
        entries = [_entry(f"02 Journal/2.02 Therapy/{i}.md") for i in range(4)]
        proposal, registry, added = build_topic_hubs_proposal(
            entries=entries, schema=default_schema(), domains=["personal"], min_cluster=3
        )
        self.assertEqual(proposal["kind"], "schema-change")
        self.assertEqual(approved_hubs_for("personal", {"topic_hubs": registry}), ["Therapy"])
        self.assertTrue(any("Therapy" in label for label in added))
        # schema.json + topic hubs md + one hub note
        paths = [op["path"] for op in proposal["operations"]]
        self.assertIn("00 System/0.01 agent/schema.json", paths)
        self.assertTrue(any(p.endswith("Therapy.md") for p in paths))

    def test_assign_hub_validator_gates_on_registry(self):
        ok = validate_stage_proposal(
            "assign-hub", {"parent": "Therapy", "confidence": 0.9, "warnings": []},
            allowed_hubs=["Therapy", "Journaling"],
        )
        self.assertTrue(ok.valid)
        self.assertEqual(ok.proposal["parent"], "[[Therapy]]")
        bad = validate_stage_proposal(
            "assign-hub", {"parent": "Gardening", "confidence": 0.9, "warnings": []},
            allowed_hubs=["Therapy"],
        )
        self.assertFalse(bad.valid)
        self.assertTrue(any("not an approved hub" in e for e in bad.errors))

    def test_assign_hub_stage_deterministic_folder_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_cli(["--vault-root", directory, "init"])
            schema_path = root / "00 System" / "0.01 agent" / "schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema.setdefault("topic_hubs", {}).setdefault("personal", []).append(
                {"name": "Therapy", "description": "x"}
            )
            schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
            cfg = load_config(
                Namespace(vault_root=directory, config=None, dry_run=False, verbose=False)
            )
            run_norms_lock(cfg, write=True)
            note = root / "02 Journal" / "2.02 Therapy" / "2025-01-01 Therapy.md"
            note.parent.mkdir(parents=True)
            note.write_text(
                "---\ntype: note\nstatus: active\ndomain: personal\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Session\n",
                encoding="utf-8",
            )
            result = process_note(
                root, note, stage="assign-hub", norms_lock_hash=current_lock_hash(root)
            )
            text = note.read_text(encoding="utf-8")

        self.assertEqual(result.mode, "hub-assigned")
        self.assertIn('parent: "[[Therapy]]"', text)

    def test_topic_hubs_markdown_lists_registry(self):
        md = topic_hubs_markdown({"personal": [{"name": "Therapy", "description": "d"}]})
        self.assertIn("## personal", md)
        self.assertIn("`Therapy`", md)


if __name__ == "__main__":
    unittest.main()
