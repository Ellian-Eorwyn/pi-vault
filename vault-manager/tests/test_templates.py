import unittest

import yaml

from vault_agent.frontmatter import parse_note
from vault_agent.schema import (
    CORE_PROPERTY_ORDER,
    NOTE_TYPES,
    index_base_templates,
    starter_templates,
)
from vault_agent.templates import append_missing_headings


class TemplateTests(unittest.TestCase):
    def test_starter_templates_exist_for_current_note_types_only(self):
        templates = starter_templates()
        expected_paths = {
            f"99 System/0.02 templates/note-types/{note_type}.md"
            for note_type in NOTE_TYPES
        }

        self.assertEqual(set(templates), expected_paths)

    def test_templates_keep_sparse_yaml_and_rich_body_structure(self):
        templates = starter_templates()

        for note_type, template in templates.items():
            with self.subTest(template=note_type):
                parsed = parse_note(template)

                self.assertFalse(parsed.error)
                self.assertEqual(tuple(parsed.frontmatter), CORE_PROPERTY_ORDER)
                self.assertIn("> [!", parsed.body)
                self.assertIn("## Summary", parsed.body)
                self.assertIn("## Notes", parsed.body)
                self.assertNotIn("tags:", template)
                self.assertNotIn("created:", template)
                self.assertNotIn("updated:", template)

    def test_templates_include_type_specific_work_surfaces(self):
        templates = starter_templates()

        self.assertIn("## Milestones", templates["99 System/0.02 templates/note-types/project.md"])
        self.assertIn("## Citation", templates["99 System/0.02 templates/note-types/source.md"])
        self.assertIn("## Contact And Context", templates["99 System/0.02 templates/note-types/person.md"])
        self.assertIn("## Action Items", templates["99 System/0.02 templates/note-types/meeting.md"])
        self.assertIn("## Start Here", templates["99 System/0.02 templates/note-types/index.md"])

    def test_index_base_templates_are_sparse_and_parseable(self):
        allowed_properties = set(CORE_PROPERTY_ORDER)
        allowed_prefixes = ("file.", "this.")
        forbidden_properties = {"tags", "created", "updated", "priority", "due"}

        for path, template in index_base_templates().items():
            with self.subTest(template=path):
                parsed = parse_note(template)
                blocks = _base_blocks(parsed.body)

                self.assertFalse(parsed.error)
                self.assertEqual(tuple(parsed.frontmatter), CORE_PROPERTY_ORDER)
                self.assertGreaterEqual(len(blocks), 1)
                self.assertNotIn("tags:", template)
                self.assertNotIn("priority:", template)

                for block in blocks:
                    loaded = yaml.safe_load(block)
                    self.assertIsInstance(loaded, dict)
                    self.assertIn("views", loaded)
                    self.assertTrue(
                        any(view["type"] == "table" for view in loaded["views"])
                    )
                    referenced = _referenced_order_properties(loaded)
                    unexpected = {
                        prop
                        for prop in referenced
                        if prop not in allowed_properties
                        and not prop.startswith(allowed_prefixes)
                        and prop not in forbidden_properties
                    }
                    self.assertEqual(unexpected, set())
                    self.assertEqual(referenced & forbidden_properties, set())

    def test_index_base_templates_cover_requested_patterns(self):
        templates = index_base_templates()

        self.assertIn("domain == this.domain", templates["99 System/0.02 templates/indexes/domain-index.md"])
        self.assertIn("parent == this.file.asLink()", templates["99 System/0.02 templates/indexes/parent-dashboard.md"])
        self.assertIn('type == "source"', templates["99 System/0.02 templates/indexes/object-collections.md"])
        self.assertIn('cover != ""', templates["99 System/0.02 templates/indexes/cover-gallery.md"])

    def test_template_application_appends_full_missing_sections(self):
        body = "# Source\n\nExisting body stays.\n\n## Summary\n\nAlready summarized.\n"

        updated, headings = append_missing_headings(body, "source")

        self.assertIn("Existing body stays.", updated)
        self.assertIn("## Citation", updated)
        self.assertIn("| Creator |  |", updated)
        self.assertIn("## Evidence And Excerpts", updated)
        self.assertIn("> [!quote] Useful Passage", updated)
        self.assertNotIn("## Summary\n\nOne to three sentences", updated)
        self.assertIn("## Citation", headings)
        self.assertNotIn("## Summary", headings)

    def test_template_application_is_idempotent(self):
        body = "# Task\n\nBody.\n"

        once, first_headings = append_missing_headings(body, "task")
        twice, second_headings = append_missing_headings(once, "task")

        self.assertIn("## Checklist", once)
        self.assertIn("| Due / Review |  |", once)
        self.assertIn("## Checklist", first_headings)
        self.assertEqual(twice, once)
        self.assertEqual(second_headings, [])


def _base_blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() == "```base":
            index += 1
            block: list[str] = []
            while index < len(lines) and lines[index].strip() != "```":
                block.append(lines[index])
                index += 1
            blocks.append("\n".join(block))
        index += 1
    return blocks


def _referenced_order_properties(base: dict) -> set[str]:
    referenced: set[str] = set()
    for view in base.get("views", []):
        referenced.update(view.get("order", []))
        group_by = view.get("groupBy")
        if isinstance(group_by, dict) and "property" in group_by:
            referenced.add(group_by["property"])
    return referenced


if __name__ == "__main__":
    unittest.main()
