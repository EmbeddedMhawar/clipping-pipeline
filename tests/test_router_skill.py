#!/usr/bin/env python3
"""
tests/test_router_skill.py

Test suite for Ticket #4:
- skills/clipping-pipeline/SKILL.md (Master Pipeline Router Skill)
- Router skill frontmatter and model-invoked trigger matchers
- Standardized 7-step sequence specification
- State engine query integration (scripts/clipping_state.py status)
- Pre-flight transition gate enforcement (scripts/clipping_state.py validate --step <step>)
- Context-isolated config extraction (scripts/clipping_state.py get-step-config --step <step>)
- Clean handoff logic to clipping-guidelines
- Completion criteria and writing-for-agents progressive disclosure
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills" / "clipping-pipeline"
SCRIPTS_DIR = REPO_ROOT / "scripts"
REFERENCES_DIR = REPO_ROOT / "references"

EXPECTED_7_STEPS = [
    "clipping-guidelines",
    "clipping-transcription",
    "clipping-hook-hunter",
    "clipping-assembly",
    "clipping-captions",
    "clipping-vfx-sfx",
    "clipping-qc-packager",
]


class TestRouterSkillFrontmatter(unittest.TestCase):
    """Verifies skills/clipping-pipeline/SKILL.md frontmatter matches specifications."""

    def setUp(self):
        self.skill_file = SKILLS_DIR / "SKILL.md"

    def test_skill_file_exists(self):
        self.assertTrue(
            self.skill_file.is_file(),
            f"Expected router skill file at {self.skill_file}",
        )

    def test_frontmatter_structure_and_model_invocation(self):
        content = self.skill_file.read_text(encoding="utf-8")
        self.assertTrue(
            content.startswith("---"), "SKILL.md must start with YAML frontmatter delimiter '---'"
        )
        parts = content.split("---", 2)
        self.assertGreaterEqual(len(parts), 3, "Invalid YAML frontmatter structure")
        frontmatter = parts[1]

        # Verify skill name
        self.assertIn("name: clipping-pipeline", frontmatter)

        # Model-invoked: must NOT have disable-model-invocation: true
        self.assertNotIn(
            "disable-model-invocation: true",
            frontmatter,
            "Master router skill must be model-invoked to enable agent reach",
        )

    def test_frontmatter_trigger_phrases(self):
        content = self.skill_file.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        frontmatter = parts[1]

        # Trigger phrases required per review findings:
        required_triggers = [
            "clipping pipeline",
            "execution workflow",
            "7 gated stages",
            "pre-flight transition checks",
        ]
        for trigger in required_triggers:
            self.assertIn(
                trigger.lower(),
                frontmatter.lower(),
                f"Frontmatter must contain trigger phrase '{trigger}'",
            )


class TestRouterSkillSpecification(unittest.TestCase):
    """Verifies skills/clipping-pipeline/SKILL.md specifies the 7-step sequence and CLI mechanics."""

    def setUp(self):
        self.skill_file = SKILLS_DIR / "SKILL.md"

    def test_skill_documents_standardized_7_step_sequence(self):
        content = self.skill_file.read_text(encoding="utf-8")

        for step in EXPECTED_7_STEPS:
            self.assertIn(
                step,
                content,
                f"Router skill must specify step '{step}' in pipeline architecture",
            )

        # Verify ordering in document: each step must appear in sequence
        last_pos = -1
        for step in EXPECTED_7_STEPS:
            pos = content.find(step)
            self.assertGreater(
                pos,
                last_pos,
                f"Step '{step}' must be documented after previous step in sequential order",
            )
            last_pos = pos

    def test_skill_documents_state_engine_status_query(self):
        content = self.skill_file.read_text(encoding="utf-8")
        self.assertIn(
            "clipping_state.py status",
            content,
            "Router skill must instruct checking status via 'clipping_state.py status'",
        )

    def test_skill_documents_preflight_gate_enforcement(self):
        content = self.skill_file.read_text(encoding="utf-8")
        self.assertIn(
            "clipping_state.py validate",
            content,
            "Router skill must enforce gate validation via 'clipping_state.py validate --step'",
        )
        self.assertIn(
            "--step",
            content,
            "Validation command must specify target step flag '--step'",
        )
        # Blocks premature transitions
        self.assertTrue(
            "exit code 2" in content.lower() or "blocked" in content.lower(),
            "Router skill must specify pre-flight blocker semantics",
        )

    def test_skill_documents_context_isolated_config_extraction(self):
        content = self.skill_file.read_text(encoding="utf-8")
        self.assertIn(
            "clipping_state.py get-step-config",
            content,
            "Router skill must extract isolated step parameters via 'clipping_state.py get-step-config'",
        )

    def test_skill_documents_clean_guidelines_handoff(self):
        content = self.skill_file.read_text(encoding="utf-8")
        self.assertIn(
            "clipping-guidelines",
            content,
            "Router skill must reference clipping-guidelines for initial ingestion",
        )
        self.assertTrue(
            "guidelines_approved" in content,
            "Router skill must check guidelines_approved state before proceeding",
        )

    def test_skill_adheres_to_writing_for_agents_completion_criteria(self):
        content = self.skill_file.read_text(encoding="utf-8")
        self.assertIn(
            "Completion Criteria",
            content,
            "Skill must define explicit, checkable Completion Criteria",
        )


class TestRouterSkillCLIIntegration(unittest.TestCase):
    """End-to-end integration tests confirming CLI commands referenced in SKILL.md execute properly."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.tmp_dir.name)
        self.cli_path = SCRIPTS_DIR / "clipping_state.py"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def run_cli(self, args, check=False):
        cmd = [sys.executable, str(self.cli_path)] + args
        return subprocess.run(cmd, capture_output=True, text=True, check=check)

    def test_pipeline_router_flow_commands(self):
        # 1. State uninitialized -> validate fails with code 2
        res_val0 = self.run_cli(["validate", "--step", "clipping-guidelines", "--dir", str(self.project_dir)])
        self.assertEqual(res_val0.returncode, 2)

        # 2. Router runs init
        res_init = self.run_cli(["init", "--dir", str(self.project_dir)])
        self.assertEqual(res_init.returncode, 0)

        # 3. Router checks status -> guidelines_approved is False, next step is clipping-guidelines
        res_stat = self.run_cli(["status", "--dir", str(self.project_dir), "--json"])
        self.assertEqual(res_stat.returncode, 0)
        status_data = json.loads(res_stat.stdout)
        self.assertFalse(status_data.get("guidelines_approved"))
        self.assertEqual(status_data.get("current_step"), "clipping-guidelines")

        # 4. Attempting to run downstream step clipping-transcription -> blocked with code 2
        res_val_trans = self.run_cli(["validate", "--step", "clipping-transcription", "--dir", str(self.project_dir)])
        self.assertEqual(res_val_trans.returncode, 2)
        self.assertIn("Pre-flight Gate Blocked", res_val_trans.stderr)

        # 5. Ingest brief and approve guidelines
        brief_data = {
            "campaign": {"title": "Router Test Campaign", "project": "router-test"},
            "global_rules": {"duration": {"ideal_min": 25.0, "ideal_max": 45.0}},
        }
        brief_path = self.project_dir / "campaign_brief.json"
        brief_path.write_text(json.dumps(brief_data), encoding="utf-8")

        res_ingest = self.run_cli(["ingest-brief", "--brief", str(brief_path), "--dir", str(self.project_dir)])
        self.assertEqual(res_ingest.returncode, 0)

        res_appr = self.run_cli(["approve", "--step", "clipping-guidelines", "--dir", str(self.project_dir)])
        self.assertEqual(res_appr.returncode, 0)

        # 6. Pre-flight validation for clipping-transcription now passes (code 0)
        res_val_unblock = self.run_cli(["validate", "--step", "clipping-transcription", "--dir", str(self.project_dir)])
        self.assertEqual(res_val_unblock.returncode, 0)
        self.assertIn("Pre-flight Gate Passed", res_val_unblock.stdout)

        # 7. Isolated step config extraction for transcription returns valid config slice
        res_cfg = self.run_cli(["get-step-config", "--step", "clipping-transcription", "--dir", str(self.project_dir)])
        self.assertEqual(res_cfg.returncode, 0)
        cfg = json.loads(res_cfg.stdout)
        self.assertIn("sample_rate", cfg)
        self.assertIn("phonetic_dictionary", cfg)


if __name__ == "__main__":
    unittest.main()
