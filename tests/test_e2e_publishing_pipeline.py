#!/usr/bin/env python3
"""
tests/test_e2e_publishing_pipeline.py

End-to-End integration test suite for Ticket #20:
Verifies the complete 8-step pipeline execution flow:
1. Pipeline state initialization (scripts/clipping_state.py init)
2. Campaign brief ingestion (scripts/clipping_state.py ingest-brief)
3. Guidelines approval gate (scripts/clipping_state.py approve --step clipping-guidelines)
4. Sequential validation & approval for steps 2 through 7 (clipping-transcription to clipping-qc-packager)
5. Pre-flight gate validation for Step 8 (clipping-publisher)
6. Step 8 approval rejection when publication_manifest is missing (exit code 1)
7. Multi-platform publishing via CLI (scripts/clipping_publisher.py publish)
8. Verification of structured publication_manifest written to .clipping_state.json
9. Step 8 approval success with publication_manifest present (scripts/clipping_state.py approve --step clipping-publisher)
10. Final pipeline status inspection confirming all 8 steps completed and approved.

Zero external runtime dependencies (Python standard library only).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_CLI = REPO_ROOT / "scripts" / "clipping_state.py"
PUBLISHER_CLI = REPO_ROOT / "scripts" / "clipping_publisher.py"


class TestE2EPublishingPipeline(unittest.TestCase):
    """End-to-end integration test verifying complete 8-step pipeline lifecycle."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_e2e_publishing_")
        self.project_dir = Path(self.tmpdir)
        self.state_file = self.project_dir / ".clipping_state.json"
        self.channels_file = self.project_dir / "channels.json"
        self.video_file = self.project_dir / "rendered_clip.mp4"
        self.video_file.write_bytes(b"\x00\x00\x00\x1cftypmp42fake_clip_video_data")
        self.cloud_stage = self.project_dir / "cloud_stage"
        self.cloud_stage.mkdir(parents=True, exist_ok=True)

        # Setup workspace channels.json with warmed-up accounts
        self.portfolio_data = {
            "version": "1.0.0",
            "workspace_id": "ws-e2e-publishing",
            "channels": [
                {
                    "id": "chan-tt-e2e-01",
                    "platform": "TikTok",
                    "handle": "@e2e_clips_tt",
                    "account_name": "E2E Brand",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 4,
                        "posts_today": 0,
                    },
                    "device_transfer": {
                        "protocol": "cloud_folder",
                        "target": str(self.cloud_stage),
                        "enabled": True,
                    },
                },
                {
                    "id": "chan-yt-e2e-01",
                    "platform": "YouTube Shorts",
                    "handle": "@E2EClipsYT",
                    "account_name": "E2E Brand",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 4,
                        "posts_today": 0,
                    },
                },
            ],
        }
        self.channels_file.write_text(
            json.dumps(self.portfolio_data, indent=2), encoding="utf-8"
        )

        # Setup campaign brief
        self.brief_file = self.project_dir / "campaign_brief.json"
        self.brief_data = {
            "campaign": {
                "title": "E2E Campaign Test",
                "client": "Test Client",
                "project": "e2e-project",
                "source_url": "https://youtube.com/watch?v=e2etest",
            },
            "global_rules": {
                "duration": {"min_seconds": 20.0, "max_seconds": 60.0},
                "tier1_geo_min_pct": 40.0,
                "watermark": {"required": True, "asset_path": "assets/wm.png"},
                "caption_closers": ["Follow for more!", "Part 2 in bio"],
                "audio": {"loudness_target_lufs": -14.0},
            },
        }
        self.brief_file.write_text(
            json.dumps(self.brief_data, indent=2), encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_state_cli(self, args):
        cmd = [sys.executable, str(STATE_CLI)] + args
        return subprocess.run(
            cmd, cwd=str(self.project_dir), capture_output=True, text=True
        )

    def run_publisher_cli(self, args):
        cmd = [sys.executable, str(PUBLISHER_CLI)] + args
        return subprocess.run(
            cmd, cwd=str(self.project_dir), capture_output=True, text=True
        )

    def test_complete_8_step_pipeline_flow(self):
        """
        Executes and validates the complete 8-step pipeline sequence from init to Step 8 approval:
        1. init
        2. ingest-brief
        3. approve step 1 (guidelines)
        4. validate & approve steps 2 through 7
        5. validate step 8
        6. approve step 8 without manifest -> rejected (code 1)
        7. publisher publish -> manifest generated and written to state
        8. approve step 8 with manifest -> succeeds (code 0)
        9. status -> All steps completed
        """
        # Step 1: Initialize pipeline state
        res_init = self.run_state_cli(["init", "--dir", str(self.project_dir)])
        self.assertEqual(res_init.returncode, 0, f"init failed: {res_init.stderr}")
        self.assertTrue(self.state_file.is_file())

        # Step 2: Ingest campaign brief
        res_ingest = self.run_state_cli([
            "ingest-brief",
            "--brief", str(self.brief_file),
            "--dir", str(self.project_dir),
        ])
        self.assertEqual(res_ingest.returncode, 0, f"ingest-brief failed: {res_ingest.stderr}")

        # Gate check: Step 2 cannot run before guidelines approval
        res_val_step2_blocked = self.run_state_cli([
            "validate", "--step", "clipping-transcription", "--dir", str(self.project_dir)
        ])
        self.assertEqual(res_val_step2_blocked.returncode, 2)

        # Step 3: Approve Step 1 clipping-guidelines
        res_appr_s1 = self.run_state_cli([
            "approve", "--step", "clipping-guidelines", "--dir", str(self.project_dir)
        ])
        self.assertEqual(res_appr_s1.returncode, 0, f"approve step 1 failed: {res_appr_s1.stderr}")

        # Step 4: Validate and approve steps 2 through 7 in sequential order
        intermediate_steps = [
            "clipping-transcription",
            "clipping-hook-hunter",
            "clipping-assembly",
            "clipping-captions",
            "clipping-vfx-sfx",
            "clipping-qc-packager",
        ]
        for step in intermediate_steps:
            # Validate cleared
            res_val = self.run_state_cli(["validate", "--step", step, "--dir", str(self.project_dir)])
            self.assertEqual(res_val.returncode, 0, f"validate {step} failed: {res_val.stderr}")

            # Approve step
            res_appr = self.run_state_cli(["approve", "--step", step, "--dir", str(self.project_dir)])
            self.assertEqual(res_appr.returncode, 0, f"approve {step} failed: {res_appr.stderr}")

        # Step 5: Validate Step 8 pre-flight gate (should clear now that Step 7 is approved)
        res_val_step8 = self.run_state_cli([
            "validate", "--step", "clipping-publisher", "--dir", str(self.project_dir)
        ])
        self.assertEqual(res_val_step8.returncode, 0, f"validate step 8 failed: {res_val_step8.stderr}")

        # Step 6: Attempt Step 8 approval BEFORE publishing manifest exists
        # MUST be rejected with exit code 1
        res_appr_step8_premature = self.run_state_cli([
            "approve", "--step", "clipping-publisher", "--dir", str(self.project_dir)
        ])
        self.assertEqual(
            res_appr_step8_premature.returncode,
            1,
            "Approving Step 8 without publication_manifest must fail with exit code 1",
        )
        self.assertIn("publication_manifest", res_appr_step8_premature.stderr.lower())

        # Step 7: Execute publisher publish via CLI
        res_pub = self.run_publisher_cli([
            "publish",
            "--brand-cluster", "E2E Brand",
            "--platforms", "TikTok",
            "--channels", str(self.channels_file),
            "--video", str(self.video_file),
            "--clip-id", "clip-e2e-001",
            "--caption-hook", "Watch What Happens Next!",
            "--caption-closer", "Follow for more!",
            "--project-dir", str(self.project_dir),
            "--json",
        ])
        self.assertEqual(res_pub.returncode, 0, f"publish failed: {res_pub.stderr}")
        pub_json = json.loads(res_pub.stdout)
        self.assertEqual(pub_json.get("status"), "staged_mobile")
        self.assertEqual(pub_json.get("clip_id"), "clip-e2e-001")

        # Step 8: Verify publication_manifest written to .clipping_state.json
        state_data = json.loads(self.state_file.read_text(encoding="utf-8"))
        step8_params = state_data["steps"]["clipping-publisher"]["params"]
        self.assertIn("publication_manifest", step8_params)
        manifest = step8_params["publication_manifest"]
        self.assertIsInstance(manifest, list)
        self.assertEqual(len(manifest), 1)

        manifest_entry = manifest[0]
        self.assertEqual(manifest_entry["clip_id"], "clip-e2e-001")
        self.assertEqual(manifest_entry["brand_cluster"], "E2E Brand")
        self.assertEqual(manifest_entry["platform"], "TikTok")
        self.assertEqual(manifest_entry["channel_id"], "chan-tt-e2e-01")
        self.assertEqual(manifest_entry["status"], "staged_mobile")
        self.assertEqual(manifest_entry["protocol"], "cloud_folder")
        self.assertEqual(manifest_entry["delivery_method"], "cloud_folder")
        self.assertTrue(manifest_entry["caption_bundled"])
        self.assertIn("timestamp", manifest_entry)

        # Also verify companion caption and video were copied to cloud_stage
        self.assertTrue((self.cloud_stage / "rendered_clip.mp4").is_file())
        self.assertTrue((self.cloud_stage / "caption.txt").is_file())
        caption_text = (self.cloud_stage / "caption.txt").read_text(encoding="utf-8")
        self.assertIn("Watch What Happens Next!", caption_text)
        self.assertIn("Follow for more!", caption_text)

        # Step 9: Now approve Step 8 (should succeed with exit code 0)
        res_appr_step8 = self.run_state_cli([
            "approve", "--step", "clipping-publisher", "--dir", str(self.project_dir)
        ])
        self.assertEqual(
            res_appr_step8.returncode,
            0,
            f"Step 8 approval with manifest should succeed: {res_appr_step8.stderr}",
        )

        # Step 10: Inspect final pipeline status
        res_status = self.run_state_cli(["status", "--dir", str(self.project_dir)])
        self.assertEqual(res_status.returncode, 0)
        self.assertIn("All steps completed", res_status.stdout)

        # Inspect json status: all 8 steps must be approved
        res_status_json = self.run_state_cli(["status", "--dir", str(self.project_dir), "--json"])
        self.assertEqual(res_status_json.returncode, 0)
        final_state = json.loads(res_status_json.stdout)

        expected_all_8 = [
            "clipping-guidelines",
            "clipping-transcription",
            "clipping-hook-hunter",
            "clipping-assembly",
            "clipping-captions",
            "clipping-vfx-sfx",
            "clipping-qc-packager",
            "clipping-publisher",
        ]
        for s in expected_all_8:
            step_obj = final_state["steps"][s]
            self.assertTrue(step_obj["approved"], f"Step {s} should be approved")
            self.assertEqual(step_obj["status"], "completed", f"Step {s} should be completed")
            self.assertIsNotNone(step_obj["completed_at"], f"Step {s} should have completed_at")


if __name__ == "__main__":
    unittest.main()
