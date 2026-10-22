#!/usr/bin/env python3
"""
Unit tests for clipping_transcription.py (Step 2 engine).
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.clipping_transcription import (
    apply_phonetic_fixes,
    extract_audio,
    get_video_duration,
    parse_yt_json3_transcript,
    execute_transcription_step,
)


class TestClippingTranscription(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_apply_phonetic_fixes(self):
        replacements = {
            "your age": "YourRAGE",
            "mat crackz": "MatCrackz",
            "hard scope": "HardScope"
        }
        text = "Welcome your age to hard scope with mat crackz!"
        fixed = apply_phonetic_fixes(text, replacements)
        self.assertEqual(fixed, "Welcome YourRAGE to HardScope with MatCrackz!")

    def test_apply_phonetic_fixes_empty(self):
        self.assertEqual(apply_phonetic_fixes("Hello world", None), "Hello world")
        self.assertEqual(apply_phonetic_fixes("", {"a": "b"}), "")

    def test_parse_yt_json3_transcript(self):
        mock_json3 = {
            "events": [
                {
                    "tStartMs": 0,
                    "dDurationMs": 2000,
                    "segs": [
                        {"utf8": "Bro,"},
                        {"utf8": " that's", "tOffsetMs": 300},
                        {"utf8": " hard.", "tOffsetMs": 600}
                    ]
                },
                {
                    "tStartMs": 2500,
                    "dDurationMs": 2000,
                    "segs": [
                        {"utf8": ">> I'm", "isSpeakerChange": 1},
                        {"utf8": " scared.", "tOffsetMs": 200}
                    ]
                }
            ]
        }
        json3_file = self.test_dir / "mock_captions.json3"
        with open(json3_file, "w", encoding="utf-8") as f:
            json.dump(mock_json3, f)

        res = parse_yt_json3_transcript(
            json3_path=json3_file,
            source_media="raw/test.mp4",
            audio_path="raw/test_audio.wav",
            duration=5.0,
            host_name="MatCrackz",
            guest_name="YourRAGE",
            phonetic_dict={"hard": "HARD"}
        )

        self.assertEqual(res["word_count"], 5)
        self.assertEqual(len(res["segments"]), 2)
        self.assertEqual(res["segments"][0]["speaker"], "MatCrackz")
        self.assertEqual(res["segments"][1]["speaker"], "YourRAGE")
        self.assertEqual(res["segments"][0]["words"][2]["word"], "HARD.")
        self.assertAlmostEqual(res["segments"][0]["words"][1]["start"], 0.3)

    @patch("scripts.clipping_transcription.subprocess.run")
    def test_extract_audio_ffmpeg_call(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        in_video = self.test_dir / "input.mp4"
        in_video.touch()
        out_wav = self.test_dir / "audio.wav"

        res = extract_audio(in_video, out_wav, sample_rate=48000)
        self.assertEqual(res, out_wav)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("48000", cmd)
        self.assertIn("pcm_s16le", cmd)


if __name__ == "__main__":
    unittest.main()
