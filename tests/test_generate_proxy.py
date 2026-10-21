#!/usr/bin/env python3
"""
tests/test_generate_proxy.py - Test suite for hardware-optimized proxy generation.
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

from generate_proxy import (
    HardwareEncoderInfo,
    build_ffmpeg_proxy_command,
    calculate_proxy_dimensions,
    generate_proxy,
    probe_hardware_acceleration,
    resolve_default_proxy_path,
    update_pipeline_state_proxy,
)


class TestGenerateProxy(unittest.TestCase):
    """Unit and integration tests for proxy generation engine."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.tmpdir.name)
        self.raw_dir = self.project_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_calculate_proxy_dimensions_1080p(self):
        """1080p (1920x1080) at half-scale with max 540 height -> 960x540."""
        w, h = calculate_proxy_dimensions(1920, 1080, scale=0.5, max_height=540)
        self.assertEqual(w, 960)
        self.assertEqual(h, 540)
        self.assertEqual(w % 2, 0)
        self.assertEqual(h % 2, 0)

    def test_calculate_proxy_dimensions_4k(self):
        """4K (3840x2160) clamped to max 540 height -> 960x540."""
        w, h = calculate_proxy_dimensions(3840, 2160, scale=0.5, max_height=540)
        self.assertEqual(w, 960)
        self.assertEqual(h, 540)

    def test_calculate_proxy_dimensions_odd_numbers(self):
        """Odd dimensions are safely clamped to even integers."""
        w, h = calculate_proxy_dimensions(1921, 1079, scale=0.5, max_height=540)
        self.assertEqual(w % 2, 0)
        self.assertEqual(h % 2, 0)

    def test_calculate_proxy_dimensions_vertical(self):
        """Vertical 1080x1920 video at 0.5 scale with no max height."""
        w, h = calculate_proxy_dimensions(1080, 1920, scale=0.5, max_height=None)
        self.assertEqual(w, 540)
        self.assertEqual(h, 960)

    def test_resolve_default_proxy_path(self):
        """Resolves to raw/Proxies/<stem>_Proxy.mp4."""
        media = self.raw_dir / "episode1.mp4"
        expected = self.raw_dir / "Proxies" / "episode1_Proxy.mp4"
        self.assertEqual(resolve_default_proxy_path(media), expected)

    def test_probe_cpu_fallback(self):
        """Forcing cpu returns libx264 configuration."""
        hw = probe_hardware_acceleration(preferred="cpu")
        self.assertEqual(hw.name, "cpu")
        self.assertEqual(hw.codec, "libx264")
        self.assertFalse(hw.is_hardware)
        self.assertIn("-tune", hw.extra_encode_args)
        self.assertIn("fastdecode", hw.extra_encode_args)

    def test_probe_hardware_auto(self):
        """Auto probe returns a valid HardwareEncoderInfo object."""
        hw = probe_hardware_acceleration(preferred="auto")
        self.assertIsInstance(hw, HardwareEncoderInfo)
        self.assertIn(hw.codec, ["h264_vaapi", "h264_nvenc", "h264_videotoolbox", "h264_qsv", "libx264"])

    def test_build_ffmpeg_proxy_command_cpu(self):
        """Builds valid CPU ffmpeg command."""
        cpu_hw = HardwareEncoderInfo(
            name="cpu",
            codec="libx264",
            filter_type="scale",
            extra_encode_args=["-preset", "veryfast", "-crf", "23", "-bf", "0"],
            is_hardware=False,
        )
        input_file = self.raw_dir / "source.mp4"
        output_file = self.raw_dir / "Proxies" / "source_Proxy.mp4"
        cmd = build_ffmpeg_proxy_command(input_file, output_file, cpu_hw, 960, 540, fps=24.0)

        cmd_str = " ".join(cmd)
        self.assertIn("ffmpeg -y -hide_banner", cmd_str)
        self.assertIn("-vf scale=960:540", cmd_str)
        self.assertIn("-c:v libx264", cmd_str)
        self.assertIn("-g 24", cmd_str)
        self.assertIn("-bf 0", cmd_str)
        self.assertIn("-movflags +faststart", cmd_str)
        self.assertIn("-c:a aac -b:a 128k -ar 48000", cmd_str)

    def test_build_ffmpeg_proxy_command_vaapi(self):
        """Builds valid VAAPI ffmpeg command."""
        vaapi_hw = HardwareEncoderInfo(
            name="vaapi",
            codec="h264_vaapi",
            device="/dev/dri/renderD128",
            init_args=["-init_hw_device", "vaapi=va:/dev/dri/renderD128", "-filter_hw_device", "va"],
            filter_type="vaapi",
            extra_encode_args=["-bf", "0"],
            is_hardware=True,
        )
        input_file = self.raw_dir / "source.mp4"
        output_file = self.raw_dir / "Proxies" / "source_Proxy.mp4"
        cmd = build_ffmpeg_proxy_command(input_file, output_file, vaapi_hw, 960, 540, fps=30.0)

        cmd_str = " ".join(cmd)
        self.assertIn("-init_hw_device vaapi=va:/dev/dri/renderD128", cmd_str)
        self.assertIn("-vf format=nv12,hwupload,scale_vaapi=w=960:h=540", cmd_str)
        self.assertIn("-c:v h264_vaapi", cmd_str)
        self.assertIn("-g 30", cmd_str)

    def test_update_pipeline_state_proxy(self):
        """Updates .clipping_state.json with media_proxy_path and step parameter slices."""
        state = {
            "version": "1.0.0",
            "current_step": "clipping-guidelines",
            "steps": {
                "clipping-transcription": {"params": {}},
                "clipping-assembly": {"params": {}},
            },
        }
        state_file = self.project_dir / ".clipping_state.json"
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)

        proxy_file = self.raw_dir / "Proxies" / "source_Proxy.mp4"
        raw_file = self.raw_dir / "source.mp4"

        ok = update_pipeline_state_proxy(self.project_dir, proxy_file, raw_file)
        self.assertTrue(ok)

        with open(state_file, "r", encoding="utf-8") as f:
            updated = json.load(f)

        self.assertEqual(updated["media_proxy_path"], "raw/Proxies/source_Proxy.mp4")
        self.assertEqual(updated["raw_video_path"], "raw/source.mp4")
        self.assertEqual(
            updated["steps"]["clipping-transcription"]["params"]["media_proxy_path"],
            "raw/Proxies/source_Proxy.mp4",
        )
        self.assertEqual(
            updated["steps"]["clipping-assembly"]["params"]["proxy_path"],
            "raw/Proxies/source_Proxy.mp4",
        )

    def test_generate_proxy_dry_run(self):
        """Dry-run returns command and metadata without executing ffmpeg."""
        dummy_input = self.raw_dir / "input.mp4"
        res = generate_proxy(
            input_path=dummy_input,
            project_dir=self.project_dir,
            dry_run=True,
            preferred_hw="cpu",
        )
        self.assertEqual(res["status"], "dry_run")
        self.assertEqual(res["hw_info"]["codec"], "libx264")
        self.assertIn("ffmpeg", " ".join(res["command"]))

    def test_generate_proxy_synthetic_file(self):
        """Generates real proxy using ffmpeg test video."""
        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg not available")

        # Create a small 1-second synthetic video
        test_source = self.raw_dir / "synthetic_test.mp4"
        make_cmd = [
            "ffmpeg", "-y", "-hide_banner",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=640x360:rate=25",
            "-f", "lavfi", "-i", "sine=duration=1:frequency=440",
            "-c:v", "libx264", "-c:a", "aac",
            str(test_source),
        ]
        res = subprocess.run(make_cmd, capture_output=True)
        if res.returncode != 0:
            self.skipTest("Failed to create synthetic test file")

        # Generate proxy with CPU to guarantee cross-environment success
        proxy_res = generate_proxy(
            input_path=test_source,
            project_dir=self.project_dir,
            preferred_hw="cpu",
            scale=0.5,
            max_height=540,
        )
        self.assertEqual(proxy_res["status"], "success")
        self.assertEqual(proxy_res["target_dimensions"], [320, 180])

        out_proxy = Path(proxy_res["output_path"])
        self.assertTrue(out_proxy.exists())
        self.assertGreater(out_proxy.stat().st_size, 0)

        # Test reuse without force
        reuse_res = generate_proxy(
            input_path=test_source,
            project_dir=self.project_dir,
            force=False,
        )
        self.assertEqual(reuse_res["status"], "exists")
        self.assertTrue(reuse_res["reused"])


if __name__ == "__main__":
    unittest.main()
