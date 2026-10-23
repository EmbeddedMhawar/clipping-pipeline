#!/usr/bin/env python3
"""
tests/test_clipping_checkpoint.py

Comprehensive test suite verifying the interactive checkpoint state gate
in scripts/clipping_state.py (GitHub Issue #26).

Verifies:
- Checkpoint creation, review artifact generation (RequestFeedback: true), and state persistence
- Pre-flight execution data validation
- Blocked downstream approval when checkpoint is pending review
- Successful approval after chat feedback registration or acknowledgment
- Preference engine invocation on chat directives (Channel 1)
- Preference engine invocation on manual Remotion Studio saves / project diffing (Channel 2)
- Auto-approve lifecycle transitions
- GUI companion synchronization (health check, timeline reload, watcher tracking)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from scripts.gui_companion import (
    DEFAULT_FLAG_FILENAME,
    MockRemotionServer,
    TICKS_PER_SECOND,
)
from scripts.clipping_preferences import (
    PROJECT_PREFERENCES_FILENAME,
    TRACK_A1_NAME,
    TRACK_A2_NAME,
    TRACK_A3_NAME,
    TRACK_V1_NAME,
    TRACK_V2_NAME,
    TRACK_V3_NAME,
    TRACK_V4_NAME,
)


class TestClippingCheckpointGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parent.parent
        cls.cli_path = cls.repo_root / "scripts" / "clipping_state.py"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)
        self.state_file = self.project_dir / ".clipping_state.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_cli(self, args, check=False):
        cmd = [sys.executable, str(self.cli_path)] + args
        result = subprocess.run(
            cmd,
            cwd=str(self.project_dir),
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result

    def _init_and_approve_guidelines(self):
        """Helper to set up pipeline through approved guidelines."""
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)
        brief_data = {
            "campaign": {
                "title": "Test Checkpoint Campaign",
                "client": "Test Client",
                "project": "test_clip",
                "platforms": ["TikTok", "YouTube Shorts"],
                "daily_post_limit": 4,
            },
            "global_rules": {
                "duration": {"min_seconds": 20.0, "max_seconds": 60.0},
                "tier1_geo_min_pct": 40.0,
                "engagement_min_pct": 1.0,
            },
        }
        brief_file = self.project_dir / "campaign_brief.json"
        with open(brief_file, "w", encoding="utf-8") as f:
            json.dump(brief_data, f, indent=2)

        self.run_cli(["ingest-brief", "--brief", str(brief_file), "--dir", str(self.project_dir)], check=True)
        self.run_cli(["approve", "--step", "clipping-guidelines", "--dir", str(self.project_dir)], check=True)

    def _create_mock_remotion_project(
        self,
        bgm_vol: float = -20.0,
        sfx_vol: float = -2.0,
        speaker_anchor: tuple = (960.0, 540.0),
        scale: float = 177.7778,
        duration_sec: float = 30.0,
        blur: float = 45.0,
        watermark_scale: float = 28.0,
    ) -> dict:
        """Create mock .remotion.json dictionary for diffing and companion inspection."""
        from scripts.clipping_preferences import TestClippingPreferences
        helper = TestClippingPreferences()
        return helper._create_mock_remotion_project(
            bgm_vol=bgm_vol,
            sfx_vol=sfx_vol,
            speaker_anchor=speaker_anchor,
            v2_scale=scale,
            clip_dur_sec=duration_sec,
            blur=blur,
            watermark_scale=watermark_scale,
        )

    # -------------------------------------------------------------------------
    # Test Cases
    # -------------------------------------------------------------------------

    def test_checkpoint_creation_and_state_persistence(self):
        """Verify checkpoint staging records state and outputs RequestFeedback artifact."""
        self._init_and_approve_guidelines()

        # Mark transcription and hook hunter completed
        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        state["steps"]["clipping-transcription"]["status"] = "completed"
        state["steps"]["clipping-transcription"]["approved"] = True
        state["steps"]["clipping-hook-hunter"]["status"] = "completed"
        state["steps"]["clipping-hook-hunter"]["approved"] = True
        state["steps"]["clipping-assembly"]["status"] = "staged"
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        # Stage checkpoint for clipping-assembly
        res = self.run_cli(["checkpoint", "--step", "clipping-assembly", "--dir", str(self.project_dir)])
        self.assertEqual(res.returncode, 0, f"checkpoint failed: {res.stderr}")
        self.assertIn("CHECKPOINT STATE GATE: clipping-assembly", res.stdout)
        self.assertIn("AWAITING HUMAN REVIEW", res.stdout)

        # Verify state file content
        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        step_state = state["steps"]["clipping-assembly"]
        self.assertEqual(step_state["status"], "awaiting_checkpoint")
        self.assertIn("checkpoint", step_state)
        cp = step_state["checkpoint"]
        self.assertTrue(cp["staged"])
        self.assertFalse(cp["reviewed"])
        self.assertEqual(cp["step"], "clipping-assembly")
        self.assertIn("timestamp", cp)
        self.assertIn("review_artifact", cp)

        # Check top-level checkpoint reference
        self.assertEqual(state["checkpoint"]["step"], "clipping-assembly")
        self.assertTrue(state["checkpoint"]["staged"])
        self.assertFalse(state["checkpoint"]["reviewed"])

        # Verify generated markdown artifact
        artifact_path = Path(cp["review_artifact"])
        self.assertTrue(artifact_path.is_file(), f"Artifact not found at {artifact_path}")
        with open(artifact_path, "r", encoding="utf-8") as f:
            artifact_content = f.read()

        self.assertIn("RequestFeedback: true", artifact_content)
        self.assertIn("Summary: Checkpoint review for step 'clipping-assembly'", artifact_content)
        self.assertIn("UserFacing: true", artifact_content)
        self.assertIn("# Checkpoint Review: `clipping-assembly`", artifact_content)
        self.assertIn("Feedback Checkpoint State", artifact_content)

    def test_checkpoint_preflight_blocks_pending_step_without_data(self):
        """Verify pre-flight check blocks staging checkpoint when step execution data is missing."""
        self._init_and_approve_guidelines()

        # clipping-assembly is pending and has no staged data or project file
        res = self.run_cli(["checkpoint", "--step", "clipping-assembly", "--dir", str(self.project_dir)])
        self.assertEqual(res.returncode, 2)
        self.assertIn("Pre-flight Gate Blocked", res.stderr)
        self.assertIn("has not finished execution data", res.stderr)

        # Force bypass allows staging
        res_force = self.run_cli([
            "checkpoint",
            "--step",
            "clipping-assembly",
            "--force",
            "--dir",
            str(self.project_dir),
        ])
        self.assertEqual(res_force.returncode, 0)
        self.assertIn("CHECKPOINT STATE GATE: clipping-assembly", res_force.stdout)

    def test_blocked_approval_when_checkpoint_is_pending_review(self):
        """Verify approve is blocked when an active checkpoint is unreviewed."""
        self._init_and_approve_guidelines()

        # Force-stage checkpoint for clipping-transcription
        self.run_cli(["checkpoint", "--step", "clipping-transcription", "--force", "--dir", str(self.project_dir)], check=True)

        # Attempt to approve step without review
        res_appr = self.run_cli(["approve", "--step", "clipping-transcription", "--dir", str(self.project_dir)])
        self.assertEqual(res_appr.returncode, 2)
        self.assertIn("Checkpoint Gate Blocked", res_appr.stderr)
        self.assertIn("unresolved feedback checkpoint pending review", res_appr.stderr)

        # Attempt to validate downstream step (clipping-hook-hunter)
        res_val = self.run_cli(["validate", "--step", "clipping-hook-hunter", "--dir", str(self.project_dir)])
        self.assertEqual(res_val.returncode, 2)
        self.assertIn("Pre-flight Gate Blocked", res_val.stderr)
        self.assertIn("has an active feedback checkpoint pending review", res_val.stderr)

    def test_successful_approval_after_checkpoint_feedback(self):
        """Verify providing feedback marks checkpoint reviewed and allows step approval."""
        self._init_and_approve_guidelines()
        self.run_cli(["checkpoint", "--step", "clipping-transcription", "--force", "--dir", str(self.project_dir)], check=True)

        # Register natural language feedback
        feedback_str = "target 35s and center on host"
        res_fb = self.run_cli([
            "checkpoint",
            "--step",
            "clipping-transcription",
            "--feedback",
            feedback_str,
            "--dir",
            str(self.project_dir),
        ])
        self.assertEqual(res_fb.returncode, 0)
        self.assertIn("[REVIEWED]", res_fb.stdout)

        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        cp = state["steps"]["clipping-transcription"]["checkpoint"]
        self.assertTrue(cp["reviewed"])
        self.assertEqual(cp["feedback"], feedback_str)
        self.assertEqual(state["steps"]["clipping-transcription"]["status"], "checkpoint_reviewed")

        # Now approve should succeed cleanly
        res_appr = self.run_cli(["approve", "--step", "clipping-transcription", "--dir", str(self.project_dir)])
        self.assertEqual(res_appr.returncode, 0)
        self.assertIn("Approved step 'clipping-transcription'", res_appr.stdout)

        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        self.assertTrue(state["steps"]["clipping-transcription"]["approved"])
        self.assertEqual(state["steps"]["clipping-transcription"]["status"], "completed")
        self.assertEqual(state["current_step"], "clipping-hook-hunter")

        # Downstream validate should now pass
        res_val = self.run_cli(["validate", "--step", "clipping-hook-hunter", "--dir", str(self.project_dir)])
        self.assertEqual(res_val.returncode, 0)
        self.assertIn("Pre-flight Gate Passed", res_val.stdout)

    def test_approval_force_bypass_clears_checkpoint(self):
        """Verify approve --force bypasses unreviewed checkpoint with warning."""
        self._init_and_approve_guidelines()
        self.run_cli(["checkpoint", "--step", "clipping-transcription", "--force", "--dir", str(self.project_dir)], check=True)

        # Force approve
        res = self.run_cli(["approve", "--step", "clipping-transcription", "--force", "--dir", str(self.project_dir)])
        self.assertEqual(res.returncode, 0)
        self.assertIn("[WARNING] Checkpoint gate bypassed with --force", res.stdout)

        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        self.assertTrue(state["steps"]["clipping-transcription"]["approved"])
        self.assertEqual(state["steps"]["clipping-transcription"]["status"], "completed")

    def test_preference_engine_invocation_on_chat_feedback(self):
        """Verify chat feedback directives invoke preference engine and codify to .clipping_preferences.json."""
        self._init_and_approve_guidelines()

        feedback = "target 32s and audio bgm volume -24 dB and move framing left"
        res = self.run_cli([
            "checkpoint",
            "--step",
            "clipping-assembly",
            "--feedback",
            feedback,
            "--force",
            "--dir",
            str(self.project_dir),
        ])
        self.assertEqual(res.returncode, 0)
        self.assertIn("Chat Directives:", res.stdout)

        # Check preferences file was written
        pref_file = self.project_dir / PROJECT_PREFERENCES_FILENAME
        self.assertTrue(pref_file.is_file(), "Preferences file was not created")
        with open(pref_file, "r", encoding="utf-8") as f:
            prefs = json.load(f)

        self.assertEqual(prefs.get("duration", {}).get("target_seconds"), 32.0)
        self.assertEqual(prefs.get("audio", {}).get("bgm_volume_db"), -24.0)
        self.assertEqual(prefs.get("framing", {}).get("speaker_anchor_x"), 0.35)

    def test_auto_approve_flag(self):
        """Verify --auto-approve stages, marks reviewed, and immediately advances step."""
        self._init_and_approve_guidelines()

        res = self.run_cli([
            "checkpoint",
            "--step",
            "clipping-transcription",
            "--auto-approve",
            "--force",
            "--dir",
            str(self.project_dir),
        ])
        self.assertEqual(res.returncode, 0)
        self.assertIn("Auto-Approve:", res.stdout)

        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        step_state = state["steps"]["clipping-transcription"]
        self.assertTrue(step_state["approved"])
        self.assertEqual(step_state["status"], "completed")
        self.assertTrue(step_state["checkpoint"]["reviewed"])
        self.assertTrue(step_state["checkpoint"]["cleared"])
        self.assertEqual(state["current_step"], "clipping-hook-hunter")

    def test_save_detection_and_project_diffing_on_flag_file(self):
        """Verify manual Remotion Studio save (.gui_companion_saved.flag) triggers project diffing."""
        self._init_and_approve_guidelines()

        # Create baseline and modified user project
        base_data = self._create_mock_remotion_project(bgm_vol=-20.0, sfx_vol=-2.0, speaker_anchor=(960.0, 540.0))
        user_data = self._create_mock_remotion_project(bgm_vol=-25.0, sfx_vol=-6.0, speaker_anchor=(480.0, 486.0))  # shifted left

        base_file = self.project_dir / "baseline.remotion.json"
        user_file = self.project_dir / "test_clip.remotion.json"
        with open(base_file, "w", encoding="utf-8") as f:
            json.dump(base_data, f)
        with open(user_file, "w", encoding="utf-8") as f:
            json.dump(user_data, f)

        # Place save detection flag file
        flag_file = self.project_dir / DEFAULT_FLAG_FILENAME
        with open(flag_file, "w", encoding="utf-8") as f:
            json.dump({"event": "project_saved", "path": str(user_file)}, f)

        res = self.run_cli([
            "checkpoint",
            "--step",
            "clipping-assembly",
            "--project-file",
            str(user_file),
            "--baseline-file",
            str(base_file),
            "--dir",
            str(self.project_dir),
        ])
        self.assertEqual(res.returncode, 0, f"Checkpoint failed: {res.stderr}")
        self.assertIn("Project Diffs:", res.stdout)

        # Verify flag was consumed
        self.assertFalse(flag_file.is_file(), "Flag file was not consumed after diffing")

        # Verify codified preferences in project store
        pref_file = self.project_dir / PROJECT_PREFERENCES_FILENAME
        self.assertTrue(pref_file.is_file())
        with open(pref_file, "r", encoding="utf-8") as f:
            prefs = json.load(f)

        self.assertEqual(prefs.get("audio", {}).get("bgm_volume_db"), -25.0)
        self.assertEqual(prefs.get("audio", {}).get("sfx_volume_db"), -6.0)
        self.assertEqual(prefs.get("framing", {}).get("speaker_anchor_x"), 0.25)

    def test_diff_project_flag_triggers_heuristic_diffing(self):
        """Verify --diff-project explicitly forces differential comparison."""
        self._init_and_approve_guidelines()

        base_data = self._create_mock_remotion_project(scale=177.78)
        user_data = self._create_mock_remotion_project(scale=210.00)

        base_file = self.project_dir / "baseline.remotion.json"
        user_file = self.project_dir / "test_clip.remotion.json"
        with open(base_file, "w", encoding="utf-8") as f:
            json.dump(base_data, f)
        with open(user_file, "w", encoding="utf-8") as f:
            json.dump(user_data, f)

        res = self.run_cli([
            "checkpoint",
            "--step",
            "clipping-assembly",
            "--project-file",
            str(user_file),
            "--baseline-file",
            str(base_file),
            "--diff-project",
            "--dir",
            str(self.project_dir),
        ])
        self.assertEqual(res.returncode, 0)
        self.assertIn("Project Diffs:", res.stdout)

        pref_file = self.project_dir / PROJECT_PREFERENCES_FILENAME
        self.assertTrue(pref_file.is_file())
        with open(pref_file, "r", encoding="utf-8") as f:
            prefs = json.load(f)
        self.assertEqual(prefs.get("framing", {}).get("foreground_scale"), 210.0)

    def test_gui_companion_sync_timeline_reload_with_mock_server(self):
        """Verify checkpoint synchronizes with active GUI companion and triggers timeline reload."""
        self._init_and_approve_guidelines()

        # Start mock Remotion server on random port
        mock_server = MockRemotionServer(port=0)
        mock_server.start()
        mock_server.ready_event.wait(timeout=2.0)
        server_port = mock_server.port

        try:
            # Create project file
            user_data = self._create_mock_remotion_project()
            user_file = self.project_dir / "test_clip.remotion.json"
            with open(user_file, "w", encoding="utf-8") as f:
                json.dump(user_data, f)

            # Record companion state with mock port
            companion_state_file = self.project_dir / ".gui_companion.json"
            with open(companion_state_file, "w", encoding="utf-8") as f:
                json.dump({"port": server_port, "status": "running"}, f)

            res = self.run_cli([
                "checkpoint",
                "--step",
                "clipping-assembly",
                "--project-file",
                str(user_file),
                "--dir",
                str(self.project_dir),
            ])
            self.assertEqual(res.returncode, 0, f"Checkpoint failed: {res.stderr}")
            self.assertIn(f"Connected (port {server_port})", res.stdout)

            with open(self.state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.assertTrue(state["steps"]["clipping-assembly"]["checkpoint"]["companion_active"])

        finally:
            mock_server.stop_server()

    def test_status_command_surfaces_checkpoint_state(self):
        """Verify status command renders checkpoint summary and JSON metadata."""
        self._init_and_approve_guidelines()
        self.run_cli(["checkpoint", "--step", "clipping-transcription", "--force", "--dir", str(self.project_dir)], check=True)

        res = self.run_cli(["status", "--dir", str(self.project_dir)])
        self.assertEqual(res.returncode, 0)
        self.assertIn("Checkpoint:   [AWAITING REVIEW - PAUSED] (clipping-transcription)", res.stdout)

        res_json = self.run_cli(["status", "--json", "--dir", str(self.project_dir)])
        self.assertEqual(res_json.returncode, 0)
        state_json = json.loads(res_json.stdout)
        self.assertIn("checkpoint", state_json)
        self.assertEqual(state_json["checkpoint"]["step"], "clipping-transcription")
        self.assertFalse(state_json["checkpoint"]["reviewed"])


if __name__ == "__main__":
    unittest.main()
