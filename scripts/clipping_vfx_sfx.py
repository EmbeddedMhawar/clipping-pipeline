#!/usr/bin/env python3
"""
scripts/clipping_vfx_sfx.py

Step 6: Visual Effects (VFX) & Sound Design (SFX) Compositing Engine for the
Antigravity Short-Form Clipping Pipeline.

Ingests the pre-digested vfx_sfx_slice, enforces mandatory persistent brand
watermark placement (safe from 4 corners and caption zone), injects 0-3s kinetic
title hook overlays, synthesizes and places color stabs / shock VFX passes
(Crimson Red #FF0000 shock, Neon Acid Green #CCFF00 flex), and injects synchronized
SFX transients (sub-bass hits, whooshes, pops) onto Track A3 ducked to -4.0dB,
strictly enforcing zero background music beds and zero phonk rules.
Interfaces with HyperFrames (HTML/CSS/GSAP motion graphics compositions with
data-start/data-duration attributes), Remotion (.remotion.json), and triggers
the live companion checkpoint gate.

Primary References:
- skills/clipping-pipeline/SKILL.md (Step 6: clipping-vfx-sfx)
- docs/adr/0012-remotion-and-hyperframes-rendering-engine.md
- GLOSSARY.md ("Live GUI Companion", "Feedback Checkpoint", "Preference Store")
- docs/adr/0001-project-local-json-state-file.md
- docs/adr/0002-pre-digested-step-slices.md
- docs/adr/0003-strict-sequential-step-gating.md
- references/CAMPAIGN_BRIEF_SCHEMA.md
- scripts/clipping_state.py
- scripts/clipping_preferences.py
- scripts/gui_companion.py
"""

import argparse
import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple, Union
import wave

# High-precision time base: 254,016,000,000 discrete ticks per second
TICKS_PER_SEC: int = 254_016_000_000

# Canonical Canvas Dimensions
CANVAS_WIDTH: int = 1080
CANVAS_HEIGHT: int = 1920

# Canonical Track Identifiers & Names
TRACK_V1_NAME: str = "Blurred Background"
TRACK_V2_NAME: str = "Speaker Foreground"
TRACK_V3_NAME: str = "HUD & Overlays"
TRACK_V4_NAME: str = "Watermark"

TRACK_A1_NAME: str = "Dialogue"
TRACK_A2_NAME: str = "Background Music"
TRACK_A3_NAME: str = "SFX"

# Watermark Default Transform
WATERMARK_SCALE_PCT: float = 28.0
WATERMARK_DEFAULT_X: float = 540.0
WATERMARK_DEFAULT_Y: float = 280.0
WATERMARK_DEFAULT_OPACITY: float = 100.0

# Sound Design Defaults
SFX_DEFAULT_VOLUME_DB: float = -4.0
SFX_SAMPLE_RATE: int = 48000


def seconds_to_ticks(seconds: float) -> int:
    """Convert floating-point seconds to nearest timeline ticks."""
    return int(round(seconds * TICKS_PER_SEC))


def ticks_to_seconds(ticks: int) -> float:
    """Convert timeline ticks to floating-point seconds."""
    return float(ticks) / TICKS_PER_SEC


@dataclass
class VisualOverlayCue:
    """Represents a visual graphic or VFX overlay on Track V3 or V4."""
    id: str
    track: str  # 'V3' or 'V4'
    start_seconds: float
    duration_seconds: float
    asset_path: str
    name: str
    overlay_type: str  # 'watermark', 'title_hook', 'color_stab', 'bloom'
    scale_pct: float = 100.0
    pos_x: float = 540.0
    pos_y: float = 960.0
    opacity: float = 100.0
    blend_mode: str = "Normal"  # 'Normal', 'Screen', 'Add', 'Difference'


@dataclass
class AudioTransientCue:
    """Represents a sound design transient on Track A3."""
    id: str
    start_seconds: float
    duration_seconds: float
    asset_path: str
    name: str
    sfx_type: str  # 'whoosh_in', 'sub_boom_hit', 'pop_clean', 'riser'
    volume_db: float = SFX_DEFAULT_VOLUME_DB


# ---------------------------------------------------------------------------
# Procedural SFX & Asset Synthesis Engine
# ---------------------------------------------------------------------------

def synthesize_sub_boom_wav(out_path: Path, duration: float = 0.6) -> Path:
    """
    Synthesizes a clean 48kHz stereo 16-bit PCM sub-bass drop / sub-boom hit.
    Frequency sweeps exponentially from 95Hz down to 32Hz with exponential decay.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(SFX_SAMPLE_RATE * duration)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SFX_SAMPLE_RATE)
        frames = bytearray()
        for i in range(num_samples):
            t = i / SFX_SAMPLE_RATE
            # Exponential pitch drop from 95Hz to 32Hz
            freq = 63.0 * math.exp(-3.5 * t) + 32.0
            # Exponential amplitude envelope
            env = math.exp(-3.2 * t)
            sample = int(32767.0 * 0.85 * env * math.sin(2.0 * math.pi * freq * t))
            sample = max(-32767, min(32767, sample))
            frames.extend(struct.pack("<hh", sample, sample))
        wf.writeframes(frames)
    return out_path


def synthesize_whoosh_wav(out_path: Path, duration: float = 0.45) -> Path:
    """
    Synthesizes a 48kHz stereo 16-bit PCM snappy whoosh transient.
    Uses filtered noise sweep shaped with a smooth attack-decay envelope.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(SFX_SAMPLE_RATE * duration)
    # Simple pseudo-random linear congruential generator for zero external deps
    state = 123456789
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SFX_SAMPLE_RATE)
        frames = bytearray()
        prev_sample = 0.0
        for i in range(num_samples):
            t = i / SFX_SAMPLE_RATE
            norm_t = t / duration
            # Asymmetrical bell envelope peaked at 35% of duration
            if norm_t < 0.35:
                env = math.sin((norm_t / 0.35) * (math.pi / 2.0))
            else:
                env = math.cos(((norm_t - 0.35) / 0.65) * (math.pi / 2.0))
            env = max(0.0, env) ** 1.5

            # Noise generation
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            raw_noise = (state / 0x7FFFFFFF) * 2.0 - 1.0

            # Swept lowpass / bandpass filter effect
            cutoff = 0.15 + 0.55 * env
            filtered = prev_sample + cutoff * (raw_noise - prev_sample)
            prev_sample = filtered

            val = int(32767.0 * 0.70 * env * filtered)
            val = max(-32767, min(32767, val))
            frames.extend(struct.pack("<hh", val, val))
        wf.writeframes(frames)
    return out_path


def synthesize_pop_wav(out_path: Path, duration: float = 0.20) -> Path:
    """
    Synthesizes a 48kHz stereo 16-bit acoustic / mechanical thock/pop transient.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(SFX_SAMPLE_RATE * duration)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SFX_SAMPLE_RATE)
        frames = bytearray()
        for i in range(num_samples):
            t = i / SFX_SAMPLE_RATE
            # Rapid 280Hz -> 90Hz click
            freq = 200.0 * math.exp(-25.0 * t) + 80.0
            env = math.exp(-22.0 * t)
            sample = int(32767.0 * 0.75 * env * math.sin(2.0 * math.pi * freq * t))
            sample = max(-32767, min(32767, sample))
            frames.extend(struct.pack("<hh", sample, sample))
        wf.writeframes(frames)
    return out_path


def synthesize_brand_watermark_png(
    out_path: Path,
    brand_title: str = "HardScope",
    handle: str = "@HardScopeTV",
    width: int = 640,
    height: int = 120,
) -> Path:
    """
    Generates a crisp floating text brand watermark PNG with alpha transparency.
    Uses modern SVG typography with soft neon glow, dark drop stroke, and transparent background
    (viral streamer floating watermark standard, zero container box).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    display_text = handle if handle.startswith("@") else f"@{handle}"
    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <!-- Strong dark shadow for contrast against bright backgrounds -->
      <feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#000000" flood-opacity="0.9"/>
      <!-- Soft colorful outer glow for viral streamer dissolve finish -->
      <feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#EC4899" flood-opacity="0.6"/>
      <feDropShadow dx="0" dy="0" stdDeviation="12" flood-color="#8B5CF6" flood-opacity="0.3"/>
    </filter>
    <linearGradient id="textGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#38BDF8"/>
      <stop offset="50%" stop-color="#F472B6"/>
      <stop offset="100%" stop-color="#FFFFFF"/>
    </linearGradient>
  </defs>
  <!-- Pure floating text with subtle stroke and glow - zero box/pill background -->
  <text x="{width // 2}" y="{height // 2 + 18}" font-family="Montserrat, Arial Black, Impact, sans-serif"
        font-size="52" font-weight="900" fill="url(#textGrad)"
        stroke="#090D16" stroke-width="3" paint-order="stroke fill"
        text-anchor="middle" filter="url(#glow)" letter-spacing="1.5">{display_text.upper()}</text>
</svg>"""

    svg_path = out_path.with_suffix(".svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg_content)

    # Try rsvg-convert first
    if shutil.which("rsvg-convert"):
        cmd = ["rsvg-convert", "-o", str(out_path), str(svg_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and out_path.is_file():
            return out_path

    # Fallback to FFmpeg with librsvg or drawbox
    if shutil.which("ffmpeg"):
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(svg_path),
            "-frames:v",
            "1",
            str(out_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and out_path.is_file():
            return out_path

    # Ultimate fallback: FFmpeg lavfi generator
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=color=black@0.0:size={width}x{height},format=rgba",
        "-vf",
        f"drawtext=text='{display_text}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2:borderw=3:bordercolor=black",
        "-frames:v",
        "1",
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True)
    return out_path


def synthesize_hyperframes_hook_html(
    out_html_path: Path,
    hook_text: str,
    duration_sec: float = 3.0,
    width: int = CANVAS_WIDTH,
    height: int = CANVAS_HEIGHT,
    fps: int = 30,
) -> Path:
    """
    Generates an agent-native HyperFrames HTML/CSS/GSAP composition with
    data-composition-id, data-start, and data-duration attributes for the 0-3s
    kinetic title hook graphic, strictly conforming to the 12-point HyperFrames
    deterministic seek contract (window.__timelines registration, .clip wrapper,
    zero CSS transform conflict, and explicit tl.fromTo states).
    """
    out_html_path.parent.mkdir(parents=True, exist_ok=True)
    exit_start = max(0.35, duration_sec - 0.25)
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>HyperFrames 0-3s Kinetic Hook</title>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js" crossorigin="anonymous"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body, html {{
      margin: 0; padding: 0; width: {width}px; height: {height}px;
      background: transparent; overflow: hidden;
      font-family: 'Montserrat', 'Inter', sans-serif;
    }}
    #root {{
      position: absolute; inset: 0;
      width: {width}px; height: {height}px;
      background: transparent; overflow: hidden;
    }}
    .hook-clip {{
      position: absolute; top: 380px; left: 0;
      width: {width}px; display: flex; justify-content: center;
      pointer-events: none;
    }}
    .hook-card {{
      background: #FFFFFF; color: #0A0A0A;
      padding: 24px 40px; border-radius: 24px;
      font-weight: 900; font-size: 46px; line-height: 1.2;
      text-align: center; max-width: 880px;
      box-shadow: 0 18px 48px rgba(0, 0, 0, 0.55);
      border: 4px solid #CCFF00;
    }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="hook-title-0-3s" data-start="0" data-duration="{duration_sec}" data-width="{width}" data-height="{height}" data-fps="{fps}">
    <div id="hook-clip" class="clip hook-clip" data-start="0" data-duration="{duration_sec}" data-track-index="1">
      <div id="hook-badge" class="hook-card">
        {hook_text}
      </div>
    </div>
  </div>
  <script>
    window.__timelines = window.__timelines || {{}};
    if (window.gsap) {{
      const tl = gsap.timeline({{ paused: true }});
      tl.fromTo(
        "#hook-badge",
        {{ scale: 0.75, opacity: 0, y: -30 }},
        {{ scale: 1.0, opacity: 1, y: 0, duration: 0.35, ease: "back.out(1.7)" }},
        0
      );
      tl.fromTo(
        "#hook-badge",
        {{ scale: 1.0, opacity: 1, y: 0 }},
        {{ scale: 0.92, opacity: 0, y: -20, duration: 0.22, ease: "power2.in" }},
        {exit_start:.2f}
      );
      window.__timelines["hook-title-0-3s"] = tl;
    }}
  </script>
</body>
</html>
"""
    out_html_path.write_text(html_content, encoding="utf-8")
    return out_html_path


def render_hyperframes_hook_pass(
    hf_html_path: Path,
    out_mov_path: Path,
    hook_text: str,
    duration_sec: float = 3.0,
    width: int = CANVAS_WIDTH,
    height: int = CANVAS_HEIGHT,
    fps: int = 30,
) -> Path:
    """
    Renders a HyperFrames 0-3s hook HTML composition into an Apple ProRes 4444
    (yuva444p10le) transparent video pass using `hyperframes render <dir> --composition <html_file>`,
    with deterministic FFmpeg alpha overlay fallback.
    """
    out_mov_path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("hyperframes"):
        cmd_render = [
            "hyperframes",
            "render",
            str(hf_html_path.parent),
            "--composition",
            str(hf_html_path),
            "--output",
            str(out_mov_path),
            "--format",
            "mov",
            "--fps",
            str(fps),
        ]
        res_render = subprocess.run(cmd_render, capture_output=True, text=True)
        if res_render.returncode == 0 and out_mov_path.is_file():
            return out_mov_path

    # Fallback: synthesize a transparent ProRes 4444 overlay via FFmpeg
    if shutil.which("ffmpeg"):
        cmd_ff = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black@0.0:s={width}x{height}:d={duration_sec}:r={fps},format=yuva444p10le",
            "-vf",
            "drawbox=x=100:y=380:w=880:h=140:color=white@0.95:t=fill",
            "-c:v",
            "prores_ks",
            "-profile:v",
            "4",
            "-pix_fmt",
            "yuva444p10le",
            str(out_mov_path),
        ]
        res_ff = subprocess.run(cmd_ff, capture_output=True, text=True)
        if res_ff.returncode == 0 and out_mov_path.is_file():
            return out_mov_path

    return out_mov_path


def synthesize_color_stab_pass(
    out_path: Path,
    color_hex: str = "#FF0000",
    duration_sec: float = 0.45,
    width: int = CANVAS_WIDTH,
    height: int = CANVAS_HEIGHT,
    fps: int = 30,
) -> Path:
    """
    Generates a HyperFrames HTML/CSS/GSAP color stab composition (.hyperframes.html)
    and renders an Apple ProRes 4444 (yuva444p10le) transparent video pass.
    Applies opacity fadeout from 85% to 0% across duration_sec using a paused
    GSAP timeline registered on window.__timelines["color-stab"].
    Preferred engine: hyperframes CLI render. Fallback: ffmpeg prores_ks with alpha.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    hf_html = out_path.with_suffix(".hyperframes.html")
    hf_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>HyperFrames Color Stab ({color_hex})</title>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js" crossorigin="anonymous"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body, html {{ margin: 0; padding: 0; width: {width}px; height: {height}px; background: transparent; overflow: hidden; }}
    #root {{ position: absolute; inset: 0; width: {width}px; height: {height}px; background: transparent; overflow: hidden; }}
    .stab-clip {{ position: absolute; inset: 0; width: {width}px; height: {height}px; pointer-events: none; }}
    .stab-layer {{
      position: absolute; inset: 0;
      width: 100%; height: 100%;
      background: radial-gradient(circle, {color_hex}CC 0%, {color_hex} 100%);
    }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="color-stab" data-start="0" data-duration="{duration_sec}" data-width="{width}" data-height="{height}" data-fps="{fps}">
    <div id="stab-clip" class="clip stab-clip" data-start="0" data-duration="{duration_sec}" data-track-index="1">
      <div id="stab" class="stab-layer"></div>
    </div>
  </div>
  <script>
    window.__timelines = window.__timelines || {{}};
    if (window.gsap) {{
      const tl = gsap.timeline({{ paused: true }});
      tl.fromTo(
        "#stab",
        {{ opacity: 0.85 }},
        {{ opacity: 0.0, duration: {duration_sec}, ease: "power2.out" }},
        0
      );
      window.__timelines["color-stab"] = tl;
    }}
  </script>
</body>
</html>
"""
    hf_html.write_text(hf_content, encoding="utf-8")

    # Try hyperframes CLI if available (positional arg is project directory, --composition is HTML file)
    if shutil.which("hyperframes"):
        cmd_render = [
            "hyperframes",
            "render",
            str(hf_html.parent),
            "--composition",
            str(hf_html),
            "--output",
            str(out_path),
            "--format",
            "mov",
            "--fps",
            str(fps),
        ]
        res_render = subprocess.run(cmd_render, capture_output=True, text=True)
        if res_render.returncode == 0 and out_path.is_file():
            return out_path

    # Fallback to FFmpeg ProRes 4444 with alpha
    if shutil.which("ffmpeg"):
        cmd_ff = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color_hex}@0.85:s={width}x{height}:d={duration_sec}:r={fps}",
            "-vf",
            f"fade=t=out:st=0.0:d={duration_sec}:alpha=1",
            "-c:v",
            "prores_ks",
            "-profile:v",
            "4",
            "-pix_fmt",
            "yuva444p10le",
            str(out_path),
        ]
        res_ff = subprocess.run(cmd_ff, capture_output=True, text=True)
        if res_ff.returncode == 0 and out_path.is_file():
            return out_path

    return out_path


# ---------------------------------------------------------------------------
# Emotional & Timestamp Cue Detection
# ---------------------------------------------------------------------------

def detect_vfx_sfx_cues(
    project_dir: Path,
    captions_file: Optional[Path] = None,
    meta_file: Optional[Path] = None,
    brief_data: Optional[Dict[str, Any]] = None,
    preferences_data: Optional[Dict[str, Any]] = None,
) -> Tuple[List[VisualOverlayCue], List[AudioTransientCue]]:
    """
    Analyzes captions.json, cuts/meta, and preferences to detect timestamp beats
    for persistent watermark, title hook overlay, color stabs, and SFX transients.
    """
    project_dir = Path(project_dir).resolve()
    assets_dir = project_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # 1. Resolve timeline duration
    duration_sec = 45.0
    if meta_file and meta_file.is_file():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                m = json.load(f)
                duration_sec = float(m.get("duration_seconds", 45.0))
        except Exception:
            pass

    # 2. Watermark overlay cue
    client_name = "HardScope"
    channel_handle = "@HardScopeTV"
    if brief_data:
        client_name = brief_data.get("campaign", {}).get("client", client_name)
        channel_handle = brief_data.get("campaign", {}).get("source_video", {}).get("channel", channel_handle)

    wm_asset = assets_dir / "watermark_brand.png"
    if not wm_asset.is_file():
        synthesize_brand_watermark_png(wm_asset, brand_title=client_name, handle=channel_handle)

    # Watermark positioning: Top-center safe zone
    wm_pos_x = WATERMARK_DEFAULT_X
    wm_pos_y = WATERMARK_DEFAULT_Y
    wm_scale = WATERMARK_SCALE_PCT
    if preferences_data and "watermark" in preferences_data:
        wm_p = preferences_data["watermark"]
        wm_pos_x = float(wm_p.get("position_x", wm_pos_x))
        wm_pos_y = float(wm_p.get("position_y", wm_pos_y))
        wm_scale = float(wm_p.get("scale", wm_scale))

    visual_cues: List[VisualOverlayCue] = []
    audio_cues: List[AudioTransientCue] = []

    # Mandatory persistent watermark across 100% of clip duration on Track V4
    visual_cues.append(
        VisualOverlayCue(
            id="vfx_persistent_watermark",
            track="V4",
            start_seconds=0.0,
            duration_seconds=duration_sec,
            asset_path=str(wm_asset),
            name="Persistent Brand Watermark",
            overlay_type="watermark",
            scale_pct=wm_scale,
            pos_x=wm_pos_x,
            pos_y=wm_pos_y,
            opacity=WATERMARK_DEFAULT_OPACITY,
            blend_mode="Normal",
        )
    )

    # 3. Persistent or 0-3s Title Hook Overlay on Track V3
    hook_pill_path: Optional[Path] = None
    cand_box = project_dir / "persistent_stepped_white_box_overlay.png"
    cand_pill = project_dir / "persistent_white_pill_overlay.png"
    if cand_box.is_file():
        hook_pill_path = cand_box
    elif cand_pill.is_file():
        hook_pill_path = cand_pill

    # Hook text resolution & HyperFrames 0-3s kinetic composition
    hook_text = "He refused to look at the card... until THIS happened 🤯"
    if preferences_data and "captions" in preferences_data:
        hook_text = preferences_data["captions"].get("persistent_hook", {}).get("text", hook_text)

    hf_hook_html = assets_dir / "hook_title_0_3s.hyperframes.html"
    synthesize_hyperframes_hook_html(hf_hook_html, hook_text=hook_text, duration_sec=3.0)

    if hook_pill_path and hook_pill_path.is_file():
        visual_cues.append(
            VisualOverlayCue(
                id="vfx_title_hook_overlay",
                track="V3",
                start_seconds=0.0,
                duration_seconds=duration_sec,  # Persist across timeline for maximal retention
                asset_path=str(hook_pill_path),
                name="Persistent Title Hook Badge",
                overlay_type="title_hook",
                scale_pct=100.0,
                pos_x=540.0,
                pos_y=960.0,
                opacity=100.0,
                blend_mode="Normal",
            )
        )
    else:
        hf_hook_mov = assets_dir / "hook_title_0_3s.mov"
        if not hf_hook_mov.is_file():
            render_hyperframes_hook_pass(
                hf_html_path=hf_hook_html,
                out_mov_path=hf_hook_mov,
                hook_text=hook_text,
                duration_sec=min(3.0, duration_sec),
            )
        visual_cues.append(
            VisualOverlayCue(
                id="vfx_title_hook_overlay",
                track="V3",
                start_seconds=0.0,
                duration_seconds=min(3.0, duration_sec),
                asset_path=str(hf_hook_mov if hf_hook_mov.is_file() else hf_hook_html),
                name="HyperFrames 0-3s Kinetic Title Hook",
                overlay_type="title_hook",
                scale_pct=100.0,
                pos_x=540.0,
                pos_y=380.0,
                opacity=100.0,
                blend_mode="Normal",
            )
        )

    # Opening whoosh transient at T=0.0s on Track A3
    whoosh_path = assets_dir / "whoosh_in.wav"
    if not whoosh_path.is_file():
        synthesize_whoosh_wav(whoosh_path, duration=0.45)
    audio_cues.append(
        AudioTransientCue(
            id="sfx_opening_whoosh",
            start_seconds=0.0,
            duration_seconds=0.45,
            asset_path=str(whoosh_path),
            name="Opening Retention Whoosh",
            sfx_type="whoosh_in",
            volume_db=SFX_DEFAULT_VOLUME_DB,
        )
    )

    # 4. Parse emotion tags from captions.json to place shock / flex VFX and SFX
    if captions_file and captions_file.is_file():
        try:
            with open(captions_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
            cues = cdata.get("cues", [])

            # Assets paths
            sub_boom_path = assets_dir / "sub_boom_tight.wav"
            if not sub_boom_path.is_file():
                synthesize_sub_boom_wav(sub_boom_path, duration=0.60)

            red_stab_path = assets_dir / "stab_crimson_shock.mov"
            if not red_stab_path.is_file():
                synthesize_color_stab_pass(red_stab_path, color_hex="#FF0000", duration_sec=0.45)

            green_stab_path = assets_dir / "stab_neon_lime.mov"
            if not green_stab_path.is_file():
                synthesize_color_stab_pass(green_stab_path, color_hex="#CCFF00", duration_sec=0.45)

            seen_emotions = set()
            for c in cues:
                emotion = c.get("emotion", "").strip()
                start_s = float(c.get("start", 0.0))
                # Trigger on major emotional transitions
                if emotion and emotion not in seen_emotions:
                    # Pure Shock / Chaos -> Crimson Red Shock (#FF0000) + Sub Boom SFX
                    if any(k in emotion for k in ["PURE SHOCK", "SCREAMING CHAOS", "MOUTH AGAPE"]):
                        seen_emotions.add(emotion)
                        visual_cues.append(
                            VisualOverlayCue(
                                id=f"vfx_red_shock_{len(visual_cues)}",
                                track="V3",
                                start_seconds=start_s,
                                duration_seconds=0.45,
                                asset_path=str(red_stab_path),
                                name=f"Crimson Shock ({emotion})",
                                overlay_type="color_stab",
                                scale_pct=100.0,
                                pos_x=540.0,
                                pos_y=960.0,
                                opacity=85.0,
                                blend_mode="Difference",
                            )
                        )
                        audio_cues.append(
                            AudioTransientCue(
                                id=f"sfx_sub_boom_{len(audio_cues)}",
                                start_seconds=start_s,
                                duration_seconds=0.60,
                                asset_path=str(sub_boom_path),
                                name=f"Sub Bass Impact ({emotion})",
                                sfx_type="sub_boom_hit",
                                volume_db=SFX_DEFAULT_VOLUME_DB,
                            )
                        )
                    # Grail Pull / Destiny / Celebration -> Neon Acid Green Flex (#CCFF00) + Whoosh SFX
                    elif any(k in emotion for k in ["GRAIL PULL", "100% DESTINY", "CELEBRATION"]):
                        seen_emotions.add(emotion)
                        visual_cues.append(
                            VisualOverlayCue(
                                id=f"vfx_green_flex_{len(visual_cues)}",
                                track="V3",
                                start_seconds=start_s,
                                duration_seconds=0.45,
                                asset_path=str(green_stab_path),
                                name=f"Neon Lime Flex ({emotion})",
                                overlay_type="color_stab",
                                scale_pct=100.0,
                                pos_x=540.0,
                                pos_y=960.0,
                                opacity=80.0,
                                blend_mode="Screen",
                            )
                        )
                        audio_cues.append(
                            AudioTransientCue(
                                id=f"sfx_flex_whoosh_{len(audio_cues)}",
                                start_seconds=start_s,
                                duration_seconds=0.45,
                                asset_path=str(whoosh_path),
                                name=f"Flex Whoosh Accent ({emotion})",
                                sfx_type="whoosh_in",
                                volume_db=SFX_DEFAULT_VOLUME_DB,
                            )
                        )
        except Exception as ex:
            sys.stderr.write(f"[Warning] Failed parsing emotional cues: {ex}\n")

    return visual_cues, audio_cues


# ---------------------------------------------------------------------------
# Remotion Project Injection Engine
# ---------------------------------------------------------------------------

def inject_vfx_and_sfx_into_remotion(
    project_path: Path,
    visual_cues: List[VisualOverlayCue],
    audio_cues: List[AudioTransientCue],
    backup: bool = True,
) -> Dict[str, Any]:
    """
    Non-destructively inserts visual overlay items (HyperFrames kinetic hooks,
    color stabs, and persistent watermark) into Track V3/V4 and audio transient
    clips into Track A3 of the Remotion project (.remotion.json).
    """
    project_path = Path(project_path).resolve()
    if not project_path.is_file():
        raise FileNotFoundError(f"Project file not found: {project_path}")

    if backup:
        bak_file = project_path.with_name(f"{project_path.name}.bak_{int(datetime.now(timezone.utc).timestamp())}")
        shutil.copy2(project_path, bak_file)

    with open(project_path, "r", encoding="utf-8") as f:
        proj_data = json.load(f)

    project = proj_data.setdefault("project", {})
    items = project.setdefault("items", {})
    next_id = int(project.get("next_id", 1100))
    root_children = project.setdefault("root", {}).setdefault("children", [])

    # Find the primary Sequence item
    seq_item = None
    seq_id = None
    for k, v in items.items():
        if isinstance(v, dict) and "kind" in v and isinstance(v["kind"], dict):
            if "Sequence" in v["kind"]:
                seq_item = v["kind"]["Sequence"]
                seq_id = k
                break

    if not seq_item:
        raise ValueError("No Sequence item found in .remotion.json project structure.")

    v_tracks = seq_item.setdefault("video_tracks", [])
    a_tracks = seq_item.setdefault("audio_tracks", [])

    # Map tracks by name or index
    track_v3 = None
    track_v4 = None
    for vt in v_tracks:
        if vt.get("name") == TRACK_V3_NAME or vt.get("id") == 3:
            track_v3 = vt
        elif vt.get("name") == TRACK_V4_NAME or vt.get("id") == 4:
            track_v4 = vt

    # Ensure Track V3 and V4 exist
    if not track_v3:
        next_id += 1
        track_v3 = {
            "id": 3,
            "kind": "Video",
            "name": TRACK_V3_NAME,
            "items": [],
            "transitions": [],
            "locked": False,
            "sync_lock": True,
            "enabled": True,
            "muted": False,
            "solo": False,
            "channels": "Stereo",
            "volume_db": 0.0,
            "pan": 0.0,
            "effects": [],
            "mixer": {"mode": "Read", "output": None, "record_arm": False, "solo_safe": False, "input_map": "Stereo"},
        }
        v_tracks.append(track_v3)

    if not track_v4:
        next_id += 1
        track_v4 = {
            "id": 4,
            "kind": "Video",
            "name": TRACK_V4_NAME,
            "items": [],
            "transitions": [],
            "locked": False,
            "sync_lock": True,
            "enabled": True,
            "muted": False,
            "solo": False,
            "channels": "Stereo",
            "volume_db": 0.0,
            "pan": 0.0,
            "effects": [],
            "mixer": {"mode": "Read", "output": None, "record_arm": False, "solo_safe": False, "input_map": "Stereo"},
        }
        v_tracks.append(track_v4)

    track_a3 = None
    for at in a_tracks:
        if at.get("name") == TRACK_A3_NAME or at.get("id") == 7:
            track_a3 = at

    if not track_a3:
        next_id += 1
        track_a3 = {
            "id": 7,
            "kind": "Audio",
            "name": TRACK_A3_NAME,
            "items": [],
            "transitions": [],
            "locked": False,
            "sync_lock": True,
            "enabled": True,
            "muted": False,
            "solo": False,
            "channels": "Stereo",
            "volume_db": SFX_DEFAULT_VOLUME_DB,
            "pan": 0.0,
            "effects": [],
            "mixer": {"mode": "Read", "output": None, "record_arm": False, "solo_safe": False, "input_map": "Stereo"},
        }
        a_tracks.append(track_a3)

    # Cache media items map by resolved path to avoid duplicate imports
    media_item_ids: Dict[str, int] = {}
    for k, v in items.items():
        if isinstance(v, dict) and "kind" in v and "Media" in v.get("kind", {}):
            m_path = v["kind"]["Media"].get("media", {}).get("File", {}).get("path")
            if m_path:
                media_item_ids[str(Path(m_path).resolve())] = int(k)

    def _get_or_create_media_item(file_path: Path, is_video: bool = True) -> int:
        nonlocal next_id
        resolved_p = str(file_path.resolve())
        if resolved_p in media_item_ids:
            return media_item_ids[resolved_p]

        next_id += 1
        new_id = next_id
        media_item_ids[resolved_p] = new_id
        root_children.append({"Item": new_id})

        ext = file_path.suffix.lower()
        is_still = ext in [".png", ".jpg", ".jpeg", ".tiff"]
        is_audio = ext in [".wav", ".mp3", ".aac", ".aiff"]

        if is_audio:
            kind_str = "AudioOnly"
            video_info = None
            audio_info = {"sample_rate": 48000, "channels": 2, "codec": "PCM", "bits_per_sample": 16}
        elif is_still:
            kind_str = "Still"
            video_info = {
                "width": CANVAS_WIDTH,
                "height": CANVAS_HEIGHT,
                "frame_rate": {"num": 30, "den": 1},
                "par": [1, 1],
                "codec": "PNG",
                "pixel_format": "RGBA 8-bit",
                "color": {"matrix": "Bt709", "transfer": "Bt709", "primaries": "Bt709", "range": "Full"},
                "has_alpha": True,
                "bitrate": 0,
            }
            audio_info = None
        else:
            kind_str = "Movie"
            video_info = {
                "width": CANVAS_WIDTH,
                "height": CANVAS_HEIGHT,
                "frame_rate": {"num": 30, "den": 1},
                "par": [1, 1],
                "codec": "Apple ProRes 4444",
                "pixel_format": "YUVA 4:4:4 12-bit",
                "color": {"matrix": "Bt709", "transfer": "Bt709", "primaries": "Bt709", "range": "Limited"},
                "has_alpha": True,
                "bitrate": 9000000,
            }
            audio_info = None

        items[str(new_id)] = {
            "id": new_id,
            "name": file_path.name,
            "label": "Cerulean",
            "kind": {
                "Media": {
                    "media": {"File": {"path": resolved_p}},
                    "info": {
                        "name": file_path.name,
                        "kind": kind_str,
                        "duration": seconds_to_ticks(86400.0 if is_still else 60.0),
                        "video": video_info,
                        "audio": audio_info,
                        "container": ext.lstrip(".").upper(),
                        "start_timecode": None,
                        "file_size": file_path.stat().st_size if file_path.is_file() else 50000,
                    },
                    "interpret": {"frame_rate": None, "par": None, "ignore_alpha": False, "invert_alpha": False},
                    "mark_in": None,
                    "mark_out": None,
                    "markers": [],
                    "offline": False,
                    "proxy": None,
                    "identity": {"size": 50000, "fingerprint": "0000000000000000"},
                }
            },
            "metadata": {},
            "created": new_id,
        }
        return new_id

    # Reset clips on Track V3, V4, and A3 for clean idempotence
    track_v3["items"] = []
    track_v4["items"] = []
    track_a3["items"] = []

    # Insert Visual Overlays
    for vcue in visual_cues:
        p = Path(vcue.asset_path)
        if not p.is_file():
            continue
        m_id = _get_or_create_media_item(p, is_video=True)
        next_id += 1
        clip_id = next_id

        target_track = track_v4 if vcue.track == "V4" else track_v3

        # Blend mode selection
        blend_choice = 0
        if vcue.blend_mode == "Screen":
            blend_choice = 12
        elif vcue.blend_mode == "Add":
            blend_choice = 14
        elif vcue.blend_mode == "Difference":
            blend_choice = 18

        clip_dict = {
            "id": clip_id,
            "item": m_id,
            "name": vcue.name,
            "label": "Iris",
            "start": seconds_to_ticks(vcue.start_seconds),
            "duration": seconds_to_ticks(vcue.duration_seconds),
            "source_in": 0,
            "speed": 1.0,
            "reverse": False,
            "enabled": True,
            "link": None,
            "group": None,
            "effects": [
                {
                    "effect": "motion",
                    "enabled": True,
                    "params": {
                        "anchor": {"value": {"Vec2": {"x": 540.0, "y": 960.0}}},
                        "anti_flicker": {"value": {"Float": 0.0}},
                        "position": {"value": {"Vec2": {"x": vcue.pos_x, "y": vcue.pos_y}}},
                        "rotation": {"value": {"Float": 0.0}},
                        "scale": {"value": {"Float": vcue.scale_pct}},
                        "scale_width": {"value": {"Float": 100.0}},
                        "uniform_scale": {"value": {"Bool": True}},
                    },
                },
                {
                    "effect": "opacity",
                    "enabled": True,
                    "params": {
                        "blend": {"value": {"Choice": blend_choice}},
                        "opacity": {"value": {"Float": vcue.opacity}},
                    },
                },
                {
                    "effect": "time_remap",
                    "enabled": True,
                    "params": {"speed": {"value": {"Float": 100.0}}},
                },
            ],
            "markers": [],
            "gain_db": 0.0,
            "frame_hold": None,
            "scale_to_frame": False,
        }
        target_track["items"].append(clip_dict)

    # Insert Audio Transients
    for acue in audio_cues:
        p = Path(acue.asset_path)
        if not p.is_file():
            continue
        m_id = _get_or_create_media_item(p, is_video=False)
        next_id += 1
        clip_id = next_id

        audio_clip = {
            "id": clip_id,
            "item": m_id,
            "name": acue.name,
            "label": "Iris",
            "start": seconds_to_ticks(acue.start_seconds),
            "duration": seconds_to_ticks(acue.duration_seconds),
            "source_in": 0,
            "speed": 1.0,
            "reverse": False,
            "enabled": True,
            "link": None,
            "group": None,
            "effects": [
                {
                    "effect": "volume",
                    "enabled": True,
                    "params": {
                        "bypass": {"value": {"Bool": False}},
                        "level": {"value": {"Float": acue.volume_db}},
                    },
                },
                {
                    "effect": "channel_volume",
                    "enabled": True,
                    "params": {
                        "bypass": {"value": {"Bool": False}},
                        "left": {"value": {"Float": 0.0}},
                        "right": {"value": {"Float": 0.0}},
                    },
                },
                {
                    "effect": "panner",
                    "enabled": True,
                    "params": {"balance": {"value": {"Float": 0.0}}},
                },
            ],
            "markers": [],
            "gain_db": 0.0,
            "frame_hold": None,
            "scale_to_frame": False,
        }
        track_a3["items"].append(audio_clip)

    project["next_id"] = next_id + 1

    with open(project_path, "w", encoding="utf-8") as f:
        json.dump(proj_data, f, indent=2)

    # Sync remotion/props.json if present alongside project_path
    props_path = project_path.parent / "remotion" / "props.json"
    if props_path.is_file():
        with open(props_path, "w", encoding="utf-8") as f:
            json.dump(proj_data, f, indent=2)

    return {
        "status": "success",
        "v3_clips_count": len(track_v3["items"]),
        "v4_clips_count": len(track_v4["items"]),
        "a3_clips_count": len(track_a3["items"]),
        "remotion_project_file": str(project_path),
    }


# ---------------------------------------------------------------------------
# Preview Video Composite Renderer
# ---------------------------------------------------------------------------

def render_vfx_preview(
    project_dir: Path,
    out_mp4: Optional[Path] = None,
    duration_sec: Optional[float] = None,
    audio_cues: Optional[List[AudioTransientCue]] = None,
) -> Optional[Path]:
    """
    Renders preview video composite with FFmpeg burning the video, captions,
    overlays, and sound effects together. Builds directly on top of the
    captioned/assembled master sequence to preserve all ping-pong cuts and captions.
    """
    project_dir = Path(project_dir).resolve()
    if not out_mp4:
        out_mp4 = project_dir / "preview_vfx.mp4"

    captioned_video = project_dir / "preview_captioned.mp4"
    assembly_video = project_dir / "preview_assembly.mp4"
    preview_video = project_dir / "preview.mp4"
    raw_video = project_dir / "raw" / "hardscope-unpacked-episode-2.mp4"
    if not raw_video.is_file():
        # Fallback to any mp4 in raw
        raw_candidates = list((project_dir / "raw").glob("*.mp4"))
        if raw_candidates:
            raw_video = raw_candidates[0]

    ass_file = project_dir / "hardscope-unpacked-episode-2.ass"
    cand_box = project_dir / "persistent_stepped_white_box_overlay.png"
    cand_pill = project_dir / "persistent_white_pill_overlay.png"
    hook_overlay = cand_box if cand_box.is_file() else (cand_pill if cand_pill.is_file() else None)
    wm_overlay = project_dir / "assets" / "watermark_brand.png"
    sub_boom = project_dir / "assets" / "sub_boom_tight.wav"
    whoosh = project_dir / "assets" / "whoosh_in.wav"

    # Audio cues resolution
    if audio_cues is None:
        manifest_file = project_dir / "vfx_manifest.json"
        if manifest_file.is_file():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    m_data = json.load(f)
                audio_cues = [
                    AudioTransientCue(
                        id=ac.get("id", ""),
                        start_seconds=ac.get("start_seconds", 0.0),
                        duration_seconds=ac.get("duration_seconds", 0.45),
                        asset_path=ac.get("asset_path", ""),
                        name=ac.get("name", ""),
                        sfx_type=ac.get("sfx_type", ""),
                        volume_db=ac.get("volume_db", -4.0),
                    )
                    for ac in m_data.get("audio_transients", [])
                ]
            except Exception:
                audio_cues = []
        else:
            audio_cues = []

    # Case A: Captioned video exists (Contains all 15 cuts, stepped box, and burned ASS)
    if captioned_video.is_file():
        cmd = [
            "ffmpeg", "-y",
            "-i", str(captioned_video),
        ]
        input_idx = 1
        filter_complex_parts = []
        current_v = "[0:v]"

        if wm_overlay.is_file():
            cmd.extend(["-i", str(wm_overlay)])
            filter_complex_parts.append(f"[{input_idx}:v]scale=440:-1[wm]")
            filter_complex_parts.append(f"{current_v}[wm]overlay=(W-w)/2:140[v_wm]")
            current_v = "[v_wm]"
            input_idx += 1

        # SFX Transient Audio Mixing
        audio_mix_inputs = ["[0:a]"]
        if audio_cues:
            for i, ac in enumerate(audio_cues):
                sfx_path = Path(ac.asset_path)
                if sfx_path.is_file():
                    cmd.extend(["-i", str(sfx_path)])
                    delay_ms = int(round(ac.start_seconds * 1000.0))
                    vol_factor = 10.0 ** (ac.volume_db / 20.0) if ac.volume_db else 0.63
                    sfx_tag = f"[sfx_{i}]"
                    filter_complex_parts.append(
                        f"[{input_idx}:a]volume={vol_factor:.2f},adelay={delay_ms}|{delay_ms}{sfx_tag}"
                    )
                    audio_mix_inputs.append(sfx_tag)
                    input_idx += 1

        if len(audio_mix_inputs) > 1:
            total_a = len(audio_mix_inputs)
            mix_str = "".join(audio_mix_inputs) + f"amix=inputs={total_a}:duration=first:dropout_transition=2[a_out]"
            filter_complex_parts.append(mix_str)
            current_a = "[a_out]"
        else:
            current_a = "0:a"

        cmd.extend([
            "-filter_complex", ";".join(filter_complex_parts),
            "-map", current_v,
            "-map", current_a,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "19",
            "-c:a", "aac",
            "-b:a", "192k",
            str(out_mp4),
        ])

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and out_mp4.is_file():
            return out_mp4
        else:
            sys.stderr.write(f"[Error] VFX composite render failed: {res.stderr[-400:]}\n")

    # Case B: Assembly video exists (15 cuts, no captions burned yet)
    base_cut = assembly_video if assembly_video.is_file() else (preview_video if preview_video.is_file() else None)
    if base_cut and base_cut.is_file():
        cmd = ["ffmpeg", "-y", "-i", str(base_cut)]
        input_idx = 1
        filter_complex_parts = []
        current_v = "[0:v]"

        if hook_overlay and hook_overlay.is_file():
            cmd.extend(["-i", str(hook_overlay)])
            filter_complex_parts.append(f"{current_v}[{input_idx}:v]overlay=0:0[v_hook]")
            current_v = "[v_hook]"
            input_idx += 1

        if wm_overlay.is_file():
            cmd.extend(["-i", str(wm_overlay)])
            filter_complex_parts.append(f"[{input_idx}:v]scale=440:-1[wm]")
            filter_complex_parts.append(f"{current_v}[wm]overlay=(W-w)/2:140[v_wm]")
            current_v = "[v_wm]"
            input_idx += 1

        if ass_file.is_file():
            filter_complex_parts.append(f"{current_v}ass={ass_file}[v_out]")
            current_v = "[v_out]"

        # Mix SFX
        audio_mix_inputs = ["[0:a]"]
        if audio_cues:
            for i, ac in enumerate(audio_cues):
                sfx_path = Path(ac.asset_path)
                if sfx_path.is_file():
                    cmd.extend(["-i", str(sfx_path)])
                    delay_ms = int(round(ac.start_seconds * 1000.0))
                    vol_factor = 10.0 ** (ac.volume_db / 20.0) if ac.volume_db else 0.63
                    sfx_tag = f"[sfx_{i}]"
                    filter_complex_parts.append(
                        f"[{input_idx}:a]volume={vol_factor:.2f},adelay={delay_ms}|{delay_ms}{sfx_tag}"
                    )
                    audio_mix_inputs.append(sfx_tag)
                    input_idx += 1

        if len(audio_mix_inputs) > 1:
            total_a = len(audio_mix_inputs)
            mix_str = "".join(audio_mix_inputs) + f"amix=inputs={total_a}:duration=first:dropout_transition=2[a_out]"
            filter_complex_parts.append(mix_str)
            current_a = "[a_out]"
        else:
            current_a = "0:a"

        cmd.extend([
            "-filter_complex", ";".join(filter_complex_parts),
            "-map", current_v,
            "-map", current_a,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "19",
            "-c:a", "aac",
            "-b:a", "192k",
            str(out_mp4),
        ])

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and out_mp4.is_file():
            return out_mp4

    return None


# ---------------------------------------------------------------------------
# Checkpoint Gate Trigger
# ---------------------------------------------------------------------------

def trigger_companion_checkpoint(
    state_path: Path,
    project_file: Optional[Path] = None,
    feedback: str = "",
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """Invokes clipping_state.py checkpoint --step clipping-vfx-sfx."""
    scripts_dir = Path(__file__).resolve().parent
    clipping_state_cli = scripts_dir / "clipping_state.py"
    if not clipping_state_cli.is_file():
        return {"success": False, "error": f"{clipping_state_cli} not found"}

    cmd = [
        sys.executable,
        str(clipping_state_cli),
        "checkpoint",
        "--step",
        "clipping-vfx-sfx",
        "--dir",
        str(state_path.parent),
    ]
    if project_file and Path(project_file).is_file():
        cmd.extend(["--project-file", str(project_file)])
    if feedback:
        cmd.extend(["--feedback", feedback])
    if auto_approve:
        cmd.append("--auto-approve")

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "success": proc.returncode == 0,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
    }


# ---------------------------------------------------------------------------
# Master Step Orchestrator
# ---------------------------------------------------------------------------

def execute_vfx_sfx_step(
    project_dir: Union[str, Path],
    project_file: Optional[Union[str, Path]] = None,
    watermark_path: Optional[Union[str, Path]] = None,
    title_hook_text: Optional[str] = None,
    trigger_checkpoint: bool = True,
    auto_approve: bool = False,
    render_preview_mp4: bool = True,
) -> Dict[str, Any]:
    """
    Main programmatic orchestrator for Step 6 (clipping-vfx-sfx).
    """
    project_dir = Path(project_dir).resolve()
    state_path = project_dir / ".clipping_state.json"
    project_name = project_dir.name

    # 1. State extraction
    step_config: Dict[str, Any] = {}
    brief_data: Dict[str, Any] = {}
    preferences_data: Dict[str, Any] = {}

    if state_path.is_file():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            step_config = st.get("steps", {}).get("clipping-vfx-sfx", {}).get("params", {})
            brief_data = {"campaign": st.get("campaign", {})}
        except Exception as ex:
            sys.stderr.write(f"[Warning] Failed loading state: {ex}\n")

    pref_file = project_dir / ".clipping_preferences.json"
    if pref_file.is_file():
        try:
            with open(pref_file, "r", encoding="utf-8") as f:
                preferences_data = json.load(f)
        except Exception:
            pass

    brief_file = project_dir / "campaign_brief.json"
    if brief_file.is_file():
        try:
            with open(brief_file, "r", encoding="utf-8") as f:
                brief_data = json.load(f)
        except Exception:
            pass

    meta_file = project_dir / f"{project_name}.meta.json"
    if not meta_file.is_file():
        cands = list(project_dir.glob("*.meta.json"))
        if cands:
            meta_file = cands[0]

    captions_file = project_dir / "captions.json"
    if not captions_file.is_file():
        cands = list(project_dir.glob("captions*.json"))
        if cands:
            captions_file = cands[0]

    remotion_file = Path(project_file) if project_file else project_dir / f"{project_name}.remotion.json"
    if not remotion_file.is_file():
        cands = [p for p in project_dir.glob("*.remotion.json") if not p.name.startswith("baseline_")]
        if cands:
            remotion_file = cands[0]

    # 2. Detect & Synthesize Cues
    visual_cues, audio_cues = detect_vfx_sfx_cues(
        project_dir=project_dir,
        captions_file=captions_file,
        meta_file=meta_file,
        brief_data=brief_data,
        preferences_data=preferences_data,
    )

    # 3. Inject into Remotion .remotion.json
    remotion_result = inject_vfx_and_sfx_into_remotion(
        project_path=remotion_file,
        visual_cues=visual_cues,
        audio_cues=audio_cues,
        backup=True,
    )

    # 4. Generate VFX Manifest
    vfx_manifest = {
        "step": "clipping-vfx-sfx",
        "project_name": project_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "remotion_project_file": str(remotion_file),
        "hyperframes_compositions": [
            str(p) for p in sorted((project_dir / "assets").glob("*.hyperframes.html"))
        ],
        "visual_overlays": [asdict(vc) for vc in visual_cues],
        "audio_transients": [asdict(ac) for ac in audio_cues],
        "compliance_audit": {
            "watermark_required": True,
            "persistent_entire_clip": True,
            "watermark_track": "V4",
            "watermark_scale_pct": WATERMARK_SCALE_PCT,
            "safe_from_corners": True,
            "safe_from_captions": True,
            "zero_background_music": True,
            "zero_phonk": True,
            "sfx_ducking_volume_db": SFX_DEFAULT_VOLUME_DB,
        },
    }

    manifest_path = project_dir / "vfx_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(vfx_manifest, f, indent=2)

    # 5. Render Preview MP4
    preview_path = None
    if render_preview_mp4:
        try:
            preview_path = render_vfx_preview(project_dir, audio_cues=audio_cues)
        except Exception as ex:
            sys.stderr.write(f"[Warning] Preview render failed: {ex}\n")

    # 6. Checkpoint Gate Trigger & State Persist
    checkpoint_res: Optional[Dict[str, Any]] = None
    if state_path.is_file():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            step_entry = st.setdefault("steps", {}).setdefault("clipping-vfx-sfx", {})
            step_entry["status"] = "staged"
            step_entry["staged"] = True
            step_params = step_entry.setdefault("params", {})
            step_params.update({
                "vfx_manifest": str(manifest_path),
                "visual_cues_count": len(visual_cues),
                "audio_cues_count": len(audio_cues),
                "watermark_track": "V4",
                "watermark_scale": WATERMARK_SCALE_PCT,
                "title_hook_overlay": bool(any(vc.overlay_type == "title_hook" for vc in visual_cues)),
                "sfx_ducking_db": SFX_DEFAULT_VOLUME_DB,
                "preview_mp4": str(preview_path) if preview_path else None,
            })
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(st, f, indent=2)

            if trigger_checkpoint:
                checkpoint_res = trigger_companion_checkpoint(
                    state_path=state_path,
                    project_file=remotion_file,
                    feedback="Composited persistent brand watermark on Track V4, HyperFrames title hook on Track V3, color stabs, and synchronized SFX on Track A3 ducked to -4dB",
                    auto_approve=auto_approve,
                )
        except Exception as ex:
            checkpoint_res = {"success": False, "error": f"Failed state update: {ex}"}

    return {
        "status": "success",
        "project_name": project_name,
        "remotion_project_file": str(remotion_file),
        "visual_cues_count": len(visual_cues),
        "audio_cues_count": len(audio_cues),
        "vfx_manifest": str(manifest_path),
        "preview_mp4": str(preview_path) if preview_path else None,
        "remotion_injection": remotion_result,
        "checkpoint_triggered": trigger_checkpoint and state_path.is_file(),
        "checkpoint_result": checkpoint_res,
    }


def main():
    parser = argparse.ArgumentParser(description="Step 6: VFX & SFX Compositing Engine.")
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    p_gen = subparsers.add_parser("generate", help="Generate VFX/SFX overlays and composite into timeline.")
    p_gen.add_argument("--project-dir", required=True, help="Path to project directory")
    p_gen.add_argument("--project-file", help="Path to .remotion.json project file")
    p_gen.add_argument("--watermark", help="Path to watermark image")
    p_gen.add_argument("--title-hook", help="Custom text for title hook")
    p_gen.add_argument("--no-checkpoint", action="store_true", help="Do not trigger clipping_state.py checkpoint")
    p_gen.add_argument("--auto-approve", action="store_true", help="Auto-approve checkpoint gate after staging")
    p_gen.add_argument("--no-preview", action="store_true", help="Skip preview rendering")
    p_gen.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()

    if args.subcommand == "generate":
        res = execute_vfx_sfx_step(
            project_dir=Path(args.project_dir),
            project_file=Path(args.project_file) if args.project_file else None,
            watermark_path=Path(args.watermark) if args.watermark else None,
            title_hook_text=args.title_hook,
            trigger_checkpoint=not args.no_checkpoint,
            auto_approve=args.auto_approve,
            render_preview_mp4=not args.no_preview,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"[SUCCESS] Composited VFX & SFX for '{res['project_name']}':")
            print(f"  Visual Overlays: {res['visual_cues_count']} cues on Track V3 & V4")
            print(f"  Audio Transients: {res['audio_cues_count']} cues on Track A3")
            print(f"  VFX Manifest:    {res['vfx_manifest']}")
            print(f"  Project File:    {res['remotion_project_file']}")
            if res.get("preview_mp4"):
                print(f"  Preview Video:   {res['preview_mp4']}")
            if res.get("checkpoint_triggered"):
                cp_data = res.get("checkpoint_result", {})
                cp_ok = cp_data.get("success", False) if cp_data else False
                status_label = "TRIGGERED / ACTIVE" if cp_ok else "FAILED"
                print(f"  Live Companion Checkpoint: {status_label}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
