#!/usr/bin/env python3
"""
tests/test_captions_skill.py

Test suite for Step 5 Skill (skills/clipping-captions/SKILL.md).
Verifies frontmatter, triggers, operating protocol, and completion criteria.
"""

from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_ROOT / "skills" / "clipping-captions" / "SKILL.md"


class TestCaptionsSkill(unittest.TestCase):
    """Verifies skills/clipping-captions/SKILL.md matches specifications."""

    def test_skill_file_exists(self):
        self.assertTrue(SKILL_PATH.is_file(), f"Expected skill file at {SKILL_PATH}")

    def test_frontmatter_structure(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---"), "SKILL.md must start with YAML frontmatter delimiter '---'")
        parts = content.split("---", 2)
        self.assertGreaterEqual(len(parts), 3, "Invalid YAML frontmatter structure")
        frontmatter = parts[1]

        self.assertIn("name: clipping-captions", frontmatter)
        self.assertIn("description:", frontmatter)
        self.assertNotIn("disable-model-invocation: true", frontmatter)

    def test_protocol_and_safe_zone_specifications(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        required_terms = [
            "MarginV=420",
            "safe zone",
            "Zylok",
            "Neon Lime",
            "Crimson Red",
            "clipping_captions.py",
            "clipping_state.py",
            "checkpoint_clipping-captions.md",
            "RequestFeedback: true",
            "Dialogue Captions",
        ]
        for term in required_terms:
            self.assertIn(term, content, f"SKILL.md must document '{term}'")


if __name__ == "__main__":
    unittest.main()
