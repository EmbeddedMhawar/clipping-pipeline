import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestClippingStateCLI(unittest.TestCase):
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

    def test_cli_exists_and_help(self):
        self.assertTrue(self.cli_path.is_file(), f"CLI not found at {self.cli_path}")
        result = self.run_cli(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("clipping_state.py", result.stdout.lower() + result.stderr.lower())

    def test_cli_directly_executable(self):
        # Verify script is executable as a standalone binary
        cmd = [str(self.cli_path), "--help"]
        result = subprocess.run(
            cmd,
            cwd=str(self.project_dir),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage", result.stdout.lower())

    def test_init_command(self):
        # Initial run creates state file
        res = self.run_cli(["init", "--dir", str(self.project_dir)])
        self.assertEqual(res.returncode, 0, f"init failed: {res.stderr}")
        self.assertTrue(self.state_file.is_file())

        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        self.assertEqual(state["version"], "1.0.0")
        self.assertFalse(state["guidelines_approved"])
        self.assertEqual(state["current_step"], "clipping-guidelines")
        self.assertIn("steps", state)
        self.assertIn("approval", state)

        expected_steps = [
            "clipping-guidelines",
            "clipping-transcription",
            "clipping-hook-hunter",
            "clipping-assembly",
            "clipping-captions",
            "clipping-vfx-sfx",
            "clipping-qc-packager",
            "clipping-publisher",
        ]
        for step in expected_steps:
            self.assertIn(step, state["steps"])
            self.assertEqual(state["steps"][step]["status"], "pending")
            self.assertFalse(state["steps"][step]["approved"])

        # Running init again without --force should fail
        res2 = self.run_cli(["init", "--dir", str(self.project_dir)])
        self.assertNotEqual(res2.returncode, 0)

        # Running init with --force should succeed
        res3 = self.run_cli(["init", "--force", "--dir", str(self.project_dir)])
        self.assertEqual(res3.returncode, 0)

    def test_ingest_brief_populates_state_and_step_slices(self):
        # Initialize first
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)

        brief_data = {
            "campaign": {
                "title": "N3on x MPJ Clipping Campaign",
                "client": "Curious Mike",
                "project": "n3on-x-mpj",
                "source_video": {
                    "url": "https://www.youtube.com/watch?v=GfVYVEPSLIM",
                    "channel": "@mpj",
                    "duration": "1:36:59",
                },
                "economics": {
                    "rate_per_1k_views": 1.0,
                    "min_payout_views": 2000,
                    "max_payout_views_per_clip": 300000,
                    "max_dollar_per_clip": 300.0,
                },
                "platforms": ["TikTok", "Instagram Reels", "YouTube Shorts"],
                "daily_post_limit": 4,
            },
            "global_rules": {
                "duration": {
                    "min_seconds": 20.0,
                    "max_seconds": 60.0,
                    "ideal_min": 25.0,
                    "ideal_max": 45.0,
                },
                "tier1_geo_min_pct": 40.0,
                "engagement_min_pct": 1.0,
                "watermark": {
                    "required": True,
                    "asset_path": "assets/watermark_yt_mpj.png",
                    "persistent_entire_clip": True,
                    "banned_corners": True,
                },
                "caption_closers": [
                    "watch the full episode @mpj on youtube",
                    "full episode is on @mpj on youtube",
                ],
                "audio": {
                    "zero_background_music": True,
                    "zero_phonk": True,
                    "loudness_target_lufs": -14.0,
                },
                "prohibited_edits": ["aura", "glow", "skull"],
                "single_post_per_edit": True,
            },
            "platform_overrides": {
                "youtube_shorts": {
                    "api_upload_allowed": True,
                    "handle_format": "tagged",
                    "bio_verification_code_required": True,
                },
                "tiktok": {
                    "api_upload_allowed": False,
                    "handle_format": "plain_text",
                },
            },
        }

        brief_path = self.project_dir / "campaign_brief.json"
        with open(brief_path, "w", encoding="utf-8") as f:
            json.dump(brief_data, f, indent=2)

        ingest_res = self.run_cli(
            ["ingest-brief", "--brief", str(brief_path), "--dir", str(self.project_dir)]
        )
        self.assertEqual(ingest_res.returncode, 0, f"ingest failed: {ingest_res.stderr}")

        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        self.assertEqual(state["campaign"]["title"], "N3on x MPJ Clipping Campaign")
        self.assertEqual(state["campaign"]["project"], "n3on-x-mpj")
        self.assertFalse(state["guidelines_approved"])
        self.assertEqual(
            state["steps"]["clipping-guidelines"]["status"], "awaiting_approval"
        )

        # Check pre-digested slices
        hook_params = state["steps"]["clipping-hook-hunter"]["params"]
        self.assertEqual(hook_params["target_duration_range"], [25.0, 45.0])
        self.assertEqual(hook_params["hard_bounds"], [20.0, 60.0])

        caption_params = state["steps"]["clipping-captions"]["params"]
        self.assertEqual(caption_params["margin_v"], 420)
        self.assertEqual(caption_params["caption_style"], "zylok_kinetic")

        vfx_params = state["steps"]["clipping-vfx-sfx"]["params"]
        self.assertTrue(vfx_params["watermark_required"])
        self.assertEqual(vfx_params["watermark_asset"], "assets/watermark_yt_mpj.png")

        qc_params = state["steps"]["clipping-qc-packager"]["params"]
        self.assertEqual(qc_params["target_loudness_lufs"], -14.0)
        self.assertEqual(
            qc_params["caption_closers"],
            [
                "watch the full episode @mpj on youtube",
                "full episode is on @mpj on youtube",
            ],
        )

    def test_ingest_brief_missing_or_invalid_file(self):
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)

        # Non-existent file
        res = self.run_cli(
            ["ingest-brief", "--brief", "/non/existent/path.json", "--dir", str(self.project_dir)]
        )
        self.assertNotEqual(res.returncode, 0)

        # Malformed json
        bad_json_path = self.project_dir / "bad.json"
        bad_json_path.write_text("{invalid json", encoding="utf-8")
        res2 = self.run_cli(
            ["ingest-brief", "--brief", str(bad_json_path), "--dir", str(self.project_dir)]
        )
        self.assertNotEqual(res2.returncode, 0)

    def test_get_step_config(self):
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)

        brief_data = {
            "campaign": {"title": "Test Campaign", "project": "test-p"},
            "global_rules": {"duration": {"ideal_min": 25.0, "ideal_max": 45.0}},
        }
        brief_path = self.project_dir / "campaign_brief.json"
        with open(brief_path, "w", encoding="utf-8") as f:
            json.dump(brief_data, f)
        self.run_cli(
            ["ingest-brief", "--brief", str(brief_path), "--dir", str(self.project_dir)],
            check=True,
        )

        # Check all 7 steps return valid JSON dictionaries
        steps = [
            "clipping-guidelines",
            "clipping-transcription",
            "clipping-hook-hunter",
            "clipping-assembly",
            "clipping-captions",
            "clipping-vfx-sfx",
            "clipping-qc-packager",
            "clipping-publisher",
        ]
        for step in steps:
            res = self.run_cli(
                ["get-step-config", "--step", step, "--dir", str(self.project_dir)]
            )
            self.assertEqual(res.returncode, 0, f"Failed config fetch for {step}")
            config = json.loads(res.stdout)
            self.assertIsInstance(config, dict)

        # Invalid step should return exit code 1
        res_invalid = self.run_cli(
            ["get-step-config", "--step", "non-existent-step", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_invalid.returncode, 1)

    def test_validate_pre_flight_gates(self):
        # 1. Without state file -> exit code 2
        res_missing = self.run_cli(
            ["validate", "--step", "clipping-guidelines", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_missing.returncode, 2)
        self.assertIn(".clipping_state.json not found", res_missing.stderr)

        # 2. Init state
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)

        # clipping-guidelines is the first step -> should pass (code 0)
        res_step1 = self.run_cli(
            ["validate", "--step", "clipping-guidelines", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_step1.returncode, 0)

        # clipping-transcription -> blocked because guidelines not approved (code 2)
        res_step2 = self.run_cli(
            ["validate", "--step", "clipping-transcription", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_step2.returncode, 2)
        self.assertIn(
            "Pre-flight Gate Blocked: Campaign guidelines must be approved before running 'clipping-transcription'.",
            res_step2.stderr,
        )

        # clipping-hook-hunter -> blocked with dynamic message including step name
        res_step3_pre = self.run_cli(
            ["validate", "--step", "clipping-hook-hunter", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_step3_pre.returncode, 2)
        self.assertIn(
            "Pre-flight Gate Blocked: Campaign guidelines must be approved before running 'clipping-hook-hunter'.",
            res_step3_pre.stderr,
        )

        # clipping-transcription with --force -> passes (code 0)
        res_step2_force = self.run_cli(
            [
                "validate",
                "--step",
                "clipping-transcription",
                "--force",
                "--dir",
                str(self.project_dir),
            ]
        )
        self.assertEqual(res_step2_force.returncode, 0)

        # unknown step -> code 1
        res_unknown = self.run_cli(
            ["validate", "--step", "unknown-step", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_unknown.returncode, 1)

    def test_approve_command_and_sequential_unblocking(self):
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)

        # Validate transcription is blocked
        res = self.run_cli(
            ["validate", "--step", "clipping-transcription", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res.returncode, 2)

        # Run approve on clipping-guidelines
        app_res = self.run_cli(
            [
                "approve",
                "--step",
                "clipping-guidelines",
                "--notes",
                "Human approved campaign rules",
                "--by",
                "TestReviewer",
                "--override",
                "target_loudness_lufs=-15.0",
                "enable_bonus=true",
                "max_clips=10",
                "--dir",
                str(self.project_dir),
            ]
        )
        self.assertEqual(app_res.returncode, 0, f"approve failed: {app_res.stderr}")

        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        self.assertTrue(state["guidelines_approved"])
        self.assertEqual(state["steps"]["clipping-guidelines"]["status"], "completed")
        self.assertTrue(state["steps"]["clipping-guidelines"]["approved"])
        self.assertIsNotNone(state["steps"]["clipping-guidelines"]["completed_at"])
        self.assertEqual(state["approval"]["approved_by"], "TestReviewer")
        self.assertEqual(state["approval"]["notes"], "Human approved campaign rules")
        self.assertEqual(state["approval"]["overrides"]["target_loudness_lufs"], -15.0)
        self.assertEqual(state["approval"]["overrides"]["enable_bonus"], True)
        self.assertEqual(state["approval"]["overrides"]["max_clips"], 10)

        # Now clipping-transcription should be unblocked (exit code 0)
        res_unblocked = self.run_cli(
            ["validate", "--step", "clipping-transcription", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_unblocked.returncode, 0)

        # Step 3 (clipping-hook-hunter) should still be blocked because transcription is pending
        res_step3 = self.run_cli(
            ["validate", "--step", "clipping-hook-hunter", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_step3.returncode, 2)

        # Approve transcription
        self.run_cli(
            ["approve", "--step", "clipping-transcription", "--dir", str(self.project_dir)],
            check=True,
        )

        # Now step 3 (clipping-hook-hunter) is unblocked
        res_step3_unblocked = self.run_cli(
            ["validate", "--step", "clipping-hook-hunter", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_step3_unblocked.returncode, 0)

    def test_full_sequential_gate_progression(self):
        # Test full chain through all 7 steps
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)

        steps = [
            "clipping-guidelines",
            "clipping-transcription",
            "clipping-hook-hunter",
            "clipping-assembly",
            "clipping-captions",
            "clipping-vfx-sfx",
            "clipping-qc-packager",
            "clipping-publisher",
        ]

        for i, step in enumerate(steps):
            # Step should be blocked before prior step approved (except first step)
            if i > 0:
                chk_blocked = self.run_cli(
                    ["validate", "--step", step, "--dir", str(self.project_dir)]
                )
                self.assertEqual(
                    chk_blocked.returncode,
                    2,
                    f"Step {step} was expected to be blocked at index {i}",
                )

                # Force should pass with code 0
                chk_forced = self.run_cli(
                    ["validate", "--step", step, "--force", "--dir", str(self.project_dir)]
                )
                self.assertEqual(chk_forced.returncode, 0)

                # Prior step approve
                prior_step = steps[i - 1]
                self.run_cli(
                    ["approve", "--step", prior_step, "--dir", str(self.project_dir)],
                    check=True,
                )

            # Now step should be unblocked
            chk_ok = self.run_cli(
                ["validate", "--step", step, "--dir", str(self.project_dir)]
            )
            self.assertEqual(chk_ok.returncode, 0, f"Step {step} should be unblocked")

        # Inject publication manifest before approving final step (clipping-publisher)
        with open(self.state_file, "r", encoding="utf-8") as f:
            state_data = json.load(f)
        state_data["steps"]["clipping-publisher"]["params"]["publication_manifest"] = [
            {"status": "published", "channel_id": "chan-01"}
        ]
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)

        # Approve final step
        self.run_cli(
            ["approve", "--step", steps[-1], "--dir", str(self.project_dir)],
            check=True,
        )

        # Verify status output with all steps completed
        status_res = self.run_cli(["status", "--dir", str(self.project_dir)])
        self.assertEqual(status_res.returncode, 0)
        self.assertIn("All steps completed", status_res.stdout)

    def test_status_command(self):
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)

        # Text/ASCII status
        res = self.run_cli(["status", "--dir", str(self.project_dir)])
        self.assertEqual(res.returncode, 0)
        self.assertIn("clipping-guidelines", res.stdout)
        self.assertIn("clipping-transcription", res.stdout)

        # JSON status
        res_json = self.run_cli(["status", "--json", "--dir", str(self.project_dir)])
        self.assertEqual(res_json.returncode, 0)
        status_obj = json.loads(res_json.stdout)
        self.assertIn("steps", status_obj)
        self.assertIn("guidelines_approved", status_obj)

    def test_ingest_sparse_brief_decoupled_defaults(self):
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)

        sparse_brief = {
            "campaign": {"title": "Generic Campaign", "project": "generic-p"},
            "global_rules": {},
        }
        brief_path = self.project_dir / "sparse_brief.json"
        brief_path.write_text(json.dumps(sparse_brief), encoding="utf-8")

        self.run_cli(
            ["ingest-brief", "--brief", str(brief_path), "--dir", str(self.project_dir)],
            check=True,
        )

        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        steps = state["steps"]

        # 1. Phonetic dictionary should be empty dict, not contain ADIN/MPJ
        trans_params = steps["clipping-transcription"]["params"]
        self.assertEqual(trans_params.get("phonetic_dictionary"), {})
        self.assertEqual(trans_params.get("diarization_speakers"), [])

        # 2. Priority hook topics should be empty list, not faked death/dubai jail
        hook_params = steps["clipping-hook-hunter"]["params"]
        self.assertEqual(hook_params.get("priority_hook_topics"), [])

        # 3. Speaker x anchors should be empty dict, not N3on/MPJ
        assembly_params = steps["clipping-assembly"]["params"]
        self.assertEqual(assembly_params.get("speaker_x_anchors"), {})

        # 4. Trigger keywords should be empty list, not N3ON/MPJ
        caption_params = steps["clipping-captions"]["params"]
        self.assertEqual(caption_params.get("trigger_keywords"), [])

        # 5. Watermark asset should be empty string when not specified
        vfx_params = steps["clipping-vfx-sfx"]["params"]
        self.assertEqual(vfx_params.get("watermark_asset"), "")

    def test_step8_publisher_preflight_gating(self):
        # 1. Init state
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)

        # 2. Step 8 validate should fail because guidelines not approved (exit code 2)
        res_step8_no_guide = self.run_cli(
            ["validate", "--step", "clipping-publisher", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_step8_no_guide.returncode, 2)
        self.assertIn(
            "Pre-flight Gate Blocked: Campaign guidelines must be approved before running 'clipping-publisher'.",
            res_step8_no_guide.stderr,
        )

        # 3. Approve guidelines
        self.run_cli(
            ["approve", "--step", "clipping-guidelines", "--dir", str(self.project_dir)],
            check=True,
        )

        # 4. Step 8 validate should still fail because Step 7 (clipping-qc-packager) is not completed (exit code 2)
        res_step8_unapproved = self.run_cli(
            ["validate", "--step", "clipping-publisher", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_step8_unapproved.returncode, 2)
        self.assertIn(
            "Final QC packaging must be completed before distribution/publishing.",
            res_step8_unapproved.stderr,
        )

        # 5. Step 8 validate with --force should pass with code 0
        res_step8_forced = self.run_cli(
            ["validate", "--step", "clipping-publisher", "--force", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_step8_forced.returncode, 0)

        # 6. Approve intermediate steps up to step 7
        intermediate_steps = [
            "clipping-transcription",
            "clipping-hook-hunter",
            "clipping-assembly",
            "clipping-captions",
            "clipping-vfx-sfx",
            "clipping-qc-packager",
        ]
        for step in intermediate_steps:
            self.run_cli(["approve", "--step", step, "--dir", str(self.project_dir)], check=True)

        # 7. Now Step 8 validate must pass (exit code 0)
        res_step8_approved = self.run_cli(
            ["validate", "--step", "clipping-publisher", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res_step8_approved.returncode, 0)
        self.assertIn("Pre-flight Gate Passed", res_step8_approved.stdout)

    def test_step7_decoupled_from_channels(self):
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)

        brief_data = {
            "campaign": {"title": "Test QC Decoupled", "project": "test-qc"},
            "global_rules": {
                "audio": {"loudness_target_lufs": -14.0},
                "caption_closers": ["closer1", "closer2"],
            },
        }
        brief_path = self.project_dir / "campaign_brief.json"
        brief_path.write_text(json.dumps(brief_data), encoding="utf-8")

        self.run_cli(
            ["ingest-brief", "--brief", str(brief_path), "--dir", str(self.project_dir)],
            check=True,
        )

        # Ensure channels.json does NOT exist in project
        self.assertFalse((self.project_dir / "channels.json").exists())

        # Calling get-step-config for Step 7 must succeed without channels.json
        res = self.run_cli(
            ["get-step-config", "--step", "clipping-qc-packager", "--dir", str(self.project_dir)]
        )
        self.assertEqual(res.returncode, 0)
        qc_params = json.loads(res.stdout)

        # Step 7 must not contain channel lists or device transfer configs
        self.assertNotIn("eligible_channels", qc_params)
        self.assertNotIn("ineligible_channels", qc_params)
        self.assertNotIn("device_transfer", qc_params)
        self.assertNotIn("default_device_transfer", qc_params)

        # Must still contain QC parameters
        self.assertEqual(qc_params.get("target_loudness_lufs"), -14.0)
        self.assertEqual(qc_params.get("caption_closers"), ["closer1", "closer2"])

    def test_approve_step8_without_manifest_fails(self):
        """Verifies approve --step clipping-publisher rejects with exit code 1 if publication_manifest is missing."""
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)
        res = self.run_cli(["approve", "--step", "clipping-publisher", "--dir", str(self.project_dir)])
        self.assertEqual(res.returncode, 1)
        self.assertIn("publication_manifest", res.stderr.lower())

    def test_approve_step8_with_force_bypasses_manifest_check(self):
        """Verifies approve --step clipping-publisher --force succeeds even when publication_manifest is missing."""
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)
        res = self.run_cli(["approve", "--step", "clipping-publisher", "--force", "--dir", str(self.project_dir)])
        self.assertEqual(res.returncode, 0)
        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        self.assertTrue(state["steps"]["clipping-publisher"]["approved"])
        self.assertEqual(state["steps"]["clipping-publisher"]["status"], "completed")

    def test_approve_step8_with_manifest_succeeds(self):
        """Verifies approve --step clipping-publisher succeeds with exit code 0 when publication_manifest is present."""
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)
        # Manually inject a publication manifest into step 8 params
        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        state["steps"]["clipping-publisher"]["params"]["publication_manifest"] = [
            {
                "status": "published",
                "platform": "YouTube Shorts",
                "channel_id": "chan-yt-01",
                "post_url": "https://youtube.com/shorts/test1234",
            }
        ]
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        res = self.run_cli(["approve", "--step", "clipping-publisher", "--dir", str(self.project_dir)])
        self.assertEqual(res.returncode, 0)
        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        self.assertTrue(state["steps"]["clipping-publisher"]["approved"])
        self.assertEqual(state["steps"]["clipping-publisher"]["status"], "completed")
        self.assertIsNotNone(state["steps"]["clipping-publisher"]["completed_at"])

    def test_approve_outputs_next_step_prompt(self):
        self.run_cli(["init", "--dir", str(self.project_dir)], check=True)
        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        state["campaign"] = {
            "title": "HardScope — Unpacked Episode 2",
            "project": "hardscope-unpacked-episode-2",
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        res = self.run_cli(
            ["approve", "--step", "clipping-guidelines", "--dir", str(self.project_dir)],
            check=True,
        )
        self.assertIn(
            "Campaign: HardScope — Unpacked Episode 2 (hardscope-unpacked-episode-2) proceed with Step 2 (clipping-transcription)",
            res.stdout,
        )

        state["guidelines_approved"] = True
        state["steps"]["clipping-transcription"]["approved"] = True
        state["steps"]["clipping-transcription"]["status"] = "completed"
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        res3 = self.run_cli(
            ["approve", "--step", "clipping-hook-hunter", "--dir", str(self.project_dir)],
            check=True,
        )
        self.assertIn(
            "Campaign: HardScope — Unpacked Episode 2 (hardscope-unpacked-episode-2) proceed with Step 4 (clipping-assembly)",
            res3.stdout,
        )


if __name__ == "__main__":
    unittest.main()

