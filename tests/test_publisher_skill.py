#!/usr/bin/env python3
"""
tests/test_publisher_skill.py

Test suite for Ticket #20:
- skills/clipping-publisher/SKILL.md (Step 8 clipping-publisher Skill)
- Skill frontmatter and model-invoked trigger matchers
- Strict adherence to /writing-for-agents:
  * Front-loaded context pointers (GLOSSARY.md, CHANNEL_PORTFOLIO_SCHEMA.md, ADR 0010)
  * Information hierarchy and progressive disclosure
  * Leading words (tight, seam, tracer bullets, positive phrasing)
  * Checkable and exhaustive completion criteria
- Clear sequential steps:
  1. State & Pre-Flight Gate Inspection (scripts/clipping_state.py validate --step clipping-publisher)
  2. Brand Cluster Matching & Zero Duplicate Platform Allocation
  3. Multi-Platform Publication Execution (YouTube Shorts API + BrowserOS Neo fallback, TikTok/IG mobile device delivery + caption bundling)
  4. Publication Manifest Persistence & Step Approval (scripts/clipping_state.py approve --step clipping-publisher)
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "clipping-publisher"
SKILL_FILE = SKILL_DIR / "SKILL.md"


class TestPublisherSkillFrontmatter(unittest.TestCase):
    """Verifies skills/clipping-publisher/SKILL.md frontmatter matches specifications."""

    def test_skill_file_exists(self):
        self.assertTrue(
            SKILL_FILE.is_file(),
            f"Expected clipping-publisher skill file at {SKILL_FILE}",
        )

    def test_frontmatter_structure_and_model_invocation(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        content = SKILL_FILE.read_text(encoding="utf-8")
        self.assertTrue(
            content.startswith("---"),
            "SKILL.md must start with YAML frontmatter delimiter '---'",
        )
        parts = content.split("---", 2)
        self.assertGreaterEqual(len(parts), 3, "Invalid YAML frontmatter structure")
        frontmatter = parts[1]

        self.assertIn("name: clipping-publisher", frontmatter)
        self.assertNotIn(
            "disable-model-invocation: true",
            frontmatter,
            "Skill must be model-invoked for agent discovery",
        )

    def test_frontmatter_trigger_phrases(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        content = SKILL_FILE.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        frontmatter = parts[1]

        required_triggers = [
            "clipping publisher",
            "brand cluster",
            "publishing",
        ]
        for trigger in required_triggers:
            self.assertIn(
                trigger.lower(),
                frontmatter.lower(),
                f"Frontmatter must contain trigger phrase '{trigger}'",
            )


class TestPublisherSkillSpecification(unittest.TestCase):
    """Verifies skills/clipping-publisher/SKILL.md specification and information hierarchy."""

    def setUp(self):
        self.content = SKILL_FILE.read_text(encoding="utf-8") if SKILL_FILE.is_file() else ""

    def test_context_pointers_exist(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        # Must point to GLOSSARY.md, CHANNEL_PORTFOLIO_SCHEMA.md, ADR 0010
        self.assertIn("GLOSSARY.md", self.content)
        self.assertIn("CHANNEL_PORTFOLIO_SCHEMA.md", self.content)
        self.assertIn("0010-dedicated-pipeline-publishing-step.md", self.content)

    def test_sequential_steps_documented(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        # Verify 4 ordered steps
        expected_steps = [
            "State & Pre-Flight Gate Inspection",
            "Brand Cluster Matching & Zero Duplicate Platform Allocation",
            "Multi-Platform Publication Execution",
            "Publication Manifest Persistence & Step Approval",
        ]
        last_pos = -1
        for step in expected_steps:
            pos = self.content.find(step)
            self.assertNotEqual(
                pos, -1, f"SKILL.md must document step heading containing '{step}'"
            )
            self.assertGreater(
                pos,
                last_pos,
                f"Step '{step}' must appear in sequential order after previous step",
            )
            last_pos = pos

    def test_cli_commands_documented(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        # Step 1 gate check
        self.assertIn("clipping_state.py validate --step clipping-publisher", self.content)
        # Step 3 publisher CLI execution
        self.assertIn("clipping_publisher.py publish", self.content)
        # Step 4 step approval
        self.assertIn("clipping_state.py approve --step clipping-publisher", self.content)

    def test_publishing_engines_and_platforms_covered(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        # YouTube Data API v3 and BrowserOS Neo fallback
        self.assertIn("YouTube Shorts", self.content)
        self.assertIn("BrowserOS Neo", self.content)
        # Mobile transfer protocols & caption bundling
        self.assertIn("caption.txt", self.content)
        self.assertIn("TikTok", self.content)
        self.assertIn("Instagram Reels", self.content)

    def test_completion_criteria_defined(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        self.assertIn("Completion Criteria", self.content)
        self.assertIn("publication_manifest", self.content)


if __name__ == "__main__":
    unittest.main()
