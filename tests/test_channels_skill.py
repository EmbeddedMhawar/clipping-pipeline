#!/usr/bin/env python3
"""
tests/test_channels_skill.py

Test suite for Ticket #12:
- skills/clipping-channels/SKILL.md (Companion Skill for Channel Portfolio & Warmup)
- Skill frontmatter and model-invoked trigger matchers
- Onboarding interview protocol (accounts, platforms, handles, age, post history, shadowban check)
- Preferred device transfer discovery (local_qr, adb_push, cloud_folder, webhook)
- Generation of channel_portfolio_audit.md diagnostic artifact
- 4-stage warmup protocol instructions and daily task checklists (Cold Lurker, Seeding, Ramp-Up, Mature)
- Health gate view-count validation (200-500 views) and 72-hour Account Cooldown
- CLI commands reference (scripts/clipping_channels.py)
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills" / "clipping-channels"
SKILL_FILE = SKILLS_DIR / "SKILL.md"


class TestChannelsSkillFrontmatter(unittest.TestCase):
    """Verifies skills/clipping-channels/SKILL.md frontmatter matches specifications."""

    def test_skill_file_exists(self):
        self.assertTrue(
            SKILL_FILE.is_file(),
            f"Expected clipping-channels skill file at {SKILL_FILE}",
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

        self.assertIn("name: clipping-channels", frontmatter)
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
            "channel portfolio",
            "warmup",
            "health gate",
        ]
        for trigger in required_triggers:
            self.assertIn(
                trigger.lower(),
                frontmatter.lower(),
                f"Frontmatter must contain trigger phrase '{trigger}'",
            )


class TestChannelsSkillOnboardingProtocol(unittest.TestCase):
    """Verifies onboarding interview protocol and discovery in SKILL.md."""

    def setUp(self):
        self.content = SKILL_FILE.read_text(encoding="utf-8") if SKILL_FILE.is_file() else ""

    def test_onboarding_interview_protocol_covers_account_discovery(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        # Must discover accounts, platforms, handles, age, post history, shadowban check
        required_elements = [
            "platform",
            "handle",
            "age",
            "post history",
            "shadowban",
        ]
        for element in required_elements:
            self.assertIn(
                element.lower(),
                self.content.lower(),
                f"SKILL.md onboarding protocol must address '{element}'",
            )

        # Platforms covered
        for platform in ["TikTok", "Instagram Reels", "YouTube Shorts"]:
            self.assertIn(
                platform,
                self.content,
                f"SKILL.md must explicitly reference platform '{platform}'",
            )

    def test_device_transfer_discovery(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        # Must cover discovery of transfer methods: local_qr, adb_push, cloud_folder, webhook
        transfer_methods = ["local_qr", "adb_push", "cloud_folder", "webhook"]
        for method in transfer_methods:
            self.assertIn(
                method,
                self.content,
                f"SKILL.md must document device transfer option '{method}'",
            )

    def test_diagnostic_artifact_generation(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        self.assertIn("channel_portfolio_audit.md", self.content)
        self.assertIn("audit", self.content)


class TestChannelsSkillWarmupProtocol(unittest.TestCase):
    """Verifies 4-stage warmup lifecycle protocol and daily tasks in SKILL.md."""

    def setUp(self):
        self.content = SKILL_FILE.read_text(encoding="utf-8") if SKILL_FILE.is_file() else ""

    def test_covers_all_four_warmup_stages(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        stages = ["Cold Lurker", "Seeding", "Ramp-Up", "Mature"]
        for stage in stages:
            self.assertIn(
                stage,
                self.content,
                f"SKILL.md must document warmup stage '{stage}'",
            )

    def test_daily_task_checklists_and_guidelines(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        self.assertIn("daily-tasks", self.content)
        # Should document browsing minutes, post limits, interactions, and spacing
        expected_terms = [
            "daily_post_limit",
            "browsing",
            "spacing",
        ]
        for term in expected_terms:
            self.assertIn(
                term.lower(),
                self.content.lower(),
                f"SKILL.md must mention '{term}' in daily task/warmup context",
            )


class TestChannelsSkillHealthGateAndCooldown(unittest.TestCase):
    """Verifies health gate view-count validation and 72-hour account cooldown."""

    def setUp(self):
        self.content = SKILL_FILE.read_text(encoding="utf-8") if SKILL_FILE.is_file() else ""

    def test_health_gate_view_validation(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        self.assertIn("health gate", self.content.lower())
        self.assertIn("200", self.content)
        self.assertIn("500", self.content)

    def test_account_cooldown_72_hours(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        self.assertIn("Account Cooldown", self.content)
        self.assertIn("72", self.content)
        self.assertIn("cooldown", self.content.lower())


class TestChannelsSkillCLIReference(unittest.TestCase):
    """Verifies CLI commands reference for scripts/clipping_channels.py."""

    def setUp(self):
        self.content = SKILL_FILE.read_text(encoding="utf-8") if SKILL_FILE.is_file() else ""

    def test_cli_script_reference_and_commands(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        self.assertIn("scripts/clipping_channels.py", self.content)

        commands = [
            "init",
            "add",
            "audit",
            "daily-tasks",
            "advance-stage",
            "cooldown",
            "log-post",
            "transfer",
        ]
        for cmd in commands:
            self.assertIn(
                cmd,
                self.content,
                f"SKILL.md must document CLI command '{cmd}'",
            )


class TestChannelsSkillReferences(unittest.TestCase):
    """Verifies references to schemas, ADRs, and domain glossary."""

    def setUp(self):
        self.content = SKILL_FILE.read_text(encoding="utf-8") if SKILL_FILE.is_file() else ""

    def test_references_and_data_contracts(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Missing {SKILL_FILE}")
        self.assertIn("references/CHANNEL_PORTFOLIO_SCHEMA.md", self.content)
        self.assertIn("GLOSSARY.md", self.content)
        self.assertIn("channels.json", self.content)


if __name__ == "__main__":
    unittest.main()
