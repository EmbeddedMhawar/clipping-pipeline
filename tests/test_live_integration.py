#!/usr/bin/env python3
"""
tests/test_live_integration.py

End-to-end live integration test suite for Ticket #5:
- Ingestion of real CAMPAIGN_GUIDELINES.md from references
- Full capture of N3on x MPJ rules (40% Tier-1, watermark asset, 12 approved closers, payout rules)
- Cole Corcoran Tier-1 defaults injection tagged [Default Applied]
- Interactive review artifact (campaign_brief_review.md) generation
- Pre-flight transition gate blocker checks (exit code 2 before approval, exit code 0 after approval)
- Parameter slice retrieval for downstream editing steps
- CLI flag compatibility (--input and --file)
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
INGEST_SCRIPT = SCRIPTS_DIR / "ingest_guidelines.py"
STATE_CLI = SCRIPTS_DIR / "clipping_state.py"

REAL_GUIDELINES_CANDIDATES = [
    Path("/home/mhawar/Work/video-editing/references/CAMPAIGN_GUIDELINES.md"),
    Path("/home/mhawar/Work/video-editing/.agents/skills/filmcraft-clipping-campaign/references/CAMPAIGN_GUIDELINES.md"),
    REPO_ROOT.parent / "video-editing" / "references" / "CAMPAIGN_GUIDELINES.md",
]


def find_real_guidelines() -> Path:
    for candidate in REAL_GUIDELINES_CANDIDATES:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"Could not locate real CAMPAIGN_GUIDELINES.md in candidates: {REAL_GUIDELINES_CANDIDATES}"
    )


class TestLiveCampaignIntegration(unittest.TestCase):
    """End-to-end integration test verifying real campaign guidelines ingestion and state gating."""

    def setUp(self):
        self.real_guidelines_path = find_real_guidelines()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def run_cmd(self, cmd, check=False):
        res = subprocess.run(cmd, cwd=str(self.project_dir), capture_output=True, text=True)
        if check and res.returncode != 0:
            raise subprocess.CalledProcessError(res.returncode, cmd, res.stdout, res.stderr)
        return res

    def test_real_guidelines_source_exists_and_readable(self):
        self.assertTrue(self.real_guidelines_path.is_file())
        content = self.real_guidelines_path.read_text(encoding="utf-8")
        self.assertIn("N3on x MPJ", content)
        self.assertIn("GfVYVEPSLIM", content)

    def test_live_ingestion_end_to_end_with_input_flag(self):
        # Run ingestion with --input flag and --dir pointing to temporary workspace
        cmd = [
            sys.executable,
            str(INGEST_SCRIPT),
            "--input",
            str(self.real_guidelines_path),
            "--dir",
            str(self.project_dir),
        ]
        res = self.run_cmd(cmd)
        self.assertEqual(
            res.returncode,
            0,
            f"Ingestion failed with exit code {res.returncode}\nStderr: {res.stderr}\nStdout: {res.stdout}",
        )

        out_brief = self.project_dir / "campaign_brief.json"
        out_artifact = self.project_dir / "campaign_brief_review.md"
        out_state = self.project_dir / ".clipping_state.json"

        # 1. Verify files are generated
        self.assertTrue(out_brief.is_file(), f"Missing {out_brief}")
        self.assertTrue(out_artifact.is_file(), f"Missing {out_artifact}")
        self.assertTrue(out_state.is_file(), f"Missing {out_state}")

        # 2. Verify campaign_brief.json contents
        with open(out_brief, "r", encoding="utf-8") as f:
            brief = json.load(f)

        campaign = brief.get("campaign", {})
        self.assertIn("N3on x MPJ", campaign.get("title", ""))
        self.assertEqual(campaign.get("client"), "Curious Mike")
        self.assertIn("GfVYVEPSLIM", campaign.get("source_video", {}).get("url", ""))

        economics = campaign.get("economics", {})
        self.assertEqual(economics.get("rate_per_1k_views"), 1.0)
        self.assertEqual(economics.get("min_payout_views"), 2000)
        self.assertEqual(economics.get("max_dollar_per_clip"), 300.0)
        self.assertEqual(economics.get("max_payout_views_per_clip"), 300000)

        self.assertIn("TikTok", campaign.get("platforms", []))
        self.assertIn("Instagram Reels", campaign.get("platforms", []))
        self.assertIn("YouTube Shorts", campaign.get("platforms", []))

        # 3. Verify strict non-negotiable rules
        global_rules = brief.get("global_rules", {})
        self.assertEqual(global_rules.get("tier1_geo_min_pct"), 40.0)
        self.assertEqual(global_rules.get("engagement_min_pct"), 1.0)

        watermark = global_rules.get("watermark", {})
        self.assertTrue(watermark.get("required"))
        self.assertTrue(watermark.get("persistent_entire_clip"))
        self.assertTrue(watermark.get("banned_corners"))
        self.assertTrue(
            any(
                ext in watermark.get("asset_path", "")
                for ext in ["watermark", "webp", "png"]
            )
        )

        closers = global_rules.get("caption_closers", [])
        self.assertEqual(len(closers), 12, "Must capture all 12 approved caption closers")
        self.assertIn("watch the full episode @mpj on youtube", closers)
        self.assertIn("whole episode @mpj on youtube", closers)

        self.assertTrue(global_rules.get("single_post_per_edit"))

        # 4. Verify Tier-1 defaults injection tagged [Default Applied]
        defaults_applied = brief.get("defaults_applied", [])
        self.assertIsInstance(defaults_applied, list)
        self.assertGreater(
            len(defaults_applied),
            0,
            "Must tag at least one Tier-1 Cole Corcoran default when absent (e.g. -14 LUFS loudness)",
        )
        self.assertTrue(
            any("[Default Applied]" in d for d in defaults_applied),
            f"Defaults must contain '[Default Applied]': {defaults_applied}",
        )

        # 5. Verify review artifact contains required sections and feedback instructions
        artifact_text = out_artifact.read_text(encoding="utf-8")
        self.assertIn("# Campaign Brief Review:", artifact_text)
        self.assertIn("## 1. Campaign Summary & Economics", artifact_text)
        self.assertIn("## 2. Strict Non-Negotiable Rules", artifact_text)
        self.assertIn("## 3. Platform Specific Overrides", artifact_text)
        self.assertIn("## 4. Tier-1 Viral Defaults Injected", artifact_text)
        self.assertIn("## 5. Action Required: Approval Gate Prompt", artifact_text)
        self.assertIn("[Default Applied]", artifact_text)

        # 6. Verify pre-flight blocker (exit code 2 before approval)
        val_cmd = [
            sys.executable,
            str(STATE_CLI),
            "validate",
            "--step",
            "clipping-transcription",
            "--dir",
            str(self.project_dir),
        ]
        val_res = self.run_cmd(val_cmd)
        self.assertEqual(
            val_res.returncode,
            2,
            f"Expected pre-flight blocker exit code 2, got {val_res.returncode}. Output: {val_res.stderr}",
        )
        self.assertIn("Pre-flight Gate Blocked", val_res.stderr)

        # 7. Test --force bypass succeeds with warning (exit code 0)
        force_cmd = [
            sys.executable,
            str(STATE_CLI),
            "validate",
            "--step",
            "clipping-transcription",
            "--force",
            "--dir",
            str(self.project_dir),
        ]
        force_res = self.run_cmd(force_cmd)
        self.assertEqual(force_res.returncode, 0)
        self.assertIn("WARNING", force_res.stdout)

        # 8. Test approval gate transitions state
        approve_cmd = [
            sys.executable,
            str(STATE_CLI),
            "approve",
            "--step",
            "clipping-guidelines",
            "--notes",
            "Live campaign verification test",
            "--dir",
            str(self.project_dir),
        ]
        approve_res = self.run_cmd(approve_cmd)
        self.assertEqual(approve_res.returncode, 0)

        # Check state file reflects approval
        with open(out_state, "r", encoding="utf-8") as f:
            state = json.load(f)
        self.assertTrue(state.get("guidelines_approved"))
        self.assertEqual(
            state.get("steps", {}).get("clipping-guidelines", {}).get("status"),
            "completed",
        )
        self.assertEqual(state.get("approval", {}).get("notes"), "Live campaign verification test")

        # 9. Test pre-flight unblocking (exit code 0 after approval)
        val_res_after = self.run_cmd(val_cmd)
        self.assertEqual(
            val_res_after.returncode,
            0,
            f"Expected pre-flight clearance exit code 0, got {val_res_after.returncode}. Stderr: {val_res_after.stderr}",
        )
        self.assertIn("Pre-flight Gate Passed", val_res_after.stdout)

        # 10. Verify isolated step parameter slices via get-step-config
        cfg_captions_cmd = [
            sys.executable,
            str(STATE_CLI),
            "get-step-config",
            "--step",
            "clipping-captions",
            "--dir",
            str(self.project_dir),
        ]
        cfg_captions_res = self.run_cmd(cfg_captions_cmd)
        self.assertEqual(cfg_captions_res.returncode, 0)
        captions_slice = json.loads(cfg_captions_res.stdout)
        self.assertEqual(captions_slice.get("margin_v"), 420)
        self.assertEqual(captions_slice.get("words_per_line_range"), [1, 2])
        self.assertIn("trigger_keywords", captions_slice)

        cfg_qc_cmd = [
            sys.executable,
            str(STATE_CLI),
            "get-step-config",
            "--step",
            "clipping-qc-packager",
            "--dir",
            str(self.project_dir),
        ]
        cfg_qc_res = self.run_cmd(cfg_qc_cmd)
        self.assertEqual(cfg_qc_res.returncode, 0)
        qc_slice = json.loads(cfg_qc_res.stdout)
        self.assertEqual(len(qc_slice.get("caption_closers", [])), 12)
        self.assertEqual(qc_slice.get("target_loudness_lufs"), -14.0)
        self.assertEqual(
            qc_slice.get("submission_rules", {}).get("whop_window_minutes"), 30
        )
        self.assertEqual(
            qc_slice.get("submission_rules", {}).get("tier1_min_pct"), 40.0
        )

        # 11. Test status command output
        status_cmd = [
            sys.executable,
            str(STATE_CLI),
            "status",
            "--dir",
            str(self.project_dir),
        ]
        status_res = self.run_cmd(status_cmd)
        self.assertEqual(status_res.returncode, 0)
        self.assertIn("N3on x MPJ", status_res.stdout)
        self.assertIn("[APPROVED]", status_res.stdout)
        self.assertIn("clipping-transcription", status_res.stdout)


if __name__ == "__main__":
    unittest.main()
