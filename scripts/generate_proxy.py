#!/usr/bin/env python3
"""
scripts/generate_proxy.py - Hardware-Optimized Video Proxy Generator.

Generates lightweight, fast-decoding edit proxies (H.264) from raw high-resolution
footage for Remotion Studio (<OffthreadVideo>) and the Short-Form Clipping Pipeline.
Automatically detects and utilizes host hardware acceleration:
- Linux VAAPI (Intel/AMD via /dev/dri/renderD128)
- NVIDIA NVENC (h264_nvenc)
- Apple Silicon VideoToolbox (h264_videotoolbox)
- Intel QuickSync Video (h264_qsv)
- CPU Fallback (libx264 -preset veryfast)

Proxies default to half-resolution (e.g. 960x540 for 1080p) with a short 1-second GOP
(keyframe interval) and no B-frames for instantaneous, responsive scrubbing in Remotion Studio.
Standard layout: <project_dir>/raw/Proxies/<name>_Proxy.mp4.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class HardwareEncoderInfo:
    """Hardware acceleration encoder capability and configuration."""
    name: str                     # 'vaapi', 'nvenc', 'videotoolbox', 'qsv', 'cpu'
    codec: str                    # 'h264_vaapi', 'h264_nvenc', 'h264_videotoolbox', 'h264_qsv', 'libx264'
    device: Optional[str] = None  # e.g. '/dev/dri/renderD128'
    init_args: List[str] = field(default_factory=list)
    filter_type: str = "scale"    # 'vaapi' or 'scale'
    extra_encode_args: List[str] = field(default_factory=list)
    is_hardware: bool = False
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "codec": self.codec,
            "device": self.device,
            "init_args": self.init_args,
            "filter_type": self.filter_type,
            "extra_encode_args": self.extra_encode_args,
            "is_hardware": self.is_hardware,
            "description": self.description,
        }


def _run_probe(cmd: List[str], timeout_sec: float = 3.0) -> bool:
    """Run a fast non-blocking ffmpeg probe command to verify encoder initialization."""
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec,
        )
        return res.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
        return False


def probe_hardware_acceleration(
    preferred: Optional[str] = None,
    device_path: Optional[str] = None,
) -> HardwareEncoderInfo:
    """
    Detect available hardware-accelerated H.264 encoder on the current host.
    Tests active encoding using a 1-frame null probe.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg binary not found in system PATH.")

    pref = (preferred or "auto").lower().strip()

    # 0. Force CPU if explicitly requested
    if pref in ("cpu", "software", "libx264"):
        return HardwareEncoderInfo(
            name="cpu",
            codec="libx264",
            filter_type="scale",
            extra_encode_args=["-preset", "veryfast", "-crf", "23", "-tune", "fastdecode", "-bf", "0", "-pix_fmt", "yuv420p"],
            is_hardware=False,
            description="CPU libx264 (veryfast preset)",
        )

    # 1. Linux VAAPI (Intel / AMD GPU)
    if pref in ("auto", "vaapi"):
        dev_candidates = []
        if device_path:
            dev_candidates.append(device_path)
        dev_candidates.extend([
            "/dev/dri/renderD128",
            "/dev/dri/renderD129",
            "/dev/dri/card0",
            "/dev/dri/card1",
        ])
        for dev in dev_candidates:
            if os.path.exists(dev):
                probe_cmd = [
                    "ffmpeg", "-hide_banner",
                    "-init_hw_device", f"vaapi=va:{dev}",
                    "-filter_hw_device", "va",
                    "-f", "lavfi", "-i", "testsrc=duration=0.04:size=320x240:rate=25",
                    "-vf", "format=nv12,hwupload",
                    "-c:v", "h264_vaapi",
                    "-f", "null", "-",
                ]
                if _run_probe(probe_cmd):
                    return HardwareEncoderInfo(
                        name="vaapi",
                        codec="h264_vaapi",
                        device=dev,
                        init_args=["-init_hw_device", f"vaapi=va:{dev}", "-filter_hw_device", "va"],
                        filter_type="vaapi",
                        extra_encode_args=["-bf", "0"],
                        is_hardware=True,
                        description=f"Linux VAAPI Hardware Encoder ({dev})",
                    )
        if pref == "vaapi":
            sys.stderr.write("[Warning] Requested VAAPI encoder but active probe failed. Falling back.\n")

    # 2. NVIDIA NVENC
    if pref in ("auto", "nvenc"):
        probe_cmd = [
            "ffmpeg", "-hide_banner",
            "-f", "lavfi", "-i", "testsrc=duration=0.04:size=320x240:rate=25",
            "-c:v", "h264_nvenc",
            "-f", "null", "-",
        ]
        if _run_probe(probe_cmd):
            return HardwareEncoderInfo(
                name="nvenc",
                codec="h264_nvenc",
                filter_type="scale",
                extra_encode_args=["-preset", "p4", "-tune", "fastdecode", "-rc", "vbr", "-cq", "24", "-bf", "0", "-pix_fmt", "yuv420p"],
                is_hardware=True,
                description="NVIDIA NVENC Hardware Encoder",
            )
        if pref == "nvenc":
            sys.stderr.write("[Warning] Requested NVENC encoder but active probe failed. Falling back.\n")

    # 3. Apple VideoToolbox (macOS)
    if pref in ("auto", "videotoolbox"):
        if sys.platform == "darwin" or pref == "videotoolbox":
            probe_cmd = [
                "ffmpeg", "-hide_banner",
                "-f", "lavfi", "-i", "testsrc=duration=0.04:size=320x240:rate=25",
                "-c:v", "h264_videotoolbox",
                "-f", "null", "-",
            ]
            if _run_probe(probe_cmd):
                return HardwareEncoderInfo(
                    name="videotoolbox",
                    codec="h264_videotoolbox",
                    filter_type="scale",
                    extra_encode_args=["-b:v", "2500k", "-bf", "0", "-pix_fmt", "yuv420p"],
                    is_hardware=True,
                    description="Apple VideoToolbox Hardware Encoder",
                )
            if pref == "videotoolbox":
                sys.stderr.write("[Warning] Requested VideoToolbox encoder but active probe failed. Falling back.\n")

    # 4. Intel QuickSync (QSV)
    if pref in ("auto", "qsv"):
        probe_cmd = [
            "ffmpeg", "-hide_banner",
            "-f", "lavfi", "-i", "testsrc=duration=0.04:size=320x240:rate=25",
            "-c:v", "h264_qsv",
            "-f", "null", "-",
        ]
        if _run_probe(probe_cmd):
            return HardwareEncoderInfo(
                name="qsv",
                codec="h264_qsv",
                filter_type="scale",
                extra_encode_args=["-preset", "veryfast", "-bf", "0", "-pix_fmt", "nv12"],
                is_hardware=True,
                description="Intel QuickSync Video (QSV) Hardware Encoder",
            )
        if pref == "qsv":
            sys.stderr.write("[Warning] Requested QSV encoder but active probe failed. Falling back.\n")

    # 5. Default CPU Fallback
    return HardwareEncoderInfo(
        name="cpu",
        codec="libx264",
        filter_type="scale",
        extra_encode_args=["-preset", "veryfast", "-crf", "23", "-tune", "fastdecode", "-bf", "0", "-pix_fmt", "yuv420p"],
        is_hardware=False,
        description="CPU libx264 (veryfast fallback)",
    )


def get_video_info(video_path: Path) -> Dict[str, Any]:
    """Retrieve video metadata (duration, width, height, fps, codec) using ffprobe."""
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe binary not found in system PATH.")

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,r_frame_rate,codec_name:format=duration",
        "-of", "json",
        str(video_path.resolve()),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed to inspect {video_path}: {res.stderr}")

    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise RuntimeError(f"No video streams found in {video_path}")

    v_stream = streams[0]
    fmt = data.get("format", {})

    width = int(v_stream.get("width", 1920))
    height = int(v_stream.get("height", 1080))
    codec = v_stream.get("codec_name", "unknown")

    # Duration parsing
    dur_str = v_stream.get("duration") or fmt.get("duration") or "0.0"
    try:
        duration = float(dur_str)
    except ValueError:
        duration = 0.0

    # Frame rate parsing
    r_fps = v_stream.get("r_frame_rate", "30/1")
    if "/" in r_fps:
        num, den = r_fps.split("/")
        fps = float(num) / max(1.0, float(den))
    else:
        try:
            fps = float(r_fps)
        except ValueError:
            fps = 30.0

    return {
        "width": width,
        "height": height,
        "duration": duration,
        "fps": fps,
        "codec": codec,
    }


def calculate_proxy_dimensions(
    src_w: int,
    src_h: int,
    scale: float = 0.5,
    max_height: Optional[int] = 540,
) -> Tuple[int, int]:
    """
    Calculate target proxy dimensions maintaining aspect ratio.
    Ensures both width and height are even integers.
    """
    target_w = int(round(src_w * scale))
    target_h = int(round(src_h * scale))

    if max_height and target_h > max_height:
        ratio = max_height / float(src_h)
        target_w = int(round(src_w * ratio))
        target_h = max_height

    # Ensure even dimensions (divisible by 2)
    target_w = max(2, (target_w // 2) * 2)
    target_h = max(2, (target_h // 2) * 2)

    return target_w, target_h


def resolve_default_proxy_path(input_path: Path) -> Path:
    """
    Resolve canonical proxy path matching Remotion pipeline standard:
    <parent>/Proxies/<stem>_Proxy.mp4
    """
    input_p = input_path.resolve()
    proxies_dir = input_p.parent / "Proxies"
    return proxies_dir / f"{input_p.stem}_Proxy.mp4"


def build_ffmpeg_proxy_command(
    input_path: Path,
    output_path: Path,
    hw_info: HardwareEncoderInfo,
    target_w: int,
    target_h: int,
    fps: float = 30.0,
) -> List[str]:
    """Construct FFmpeg command line for proxy generation based on hardware configuration."""
    gop = max(1, int(round(fps)))  # 1-second keyframe interval for instant scrub seeking

    cmd: List[str] = ["ffmpeg", "-y", "-hide_banner"]

    # Hardware initialization arguments before -i
    cmd.extend(hw_info.init_args)

    cmd.extend(["-i", str(input_path.resolve())])

    # Video filter chain
    if hw_info.filter_type == "vaapi":
        vf = f"format=nv12,hwupload,scale_vaapi=w={target_w}:h={target_h}"
    else:
        vf = f"scale={target_w}:{target_h}"
    cmd.extend(["-vf", vf])

    # Encoder and rate control
    cmd.extend(["-c:v", hw_info.codec, "-g", str(gop)])
    cmd.extend(hw_info.extra_encode_args)

    # Audio re-encode: 48kHz stereo AAC (fast and highly compatible across all NLEs)
    cmd.extend(["-c:a", "aac", "-b:a", "128k", "-ar", "48000"])

    # Faststart: move moov atom to beginning of MP4 container for instant seeking
    cmd.extend(["-movflags", "+faststart"])

    cmd.append(str(output_path.resolve()))
    return cmd


def update_pipeline_state_proxy(
    project_dir: Path,
    proxy_path: Path,
    raw_video_path: Optional[Path] = None,
) -> bool:
    """Update .clipping_state.json with the generated proxy path if present."""
    state_file = project_dir / ".clipping_state.json"
    if not state_file.exists():
        return False

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        rel_proxy = str(proxy_path.resolve())
        try:
            rel_proxy = str(proxy_path.resolve().relative_to(project_dir.resolve()))
        except ValueError:
            pass

        state["media_proxy_path"] = rel_proxy

        if raw_video_path:
            rel_raw = str(raw_video_path.resolve())
            try:
                rel_raw = str(raw_video_path.resolve().relative_to(project_dir.resolve()))
            except ValueError:
                pass
            state["raw_video_path"] = rel_raw

        # Inject into Step slices
        steps = state.setdefault("steps", {})
        if "clipping-transcription" in steps:
            steps["clipping-transcription"].setdefault("params", {})["media_proxy_path"] = rel_proxy
        if "clipping-assembly" in steps:
            steps["clipping-assembly"].setdefault("params", {})["proxy_path"] = rel_proxy

        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        return True
    except Exception as e:
        sys.stderr.write(f"[Warning] Failed to update .clipping_state.json with proxy: {e}\n")
        return False


def generate_proxy(
    input_path: Path,
    output_path: Optional[Path] = None,
    project_dir: Optional[Path] = None,
    scale: float = 0.5,
    max_height: Optional[int] = 540,
    preferred_hw: Optional[str] = None,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Generate hardware-optimized proxy video for input media file.
    Automatically creates <dir>/raw/Proxies/<name>_Proxy.mp4.
    """
    input_p = Path(input_path).resolve()
    if not input_p.exists() and not dry_run:
        raise FileNotFoundError(f"Source video file not found: {input_p}")

    out_p = Path(output_path).resolve() if output_path else resolve_default_proxy_path(input_p)

    # Check if proxy already exists and force is False
    if out_p.exists() and not force and not dry_run:
        print(f"✓ Proxy video already exists: {out_p} (use --force to regenerate)")
        if project_dir:
            update_pipeline_state_proxy(Path(project_dir), out_p, input_p)
        return {
            "status": "exists",
            "input_path": str(input_p),
            "output_path": str(out_p),
            "reused": True,
            "file_size": out_p.stat().st_size,
        }

    # Inspect source metadata (with fallback for dry_run if file does not exist yet)
    if input_p.exists():
        info = get_video_info(input_p)
    else:
        info = {
            "width": 1920,
            "height": 1080,
            "duration": 0.0,
            "fps": 30.0,
            "codec": "mock_h264",
        }
    target_w, target_h = calculate_proxy_dimensions(
        info["width"], info["height"], scale=scale, max_height=max_height
    )

    # Detect hardware encoder
    hw_info = probe_hardware_acceleration(preferred=preferred_hw)
    cmd = build_ffmpeg_proxy_command(
        input_p, out_p, hw_info, target_w, target_h, fps=info["fps"]
    )

    if dry_run:
        print(f"[dry-run] Hardware backend: {hw_info.description}")
        print(f"[dry-run] Target dimensions: {target_w}x{target_h}")
        print(f"[dry-run] Command: {' '.join(cmd)}")
        return {
            "status": "dry_run",
            "input_path": str(input_p),
            "output_path": str(out_p),
            "hw_info": hw_info.to_dict(),
            "target_dimensions": [target_w, target_h],
            "command": cmd,
        }

    # Ensure destination directory exists
    out_p.parent.mkdir(parents=True, exist_ok=True)

    print(f"Generating proxy: {input_p.name} -> {out_p.name}")
    print(f"  Encoder backend : {hw_info.description}")
    print(f"  Resolution      : {info['width']}x{info['height']} -> {target_w}x{target_h} (half-res)")
    print(f"  GOP interval    : {max(1, int(round(info['fps'])))} frames (1s instant scrub)")

    # Execute ffmpeg
    res = subprocess.run(cmd, capture_output=True, text=True)

    # If hardware encode failed and was not CPU, attempt automatic CPU fallback
    if res.returncode != 0 and hw_info.is_hardware:
        sys.stderr.write(
            f"[Warning] Hardware encoder '{hw_info.name}' failed during encode. "
            f"Falling back to CPU libx264...\n"
        )
        cpu_hw = HardwareEncoderInfo(
            name="cpu",
            codec="libx264",
            filter_type="scale",
            extra_encode_args=["-preset", "veryfast", "-crf", "23", "-tune", "fastdecode", "-bf", "0", "-pix_fmt", "yuv420p"],
            is_hardware=False,
            description="CPU libx264 fallback",
        )
        cmd_fallback = build_ffmpeg_proxy_command(
            input_p, out_p, cpu_hw, target_w, target_h, fps=info["fps"]
        )
        res = subprocess.run(cmd_fallback, capture_output=True, text=True)
        if res.returncode == 0:
            hw_info = cpu_hw

    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg proxy generation failed: {res.stderr[-500:]}")

    file_size = out_p.stat().st_size
    print(f"✓ Proxy generated successfully: {out_p} ({file_size / (1024 * 1024):.2f} MB)")

    if project_dir:
        update_pipeline_state_proxy(Path(project_dir), out_p, input_p)

    return {
        "status": "success",
        "input_path": str(input_p),
        "output_path": str(out_p),
        "hw_backend": hw_info.name,
        "hw_codec": hw_info.codec,
        "is_hardware": hw_info.is_hardware,
        "source_dimensions": [info["width"], info["height"]],
        "target_dimensions": [target_w, target_h],
        "file_size": file_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hardware-Optimized Video Proxy Generator (scripts/generate_proxy.py)"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # generate
    p_gen = subparsers.add_parser("generate", help="Generate hardware-optimized proxy for a video")
    p_gen.add_argument("--input", "-i", required=True, help="Path to input raw video file")
    p_gen.add_argument("--output", "-o", default=None, help="Path to destination proxy file (default: raw/Proxies/<stem>_Proxy.mp4)")
    p_gen.add_argument("--dir", "-d", default=None, help="Project directory to update in .clipping_state.json")
    p_gen.add_argument("--scale", type=float, default=0.5, help="Scale factor (default: 0.5 for half-res)")
    p_gen.add_argument("--max-height", type=int, default=540, help="Maximum proxy height in pixels (default: 540)")
    p_gen.add_argument("--hw", default="auto", choices=["auto", "vaapi", "nvenc", "videotoolbox", "qsv", "cpu"], help="Hardware acceleration backend")
    p_gen.add_argument("--force", action="store_true", help="Overwrite existing proxy file if present")
    p_gen.add_argument("--dry-run", action="store_true", help="Print FFmpeg command without executing")
    p_gen.add_argument("--json", action="store_true", help="Emit JSON output")

    # probe-hw
    p_probe = subparsers.add_parser("probe-hw", help="Probe and display host hardware acceleration capabilities")
    p_probe.add_argument("--hw", default="auto", choices=["auto", "vaapi", "nvenc", "videotoolbox", "qsv", "cpu"], help="Preferred hardware backend to test")
    p_probe.add_argument("--json", action="store_true", help="Emit JSON output")

    args = parser.parse_args()

    if not args.subcommand or args.subcommand == "probe-hw":
        hw = probe_hardware_acceleration(preferred=getattr(args, "hw", "auto"))
        if getattr(args, "json", False):
            print(json.dumps(hw.to_dict(), indent=2))
        else:
            print("=" * 60)
            print("HARDWARE ACCELERATION ENCODER PROBE")
            print("=" * 60)
            print(f"Backend Name: {hw.name}")
            print(f"Codec:        {hw.codec}")
            print(f"Device:       {hw.device or 'N/A'}")
            print(f"Hardware Acc: {hw.is_hardware}")
            print(f"Description:  {hw.description}")
            print("=" * 60)
        return 0

    if args.subcommand == "generate":
        try:
            res = generate_proxy(
                input_path=Path(args.input),
                output_path=Path(args.output) if args.output else None,
                project_dir=Path(args.dir) if args.dir else None,
                scale=args.scale,
                max_height=args.max_height,
                preferred_hw=args.hw,
                force=args.force,
                dry_run=args.dry_run,
            )
            if args.json:
                print(json.dumps(res, indent=2))
            return 0
        except Exception as e:
            sys.stderr.write(f"Error generating proxy: {e}\n")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
