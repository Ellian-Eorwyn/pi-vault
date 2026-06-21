import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from vault_agent.action_queue import (
    build_action_plan,
    extract_person_names,
    generate_action_queue_proposal,
    normalize_person_name,
    transcript_score,
)
from vault_agent.cli import main
from vault_agent.config import load_config
from vault_agent.llm import _parse_json_object


class SummaryProvider:
    def __init__(self):
        self.calls = 0

    def propose_stage(self, *, note_path, note_text, stage):
        del note_path, note_text
        self.calls += 1
        self.stage = stage
        return {
            "summary": "LLM-produced transcript summary.",
            "confidence": 0.9,
            "warnings": [],
        }


class CategorizationProvider:
    def __init__(self):
        self.calls = 0

    def propose(self, *, note_path, note_text):
        del note_path
        self.calls += 1
        self.note_text = note_text
        return {
            "note_type": "source",
            "status": "active",
            "domain": "technology",
            "source_kind": "article",
            "parent": "[[AI]]",
            "related": ["[[LLMs]]"],
            "cover": "",
            "summary": "Article about LLM infrastructure.",
            "capture_type": "imported",
            "confidence": 0.92,
            "warnings": [],
        }


class StagedCategorizationProvider:
    def __init__(self):
        self.propose_calls = 0
        self.stage_calls = []

    def propose(self, *, note_path, note_text):
        del note_path, note_text
        self.propose_calls += 1
        raise ValueError("LLM response did not contain a JSON object")

    def propose_stage(self, *, note_path, note_text, stage):
        del note_path
        self.stage_calls.append((stage, note_text))
        if stage == "classify-type":
            return {
                "note_type": "source",
                "confidence": 0.88,
                "warnings": [],
            }
        if stage == "property-values":
            return {
                "status": "active",
                "domain": "technology",
                "source_kind": "article",
                "parent": "[[AI]]",
                "related": ["[[LLMs]]"],
                "cover": "",
                "capture_type": "imported",
                "confidence": 0.86,
                "warnings": [],
            }
        if stage == "summary":
            return {
                "summary": "Article about LLM infrastructure.",
                "confidence": 0.9,
                "warnings": [],
            }
        raise AssertionError(f"unexpected stage {stage}")


class ActionQueueTests(unittest.TestCase):
    def run_cli(self, args):
        import contextlib
        import io

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_transcript_score_flags_speaker_filler_and_low_structure(self):
        text = (
            "# Raw Call\n\n"
            "Alice: Um I was thinking, like, we should review the plan.\n\n"
            "Bob: Uh yeah, I mean, you know, that makes sense.\n\n"
            "Alice: Like there were several things we said about the timeline.\n"
            + "I remember we were going back and forth about the decision. " * 12
        )

        score = transcript_score(text)

        self.assertGreaterEqual(score.score, 4)
        self.assertIn("speaker-label lines", " ".join(score.reasons))
        self.assertIn("filler-word density", " ".join(score.reasons))

    def test_person_name_extraction_and_normalization(self):
        names = extract_person_names(
            "Met with Alice Smith and [[Bob Jones]]. The Action Queue was unrelated."
        )

        self.assertIn("Alice Smith", names)
        self.assertIn("Bob Jones", names)
        self.assertNotIn("Action Queue", names)
        self.assertEqual(normalize_person_name("Alice B. Smith"), "alicebsmith")

    def test_person_candidates_distinguish_referenced_people_from_direct_contacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Thinkers.md").write_text(
                "---\ntype: note\nstatus: active\ndomain: philosophy\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Thinkers\n\n- **Key thinkers**, Donna Haraway, Bruno Latour.\n",
                encoding="utf-8",
            )
            (root / "Meeting.md").write_text(
                "---\ntype: meeting\nstatus: active\ndomain: work\nparent: \"[[Work]]\"\nrelated: []\ncover:\nsource_kind:\ncapture_type: meeting\n---\n"
                "# Meeting\n\nMet with Alice Smith about the project.\n",
                encoding="utf-8",
            )
            config = load_config(
                Namespace(vault_root=directory, config=None, dry_run=True, verbose=False)
            )

            plan, errors = build_action_plan(config)
            by_name = {item["name"]: item for item in plan["person_candidates"]}

        self.assertEqual(errors, [])
        self.assertEqual(by_name["Donna Haraway"]["person_kind"], "referenced_person")
        self.assertEqual(by_name["Alice Smith"]["person_kind"], "direct_contact")
        self.assertEqual(plan["counts"]["person_candidate_kinds"]["referenced_person"], 2)
        self.assertEqual(plan["counts"]["person_candidate_kinds"]["direct_contact"], 1)

    def test_people_proposal_marks_referenced_people_separately_from_contacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Thinkers.md").write_text(
                "---\ntype: note\nstatus: active\ndomain: philosophy\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Thinkers\n\n- **Key thinkers**, Donna Haraway, Bruno Latour.\n",
                encoding="utf-8",
            )
            (root / "Meeting.md").write_text(
                "---\ntype: meeting\nstatus: active\ndomain: work\nparent: \"[[Work]]\"\nrelated: []\ncover:\nsource_kind:\ncapture_type: meeting\n---\n"
                "# Meeting\n\nMet with Alice Smith about the project.\n",
                encoding="utf-8",
            )
            config = load_config(
                Namespace(vault_root=directory, config=None, dry_run=True, verbose=False)
            )
            plan, errors = build_action_plan(config)

            proposal, proposal_errors = generate_action_queue_proposal(
                config,
                plan,
                ["people"],
            )
            contents = {
                operation["path"]: operation["content"]
                for operation in proposal["operations"]
                if operation["op"] == "write_file"
            }

        self.assertEqual(errors, [])
        self.assertEqual(proposal_errors, [])
        self.assertIn("Referenced thinker, author, scholar, or public figure", contents["People/Donna-Haraway.md"])
        self.assertIn("## Reference Context", contents["People/Donna-Haraway.md"])
        self.assertIn("- **Key thinkers**, Donna Haraway, Bruno Latour.", contents["People/Donna-Haraway.md"])
        self.assertNotIn("- - **Key thinkers**", contents["People/Donna-Haraway.md"])
        self.assertNotIn("## Contact Details", contents["People/Donna-Haraway.md"])
        self.assertIn("Direct contact or conversation participant", contents["People/Alice-Smith.md"])
        self.assertIn("## Contact Details", contents["People/Alice-Smith.md"])
        self.assertIn("## Direct Contacts", contents["People/INDEX.md"])
        self.assertIn("## Referenced People", contents["People/INDEX.md"])

    def test_parse_json_object_accepts_thinking_text_around_json(self):
        parsed = _parse_json_object('thinking first\n{"note_type": "note"}\ntrailing text')

        self.assertEqual(parsed, {"note_type": "note"})

    def test_action_plan_json_reports_available_queues(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Raw Call.md"
            note.write_text(
                "---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Raw Call\n\n"
                "Alice Smith: Um I was thinking, like, we should review this.\n\n"
                "Bob Jones: Uh yeah, I mean that makes sense.\n"
                + "I remember we were talking about the schedule. " * 14,
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "action-plan", "--json"]
            )
            payload = json.loads(output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["counts"]["notes"], 1)
        self.assertEqual(payload["counts"]["transcript_candidates"], 1)
        self.assertGreaterEqual(payload["counts"]["person_candidates"], 2)
        self.assertEqual(payload["counts"]["categorization_failures"], 1)
        self.assertEqual(payload["available_actions"][0]["action"], "transcript")

    def test_propose_action_queue_writes_pending_valid_proposal_without_note_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Raw Call.md"
            original = (
                "---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Raw Call\n\n"
                "Alice Smith: Um I was thinking, like, we should review this.\n\n"
                "Bob Jones: Uh yeah, I mean that makes sense.\n"
                + "I remember we were talking about the schedule. " * 14
            )
            note.write_text(original, encoding="utf-8")

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-action-queue",
                    "--actions",
                    "transcript,people,categorization",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "action-queue-transcript-people-categorization.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            review_exit, review_output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--dry-run"]
            )
            current_note = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("proposal complete", output)
        self.assertEqual(current_note, original)
        self.assertEqual(proposal["kind"], "action-queue")
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(review_exit, 0)
        self.assertIn("Validation: passed", review_output)

    def test_propose_action_queue_can_overwrite_existing_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Raw Call.md").write_text(
                "---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Raw Call\n\n"
                "Alice Smith: Um I was thinking, like, we should review this.\n\n"
                "Bob Jones: Uh yeah, I mean that makes sense.\n"
                + "I remember we were talking about the schedule. " * 14,
                encoding="utf-8",
            )
            args = [
                "--vault-root",
                directory,
                "propose-action-queue",
                "--actions",
                "transcript",
            ]

            first_exit, _first_output = self.run_cli(args)
            second_exit, second_output = self.run_cli(args)
            overwrite_exit, overwrite_output = self.run_cli(args + ["--overwrite-proposal"])

        self.assertEqual(first_exit, 0)
        self.assertEqual(second_exit, 1)
        self.assertIn("proposal already exists", second_output)
        self.assertEqual(overwrite_exit, 0)
        self.assertIn("proposal complete", overwrite_output)

    def test_transcript_proposal_uses_bounded_llm_summary_when_provider_supplied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Raw Call.md").write_text(
                "---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Raw Call\n\n"
                "Alice Smith: Um I was thinking, like, we should review this.\n\n"
                "Bob Jones: Uh yeah, I mean that makes sense.\n"
                + "I remember we were talking about the schedule. " * 14,
                encoding="utf-8",
            )
            config = load_config(
                Namespace(vault_root=directory, config=None, dry_run=True, verbose=False)
            )
            plan, errors = build_action_plan(config)
            provider = SummaryProvider()

            proposal, proposal_errors = generate_action_queue_proposal(
                config,
                plan,
                ["transcript"],
                proposal_provider=provider,
                llm_limit=1,
            )

        self.assertEqual(errors, [])
        self.assertEqual(proposal_errors, [])
        self.assertEqual(provider.calls, 1)
        self.assertIn("LLM-produced transcript summary.", proposal["operations"][0]["content"])

    def test_categorization_proposal_uses_llm_with_schema_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Article.md").write_text(
                "---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Scaling LLM Infrastructure\n\nThis imported article discusses GPUs and model serving.",
                encoding="utf-8",
            )
            config = load_config(
                Namespace(vault_root=directory, config=None, dry_run=True, verbose=False)
            )
            plan, errors = build_action_plan(config)
            provider = CategorizationProvider()

            proposal, proposal_errors = generate_action_queue_proposal(
                config,
                plan,
                ["categorization"],
                proposal_provider=provider,
                llm_limit=1,
                max_items=1,
            )

        self.assertEqual(errors, [])
        self.assertEqual(proposal_errors, [])
        self.assertEqual(provider.calls, 1)
        self.assertIn("Use only these note types and definitions", provider.note_text)
        self.assertEqual(proposal["operations"][0]["op"], "organize_note")
        self.assertEqual(proposal["operations"][0]["path"], "Article.md")
        self.assertEqual(proposal["operations"][0]["set"]["type"], "source")
        self.assertEqual(proposal["operations"][0]["summary"], "Article about LLM infrastructure.")

    def test_categorization_proposal_falls_back_to_serialized_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Article.md").write_text(
                "---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Scaling LLM Infrastructure\n\nThis imported article discusses GPUs and model serving.",
                encoding="utf-8",
            )
            config = load_config(
                Namespace(vault_root=directory, config=None, dry_run=True, verbose=False)
            )
            plan, errors = build_action_plan(config)
            provider = StagedCategorizationProvider()

            proposal, proposal_errors = generate_action_queue_proposal(
                config,
                plan,
                ["categorization"],
                proposal_provider=provider,
                llm_limit=1,
                max_items=1,
            )

        self.assertEqual(errors, [])
        self.assertEqual(proposal_errors, [])
        self.assertEqual(provider.propose_calls, 1)
        self.assertEqual(
            [stage for stage, _text in provider.stage_calls],
            ["classify-type", "property-values", "summary"],
        )
        self.assertTrue(
            all("Use only these note types and definitions" in text for _stage, text in provider.stage_calls)
        )
        self.assertEqual(proposal["operations"][0]["op"], "organize_note")
        self.assertEqual(proposal["operations"][0]["set"]["source_kind"], "article")
        self.assertEqual(proposal["operations"][0]["summary"], "Article about LLM infrastructure.")

    def test_categorization_proposal_records_llm_noop_as_unresolved(self):
        class NoopProvider:
            def propose(self, *, note_path, note_text):
                del note_path, note_text
                return {
                    "note_type": "project",
                    "status": "active",
                    "domain": "personal",
                    "source_kind": "",
                    "parent": "",
                    "related": [],
                    "cover": "",
                    "summary": "Personal project note.",
                    "capture_type": "",
                    "confidence": 0.9,
                    "warnings": [],
                }

            def propose_stage(self, *, note_path, note_text, stage):
                del note_path, note_text
                if stage == "classify-type":
                    return {"note_type": "project", "confidence": 0.9, "warnings": []}
                if stage == "property-values":
                    return {
                        "status": "active",
                        "domain": "personal",
                        "source_kind": "",
                        "parent": "",
                        "related": [],
                        "cover": "",
                        "capture_type": "",
                        "confidence": 0.9,
                        "warnings": [],
                    }
                return {"summary": "Personal project note.", "confidence": 0.9, "warnings": []}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Living Well.md").write_text(
                "---\ntype: project\nstatus: active\ndomain: personal\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Living Well\n\nA list of personal habits.",
                encoding="utf-8",
            )
            config = load_config(
                Namespace(vault_root=directory, config=None, dry_run=True, verbose=False)
            )
            plan, errors = build_action_plan(config)

            proposal, proposal_errors = generate_action_queue_proposal(
                config,
                plan,
                ["categorization"],
                proposal_provider=NoopProvider(),
                llm_limit=1,
                max_items=1,
            )

        self.assertEqual(errors, [])
        self.assertEqual(proposal_errors, [])
        self.assertEqual(proposal["operations"][0]["op"], "write_file")
        self.assertIn("project note has no parent", proposal["operations"][0]["content"])
        self.assertIn("did not resolve categorization failure", proposal["operations"][0]["content"])

    def test_approved_action_queue_applies_transcript_cleanup_and_people_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Raw Call.md"
            note.write_text(
                "---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n"
                "# Raw Call\n\n"
                "Alice Smith: Um I was thinking, like, we should review this.\n\n"
                "Bob Jones: Uh yeah, I mean that makes sense.\n"
                + "I remember we were talking about the schedule. " * 14,
                encoding="utf-8",
            )
            self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-action-queue",
                    "--actions",
                    "transcript,people",
                ]
            )
            proposal_path = (
                root
                / "00 System"
                / "0.01 agent"
                / "review"
                / "proposals"
                / "action-queue-transcript-people.json"
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            proposal["status"] = "approved"
            proposal_path.write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            updated_note = note.read_text(encoding="utf-8")
            people_index = (root / "People" / "INDEX.md").read_text(encoding="utf-8")
            alice_exists = (root / "People" / "Alice-Smith.md").exists()

        self.assertEqual(exit_code, 0)
        self.assertIn("Applied: 1", output)
        self.assertIn("source_kind: transcript", updated_note)
        self.assertIn("## Cleaned Narrative", updated_note)
        self.assertIn("## Verbatim Transcript", updated_note)
        self.assertTrue(alice_exists)
        self.assertIn("[[People/Alice-Smith|Alice Smith]]", people_index)


if __name__ == "__main__":
    unittest.main()
