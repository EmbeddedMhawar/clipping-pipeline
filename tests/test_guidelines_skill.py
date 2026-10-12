#!/usr/bin/env python3
"""
tests/test_guidelines_skill.py

Test suite for Ticket #3:
- references/CAMPAIGN_BRIEF_SCHEMA.md (JSON schema and documentation)
- skills/clipping-guidelines/SKILL.md (frontmatter, triggers, gate criteria)
- scripts/ingest_guidelines.py (ingestion parser, default injector, review artifact, state integration)
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
SCRIPTS_DIR = REPO_ROOT / "scripts"
REFERENCES_DIR = REPO_ROOT / "references"
SKILLS_DIR = REPO_ROOT / "skills" / "clipping-guidelines"


class TestCampaignBriefSchema(unittest.TestCase):
    """Verifies references/CAMPAIGN_BRIEF_SCHEMA.md exists and defines valid schema."""

    def setUp(self):
        self.schema_doc = REFERENCES_DIR / "CAMPAIGN_BRIEF_SCHEMA.md"

    def test_schema_file_exists(self):
        self.assertTrue(
            self.schema_doc.is_file(),
            f"Expected schema doc at {self.schema_doc}",
        )

    def test_schema_contains_valid_json_schema_block(self):
        content = self.schema_doc.read_text(encoding="utf-8")
        # Extract json or jsonc code block
        match = re.search(r"```(?:json|jsonc)\s*\n(\{.*?\})\n```", content, re.DOTALL)
        self.assertIsNotNone(
            match, "CAMPAIGN_BRIEF_SCHEMA.md must contain a JSON schema code block"
        )
        schema_json = json.loads(match.group(1))
        self.assertIn("$schema", schema_json)
        self.assertEqual(schema_json.get("type"), "object")
        properties = schema_json.get("properties", {})
        self.assertIn("campaign", properties)
        self.assertIn("global_rules", properties)
        self.assertIn("platform_overrides", properties)
        self.assertIn("defaults_applied", properties)

    def test_schema_documents_cole_corcoran_rules(self):
        content = self.schema_doc.read_text(encoding="utf-8")
        required_terms = [
            "global_rules",
            "platform_overrides",
            "tier1_geo_min_pct",
            "engagement_min_pct",
            "caption_closers",
            "watermark",
            "loudness_target_lufs",
            "defaults_applied",
            "youtube_shorts",
            "tiktok",
            "instagram_reels",
        ]
        for term in required_terms:
            self.assertIn(term, content, f"CAMPAIGN_BRIEF_SCHEMA.md must document '{term}'")


class TestGuidelinesSkillFrontmatter(unittest.TestCase):
    """Verifies skills/clipping-guidelines/SKILL.md follows writing-for-agents."""

    def setUp(self):
        self.skill_file = SKILLS_DIR / "SKILL.md"

    def test_skill_file_exists(self):
        self.assertTrue(self.skill_file.is_file(), f"Missing {self.skill_file}")

    def test_skill_frontmatter_and_triggers(self):
        content = self.skill_file.read_text(encoding="utf-8")
        # Check frontmatter bounds
        self.assertTrue(content.startswith("---"), "SKILL.md must start with YAML frontmatter")
        parts = content.split("---", 2)
        self.assertGreaterEqual(len(parts), 3, "Invalid frontmatter structure in SKILL.md")
        frontmatter = parts[1]

        self.assertIn("name: clipping-guidelines", frontmatter)
        # Check model-invoked (no disable-model-invocation: true)
        self.assertNotIn("disable-model-invocation: true", frontmatter)

        # Check required sharp leading trigger words in description
        required_triggers = [
            "clipping guidelines",
            "campaign brief",
            "ingest guidelines",
            "whop rules",
            "payout rules",
        ]
        for trigger in required_triggers:
            self.assertIn(
                trigger.lower(),
                frontmatter.lower(),
                f"Frontmatter description must include trigger phrase '{trigger}'",
            )

    def test_skill_body_includes_completion_criteria_and_gate(self):
        content = self.skill_file.read_text(encoding="utf-8")
        self.assertIn("references/CAMPAIGN_BRIEF_SCHEMA.md", content)
        self.assertIn("[Default Applied]", content)
        self.assertIn("campaign_brief.json", content)
        self.assertIn("RequestFeedback: true", content)
        self.assertIn("guidelines_approved", content)
        self.assertIn("clipping_state.py approve", content)


class TestGuidelinesIngestionParser(unittest.TestCase):
    """Tests scripts/ingest_guidelines.py ingestion, normalizer, and review artifact."""

    SAMPLE_GUIDELINES = """# N3on x MPJ Clipping Campaign Guidelines

**Campaign Document:** [Notion Source](https://example.com/notion)
**Target Video:** [N3on Gets Real About Fame (1:36:59)](https://www.youtube.com/watch?v=GfVYVEPSLIM)
**Channel:** `@mpj` (Curious Mike)
**Submission Form:** [Google Form](https://example.com/form)

## 1. Campaign Details & Financials

| Key Metric | Value |
| :--- | :--- |
| **Pay Rate** | **$1.00 per 1,000 verified views** |
| **Minimum Payout** | **$2.00 (2,000 views minimum)** |
| **Maximum per Clip** | **$300.00** (views capped at 300,000 per clip) |
| **Eligible Platforms** | **TikTok**, **Instagram Reels**, **YouTube Shorts** |
| **Posting Frequency** | 1 to 4 clips/day per account |

## 2. The 7 Non-Negotiable Rules

1. **Rule 1: At least 40% Tier-1 Viewers (US, Canada, UK combined)**
2. **Rule 2: At least 1% Engagement Rate**
3. **Rule 3: No AI-Generated Video / Auto-Clippers**
4. **Rule 4: At least 2,000 Views ($2 floor)**
5. **Rule 5: Only the N3on Episode**
6. **Rule 6: Mandatory `YT: @mpj` Watermark**
   Must use `assets/watermark_yt_mpj.png`. Must stay on-screen for entire duration.
   Do not place in 4 corners.
7. **Rule 7: Mandatory Approved Caption Closer**
   Every single caption must end with one of the 12 approved closers:
   1. `watch the full episode @mpj on youtube`
   2. `full episode is on @mpj on youtube`
   3. `the whole thing is up on @mpj on youtube`
   4. `go watch the full one @mpj on youtube`
   5. `full ep is on @mpj on youtube`
   6. `this is from the full episode @mpj on youtube`
   7. `catch the rest @mpj on youtube`
   8. `the full sit down is on @mpj on youtube`
   9. `watch it all @mpj on youtube`
   10. `full interview is on @mpj on youtube`
   11. `rest of it is on @mpj on youtube`
   12. `whole episode @mpj on youtube`

## 4. "One Clip, One Post" Rule
Every edit gets posted once.

## 6. Bio Templates
- **Instagram Bio:**
  fan page of @curiousmike
  not affiliated
- **TikTok Bio:**
  fan page of @curiousmike
  not affiliated
- **YouTube Shorts Channel Description:**
  fan page of @mpj
  not affiliated
"""

    def setUp(self):
        self.ingest_script = SCRIPTS_DIR / "ingest_guidelines.py"
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.tmp_dir.name)

        # Initialize clipping state in tmp_dir
        cmd_init = [
            sys.executable,
            str(SCRIPTS_DIR / "clipping_state.py"),
            "init",
            "--dir",
            str(self.project_dir),
        ]
        res = subprocess.run(cmd_init, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Failed init: {res.stderr}")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_ingest_script_exists(self):
        self.assertTrue(
            self.ingest_script.is_file(),
            f"Missing ingestion script {self.ingest_script}",
        )

    def test_parse_sample_guidelines(self):
        sample_path = self.project_dir / "CAMPAIGN_GUIDELINES.md"
        sample_path.write_text(self.SAMPLE_GUIDELINES, encoding="utf-8")

        out_brief = self.project_dir / "campaign_brief.json"
        out_artifact = self.project_dir / "campaign_brief_review.md"

        cmd = [
            sys.executable,
            str(self.ingest_script),
            "--file",
            str(sample_path),
            "--dir",
            str(self.project_dir),
            "--output-brief",
            str(out_brief),
            "--output-artifact",
            str(out_artifact),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Ingestion failed: {res.stderr}\nStdout: {res.stdout}")
        self.assertTrue(out_brief.is_file(), "campaign_brief.json was not created")
        self.assertTrue(out_artifact.is_file(), "campaign_brief_review.md was not created")

        with open(out_brief, "r", encoding="utf-8") as f:
            brief = json.load(f)

        # Verify parsed properties
        campaign = brief.get("campaign", {})
        self.assertEqual(campaign.get("title"), "N3on x MPJ Clipping Campaign")
        self.assertEqual(campaign.get("client"), "Curious Mike")
        self.assertIn("GfVYVEPSLIM", campaign.get("source_video", {}).get("url", ""))

        economics = campaign.get("economics", {})
        self.assertEqual(economics.get("rate_per_1k_views"), 1.0)
        self.assertEqual(economics.get("min_payout_views"), 2000)
        self.assertEqual(economics.get("max_dollar_per_clip"), 300.0)

        global_rules = brief.get("global_rules", {})
        self.assertEqual(global_rules.get("tier1_geo_min_pct"), 40.0)
        self.assertEqual(global_rules.get("engagement_min_pct"), 1.0)
        self.assertEqual(len(global_rules.get("caption_closers", [])), 12)
        self.assertEqual(global_rules.get("watermark", {}).get("asset_path"), "assets/watermark_yt_mpj.png")
        self.assertTrue(global_rules.get("single_post_per_edit"))

        # Verify state engine was updated
        state_file = self.project_dir / ".clipping_state.json"
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        self.assertFalse(state.get("guidelines_approved"))
        self.assertEqual(state.get("steps", {}).get("clipping-guidelines", {}).get("status"), "awaiting_approval")
        # Check params sliced into downstream step
        qc_params = state.get("steps", {}).get("clipping-qc-packager", {}).get("params", {})
        self.assertEqual(len(qc_params.get("caption_closers", [])), 12)

    def test_default_applied_injections_for_sparse_brief(self):
        sparse_text = "Acme Stream Clips: Earn $1 per 1000 views. Post on YouTube Shorts."
        out_brief = self.project_dir / "campaign_brief.json"
        out_artifact = self.project_dir / "campaign_brief_review.md"

        cmd = [
            sys.executable,
            str(self.ingest_script),
            "--text",
            sparse_text,
            "--dir",
            str(self.project_dir),
            "--output-brief",
            str(out_brief),
            "--output-artifact",
            str(out_artifact),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Ingestion failed: {res.stderr}\nStdout: {res.stdout}")

        with open(out_brief, "r", encoding="utf-8") as f:
            brief = json.load(f)

        defaults_applied = brief.get("defaults_applied", [])
        self.assertIsInstance(defaults_applied, list)
        self.assertGreater(len(defaults_applied), 0, "Sparse brief must inject Cole Corcoran defaults")

        # Verify defaults presence
        applied_str = " ".join(defaults_applied)
        self.assertIn("duration", applied_str.lower())
        self.assertIn("audio", applied_str.lower())
        self.assertIn("tier1", applied_str.lower())

        # Check artifact contains [Default Applied] markers
        artifact_content = out_artifact.read_text(encoding="utf-8")
        self.assertIn("[Default Applied]", artifact_content)
        self.assertIn("Campaign Summary & Economics", artifact_content)
        self.assertIn("Strict Non-Negotiable Rules", artifact_content)
        self.assertIn("Platform Specific Overrides", artifact_content)
        self.assertIn("Action Required: Approval Gate Prompt", artifact_content)

    def test_ingest_existing_brief_json(self):
        brief_data = {
            "version": "1.0.0",
            "campaign": {
                "title": "Custom JSON Brief",
                "client": "Custom Creator",
                "project": "custom-json",
                "source_video": {"url": "https://youtube.com/watch?v=12345"},
                "economics": {"rate_per_1k_views": 2.0, "min_payout_views": 1000, "max_dollar_per_clip": 500.0},
                "platforms": ["TikTok"],
            },
            "global_rules": {
                "duration": {"min_seconds": 20.0, "max_seconds": 60.0},
                "tier1_geo_min_pct": 50.0,
                "engagement_min_pct": 2.0,
                "watermark": {"required": True, "asset_path": "assets/custom.png"},
                "caption_closers": ["custom closer @channel"],
                "audio": {"zero_background_music": True, "loudness_target_lufs": -14.0},
            },
        }
        json_file = self.project_dir / "custom_input.json"
        json_file.write_text(json.dumps(brief_data), encoding="utf-8")
        out_artifact = self.project_dir / "custom_review.md"

        cmd = [
            sys.executable,
            str(self.ingest_script),
            "--brief",
            str(json_file),
            "--dir",
            str(self.project_dir),
            "--output-artifact",
            str(out_artifact),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Error: {res.stderr}")
        self.assertTrue(out_artifact.is_file())
        art_text = out_artifact.read_text(encoding="utf-8")
        self.assertIn("Custom JSON Brief", art_text)
        self.assertIn("50.0% Tier-1 Viewers", art_text)

    def test_cli_error_on_nonexistent_file(self):
        cmd = [
            sys.executable,
            str(self.ingest_script),
            "--file",
            str(self.project_dir / "nonexistent.md"),
            "--dir",
            str(self.project_dir),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not found", res.stderr.lower())

    def test_pipeline_gate_unblocking_after_approval(self):
        sample_path = self.project_dir / "CAMPAIGN_GUIDELINES.md"
        sample_path.write_text(self.SAMPLE_GUIDELINES, encoding="utf-8")

        # Ingest guidelines
        cmd_ingest = [
            sys.executable,
            str(self.ingest_script),
            "--file",
            str(sample_path),
            "--dir",
            str(self.project_dir),
        ]
        res_ingest = subprocess.run(cmd_ingest, capture_output=True, text=True)
        self.assertEqual(res_ingest.returncode, 0)

        # Pre-flight validate downstream step -> MUST FAIL with code 2
        cmd_val_fail = [
            sys.executable,
            str(SCRIPTS_DIR / "clipping_state.py"),
            "validate",
            "--step",
            "clipping-transcription",
            "--dir",
            str(self.project_dir),
        ]
        res_val_fail = subprocess.run(cmd_val_fail, capture_output=True, text=True)
        self.assertEqual(res_val_fail.returncode, 2, "Expected exit code 2 when guidelines unapproved")

        # Approve guidelines
        cmd_approve = [
            sys.executable,
            str(SCRIPTS_DIR / "clipping_state.py"),
            "approve",
            "--step",
            "clipping-guidelines",
            "--dir",
            str(self.project_dir),
        ]
        res_appr = subprocess.run(cmd_approve, capture_output=True, text=True)
        self.assertEqual(res_appr.returncode, 0)

        # Pre-flight validate downstream step -> MUST PASS with code 0
        cmd_val_pass = [
            sys.executable,
            str(SCRIPTS_DIR / "clipping_state.py"),
            "validate",
            "--step",
            "clipping-transcription",
            "--dir",
            str(self.project_dir),
        ]
        res_val_pass = subprocess.run(cmd_val_pass, capture_output=True, text=True)
        self.assertEqual(res_val_pass.returncode, 0, "Expected exit code 0 when guidelines approved")


if __name__ == "__main__":
    unittest.main()

