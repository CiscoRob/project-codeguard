"""Version manifest synchronization and validation."""

import contextlib
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import validate_versions as versions  # noqa: E402


class ValidateVersionsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codeguard-versions-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".claude-plugin").mkdir()
        (self.root / ".codex-plugin").mkdir()
        (self.root / "skills" / "codeguard").mkdir(parents=True)
        (self.root / "pyproject.toml").write_text('[project]\nversion = "1.5.0"\n')
        (self.root / ".claude-plugin" / "plugin.json").write_text('{"version": "1.5.0"}')
        (self.root / ".claude-plugin" / "marketplace.json").write_text(
            '{"plugins": [{"version": "1.5.0"}, {"version": "1.5.0"}]}'
        )
        (self.root / ".codex-plugin" / "plugin.json").write_text('{"version": "1.5.0"}')
        (self.root / "skills" / "codeguard" / "SKILL.md").write_text(
            '---\ncodeguard-version: "1.5.0"\n---\n# CodeGuard\n'
        )

    def test_getters_and_version_comparison(self):
        self.assertEqual(versions.get_pyproject_version(self.root), "1.5.0")
        self.assertEqual(versions.get_plugin_version(self.root), "1.5.0")
        self.assertEqual(versions.get_marketplace_version(self.root), "1.5.0")
        self.assertEqual(versions.get_codex_plugin_version(self.root), "1.5.0")
        self.assertEqual(versions.get_skill_codeguard_version(self.root), "1.5.0")
        self.assertTrue(
            all(check.matches for check in versions.validate_versions("1.5.0", self.root))
        )
        self.assertFalse(
            any(check.matches for check in versions.validate_versions("2.0.0", self.root))
        )

    def test_setters_update_all_manifest_versions(self):
        versions.set_plugin_version("2.0.0", self.root)
        versions.set_codex_plugin_version("2.0.0", self.root)
        versions.set_marketplace_version("2.0.0", self.root)
        self.assertEqual(versions.get_plugin_version(self.root), "2.0.0")
        self.assertEqual(versions.get_codex_plugin_version(self.root), "2.0.0")
        self.assertEqual(versions.get_marketplace_version(self.root), "2.0.0")
        marketplace = json.loads((self.root / ".claude-plugin" / "marketplace.json").read_text())
        self.assertEqual([plugin["version"] for plugin in marketplace["plugins"]], ["2.0.0"] * 2)
        for path in (
            self.root / ".claude-plugin" / "plugin.json",
            self.root / ".claude-plugin" / "marketplace.json",
            self.root / ".codex-plugin" / "plugin.json",
        ):
            self.assertTrue(path.read_text().endswith("\n"))

    def test_skill_frontmatter_value_requires_key_and_delimiters(self):
        skill = self.root / "skills" / "codeguard" / "SKILL.md"
        skill.write_text("No frontmatter")
        with self.assertRaisesRegex(ValueError, "Missing front matter"):
            versions.get_skill_codeguard_version(self.root)
        skill.write_text("---\nname: codeguard\n---\n# CodeGuard\n")
        with self.assertRaisesRegex(ValueError, "Missing codeguard-version"):
            versions.get_skill_codeguard_version(self.root)

    def test_default_validation_root_is_script_parent(self):
        fake_script = self.root / "src" / "validate_versions.py"
        with mock.patch.object(versions, "__file__", str(fake_script)):
            self.assertTrue(all(check.matches for check in versions.validate_versions("1.5.0")))

    def test_cli_reports_usage_success_and_mismatch(self):
        output = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["validate_versions.py"]),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(versions.main(), 1)
        self.assertIn("Usage:", output.getvalue())

        for found, expected_status in (("1.5.0", 0), ("2.0.0", 1)):
            result = versions.VersionCheck("pyproject.toml", "1.5.0", found, found == "1.5.0")
            output = io.StringIO()
            with (
                mock.patch.object(sys, "argv", ["validate_versions.py", "1.5.0"]),
                mock.patch.object(versions, "validate_versions", return_value=[result]),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(versions.main(), expected_status)
            self.assertIn("pyproject.toml", output.getvalue())

    def test_module_entry_point_returns_a_status(self):
        with (
            mock.patch.object(sys, "argv", ["validate_versions.py"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as error:
                runpy.run_module("validate_versions", run_name="__main__")
        self.assertEqual(error.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
