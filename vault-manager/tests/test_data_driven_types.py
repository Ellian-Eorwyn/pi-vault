import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from vault_agent.cli import main
from vault_agent.llm import validate_stage_proposal
from vault_agent.review import _validate_schema_json_write
from vault_agent.schema import (
    allowed_note_types,
    allowed_note_types_from_schema,
    default_schema,
)
from vault_agent.templates import template_sections


def _schema_with_type(name: str) -> dict:
    schema = default_schema()
    schema["note_types"][name] = {"folder": "08 Recipes", "description": "A recipe."}
    schema["core_properties"]["type"]["allowed"].append(name)
    schema["common_properties"] = schema["core_properties"]
    return schema


class SchemaHelperTests(unittest.TestCase):
    def test_allowed_note_types_overlays_builtins(self):
        allowed = allowed_note_types_from_schema(_schema_with_type("recipe"))
        self.assertIn("recipe", allowed)
        self.assertIn("project", allowed)  # built-in preserved

    def test_load_from_vault(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = root / "99 System" / "0.01 agent"
            agent.mkdir(parents=True)
            (agent / "schema.json").write_text(
                json.dumps(_schema_with_type("recipe")), encoding="utf-8"
            )
            allowed = allowed_note_types(root)
        self.assertIn("recipe", allowed)
        self.assertIn("person", allowed)


class CustomTypeBehaviorTests(unittest.TestCase):
    def test_classify_type_accepts_custom_type(self):
        ok = validate_stage_proposal(
            "classify-type", {"note_type": "recipe", "confidence": 0.9}, extra_note_types=["recipe"]
        )
        self.assertTrue(ok.valid, ok.errors)
        rejected = validate_stage_proposal("classify-type", {"note_type": "recipe", "confidence": 0.9})
        self.assertFalse(rejected.valid)

    def test_template_sections_from_disk_for_custom_type(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            note_types_dir = root / "99 System" / "0.02 templates" / "note-types"
            note_types_dir.mkdir(parents=True)
            (note_types_dir / "recipe.md").write_text(
                "---\ntype: recipe\n---\n\n## Ingredients\n\n- \n\n## Steps\n\n1. \n",
                encoding="utf-8",
            )
            sections = template_sections("recipe", vault_root=root)
        headings = [section["heading"] for section in sections]
        self.assertEqual(headings, ["## Ingredients", "## Steps"])

    def test_template_sections_empty_for_unknown_type(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(template_sections("nope", vault_root=Path(directory)), [])


class SchemaGuardTests(unittest.TestCase):
    def test_accepts_additive_schema(self):
        self.assertEqual(_validate_schema_json_write(json.dumps(_schema_with_type("recipe"))), [])

    def test_rejects_malformed_json(self):
        errors = _validate_schema_json_write("{not json")
        self.assertTrue(any("not valid JSON" in e for e in errors))

    def test_rejects_dropped_builtin(self):
        schema = default_schema()
        del schema["note_types"]["project"]
        errors = _validate_schema_json_write(json.dumps(schema))
        self.assertTrue(any("built-in note types" in e and "project" in e for e in errors))

    def test_rejects_allowed_without_definition(self):
        schema = default_schema()
        schema["core_properties"]["type"]["allowed"].append("ghost")
        errors = _validate_schema_json_write(json.dumps(schema))
        self.assertTrue(any("ghost" in e for e in errors))

    def test_rejects_bad_slug(self):
        schema = _schema_with_type("Bad Type")
        errors = _validate_schema_json_write(json.dumps(schema))
        self.assertTrue(any("slug" in e for e in errors))


class SchemaGuardEndToEndTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_apply_blocks_corrupt_schema_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = root / "99 System" / "0.01 agent"
            proposals = agent / "review" / "proposals"
            proposals.mkdir(parents=True)
            broken = default_schema()
            del broken["note_types"]["person"]
            (proposals / "schema.json").write_text(
                json.dumps(
                    {
                        "id": "bad-schema",
                        "kind": "schema-change",
                        "status": "approved",
                        "operations": [
                            {
                                "op": "write_file",
                                "path": "99 System/0.01 agent/schema.json",
                                "if_exists": "overwrite",
                                "content": json.dumps(broken) + "\n",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            exit_code, output = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
        self.assertNotEqual(exit_code, 0)
        self.assertIn("built-in note types", output)


class ProposeNoteTypeTests(unittest.TestCase):
    def run_cli(self, args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(args)
        return exit_code, stdout.getvalue()

    def test_propose_and_apply_note_type(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exit_code, _ = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-note-type",
                    "--name",
                    "recipe",
                    "--description",
                    "A cooking recipe.",
                    "--folder",
                    "08 Recipes",
                ]
            )
            self.assertEqual(exit_code, 0)
            proposal = root / "99 System" / "0.01 agent" / "review" / "proposals" / "note-type-recipe.json"
            data = json.loads(proposal.read_text(encoding="utf-8"))
            self.assertEqual(data["kind"], "schema-change")
            data["status"] = "approved"
            proposal.write_text(json.dumps(data), encoding="utf-8")

            apply_code, apply_out = self.run_cli(
                ["--vault-root", directory, "review-proposals", "--apply-approved"]
            )
            schema = json.loads((root / "99 System" / "0.01 agent" / "schema.json").read_text())
            template_exists = (
                root / "99 System" / "0.02 templates" / "note-types" / "recipe.md"
            ).is_file()

        self.assertEqual(apply_code, 0, apply_out)
        self.assertIn("recipe", schema["note_types"])
        self.assertIn("recipe", schema["core_properties"]["type"]["allowed"])
        self.assertTrue(template_exists)

    def test_rejects_builtin_name(self):
        with tempfile.TemporaryDirectory() as directory:
            exit_code, output = self.run_cli(
                [
                    "--vault-root",
                    directory,
                    "propose-note-type",
                    "--name",
                    "project",
                    "--description",
                    "x",
                    "--folder",
                    "08 Recipes",
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("built-in note type", output)


if __name__ == "__main__":
    unittest.main()
