#!/usr/bin/env python3
"""
tests/test_channels_pipeline_bridge.py

Test suite for Ticket #13:
- Channel portfolio bridge between workspace-level channels.json and clipping pipeline
- Non-blocking advisory notice when channels.json is missing during Step 1 guidelines validation or status check
- Step 7 (clipping-qc-packager) get-step-config filtering of eligible_channels:
  * Matching campaign platforms
  * health_status != 'cooldown' (and not in Account Cooldown)
  * posts_today < daily_post_cap (daily post limit)
- Flagging channels in cooldown or at daily capacity as ineligible with reasons
- Device transfer configuration passed into Step 7 slice
- Documentation of portfolio bridge and Step 7 device delivery in skills/clipping-pipeline/SKILL.md
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SKILLS_DIR = REPO_ROOT / "skills" / "clipping-pipeline"
CLIPPING_STATE_CLI = SCRIPTS_DIR / "clipping_state.py"
CLIPPING_CHANNELS_CLI = SCRIPTS_DIR / "clipping_channels.py"


class TestChannelsPipelineBridge(unittest.TestCase):
    """Verifies integration between clipping pipeline state engine and channel portfolio."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_bridge_")
        self.workspace_dir = Path(self.tmpdir)
        self.project_dir = self.workspace_dir / "test-project"
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.channels_path = self.workspace_dir / "channels.json"

        # Initialize project clipping state
        cmd_init = [
            sys.executable,
            str(CLIPPING_STATE_CLI),
            "init",
            "--dir",
            str(self.project_dir),
        ]
        res = subprocess.run(cmd_init, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Failed to init clipping state: {res.stderr}")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_sample_brief(self, platforms: List[str] = None) -> Path:
        """Create a minimal campaign_brief.json in project dir."""
        brief_data = {
            "campaign": {
                "title": "Test Campaign",
                "client": "Test Client",
                "project": "test-project",
                "platforms": platforms or ["TikTok", "Instagram Reels", "YouTube Shorts"],
                "daily_post_limit": 4,
                "economics": {"rate_per_1k_views": 1.0, "payout_cap": 300},
            },
            "global_rules": {
                "duration": {"min_seconds": 20.0, "max_seconds": 60.0},
                "tier1_geo_min_pct": 40.0,
                "engagement_min_pct": 1.0,
                "watermark": {"required": True, "asset_path": "assets/watermark.png"},
                "caption_closers": ["Follow for more", "Link in bio"],
                "audio": {
                    "zero_background_music": True,
                    "zero_phonk": True,
                    "loudness_target_lufs": -14.0,
                },
            },
        }
        brief_path = self.project_dir / "campaign_brief.json"
        with open(brief_path, "w", encoding="utf-8") as f:
            json.dump(brief_data, f, indent=2)
        return brief_path

    def _ingest_brief(self, brief_path: Path):
        """Ingest brief into project clipping state."""
        cmd_ingest = [
            sys.executable,
            str(CLIPPING_STATE_CLI),
            "ingest-brief",
            "--brief",
            str(brief_path),
            "--dir",
            str(self.project_dir),
        ]
        res = subprocess.run(cmd_ingest, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Failed to ingest brief: {res.stderr}")

    def test_advisory_notice_when_channels_missing_during_step1_validation(self):
        """Step 1 guidelines validation outputs non-blocking advisory notice when channels.json is missing."""
        # Ensure channels.json does not exist anywhere in workspace or project
        self.assertFalse(self.channels_path.is_file())
        self.assertFalse((self.project_dir / "channels.json").is_file())

        cmd = [
            sys.executable,
            str(CLIPPING_STATE_CLI),
            "validate",
            "--step",
            "clipping-guidelines",
            "--dir",
            str(self.project_dir),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)

        # Pre-flight gate must pass (exit code 0 - non-blocking!)
        self.assertEqual(res.returncode, 0, f"Step 1 validation failed unexpectedly: {res.stderr}")

        # Must issue an advisory notice referencing channels.json
        combined_output = res.stdout + res.stderr
        self.assertIn("channels.json", combined_output)
        self.assertTrue(
            "notice" in combined_output.lower() or "advisory" in combined_output.lower(),
            f"Expected advisory notice keyword in output: {combined_output}",
        )

    def test_advisory_notice_when_channels_missing_during_status_check(self):
        """Status check displays non-blocking advisory notice when channels.json is missing."""
        self.assertFalse(self.channels_path.is_file())

        # Human-readable status check
        cmd = [
            sys.executable,
            str(CLIPPING_STATE_CLI),
            "status",
            "--dir",
            str(self.project_dir),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        combined_output = res.stdout + res.stderr
        self.assertIn("channels.json", combined_output)
        self.assertTrue(
            "notice" in combined_output.lower() or "advisory" in combined_output.lower() or "portfolio" in combined_output.lower(),
            f"Expected portfolio/advisory notice in status output: {combined_output}",
        )

        # JSON status check
        cmd_json = [
            sys.executable,
            str(CLIPPING_STATE_CLI),
            "status",
            "--dir",
            str(self.project_dir),
            "--json",
        ]
        res_json = subprocess.run(cmd_json, capture_output=True, text=True)
        self.assertEqual(res_json.returncode, 0)
        # JSON must be valid
        status_data = json.loads(res_json.stdout)
        self.assertIsInstance(status_data, dict)
        # Notice should be present in stderr or as a field in JSON
        combined_json_output = res_json.stderr + json.dumps(status_data)
        self.assertIn("channels.json", combined_json_output)

    def test_no_advisory_notice_when_channels_present(self):
        """When channels.json is present, no missing channels advisory notice is emitted."""
        # Create minimal valid channels.json
        portfolio_data = {
            "version": "1.0.0",
            "channels": [
                {
                    "id": "chan-tiktok-01",
                    "platform": "TikTok",
                    "handle": "@test_tt",
                    "stage": "Mature",
                    "status": "active",
                }
            ],
        }
        with open(self.channels_path, "w", encoding="utf-8") as f:
            json.dump(portfolio_data, f, indent=2)

        cmd = [
            sys.executable,
            str(CLIPPING_STATE_CLI),
            "validate",
            "--step",
            "clipping-guidelines",
            "--dir",
            str(self.project_dir),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        # Stderr should not mention missing channels.json
        self.assertNotIn("channels.json) not found", res.stderr)
        self.assertNotIn("channels.json not found", res.stderr)

    def test_step7_config_includes_eligible_channels(self):
        """Step 7 (clipping-qc-packager) get-step-config includes eligible_channels matching platforms and capacity."""
        brief_path = self._create_sample_brief(platforms=["TikTok", "Instagram Reels", "YouTube Shorts"])
        self._ingest_brief(brief_path)

        # Setup channels.json in workspace
        portfolio = {
            "version": "1.0.0",
            "workspace_id": "test-ws",
            "default_device_transfer": {
                "protocol": "qr_code",
                "target": "http://127.0.0.1:8080",
                "enabled": True,
            },
            "channels": [
                {
                    "id": "chan-tt-01",
                    "platform": "TikTok",
                    "handle": "@tt_viral",
                    "stage": "Seeding",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 1,
                        "posts_today": 0,
                    },
                    "health_gate": {"cleared_health_gate": False},
                    "cooldown": {"in_cooldown": False},
                    "device_transfer": {
                        "protocol": "qr_code",
                        "target": "http://127.0.0.1:8080",
                        "enabled": True,
                    },
                },
                {
                    "id": "chan-ig-01",
                    "platform": "Instagram Reels",
                    "handle": "@ig_clips",
                    "stage": "Ramp-Up",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 3,
                        "posts_today": 1,
                    },
                    "health_gate": {"cleared_health_gate": True},
                    "cooldown": {"in_cooldown": False},
                    "device_transfer": {
                        "protocol": "adb_push",
                        "target": "/sdcard/DCIM/Camera/",
                        "enabled": True,
                    },
                },
                {
                    "id": "chan-yt-01",
                    "platform": "YouTube Shorts",
                    "handle": "@yt_shorts",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 4,
                        "posts_today": 2,
                    },
                    "health_gate": {"cleared_health_gate": True},
                    "cooldown": {"in_cooldown": False},
                    "device_transfer": {
                        "protocol": "cloud_sync",
                        "target": "/home/user/Clips",
                        "enabled": True,
                    },
                },
            ],
        }
        with open(self.channels_path, "w", encoding="utf-8") as f:
            json.dump(portfolio, f, indent=2)

        cmd = [
            sys.executable,
            str(CLIPPING_STATE_CLI),
            "get-step-config",
            "--step",
            "clipping-qc-packager",
            "--dir",
            str(self.project_dir),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"get-step-config failed: {res.stderr}")

        config = json.loads(res.stdout)
        self.assertIn("eligible_channels", config)
        eligible_ids = [c["id"] for c in config["eligible_channels"]]
        self.assertEqual(set(eligible_ids), {"chan-tt-01", "chan-ig-01", "chan-yt-01"})

    def test_step7_config_flags_ineligible_channels_with_reasons(self):
        """Step 7 flags channels in cooldown or at daily capacity as ineligible with specific reasons."""
        brief_path = self._create_sample_brief(platforms=["TikTok", "Instagram Reels", "YouTube Shorts"])
        self._ingest_brief(brief_path)

        portfolio = {
            "version": "1.0.0",
            "channels": [
                # 1. Eligible channel
                {
                    "id": "chan-tt-ok",
                    "platform": "TikTok",
                    "handle": "@tt_ok",
                    "stage": "Ramp-Up",
                    "status": "active",
                    "posting_cadence": {"daily_post_limit": 3, "posts_today": 0},
                    "cooldown": {"in_cooldown": False},
                },
                # 2. Ineligible: In cooldown (status: 'cooldown')
                {
                    "id": "chan-tt-cd1",
                    "platform": "TikTok",
                    "handle": "@tt_cd1",
                    "stage": "Account Cooldown",
                    "status": "cooldown",
                    "posting_cadence": {"daily_post_limit": 0, "posts_today": 0},
                    "cooldown": {
                        "in_cooldown": True,
                        "reason": "0-view shadowban detected",
                    },
                },
                # 3. Ineligible: health_status = 'cooldown' or in_cooldown = True
                {
                    "id": "chan-ig-cd2",
                    "platform": "Instagram Reels",
                    "handle": "@ig_cd2",
                    "stage": "Seeding",
                    "health_status": "cooldown",
                    "status": "cooldown",
                    "posting_cadence": {"daily_post_limit": 1, "posts_today": 0},
                    "cooldown": {"in_cooldown": True, "reason": "view suppression"},
                },
                # 4. Ineligible: At daily capacity (posts_today == daily_post_limit)
                {
                    "id": "chan-yt-full",
                    "platform": "YouTube Shorts",
                    "handle": "@yt_full",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {"daily_post_limit": 2, "posts_today": 2},
                    "cooldown": {"in_cooldown": False},
                },
                # 5. Ineligible: Cold Lurker (daily_post_limit == 0)
                {
                    "id": "chan-tt-cold",
                    "platform": "TikTok",
                    "handle": "@tt_cold",
                    "stage": "Cold Lurker",
                    "status": "active",
                    "posting_cadence": {"daily_post_limit": 0, "posts_today": 0},
                    "cooldown": {"in_cooldown": False},
                },
                # 6. Ineligible: Platform not in campaign platforms
                {
                    "id": "chan-twitter-01",
                    "platform": "Twitter",
                    "handle": "@x_clips",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {"daily_post_limit": 5, "posts_today": 0},
                    "cooldown": {"in_cooldown": False},
                },
            ],
        }
        with open(self.channels_path, "w", encoding="utf-8") as f:
            json.dump(portfolio, f, indent=2)

        cmd = [
            sys.executable,
            str(CLIPPING_STATE_CLI),
            "get-step-config",
            "--step",
            "clipping-qc-packager",
            "--dir",
            str(self.project_dir),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        config = json.loads(res.stdout)

        # Check eligible channels list
        eligible_ids = [c["id"] for c in config.get("eligible_channels", [])]
        self.assertEqual(eligible_ids, ["chan-tt-ok"])

        # Check ineligible channels list and reasons
        self.assertIn("ineligible_channels", config)
        ineligible_map = {c["id"]: c for c in config["ineligible_channels"]}

        # chan-tt-cd1 must cite cooldown
        self.assertIn("chan-tt-cd1", ineligible_map)
        reason_cd1 = ineligible_map["chan-tt-cd1"].get("reason", "").lower()
        self.assertTrue("cooldown" in reason_cd1 or "shadowban" in reason_cd1, f"Expected cooldown reason: {reason_cd1}")

        # chan-ig-cd2 must cite cooldown
        self.assertIn("chan-ig-cd2", ineligible_map)
        reason_cd2 = ineligible_map["chan-ig-cd2"].get("reason", "").lower()
        self.assertTrue("cooldown" in reason_cd2 or "suppression" in reason_cd2, f"Expected cooldown reason: {reason_cd2}")

        # chan-yt-full must cite capacity / post limit
        self.assertIn("chan-yt-full", ineligible_map)
        reason_full = ineligible_map["chan-yt-full"].get("reason", "").lower()
        self.assertTrue(
            "capacity" in reason_full or "limit" in reason_full or "posts today" in reason_full,
            f"Expected capacity reason: {reason_full}",
        )

        # chan-tt-cold must cite capacity / 0 posts limit
        self.assertIn("chan-tt-cold", ineligible_map)
        reason_cold = ineligible_map["chan-tt-cold"].get("reason", "").lower()
        self.assertTrue(
            "capacity" in reason_cold or "limit" in reason_cold or "cold lurker" in reason_cold,
            f"Expected cold/capacity reason: {reason_cold}",
        )

        # chan-twitter-01 must cite platform mismatch
        self.assertIn("chan-twitter-01", ineligible_map)
        reason_plat = ineligible_map["chan-twitter-01"].get("reason", "").lower()
        self.assertTrue(
            "platform" in reason_plat or "mismatch" in reason_plat,
            f"Expected platform reason: {reason_plat}",
        )

    def test_step7_slice_includes_device_transfer_configuration(self):
        """Device transfer configuration from channels.json is passed into Step 7 slice."""
        brief_path = self._create_sample_brief(platforms=["TikTok"])
        self._ingest_brief(brief_path)

        portfolio = {
            "version": "1.0.0",
            "workspace_id": "test-ws",
            "default_device_transfer": {
                "protocol": "qr_code",
                "target": "http://192.168.1.50:8080",
                "enabled": True,
            },
            "channels": [
                {
                    "id": "chan-tt-custom-transfer",
                    "platform": "TikTok",
                    "handle": "@tt_custom",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {"daily_post_limit": 4, "posts_today": 0},
                    "cooldown": {"in_cooldown": False},
                    "device_transfer": {
                        "protocol": "adb_push",
                        "target": "/sdcard/DCIM/Camera/",
                        "enabled": True,
                    },
                }
            ],
        }
        with open(self.channels_path, "w", encoding="utf-8") as f:
            json.dump(portfolio, f, indent=2)

        cmd = [
            sys.executable,
            str(CLIPPING_STATE_CLI),
            "get-step-config",
            "--step",
            "clipping-qc-packager",
            "--dir",
            str(self.project_dir),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        config = json.loads(res.stdout)

        # Root level or dedicated transfer config present
        self.assertTrue(
            "device_transfer" in config or "default_device_transfer" in config,
            "Step 7 slice must contain device transfer configuration from channels.json",
        )
        dt_config = config.get("device_transfer") or config.get("default_device_transfer")
        self.assertIn("protocol", dt_config)

        # Eligible channel must preserve its specific device_transfer config
        eligible = config.get("eligible_channels", [])
        self.assertEqual(len(eligible), 1)
        self.assertIn("device_transfer", eligible[0])
        self.assertEqual(eligible[0]["device_transfer"]["protocol"], "adb_push")

    def test_skill_doc_describes_portfolio_bridge_and_step7_delivery(self):
        """skills/clipping-pipeline/SKILL.md documents the portfolio bridge and Step 7 device delivery."""
        skill_file = SKILLS_DIR / "SKILL.md"
        self.assertTrue(skill_file.is_file(), f"SKILL.md missing at {skill_file}")
        content = skill_file.read_text(encoding="utf-8")

        # Must mention channels.json or channel portfolio
        self.assertIn("channels.json", content)
        self.assertIn("channel portfolio", content.lower())

        # Must mention Step 1 advisory notice for missing channels.json
        self.assertTrue(
            "advisory" in content.lower() or "notice" in content.lower(),
            "SKILL.md must document advisory notice when channels.json is missing",
        )

        # Must mention eligible channels filtering in Step 7
        self.assertIn("eligible_channels", content)
        self.assertTrue(
            "cooldown" in content.lower(),
            "SKILL.md must document cooldown exclusion",
        )
        self.assertTrue(
            "daily_post_cap" in content or "daily_post_limit" in content or "daily post" in content.lower(),
            "SKILL.md must document daily post capacity constraint",
        )

        # Must mention device delivery / device transfer protocols in Step 7
        self.assertTrue(
            "device_transfer" in content or "device transfer" in content.lower() or "device delivery" in content.lower(),
            "SKILL.md must document Step 7 device delivery / device transfer",
        )


if __name__ == "__main__":
    unittest.main()
