#!/usr/bin/env python3
"""
tests/test_download_source.py - Test suite for source video downloader & proxy pipeline bridge.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from download_source import (
    download_and_generate_proxy,
    download_video,
    resolve_source_url_from_project,
    sanitize_filename_slug,
)


class TestDownloadSource(unittest.TestCase):
    """Unit tests for download_source.py."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.tmpdir.name)
        self.raw_dir = self.project_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_sanitize_filename_slug(self):
        """Sanitizes names with punctuation and spaces."""
        self.assertEqual(sanitize_filename_slug("N3on & MPJ: Episode #1"), "n3on-mpj-episode-1")
        self.assertEqual(sanitize_filename_slug("Curious Mike Episode 24"), "curious-mike-episode-24")

    def test_resolve_source_url_from_brief(self):
        """Resolves URL and slug from campaign_brief.json."""
        brief_data = {
            "version": "1.0.0",
            "campaign": {
                "title": "N3on x MPJ",
                "project": "n3on-x-mpj",
                "source_video": {
                    "url": "https://www.youtube.com/watch?v=GfVYVEPSLIM",
                    "channel": "@mpj",
                },
            },
        }
        brief_file = self.project_dir / "campaign_brief.json"
        with open(brief_file, "w", encoding="utf-8") as f:
            json.dump(brief_data, f)

        url, slug = resolve_source_url_from_project(self.project_dir)
        self.assertEqual(url, "https://www.youtube.com/watch?v=GfVYVEPSLIM")
        self.assertEqual(slug, "n3on-x-mpj")

    def test_resolve_source_url_from_state(self):
        """Resolves URL and slug from .clipping_state.json when brief is absent."""
        state_data = {
            "version": "1.0.0",
            "project": "n3on-x-mpj",
            "source_url": "https://www.youtube.com/watch?v=GfVYVEPSLIM",
        }
        state_file = self.project_dir / ".clipping_state.json"
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f)

        url, slug = resolve_source_url_from_project(self.project_dir)
        self.assertEqual(url, "https://www.youtube.com/watch?v=GfVYVEPSLIM")
        self.assertEqual(slug, "n3on-x-mpj")

    def test_download_video_dry_run(self):
        """Dry-run returns output path without executing yt-dlp."""
        target_path = self.raw_dir / "test_download.mp4"
        res = download_video(
            url="https://www.youtube.com/watch?v=GfVYVEPSLIM",
            output_path=target_path,
            dry_run=True,
        )
        self.assertEqual(res, target_path.resolve())

    @patch("subprocess.run")
    def test_download_video_mocked(self, mock_run):
        """Executes yt-dlp with appropriate arguments."""
        mock_run.return_value = MagicMock(returncode=0)
        target_path = self.raw_dir / "video.mp4"
        # Create file so exists check succeeds
        target_path.touch()

        download_video(
            url="https://www.youtube.com/watch?v=12345",
            output_path=target_path,
            dry_run=False,
        )
        self.assertTrue(mock_run.called)
        cmd_args = mock_run.call_args[0][0]
        self.assertEqual(cmd_args[0], "yt-dlp")
        self.assertIn("https://www.youtube.com/watch?v=12345", cmd_args)
        self.assertIn("--merge-output-format", cmd_args)

    def test_download_and_generate_proxy_dry_run(self):
        """End-to-end dry-run pipeline test."""
        brief_data = {
            "version": "1.0.0",
            "campaign": {
                "title": "N3on x MPJ",
                "project": "n3on-x-mpj",
                "source_video": {
                    "url": "https://www.youtube.com/watch?v=GfVYVEPSLIM",
                },
            },
        }
        with open(self.project_dir / "campaign_brief.json", "w", encoding="utf-8") as f:
            json.dump(brief_data, f)

        res = download_and_generate_proxy(
            project_dir=self.project_dir,
            dry_run=True,
            hw_backend="cpu",
        )
        self.assertEqual(res["status"], "success")
        self.assertIn("n3on-x-mpj.mp4", res["raw_video_path"])
        self.assertIn("n3on-x-mpj_Proxy.mp4", res["proxy_path"])

    def test_download_and_generate_proxy_proxy_only_mode(self):
        """--proxy-only skips download and generates proxy for existing raw video."""
        # Create synthetic raw video
        test_source = self.raw_dir / "existing_show.mp4"
        make_cmd = [
            "ffmpeg", "-y", "-hide_banner",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=640x360:rate=25",
            "-f", "lavfi", "-i", "sine=duration=1:frequency=440",
            "-c:v", "libx264", "-c:a", "aac",
            str(test_source),
        ]
        res = subprocess.run(make_cmd, capture_output=True)
        if res.returncode != 0:
            self.skipTest("ffmpeg failed to create synthetic source")

        state = {
            "version": "1.0.0",
            "steps": {"clipping-assembly": {"params": {}}},
        }
        with open(self.project_dir / ".clipping_state.json", "w", encoding="utf-8") as f:
            json.dump(state, f)

        res = download_and_generate_proxy(
            project_dir=self.project_dir,
            proxy_only=True,
            hw_backend="cpu",
        )
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["proxy_generated"])

        expected_proxy = self.raw_dir / "Proxies" / "existing_show_Proxy.mp4"
        self.assertTrue(expected_proxy.exists())


if __name__ == "__main__":
    unittest.main()
