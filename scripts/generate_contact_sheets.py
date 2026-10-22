#!/usr/bin/env python3
"""
generate_contact_sheets.py - High-performance timestamped contact sheet generator.

Creates 3x3, 4x4 (or custom NxM) visual contact sheets with burnt-in timecode overlays
from long-form video footage. Used to ground AI video editing subagents (clipping,
hook hunting, rough cuts, and B-roll selection) with visual context (reactions,
facial expressions, gestures, physical humor, streamer freak-outs) alongside Whisper JSON.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def find_system_font() -> Optional[str]:
    """Locate a reliable system TTF font for drawtext overlays."""
    candidates = [
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    try:
        res = subprocess.run(["fc-match", "-f", "%{file}"], capture_output=True, text=True)
        if res.returncode == 0:
            font_path = res.stdout.strip()
            if os.path.isfile(font_path) and font_path.lower().endswith((".ttf", ".otf", ".ttc")):
                return font_path
    except Exception:
        pass
    return None


def parse_timecode_to_seconds(tc: Any) -> float:
    """Parse float seconds, MM:SS, or HH:MM:SS string to float seconds."""
    if isinstance(tc, (int, float)):
        return float(tc)
    tc_str = str(tc).strip()
    try:
        return float(tc_str)
    except ValueError:
        pass

    parts = tc_str.split(":")
    if len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"Unrecognized timecode format: '{tc}'")


def format_seconds_to_hms(seconds: float, force_hours: bool = False) -> str:
    """Format seconds into HH:MM:SS or MM:SS string."""
    total_sec = max(0.0, float(seconds))
    s = int(round(total_sec))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0 or force_hours:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def get_video_info(video_path: Path) -> Dict[str, Any]:
    """Retrieve video metadata (duration, width, height, fps) using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,r_frame_rate,nb_frames:format=duration",
        "-of", "json",
        str(video_path.resolve())
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

    duration_str = v_stream.get("duration") or fmt.get("duration") or "0"
    duration = float(duration_str)

    fps_str = v_stream.get("r_frame_rate", "30/1")
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / max(1.0, float(den))
    else:
        fps = float(fps_str)

    return {
        "width": width,
        "height": height,
        "duration": duration,
        "fps": fps,
        "aspect_ratio": "9:16" if height > width else ("16:9" if width > height else "1:1")
    }


def is_vaapi_available() -> bool:
    """Check if Linux VAAPI hardware acceleration is accessible."""
    dev = Path("/dev/dri/renderD128")
    if not dev.exists() or not os.access(dev, os.R_OK | os.W_OK):
        return False
    cmd = [
        "ffmpeg", "-init_hw_device", "vaapi=vaapi0:/dev/dri/renderD128",
        "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
        "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0


def render_single_pass_sheet(
    video_path: Path,
    output_image: Path,
    start_time: float,
    end_time: float,
    rows: int,
    cols: int,
    tile_width: int,
    font_path: Optional[str] = None,
    force_hours: bool = False,
    use_vaapi: bool = False,
) -> List[Dict[str, Any]]:
    """
    Render a contact sheet using single-pass linear decode with fps sampling.
    Best for short/medium segments (up to ~3 minutes).
    """
    total_tiles = rows * cols
    span = max(0.1, end_time - start_time)
    
    # Calculate exact timestamps for each tile
    if total_tiles == 1:
        timestamps = [start_time]
    else:
        step = span / float(total_tiles - 1)
        timestamps = [min(end_time, start_time + i * step) for i in range(total_tiles)]

    tiles_meta = []
    drawtext_filters = []

    # Dynamic sizing based on tile width
    font_size = max(12, int(tile_width / 18))
    box_border = max(2, int(font_size / 4))
    padding = max(4, int(tile_width / 35))

    for i, t in enumerate(timestamps):
        tc = format_seconds_to_hms(t, force_hours=force_hours)
        tc_escaped = tc.replace(":", "\\:")
        r = i // cols
        c = i % cols
        tiles_meta.append({
            "tile_index": i,
            "row": r,
            "col": c,
            "timestamp": round(t, 3),
            "timecode": tc
        })

        font_clause = f"fontfile='{font_path}':" if font_path else ""
        drawtext_filters.append(
            f"drawtext={font_clause}text='{tc_escaped}':enable='eq(n\\,{i})':"
            f"x={padding}:y=h-th-{padding}:fontsize={font_size}:fontcolor=white:"
            f"box=1:boxcolor=black@0.75:boxborderw={box_border}"
        )

    fps_val = total_tiles / span
    dt_chain = ",".join(drawtext_filters)
    vf = f"fps={fps_val:.6f},scale={tile_width}:-2,{dt_chain},tile={cols}x{rows}:padding=4:margin=4:color=black"

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if use_vaapi and is_vaapi_available():
        cmd += ["-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128"]

    cmd += [
        "-ss", f"{start_time:.3f}",
        "-to", f"{end_time:.3f}",
        "-i", str(video_path.resolve()),
        "-vf", vf,
        "-frames:v", "1",
        "-q:v", "2",
        str(output_image.resolve())
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 and use_vaapi:
        # Fall back to software decode if VAAPI failed (e.g. unsupported codec like AV1)
        cmd_software = [c for c in cmd if c not in ("-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128")]
        res = subprocess.run(cmd_software, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg single-pass contact sheet failed: {res.stderr}")

    return tiles_meta


def render_seek_grab_sheet(
    video_path: Path,
    output_image: Path,
    timestamps: List[float],
    rows: int,
    cols: int,
    tile_width: int,
    font_path: Optional[str] = None,
    force_hours: bool = False,
    use_vaapi: bool = False,
) -> List[Dict[str, Any]]:
    """
    Render a contact sheet using fast input seeks (-ss per frame).
    Essential for long durations / full video overviews to avoid decoding dead footage.
    """
    total_tiles = len(timestamps)
    font_size = max(12, int(tile_width / 18))
    box_border = max(2, int(font_size / 4))
    padding = max(4, int(tile_width / 35))

    inputs = []
    per_input_filters = []
    tiles_meta = []

    for i, t in enumerate(timestamps):
        tc = format_seconds_to_hms(t, force_hours=force_hours)
        tc_escaped = tc.replace(":", "\\:")
        r = i // cols
        c = i % cols
        tiles_meta.append({
            "tile_index": i,
            "row": r,
            "col": c,
            "timestamp": round(t, 3),
            "timecode": tc
        })

        inputs += ["-ss", f"{t:.3f}", "-i", str(video_path.resolve())]

        font_clause = f"fontfile='{font_path}':" if font_path else ""
        drawtext = (
            f"drawtext={font_clause}text='{tc_escaped}':"
            f"x={padding}:y=h-th-{padding}:fontsize={font_size}:fontcolor=white:"
            f"box=1:boxcolor=black@0.75:boxborderw={box_border}"
        )
        per_input_filters.append(f"[{i}:v]scale={tile_width}:-2,{drawtext},setsar=1[v{i}]")

    concat_inputs = "".join(f"[v{i}]" for i in range(total_tiles))
    filter_complex = (
        f"{';'.join(per_input_filters)};"
        f"{concat_inputs}concat=n={total_tiles}:v=1[c];"
        f"[c]tile={cols}x{rows}:padding=4:margin=4:color=black"
    )

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if use_vaapi and is_vaapi_available():
        cmd += ["-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128"]

    cmd += inputs + [
        "-filter_complex", filter_complex,
        "-frames:v", "1",
        "-q:v", "2",
        str(output_image.resolve())
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 and use_vaapi:
        # Fall back to software decode if VAAPI failed (e.g. unsupported codec like AV1)
        cmd_software = [c for c in cmd if c not in ("-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128")]
        res = subprocess.run(cmd_software, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg seek-grab contact sheet failed: {res.stderr}")

    return tiles_meta


def generate_contact_sheets(
    video_path: Path,
    output_dir: Path,
    grid: str = "4x4",
    mode: str = "batch",
    slice_duration: float = 120.0,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
    tile_width: Optional[int] = None,
    use_vaapi: bool = True,
    prefix: str = "sheet"
) -> Dict[str, Any]:
    """
    Main programmatic API to generate contact sheets and index JSON.
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    info = get_video_info(video_path)
    duration = info["duration"]
    force_hours = duration >= 3600.0

    # Parse grid
    try:
        parts = grid.lower().split("x")
        cols = int(parts[0])
        rows = int(parts[1])
    except Exception:
        cols, rows = 4, 4

    total_tiles = cols * rows

    # Automatic tile width based on orientation
    if tile_width is None:
        tile_width = 240 if info["aspect_ratio"] == "9:16" else 360

    font_path = find_system_font()
    sheets_output = []

    if mode == "range":
        s_time = max(0.0, start_time if start_time is not None else 0.0)
        e_time = min(duration, end_time if end_time is not None else duration)
        span = e_time - s_time
        img_name = f"{prefix}_range_{int(s_time)}s_{int(e_time)}s.jpg"
        out_img = output_dir / img_name

        if span > 180.0:
            step = span / float(total_tiles - 1)
            ts_list = [min(e_time, s_time + i * step) for i in range(total_tiles)]
            tiles = render_seek_grab_sheet(
                video_path, out_img, ts_list, rows, cols, tile_width,
                font_path, force_hours, use_vaapi
            )
        else:
            tiles = render_single_pass_sheet(
                video_path, out_img, s_time, e_time, rows, cols, tile_width,
                font_path, force_hours, use_vaapi
            )

        sheets_output.append({
            "sheet_id": 1,
            "filename": img_name,
            "image_path": str(out_img.resolve()),
            "start_time": round(s_time, 3),
            "end_time": round(e_time, 3),
            "start_tc": format_seconds_to_hms(s_time, force_hours),
            "end_tc": format_seconds_to_hms(e_time, force_hours),
            "tiles": tiles
        })

    elif mode == "overview":
        img_name = f"{prefix}_full_overview.jpg"
        out_img = output_dir / img_name
        step = duration / float(total_tiles - 1)
        ts_list = [min(duration, i * step) for i in range(total_tiles)]
        tiles = render_seek_grab_sheet(
            video_path, out_img, ts_list, rows, cols, tile_width,
            font_path, force_hours, use_vaapi
        )
        sheets_output.append({
            "sheet_id": 1,
            "filename": img_name,
            "image_path": str(out_img.resolve()),
            "start_time": 0.0,
            "end_time": round(duration, 3),
            "start_tc": format_seconds_to_hms(0.0, force_hours),
            "end_tc": format_seconds_to_hms(duration, force_hours),
            "tiles": tiles
        })

    elif mode == "candidates" and candidates:
        for idx, cand in enumerate(candidates):
            c_start = parse_timecode_to_seconds(cand.get("start", 0.0))
            c_end = parse_timecode_to_seconds(cand.get("end", c_start + 30.0))
            cid = cand.get("id") or cand.get("slug") or f"candidate_{idx+1}"
            img_name = f"{prefix}_{cid}.jpg"
            out_img = output_dir / img_name

            span = c_end - c_start
            if span > 180.0:
                step = span / float(total_tiles - 1)
                ts_list = [min(c_end, c_start + i * step) for i in range(total_tiles)]
                tiles = render_seek_grab_sheet(
                    video_path, out_img, ts_list, rows, cols, tile_width,
                    font_path, force_hours, use_vaapi
                )
            else:
                tiles = render_single_pass_sheet(
                    video_path, out_img, c_start, c_end, rows, cols, tile_width,
                    font_path, force_hours, use_vaapi
                )

            sheets_output.append({
                "sheet_id": idx + 1,
                "candidate_id": cid,
                "title": cand.get("title", f"Clip {cid}"),
                "filename": img_name,
                "image_path": str(out_img.resolve()),
                "start_time": round(c_start, 3),
                "end_time": round(c_end, 3),
                "start_tc": format_seconds_to_hms(c_start, force_hours),
                "end_tc": format_seconds_to_hms(c_end, force_hours),
                "tiles": tiles
            })

    else:  # mode == "batch"
        cur = 0.0
        sheet_id = 1
        num_slices = max(1, int(math.ceil(duration / slice_duration)))

        while cur < duration:
            nxt = min(duration, cur + slice_duration)
            img_name = f"{prefix}_{sheet_id:04d}.jpg"
            out_img = output_dir / img_name

            span = nxt - cur
            if span > 180.0:
                step = span / float(total_tiles - 1)
                ts_list = [min(nxt, cur + i * step) for i in range(total_tiles)]
                tiles = render_seek_grab_sheet(
                    video_path, out_img, ts_list, rows, cols, tile_width,
                    font_path, force_hours, use_vaapi
                )
            else:
                tiles = render_single_pass_sheet(
                    video_path, out_img, cur, nxt, rows, cols, tile_width,
                    font_path, force_hours, use_vaapi
                )

            sheets_output.append({
                "sheet_id": sheet_id,
                "filename": img_name,
                "image_path": str(out_img.resolve()),
                "start_time": round(cur, 3),
                "end_time": round(nxt, 3),
                "start_tc": format_seconds_to_hms(cur, force_hours),
                "end_tc": format_seconds_to_hms(nxt, force_hours),
                "tiles": tiles
            })

            cur = nxt
            sheet_id += 1

    index_data = {
        "source_video": str(video_path.resolve()),
        "duration": round(duration, 3),
        "duration_tc": format_seconds_to_hms(duration, force_hours),
        "resolution": f"{info['width']}x{info['height']}",
        "aspect_ratio": info["aspect_ratio"],
        "grid": f"{cols}x{rows}",
        "total_tiles_per_sheet": total_tiles,
        "mode": mode,
        "sheets_count": len(sheets_output),
        "sheets": sheets_output
    }

    index_path = output_dir / "contact_sheets.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2)

    return index_data


def main():
    parser = argparse.ArgumentParser(
        description="Render timestamped 3x3 or 4x4 contact sheets for visual video grounding."
    )
    parser.add_argument("--input", "-i", required=True, help="Input video file path")
    parser.add_argument("--output-dir", "-o", default=None, help="Output directory for sheets and index")
    parser.add_argument("--grid", "-g", default="4x4", help="Grid dimension, e.g. 4x4 or 3x3 (default: 4x4)")
    parser.add_argument(
        "--mode", "-m", choices=["batch", "range", "overview", "candidates"],
        default="batch", help="Operating mode: batch slices, specific range, full overview, or candidates list"
    )
    parser.add_argument("--slice-duration", "-d", type=float, default=120.0, help="Duration (sec) per sheet in batch mode")
    parser.add_argument("--start", "-s", default=None, help="Start timecode/seconds for range mode")
    parser.add_argument("--end", "-e", default=None, help="End timecode/seconds for range mode")
    parser.add_argument("--candidates-json", "-c", default=None, help="Path to JSON file containing candidate clips")
    parser.add_argument("--tile-width", "-w", type=int, default=None, help="Width in pixels of each tile (default: auto)")
    parser.add_argument("--no-vaapi", action="store_true", help="Disable Intel VAAPI hardware acceleration")
    parser.add_argument("--prefix", "-p", default="sheet", help="Filename prefix for generated contact sheets")

    args = parser.parse_args()

    video_path = Path(args.input)
    if not video_path.exists():
        print(f"Error: Video file not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.output_dir) if args.output_dir else video_path.parent / "contact_sheets"

    start_sec = parse_timecode_to_seconds(args.start) if args.start is not None else None
    end_sec = parse_timecode_to_seconds(args.end) if args.end is not None else None

    candidates_list = None
    if args.candidates_json:
        c_path = Path(args.candidates_json)
        if c_path.exists():
            with open(c_path, "r", encoding="utf-8") as f:
                c_data = json.load(f)
                candidates_list = c_data if isinstance(c_data, list) else c_data.get("candidates", [])

    print(f"Generating {args.grid} contact sheets for {video_path.name} in mode '{args.mode}'...")
    manifest = generate_contact_sheets(
        video_path=video_path,
        output_dir=out_dir,
        grid=args.grid,
        mode=args.mode,
        slice_duration=args.slice_duration,
        start_time=start_sec,
        end_time=end_sec,
        candidates=candidates_list,
        tile_width=args.tile_width,
        use_vaapi=not args.no_vaapi,
        prefix=args.prefix
    )

    print(f"✓ Generated {manifest['sheets_count']} contact sheet(s) into: {out_dir}")
    print(f"✓ Index saved at: {out_dir / 'contact_sheets.json'}")


if __name__ == "__main__":
    main()
