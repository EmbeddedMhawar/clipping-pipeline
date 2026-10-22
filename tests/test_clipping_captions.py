#!/usr/bin/env python3
"""
tests/test_clipping_captions.py

Test suite for Step 5: Kinetic Subtitle & Caption Styling Engine (clipping-captions).
Tests emotion annotation, dual-line formatting, safe-zone margin, ASS/SRT generation,
Remotion (@remotion/captions) integration, and pipeline checkpoint gate staging.
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

from scripts.clipping_captions import (
    CaptionCue,
    EmotionVisualAnnotator,
    apply_phonetic_dictionary,
    build_ass_content,
    build_srt_content,
    censor_expletives,
    execute_captions_step,
    format_ass_time,
    format_srt_time,
    segment_words_into_cues,
)


class TestPhoneticsAndCensorship(unittest.TestCase):
    """Tests phonetic correction and profanity masking."""

    def test_domain_replacements(self):
        text = "YOUR AGE AND MAT CRACKZ ON HARDSCOPE UN PACKED"
        cleaned = apply_phonetic_dictionary(text)
        self.assertIn("YOURRAGE", cleaned)
        self.assertIn("MATCRACKZ", cleaned)
        self.assertIn("HARDSCOPE", cleaned)
        self.assertIn("UNPACKED", cleaned)

    def test_expletive_censorship(self):
        text = "WHAT THE FUCK THIS SHIT IS CRAZY [ __ ] BUST"
        censored = censor_expletives(text)
        self.assertIn("F*CK", censored)
        self.assertIn("SH*T", censored)
        self.assertNotIn("FUCK", censored)
        self.assertNotIn("SHIT", censored)


class TestTimeFormatting(unittest.TestCase):
    """Tests ASS and SRT timestamp formatting."""

    def test_format_ass_time(self):
        self.assertEqual(format_ass_time(0.0), "0:00:00.00")
        self.assertEqual(format_ass_time(15.25), "0:00:15.25")
        self.assertEqual(format_ass_time(3665.4), "1:01:05.40")

    def test_format_srt_time(self):
        self.assertEqual(format_srt_time(0.0), "00:00:00,000")
        self.assertEqual(format_srt_time(15.25), "00:00:15,250")
        self.assertEqual(format_srt_time(75.08), "00:01:15,080")


class TestEmotionVisualAnnotator(unittest.TestCase):
    """Tests derivation of *emotion or visual context comment*."""

    def setUp(self):
        cuts = [
            {"start": 0.0, "end": 2.0, "shot_type": "MatCrackz Close-Up (Host Shock)", "speaker": "host"},
            {"start": 2.0, "end": 5.0, "shot_type": "Tight Close-Up", "speaker": "guest"},
            {"start": 14.5, "end": 17.5, "shot_type": "Wide Reaction Punch-Out", "speaker": "host"},
            {"start": 24.5, "end": 30.9, "shot_type": "Wide Desk Climax Punch-Out ($2,000+ Payoff)", "speaker": "host"},
        ]
        self.annotator = EmotionVisualAnnotator(cuts=cuts)

    def test_annotate_shock_and_disbelief(self):
        em = self.annotator.annotate("OH MY GOD", 0.5, 1.5, self.annotator.get_cut_for_time(1.0))
        self.assertEqual(em, "*PURE SHOCK*")

    def test_annotate_screaming_chaos(self):
        em = self.annotator.annotate("[SCREAMING] WHAT?!", 15.0, 16.0, self.annotator.get_cut_for_time(15.5))
        self.assertEqual(em, "*SCREAMING CHAOS*")

    def test_annotate_hands_shaking(self):
        em = self.annotator.annotate("I'M ACTUALLY SHAKING", 10.0, 11.5, None)
        self.assertEqual(em, "*HANDS SHAKING*")

    def test_annotate_grail_pull_and_odds(self):
        em1 = self.annotator.annotate("YOU PULLED YOUR GRAIL", 28.0, 30.0, self.annotator.get_cut_for_time(29.0))
        self.assertEqual(em1, "*GRAIL PULL*")

        em2 = self.annotator.annotate("THE ODDS ARE 100%", 35.0, 37.0, None)
        self.assertEqual(em2, "*100% DESTINY*")

    def test_annotate_celebration(self):
        em = self.annotator.annotate("LET'S GO BRO!", 38.0, 40.0, None)
        self.assertEqual(em, "*PURE HYPE*")


class TestCueSegmentation(unittest.TestCase):
    """Tests splitting words into discrete kinetic cues."""

    def test_segment_words(self):
        words = [
            {"word": "Oh", "start": 0.0, "end": 0.2},
            {"word": "my", "start": 0.2, "end": 0.4},
            {"word": "god.", "start": 0.4, "end": 1.2},
            {"word": "I'm", "start": 1.5, "end": 1.7},
            {"word": "actually", "start": 1.7, "end": 2.1},
            {"word": "shaking.", "start": 2.1, "end": 2.8},
        ]
        cues = segment_words_into_cues(
            words=words,
            clip_start=0.0,
            clip_end=3.0,
            words_per_line=2,
            include_emotions=True,
        )
        self.assertGreaterEqual(len(cues), 2)
        # All cues must have an emotion comment
        for c in cues:
            self.assertTrue(c.emotion.startswith("*") and c.emotion.endswith("*"))
            self.assertGreater(c.end, c.start)

    def test_keyword_highlight_assignment(self):
        words = [
            {"word": "You", "start": 0.0, "end": 0.3},
            {"word": "pulled", "start": 0.3, "end": 0.7},
            {"word": "your", "start": 0.7, "end": 0.9},
            {"word": "grail.", "start": 0.9, "end": 1.5},
        ]
        cues = segment_words_into_cues(
            words=words,
            clip_start=0.0,
            clip_end=2.0,
            words_per_line=2,
            trigger_keywords=["GRAIL"],
        )
        grail_cue = [c for c in cues if "GRAIL" in c.text][0]
        self.assertEqual(grail_cue.highlight_color, "neon_lime")
        self.assertEqual(grail_cue.style, "ZylokLime")


class TestSubtitleWriters(unittest.TestCase):
    """Tests ASS and SRT generation."""

    def test_build_ass_and_srt(self):
        cues = [
            CaptionCue(
                index=1,
                start=0.5,
                end=2.0,
                text="OH MY GOD",
                emotion="*PURE SHOCK*",
                style="ZylokWhite",
            ),
            CaptionCue(
                index=2,
                start=2.2,
                end=4.0,
                text="PULLED YOUR GRAIL",
                emotion="*GRAIL PULL*",
                highlight_color="neon_lime",
                style="ZylokLime",
            ),
        ]
        ass_str = build_ass_content(cues, margin_v=420)
        self.assertIn("PlayResX: 1080", ass_str)
        self.assertIn("PlayResY: 1920", ass_str)
        self.assertIn("MarginV, Encoding", ass_str)
        self.assertIn("420", ass_str)
        self.assertIn("*PURE SHOCK*", ass_str)
        self.assertIn("*GRAIL PULL*", ass_str)
        self.assertIn("PULLED YOUR GRAIL", ass_str)

        srt_str = build_srt_content(cues)
        self.assertIn("00:00:00,500 --> 00:00:02,000", srt_str)
        self.assertIn("*PURE SHOCK*", srt_str)
        self.assertIn("OH MY GOD", srt_str)
        self.assertIn("00:00:02,200 --> 00:00:04,000", srt_str)
        self.assertIn("*GRAIL PULL*", srt_str)


class TestCaptionsPipelineIntegration(unittest.TestCase):
    """Integration test running execute_captions_step and verifying checkpoint staging."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)

        # Create dummy transcript
        transcript = {
            "segments": [
                {
                    "words": [
                        {"word": "Oh", "start": 10.0, "end": 10.2},
                        {"word": "my", "start": 10.2, "end": 10.4},
                        {"word": "god.", "start": 10.4, "end": 11.0},
                        {"word": "You", "start": 11.2, "end": 11.4},
                        {"word": "pulled", "start": 11.4, "end": 11.7},
                        {"word": "your", "start": 11.7, "end": 11.9},
                        {"word": "grail.", "start": 11.9, "end": 12.5},
                    ]
                }
            ]
        }
        (self.project_dir / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")

        # Create dummy cuts
        cuts_data = {
            "start": 10.0,
            "end": 13.0,
            "cuts": [
                {
                    "start": 10.0,
                    "end": 11.1,
                    "speaker": "host",
                    "speaker_name": "MatCrackz",
                    "shot_type": "Host Shock Close-Up",
                    "text": "Oh my god.",
                },
                {
                    "start": 11.1,
                    "end": 13.0,
                    "speaker": "host",
                    "speaker_name": "MatCrackz",
                    "shot_type": "Wide Desk Grail Payoff",
                    "text": "You pulled your grail.",
                },
            ],
        }
        (self.project_dir / "cuts.json").write_text(json.dumps(cuts_data), encoding="utf-8")

        # Initialize state with completed assembly step
        state = {
            "version": "1.0.0",
            "current_step": "clipping-captions",
            "guidelines_approved": True,
            "campaign": {"title": "Test Campaign", "project": "test-project"},
            "steps": {
                "clipping-guidelines": {"status": "completed", "approved": True},
                "clipping-transcription": {"status": "completed", "approved": True},
                "clipping-hook-hunter": {"status": "completed", "approved": True},
                "clipping-assembly": {"status": "completed", "approved": True},
                "clipping-captions": {
                    "status": "pending",
                    "approved": False,
                    "params": {
                        "words_per_line_range": [1, 2],
                        "margin_v": 420,
                        "highlight_colors": {"neon_lime": "#CCFF00"},
                    },
                },
                "clipping-vfx-sfx": {"status": "pending", "approved": False},
                "clipping-qc-packager": {"status": "pending", "approved": False},
                "clipping-publisher": {"status": "pending", "approved": False},
            },
        }
        (self.project_dir / ".clipping_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_execute_captions_generates_files_and_stages_checkpoint(self):
        res = execute_captions_step(
            project_dir=self.project_dir,
            words_per_line=2,
            margin_v=420,
            include_emotions=True,
            trigger_checkpoint=True,
            auto_approve=False,
        )
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["cues_count"], 0)

        # Verify output files exist
        ass_file = Path(res["output_ass"])
        srt_file = Path(res["output_srt"])
        json_file = Path(res["output_json"])

        self.assertTrue(ass_file.is_file(), f"Expected ASS at {ass_file}")
        self.assertTrue(srt_file.is_file(), f"Expected SRT at {srt_file}")
        self.assertTrue(json_file.is_file(), f"Expected JSON at {json_file}")

        # Verify emotion comments in files
        ass_text = ass_file.read_text(encoding="utf-8")
        self.assertIn("*PURE SHOCK*", ass_text)
        self.assertIn("*GRAIL PULL*", ass_text)

        srt_text = srt_file.read_text(encoding="utf-8")
        self.assertIn("*PURE SHOCK*", srt_text)
        self.assertIn("*GRAIL PULL*", srt_text)

        # Verify checkpoint artifact generated
        checkpoint_md = self.project_dir / "checkpoint_clipping-captions.md"
        self.assertTrue(checkpoint_md.is_file(), f"Expected checkpoint artifact at {checkpoint_md}")
        cp_text = checkpoint_md.read_text(encoding="utf-8")
        self.assertIn("RequestFeedback: true", cp_text)
        self.assertIn("clipping-captions", cp_text)

        # Verify state file staged
        state = json.loads((self.project_dir / ".clipping_state.json").read_text(encoding="utf-8"))
        step_caps = state["steps"]["clipping-captions"]
        self.assertIn(step_caps["status"], ("staged", "awaiting_checkpoint", "checkpoint_reviewed"))
        self.assertTrue(step_caps.get("checkpoint", {}).get("staged") or step_caps.get("staged"))
        self.assertIn("cues_count", step_caps["params"])

        # Verify @remotion/captions Caption schema compliance (timestampMs, confidence, leading space)
        captions_manifest = json.loads(json_file.read_text(encoding="utf-8"))
        self.assertIn("remotion_captions", captions_manifest)
        rem_caps = captions_manifest["remotion_captions"]
        self.assertGreater(len(rem_caps), 0)
        for idx, cap in enumerate(rem_caps):
            self.assertIn("text", cap)
            self.assertIn("startMs", cap)
            self.assertIn("endMs", cap)
            self.assertIn("timestampMs", cap)
            self.assertIn("confidence", cap)
            if idx > 0:
                self.assertTrue(cap["text"].startswith(" "), "Tokens after index 0 must preserve leading space per @remotion/captions")


if __name__ == "__main__":
    unittest.main()
