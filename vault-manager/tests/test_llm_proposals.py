import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vault_agent.cli import main
from vault_agent.llm import (
    OpenAICompatibleProposalProvider,
    validate_proposal,
    validate_stage_proposal,
)


class LlmProposalTests(unittest.TestCase):
    def run_cli(self, args):
        import contextlib
        import io

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_type_stage_only_classifies_note_type(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            note = root / "00 Inbox" / "idea.md"
            note.write_text(
                "---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\n---\n# Idea\n\nThis is about retrieval indexes.\n",
                encoding="utf-8",
            )
            proposal = root / "proposal.json"
            proposal.write_text(
                json.dumps(
                    {
                        "note_type": "note",
                        "confidence": 0.92,
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-next",
                    "--stage",
                    "classify-type",
                    "--proposal-file",
                    str(proposal),
                ]
            )
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Stage: classify-type", output)
        self.assertIn("Mode: type-classified", output)
        self.assertIn("type: note", text)
        self.assertIn("domain:", text)
        self.assertIn("parent:", text)
        self.assertIn("related: []", text)
        self.assertNotIn("processing_status:", text)
        self.assertNotIn("summary:", text)
        self.assertIn("This is about retrieval indexes.", text)

    def test_property_values_stage_preserves_unknown_existing_frontmatter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            note = root / "00 Inbox" / "idea.md"
            note.write_text(
                "---\ntype: note\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\ncreated: 2026-01-01\nlegacy: true\n---\n# Idea\n\nBody.\n",
                encoding="utf-8",
            )
            proposal = root / "proposal.json"
            proposal.write_text(
                json.dumps(
                    {
                        "status": "active",
                        "domain": "meta",
                        "parent": "",
                        "related": [],
                        "cover": "",
                        "confidence": 0.92,
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, _output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-next",
                    "--stage",
                    "property-values",
                    "--proposal-file",
                    str(proposal),
                ]
            )
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("created: 2026-01-01", text)
        self.assertIn("legacy: true", text)
        self.assertTrue(text.startswith("---\ntype: note\nstatus: active\n"))
        self.assertIn("domain: meta", text)

    def test_note_target_processes_specific_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            first = root / "00 Inbox" / "a.md"
            second = root / "00 Inbox" / "b.md"
            first.write_text("---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# A\n", encoding="utf-8")
            second.write_text("---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# B\n", encoding="utf-8")
            proposal = root / "proposal.json"
            proposal.write_text(
                json.dumps({"note_type": "note", "confidence": 0.92, "warnings": []}),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-next",
                    "--note",
                    "00 Inbox/b.md",
                    "--stage",
                    "classify-type",
                    "--proposal-file",
                    str(proposal),
                ]
            )
            first_text = first.read_text(encoding="utf-8")
            second_text = second.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Processed: 00 Inbox/b.md", output)
        self.assertIn("type:\n", first_text)
        self.assertIn("type: note\n", second_text)

    def test_warning_proposal_requires_review_without_editing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            note = root / "00 Inbox" / "idea.md"
            original = "---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\nsource_kind:\ncapture_type:\n---\n# Idea\n"
            note.write_text(original, encoding="utf-8")
            proposal = root / "proposal.json"
            proposal.write_text(
                json.dumps(
                    {
                        "note_type": "project",
                        "confidence": 0.95,
                        "warnings": ["ambiguous checklist note"],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-next",
                    "--stage",
                    "classify-type",
                    "--proposal-file",
                    str(proposal),
                ]
            )
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 1)
        self.assertIn("requires review", output)
        self.assertEqual(text, original)

    def test_completed_property_stage_still_runs_when_core_key_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            state_dir = root / "99 System" / "0.01 agent"
            state_dir.mkdir(parents=True)
            note = root / "00 Inbox" / "idea.md"
            note.write_text(
                "---\ntype: note\nstatus: active\ndomain: meta\nparent:\nrelated: []\ncover:\nsource_kind:\n---\n# Idea\n",
                encoding="utf-8",
            )
            (state_dir / "processing-state.json").write_text(
                json.dumps(
                    {
                        "generated_by": "vault-agent",
                        "notes": {
                            "00 Inbox/idea.md": {
                                "hash": "old",
                                "stages": {
                                    "property-values": {"status": "complete"}
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            proposal = root / "proposal.json"
            proposal.write_text(
                json.dumps(
                    {
                        "status": "active",
                        "domain": "meta",
                        "source_kind": "",
                        "parent": "",
                        "related": [],
                        "cover": "",
                        "confidence": 0.92,
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-next",
                    "--note",
                    "00 Inbox/idea.md",
                    "--stage",
                    "property-values",
                    "--proposal-file",
                    str(proposal),
                ]
            )
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Stage: property-values", output)
        self.assertIn("source_kind:", text)
        self.assertIn("capture_type:", text)

    def test_summary_stage_only_writes_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            note = root / "00 Inbox" / "idea.md"
            note.write_text(
                "---\ntype: note\nstatus: active\ndomain: meta\nparent:\nrelated: []\ncover:\n---\n# Idea\n\nBody.\n",
                encoding="utf-8",
            )
            proposal = root / "proposal.json"
            proposal.write_text(
                json.dumps(
                    {
                        "summary": "A note about knowledge management.",
                        "confidence": 0.92,
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-next",
                    "--stage",
                    "summary",
                    "--proposal-file",
                    str(proposal),
                ]
            )
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Stage: summary", output)
        self.assertIn("## Summary", text)
        self.assertIn("A note about knowledge management.", text)

    def test_invalid_proposal_does_not_edit_note(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            note = root / "00 Inbox" / "idea.md"
            original = "# Idea\n\nBody stays untouched.\n"
            note.write_text(
                "---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\n---\n" + original,
                encoding="utf-8",
            )
            proposal = root / "proposal.json"
            proposal.write_text(
                json.dumps({"note_type": "not-a-type", "warnings": []}),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-next",
                    "--stage",
                    "classify-type",
                    "--proposal-file",
                    str(proposal),
                ]
            )

            self.assertIn(original, note.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertIn("note_type must be one of", output)

    def test_low_confidence_proposal_does_not_edit_note(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            note = root / "00 Inbox" / "idea.md"
            original = "# Idea\n\nBody stays untouched.\n"
            note.write_text(
                "---\ntype:\nstatus:\ndomain:\nparent:\nrelated: []\ncover:\n---\n" + original,
                encoding="utf-8",
            )
            proposal = root / "proposal.json"
            proposal.write_text(
                json.dumps(
                    {
                        "note_type": "note",
                        "confidence": 0.5,
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-next",
                    "--stage",
                    "classify-type",
                    "--proposal-file",
                    str(proposal),
                ]
            )

            self.assertIn(original, note.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertIn("below threshold", output)

    def test_proposal_file_batch_requires_single_note_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "00 Inbox").mkdir()
            (root / "00 Inbox" / "one.md").write_text("# One\n", encoding="utf-8")
            proposal = root / "proposal.json"
            proposal.write_text(
                json.dumps({"note_type": "note", "summary": "One."}),
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "process-inbox",
                    "--proposal-file",
                    str(proposal),
                    "--max-notes",
                    "2",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("--proposal-file can only be used", output)

    def test_validate_proposal_rejects_unknown_keys(self):
        result = validate_proposal(
            {
                "note_type": "note",
                "summary": "Valid summary.",
                "frontmatter_updates": {"processing_status": "processed"},
            }
        )

        self.assertFalse(result.valid)
        self.assertIn("unknown proposal keys", result.errors[0])

    def test_validate_stage_proposal_rejects_cross_stage_keys(self):
        result = validate_stage_proposal(
            "classify-type",
            {"note_type": "note", "summary": "too much", "confidence": 0.9},
        )

        self.assertFalse(result.valid)
        self.assertIn("unknown proposal keys", result.errors[0])

    def test_property_values_stage_rejects_unknown_domain(self):
        result = validate_stage_proposal(
            "property-values",
            {
                "status": "active",
                "domain": "gaming",
                "parent": "",
                "related": [],
                "cover": "",
                "confidence": 0.9,
                "warnings": [],
            },
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("domain must be one of" in error for error in result.errors))

    def test_property_values_stage_rejects_unknown_source_kind(self):
        result = validate_stage_proposal(
            "property-values",
            {
                "status": "active",
                "domain": "academic",
                "source_kind": "zine",
                "parent": "",
                "related": [],
                "cover": "",
                "confidence": 0.9,
                "warnings": [],
            },
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("source_kind must be one of" in error for error in result.errors))

    def test_openai_compatible_provider_reads_chat_completion_json(self):
        received = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                body = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "note_type": "note",
                                        "status": "active",
                                        "domain": "meta",
                                        "source_kind": "",
                                        "parent": "",
                                        "related": [],
                                        "cover": "",
                                        "summary": "A concise test summary.",
                                        "confidence": 0.9,
                                        "warnings": [],
                                    }
                                )
                            }
                        }
                    ]
                }
                return json.dumps(body).encode("utf-8")

        def fake_urlopen(request, timeout):
            received["url"] = request.full_url
            received["payload"] = json.loads(request.data.decode("utf-8"))
            received["timeout"] = timeout
            return Response()

        provider = OpenAICompatibleProposalProvider(
            base_url="http://127.0.0.1:1234",
            model="local-test",
            timeout_seconds=5,
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            proposal = provider.propose(
                note_path=Path("00 Inbox/idea.md"),
                note_text="# Idea\n\nA test note.\n",
            )

        self.assertEqual(received["url"], "http://127.0.0.1:1234/v1/chat/completions")
        self.assertEqual(received["payload"]["model"], "local-test")
        self.assertFalse(received["payload"]["stream"])
        self.assertNotIn("max_tokens", received["payload"])
        self.assertEqual(received["timeout"], 5)
        self.assertEqual(proposal["note_type"], "note")
        self.assertEqual(proposal["summary"], "A concise test summary.")

    def test_openai_compatible_provider_accepts_trailing_text_after_json(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                body = {
                    "choices": [
                        {
                            "message": {
                                "content": '{"note_type":"person","confidence":0.9,"warnings":[]} trailing'
                            }
                        }
                    ]
                }
                return json.dumps(body).encode("utf-8")

        def fake_urlopen(request, timeout):
            del request, timeout
            return Response()

        provider = OpenAICompatibleProposalProvider(
            base_url="http://127.0.0.1:1234",
            model="local-test",
            timeout_seconds=5,
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            proposal = provider.propose_stage(
                note_path=Path("Vinod Narayanan.md"),
                note_text="# Vinod Narayanan\n",
                stage="classify-type",
            )

        self.assertEqual(proposal["note_type"], "person")

    def test_openai_compatible_provider_retries_after_non_json_response(self):
        calls = []

        class Response:
            def __init__(self, content):
                self.content = content

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                body = {"choices": [{"message": {"content": self.content}}]}
                return json.dumps(body).encode("utf-8")

        def fake_urlopen(request, timeout):
            del timeout
            payload = json.loads(request.data.decode("utf-8"))
            calls.append(payload)
            if len(calls) == 1:
                return Response("Here's a thinking process with no JSON.")
            return Response('{"note_type":"person","confidence":0.9,"warnings":[]}')

        provider = OpenAICompatibleProposalProvider(
            base_url="http://127.0.0.1:1234",
            model="local-test",
            timeout_seconds=5,
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            proposal = provider.propose_stage(
                note_path=Path("Vinod Narayanan.md"),
                note_text="# Vinod Narayanan\n",
                stage="classify-type",
            )

        self.assertEqual(len(calls), 2)
        self.assertIn("previous response was invalid", calls[1]["messages"][1]["content"])
        self.assertEqual(proposal["note_type"], "person")

    def test_openai_compatible_provider_no_json_error_includes_excerpt(self):
        calls = []

        class Response:
            def __init__(self, content):
                self.content = content

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                body = {
                    "choices": [
                        {
                            "message": {
                                "content": self.content,
                            }
                        }
                    ]
                }
                return json.dumps(body).encode("utf-8")

        def fake_urlopen(request, timeout):
            del timeout
            calls.append(json.loads(request.data.decode("utf-8")))
            if len(calls) == 1:
                return Response("note_type: person\nconfidence: 0.9\nwarnings: []")
            return Response("Still not JSON.")

        provider = OpenAICompatibleProposalProvider(
            base_url="http://127.0.0.1:1234",
            model="local-test",
            timeout_seconds=5,
        )

        with patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(ValueError) as context:
                provider.propose_stage(
                    note_path=Path("Vinod Narayanan.md"),
                    note_text="# Vinod Narayanan\n",
                    stage="classify-type",
                )

        self.assertEqual(len(calls), 2)
        self.assertIn("LLM JSON repair failed", str(context.exception))
        self.assertIn('"phase": "initial"', str(context.exception))
        self.assertIn('"phase": "repair"', str(context.exception))
        self.assertIn("note_type: person", str(context.exception))


if __name__ == "__main__":
    unittest.main()
