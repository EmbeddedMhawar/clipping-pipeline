#!/usr/bin/env python3
"""
tests/test_clipping_assembly.py

Comprehensive test suite verifying the clipping-assembly engine and
checkpoint triggering (GitHub Issue #29).

Verifies:
1. FcprojBuilder JSON schema validity against `filmcraft-cli inspect sequence`
2. Track stack layering (4 video tracks, 3 audio tracks)
3. Speaker ping-pong crop calculations & punch-in scaling
4. Dead air pruning (>0.40s) with consonant protection buffer (0.08s)
5. Integration with clipping_state.py and interactive checkpoint generation
6. CLI assemble and inspect subcommands
7. Skill definition and architecture in skills/clipping-assembly/SKILL.md
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.clipping_assembly import (
    DEFAULT_BG_SCALE_PCT,
    DEFAULT_CANVAS_HEIGHT,
    DEFAULT_CANVAS_WIDTH,
    DEFAULT_FILL_SCALE_PCT,
    DEFAULT_SRC_HEIGHT,
    DEFAULT_SRC_WIDTH,
    MIN_CUT_DURATION_SEC,
    SPEAKER_CENTER_XC,
    SPEAKER_DEFAULT_YC,
    SPEAKER_GUEST_XC,
    SPEAKER_HOST_XC,
    TICKS_PER_SEC,
    TRACK_A1_NAME,
    TRACK_A2_NAME,
    TRACK_A3_NAME,
    TRACK_V1_NAME,
    TRACK_V2_NAME,
    TRACK_V3_NAME,
    TRACK_V4_NAME,
    WATERMARK_POS_X,
    WATERMARK_POS_Y,
    WATERMARK_SCALE_PCT,
    AssemblyConfig,
    FcprojBuilder,
    SubCut,
    assemble_vertical_project,
    frames_to_ticks,
    parse_cuts_data,
    prune_dead_air,
    seconds_to_ticks,
    ticks_to_seconds,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_FILE = REPO_ROOT / "skills" / "clipping-assembly" / "SKILL.md"


class TestFcprojBuilder(unittest.TestCase):
    """Unit tests for the FcprojBuilder class and time base conversions."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.media_file = self.tmp / "test_footage.mp4"
        self.media_file.write_bytes(b"\x00" * 1024)
        self.wm_file = self.tmp / "watermark.png"
        self.wm_file.write_bytes(b"\x00" * 512)
        self.bgm_file = self.tmp / "bgm.mp3"
        self.bgm_file.write_bytes(b"\x00" * 512)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ticks_conversion_precision(self):
        """Verifies high-precision integer tick calculations."""
        self.assertEqual(TICKS_PER_SEC, 254_016_000_000)
        self.assertEqual(seconds_to_ticks(1.0), 254_016_000_000)
        self.assertAlmostEqual(ticks_to_seconds(254_016_000_000), 1.0)

        # Standard broadcast frame rates
        self.assertEqual(frames_to_ticks(1, 24), 10_584_000_000)
        self.assertEqual(frames_to_ticks(1, 25), 10_160_640_000)
        self.assertEqual(frames_to_ticks(1, 30), 8_467_200_000)
        self.assertEqual(frames_to_ticks(1, 60), 4_233_600_000)

    def test_fcproj_schema_validity_with_filmcraft_cli(self):
        """Validates declarative JSON project against filmcraft-cli inspect sequence."""
        out_proj = self.tmp / "test_declarative.fcproj"
        config = AssemblyConfig(
            project_name="TestSchemaValidity",
            output_path=out_proj,
            media_path=self.media_file,
            watermark_path=self.wm_file,
            bgm_path=self.bgm_file,
            sub_cuts=[
                SubCut(start=0.0, end=4.0, speaker="host", punch_in=1.0),
                SubCut(start=5.0, end=9.0, speaker="guest", punch_in=1.12),
            ],
        )

        builder = FcprojBuilder(config)
        doc = builder.build()

        with open(out_proj, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)

        # Basic document structure
        self.assertEqual(doc["format"], "filmcraft.project")
        self.assertEqual(doc["schema_version"], 12)
        self.assertEqual(doc["generator"], "FilmCraft 0.4.0")
        self.assertIn("project", doc)
        self.assertIn("items", doc["project"])
        self.assertIn("view", doc)

        # Test against filmcraft-cli if binary is available
        cli_path = shutil.which("filmcraft-cli")
        if cli_path:
            res = subprocess.run(
                [cli_path, "--project", str(out_proj), "inspect", "sequence"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode,
                0,
                f"filmcraft-cli failed on declarative project: {res.stderr}",
            )
            parsed_inspect = json.loads(res.stdout)
            self.assertIn("video", parsed_inspect)
            self.assertIn("audio", parsed_inspect)
            self.assertEqual(len(parsed_inspect["video"]), 4)
            self.assertEqual(len(parsed_inspect["audio"]), 3)

    def test_track_stack_layering(self):
        """Verifies strict 4-video / 3-audio track hierarchy and configurations."""
        out_proj = self.tmp / "test_tracks.fcproj"
        config = AssemblyConfig(
            project_name="TrackStackTest",
            output_path=out_proj,
            media_path=self.media_file,
            watermark_path=self.wm_file,
            bgm_path=self.bgm_file,
            bgm_volume_db=-18.0,
            sfx_volume_db=-4.0,
            sub_cuts=[
                SubCut(start=0.0, end=5.0, speaker="host"),
                SubCut(start=6.0, end=11.0, speaker="guest"),
            ],
        )

        builder = FcprojBuilder(config)
        doc = builder.build()

        seq = doc["project"]["items"]["1"]["kind"]["Sequence"]
        v_tracks = seq["video_tracks"]
        a_tracks = seq["audio_tracks"]

        self.assertEqual(len(v_tracks), 4)
        self.assertEqual(len(a_tracks), 3)

        # Track V1: Blurred Background
        self.assertEqual(v_tracks[0]["name"], TRACK_V1_NAME)
        v1_effects = v_tracks[0]["items"][0]["effects"]
        effect_names = [e["effect"] for e in v1_effects]
        self.assertIn("gaussian_blur", effect_names)
        self.assertIn("motion", effect_names)
        self.assertIn("opacity", effect_names)
        self.assertIn("time_remap", effect_names)

        # V1 scale check: 209.78% (fill * 1.18)
        motion_v1 = next(e for e in v1_effects if e["effect"] == "motion")
        self.assertAlmostEqual(
            motion_v1["params"]["scale"]["value"]["Float"],
            DEFAULT_BG_SCALE_PCT,
            places=3,
        )
        blur_v1 = next(e for e in v1_effects if e["effect"] == "gaussian_blur")
        self.assertEqual(blur_v1["params"]["blurriness"]["value"]["Float"], 45.0)
        self.assertTrue(blur_v1["params"]["repeat_edge"]["value"]["Bool"])
        opacity_v1 = next(e for e in v1_effects if e["effect"] == "opacity")
        self.assertEqual(opacity_v1["params"]["opacity"]["value"]["Float"], 40.0)

        # Track V2: Speaker Foreground
        self.assertEqual(v_tracks[1]["name"], TRACK_V2_NAME)
        self.assertEqual(len(v_tracks[1]["items"]), 2)
        v2_item_0 = v_tracks[1]["items"][0]
        self.assertIsNotNone(v2_item_0["link"])
        motion_v2 = next(e for e in v2_item_0["effects"] if e["effect"] == "motion")
        self.assertAlmostEqual(
            motion_v2["params"]["scale"]["value"]["Float"],
            DEFAULT_FILL_SCALE_PCT,
            places=3,
        )

        # Track V3: HUD & Overlays
        self.assertEqual(v_tracks[2]["name"], TRACK_V3_NAME)

        # Track V4: Watermark
        self.assertEqual(v_tracks[3]["name"], TRACK_V4_NAME)
        self.assertEqual(len(v_tracks[3]["items"]), 1)
        v4_item = v_tracks[3]["items"][0]
        motion_v4 = next(e for e in v4_item["effects"] if e["effect"] == "motion")
        self.assertEqual(
            motion_v4["params"]["scale"]["value"]["Float"], WATERMARK_SCALE_PCT
        )
        self.assertEqual(
            motion_v4["params"]["position"]["value"]["Vec2"]["x"], WATERMARK_POS_X
        )
        self.assertEqual(
            motion_v4["params"]["position"]["value"]["Vec2"]["y"], WATERMARK_POS_Y
        )

        # Audio Track A1: Dialogue (volume 0.0 dB, phase-locked link to V2)
        self.assertEqual(a_tracks[0]["name"], TRACK_A1_NAME)
        self.assertEqual(a_tracks[0]["volume_db"], 0.0)
        a1_item_0 = a_tracks[0]["items"][0]
        self.assertEqual(a1_item_0["link"], v2_item_0["link"])

        # Audio Track A2: Background Music (ducked -18.0 dB)
        self.assertEqual(a_tracks[1]["name"], TRACK_A2_NAME)
        self.assertEqual(a_tracks[1]["volume_db"], -18.0)

        # Audio Track A3: SFX transients (-4.0 dB)
        self.assertEqual(a_tracks[2]["name"], TRACK_A3_NAME)
        self.assertEqual(a_tracks[2]["volume_db"], -4.0)

    def test_speaker_ping_pong_crop_calculations(self):
        """Verifies speaker anchor coordinates and punch-in scaling."""
        out_proj = self.tmp / "test_ping_pong.fcproj"
        config = AssemblyConfig(
            project_name="PingPongTest",
            output_path=out_proj,
            media_path=self.media_file,
            src_width=1920,
            src_height=1080,
            sub_cuts=[
                SubCut(start=0.0, end=3.0, speaker="host", punch_in=1.00),
                SubCut(start=4.0, end=7.0, speaker="guest", punch_in=1.12),
                SubCut(start=8.0, end=11.0, speaker="center", punch_in=1.06),
            ],
        )

        builder = FcprojBuilder(config)
        doc = builder.build()

        seq = doc["project"]["items"]["1"]["kind"]["Sequence"]
        v2_items = seq["video_tracks"][1]["items"]

        # Cut 1: Host (x_c = 0.25 -> anchor_x = 1920 * 0.25 = 480.0)
        motion_0 = next(e for e in v2_items[0]["effects"] if e["effect"] == "motion")
        self.assertEqual(
            motion_0["params"]["anchor"]["value"]["Vec2"]["x"], 1920 * SPEAKER_HOST_XC
        )
        self.assertEqual(
            motion_0["params"]["anchor"]["value"]["Vec2"]["y"], 1080 * SPEAKER_DEFAULT_YC
        )
        self.assertAlmostEqual(
            motion_0["params"]["scale"]["value"]["Float"],
            DEFAULT_FILL_SCALE_PCT * 1.00,
            places=3,
        )

        # Cut 2: Guest (x_c = 0.75 -> anchor_x = 1920 * 0.75 = 1440.0, punch-in 1.12)
        motion_1 = next(e for e in v2_items[1]["effects"] if e["effect"] == "motion")
        self.assertEqual(
            motion_1["params"]["anchor"]["value"]["Vec2"]["x"], 1920 * SPEAKER_GUEST_XC
        )
        self.assertAlmostEqual(
            motion_1["params"]["scale"]["value"]["Float"],
            DEFAULT_FILL_SCALE_PCT * 1.12,
            places=3,
        )

        # Cut 3: Center (x_c = 0.50 -> anchor_x = 1920 * 0.50 = 960.0, punch-in 1.06)
        motion_2 = next(e for e in v2_items[2]["effects"] if e["effect"] == "motion")
        self.assertEqual(
            motion_2["params"]["anchor"]["value"]["Vec2"]["x"], 1920 * SPEAKER_CENTER_XC
        )
        self.assertAlmostEqual(
            motion_2["params"]["scale"]["value"]["Float"],
            DEFAULT_FILL_SCALE_PCT * 1.06,
            places=3,
        )

    def test_dead_air_pruning_with_consonant_buffer(self):
        """Verifies dead air excision (>0.40s) and 0.08s consonant tail padding."""
        raw_cuts = [
            SubCut(start=1.0, end=3.0, speaker="host"),
            # Gap of 0.8s (> 0.40s): dead air should be pruned, consonant buffer 0.08s applied to cut 1
            SubCut(start=3.8, end=5.0, speaker="guest"),
            # Tight gap of 0.04s (< 0.08s): collision guard should cap pad to (0.04 - 0.01) = 0.03s
            SubCut(start=5.04, end=7.0, speaker="host"),
        ]

        pruned = prune_dead_air(
            raw_cuts, silence_threshold=0.40, consonant_buffer=0.08
        )
        self.assertEqual(len(pruned), 3)

        # Cut 1: pad should be 0.08s -> effective end = 3.08
        self.assertAlmostEqual(pruned[0].effective_end, 3.08, places=3)

        # Cut 2: next start is 5.04 -> max pad is max(0, 5.04 - 5.0 - 0.01) = 0.03s
        self.assertAlmostEqual(pruned[1].effective_end, 5.03, places=3)
        self.assertLess(pruned[1].effective_end, pruned[2].start)

        # Cut 3: last cut receives full 0.08s pad
        self.assertAlmostEqual(pruned[2].effective_end, 7.08, places=3)

    def test_parse_cuts_data_variations(self):
        """Verifies parsing of arbitrary cuts JSON payloads."""
        # 1. Plain array
        arr = [{"start": 1.0, "end": 4.0, "speaker": "host"}]
        cuts = parse_cuts_data(arr)
        self.assertEqual(len(cuts), 1)
        self.assertEqual(cuts[0].x_center, SPEAKER_HOST_XC)

        # 2. Dict with 'cuts'
        obj_cuts = {"cuts": [{"start": 2.0, "end": 5.0, "speaker": "guest"}]}
        cuts = parse_cuts_data(obj_cuts)
        self.assertEqual(len(cuts), 1)
        self.assertEqual(cuts[0].x_center, SPEAKER_GUEST_XC)

        # 3. Dict with 'hook'
        obj_hook = {"hook": {"start": 0.0, "end": 10.0, "speaker": "center", "zoom": 1.12}}
        cuts = parse_cuts_data(obj_hook)
        self.assertEqual(len(cuts), 1)
        self.assertEqual(cuts[0].punch_in, 1.12)


class TestClippingAssemblyIntegration(unittest.TestCase):
    """Verifies state machine integration and interactive companion checkpoint gate."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)
        self.media_file = self.project_dir / "raw_video.mp4"
        self.media_file.write_bytes(b"\x00" * 2048)

        # Initialize .clipping_state.json with prerequisites completed
        self._init_project_state()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _init_project_state(self):
        now = datetime.now(timezone.utc).isoformat()
        state = {
            "version": "1.0.0",
            "created_at": now,
            "updated_at": now,
            "current_step": "clipping-assembly",
            "guidelines_approved": True,
            "campaign": {"title": "Test Assembly Campaign", "project": "test_assembly"},
            "steps": {
                "clipping-guidelines": {
                    "status": "approved",
                    "approved": True,
                    "completed_at": now,
                    "params": {},
                },
                "clipping-transcription": {
                    "status": "completed",
                    "approved": True,
                    "completed_at": now,
                    "params": {},
                },
                "clipping-hook-hunter": {
                    "status": "completed",
                    "approved": True,
                    "completed_at": now,
                    "params": {},
                },
                "clipping-assembly": {
                    "status": "pending",
                    "approved": False,
                    "completed_at": None,
                    "params": {},
                },
                "clipping-captions": {
                    "status": "pending",
                    "approved": False,
                    "completed_at": None,
                    "params": {},
                },
            },
        }
        state_file = self.project_dir / ".clipping_state.json"
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def test_assembly_and_checkpoint_trigger(self):
        """Verifies assembling project stages state and triggers checkpoint gate."""
        cuts_data = [
            {"start": 0.0, "end": 5.0, "speaker": "host"},
            {"start": 6.0, "end": 12.0, "speaker": "guest", "punch_in": 1.12},
        ]
        cuts_file = self.project_dir / "cuts.json"
        with open(cuts_file, "w", encoding="utf-8") as f:
            json.dump(cuts_data, f)

        res = assemble_vertical_project(
            media_path=self.media_file,
            output_dir=self.project_dir,
            cuts_path=cuts_file,
            project_dir=self.project_dir,
            project_name="test_assembly",
            trigger_checkpoint=True,
        )

        self.assertEqual(res["status"], "success")
        fcproj_path = Path(res["project_file"])
        meta_path = Path(res["meta_file"])

        self.assertTrue(fcproj_path.is_file())
        self.assertTrue(meta_path.is_file())

        # Check state persistence
        state_file = self.project_dir / ".clipping_state.json"
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        step_asm = state["steps"]["clipping-assembly"]
        self.assertIn(step_asm["status"], ("staged", "awaiting_checkpoint"))
        self.assertTrue(step_asm.get("checkpoint", {}).get("staged") or step_asm.get("staged"))
        self.assertIn("project_file", step_asm["params"])
        self.assertEqual(step_asm["params"]["project_name"], "test_assembly")
        self.assertEqual(step_asm["params"]["cuts_count"], 2)

        # Checkpoint gate verification: review artifact should be created
        artifact_path = self.project_dir / "checkpoint_clipping-assembly.md"
        self.assertTrue(
            artifact_path.is_file(),
            f"Expected checkpoint review artifact at {artifact_path}",
        )
        artifact_content = artifact_path.read_text(encoding="utf-8")
        self.assertIn("RequestFeedback: true", artifact_content)
        self.assertIn("clipping-assembly", artifact_content)

        # Downstream pre-flight validation must block until checkpoint is approved
        clipping_state_cli = REPO_ROOT / "scripts" / "clipping_state.py"
        val_res = subprocess.run(
            [
                sys.executable,
                str(clipping_state_cli),
                "validate",
                "--step",
                "clipping-captions",
                "--dir",
                str(self.project_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            val_res.returncode,
            2,
            "Downstream step must be blocked while checkpoint review is pending",
        )

        # Verify approval is blocked while checkpoint is unreviewed
        appr_blocked = subprocess.run(
            [
                sys.executable,
                str(clipping_state_cli),
                "approve",
                "--step",
                "clipping-assembly",
                "--dir",
                str(self.project_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            appr_blocked.returncode,
            2,
            "Approval must be blocked while checkpoint review is unresolved",
        )

        # Register operator chat feedback / review
        fb_res = subprocess.run(
            [
                sys.executable,
                str(clipping_state_cli),
                "checkpoint",
                "--step",
                "clipping-assembly",
                "--dir",
                str(self.project_dir),
                "--feedback",
                "Approved framing and dead air excision",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(fb_res.returncode, 0)

        # Approving now succeeds and unblocks downstream step
        appr_res = subprocess.run(
            [
                sys.executable,
                str(clipping_state_cli),
                "approve",
                "--step",
                "clipping-assembly",
                "--dir",
                str(self.project_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(appr_res.returncode, 0)

        val_res_after = subprocess.run(
            [
                sys.executable,
                str(clipping_state_cli),
                "validate",
                "--step",
                "clipping-captions",
                "--dir",
                str(self.project_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            val_res_after.returncode,
            0,
            "Downstream step must be cleared after assembly approval",
        )

    def test_cli_assemble_and_inspect(self):
        """Verifies CLI execution of assemble and inspect subcommands."""
        cuts_file = self.project_dir / "cuts.json"
        with open(cuts_file, "w", encoding="utf-8") as f:
            json.dump([{"start": 1.0, "end": 6.0, "speaker": "host"}], f)

        asm_cli = REPO_ROOT / "scripts" / "clipping_assembly.py"

        # 1. assemble CLI
        res_asm = subprocess.run(
            [
                sys.executable,
                str(asm_cli),
                "assemble",
                "--media",
                str(self.media_file),
                "--cuts",
                str(cuts_file),
                "--output-dir",
                str(self.project_dir / "out"),
                "--project-dir",
                str(self.project_dir),
                "--project-name",
                "cli_clip",
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_asm.returncode, 0, f"CLI assemble failed: {res_asm.stderr}")
        asm_data = json.loads(res_asm.stdout)
        self.assertEqual(asm_data["status"], "success")
        created_fcproj = Path(asm_data["project_file"])
        self.assertTrue(created_fcproj.is_file())

        # 2. inspect CLI
        res_inspect = subprocess.run(
            [
                sys.executable,
                str(asm_cli),
                "inspect",
                "--project",
                str(created_fcproj),
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_inspect.returncode, 0)
        inspect_data = json.loads(res_inspect.stdout)
        self.assertEqual(inspect_data["project_name"], "cli_clip")
        self.assertEqual(len(inspect_data["video_tracks"]), 4)
        self.assertEqual(len(inspect_data["audio_tracks"]), 3)


class TestClippingAssemblySkill(unittest.TestCase):
    """Verifies skills/clipping-assembly/SKILL.md architecture and contents."""

    def test_skill_file_exists_and_frontmatter(self):
        self.assertTrue(SKILL_FILE.is_file(), f"Skill file not found at {SKILL_FILE}")
        content = SKILL_FILE.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---"))
        parts = content.split("---", 2)
        self.assertGreaterEqual(len(parts), 3)
        frontmatter = parts[1]
        self.assertIn("name: clipping-assembly", frontmatter)
        self.assertIn("9:16 vertical video", frontmatter)

    def test_skill_context_pointers_and_steps(self):
        content = SKILL_FILE.read_text(encoding="utf-8")
        self.assertIn("GLOSSARY.md", content)
        self.assertIn("fcproj-assembly-spec.md", content)
        self.assertIn("scripts/clipping_assembly.py", content)
        self.assertIn("scripts/clipping_state.py", content)
        self.assertIn("scripts/gui_companion.py", content)

        expected_sections = [
            "State & Pre-Flight Gate Inspection",
            "Vertical Canvas Assembly & Dead Air Excision",
            "Live Companion Checkpoint & Timeline Inspection",
            "Feedback Registration & Step Approval",
            "Completion Criteria",
        ]
        for sec in expected_sections:
            self.assertIn(sec, content)


if __name__ == "__main__":
    unittest.main()
