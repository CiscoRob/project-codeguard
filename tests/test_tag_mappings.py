"""Known tag set used by rule validation."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tag_mappings import KNOWN_TAGS  # noqa: E402


class TagMappingsTests(unittest.TestCase):
    def test_known_rule_tags_are_available(self):
        self.assertTrue({"authentication", "data-security", "web"} <= KNOWN_TAGS)


if __name__ == "__main__":
    unittest.main()
