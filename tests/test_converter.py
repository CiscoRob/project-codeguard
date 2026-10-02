"""Rule parser and format conversion contracts."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from converter import RuleConverter  # noqa: E402
from formats import CursorFormat  # noqa: E402


def rule_content(
    *, description="Example", languages="[python]", always_apply="false", body="# Title"
):
    return (
        "---\n"
        f"description: {description}\n"
        f"languages: {languages}\n"
        f"alwaysApply: {always_apply}\n"
        "tags: [authentication]\n"
        "---\n\n"
        f"{body}\n"
    )


class RuleConverterTests(unittest.TestCase):
    def setUp(self):
        self.converter = RuleConverter([CursorFormat("1.5.0")])

    def test_authored_heading_and_metadata_are_preserved(self):
        parsed = self.converter.parse_rule(rule_content(), "codeguard-example.md")
        self.assertEqual(parsed.description, "Example")
        self.assertEqual(parsed.languages, ["python"])
        self.assertEqual(parsed.tags, ["authentication"])
        self.assertEqual(parsed.content, "# Title\n\nrule_id: codeguard-example\n\n")

    def test_legacy_body_gets_rule_id_heading(self):
        parsed = self.converter.parse_rule(
            rule_content(body="## Existing section"), "codeguard-example.md"
        )
        self.assertTrue(
            parsed.content.startswith("# codeguard-example\n\nrule_id: codeguard-example")
        )

    def test_always_apply_rule_has_universal_glob(self):
        content = rule_content(languages="[]", always_apply="true")
        parsed = self.converter.parse_rule(content, "codeguard-always.md")
        self.assertEqual(parsed.languages, [])
        self.assertTrue(parsed.always_apply)
        self.assertEqual(self.converter.generate_globs(parsed.languages), "**/*")

    def test_parse_rule_rejects_invalid_frontmatter(self):
        cases = (
            ("No YAML", "Missing or invalid frontmatter"),
            (rule_content().replace("description: Example\n", ""), "description"),
            (rule_content(description="''"), "description"),
            (rule_content(languages="[python]", always_apply="true"), "alwaysApply"),
            (rule_content().replace("languages: [python]\n", ""), "languages"),
            (rule_content(languages="[]"), "non-empty list"),
            (rule_content(languages="python"), "non-empty list"),
            (rule_content().replace("tags: [authentication]", "tags: []"), "tags"),
        )
        for content, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.converter.parse_rule(content, "codeguard-example.md")

    def test_convert_writes_each_registered_format_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "codeguard-example.md"
            path.write_text(rule_content(), encoding="utf-8")
            result = self.converter.convert(path)
        self.assertEqual(result.filename, "codeguard-example.md")
        self.assertEqual(result.basename, "codeguard-example")
        self.assertEqual(result.languages, ["python"])
        self.assertEqual(result.tags, ["authentication"])
        self.assertEqual(set(result.outputs), {"cursor"})
        self.assertEqual(result.outputs["cursor"].extension, ".mdc")
        self.assertIn("# Title", result.outputs["cursor"].content)

    def test_convert_propagates_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            self.converter.convert("/does/not/exist/codeguard-rule.md")


if __name__ == "__main__":
    unittest.main()
