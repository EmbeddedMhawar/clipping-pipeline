#!/usr/bin/env python3
"""
scripts/clipping_assembly.py

Native 9:16 Vertical Video Assembly Engine for the Antigravity Short-Form
Clipping Pipeline.
Generates production-grade Storyteller FilmCraft (.fcproj) project files
using declarative in-memory construction (FcprojBuilder).
Zero external runtime dependencies (Python standard library only).

Primary References:
- docs/research/fcproj-assembly-spec.md
- scripts/clipping_state.py
- scripts/gui_companion.py
- GLOSSARY.md ("Live GUI Companion", "Feedback Checkpoint", "Preference Store")
- GitHub Issue #29
"""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

# High-precision time base (FilmCraft integer ticks per second)
TICKS_PER_SEC: int = 254_016_000_000

# Canonical Track Names (matching clipping_preferences.py)
TRACK_V1_NAME: str = "Blurred Background"
TRACK_V2_NAME: str = "Speaker Foreground"
TRACK_V3_NAME: str = "HUD & Overlays"
TRACK_V4_NAME: str = "Watermark"

TRACK_A1_NAME: str = "Dialogue"
TRACK_A2_NAME: str = "Background Music"
TRACK_A3_NAME: str = "SFX"

# Default Framing Constants
DEFAULT_CANVAS_WIDTH: int = 1080
DEFAULT_CANVAS_HEIGHT: int = 1920
DEFAULT_SRC_WIDTH: int = 1920
DEFAULT_SRC_HEIGHT: int = 1080

DEFAULT_FILL_SCALE_PCT: float = (1920.0 / 1080.0) * 100.0  # 177.77777777777777% (~177.78%)
DEFAULT_BG_SCALE_PCT: float = DEFAULT_FILL_SCALE_PCT * 1.18  # 209.77777777777777% (~209.78%)

# Speaker Ping-Pong Normalized Center Coordinates
SPEAKER_HOST_XC: float = 0.25
SPEAKER_GUEST_XC: float = 0.75
SPEAKER_CENTER_XC: float = 0.50
SPEAKER_DEFAULT_YC: float = 0.50

# Dead Air & Protection Buffers
DEFAULT_SILENCE_THRESHOLD_SEC: float = 0.40
DEFAULT_CONSONANT_BUFFER_SEC: float = 0.08
MIN_CUT_DURATION_SEC: float = 0.04

# Watermark Default Transform
WATERMARK_SCALE_PCT: float = 28.0
WATERMARK_POS_X: float = 540.0
WATERMARK_POS_Y: float = 280.0

# State filename
STATE_FILENAME: str = ".clipping_state.json"


def seconds_to_ticks(seconds: float) -> int:
    """Convert floating-point seconds to nearest discrete FilmCraft ticks."""
    return int(round(seconds * TICKS_PER_SEC))


def ticks_to_seconds(ticks: int) -> float:
    """Convert discrete FilmCraft ticks to floating-point seconds."""
    return float(ticks) / TICKS_PER_SEC


def frames_to_ticks(frames: int, fps_num: int, fps_den: int = 1) -> int:
    """Convert frame count at rational frame rate to exact ticks."""
    return int(round(frames * (TICKS_PER_SEC * fps_den / fps_num)))


@dataclass
class SubCut:
    """Represents a discrete speech or video sub-cut to assemble."""
    start: float  # Source in-point in seconds
    end: float    # Source out-point in seconds
    x_center: float = SPEAKER_CENTER_XC
    y_center: float = SPEAKER_DEFAULT_YC
    punch_in: float = 1.00
    speaker: str = "center"
    effective_end: Optional[float] = None  # End time after dead air pruning & consonant buffer

    def __post_init__(self):
        # Automatically align x_center with speaker role if x_center is at default
        if self.x_center == SPEAKER_CENTER_XC:
            sp = self.speaker.lower()
            if sp == "host":
                self.x_center = SPEAKER_HOST_XC
            elif sp == "guest":
                self.x_center = SPEAKER_GUEST_XC


@dataclass
class AssemblyConfig:
    """Configuration options for FcprojBuilder."""
    project_name: str
    output_path: Path
    media_path: Path
    watermark_path: Optional[Path] = None
    bgm_path: Optional[Path] = None
    bgm_volume_db: float = -18.0
    sfx_volume_db: float = -4.0
    src_width: int = DEFAULT_SRC_WIDTH
    src_height: int = DEFAULT_SRC_HEIGHT
    canvas_width: int = DEFAULT_CANVAS_WIDTH
    canvas_height: int = DEFAULT_CANVAS_HEIGHT
    fps_num: int = 30
    fps_den: int = 1
    sub_cuts: List[SubCut] = field(default_factory=list)
    consonant_buffer: float = DEFAULT_CONSONANT_BUFFER_SEC
    silence_threshold: float = DEFAULT_SILENCE_THRESHOLD_SEC


def prune_dead_air(
    cuts: List[SubCut],
    silence_threshold: float = DEFAULT_SILENCE_THRESHOLD_SEC,
    consonant_buffer: float = DEFAULT_CONSONANT_BUFFER_SEC,
    min_cut_duration: float = MIN_CUT_DURATION_SEC,
) -> List[SubCut]:
    """Prunes dead air gaps (> silence_threshold) while applying consonant buffers.

    Rules:
    1. Silence gaps between consecutive spoken segments > silence_threshold (0.40s)
       are excised.
    2. Every cut receives up to consonant_buffer (0.08s) tail padding to prevent
       clipping word-ending consonants.
    3. Boundary collision guard: padding must never overrun into subsequent spoken
       start time: pad = min(consonant_buffer, max(0.0, next_start - cut.end - 0.01)).
    4. Enforces min_cut_duration (0.04s, approx 1 frame).
    """
    if not cuts:
        return []

    sorted_cuts = sorted(cuts, key=lambda c: c.start)
    pruned: List[SubCut] = []

    for i, cut in enumerate(sorted_cuts):
        start_sec = cut.start
        end_sec = cut.end

        # Calculate safe tail buffer
        pad = consonant_buffer
        if i + 1 < len(sorted_cuts):
            next_start = sorted_cuts[i + 1].start
            # Collision guard: leave at least 10ms gap before next start
            max_pad = max(0.0, next_start - end_sec - 0.01)
            pad = min(pad, max_pad)

        effective_end = end_sec + pad
        dur_sec = max(min_cut_duration, effective_end - start_sec)
        effective_end = start_sec + dur_sec

        pruned_cut = SubCut(
            start=start_sec,
            end=end_sec,
            x_center=cut.x_center,
            y_center=cut.y_center,
            punch_in=cut.punch_in,
            speaker=cut.speaker,
            effective_end=effective_end,
        )
        pruned.append(pruned_cut)

    return pruned


class FcprojBuilder:
    """In-memory declarative builder for Storyteller FilmCraft 0.4.0 (.fcproj) files.

    Generates valid schema_version 12 JSON projects with a broadcast-ready 4V / 3A track stack.
    """

    def __init__(self, config: AssemblyConfig):
        self.config = config
        self.next_id = 1
        self.items: Dict[str, Any] = {}
        self.root_children: List[Dict[str, int]] = []

        self.canvas_w = float(config.canvas_width)
        self.canvas_h = float(config.canvas_height)
        self.src_w = float(config.src_width)
        self.src_h = float(config.src_height)

        # Scale formulas
        self.fill_scale = (self.canvas_h / self.src_h) * 100.0  # 177.77777777777777%
        self.bg_scale = self.fill_scale * 1.18  # 209.77777777777777%

    def _alloc_id(self) -> int:
        cur = self.next_id
        self.next_id += 1
        return cur

    def _sec_to_ticks(self, s: float) -> int:
        return seconds_to_ticks(s)

    def _make_motion_effect(
        self,
        scale: float,
        anchor_x: float,
        anchor_y: float,
        pos_x: float,
        pos_y: float,
        rotation: float = 0.0,
    ) -> Dict[str, Any]:
        return {
            "effect": "motion",
            "enabled": True,
            "params": {
                "anchor": {"value": {"Vec2": {"x": anchor_x, "y": anchor_y}}},
                "anti_flicker": {"value": {"Float": 0.0}},
                "position": {"value": {"Vec2": {"x": pos_x, "y": pos_y}}},
                "rotation": {"value": {"Float": rotation}},
                "scale": {"value": {"Float": scale}},
                "scale_width": {"value": {"Float": 100.0}},
                "uniform_scale": {"value": {"Bool": True}},
            },
        }

    def _make_opacity_effect(self, opacity: float = 100.0) -> Dict[str, Any]:
        return {
            "effect": "opacity",
            "enabled": True,
            "params": {
                "blend": {"value": {"Choice": 0}},
                "opacity": {"value": {"Float": opacity}},
            },
        }

    def _make_gaussian_blur_effect(
        self, blurriness: float = 45.0, repeat_edge: bool = True
    ) -> Dict[str, Any]:
        return {
            "effect": "gaussian_blur",
            "enabled": True,
            "params": {
                "blurriness": {"value": {"Float": blurriness}},
                "dimensions": {"value": {"Choice": 0}},
                "repeat_edge": {"value": {"Bool": repeat_edge}},
            },
        }

    def _make_time_remap_effect(self, speed: float = 100.0) -> Dict[str, Any]:
        return {
            "effect": "time_remap",
            "enabled": True,
            "params": {"speed": {"value": {"Float": speed}}},
        }

    def _make_audio_volume_effects(self, level_db: float = 0.0) -> List[Dict[str, Any]]:
        return [
            {
                "effect": "volume",
                "enabled": True,
                "params": {
                    "bypass": {"value": {"Bool": False}},
                    "level": {"value": {"Float": level_db}},
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
        ]

    def build(self) -> Dict[str, Any]:
        """Constructs and returns the complete in-memory .fcproj JSON dictionary."""
        seq_id = self._alloc_id()
        media_id = self._alloc_id()

        self.root_children.append({"Item": seq_id})
        self.root_children.append({"Item": media_id})

        media_resolved = self.config.media_path.resolve()
        media_name = self.config.media_path.name

        # Primary Media Item
        self.items[str(media_id)] = {
            "id": media_id,
            "name": media_name,
            "label": "Iris",
            "kind": {
                "Media": {
                    "media": {"File": {"path": str(media_resolved)}},
                    "info": {
                        "name": media_name,
                        "kind": "Movie",
                        "duration": self._sec_to_ticks(3600.0),
                        "video": {
                            "width": self.config.src_width,
                            "height": self.config.src_height,
                            "frame_rate": {
                                "num": self.config.fps_num,
                                "den": self.config.fps_den,
                            },
                            "par": [1, 1],
                            "codec": "H.264",
                            "pixel_format": "YUV 4:2:0 8-bit",
                            "color": {
                                "matrix": "Bt709",
                                "transfer": "Bt709",
                                "primaries": "Bt709",
                                "range": "Limited",
                            },
                            "has_alpha": False,
                            "bitrate": 10000000,
                        },
                        "audio": {
                            "sample_rate": 48000,
                            "channels": 2,
                            "codec": "AAC",
                            "bits_per_sample": None,
                        },
                        "container": "MPEG-4",
                        "start_timecode": None,
                        "file_size": 100000000,
                    },
                    "interpret": {
                        "frame_rate": None,
                        "par": None,
                        "ignore_alpha": False,
                        "invert_alpha": False,
                    },
                    "mark_in": None,
                    "mark_out": None,
                    "markers": [],
                    "offline": False,
                    "proxy": None,
                    "identity": {
                        "size": 100000000,
                        "fingerprint": "0000000000000000",
                    },
                }
            },
            "metadata": {},
            "created": media_id,
        }

        # Watermark media item (if provided)
        wm_id = None
        if self.config.watermark_path:
            wm_id = self._alloc_id()
            self.root_children.append({"Item": wm_id})
            wm_resolved = self.config.watermark_path.resolve()
            wm_name = self.config.watermark_path.name
            self.items[str(wm_id)] = {
                "id": wm_id,
                "name": wm_name,
                "label": "Cerulean",
                "kind": {
                    "Media": {
                        "media": {"File": {"path": str(wm_resolved)}},
                        "info": {
                            "name": wm_name,
                            "kind": "Still",
                            "duration": self._sec_to_ticks(86400.0),
                            "video": {
                                "width": 1600,
                                "height": 533,
                                "frame_rate": {"num": 30, "den": 1},
                                "par": [1, 1],
                                "codec": "PNG",
                                "pixel_format": "RGBA 8-bit",
                                "color": {
                                    "matrix": "Bt709",
                                    "transfer": "Bt709",
                                    "primaries": "Bt709",
                                    "range": "Full",
                                },
                                "has_alpha": True,
                                "bitrate": 0,
                            },
                            "audio": None,
                            "container": "PNG",
                            "start_timecode": None,
                            "file_size": 50000,
                        },
                        "interpret": {
                            "frame_rate": None,
                            "par": None,
                            "ignore_alpha": False,
                            "invert_alpha": False,
                        },
                        "mark_in": None,
                        "mark_out": None,
                        "markers": [],
                        "offline": False,
                        "proxy": None,
                        "identity": {
                            "size": 50000,
                            "fingerprint": "0000000000000000",
                        },
                    }
                },
                "metadata": {},
                "created": wm_id,
            }

        # Background music media item (if provided)
        bgm_id = None
        if self.config.bgm_path:
            bgm_id = self._alloc_id()
            self.root_children.append({"Item": bgm_id})
            bgm_resolved = self.config.bgm_path.resolve()
            bgm_name = self.config.bgm_path.name
            self.items[str(bgm_id)] = {
                "id": bgm_id,
                "name": bgm_name,
                "label": "Iris",
                "kind": {
                    "Media": {
                        "media": {"File": {"path": str(bgm_resolved)}},
                        "info": {
                            "name": bgm_name,
                            "kind": "AudioOnly",
                            "duration": self._sec_to_ticks(3600.0),
                            "video": None,
                            "audio": {
                                "sample_rate": 48000,
                                "channels": 2,
                                "codec": "AAC",
                                "bits_per_sample": None,
                            },
                            "container": "MPEG-4",
                            "start_timecode": None,
                            "file_size": 10000000,
                        },
                        "interpret": {
                            "frame_rate": None,
                            "par": None,
                            "ignore_alpha": False,
                            "invert_alpha": False,
                        },
                        "mark_in": None,
                        "mark_out": None,
                        "markers": [],
                        "offline": False,
                        "proxy": None,
                        "identity": {
                            "size": 10000000,
                            "fingerprint": "0000000000000000",
                        },
                    }
                },
                "metadata": {},
                "created": bgm_id,
            }

        # Track stacks
        v1_items: List[Dict[str, Any]] = []
        v2_items: List[Dict[str, Any]] = []
        v3_items: List[Dict[str, Any]] = []
        v4_items: List[Dict[str, Any]] = []

        a1_items: List[Dict[str, Any]] = []
        a2_items: List[Dict[str, Any]] = []
        a3_items: List[Dict[str, Any]] = []

        timeline_time = 0

        # Process and place cuts
        cuts_to_place = self.config.sub_cuts
        if not cuts_to_place:
            # Default single cut spanning 30s
            cuts_to_place = [
                SubCut(
                    start=0.0,
                    end=30.0,
                    x_center=SPEAKER_CENTER_XC,
                    y_center=SPEAKER_DEFAULT_YC,
                    punch_in=1.0,
                )
            ]

        # Prune dead air & apply consonant tail padding
        pruned_cuts = prune_dead_air(
            cuts_to_place,
            silence_threshold=self.config.silence_threshold,
            consonant_buffer=self.config.consonant_buffer,
        )

        for cut in pruned_cuts:
            start_sec = cut.start
            end_sec = cut.effective_end if cut.effective_end is not None else cut.end
            dur_sec = max(MIN_CUT_DURATION_SEC, end_sec - start_sec)
            dur_ticks = self._sec_to_ticks(dur_sec)
            src_in_ticks = self._sec_to_ticks(start_sec)

            # Link group for synchronized V2 Foreground / A1 Dialogue
            link_id = self._alloc_id()

            # V1: Blurred Background item
            v1_clip_id = self._alloc_id()
            v1_items.append({
                "id": v1_clip_id,
                "item": media_id,
                "name": media_name,
                "label": "Iris",
                "start": timeline_time,
                "duration": dur_ticks,
                "source_in": src_in_ticks,
                "speed": 1.0,
                "reverse": False,
                "enabled": True,
                "link": None,
                "group": None,
                "effects": [
                    self._make_gaussian_blur_effect(blurriness=45.0, repeat_edge=True),
                    self._make_motion_effect(
                        scale=self.bg_scale,
                        anchor_x=self.src_w / 2.0,
                        anchor_y=self.src_h / 2.0,
                        pos_x=self.canvas_w / 2.0,
                        pos_y=self.canvas_h / 2.0,
                    ),
                    self._make_opacity_effect(opacity=40.0),
                    self._make_time_remap_effect(speed=100.0),
                ],
                "markers": [],
                "gain_db": 0.0,
                "frame_hold": None,
                "scale_to_frame": False,
            })

            # V2: Crisp Speaker Foreground item with ping-pong reframing
            v2_clip_id = self._alloc_id()
            v2_scale = self.fill_scale * cut.punch_in
            v2_anchor_x = self.src_w * cut.x_center
            v2_anchor_y = self.src_h * cut.y_center
            v2_items.append({
                "id": v2_clip_id,
                "item": media_id,
                "name": media_name,
                "label": "Iris",
                "start": timeline_time,
                "duration": dur_ticks,
                "source_in": src_in_ticks,
                "speed": 1.0,
                "reverse": False,
                "enabled": True,
                "link": link_id,
                "group": None,
                "effects": [
                    self._make_motion_effect(
                        scale=v2_scale,
                        anchor_x=v2_anchor_x,
                        anchor_y=v2_anchor_y,
                        pos_x=self.canvas_w / 2.0,
                        pos_y=self.canvas_h / 2.0,
                    ),
                    self._make_opacity_effect(opacity=100.0),
                    self._make_time_remap_effect(speed=100.0),
                ],
                "markers": [],
                "gain_db": 0.0,
                "frame_hold": None,
                "scale_to_frame": False,
            })

            # A1: Spoken Dialogue item
            a1_clip_id = self._alloc_id()
            a1_items.append({
                "id": a1_clip_id,
                "item": media_id,
                "name": media_name,
                "label": "Iris",
                "start": timeline_time,
                "duration": dur_ticks,
                "source_in": src_in_ticks,
                "speed": 1.0,
                "reverse": False,
                "enabled": True,
                "link": link_id,
                "group": None,
                "effects": self._make_audio_volume_effects(level_db=0.0),
                "markers": [],
                "gain_db": 0.0,
                "frame_hold": None,
                "scale_to_frame": False,
            })

            timeline_time += dur_ticks

        # V4: Persistent Watermark across entire timeline
        if wm_id and timeline_time > 0:
            v4_clip_id = self._alloc_id()
            v4_items.append({
                "id": v4_clip_id,
                "item": wm_id,
                "name": self.config.watermark_path.name,
                "label": "Cerulean",
                "start": 0,
                "duration": timeline_time,
                "source_in": 0,
                "speed": 1.0,
                "reverse": False,
                "enabled": True,
                "link": None,
                "group": None,
                "effects": [
                    self._make_motion_effect(
                        scale=WATERMARK_SCALE_PCT,
                        anchor_x=800.0,
                        anchor_y=266.5,
                        pos_x=WATERMARK_POS_X,
                        pos_y=WATERMARK_POS_Y,
                    ),
                    self._make_opacity_effect(opacity=100.0),
                ],
                "markers": [],
                "gain_db": 0.0,
                "frame_hold": None,
                "scale_to_frame": False,
            })

        # A2: Ducked Background Music across timeline (if provided)
        if bgm_id and timeline_time > 0:
            a2_clip_id = self._alloc_id()
            a2_items.append({
                "id": a2_clip_id,
                "item": bgm_id,
                "name": self.config.bgm_path.name,
                "label": "Iris",
                "start": 0,
                "duration": timeline_time,
                "source_in": 0,
                "speed": 1.0,
                "reverse": False,
                "enabled": True,
                "link": None,
                "group": None,
                "effects": self._make_audio_volume_effects(
                    level_db=self.config.bgm_volume_db
                ),
                "markers": [],
                "gain_db": 0.0,
                "frame_hold": None,
                "scale_to_frame": False,
            })

        def _make_track(
            track_id: int, kind: str, name: str, items: list, vol_db: float = 0.0
        ) -> Dict[str, Any]:
            return {
                "id": track_id,
                "kind": kind,
                "name": name,
                "items": items,
                "transitions": [],
                "locked": False,
                "sync_lock": True,
                "enabled": True,
                "muted": False,
                "solo": False,
                "channels": "Stereo",
                "volume_db": vol_db,
                "pan": 0.0,
                "effects": [],
                "mixer": {
                    "mode": "Read",
                    "output": None,
                    "record_arm": False,
                    "solo_safe": False,
                    "input_map": "Stereo",
                },
            }

        # Sequence Definition (4 Video / 3 Audio Track Stack)
        self.items[str(seq_id)] = {
            "id": seq_id,
            "name": self.config.project_name,
            "label": "Forest",
            "kind": {
                "Sequence": {
                    "settings": {
                        "width": int(self.canvas_w),
                        "height": int(self.canvas_h),
                        "frame_rate": {
                            "num": self.config.fps_num,
                            "den": self.config.fps_den,
                        },
                        "par": [1, 1],
                        "sample_rate": 48000,
                        "drop_frame": False,
                        "preset": f"{int(self.canvas_w)}x{int(self.canvas_h)} {self.config.fps_num}",
                        "audio_master": "Stereo",
                        "preview_codec": "ProRes 422",
                        "max_bit_depth": False,
                        "max_render_quality": False,
                        "working_space": "Rec. 709",
                        "color": {
                            "working": "Rec709",
                            "wide_gamut": False,
                            "auto_tone_map": True,
                        },
                    },
                    "video_tracks": [
                        _make_track(1, "Video", TRACK_V1_NAME, v1_items),
                        _make_track(2, "Video", TRACK_V2_NAME, v2_items),
                        _make_track(3, "Video", TRACK_V3_NAME, v3_items),
                        _make_track(4, "Video", TRACK_V4_NAME, v4_items),
                    ],
                    "audio_tracks": [
                        _make_track(5, "Audio", TRACK_A1_NAME, a1_items, 0.0),
                        _make_track(
                            6, "Audio", TRACK_A2_NAME, a2_items, self.config.bgm_volume_db
                        ),
                        _make_track(
                            7, "Audio", TRACK_A3_NAME, a3_items, self.config.sfx_volume_db
                        ),
                    ],
                    "markers": [],
                    "mark_in": None,
                    "mark_out": None,
                    "work_area": None,
                    "start_timecode": 0,
                    "master_volume_db": 0.0,
                    "master_effects": [],
                    "master_mixer": {
                        "mode": "Read",
                        "output": None,
                        "record_arm": False,
                        "solo_safe": False,
                        "input_map": "Stereo",
                    },
                    "submix_tracks": [],
                    "caption_tracks": [],
                }
            },
            "metadata": {},
            "created": seq_id,
        }

        # Project Envelope
        return {
            "format": "filmcraft.project",
            "schema_version": 12,
            "generator": "FilmCraft 0.4.0",
            "project": {
                "name": self.config.project_name,
                "settings": {
                    "renderer": "FilmCraft GPU Acceleration (wgpu)",
                    "video_display": "Timecode",
                    "audio_display_samples": True,
                    "default_still_duration": self._sec_to_ticks(5.0),
                    "default_transition_duration_frames": 24,
                    "default_audio_transition_duration": self._sec_to_ticks(1.0),
                    "ingest": {
                        "enabled": False,
                        "action": "createProxies",
                        "destination": None,
                        "preset": "",
                    },
                    "title_safe": [20.0, 20.0],
                    "action_safe": [10.0, 10.0],
                    "capture_format": "DV",
                    "scratch": {
                        "captured": None,
                        "videoPreviews": None,
                        "audioPreviews": None,
                        "autoSave": None,
                    },
                },
                "root": {
                    "id": 0,
                    "name": self.config.project_name,
                    "children": self.root_children,
                },
                "items": self.items,
                "next_id": self.next_id,
            },
            "view": {
                "open_sequences": [seq_id],
                "active_sequence": seq_id,
                "sequences": {},
            },
        }


def parse_cuts_data(raw_data: Any) -> List[SubCut]:
    """Parses arbitrary JSON cuts structures into standardized SubCut objects."""
    cuts_list: List[Dict[str, Any]] = []

    if isinstance(raw_data, list):
        cuts_list = raw_data
    elif isinstance(raw_data, dict):
        if "cuts" in raw_data and isinstance(raw_data["cuts"], list):
            cuts_list = raw_data["cuts"]
        elif "sub_cuts" in raw_data and isinstance(raw_data["sub_cuts"], list):
            cuts_list = raw_data["sub_cuts"]
        elif "segments" in raw_data and isinstance(raw_data["segments"], list):
            cuts_list = raw_data["segments"]
        elif "hook" in raw_data and isinstance(raw_data["hook"], dict):
            cuts_list = [raw_data["hook"]]
        elif "start" in raw_data and "end" in raw_data:
            cuts_list = [raw_data]

    sub_cuts: List[SubCut] = []
    for item in cuts_list:
        if not isinstance(item, dict):
            continue
        start = float(item.get("start", 0.0))
        end = float(item.get("end", 0.0))
        if end <= start:
            continue

        speaker = str(item.get("speaker", "center")).strip().lower()

        # Derive normalized x_center from speaker role or explicit coordinates
        if "x_center" in item or "x_c" in item:
            x_c = float(item.get("x_center", item.get("x_c", SPEAKER_CENTER_XC)))
        elif speaker == "host":
            x_c = SPEAKER_HOST_XC
        elif speaker == "guest":
            x_c = SPEAKER_GUEST_XC
        else:
            x_c = SPEAKER_CENTER_XC

        y_c = float(item.get("y_center", item.get("y_c", SPEAKER_DEFAULT_YC)))
        punch_in = float(item.get("punch_in", item.get("zoom", 1.00)))

        sub_cuts.append(
            SubCut(
                start=start,
                end=end,
                x_center=x_c,
                y_center=y_c,
                punch_in=punch_in,
                speaker=speaker,
            )
        )

    return sub_cuts


def resolve_state_file(
    output_dir: Path, project_dir: Optional[Path] = None
) -> Optional[Path]:
    """Finds .clipping_state.json across project directory, output dir, or upward tree."""
    if project_dir:
        cand = project_dir / STATE_FILENAME
        if cand.is_file():
            return cand

    cand_out = output_dir / STATE_FILENAME
    if cand_out.is_file():
        return cand_out

    cand_parent = output_dir.parent / STATE_FILENAME
    if cand_parent.is_file():
        return cand_parent

    cand_cwd = Path.cwd() / STATE_FILENAME
    if cand_cwd.is_file():
        return cand_cwd

    return None


def trigger_companion_checkpoint(
    state_path: Path,
    project_file: Path,
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """Invokes clipping_state.py checkpoint --step clipping-assembly.

    This notifies the live FilmCraft GUI companion (if running) to reload the
    timeline, computes differentials against the baseline, generates the
    RequestFeedback: true review artifact, and stages the checkpoint gate.
    """
    scripts_dir = Path(__file__).resolve().parent
    clipping_state_cli = scripts_dir / "clipping_state.py"
    if not clipping_state_cli.is_file():
        return {"success": False, "error": f"{clipping_state_cli} not found"}

    cmd = [
        sys.executable,
        str(clipping_state_cli),
        "checkpoint",
        "--step",
        "clipping-assembly",
        "--dir",
        str(state_path.parent),
        "--project-file",
        str(project_file.resolve()),
        "--json",
    ]
    if auto_approve:
        cmd.append("--auto-approve")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        parsed: Dict[str, Any] = {}
        if stdout:
            try:
                parsed = json.loads(stdout)
            except Exception:
                parsed = {"raw_stdout": stdout}

        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "data": parsed,
            "stderr": stderr,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def assemble_vertical_project(
    media_path: Union[str, Path],
    output_dir: Union[str, Path],
    cuts_path: Optional[Union[str, Path]] = None,
    sub_cuts: Optional[List[SubCut]] = None,
    watermark_path: Optional[Union[str, Path]] = None,
    bgm_path: Optional[Union[str, Path]] = None,
    bgm_volume_db: float = -18.0,
    sfx_volume_db: float = -4.0,
    project_name: Optional[str] = None,
    project_dir: Optional[Union[str, Path]] = None,
    src_width: int = DEFAULT_SRC_WIDTH,
    src_height: int = DEFAULT_SRC_HEIGHT,
    fps_num: int = 30,
    fps_den: int = 1,
    silence_threshold: float = DEFAULT_SILENCE_THRESHOLD_SEC,
    consonant_buffer: float = DEFAULT_CONSONANT_BUFFER_SEC,
    trigger_checkpoint: bool = True,
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """High-level Python API to assemble a 9:16 vertical project and stage checkpoint."""
    media_p = Path(media_path).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    wm_p = Path(watermark_path).resolve() if watermark_path else None
    bgm_p = Path(bgm_path).resolve() if bgm_path else None
    proj_dir = Path(project_dir).resolve() if project_dir else None

    if not project_name:
        project_name = media_p.stem

    # Resolve cuts
    final_sub_cuts: List[SubCut] = []
    if sub_cuts is not None:
        final_sub_cuts = list(sub_cuts)
    elif cuts_path:
        cp = Path(cuts_path).resolve()
        if cp.is_file():
            with open(cp, "r", encoding="utf-8") as f:
                raw = json.load(f)
            final_sub_cuts = parse_cuts_data(raw)
        else:
            raise FileNotFoundError(f"Cuts file not found at {cp}")
    else:
        # Default single cut spanning 30s
        final_sub_cuts = [
            SubCut(
                start=0.0,
                end=30.0,
                x_center=SPEAKER_CENTER_XC,
                y_center=SPEAKER_DEFAULT_YC,
                punch_in=1.00,
            )
        ]

    # Initialize builder
    fcproj_file = out_dir / f"{project_name}.fcproj"
    config = AssemblyConfig(
        project_name=project_name,
        output_path=fcproj_file,
        media_path=media_p,
        watermark_path=wm_p,
        bgm_path=bgm_p,
        bgm_volume_db=bgm_volume_db,
        sfx_volume_db=sfx_volume_db,
        src_width=src_width,
        src_height=src_height,
        fps_num=fps_num,
        fps_den=fps_den,
        sub_cuts=final_sub_cuts,
        consonant_buffer=consonant_buffer,
        silence_threshold=silence_threshold,
    )

    builder = FcprojBuilder(config)
    fcproj_doc = builder.build()

    # Calculate assembled timeline duration
    seq_item = fcproj_doc["project"]["items"]["1"]["kind"]["Sequence"]
    v1_track = seq_item["video_tracks"][0]
    total_ticks = sum(item["duration"] for item in v1_track["items"])
    total_seconds = ticks_to_seconds(total_ticks)

    # Save .fcproj
    with open(fcproj_file, "w", encoding="utf-8") as f:
        json.dump(fcproj_doc, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Generate standardized sidecar manifest (.meta.json) per ADR 0002 & spec
    meta_file = out_dir / f"{project_name}.meta.json"
    sidecar_data = {
        "project_name": project_name,
        "fcproj_file": str(fcproj_file.resolve()),
        "media_file": str(media_p),
        "watermark_file": str(wm_p) if wm_p else None,
        "bgm_file": str(bgm_p) if bgm_p else None,
        "duration_seconds": total_seconds,
        "duration_ticks": total_ticks,
        "canvas": {"width": DEFAULT_CANVAS_WIDTH, "height": DEFAULT_CANVAS_HEIGHT, "fps": fps_num / fps_den},
        "tracks": {
            "V1": {"name": TRACK_V1_NAME, "scale_pct": builder.bg_scale, "blur": 45.0, "opacity": 40.0},
            "V2": {"name": TRACK_V2_NAME, "fill_scale_pct": builder.fill_scale, "cuts_count": len(final_sub_cuts)},
            "V3": {"name": TRACK_V3_NAME, "items_count": 0},
            "V4": {"name": TRACK_V4_NAME, "watermark": str(wm_p) if wm_p else None, "scale_pct": WATERMARK_SCALE_PCT},
            "A1": {"name": TRACK_A1_NAME, "volume_db": 0.0},
            "A2": {"name": TRACK_A2_NAME, "volume_db": bgm_volume_db},
            "A3": {"name": TRACK_A3_NAME, "volume_db": sfx_volume_db},
        },
        "sub_cuts": [
            {
                "index": idx,
                "start": c.start,
                "end": c.effective_end if c.effective_end is not None else c.end,
                "raw_end": c.end,
                "duration": (c.effective_end if c.effective_end is not None else c.end) - c.start,
                "speaker": c.speaker,
                "x_center": c.x_center,
                "y_center": c.y_center,
                "punch_in": c.punch_in,
            }
            for idx, c in enumerate(prune_dead_air(final_sub_cuts, silence_threshold, consonant_buffer))
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(sidecar_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # State staging and companion checkpoint triggering
    state_file = resolve_state_file(out_dir, proj_dir)
    checkpoint_res: Optional[Dict[str, Any]] = None

    if state_file and state_file.is_file():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)

            steps = state_data.setdefault("steps", {})
            step_assembly = steps.setdefault("clipping-assembly", {
                "status": "pending",
                "approved": False,
                "completed_at": None,
                "params": {},
            })

            step_assembly["status"] = "staged"
            step_assembly["staged"] = True
            params = step_assembly.setdefault("params", {})
            params["project_file"] = str(fcproj_file.resolve())
            params["meta_file"] = str(meta_file.resolve())
            params["project_name"] = project_name
            params["duration_seconds"] = total_seconds
            params["cuts_count"] = len(final_sub_cuts)
            params["tracks"] = {
                "video": [TRACK_V1_NAME, TRACK_V2_NAME, TRACK_V3_NAME, TRACK_V4_NAME],
                "audio": [TRACK_A1_NAME, TRACK_A2_NAME, TRACK_A3_NAME],
            }
            params["timestamp"] = datetime.now(timezone.utc).isoformat()
            state_data["updated_at"] = datetime.now(timezone.utc).isoformat()

            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2, ensure_ascii=False)
                f.write("\n")

            if trigger_checkpoint:
                checkpoint_res = trigger_companion_checkpoint(
                    state_path=state_file,
                    project_file=fcproj_file,
                    auto_approve=auto_approve,
                )
        except Exception as ex:
            checkpoint_res = {"success": False, "error": f"Failed state update: {ex}"}

    return {
        "status": "success",
        "project_name": project_name,
        "project_file": str(fcproj_file.resolve()),
        "meta_file": str(meta_file.resolve()),
        "duration_seconds": total_seconds,
        "duration_ticks": total_ticks,
        "cuts_count": len(final_sub_cuts),
        "state_file": str(state_file.resolve()) if state_file else None,
        "checkpoint_triggered": trigger_checkpoint and bool(state_file),
        "checkpoint_result": checkpoint_res,
    }


def cmd_assemble(args: argparse.Namespace) -> int:
    """CLI handler for `assemble` subcommand."""
    try:
        res = assemble_vertical_project(
            media_path=args.media,
            output_dir=args.output_dir,
            cuts_path=args.cuts,
            watermark_path=args.watermark,
            bgm_path=args.bgm,
            bgm_volume_db=args.bgm_volume,
            sfx_volume_db=args.sfx_volume,
            project_name=args.project_name,
            project_dir=args.project_dir,
            src_width=args.src_width,
            src_height=args.src_height,
            fps_num=args.fps_num,
            fps_den=args.fps_den,
            silence_threshold=args.silence_threshold,
            consonant_buffer=args.consonant_buffer,
            trigger_checkpoint=not args.no_checkpoint,
            auto_approve=args.auto_approve,
        )

        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"[SUCCESS] Assembled 9:16 vertical project: {res['project_file']}")
            print(f"  Duration: {res['duration_seconds']:.2f}s ({res['duration_ticks']} ticks)")
            print(f"  Sidecar Meta: {res['meta_file']}")
            if res.get("checkpoint_triggered"):
                cp_data = res.get("checkpoint_result", {})
                cp_ok = cp_data.get("success", False) if cp_data else False
                status_label = "TRIGGERED / ACTIVE" if cp_ok else "TRIGGER ATTEMPTED"
                print(f"  Live Companion Checkpoint: {status_label}")
            elif not res.get("state_file"):
                print("  Note: No .clipping_state.json found; project created in standalone mode.")

        return 0
    except Exception as e:
        sys.stderr.write(f"Assembly Error: {e}\n")
        return 1


def cmd_inspect(args: argparse.Namespace) -> int:
    """CLI handler for `inspect` subcommand."""
    p_path = Path(args.project).resolve()
    if not p_path.is_file():
        sys.stderr.write(f"Error: Project file not found at {p_path}\n")
        return 1

    try:
        with open(p_path, "r", encoding="utf-8") as f:
            doc = json.load(f)

        seq_item = doc["project"]["items"]["1"]["kind"]["Sequence"]
        v_tracks = seq_item["video_tracks"]
        a_tracks = seq_item["audio_tracks"]

        v1_dur = sum(item["duration"] for item in v_tracks[0]["items"])
        total_sec = ticks_to_seconds(v1_dur)

        summary = {
            "format": doc.get("format"),
            "schema_version": doc.get("schema_version"),
            "project_name": doc["project"]["name"],
            "duration_seconds": total_sec,
            "video_tracks": [
                {"id": t["id"], "name": t["name"], "items_count": len(t["items"])}
                for t in v_tracks
            ],
            "audio_tracks": [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "volume_db": t["volume_db"],
                    "items_count": len(t["items"]),
                }
                for t in a_tracks
            ],
        }

        # Optional filmcraft-cli verification
        if args.verify_cli:
            cli_res = subprocess.run(
                ["filmcraft-cli", "--project", str(p_path), "inspect", "sequence"],
                capture_output=True,
                text=True,
            )
            summary["filmcraft_cli_status"] = cli_res.returncode
            summary["filmcraft_cli_valid"] = cli_res.returncode == 0

        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"Project: {summary['project_name']} ({summary['duration_seconds']:.2f}s)")
            print(f"Format: {summary['format']} (v{summary['schema_version']})")
            print("Video Tracks:")
            for vt in summary["video_tracks"]:
                print(f"  V{vt['id']}: {vt['name']} ({vt['items_count']} clips)")
            print("Audio Tracks:")
            for at in summary["audio_tracks"]:
                print(f"  A{at['id']}: {at['name']} ({at['volume_db']} dB, {at['items_count']} clips)")

        return 0
    except Exception as e:
        sys.stderr.write(f"Inspection Error: {e}\n")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Native 9:16 vertical video assembly engine (.fcproj) for FilmCraft."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # assemble
    p_assemble = subparsers.add_parser(
        "assemble", help="Assemble 9:16 vertical video project from media and cuts."
    )
    p_assemble.add_argument(
        "--media", required=True, help="Path to raw source video file"
    )
    p_assemble.add_argument(
        "--cuts", default=None, help="Path to cuts JSON file (optional)"
    )
    p_assemble.add_argument(
        "--output-dir", required=True, help="Directory to output assembled .fcproj and .meta.json"
    )
    p_assemble.add_argument(
        "--project-dir",
        default=None,
        help="Path to project directory containing .clipping_state.json (optional)",
    )
    p_assemble.add_argument(
        "--project-name", default=None, help="Name for sequence and project"
    )
    p_assemble.add_argument(
        "--watermark", default=None, help="Path to watermark transparent PNG"
    )
    p_assemble.add_argument(
        "--bgm", default=None, help="Path to background music audio file"
    )
    p_assemble.add_argument(
        "--bgm-volume", type=float, default=-18.0, help="BGM volume in dB (default: -18.0)"
    )
    p_assemble.add_argument(
        "--sfx-volume", type=float, default=-4.0, help="SFX volume in dB (default: -4.0)"
    )
    p_assemble.add_argument(
        "--src-width", type=int, default=DEFAULT_SRC_WIDTH, help="Source width in px (default: 1920)"
    )
    p_assemble.add_argument(
        "--src-height", type=int, default=DEFAULT_SRC_HEIGHT, help="Source height in px (default: 1080)"
    )
    p_assemble.add_argument(
        "--fps-num", type=int, default=30, help="Framerate numerator (default: 30)"
    )
    p_assemble.add_argument(
        "--fps-den", type=int, default=1, help="Framerate denominator (default: 1)"
    )
    p_assemble.add_argument(
        "--silence-threshold",
        type=float,
        default=DEFAULT_SILENCE_THRESHOLD_SEC,
        help="Dead air silence threshold in seconds (default: 0.40)",
    )
    p_assemble.add_argument(
        "--consonant-buffer",
        type=float,
        default=DEFAULT_CONSONANT_BUFFER_SEC,
        help="Consonant buffer in seconds (default: 0.08)",
    )
    p_assemble.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Do not trigger clipping_state.py checkpoint after assembly",
    )
    p_assemble.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve checkpoint gate after staging",
    )
    p_assemble.add_argument(
        "--json", action="store_true", help="Output result as JSON"
    )

    # inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect an assembled .fcproj file.")
    p_inspect.add_argument(
        "--project", required=True, help="Path to .fcproj project file"
    )
    p_inspect.add_argument(
        "--verify-cli", action="store_true", help="Verify syntax with filmcraft-cli binary"
    )
    p_inspect.add_argument(
        "--json", action="store_true", help="Output summary as JSON"
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.subcommand == "assemble":
        return cmd_assemble(args)
    elif args.subcommand == "inspect":
        return cmd_inspect(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
