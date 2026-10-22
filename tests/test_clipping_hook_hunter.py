#!/usr/bin/env python3
"""
Unit tests for clipping_hook_hunter.py (Step 3 engine).
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.clipping_hook_hunter import (
    build_candidate_sub_cuts,
    calculate_speech_density,
    correlate_contact_sheet,
    detect_inaudible_gags,
    evaluate_candidate_clip,
    execute_hook_hunter_step,
    format_tc,
    hunt_viral_candidates,
    score_loop_viability,
    score_opening_hook,
)


class TestClippingHookHunter(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_format_tc(self):
        self.assertEqual(format_tc(0.0), "00:00")
        self.assertEqual(format_tc(65.0), "01:05")
        self.assertEqual(format_tc(3665.0), "01:01:05")

    def test_score_opening_hook_question(self):
        score, tags = score_opening_hook("Why would anyone pay that?")
        self.assertIn("question_hook", tags)
        self.assertGreater(score, 6.0)

    def test_score_opening_hook_disbelief(self):
        score, tags = score_opening_hook("No way! I'm actually shaking, you can't script this!")
        self.assertIn("disbelief_or_shock", tags)
        self.assertGreaterEqual(score, 7.0)

    def test_score_opening_hook_money(self):
        score, tags = score_opening_hook("We have a box for $5,000 right here.")
        self.assertIn("money_or_value_flex", tags)
        self.assertGreater(score, 6.5)

    def test_score_opening_hook_empty(self):
        score, tags = score_opening_hook("")
        self.assertIn("empty_hook", tags)
        self.assertEqual(score, 2.0)

    def test_calculate_speech_density(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Hello world this is a test", "words": [{"word": "w"} for _ in range(7)]},
            {"start": 2.0, "end": 4.0, "text": "Rapid speech test segment", "words": [{"word": "w"} for _ in range(4)]},
        ]
        wps, silence = calculate_speech_density(segments, 4.0)
        self.assertEqual(wps, 2.75)  # 11 words / 4.0s = 2.75 wps
        self.assertEqual(silence, 0.0)

    def test_score_loop_viability(self):
        is_loop, score = score_loop_viability(
            first_text="Only thing that could be worse is pulling Tyler Herro.",
            last_text="Tyler Herro, this is what you do to us Heat fans, bro!",
        )
        self.assertTrue(is_loop)
        self.assertGreater(score, 5.0)

    def test_detect_inaudible_gags(self):
        segments = [
            {"text": "Normal words here", "words": [{"word": "Normal", "probability": 0.99}]},
            {"text": "Wait *inaudible* what?", "words": [{"word": "*inaudible*", "probability": 0.20}]},
        ]
        count = detect_inaudible_gags(segments)
        self.assertGreaterEqual(count, 1)

    def test_correlate_contact_sheet(self):
        manifest = {
            "sheets": [
                {"filename": "sheet_0001.jpg", "start_time": 0.0, "end_time": 120.0},
                {"filename": "sheet_0002.jpg", "start_time": 120.0, "end_time": 240.0},
            ]
        }
        sheet_ref, tc_window = correlate_contact_sheet(60.0, 90.0, manifest)
        self.assertEqual(sheet_ref, "sheet_0001.jpg")
        self.assertEqual(tc_window, "01:00 - 01:30")

    def test_build_candidate_sub_cuts(self):
        segments = [
            {"start": 10.0, "end": 12.0, "speaker": "MatCrackz", "text": "Host speaks here"},
            {"start": 12.0, "end": 14.5, "speaker": "YourRAGE", "text": "Guest responds excitedly!"},
        ]
        cuts = build_candidate_sub_cuts(segments, 10.0, 14.5, "MatCrackz", "YourRAGE")
        self.assertEqual(len(cuts), 2)
        self.assertEqual(cuts[0]["speaker"], "host")
        self.assertEqual(cuts[0]["x_center"], 0.25)
        self.assertEqual(cuts[1]["speaker"], "guest")
        self.assertEqual(cuts[1]["x_center"], 0.75)
        self.assertEqual(cuts[1]["punch_in"], 1.15)  # due to exclamation

    def test_hunt_viral_candidates(self):
        mock_transcript = {
            "segments": [
                {"id": 0, "speaker": "MatCrackz", "start": 331.0, "end": 334.0, "text": "First thing you collected?"},
                {"id": 1, "speaker": "YourRAGE", "start": 334.0, "end": 340.0, "text": "First thing was rocks."},
                {"id": 2, "speaker": "MatCrackz", "start": 341.0, "end": 346.0, "text": "Those are signs of early autism."},
                {"id": 3, "speaker": "MatCrackz", "start": 1044.0, "end": 1050.0, "text": "Last pack. Only thing worse is pulling Tyler Herro."},
                {"id": 4, "speaker": "YourRAGE", "start": 1059.0, "end": 1075.0, "text": "There's no way! The last card! He's crying!"},
                {"id": 5, "speaker": "MatCrackz", "start": 1134.0, "end": 1145.0, "text": "I'M NOT LOOKING! I'm actually shaking, don't touch it!"},
                {"id": 6, "speaker": "YourRAGE", "start": 1150.0, "end": 1175.0, "text": "You pulled your grail! The odds are 100%! Let's go!"},
            ]
        }
        candidates = hunt_viral_candidates(
            transcript_data=mock_transcript,
            target_duration_range=(25.0, 45.0),
            hard_bounds=(7.0, 60.0),
        )
        self.assertGreaterEqual(len(candidates), 1)
        # Verify sorted by viral_score descending
        scores = [c["viral_score"] for c in candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(candidates[0]["rank"], 1)

    def test_execute_hook_hunter_step_e2e(self):
        # Create minimal project directory
        transcript_path = self.test_dir / "transcript.json"
        state_path = self.test_dir / ".clipping_state.json"

        mock_transcript = {
            "segments": [
                {"id": 0, "speaker": "MatCrackz", "start": 1134.0, "end": 1145.0, "text": "I'M NOT LOOKING! I'm actually shaking!"},
                {"id": 1, "speaker": "YourRAGE", "start": 1150.0, "end": 1175.0, "text": "You pulled your grail! Let's go!"},
            ]
        }
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(mock_transcript, f)

        mock_state = {
            "version": "1.0.0",
            "campaign": {"title": "Test Show", "project": "test-show"},
            "current_step": "clipping-hook-hunter",
            "steps": {
                "clipping-hook-hunter": {
                    "status": "pending",
                    "approved": False,
                    "params": {"target_duration_range": [25.0, 45.0], "hard_bounds": [7.0, 60.0]},
                }
            },
        }
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(mock_state, f)

        manifest = execute_hook_hunter_step(
            project_dir=self.test_dir,
            generate_sheets=False,
            stage_checkpoint=True,
        )

        self.assertIn("candidates", manifest)
        self.assertGreater(manifest["total_candidates"], 0)
        self.assertTrue((self.test_dir / "candidates.json").exists())
        self.assertTrue((self.test_dir / "checkpoint_clipping_hook_hunter.md").exists())

        # Check state update
        with open(state_path, "r", encoding="utf-8") as f:
            updated_state = json.load(f)
        step_entry = updated_state["steps"]["clipping-hook-hunter"]
        self.assertTrue(step_entry["staged"])
        self.assertTrue(step_entry["checkpoint"]["staged"])
        self.assertEqual(step_entry["params"]["candidate_count"], manifest["total_candidates"])


if __name__ == "__main__":
    unittest.main()
