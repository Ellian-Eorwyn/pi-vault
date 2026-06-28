"""Tests for value definitions: schema storage, prompt injection, authoring,
and the norms-lock requirement."""

from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from vault_agent.config import load_config
from vault_agent.llm import OpenAICompatibleProposalProvider, _stage_prompt
from vault_agent.norms import run_norms_lock
from vault_agent.paths import paths_for
from vault_agent.proposals import generate_property_proposal
from vault_agent.schema import (
    CAPTURE_TYPE_DEFINITIONS,
    SOURCE_KIND_DEFINITIONS,
    default_schema,
    definitions_for,
    missing_definitions,
)
from vault_agent.schema_defaults import (
    parse_vault_defaults_markdown,
    proposal_from_vault_defaults,
    vault_defaults_markdown,
)


class SchemaDefinitionDataTests(unittest.TestCase):
    def test_default_schema_includes_new_definition_maps(self):
        schema = default_schema()
        self.assertEqual(schema["source_kind_definitions"], SOURCE_KIND_DEFINITIONS)
        self.assertEqual(schema["capture_type_definitions"], CAPTURE_TYPE_DEFINITIONS)
        self.assertTrue(schema["source_kind_definitions"]["book"])

    def test_definitions_for_merges_schema_over_builtin(self):
        schema = default_schema()
        schema["domain_definitions"]["work"] = "Custom work meaning."
        merged = definitions_for(schema, "domain")
        self.assertEqual(merged["work"], "Custom work meaning.")
        # untouched values still come from the built-in defaults
        self.assertTrue(merged["academic"])


class PromptInjectionTests(unittest.TestCase):
    def setUp(self):
        self.provider = OpenAICompatibleProposalProvider(base_url="http://x", model="m")

    def test_property_values_prompt_includes_domain_definition(self):
        prompt = _stage_prompt(
            note_path=Path("01 Inbox/n.md"),
            note_text="body",
            stage="property-values",
            max_chars=500,
            definitions=self.provider._definitions(),
        )
        self.assertIn("academic: Research", prompt)
        self.assertIn("book: A book", prompt)

    def test_classify_type_prompt_includes_note_type_definition(self):
        prompt = _stage_prompt(
            note_path=Path("01 Inbox/n.md"),
            note_text="body",
            stage="classify-type",
            max_chars=500,
            definitions=self.provider._definitions(),
        )
        self.assertIn("project:", prompt)
        self.assertIn("Temporary effort", prompt)

    def test_assign_hub_prompt_renders_hub_descriptions(self):
        prompt = _stage_prompt(
            note_path=Path("n.md"),
            note_text="b",
            stage="assign-hub",
            max_chars=500,
            allowed_hubs=[("AI", "Artificial intelligence topics"), ("Linux", "")],
        )
        self.assertIn("AI: Artificial intelligence topics", prompt)
        self.assertIn("- Linux", prompt)

    def test_definitions_on_by_default_via_provider(self):
        # The provider defaults its maps to the built-in definitions.
        self.assertTrue(self.provider.domain_definitions["work"])
        self.assertTrue(self.provider.source_kind_definitions["article"])


class PropertyProposalRecordsDefinitionTests(unittest.TestCase):
    def test_new_value_definition_lands_in_schema_json(self):
        proposal, errors = generate_property_proposal(
            property_name="source_kind",
            allowed_value="map",
            description="A cartographic map.",
        )
        self.assertEqual(errors, [])
        schema_op = next(op for op in proposal["operations"] if op["path"].endswith("schema.json"))
        schema = json.loads(schema_op["content"])
        self.assertEqual(schema["source_kind_definitions"]["map"], "A cartographic map.")
        self.assertIn("map", schema["core_properties"]["source_kind"]["allowed"])


class MissingDefinitionsTests(unittest.TestCase):
    def test_default_schema_is_fully_defined(self):
        self.assertEqual(missing_definitions(default_schema()), [])

    def test_custom_value_without_definition_is_reported(self):
        # Built-in values always carry built-in definitions; only undefined custom
        # additions are flagged.
        schema = default_schema()
        schema["core_properties"]["domain"]["allowed"].append("robotics")
        schema["core_properties"]["source_kind"]["allowed"].append("zine")
        missing = missing_definitions(schema)
        self.assertIn("domain:robotics", missing)
        self.assertIn("source_kind:zine", missing)
        # a custom value WITH a definition is not flagged
        schema["domain_definitions"]["robotics"] = "Robots and automation."
        self.assertNotIn("domain:robotics", missing_definitions(schema))


class NormsLockRequiresDefinitionsTests(unittest.TestCase):
    def _config(self, directory):
        return load_config(
            Namespace(vault_root=directory, config=None, dry_run=False, verbose=False)
        )

    def _write_schema(self, root: Path, schema: dict) -> None:
        agent_dir = root / paths_for(root).agent_dir
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "schema.json").write_text(json.dumps(schema), encoding="utf-8")

    def test_lock_blocks_when_definition_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema = default_schema()
            schema["core_properties"]["capture_type"]["allowed"].append("scanned")
            self._write_schema(root, schema)
            code, message = run_norms_lock(self._config(directory), write=True)
        self.assertEqual(code, 1)
        self.assertIn("capture_type:scanned", message)

    def test_lock_succeeds_when_all_defined(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_schema(root, default_schema())
            code, message = run_norms_lock(self._config(directory), write=True)
        self.assertEqual(code, 0)
        self.assertIn("complete", message)


class SchemaDefaultsRoundtripTests(unittest.TestCase):
    def test_edited_definition_is_applied_to_schema(self):
        parsed = parse_vault_defaults_markdown(vault_defaults_markdown())
        parsed["source_kind_descriptions"]["book"] = "EDITED book meaning."
        parsed["domain_descriptions"]["work"] = "EDITED work meaning."
        proposal = proposal_from_vault_defaults(None, parsed)
        schema_op = next(op for op in proposal["operations"] if op["path"].endswith("schema.json"))
        schema = json.loads(schema_op["content"])
        self.assertEqual(schema["source_kind_definitions"]["book"], "EDITED book meaning.")
        self.assertEqual(schema["domain_definitions"]["work"], "EDITED work meaning.")


if __name__ == "__main__":
    unittest.main()
