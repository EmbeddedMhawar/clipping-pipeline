#!/usr/bin/env python3
"""
tests/test_clipping_qc_packager.py

Unit test suite for Step 7: Quality Control & Whop Packaging Engine (scripts/clipping_qc_packager.py).
Tests:
- Caption closer rotation and deterministic pseudo-random distribution
- Platform-specific copy generation (YouTube Shorts, TikTok, Instagram Reels)
- QC compliance auditing (EBU R128 loudness, true peak, duration bounds, safe zones, Whop checklist)
- Media inspection fallback handling
- End-to-end execution of execute_qc_packaging on synthetic campaign project
"""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.clipping_qc_packager import (
    DEFAULT_MAX_DURATION,
    DEFAULT_MAX_TRUE_PEAK,
    DEFAULT_MIN_DURATION,
    DEFAULT_TARGET_LUFS,
    QC_PACKAGE_FILENAME,
    STATE_FILENAME,
    audit_qc_compliance,
    build_platform_copy_packages,
    execute_qc_packaging,
    probe_media_file,
    rotate_caption_closer,
)


class TestCloserRotationAndCopy(unittest.TestCase):
    """Tests for closer rotation and platform copy formatting."""

    def test_rotate_caption_closer(self):
        closers = [
            "watch the full episode @HardScopeTV on youtube #unpacked",
            "full episode is on @HardScopeTV on youtube #unpacked",
            "the whole thing is up on @HardScopeTV on youtube #unpacked",
        ]
        c1 = rotate_caption_closer(closers, "proj-1", "clip-01")
        c2 = rotate_caption_closer(closers, "proj-1", "clip-01")
        # Must be deterministic given same inputs
        self.assertEqual(c1, c2)
        self.assertIn(c1, closers)

        # Empty fallback
        self.assertEqual(
            rotate_caption_closer([], "proj-1", "clip-01"),
            "Watch the full episode on YouTube #Shorts",
        )

    def test_build_platform_copy_packages(self):
        title = "He refused to look at the card... until THIS happened 🤯"
        closer = "watch the full episode @HardScopeTV on youtube #unpacked"
        packages = build_platform_copy_packages(title, closer)

        self.assertIn("YouTube Shorts", packages)
        self.assertIn("TikTok", packages)
        self.assertIn("Instagram Reels", packages)

        yt = packages["YouTube Shorts"]
        self.assertIn("#Shorts", yt["title"])
        self.assertIn(closer, yt["description"])
        self.assertEqual(yt["handle_format"], "tagged")

        tt = packages["TikTok"]
        self.assertEqual(tt["handle_format"], "plain_text")
        self.assertIn("HardScopeTV", tt["caption"])
        self.assertNotIn("@HardScopeTV", tt["caption"])

        ig = packages["Instagram Reels"]
        self.assertEqual(ig["handle_format"], "plain_text")
        self.assertIn("HardScopeTV", ig["caption"])


class TestComplianceAuditing(unittest.TestCase):
    """Tests for audit_qc_compliance logic."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_audit_qc_")
        self.proj_dir = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_compliance_pass(self):
        media_specs = {
            "duration": 41.088,
            "width": 1080,
            "height": 1920,
            "aspect_ratio": "9:16",
        }
        loudness = {
            "integrated_loudness_lufs": -14.2,
            "true_peak_dbtp": -1.1,
            "loudness_range_lu": 6.5,
        }

        res = audit_qc_compliance(
            project_dir=self.proj_dir,
            media_specs=media_specs,
            loudness_metrics=loudness,
            target_lufs=-14.0,
            lufs_tolerance=1.0,
            max_true_peak=-1.0,
            min_duration=7.0,
            max_duration=60.0,
        )

        self.assertTrue(res["loudness_pass"])
        self.assertTrue(res["true_peak_pass"])
        self.assertTrue(res["duration_pass"])
        self.assertTrue(res["resolution_pass"])
        self.assertTrue(res["all_passed"])
        self.assertEqual(len(res["whop_checklist"]), 6)

    def test_compliance_fail_loudness_and_duration(self):
        media_specs = {
            "duration": 65.0,  # Exceeds max 60s
            "width": 1080,
            "height": 1920,
            "aspect_ratio": "9:16",
        }
        loudness = {
            "integrated_loudness_lufs": -20.8,  # Out of tolerance for -14.0
            "true_peak_dbtp": -0.2,  # > -1.0 dBTP
            "loudness_range_lu": 12.0,
        }

        res = audit_qc_compliance(
            project_dir=self.proj_dir,
            media_specs=media_specs,
            loudness_metrics=loudness,
            target_lufs=-14.0,
            lufs_tolerance=1.0,
            max_true_peak=-1.0,
            min_duration=7.0,
            max_duration=60.0,
        )

        self.assertFalse(res["loudness_pass"])
        self.assertFalse(res["true_peak_pass"])
        self.assertFalse(res["duration_pass"])
        self.assertFalse(res["all_passed"])


class TestQCExecutionFlow(unittest.TestCase):
    """Tests execute_qc_packaging on an active project structure."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_qc_exec_")
        self.proj_dir = Path(self.tmpdir)

        # Mock video
        self.mock_video = self.proj_dir / "preview_vfx.mp4"
        self.mock_video.write_bytes(b"\x00\x00\x00\x1cftypmp42mock_video_bytes")

        # Mock state file
        self.state_file = self.proj_dir / STATE_FILENAME
        state_data = {
            "version": "1.0.0",
            "campaign": {
                "title": "Test QC Campaign",
                "client": "Test Client",
                "project": "test-qc-proj",
            },
            "steps": {
                "clipping-qc-packager": {
                    "status": "pending",
                    "approved": False,
                    "params": {
                        "target_loudness_lufs": -14.0,
                        "min_duration": 7.0,
                        "max_duration": 60.0,
                        "caption_closers": [
                            "Full episode on YouTube #Shorts",
                            "Watch the rest on YT #Shorts",
                        ],
                        "submission_rules": {
                            "whop_window_minutes": 30,
                        },
                    },
                }
            },
        }
        self.state_file.write_text(json.dumps(state_data, indent=2), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_execute_qc_packaging(self):
        master_out = self.proj_dir / "master_test.mp4"

        res = execute_qc_packaging(
            project_dir=self.proj_dir,
            video_path=self.mock_video,
            output_mp4=master_out,
            trigger_checkpoint=False,  # avoid invoking state cli subprocess in unit test
        )

        self.assertIn("master_video", res)
        self.assertIn("loudness_audit", res)
        self.assertIn("selected_closer", res)
        self.assertIn("platform_packages", res)
        self.assertIn("whop_submission", res)

        # Verify qc_package.json was written
        qc_json = self.proj_dir / QC_PACKAGE_FILENAME
        self.assertTrue(qc_json.is_file())
        with open(qc_json, "r", encoding="utf-8") as f:
            saved_pkg = json.load(f)
        self.assertEqual(saved_pkg["clip_id"], "test-qc-proj-clip-01")

        # Verify .clipping_state.json updated
        with open(self.state_file, "r", encoding="utf-8") as f:
            updated_state = json.load(f)
        params = updated_state["steps"]["clipping-qc-packager"]["params"]
        self.assertEqual(params["target_loudness_lufs"], -14.0)
        self.assertIn("master_video_path", params)
        self.assertTrue(updated_state["steps"]["clipping-qc-packager"]["staged"])


if __name__ == "__main__":
    unittest.main()
