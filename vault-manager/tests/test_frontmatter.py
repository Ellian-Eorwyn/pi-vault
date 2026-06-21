import unittest

from vault_agent.frontmatter import parse_note, render_note


class FrontmatterTests(unittest.TestCase):
    def test_parse_note_without_frontmatter(self):
        parsed = parse_note("# Title\n\nBody.\n")

        self.assertFalse(parsed.has_frontmatter)
        self.assertEqual(parsed.frontmatter, {})
        self.assertEqual(parsed.body, "# Title\n\nBody.\n")

    def test_parse_empty_values_and_render_canonical_order(self):
        parsed = parse_note("---\ndomain:\ntype: note\nrelated: []\n---\n# Note\n")

        rendered = render_note(parsed.frontmatter, parsed.body)

        self.assertIsNone(parsed.frontmatter["domain"])
        self.assertEqual(
            rendered,
            "---\ntype: note\ndomain: \nrelated: []\n---\n# Note\n",
        )

    def test_parse_inline_lists_and_quoted_wikilinks(self):
        parsed = parse_note(
            '---\nrelated: ["[[One]]", "[[Two]]"]\nparent: "[[Root]]"\n---\n# Note\n'
        )

        self.assertEqual(parsed.frontmatter["related"], ["[[One]]", "[[Two]]"])
        self.assertEqual(parsed.frontmatter["parent"], "[[Root]]")

    def test_parse_block_lists_and_comments(self):
        parsed = parse_note(
            "---\n# comment\nrelated:\n  - '[[One]]'\n  - \"[[Two]]\"\n---\n# Note\n"
        )

        self.assertEqual(parsed.frontmatter["related"], ["[[One]]", "[[Two]]"])

    def test_malformed_frontmatter_is_error(self):
        parsed = parse_note("---\ntype: [broken\n---\n# Bad\n")

        self.assertTrue(parsed.has_frontmatter)
        self.assertIsNotNone(parsed.error)
        self.assertEqual(parsed.frontmatter, {})

    def test_unclosed_frontmatter_is_error(self):
        parsed = parse_note("---\ntype: note\n# Bad\n")

        self.assertEqual(parsed.error, "frontmatter block is not closed")

    def test_nested_yaml_renders_as_canonical_scalar(self):
        parsed = parse_note("---\nmetadata:\n  source: book\n---\n# Note\n")

        rendered = render_note(parsed.frontmatter, parsed.body)

        self.assertEqual(parsed.frontmatter["metadata"], {"source": "book"})
        self.assertIn("metadata: \"{'source': 'book'}\"", rendered)

    def test_special_scalars_render_as_valid_yaml(self):
        rendered = render_note(
            {
                "title": "** HoMEDUCS Scratch",
                "summary": r"Demand/Market Assessment \[Q6, Q8\]",
            },
            "# Note\n",
        )

        parsed = parse_note(rendered)

        self.assertIsNone(parsed.error)
        self.assertEqual(parsed.frontmatter["title"], "** HoMEDUCS Scratch")
        self.assertEqual(
            parsed.frontmatter["summary"],
            r"Demand/Market Assessment \[Q6, Q8\]",
        )


if __name__ == "__main__":
    unittest.main()
