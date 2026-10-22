#!/usr/bin/env python3
"""
tests/test_generate_contact_sheets.py

Unit tests for scripts/generate_contact_sheets.py.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
import sys
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from generate_contact_sheets import (
    format_seconds_to_hms,
    generate_contact_sheets,
    get_video_info,
    parse_timecode_to_seconds,
)


class TestGenerateContactSheets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="cs_test_"))
        cls.test_video = cls.temp_dir / "test_synth.mp4"
        # Generate short 6s synthetic video for rapid test execution
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=duration=6:size=640x360:rate=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(cls.test_video)
        ]
        subprocess.run(cmd, check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_timecode_parsing(self):
        self.assertEqual(parse_timecode_to_seconds(45.5), 45.5)
        self.assertEqual(parse_timecode_to_seconds("01:30"), 90.0)
        self.assertEqual(parse_timecode_to_seconds("01:02:03"), 3723.0)

    def test_timecode_formatting(self):
        self.assertEqual(format_seconds_to_hms(45), "00:45")
        self.assertEqual(format_seconds_to_hms(95), "01:35")
        self.assertEqual(format_seconds_to_hms(3665), "01:01:05")

    def test_video_info(self):
        info = get_video_info(self.test_video)
        self.assertEqual(info["width"], 640)
        self.assertEqual(info["height"], 360)
        self.assertAlmostEqual(info["duration"], 6.0, delta=0.5)
        self.assertEqual(info["aspect_ratio"], "16:9")

    def test_generate_overview_sheet(self):
        out_dir = self.temp_dir / "overview_out"
        manifest = generate_contact_sheets(
            video_path=self.test_video,
            output_dir=out_dir,
            grid="3x3",
            mode="overview",
            tile_width=160,
            use_vaapi=False
        )
        self.assertEqual(manifest["sheets_count"], 1)
        self.assertEqual(manifest["grid"], "3x3")
        self.assertEqual(manifest["total_tiles_per_sheet"], 9)
        self.assertTrue((out_dir / "contact_sheets.json").exists())
        self.assertTrue((out_dir / "sheet_full_overview.jpg").exists())

    def test_generate_batch_sheets(self):
        out_dir = self.temp_dir / "batch_out"
        manifest = generate_contact_sheets(
            video_path=self.test_video,
            output_dir=out_dir,
            grid="2x2",
            mode="batch",
            slice_duration=3.0,
            tile_width=160,
            use_vaapi=False
        )
        self.assertEqual(manifest["sheets_count"], 2)
        self.assertTrue((out_dir / "sheet_0001.jpg").exists())
        self.assertTrue((out_dir / "sheet_0002.jpg").exists())

    def test_generate_candidates_sheets(self):
        out_dir = self.temp_dir / "cands_out"
        candidates = [
            {"id": "cand_a", "title": "Moment A", "start": 0.5, "end": 2.5},
            {"id": "cand_b", "title": "Moment B", "start": 3.0, "end": 5.0}
        ]
        manifest = generate_contact_sheets(
            video_path=self.test_video,
            output_dir=out_dir,
            grid="3x3",
            mode="candidates",
            candidates=candidates,
            tile_width=160,
            use_vaapi=False
        )
        self.assertEqual(manifest["sheets_count"], 2)
        self.assertTrue((out_dir / "sheet_cand_a.jpg").exists())
        self.assertTrue((out_dir / "sheet_cand_b.jpg").exists())


if __name__ == "__main__":
    unittest.main()
