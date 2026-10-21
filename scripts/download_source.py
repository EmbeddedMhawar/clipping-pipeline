#!/usr/bin/env python3
"""
scripts/download_source.py - Source Video Downloader & Proxy Pipeline Bridge.

Downloads raw campaign source videos (YouTube, VODs, creator links) via yt-dlp,
saves them to <project_dir>/raw/<slug>.mp4, and immediately chains hardware-accelerated
proxy generation (scripts/generate_proxy.py) into <project_dir>/raw/Proxies/<slug>_Proxy.mp4.
Updates .clipping_state.json with resolved raw and proxy paths to prepare for Step 2
transcription and Step 4 timeline assembly.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Import proxy generation engine
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from generate_proxy import generate_proxy, probe_hardware_acceleration


def sanitize_filename_slug(name: str) -> str:
    """Convert string to safe filesystem filename slug."""
    s = re.sub(r"[^\w\s-]", "", name).strip().lower()
    return re.sub(r"[-\s]+", "-", s)


def resolve_source_url_from_project(project_dir: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Inspect project directory for source_video URL and campaign slug.
    Checks campaign_brief.json and .clipping_state.json.
    Returns (url, project_slug).
    """
    brief_file = project_dir / "campaign_brief.json"
    state_file = project_dir / ".clipping_state.json"

    url: Optional[str] = None
    slug: Optional[str] = None

    if brief_file.is_file():
        try:
            with open(brief_file, "r", encoding="utf-8") as f:
                brief = json.load(f)
            camp = brief.get("campaign", {})
            slug = camp.get("project")
            src_v = camp.get("source_video", {})
            if isinstance(src_v, dict):
                url = src_v.get("url")
            elif isinstance(src_v, str):
                url = src_v
        except Exception:
            pass

    if not url and state_file.is_file():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            url = (
                state.get("source_url")
                or state.get("campaign_brief", {}).get("campaign", {}).get("source_video", {}).get("url")
            )
            if not slug:
                slug = (
                    state.get("project")
                    or state.get("campaign_brief", {}).get("campaign", {}).get("project")
                )
        except Exception:
            pass

    return url, slug


def get_remote_video_metadata(url: str) -> Dict[str, Any]:
    """Retrieve video title, duration, and uploader using yt-dlp without downloading."""
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp binary not found in system PATH. Please install yt-dlp.")

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "--dump-json",
        url,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"yt-dlp failed to inspect URL {url}: {res.stderr.strip()[:300]}")

    try:
        data = json.loads(res.stdout)
        return {
            "title": data.get("title", ""),
            "duration": data.get("duration", 0),
            "uploader": data.get("uploader", "") or data.get("channel", ""),
            "ext": data.get("ext", "mp4"),
            "id": data.get("id", ""),
        }
    except json.JSONDecodeError:
        return {}


def download_video(
    url: str,
    output_path: Path,
    format_selector: str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    dry_run: bool = False,
) -> Path:
    """Download video using yt-dlp into specified output path."""
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp binary not found in system PATH. Please install yt-dlp.")

    output_p = output_path.resolve()
    output_p.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "-f", format_selector,
        "--merge-output-format", "mp4",
        "-o", str(output_p),
        url,
    ]

    if dry_run:
        print(f"[dry-run] yt-dlp download command: {' '.join(cmd)}")
        return output_p

    print(f"Downloading source video from: {url}")
    print(f"  Target path : {output_p}")

    res = subprocess.run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"yt-dlp download failed with exit code {res.returncode}")

    if not output_p.exists():
        # Check if yt-dlp appended extension or changed filename
        candidates = list(output_p.parent.glob(f"{output_p.stem}.*"))
        if candidates:
            return candidates[0]
        raise FileNotFoundError(f"Expected downloaded video file not found at {output_p}")

    print(f"✓ Video download complete: {output_p} ({output_p.stat().st_size / (1024 * 1024):.2f} MB)")
    return output_p


def download_and_generate_proxy(
    url: Optional[str] = None,
    project_dir: Optional[Path] = None,
    slug: Optional[str] = None,
    output_path: Optional[Path] = None,
    no_proxy: bool = False,
    proxy_only: bool = False,
    hw_backend: Optional[str] = "auto",
    scale: float = 0.5,
    max_height: Optional[int] = 540,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Download video from source URL (or resolve from project) and immediately
    generate hardware-accelerated proxy in <project_dir>/raw/Proxies/<slug>_Proxy.mp4.
    """
    p_dir = Path(project_dir).resolve() if project_dir else Path.cwd().resolve()

    target_url = url
    target_slug = slug

    # If URL or slug missing, attempt project resolution
    if not target_url or not target_slug:
        proj_url, proj_slug = resolve_source_url_from_project(p_dir)
        if not target_url:
            target_url = proj_url
        if not target_slug:
            target_slug = proj_slug

    raw_dir = p_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Resolve target video path
    if output_path:
        target_video_path = Path(output_path).resolve()
    elif target_slug:
        target_video_path = raw_dir / f"{sanitize_filename_slug(target_slug)}.mp4"
    else:
        # Fallback to general slug or lookup existing mp4
        existing_mp4s = list(raw_dir.glob("*.mp4"))
        existing_raw = [f for f in existing_mp4s if not f.name.endswith("_Proxy.mp4")]
        if proxy_only and existing_raw:
            target_video_path = existing_raw[0]
        else:
            target_video_path = raw_dir / "source_video.mp4"

    # Step 1: Download video (unless proxy_only is True)
    if not proxy_only:
        if not target_url:
            raise ValueError(
                "No source URL provided via --url and none could be resolved from "
                f"{p_dir}/campaign_brief.json or .clipping_state.json."
            )

        if not target_video_path.exists() or force:
            target_video_path = download_video(
                url=target_url,
                output_path=target_video_path,
                dry_run=dry_run,
            )
        else:
            print(f"✓ Source video already downloaded: {target_video_path}")
    else:
        if not target_video_path.exists():
            raise FileNotFoundError(f"--proxy-only specified but source video not found at: {target_video_path}")
        print(f"✓ Using existing source video: {target_video_path}")

    result: Dict[str, Any] = {
        "status": "success",
        "url": target_url,
        "raw_video_path": str(target_video_path),
        "proxy_path": None,
        "proxy_generated": False,
    }

    # Step 2: Generate Hardware Proxy
    if not no_proxy:
        proxy_res = generate_proxy(
            input_path=target_video_path,
            project_dir=p_dir,
            scale=scale,
            max_height=max_height,
            preferred_hw=hw_backend,
            force=force,
            dry_run=dry_run,
        )
        result["proxy_path"] = proxy_res.get("output_path")
        result["proxy_generated"] = (proxy_res.get("status") == "success")
        result["proxy_info"] = proxy_res

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Source Video Downloader & Hardware Proxy Engine (scripts/download_source.py)"
    )
    parser.add_argument("--url", "-u", default=None, help="Source video URL (YouTube, VOD, etc.)")
    parser.add_argument("--dir", "-d", default=None, help="Target clipping project directory")
    parser.add_argument("--slug", "-s", default=None, help="Project or filename slug for the downloaded video")
    parser.add_argument("--output", "-o", default=None, help="Explicit destination path for downloaded raw video")
    parser.add_argument("--no-proxy", action="store_true", help="Skip proxy generation after download")
    parser.add_argument("--proxy-only", action="store_true", help="Skip download and generate proxy for existing raw video")
    parser.add_argument("--hw", default="auto", choices=["auto", "vaapi", "nvenc", "videotoolbox", "qsv", "cpu"], help="Hardware acceleration backend for proxy")
    parser.add_argument("--scale", type=float, default=0.5, help="Proxy scale factor (default: 0.5)")
    parser.add_argument("--max-height", type=int, default=540, help="Maximum proxy height (default: 540)")
    parser.add_argument("--force", action="store_true", help="Force re-download and re-generate existing files")
    parser.add_argument("--dry-run", action="store_true", help="Print plan and commands without executing")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")

    args = parser.parse_args()

    try:
        res = download_and_generate_proxy(
            url=args.url,
            project_dir=Path(args.dir) if args.dir else None,
            slug=args.slug,
            output_path=Path(args.output) if args.output else None,
            no_proxy=args.no_proxy,
            proxy_only=args.proxy_only,
            hw_backend=args.hw,
            scale=args.scale,
            max_height=args.max_height,
            force=args.force,
            dry_run=args.dry_run,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        return 0
    except Exception as e:
        sys.stderr.write(f"Error in download_source: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
