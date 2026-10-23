#!/usr/bin/env python3
"""
tests/test_clipping_vfx_sfx.py

Unit test suite for Step 6: Visual Effects & Sound Design Compositing (clipping-vfx-sfx).
Tests procedural audio generation, watermark badge synthesis, emotional cue detection,
HyperFrames HTML/CSS/GSAP composition synthesis, Remotion (.remotion.json) timeline track
injection, manifest generation, and checkpoint staging.
"""

from dataclasses import asdict
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.clipping_vfx_sfx import (
    AudioTransientCue,
    SFX_DEFAULT_VOLUME_DB,
    SFX_SAMPLE_RATE,
    TICKS_PER_SEC,
    TRACK_A3_NAME,
    TRACK_V3_NAME,
    TRACK_V4_NAME,
    VisualOverlayCue,
    detect_vfx_sfx_cues,
    execute_vfx_sfx_step,
    inject_vfx_and_sfx_into_remotion,
    seconds_to_ticks,
    synthesize_brand_watermark_png,
    synthesize_color_stab_pass,
    synthesize_hyperframes_hook_html,
    synthesize_pop_wav,
    synthesize_sub_boom_wav,
    synthesize_whoosh_wav,
    ticks_to_seconds,
)


class TestTimeConversions(unittest.TestCase):
    """Tests tick and second conversions."""

    def test_seconds_to_ticks(self):
        self.assertEqual(seconds_to_ticks(1.0), TICKS_PER_SEC)
        self.assertEqual(seconds_to_ticks(0.0), 0)
        self.assertEqual(seconds_to_ticks(0.5), TICKS_PER_SEC // 2)

    def test_ticks_to_seconds(self):
        self.assertAlmostEqual(ticks_to_seconds(TICKS_PER_SEC), 1.0)
        self.assertAlmostEqual(ticks_to_seconds(0), 0.0)


class TestProceduralSFXSynthesis(unittest.TestCase):
    """Tests procedural 48kHz stereo WAV synthesis without external audio dependencies."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_synthesize_sub_boom_wav(self):
        out_wav = self.temp_path / "sub_boom.wav"
        res = synthesize_sub_boom_wav(out_wav, duration=0.5)
        self.assertTrue(res.is_file())
        with wave.open(str(res), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 2)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), SFX_SAMPLE_RATE)
            self.assertEqual(wf.getnframes(), int(0.5 * SFX_SAMPLE_RATE))

    def test_synthesize_whoosh_wav(self):
        out_wav = self.temp_path / "whoosh.wav"
        res = synthesize_whoosh_wav(out_wav, duration=0.4)
        self.assertTrue(res.is_file())
        with wave.open(str(res), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 2)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), SFX_SAMPLE_RATE)
            self.assertEqual(wf.getnframes(), int(0.4 * SFX_SAMPLE_RATE))

    def test_synthesize_pop_wav(self):
        out_wav = self.temp_path / "pop.wav"
        res = synthesize_pop_wav(out_wav, duration=0.2)
        self.assertTrue(res.is_file())
        with wave.open(str(res), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 2)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), SFX_SAMPLE_RATE)
            self.assertEqual(wf.getnframes(), int(0.2 * SFX_SAMPLE_RATE))


class TestWatermarkAndStabSynthesis(unittest.TestCase):
    """Tests watermark and color stab asset synthesis."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_synthesize_brand_watermark_png(self):
        out_png = self.temp_path / "watermark.png"
        res = synthesize_brand_watermark_png(out_png, brand_title="TestBrand", handle="@TestTV")
        self.assertTrue(res.is_file())
        self.assertGreater(res.stat().st_size, 100)

    def test_synthesize_color_stab_pass(self):
        out_mov = self.temp_path / "stab_red.mov"
        res = synthesize_color_stab_pass(out_mov, color_hex="#FF0000", duration_sec=0.2, fps=24)
        self.assertTrue(res.is_file())
        self.assertGreater(res.stat().st_size, 500)


class TestEmotionalCueDetection(unittest.TestCase):
    """Tests detection of watermark, title hook, color stabs, and SFX transients."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)

        # Mock captions.json
        self.captions_file = self.project_dir / "captions.json"
        captions_data = {
            "cues": [
                {"start": 0.0, "end": 1.5, "emotion": "*PURE SHOCK*", "words": [{"text": "WHAT"}]},
                {"start": 10.0, "end": 12.0, "emotion": "*SCREAMING CHAOS*", "words": [{"text": "BRO"}]},
                {"start": 20.0, "end": 22.5, "emotion": "*GRAIL PULL*", "words": [{"text": "GRAIL"}]},
            ]
        }
        with open(self.captions_file, "w") as f:
            json.dump(captions_data, f)

        # Mock meta file
        self.meta_file = self.project_dir / "meta.json"
        with open(self.meta_file, "w") as f:
            json.dump({"duration_seconds": 30.0}, f)

        # Mock persistent hook pill
        pill = self.project_dir / "persistent_white_pill_overlay.png"
        pill.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_bytes")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_detect_cues(self):
        visual_cues, audio_cues = detect_vfx_sfx_cues(
            project_dir=self.project_dir,
            captions_file=self.captions_file,
            meta_file=self.meta_file,
        )

        # Verify persistent watermark on V4
        wm_cues = [c for c in visual_cues if c.track == "V4" and c.overlay_type == "watermark"]
        self.assertEqual(len(wm_cues), 1)
        self.assertEqual(wm_cues[0].start_seconds, 0.0)
        self.assertEqual(wm_cues[0].duration_seconds, 30.0)

        # Verify title hook on V3
        hook_cues = [c for c in visual_cues if c.track == "V3" and c.overlay_type == "title_hook"]
        self.assertEqual(len(hook_cues), 1)

        # Verify color stabs on V3
        stab_cues = [c for c in visual_cues if c.track == "V3" and c.overlay_type == "color_stab"]
        self.assertGreaterEqual(len(stab_cues), 2)  # Crimson Shock and Neon Flex

        # Verify audio cues on A3
        self.assertGreaterEqual(len(audio_cues), 3)  # Opening whoosh, sub boom, flex whoosh


class TestRemotionAndHyperFramesInjection(unittest.TestCase):
    """Tests HyperFrames HTML/CSS/GSAP synthesis and non-destructive insertion into .remotion.json track structure."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)
        self.remotion_file = self.project_dir / "test.remotion.json"

        # Minimal .remotion.json structure
        initial_proj = {
            "format": "remotion.project",
            "schema_version": 2,
            "project": {
                "name": "test",
                "next_id": 100,
                "root": {"id": 1, "children": []},
                "items": {
                    "10": {
                        "id": 10,
                        "kind": {
                            "Sequence": {
                                "video_tracks": [
                                    {"id": 1, "name": "Blurred Background", "items": []},
                                    {"id": 2, "name": "Speaker Foreground", "items": []},
                                    {"id": 3, "name": "HUD & Overlays", "items": []},
                                    {"id": 4, "name": "Watermark", "items": []},
                                ],
                                "audio_tracks": [
                                    {"id": 5, "name": "Dialogue", "items": []},
                                    {"id": 6, "name": "Background Music", "items": []},
                                    {"id": 7, "name": "SFX", "items": []},
                                ],
                            }
                        },
                    }
                },
            },
        }
        with open(self.remotion_file, "w") as f:
            json.dump(initial_proj, f)

        # Create dummy assets
        self.dummy_png = self.project_dir / "dummy.png"
        self.dummy_png.write_bytes(b"\x89PNG\r\ndummy")
        self.dummy_wav = self.project_dir / "dummy.wav"
        synthesize_whoosh_wav(self.dummy_wav, duration=0.2)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_hyperframes_hook_html_synthesis(self):
        out_html = self.project_dir / "hook_0_3s.hyperframes.html"
        res = synthesize_hyperframes_hook_html(out_html, hook_text="WHAT JUST HAPPENED?!", duration_sec=3.0)
        self.assertTrue(res.is_file())
        html_content = res.read_text(encoding="utf-8")
        # Official HyperFrames 12-point deterministic render contract checks
        self.assertIn('data-composition-id="hook-title-0-3s"', html_content)
        self.assertIn('data-start="0"', html_content)
        self.assertIn('data-duration="3.0"', html_content)
        self.assertIn('class="clip hook-clip"', html_content)
        self.assertIn("gsap.timeline({ paused: true })", html_content)
        self.assertIn('window.__timelines["hook-title-0-3s"] = tl;', html_content)
        self.assertIn("tl.fromTo(", html_content)
        self.assertIn("cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js", html_content)
        self.assertNotIn("transform: translateX(-50%)", html_content)

    def test_inject_vfx_and_sfx(self):
        v_cues = [
            VisualOverlayCue(
                id="wm",
                track="V4",
                start_seconds=0.0,
                duration_seconds=30.0,
                asset_path=str(self.dummy_png),
                name="Watermark",
                overlay_type="watermark",
                scale_pct=28.0,
                pos_x=540.0,
                pos_y=280.0,
            ),
            VisualOverlayCue(
                id="hook",
                track="V3",
                start_seconds=0.0,
                duration_seconds=30.0,
                asset_path=str(self.dummy_png),
                name="Title Hook",
                overlay_type="title_hook",
                scale_pct=100.0,
            ),
        ]
        a_cues = [
            AudioTransientCue(
                id="whoosh",
                start_seconds=0.0,
                duration_seconds=0.2,
                asset_path=str(self.dummy_wav),
                name="Whoosh",
                sfx_type="whoosh_in",
                volume_db=-4.0,
            )
        ]

        res = inject_vfx_and_sfx_into_remotion(
            project_path=self.remotion_file,
            visual_cues=v_cues,
            audio_cues=a_cues,
            backup=True,
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["v4_clips_count"], 1)
        self.assertEqual(res["v3_clips_count"], 1)
        self.assertEqual(res["a3_clips_count"], 1)

        # Verify persisted JSON
        with open(self.remotion_file, "r") as f:
            updated = json.load(f)

        seq = updated["project"]["items"]["10"]["kind"]["Sequence"]
        v4 = [t for t in seq["video_tracks"] if t["id"] == 4][0]
        self.assertEqual(len(v4["items"]), 1)
        self.assertEqual(v4["items"][0]["duration"], seconds_to_ticks(30.0))

        a3 = [t for t in seq["audio_tracks"] if t["id"] == 7][0]
        self.assertEqual(len(a3["items"]), 1)
        self.assertEqual(a3["items"][0]["effects"][0]["params"]["level"]["value"]["Float"], -4.0)


if __name__ == "__main__":
    unittest.main()
