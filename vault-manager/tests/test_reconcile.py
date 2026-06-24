import tempfile
import unittest
from pathlib import Path

from vault_agent.cli import main
from vault_agent.reconcile import infer_type_from_content


class ReconcileTests(unittest.TestCase):
    def run_cli(self, args):
        import contextlib
        import io

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_reconcile_properties_only_skips_template_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "Meeting Notes.md"
            note.write_text(
                "---\ntype: meeting\nareas: [work]\n---\n# Sync\n\nAgenda and attendees.\n",
                encoding="utf-8",
            )
            exit_code, output = self.run_cli(
                ["--vault-root", directory, "reconcile", "--properties-only"]
            )
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        # legacy `areas` was mapped into the sparse `domain` property
        self.assertIn("domain: work", text)
        # but no template body headings were injected
        self.assertNotIn("## Summary", text)

    def test_reconcile_infers_template_from_content_not_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Loose Notes"
            folder.mkdir()
            note = folder / "epistemic-friction.md"
            note.write_text(
                "# Epistemic Friction\n\nDefinition: resistance in shared knowledge work.\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(["--vault-root", directory, "reconcile"])
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Applied: 1", output)
        self.assertIn("type: note", text)
        self.assertIn("domain:", text)
        self.assertIn("parent:", text)
        self.assertIn("related: []", text)
        self.assertIn("cover:", text)
        self.assertNotIn("processing_status:", text)
        self.assertIn("## Summary", text)
        self.assertIn("## Notes", text)

    def test_reconcile_dry_run_reports_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "claim.md"
            note.write_text("# Claim\n\nClaim: templates should be safe.\n", encoding="utf-8")

            exit_code, output = self.run_cli(["--vault-root", directory, "reconcile", "--dry-run"])
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("reconcile dry run", output)
        self.assertIn("properties:", output)
        self.assertNotIn("type: note", text)

    def test_reconcile_preserves_existing_property_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "project.md"
            note.write_text(
                "---\ntype: project\nstatus: active\ndomain: work\n---\n# Plan\n\nMilestone: ship.\n",
                encoding="utf-8",
            )

            exit_code, _output = self.run_cli(["--vault-root", directory, "reconcile"])
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("status: active", text)
        self.assertIn("domain: work", text)
        self.assertIn("parent:", text)
        self.assertIn("related: []", text)
        self.assertIn("capture_type:", text)
        self.assertNotIn("processing_status:", text)

    def test_reconcile_preserves_unknown_properties_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "note.md"
            note.write_text(
                "---\ntype: note\nstatus: active\nlegacy: keep elsewhere\nprocessing_status: old\n---\n# Note\n\nDefinition: one.\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(["--vault-root", directory, "reconcile"])
            text = note.read_text(encoding="utf-8")
            backups = list(
                (root / "99 System" / "0.01 agent" / "backups").glob("note.md.*.bak")
            )

        self.assertEqual(exit_code, 0)
        self.assertNotIn("remove properties: legacy, processing_status", output)
        self.assertIn("legacy: keep elsewhere", text)
        self.assertIn("processing_status: old", text)
        self.assertIn("type: note\nstatus: active\ndomain:", text)
        self.assertEqual(len(backups), 1)

    def test_reconcile_can_remove_unknown_properties_when_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.yaml"
            config.write_text(
                "legacy_metadata:\n  preserve_unknown_properties: false\n",
                encoding="utf-8",
            )
            note = root / "note.md"
            note.write_text(
                "---\ntype: note\nstatus: active\nlegacy: keep elsewhere\nprocessing_status: old\n---\n# Note\n\nDefinition: one.\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(
                ["--vault-root", directory, "--config", str(config), "reconcile"]
            )
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("remove properties: legacy, processing_status", output)
        self.assertNotIn("legacy:", text)
        self.assertNotIn("processing_status:", text)

    def test_reconcile_dry_run_preserves_unknown_properties_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "note.md"
            note.write_text(
                "---\ntype: note\nlegacy: yes\n---\n# Note\n\nDefinition: one.\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(["--vault-root", directory, "reconcile", "--dry-run"])
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertNotIn("remove properties: legacy", output)
        self.assertIn("legacy: yes", text)

    def test_reconcile_applies_legacy_aliases_without_removing_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "journal.md"
            note.write_text(
                "---\ntype: journal\nstatus: raw\ndomains: [personal]\n---\n# Journal\n\nBody.\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(["--vault-root", directory, "reconcile"])
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("properties: capture_type, cover, domain, parent, related, source_kind, status, type", output)
        self.assertIn("type: daily", text)
        self.assertIn("status: active", text)
        self.assertIn("domain: personal", text)
        self.assertIn("domains: [personal]", text)

    def test_reconcile_maps_broader_legacy_metadata_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "source.md"
            note.write_text(
                "---\n"
                "type: source\n"
                "area: [unknown, academic]\n"
                "publication_type: web\n"
                "tags: [PKM, agents]\n"
                "created: 2026-01-01\n"
                "updated: 2026-01-02\n"
                "title: Legacy Title\n"
                "aliases: [Old Name]\n"
                "summary: Keep this legacy summary.\n"
                "---\n"
                "# Source\n\nAuthor: A.\n",
                encoding="utf-8",
            )

            exit_code, output = self.run_cli(["--vault-root", directory, "reconcile"])
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("properties:", output)
        self.assertIn("domain: academic", text)
        self.assertIn("source_kind: website", text)
        self.assertIn("related: [PKM, agents]", text)
        self.assertIn("created: 2026-01-01", text)
        self.assertIn("updated: 2026-01-02", text)
        self.assertIn("title: Legacy Title", text)
        self.assertIn("aliases: [Old Name]", text)
        self.assertIn("summary: Keep this legacy summary.", text)
        self.assertIn("area: [unknown, academic]", text)
        self.assertIn("publication_type: web", text)
        self.assertIn("tags: [PKM, agents]", text)

    def test_reconcile_leaves_domain_blank_when_legacy_domain_is_not_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "note.md"
            note.write_text(
                "---\ntype: note\nareas: [very-specific-topic]\n---\n# Note\n\nDefinition: one.\n",
                encoding="utf-8",
            )

            exit_code, _output = self.run_cli(["--vault-root", directory, "reconcile"])
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("domain:", text)
        self.assertNotIn("domain: very-specific-topic", text)
        self.assertIn("areas: [very-specific-topic]", text)

    def test_reconcile_uses_canonical_property_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "source.md"
            note.write_text(
                "---\nrelated: []\ncover:\nparent:\ndomain: academic\nstatus: active\ntype: source\n---\n# Source\n\nAuthor: A.\n",
                encoding="utf-8",
            )

            exit_code, _output = self.run_cli(["--vault-root", directory, "reconcile"])
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertTrue(
            text.startswith(
                "---\ntype: source\nstatus: active\ndomain: academic\nparent: \nrelated: []\ncover: \nsource_kind: \ncapture_type: \n---"
            )
        )

    def test_reconcile_skips_malformed_notes_without_editing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "bad.md"
            original = "---\ntype: [broken\n---\n# Bad\n\nDefinition: no edit.\n"
            note.write_text(original, encoding="utf-8")

            exit_code, output = self.run_cli(["--vault-root", directory, "reconcile"])
            text = note.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("Skipped notes: 1", output)
        self.assertEqual(text, original)

    def test_reconcile_reports_untyped_notes_for_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note = root / "plain.md"
            note.write_text("---\nlegacy: yes\n---\n# Plain\n\nNo clear signals.\n", encoding="utf-8")

            exit_code, output = self.run_cli(["--vault-root", directory, "reconcile", "--dry-run"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Needs review: 1", output)
        self.assertIn("could not infer note type", output)

    def test_content_inference_beats_misleading_folder(self):
        inferred = infer_type_from_content(
            Path("02 Concepts/weekly-sync.md"),
            "# Weekly Sync\n\nAttendees: Ellie\n\nAgenda\n",
        )

        self.assertEqual(inferred, "meeting")


if __name__ == "__main__":
    unittest.main()
