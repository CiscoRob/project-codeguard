"""Bundle target metadata shared by the converter and agent emitter."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from artifact_targets import AGENT_HOSTS, SKILL_COPY_HOSTS, TOML_AGENT_HOSTS  # noqa: E402


class ArtifactTargetsTests(unittest.TestCase):
    def test_core_distribution_targets_exist(self):
        self.assertIn(".agents", SKILL_COPY_HOSTS)
        self.assertEqual(AGENT_HOSTS[".cursor"]["rule_ext"], ".mdc")
        self.assertEqual(TOML_AGENT_HOSTS["codex"]["output_dir"], ".codex/agents")


if __name__ == "__main__":
    unittest.main()
