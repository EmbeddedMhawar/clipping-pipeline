#!/usr/bin/env python3
"""
tests/test_qc_packager_skill.py

Test suite for Step 7 Skill (skills/clipping-qc-packager/SKILL.md).
Verifies frontmatter, triggers, operating protocol, and completion criteria.
"""

from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_ROOT / "skills" / "clipping-qc-packager" / "SKILL.md"


class TestQCPackagerSkill(unittest.TestCase):
    """Verifies skills/clipping-qc-packager/SKILL.md matches specifications."""

    def test_skill_file_exists(self):
        self.assertTrue(SKILL_PATH.is_file(), f"Expected skill file at {SKILL_PATH}")

    def test_frontmatter_structure(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---"), "SKILL.md must start with YAML frontmatter delimiter '---'")
        parts = content.split("---", 2)
        self.assertGreaterEqual(len(parts), 3, "Invalid YAML frontmatter structure")
        frontmatter = parts[1]

        self.assertIn("name: clipping-qc-packager", frontmatter)
        self.assertIn("description:", frontmatter)
        self.assertNotIn("disable-model-invocation: true", frontmatter)

    def test_protocol_and_compliance_specifications(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        required_terms = [
            "-14.0 LUFS",
            "EBU R128",
            "true peak",
            "whop",
            "30-minute",
            "caption_closers",
            "clipping_qc_packager.py",
            "clipping_state.py",
            "checkpoint_clipping-qc-packager.md",
            "RequestFeedback: true",
            "0010-dedicated-pipeline-publishing-step.md",
            "clipping-publisher",
        ]
        for term in required_terms:
            self.assertIn(term.lower(), content.lower(), f"SKILL.md must document '{term}'")


if __name__ == "__main__":
    unittest.main()
