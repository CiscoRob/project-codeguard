"""Regression tests for the release rule converter entry point."""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "src" / "convert_to_ide_formats.py"
sys.path.insert(0, str(SCRIPT_PATH.parent))

import convert_to_ide_formats as converter_script  # noqa: E402
import emit_agents  # noqa: E402
import validate_versions  # noqa: E402

SCRIPT_CODE = compile(SCRIPT_PATH.read_bytes(), str(SCRIPT_PATH), "exec")

SKILL_TEMPLATE = """---
name: codeguard
description: Test skill
metadata:
  codeguard-version: "0.0.0"
---

# CodeGuard

<!-- LANGUAGE_MAPPINGS_START -->
Old language mapping
<!-- LANGUAGE_MAPPINGS_END -->

<!-- TAG_MAPPINGS_START -->
Old tag mapping
<!-- TAG_MAPPINGS_END -->
"""


class ConvertToIdeFormatsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codeguard-converter-")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        (self.project / "src").mkdir()
        (self.project / "sources" / "rules").mkdir(parents=True)
        (self.project / "pyproject.toml").write_text(
            '[project]\nversion = "1.5.0"\n', encoding="utf-8"
        )

    def make_rule(self, source="core", name="codeguard-example.md", tags="authentication"):
        directory = self.project / "sources" / "rules" / source
        directory.mkdir(parents=True, exist_ok=True)
        rule = directory / name
        rule.write_text(
            "---\n"
            "description: Example security rule\n"
            "languages:\n"
            "  - python\n"
            f"tags:\n  - {tags}\n"
            "alwaysApply: false\n"
            "---\n\n"
            "# Example security rule\n\n"
            "## Guidance\n\nUse a safe API.\n",
            encoding="utf-8",
        )
        return rule

    def make_template(self):
        template = self.project / "sources" / "rules" / "core" / "codeguard-SKILLS.md.template"
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text(SKILL_TEMPLATE, encoding="utf-8")
        return template

    def run_cli(self, *args, agent_error=None):
        """Run the real CLI body with an isolated project root and no plugin writes."""
        previous_directory = Path.cwd()
        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            plugin = stack.enter_context(mock.patch.object(validate_versions, "set_plugin_version"))
            marketplace = stack.enter_context(
                mock.patch.object(validate_versions, "set_marketplace_version")
            )
            codex = stack.enter_context(
                mock.patch.object(validate_versions, "set_codex_plugin_version")
            )
            agents = stack.enter_context(mock.patch.object(emit_agents, "emit_agents"))
            agents.side_effect = agent_error
            stack.enter_context(mock.patch.object(sys, "argv", [str(SCRIPT_PATH), *args]))
            stack.enter_context(contextlib.redirect_stdout(output))
            os.chdir(self.project)
            try:
                namespace = {
                    "__name__": "__main__",
                    "__file__": str(self.project / "src" / SCRIPT_PATH.name),
                }
                exec(SCRIPT_CODE, namespace)
            finally:
                os.chdir(previous_directory)
        return output.getvalue(), plugin, marketplace, codex, agents

    def test_mapping_list_is_sorted_and_replaces_only_the_marked_section(self):
        skill = self.project / "SKILL.md"
        skill.write_text("Before\n<!-- TAG_MAPPINGS_START -->old<!-- TAG_MAPPINGS_END -->\nAfter\n")

        converter_script._inject_mapping_list(
            skill,
            {"zeta": ["z.md", "a.md"], "alpha": ["b.md"]},
            marker_name="TAG_MAPPINGS",
        )

        self.assertEqual(
            skill.read_text(),
            "Before\n\n\n- **alpha**:\n  - `b.md`\n- **zeta**:\n"
            "  - `a.md`\n  - `z.md`\n\n\nAfter\n",
        )

    def test_mapping_list_requires_both_markers(self):
        skill = self.project / "SKILL.md"
        skill.write_text("No markers here")
        with self.assertRaisesRegex(RuntimeError, "LANGUAGE_MAPPINGS section markers"):
            converter_script._inject_mapping_list(
                skill, {"python": ["rule.md"]}, marker_name="LANGUAGE_MAPPINGS"
            )

    def test_tag_filter_matches_all_requested_tags(self):
        self.assertTrue(converter_script.matches_tag_filter([], []))
        self.assertTrue(
            converter_script.matches_tag_filter(
                ["authentication", "data-security"], ["authentication"]
            )
        )
        self.assertFalse(
            converter_script.matches_tag_filter(
                ["authentication"], ["authentication", "data-security"]
            )
        )

    def test_sync_plugin_metadata_updates_every_manifest(self):
        with (
            mock.patch.object(converter_script, "set_plugin_version") as plugin,
            mock.patch.object(converter_script, "set_marketplace_version") as marketplace,
            mock.patch.object(converter_script, "set_codex_plugin_version") as codex,
        ):
            converter_script.sync_plugin_metadata("1.5.0")
        for update in (plugin, marketplace, codex):
            update.assert_called_once_with("1.5.0", converter_script.PROJECT_ROOT)

    def test_convert_rules_writes_all_formats_and_sorted_skill_mappings(self):
        self.make_rule(name="codeguard-zeta.md", tags="data-security")
        self.make_rule(name="codeguard-alpha.md", tags="authentication")
        template = self.make_template()
        output = self.project / "dist"

        with (
            mock.patch.object(converter_script, "PROJECT_ROOT", self.project),
            mock.patch.object(converter_script, "_SKILL_TEMPLATE", template),
            mock.patch.object(converter_script, "SKILL_COPY_HOSTS", [".claude", ".agents"]),
        ):
            results = converter_script.convert_rules(
                str(self.project / "sources" / "rules" / "core"), str(output), version="1.5.0"
            )

        self.assertEqual(results["errors"], [])
        self.assertEqual(len(results["success"]), 2)
        skill = (self.project / "skills" / "codeguard" / "SKILL.md").read_text()
        self.assertIn('codeguard-version: "1.5.0"', skill)
        self.assertIn("- **python**:\n  - `codeguard-alpha.md`\n  - `codeguard-zeta.md`", skill)
        self.assertIn("- **authentication**:\n  - `codeguard-alpha.md`", skill)
        self.assertNotIn("Old language mapping", skill)
        self.assertNotIn("| Language |", skill)
        self.assertEqual(
            (output / ".agents" / "skills" / "codeguard" / "SKILL.md").read_text(), skill
        )
        self.assertEqual(
            (output / ".claude" / "skills" / "codeguard" / "SKILL.md").read_text(), skill
        )
        self.assertTrue((output / ".cursor" / "rules" / "codeguard-alpha.mdc").exists())
        self.assertTrue(
            (self.project / "skills" / "codeguard" / "rules" / "codeguard-alpha.md").exists()
        )

    def test_convert_rules_can_filter_tags_without_generating_skills(self):
        self.make_rule(source="owasp", name="codeguard-keep.md", tags="authentication")
        self.make_rule(source="owasp", name="codeguard-skip.md", tags="data-security")
        output = self.project / "dist"

        with mock.patch.object(converter_script, "PROJECT_ROOT", self.project):
            results = converter_script.convert_rules(
                str(self.project / "sources" / "rules" / "owasp"),
                str(output),
                include_agentskills=False,
                version="1.5.0",
                filter_tags=["authentication"],
            )

        self.assertEqual(results["success"], ["codeguard-keep.md"])
        self.assertEqual(results["skipped"], ["codeguard-skip.md"])
        self.assertEqual(results["errors"], [])
        self.assertTrue((output / ".cursor" / "rules" / "codeguard-keep.mdc").exists())
        self.assertFalse((output / ".cursor" / "rules" / "codeguard-skip.mdc").exists())
        self.assertFalse((self.project / "skills").exists())

    def test_convert_rules_uses_project_version_if_none_given(self):
        self.make_rule(source="owasp")
        with mock.patch.object(
            converter_script, "get_version_from_pyproject", return_value="2.0.0"
        ) as version:
            converter_script.convert_rules(
                str(self.project / "sources" / "rules" / "owasp"),
                str(self.project / "dist"),
                include_agentskills=False,
            )
        version.assert_called_once_with()

    def test_convert_rules_rejects_invalid_input_paths(self):
        missing = self.project / "missing"
        with self.assertRaises(FileNotFoundError):
            converter_script.convert_rules(str(missing), version="1.5.0")

        wrong_extension = self.project / "sources" / "rules" / "core" / "codeguard-rule.txt"
        wrong_extension.parent.mkdir(parents=True)
        wrong_extension.write_text("not Markdown")
        with self.assertRaisesRegex(ValueError, "not a .md file"):
            converter_script.convert_rules(str(wrong_extension), version="1.5.0")

        wrong_name = wrong_extension.with_name("README.md")
        wrong_name.write_text("not a rule")
        with self.assertRaisesRegex(ValueError, "not a rule file"):
            converter_script.convert_rules(str(wrong_name), version="1.5.0")

        with self.assertRaisesRegex(ValueError, "No rule files"):
            converter_script.convert_rules(str(wrong_extension.parent), version="1.5.0")

    def test_convert_rules_accepts_one_rule_file(self):
        rule = self.make_rule(source="owasp")
        results = converter_script.convert_rules(
            str(rule), str(self.project / "dist"), include_agentskills=False, version="1.5.0"
        )
        self.assertEqual(results["success"], [rule.name])

    def test_convert_rules_reports_each_conversion_error_type(self):
        for name in ("codeguard-a.md", "codeguard-b.md", "codeguard-c.md"):
            self.make_rule(source="owasp", name=name)
        with mock.patch.object(converter_script, "RuleConverter") as converter:
            converter.return_value.convert.side_effect = [
                FileNotFoundError("gone"),
                ValueError("invalid"),
                RuntimeError("unexpected"),
            ]
            results = converter_script.convert_rules(
                str(self.project / "sources" / "rules" / "owasp"),
                str(self.project / "dist"),
                include_agentskills=False,
                version="1.5.0",
            )
        self.assertEqual(len(results["errors"]), 3)
        self.assertIn("File not found", results["errors"][0])
        self.assertIn("Validation error", results["errors"][1])
        self.assertIn("Unexpected error", results["errors"][2])

    def test_convert_rules_requires_a_skill_template_for_core(self):
        self.make_rule()
        with (
            mock.patch.object(converter_script, "PROJECT_ROOT", self.project),
            mock.patch.object(
                converter_script, "_SKILL_TEMPLATE", self.project / "missing.template"
            ),
        ):
            with self.assertRaisesRegex(FileNotFoundError, "SKILL.md template not found"):
                converter_script.convert_rules(
                    str(self.project / "sources" / "rules" / "core"),
                    str(self.project / "dist"),
                    version="1.5.0",
                )

    def test_resolve_source_paths_accepts_names_but_rejects_escape(self):
        self.assertEqual(
            converter_script._resolve_source_paths(SimpleNamespace(source=None)),
            [Path("sources/rules/core")],
        )
        self.assertEqual(
            converter_script._resolve_source_paths(SimpleNamespace(source=["core", "owasp"])),
            [Path("sources/rules/core"), Path("sources/rules/owasp")],
        )
        for invalid in ("", "  ", "../outside", "/absolute/path"):
            with (
                self.subTest(invalid=invalid),
                self.assertRaisesRegex(ValueError, "non-empty relative"),
            ):
                converter_script._resolve_source_paths(SimpleNamespace(source=[invalid]))

    def test_find_and_print_duplicate_rule_filenames(self):
        self.make_rule(source="core", name="codeguard-duplicate.md")
        self.make_rule(source="owasp", name="codeguard-duplicate.md")
        root = self.project / "sources" / "rules"
        duplicates = converter_script._find_duplicate_rule_filenames(root)
        self.assertEqual(list(duplicates), ["codeguard-duplicate.md"])
        self.assertEqual(len(duplicates["codeguard-duplicate.md"]), 2)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            converter_script._print_duplicate_rule_filenames(duplicates, root)
        self.assertIn("core/codeguard-duplicate.md", output.getvalue())
        self.assertIn("owasp/codeguard-duplicate.md", output.getvalue())

    def test_cli_builds_core_and_owasp_and_cleans_stale_outputs(self):
        self.make_rule(source="core")
        self.make_rule(source="owasp", name="codeguard-extra.md", tags="data-security")
        self.make_template()
        stale = self.project / "dist" / "stale.txt"
        stale.parent.mkdir()
        stale.write_text("stale")
        stale_skill = self.project / "skills" / "codeguard" / "rules" / "stale.md"
        stale_skill.parent.mkdir(parents=True)
        stale_skill.write_text("stale")

        output, plugin, marketplace, codex, agents = self.run_cli(
            "--source", "core", "owasp", "--output-dir", "dist", "--tag", "authentication"
        )

        self.assertIn("Converting 2 sources", output)
        self.assertIn("1 skipped", output)
        self.assertFalse(stale.exists())
        self.assertFalse(stale_skill.exists())
        self.assertTrue(
            (self.project / "dist" / ".cursor" / "rules" / "codeguard-example.mdc").exists()
        )
        self.assertFalse(
            (self.project / "dist" / ".cursor" / "rules" / "codeguard-extra.mdc").exists()
        )
        for update in (plugin, marketplace, codex):
            update.assert_called_once_with("1.5.0", self.project)
        agents.assert_called_once()

    def test_cli_owasp_only_skips_skill_and_agent_generation(self):
        self.make_rule(source="owasp")
        output, _, _, _, agents = self.run_cli("--source", "owasp", "--output-dir", "dist")
        self.assertIn("Skipped agent emission", output)
        self.assertFalse((self.project / "skills").exists())
        agents.assert_not_called()

    def test_cli_rejects_invalid_or_missing_sources(self):
        for arguments, expected in (
            (("--source", "../outside"), "non-empty relative"),
            (("--source", "missing"), "Source path(s) not found"),
        ):
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as error:
                self.run_cli(*arguments)
            self.assertEqual(error.exception.code, 1)

    def test_cli_rejects_duplicate_rule_names(self):
        self.make_rule(source="core", name="codeguard-duplicate.md")
        self.make_rule(source="owasp", name="codeguard-duplicate.md")
        with self.assertRaises(SystemExit) as error:
            self.run_cli("--source", "core", "owasp")
        self.assertEqual(error.exception.code, 1)

    def test_cli_rejects_missing_skill_template(self):
        self.make_rule(source="core")
        with self.assertRaises(SystemExit) as error:
            self.run_cli()
        self.assertEqual(error.exception.code, 1)

    def test_cli_exits_when_a_rule_cannot_be_converted(self):
        bad_rule = self.make_rule(source="owasp")
        bad_rule.write_text("invalid frontmatter")
        with self.assertRaises(SystemExit) as error:
            self.run_cli("--source", "owasp")
        self.assertEqual(error.exception.code, 1)

    def test_cli_exits_when_agent_emission_fails(self):
        self.make_rule(source="core")
        self.make_template()
        with self.assertRaises(SystemExit) as error:
            self.run_cli(agent_error=ValueError("bad agent"))
        self.assertEqual(error.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
