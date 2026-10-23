#!/usr/bin/env python3
"""
scripts/clipping_preferences.py

Prototype Dual-Channel Preference Codification Engine for Antigravity Short-Form Clipping Pipeline.

Features:
1. 3-Tier Hierarchical Preference Storage & Resolution:
   - Tier 1: Project-level (<project-dir>/.clipping_preferences.json)
   - Tier 2: Campaign-level (<project-dir>/campaign_brief.json)
   - Tier 3: Global user-level (~/.config/clipping-pipeline/preferences.json)
   - Safe Defaults (Base Tier 4)
   - Precedence: Project > Campaign > Global > Safe Defaults

2. Channel 1 (Chat Directives Parsing):
   - Natural language feedback parser detecting editorial directives:
     target duration, speaker framing anchors, layout presets, punch-ins,
     caption words per line, caption colors/typography, SFX/BGM levels,
     consonant cut padding, and watermark options.

3. Channel 2 (Project Diffing Heuristic):
   - Differential analysis comparing user-modified .remotion.json files against
     agent-generated baselines to detect timeline item modifications,
     speaker framing anchors (x_c, y_c), consonant padding trims, track volume
     overrides, blur/opacity values, and watermark styling.
   - Automatically codifies detected diffs into the specified preference scope.

4. Preference Management CLI & Built-in Test Suite:
   - CLI: get, set, list, reset, parse-feedback, diff-project, test

Zero external runtime dependencies (Python standard library only).
"""

import argparse
import copy
import json
import math
import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Constants & High-Precision Time Base
# ---------------------------------------------------------------------------

TICKS_PER_SEC: int = 254_016_000_000

PROJECT_PREFERENCES_FILENAME: str = ".clipping_preferences.json"
CAMPAIGN_BRIEF_FILENAME: str = "campaign_brief.json"
GLOBAL_CONFIG_DIR: str = "clipping-pipeline"
GLOBAL_PREFERENCES_FILENAME: str = "preferences.json"

# Canonical Video Track Identifiers & Names
TRACK_V1_NAME: str = "Blurred Background"
TRACK_V2_NAME: str = "Speaker Foreground"
TRACK_V3_NAME: str = "HUD & Overlays"
TRACK_V4_NAME: str = "Watermark"

# Canonical Audio Track Identifiers & Names
TRACK_A1_NAME: str = "Dialogue"
TRACK_A2_NAME: str = "Background Music"
TRACK_A3_NAME: str = "SFX"

# Canonical Canvas Dimensions
CANVAS_WIDTH: float = 1080.0
CANVAS_HEIGHT: float = 1920.0
CANVAS_CENTER_X: float = 540.0
CANVAS_CENTER_Y: float = 960.0

# Base Safe Defaults (Tier 4)
SAFE_DEFAULTS: Dict[str, Any] = {
    "duration": {
        "target_seconds": 45.0,
        "min_seconds": 20.0,
        "max_seconds": 60.0,
    },
    "framing": {
        "default_preset": "split_sandwich",
        "speaker_anchor_x": 0.50,
        "speaker_anchor_y": 0.50,
        "foreground_scale": 177.7778,
        "background_scale": 209.7778,
        "background_blur": 45.0,
        "background_opacity": 40.0,
        "punch_in_enabled": True,
        "punch_in_scale": 199.1111,
        "letterbox_scale": 56.25,
    },
    "timeline": {
        "consonant_padding_seconds": 0.08,
        "silence_threshold_seconds": 0.40,
        "min_clip_duration_seconds": 0.04,
    },
    "captions": {
        "words_per_line": 3,
        "max_lines": 2,
        "font_size": 72,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFD700",
        "stroke_color": "#000000",
        "stroke_width": 8.0,
        "y_position": 1300.0,
    },
    "audio": {
        "dialogue_volume_db": 0.0,
        "bgm_volume_db": -20.0,
        "sfx_volume_db": -2.0,
        "loudness_target_lufs": -14.0,
    },
    "watermark": {
        "enabled": True,
        "scale": 28.0,
        "position_x": 540.0,
        "position_y": 280.0,
        "opacity": 100.0,
    },
}

COLOR_NAME_MAP: Dict[str, str] = {
    "yellow": "#FFD700",
    "gold": "#FFD700",
    "white": "#FFFFFF",
    "cyan": "#00FFFF",
    "aqua": "#00FFFF",
    "green": "#00FF00",
    "lime": "#CCFF00",
    "red": "#FF3333",
    "crimson": "#FF0000",
    "black": "#000000",
    "orange": "#FFA500",
    "purple": "#9933FF",
}

# ---------------------------------------------------------------------------
# Time Base Conversion Utilities
# ---------------------------------------------------------------------------

def seconds_to_ticks(seconds: float) -> int:
    """Convert floating-point seconds to discrete timeline ticks."""
    return int(round(seconds * TICKS_PER_SEC))


def ticks_to_seconds(ticks: int) -> float:
    """Convert discrete timeline ticks to floating-point seconds."""
    return float(ticks) / TICKS_PER_SEC


# ---------------------------------------------------------------------------
# Storage & Path Resolution
# ---------------------------------------------------------------------------

def get_global_preferences_path() -> Path:
    """
    Get the path to global user-level preferences.json.
    Honors CLIPPING_GLOBAL_PREFERENCES_PATH or CLIPPING_CONFIG_DIR if set.
    """
    override = os.environ.get("CLIPPING_GLOBAL_PREFERENCES_PATH")
    if override:
        return Path(override)
    config_dir_env = os.environ.get("CLIPPING_CONFIG_DIR")
    if config_dir_env:
        return Path(config_dir_env) / GLOBAL_PREFERENCES_FILENAME
    return Path.home() / ".config" / GLOBAL_CONFIG_DIR / GLOBAL_PREFERENCES_FILENAME


def get_project_preferences_path(project_dir: Optional[Union[str, Path]] = None) -> Path:
    """Get project-level preferences file path."""
    base = Path(project_dir) if project_dir else Path.cwd()
    return base / PROJECT_PREFERENCES_FILENAME


def get_campaign_brief_path(project_dir: Optional[Union[str, Path]] = None) -> Optional[Path]:
    """Locate campaign_brief.json in project dir or parents."""
    curr = Path(project_dir).resolve() if project_dir else Path.cwd().resolve()
    for directory in [curr, *curr.parents]:
        target = directory / CAMPAIGN_BRIEF_FILENAME
        if target.is_file():
            return target
    return None


def load_json_file(path: Path) -> Dict[str, Any]:
    """Safely load JSON dictionary from file. Returns empty dict if not found or malformed."""
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        sys.stderr.write(f"[Warning] Failed to read JSON file {path}: {exc}\n")
        return {}


def save_json_file(path: Path, data: Dict[str, Any]) -> None:
    """Atomically save JSON data to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp." + str(os.getpid()))
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# Dictionary Helpers (Deep Merge, Dot-Notation, Flattening)
# ---------------------------------------------------------------------------

def deep_merge(base: Dict[str, Any], *overrides: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively deep-merge dictionaries from left to right.
    Overrides overwrite scalar values and merge nested dicts.
    """
    result = copy.deepcopy(base)
    for override in overrides:
        if not isinstance(override, dict):
            continue
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
    return result


def flatten_dict(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Flatten nested dictionary into dot-separated keys."""
    items: Dict[str, Any] = {}
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            items.update(flatten_dict(value, full_key))
        else:
            items[full_key] = value
    return items


def unflatten_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convert flat dot-separated keys into a nested dictionary."""
    result: Dict[str, Any] = {}
    for key, value in d.items():
        parts = key.split(".")
        current = result
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = copy.deepcopy(value)
    return result


def get_nested(d: Dict[str, Any], dot_key: str, default: Any = None) -> Any:
    """Retrieve value using dot-notation string."""
    parts = dot_key.split(".")
    curr: Any = d
    for part in parts:
        if not isinstance(curr, dict) or part not in curr:
            return default
        curr = curr[part]
    return curr


def set_nested(d: Dict[str, Any], dot_key: str, value: Any) -> None:
    """Set value using dot-notation string, creating intermediate dicts as needed."""
    parts = dot_key.split(".")
    curr = d
    for part in parts[:-1]:
        if part not in curr or not isinstance(curr[part], dict):
            curr[part] = {}
        curr = curr[part]
    curr[parts[-1]] = value


def delete_nested(d: Dict[str, Any], dot_key: str) -> bool:
    """Delete a key using dot-notation string. Returns True if deleted."""
    parts = dot_key.split(".")
    curr = d
    stack = []
    for part in parts[:-1]:
        if not isinstance(curr, dict) or part not in curr:
            return False
        stack.append((curr, part))
        curr = curr[part]

    if isinstance(curr, dict) and parts[-1] in curr:
        del curr[parts[-1]]
        # Clean up empty parent dicts
        for parent_dict, parent_key in reversed(stack):
            if parent_dict[parent_key] == {}:
                del parent_dict[parent_key]
        return True
    return False


def parse_typed_value(raw: str) -> Any:
    """Parse a CLI string into appropriate primitive or JSON structure."""
    raw_stripped = raw.strip()
    if raw_stripped.lower() == "true":
        return True
    if raw_stripped.lower() == "false":
        return False
    if raw_stripped.lower() in ("null", "none"):
        return None
    try:
        if "." in raw_stripped or "e" in raw_stripped.lower():
            return float(raw_stripped)
        return int(raw_stripped)
    except ValueError:
        pass
    try:
        return json.loads(raw_stripped)
    except Exception:
        return raw_stripped


# ---------------------------------------------------------------------------
# Campaign Brief Adapter
# ---------------------------------------------------------------------------

def adapt_campaign_brief(brief: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map schema from campaign_brief.json into the unified preference schema.
    Extracts duration constraints, audio guidelines, watermark requirements, etc.
    """
    mapped: Dict[str, Any] = {}

    # Check for direct 'preferences' section if present
    if isinstance(brief.get("preferences"), dict):
        mapped = deep_merge(mapped, brief["preferences"])

    # Duration mappings
    duration_info = brief.get("duration")
    if isinstance(duration_info, dict):
        dur_prefs: Dict[str, Any] = {}
        if "ideal_max" in duration_info:
            dur_prefs["target_seconds"] = float(duration_info["ideal_max"])
        elif "max_seconds" in duration_info:
            dur_prefs["target_seconds"] = float(duration_info["max_seconds"])
        if "min_seconds" in duration_info:
            dur_prefs["min_seconds"] = float(duration_info["min_seconds"])
        if "max_seconds" in duration_info:
            dur_prefs["max_seconds"] = float(duration_info["max_seconds"])
        if dur_prefs:
            mapped["duration"] = dur_prefs

    # Audio mappings
    audio_info = brief.get("audio")
    if isinstance(audio_info, dict):
        audio_prefs: Dict[str, Any] = {}
        if audio_info.get("zero_background_music") is True or audio_info.get("zero_phonk") is True:
            audio_prefs["bgm_volume_db"] = -80.0  # effectively muted
        if "loudness_target_lufs" in audio_info:
            audio_prefs["loudness_target_lufs"] = float(audio_info["loudness_target_lufs"])
        if audio_prefs:
            mapped["audio"] = audio_prefs

    # Watermark mappings
    watermark_info = brief.get("watermark")
    if isinstance(watermark_info, dict):
        wm_prefs: Dict[str, Any] = {}
        if "required" in watermark_info:
            wm_prefs["enabled"] = bool(watermark_info["required"])
        if wm_prefs:
            mapped["watermark"] = wm_prefs

    return mapped


# ---------------------------------------------------------------------------
# 3-Tier Hierarchy Resolution Engine
# ---------------------------------------------------------------------------

class PreferenceStore:
    """
    Manages the 3-tier preference hierarchy:
    Tier 1: Project-level (<project_dir>/.clipping_preferences.json)
    Tier 2: Campaign-level (<project_dir>/campaign_brief.json)
    Tier 3: Global user-level (~/.config/clipping-pipeline/preferences.json)
    Tier 4: Safe Defaults
    """

    def __init__(self, project_dir: Optional[Union[str, Path]] = None):
        self.project_dir = Path(project_dir).resolve() if project_dir else Path.cwd().resolve()
        self.project_path = get_project_preferences_path(self.project_dir)
        self.campaign_path = get_campaign_brief_path(self.project_dir)
        self.global_path = get_global_preferences_path()

    def load_tier_data(self) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """Load data from each tier independently."""
        default_data = copy.deepcopy(SAFE_DEFAULTS)
        global_data = load_json_file(self.global_path)
        campaign_raw = load_json_file(self.campaign_path) if self.campaign_path else {}
        campaign_data = adapt_campaign_brief(campaign_raw)
        project_data = load_json_file(self.project_path)
        return default_data, global_data, campaign_data, project_data

    def resolve(self) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """
        Hierarchically merge preferences:
        Defaults < Global < Campaign < Project.
        Returns:
            resolved_dict: Merged preference dictionary.
            provenance: Mapping from flattened dot-key to source tier name ('default', 'global', 'campaign', 'project').
        """
        defaults, global_d, campaign_d, project_d = self.load_tier_data()

        # Compute merged dictionary
        merged = deep_merge(defaults, global_d, campaign_d, project_d)

        # Track provenance for every flat key
        flat_defaults = flatten_dict(defaults)
        flat_global = flatten_dict(global_d)
        flat_campaign = flatten_dict(campaign_d)
        flat_project = flatten_dict(project_d)
        flat_merged = flatten_dict(merged)

        provenance: Dict[str, str] = {}
        for key in flat_merged:
            if key in flat_project:
                provenance[key] = "project"
            elif key in flat_campaign:
                provenance[key] = "campaign"
            elif key in flat_global:
                provenance[key] = "global"
            else:
                provenance[key] = "default"

        return merged, provenance

    def get(self, key: Optional[str] = None) -> Tuple[Any, Optional[str]]:
        """Get a resolved preference value and its source tier."""
        resolved, provenance = self.resolve()
        if not key:
            return resolved, None
        val = get_nested(resolved, key)
        src = provenance.get(key)
        return val, src

    def set(self, key: str, value: Any, scope: str = "project") -> None:
        """Set a preference in the specified scope ('project' or 'global')."""
        target_path = self.project_path if scope == "project" else self.global_path
        data = load_json_file(target_path)
        set_nested(data, key, value)
        save_json_file(target_path, data)

    def reset(self, key: Optional[str] = None, scope: str = "project") -> bool:
        """Reset a preference key or the entire file for the specified scope."""
        target_path = self.project_path if scope == "project" else self.global_path
        if not target_path.is_file():
            return False

        if not key:
            try:
                target_path.unlink()
                return True
            except OSError:
                return False

        data = load_json_file(target_path)
        deleted = delete_nested(data, key)
        if deleted:
            if data:
                save_json_file(target_path, data)
            else:
                target_path.unlink()
        return deleted


# ---------------------------------------------------------------------------
# Channel 1: Chat Directives Parsing
# ---------------------------------------------------------------------------

def parse_feedback_directives(text: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Parses natural language operator directives from chat feedback.
    Returns:
        directives: List of recognized directives with metadata.
        proposed_preferences: Dict of proposed preference overrides.
    """
    directives: List[Dict[str, Any]] = []
    proposed_preferences: Dict[str, Any] = {}

    norm_text = text.strip()
    lower_text = norm_text.lower()

    # 1. Target Duration
    # Examples: "target 30s", "make it 45 seconds", "shorten to 30s", "duration around 40s", "between 30 and 45 seconds"
    range_match = re.search(
        r"between\s+(\d+(?:\.\d+)?)\s*(?:and|to|-)\s*(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)",
        lower_text,
    )
    if range_match:
        min_s = float(range_match.group(1))
        max_s = float(range_match.group(2))
        target_s = round((min_s + max_s) / 2.0, 1)
        directives.append({
            "directive": "duration_range",
            "raw_match": range_match.group(0),
            "key": "duration.target_seconds",
            "value": target_s,
            "bounds": {"min_seconds": min_s, "max_seconds": max_s},
            "explanation": f"Set duration range {min_s}s - {max_s}s (target: {target_s}s)",
        })
        set_nested(proposed_preferences, "duration.target_seconds", target_s)
        set_nested(proposed_preferences, "duration.min_seconds", min_s)
        set_nested(proposed_preferences, "duration.max_seconds", max_s)
    else:
        dur_match = re.search(
            r"(?:target|set|make(?: it)?|duration|length|shorten to|keep it to|around|approx(?:imately)?)\s*(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)\b",
            lower_text,
        )
        if not dur_match:
            dur_match = re.search(
                r"\b(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds)\s*(?:target|duration|length|long|clip)\b",
                lower_text,
            )
        if dur_match:
            val = float(dur_match.group(1))
            directives.append({
                "directive": "duration_target",
                "raw_match": dur_match.group(0),
                "key": "duration.target_seconds",
                "value": val,
                "explanation": f"Set target duration to {val}s",
            })
            set_nested(proposed_preferences, "duration.target_seconds", val)

    # 2. Speaker Crop / Framing Anchor
    # Examples: "center on host", "crop to guest", "framing anchor x 0.25", "move framing left", "shift speaker framing up"
    speaker_anchor_match = re.search(
        r"(?:anchor|crop|center|reframe|focus)\s*(?:on|to)?\s*(?:the\s+)?(host|guest|speaker\s*[ab]|center|left|right)\b",
        lower_text,
    )
    if speaker_anchor_match:
        speaker_id = speaker_anchor_match.group(1).strip()
        if "host" in speaker_id or "left" in speaker_id or "speaker a" in speaker_id:
            x_c, y_c = 0.25, 0.45
            desc = "Framed on Host (Camera Left, x=0.25, y=0.45)"
        elif "guest" in speaker_id or "right" in speaker_id or "speaker b" in speaker_id:
            x_c, y_c = 0.75, 0.45
            desc = "Framed on Guest (Camera Right, x=0.75, y=0.45)"
        else:
            x_c, y_c = 0.50, 0.50
            desc = "Framed Center (x=0.50, y=0.50)"

        directives.append({
            "directive": "speaker_framing_preset",
            "raw_match": speaker_anchor_match.group(0),
            "key": "framing.speaker_anchor_x",
            "value": x_c,
            "anchor_y": y_c,
            "explanation": desc,
        })
        set_nested(proposed_preferences, "framing.speaker_anchor_x", x_c)
        set_nested(proposed_preferences, "framing.speaker_anchor_y", y_c)

    # Explicit anchor coordinates: "anchor x 0.35", "framing x=0.2"
    anchor_x_match = re.search(r"(?:anchor|framing|crop|shift)\s*(?:anchor\s*)?x\s*(?:to\s*|=|\s+)?(\d+(?:\.\d+)?)", lower_text)
    if anchor_x_match:
        ax = float(anchor_x_match.group(1))
        directives.append({
            "directive": "speaker_anchor_x",
            "raw_match": anchor_x_match.group(0),
            "key": "framing.speaker_anchor_x",
            "value": ax,
            "explanation": f"Set speaker anchor x to {ax}",
        })
        set_nested(proposed_preferences, "framing.speaker_anchor_x", ax)

    anchor_y_match = re.search(r"(?:anchor|framing|crop|shift)\s*(?:anchor\s*)?y\s*(?:to\s*|=|\s+)?(\d+(?:\.\d+)?)", lower_text)
    if anchor_y_match:
        ay = float(anchor_y_match.group(1))
        directives.append({
            "directive": "speaker_anchor_y",
            "raw_match": anchor_y_match.group(0),
            "key": "framing.speaker_anchor_y",
            "value": ay,
            "explanation": f"Set speaker anchor y to {ay}",
        })
        set_nested(proposed_preferences, "framing.speaker_anchor_y", ay)

    # Relative framing shift: "shift framing left", "move crop right"
    dir_shift = re.search(r"(?:shift|move)\s*(?:framing|crop|speaker)?\s*(left|right|up|down)", lower_text)
    if dir_shift and not speaker_anchor_match:
        d_name = dir_shift.group(1)
        if d_name == "left":
            val = 0.35
            key = "framing.speaker_anchor_x"
        elif d_name == "right":
            val = 0.65
            key = "framing.speaker_anchor_x"
        elif d_name == "up":
            val = 0.40
            key = "framing.speaker_anchor_y"
        else:
            val = 0.60
            key = "framing.speaker_anchor_y"

        directives.append({
            "directive": "relative_framing_shift",
            "raw_match": dir_shift.group(0),
            "key": key,
            "value": val,
            "explanation": f"Shifted framing {d_name} to {val}",
        })
        set_nested(proposed_preferences, key, val)

    # 3. Layout Presets
    # Examples: "use split sandwich", "switch to stacked split", "speaker ping-pong", "two-shot letterbox"
    if re.search(r"\bsplit[- ]sandwich\b", lower_text):
        directives.append({
            "directive": "layout_preset",
            "raw_match": "split-sandwich",
            "key": "framing.default_preset",
            "value": "split_sandwich",
            "explanation": "Set layout preset to split_sandwich (V1 blurred + V2 foreground)",
        })
        set_nested(proposed_preferences, "framing.default_preset", "split_sandwich")
    elif re.search(r"\b(stacked[- ]split|stacked|split[- ]screen)\b", lower_text):
        directives.append({
            "directive": "layout_preset",
            "raw_match": "stacked-split",
            "key": "framing.default_preset",
            "value": "stacked_split",
            "explanation": "Set layout preset to stacked_split (top host / bottom guest)",
        })
        set_nested(proposed_preferences, "framing.default_preset", "stacked_split")
    elif re.search(r"\b(ping[- ]pong|speaker ping-pong)\b", lower_text):
        directives.append({
            "directive": "layout_preset",
            "raw_match": "speaker ping-pong",
            "key": "framing.default_preset",
            "value": "speaker_ping_pong",
            "explanation": "Set layout preset to speaker_ping_pong (alternating speaker framing)",
        })
        set_nested(proposed_preferences, "framing.default_preset", "speaker_ping_pong")
    elif re.search(r"\b(letterbox|two[- ]shot)\b", lower_text):
        directives.append({
            "directive": "layout_preset",
            "raw_match": "letterbox",
            "key": "framing.default_preset",
            "value": "letterbox",
            "explanation": "Set layout preset to letterbox (56.25% full landscape width)",
        })
        set_nested(proposed_preferences, "framing.default_preset", "letterbox")

    # 4. Punch-ins / Zoom Cuts
    # Examples: "disable punch ins", "no zoom cuts", "turn off punch ins", "enable punch ins"
    if re.search(r"\b(?:disable|turn off|no|remove)\s*(?:punch[- ]ins?|zoom[- ]cuts?|zooms?)\b", lower_text):
        directives.append({
            "directive": "punch_in_toggle",
            "raw_match": "disable punch ins",
            "key": "framing.punch_in_enabled",
            "value": False,
            "explanation": "Disabled rhetorical punch-in zoom cuts",
        })
        set_nested(proposed_preferences, "framing.punch_in_enabled", False)
    elif re.search(r"\b(?:enable|turn on|keep|add|use)\s*(?:punch[- ]ins?|zoom[- ]cuts?|zooms?)\b", lower_text):
        directives.append({
            "directive": "punch_in_toggle",
            "raw_match": "enable punch ins",
            "key": "framing.punch_in_enabled",
            "value": True,
            "explanation": "Enabled rhetorical punch-in zoom cuts",
        })
        set_nested(proposed_preferences, "framing.punch_in_enabled", True)

    punch_scale_match = re.search(r"(?:punch[- ]in|zoom)\s*(?:scale|zoom|factor)?\s*(?:to\s*|=|\s+)?(\d+(?:\.\d+)?)\s*%?", lower_text)
    if punch_scale_match:
        scale_val = float(punch_scale_match.group(1))
        directives.append({
            "directive": "punch_in_scale",
            "raw_match": punch_scale_match.group(0),
            "key": "framing.punch_in_scale",
            "value": scale_val,
            "explanation": f"Set punch-in zoom scale to {scale_val}%",
        })
        set_nested(proposed_preferences, "framing.punch_in_scale", scale_val)

    # 4b. Punch-outs / Unzooms / Blurry Background
    # Examples: "punchout", "zoom out with blurry background", "punch out on reactions", "unzoom"
    if re.search(r"\b(?:punch[- ]?outs?|zoom[- ]?outs?|unzooms?|(?:zoom\s*out\s*with\s*blurry\s*background))\b", lower_text):
        directives.append({
            "directive": "punch_out_toggle",
            "raw_match": "punchout / zoom out with blurry background",
            "key": "framing.punch_out_enabled",
            "value": True,
            "explanation": "Enabled punch-out / unzoom to full landscape width with blurred background for dual-reactions and wide shots",
        })
        set_nested(proposed_preferences, "framing.punch_out_enabled", True)

    # 5. Caption Words Per Line & Geometry
    # Examples: "2 words per line", "1 word at a time", "one word per line", "max 2 lines"
    wpl_match = re.search(r"\b(\d+)\s*(?:words?\s*per\s*line|wpl)\b", lower_text)
    if not wpl_match:
        wpl_match = re.search(r"\b(?:set|make|use)?\s*(\d+)\s*words?\s*(?:at a time|per subtitle)\b", lower_text)
    if not wpl_match and re.search(r"\b(?:1|one)\s*word\s*(?:at a time|per line)\b", lower_text):
        wpl = 1
        directives.append({
            "directive": "caption_words_per_line",
            "raw_match": "one word at a time",
            "key": "captions.words_per_line",
            "value": wpl,
            "explanation": "Configured kinetic single-word subtitle reveals (1 word per line)",
        })
        set_nested(proposed_preferences, "captions.words_per_line", wpl)
    elif wpl_match:
        wpl = int(wpl_match.group(1))
        directives.append({
            "directive": "caption_words_per_line",
            "raw_match": wpl_match.group(0),
            "key": "captions.words_per_line",
            "value": wpl,
            "explanation": f"Configured {wpl} words per line for captions",
        })
        set_nested(proposed_preferences, "captions.words_per_line", wpl)

    max_lines_match = re.search(r"\b(?:max|maximum)?\s*(\d+)\s*lines?\b", lower_text)
    if max_lines_match:
        ml = int(max_lines_match.group(1))
        directives.append({
            "directive": "caption_max_lines",
            "raw_match": max_lines_match.group(0),
            "key": "captions.max_lines",
            "value": ml,
            "explanation": f"Set maximum caption lines to {ml}",
        })
        set_nested(proposed_preferences, "captions.max_lines", ml)

    caption_y_match = re.search(r"(?:captions?\s*(?:lower|higher|y|position)|caption\s*y)\s*(?:to\s*|=|\s+)?(\d+(?:\.\d+)?)", lower_text)
    if caption_y_match:
        y_pos = float(caption_y_match.group(1))
        directives.append({
            "directive": "caption_y_position",
            "raw_match": caption_y_match.group(0),
            "key": "captions.y_position",
            "value": y_pos,
            "explanation": f"Set caption vertical position Y to {y_pos}px",
        })
        set_nested(proposed_preferences, "captions.y_position", y_pos)

    font_size_match = re.search(r"(?:caption|font)\s*size\s*(?:to\s*|=|\s+)?(\d+(?:\.\d+)?)", lower_text)
    if font_size_match:
        fs = int(float(font_size_match.group(1)))
        directives.append({
            "directive": "caption_font_size",
            "raw_match": font_size_match.group(0),
            "key": "captions.font_size",
            "value": fs,
            "explanation": f"Set caption font size to {fs}pt",
        })
        set_nested(proposed_preferences, "captions.font_size", fs)

    # 6. Caption Colors & Typography
    # Examples: "caption highlight color gold", "highlight color yellow", "primary caption color white", "#FF5500"
    hex_match = re.search(r"#(?:[0-9a-fA-F]{3}){1,2}\b", norm_text)
    if hex_match:
        hex_color = hex_match.group(0).upper()
        if "highlight" in lower_text:
            key = "captions.highlight_color"
            role = "highlight"
        else:
            key = "captions.primary_color"
            role = "primary"
        directives.append({
            "directive": "caption_color_hex",
            "raw_match": hex_match.group(0),
            "key": key,
            "value": hex_color,
            "explanation": f"Set caption {role} color to {hex_color}",
        })
        set_nested(proposed_preferences, key, hex_color)
    else:
        for c_name, c_hex in COLOR_NAME_MAP.items():
            if re.search(rf"\b{c_name}\b", lower_text):
                if "highlight" in lower_text or "accent" in lower_text:
                    key = "captions.highlight_color"
                    role = "highlight"
                elif "primary" in lower_text or "caption" in lower_text or "subtitle" in lower_text:
                    key = "captions.primary_color"
                    role = "primary"
                else:
                    key = "captions.highlight_color"
                    role = "highlight"
                directives.append({
                    "directive": "caption_color_named",
                    "raw_match": c_name,
                    "key": key,
                    "value": c_hex,
                    "explanation": f"Set caption {role} color to {c_name} ({c_hex})",
                })
                set_nested(proposed_preferences, key, c_hex)
                break

    # 7. Audio Levels & Mixing
    # Examples: "lower sfx volume to -6db", "sfx volume -4 dB", "mute bgm", "bgm volume -24db", "dialogue volume 1.5 dB"
    if re.search(r"\b(?:mute|remove|no|disable)\s*(?:bgm|music|background music)\b", lower_text):
        directives.append({
            "directive": "audio_bgm_mute",
            "raw_match": "mute bgm",
            "key": "audio.bgm_volume_db",
            "value": -80.0,
            "explanation": "Muted background music (-80.0 dB)",
        })
        set_nested(proposed_preferences, "audio.bgm_volume_db", -80.0)
    else:
        bgm_match = re.search(r"(?:bgm|music|background music)\s*(?:volume|level)?\s*(?:to\s*|=|\s+)?([+-]?\d+(?:\.\d+)?)\s*d[bB]\b", lower_text)
        if bgm_match:
            b_val = float(bgm_match.group(1))
            directives.append({
                "directive": "audio_bgm_level",
                "raw_match": bgm_match.group(0),
                "key": "audio.bgm_volume_db",
                "value": b_val,
                "explanation": f"Set background music volume to {b_val} dB",
            })
            set_nested(proposed_preferences, "audio.bgm_volume_db", b_val)

    if re.search(r"\b(?:mute|remove|no|disable)\s*sfx\b", lower_text):
        directives.append({
            "directive": "audio_sfx_mute",
            "raw_match": "mute sfx",
            "key": "audio.sfx_volume_db",
            "value": -80.0,
            "explanation": "Muted SFX track (-80.0 dB)",
        })
        set_nested(proposed_preferences, "audio.sfx_volume_db", -80.0)
    else:
        sfx_match = re.search(r"(?:sfx|sound effects?)\s*(?:volume|level)?\s*(?:to\s*|=|\s+)?([+-]?\d+(?:\.\d+)?)\s*d[bB]\b", lower_text)
        if sfx_match:
            s_val = float(sfx_match.group(1))
            directives.append({
                "directive": "audio_sfx_level",
                "raw_match": sfx_match.group(0),
                "key": "audio.sfx_volume_db",
                "value": s_val,
                "explanation": f"Set SFX volume to {s_val} dB",
            })
            set_nested(proposed_preferences, "audio.sfx_volume_db", s_val)

    dia_match = re.search(r"(?:dialogue|speech|voice)\s*(?:volume|level)?\s*(?:to\s*|=|\s+)?([+-]?\d+(?:\.\d+)?)\s*d[bB]\b", lower_text)
    if dia_match:
        d_val = float(dia_match.group(1))
        directives.append({
            "directive": "audio_dialogue_level",
            "raw_match": dia_match.group(0),
            "key": "audio.dialogue_volume_db",
            "value": d_val,
            "explanation": f"Set dialogue volume to {d_val} dB",
        })
        set_nested(proposed_preferences, "audio.dialogue_volume_db", d_val)

    # 8. Timeline Padding & Dead Air
    # Examples: "consonant padding 0.12s", "padding 100ms", "silence threshold 0.3s"
    pad_match = re.search(r"(?:consonant\s*)?padding\s*(?:to\s*|=|\s+)?(\d+(?:\.\d+)?)\s*(s|sec|ms|milliseconds)?\b", lower_text)
    if pad_match:
        val_raw = float(pad_match.group(1))
        unit = pad_match.group(2) or "s"
        pad_sec = val_raw / 1000.0 if "ms" in unit or val_raw > 1.0 else val_raw
        directives.append({
            "directive": "consonant_padding",
            "raw_match": pad_match.group(0),
            "key": "timeline.consonant_padding_seconds",
            "value": pad_sec,
            "explanation": f"Set consonant tail padding to {pad_sec}s",
        })
        set_nested(proposed_preferences, "timeline.consonant_padding_seconds", pad_sec)

    silence_match = re.search(r"(?:silence|dead air)\s*(?:threshold)?\s*(?:to\s*|=|\s+)?(\d+(?:\.\d+)?)\s*(s|sec|ms)?\b", lower_text)
    if silence_match:
        val_raw = float(silence_match.group(1))
        unit = silence_match.group(2) or "s"
        sil_sec = val_raw / 1000.0 if "ms" in unit or val_raw > 1.0 else val_raw
        directives.append({
            "directive": "silence_threshold",
            "raw_match": silence_match.group(0),
            "key": "timeline.silence_threshold_seconds",
            "value": sil_sec,
            "explanation": f"Set dead air silence excision threshold to {sil_sec}s",
        })
        set_nested(proposed_preferences, "timeline.silence_threshold_seconds", sil_sec)

    # 9. Watermark Options
    # Examples: "disable watermark", "hide watermark", "watermark scale 25%"
    if re.search(r"\b(?:disable|hide|remove|no)\s*watermark\b", lower_text):
        directives.append({
            "directive": "watermark_toggle",
            "raw_match": "disable watermark",
            "key": "watermark.enabled",
            "value": False,
            "explanation": "Disabled persistent watermark",
        })
        set_nested(proposed_preferences, "watermark.enabled", False)
    elif re.search(r"\b(?:enable|show|add|keep)\s*watermark\b", lower_text):
        directives.append({
            "directive": "watermark_toggle",
            "raw_match": "enable watermark",
            "key": "watermark.enabled",
            "value": True,
            "explanation": "Enabled persistent watermark",
        })
        set_nested(proposed_preferences, "watermark.enabled", True)

    wm_scale_match = re.search(r"watermark\s*scale\s*(?:to\s*|=|\s+)?(\d+(?:\.\d+)?)\s*%?", lower_text)
    if wm_scale_match:
        wms = float(wm_scale_match.group(1))
        directives.append({
            "directive": "watermark_scale",
            "raw_match": wm_scale_match.group(0),
            "key": "watermark.scale",
            "value": wms,
            "explanation": f"Set watermark scale to {wms}%",
        })
        set_nested(proposed_preferences, "watermark.scale", wms)

    return directives, proposed_preferences


# ---------------------------------------------------------------------------
# Channel 2: Project Diffing Heuristic (.remotion.json)
# ---------------------------------------------------------------------------

def _find_sequence_in_project(doc: Dict[str, Any]) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    """Extract the active sequence from a .remotion.json document."""
    items = doc.get("project", {}).get("items", {})
    view_active = doc.get("view", {}).get("active_sequence")
    if view_active is not None and str(view_active) in items:
        seq_item = items[str(view_active)]
        kind = seq_item.get("kind", {})
        if "Sequence" in kind:
            return int(view_active), kind["Sequence"]

    # Fallback: scan all items for kind.Sequence
    for item_id, item_data in items.items():
        if isinstance(item_data, dict):
            kind = item_data.get("kind", {})
            if "Sequence" in kind:
                return int(item_id), kind["Sequence"]

    return None, None


def _find_track_by_name(tracks: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    """Locate a track in track list by canonical name."""
    for tr in tracks:
        if tr.get("name") == name:
            return tr
    return None


def _to_xy_list(val: Any, default_x: float, default_y: float) -> List[float]:
    """Helper to normalize Vec2 AST dict or list into [x, y]."""
    if isinstance(val, dict) and "Vec2" in val:
        val = val["Vec2"]
    if isinstance(val, dict) and "x" in val and "y" in val:
        return [float(val["x"]), float(val["y"])]
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        return [float(val[0]), float(val[1])]
    return [float(default_x), float(default_y)]


def _extract_motion_effect_params(clip: Dict[str, Any]) -> Dict[str, Any]:
    """Extract scale, position, and anchor from a clip's motion effect."""
    effects = clip.get("effects", [])
    for eff in effects:
        if isinstance(eff, dict) and eff.get("effect") == "motion":
            params = eff.get("params", {})
            scale_raw = params.get("scale", {}).get("value", {})
            scale = scale_raw.get("Float", 100.0) if isinstance(scale_raw, dict) else 100.0

            pos_raw = params.get("position", {}).get("value", {})
            position = _to_xy_list(pos_raw, CANVAS_CENTER_X, CANVAS_CENTER_Y)

            anchor_raw = params.get("anchor", {}).get("value", {})
            anchor = _to_xy_list(anchor_raw, 960.0, 540.0)

            return {"scale": scale, "position": position, "anchor": anchor, "enabled": eff.get("enabled", True)}
    return {}


def _extract_blur_effect_params(clip: Dict[str, Any]) -> Dict[str, Any]:
    """Extract gaussian_blur parameters."""
    for eff in clip.get("effects", []):
        if isinstance(eff, dict) and eff.get("effect") == "gaussian_blur":
            params = eff.get("params", {})
            blur_raw = params.get("blurriness", {}).get("value", {})
            blur = blur_raw.get("Float", 0.0) if isinstance(blur_raw, dict) else 0.0
            return {"blurriness": blur, "enabled": eff.get("enabled", True)}
    return {}


def _extract_opacity_effect_params(clip: Dict[str, Any]) -> Dict[str, Any]:
    """Extract opacity effect parameters."""
    for eff in clip.get("effects", []):
        if isinstance(eff, dict) and eff.get("effect") == "opacity":
            params = eff.get("params", {})
            op_raw = params.get("opacity", {}).get("value", {})
            opacity = op_raw.get("Float", 100.0) if isinstance(op_raw, dict) else 100.0
            return {"opacity": opacity, "enabled": eff.get("enabled", True)}
    return {}


def diff_project_heuristic(baseline_path: Path, user_edit_path: Path) -> Dict[str, Any]:
    """
    Compares a user-modified .remotion.json file against an agent-generated baseline.
    Detects:
    1. Audio track volume adjustments (Dialogue, BGM, SFX)
    2. Speaker foreground framing anchor shifts (x_c, y_c) and scale
    3. Rhetorical punch-ins (zoom cuts toggle / punch scale)
    4. Background blur and opacity modifications
    5. Persistent watermark transformations (scale, position, enabled)
    6. Cut trimming / Consonant padding buffer adjustments
    7. Total clip duration adjustments

    Returns:
        diff_summary: Dict with 'differences' (list) and 'codified_preferences' (nested dict).
    """
    base_doc = load_json_file(baseline_path)
    user_doc = load_json_file(user_edit_path)

    if not base_doc or not user_doc:
        raise ValueError("Could not load baseline or user project file as valid JSON")

    _, base_seq = _find_sequence_in_project(base_doc)
    _, user_seq = _find_sequence_in_project(user_doc)

    if not base_seq or not user_seq:
        raise ValueError("Could not locate active sequence in both .remotion.json projects")

    differences: List[Dict[str, Any]] = []
    codified_preferences: Dict[str, Any] = {}

    base_vtracks = base_seq.get("video_tracks", [])
    user_vtracks = user_seq.get("video_tracks", [])
    base_atracks = base_seq.get("audio_tracks", [])
    user_atracks = user_seq.get("audio_tracks", [])

    # -----------------------------------------------------------------------
    # 1. Audio Track Volume Diffs
    # -----------------------------------------------------------------------
    audio_mapping = {
        TRACK_A1_NAME: ("audio.dialogue_volume_db", "Dialogue Track (A1)"),
        TRACK_A2_NAME: ("audio.bgm_volume_db", "Background Music Track (A2)"),
        TRACK_A3_NAME: ("audio.sfx_volume_db", "SFX Track (A3)"),
    }

    for track_name, (pref_key, label) in audio_mapping.items():
        base_tr = _find_track_by_name(base_atracks, track_name)
        user_tr = _find_track_by_name(user_atracks, track_name)
        if base_tr and user_tr:
            base_vol = float(base_tr.get("volume_db", 0.0))
            user_vol = float(user_tr.get("volume_db", 0.0))
            if abs(base_vol - user_vol) > 0.1:
                differences.append({
                    "category": "audio",
                    "description": f"{label} volume changed from {base_vol:.1f} dB to {user_vol:.1f} dB",
                    "baseline_value": base_vol,
                    "user_value": user_vol,
                    "codified_preference_key": pref_key,
                    "codified_value": user_vol,
                })
                set_nested(codified_preferences, pref_key, user_vol)

    # -----------------------------------------------------------------------
    # 2. Speaker Foreground Framing & Punch-Ins (Track V2)
    # -----------------------------------------------------------------------
    base_v2 = _find_track_by_name(base_vtracks, TRACK_V2_NAME)
    user_v2 = _find_track_by_name(user_vtracks, TRACK_V2_NAME)

    if base_v2 and user_v2:
        base_v2_items = base_v2.get("items", [])
        user_v2_items = user_v2.get("items", [])

        if base_v2_items and user_v2_items:
            # Inspect first item for primary framing anchor
            b_first_motion = _extract_motion_effect_params(base_v2_items[0])
            u_first_motion = _extract_motion_effect_params(user_v2_items[0])

            if b_first_motion and u_first_motion:
                b_anchor = b_first_motion.get("anchor", [960.0, 540.0])
                u_anchor = u_first_motion.get("anchor", [960.0, 540.0])

                # Source frame assumed 1920x1080
                src_w, src_h = 1920.0, 1080.0
                b_xc = round(b_anchor[0] / src_w, 4)
                b_yc = round(b_anchor[1] / src_h, 4)
                u_xc = round(u_anchor[0] / src_w, 4)
                u_yc = round(u_anchor[1] / src_h, 4)

                if abs(b_xc - u_xc) > 0.01 or abs(b_yc - u_yc) > 0.01:
                    differences.append({
                        "category": "framing",
                        "description": f"Speaker anchor shifted from ({b_xc:.2f}, {b_yc:.2f}) to ({u_xc:.2f}, {u_yc:.2f})",
                        "baseline_value": [b_xc, b_yc],
                        "user_value": [u_xc, u_yc],
                        "codified_preference_key": "framing.speaker_anchor_x",
                        "codified_value": u_xc,
                    })
                    set_nested(codified_preferences, "framing.speaker_anchor_x", u_xc)
                    set_nested(codified_preferences, "framing.speaker_anchor_y", u_yc)

                # Primary foreground scale
                b_scale = round(b_first_motion.get("scale", 177.7778), 2)
                u_scale = round(u_first_motion.get("scale", 177.7778), 2)
                if abs(b_scale - u_scale) > 0.5:
                    differences.append({
                        "category": "framing",
                        "description": f"Speaker foreground scale adjusted from {b_scale}% to {u_scale}%",
                        "baseline_value": b_scale,
                        "user_value": u_scale,
                        "codified_preference_key": "framing.foreground_scale",
                        "codified_value": u_scale,
                    })
                    set_nested(codified_preferences, "framing.foreground_scale", u_scale)

            # Punch-in detection across all V2 clips
            u_scales = []
            for item in user_v2_items:
                m = _extract_motion_effect_params(item)
                if m and "scale" in m:
                    u_scales.append(round(m["scale"], 2))

            b_scales = []
            for item in base_v2_items:
                m = _extract_motion_effect_params(item)
                if m and "scale" in m:
                    b_scales.append(round(m["scale"], 2))

            b_has_punch = any(s > 185.0 for s in b_scales)
            u_has_punch = any(s > 185.0 for s in u_scales)

            if b_has_punch and not u_has_punch:
                differences.append({
                    "category": "framing",
                    "description": "User removed rhetorical punch-ins (all clips flattened to standard scale)",
                    "baseline_value": True,
                    "user_value": False,
                    "codified_preference_key": "framing.punch_in_enabled",
                    "codified_value": False,
                })
                set_nested(codified_preferences, "framing.punch_in_enabled", False)
            elif not b_has_punch and u_has_punch:
                max_u_scale = max(u_scales)
                differences.append({
                    "category": "framing",
                    "description": f"User introduced punch-ins with scale {max_u_scale}%",
                    "baseline_value": False,
                    "user_value": True,
                    "codified_preference_key": "framing.punch_in_enabled",
                    "codified_value": True,
                })
                set_nested(codified_preferences, "framing.punch_in_enabled", True)
                set_nested(codified_preferences, "framing.punch_in_scale", max_u_scale)
            elif u_has_punch and b_has_punch:
                max_b = max(b_scales)
                max_u = max(u_scales)
                if abs(max_b - max_u) > 1.0:
                    differences.append({
                        "category": "framing",
                        "description": f"Punch-in zoom scale modified from {max_b}% to {max_u}%",
                        "baseline_value": max_b,
                        "user_value": max_u,
                        "codified_preference_key": "framing.punch_in_scale",
                        "codified_value": max_u,
                    })
                    set_nested(codified_preferences, "framing.punch_in_scale", max_u)

            # Punch-out (unzoom) detection: scale < 100.0 (e.g. 70-85% for graphic overlays)
            u_unzooms = [s for s in u_scales if s < 100.0]
            b_unzooms = [s for s in b_scales if s < 100.0]
            if u_unzooms and not b_unzooms:
                avg_unzoom = round(sum(u_unzooms) / len(u_unzooms), 1)
                differences.append({
                    "category": "framing",
                    "description": f"User introduced punch-outs / unzooms for graphics/overlays with avg scale {avg_unzoom}%",
                    "baseline_value": False,
                    "user_value": True,
                    "codified_preference_key": "framing.punch_out_enabled",
                    "codified_value": True,
                })
                set_nested(codified_preferences, "framing.punch_out_enabled", True)
                set_nested(codified_preferences, "framing.punch_out_scale", avg_unzoom)
            elif u_unzooms and b_unzooms:
                avg_u = round(sum(u_unzooms) / len(u_unzooms), 1)
                avg_b = round(sum(b_unzooms) / len(b_unzooms), 1)
                if abs(avg_u - avg_b) > 2.0:
                    differences.append({
                        "category": "framing",
                        "description": f"Punch-out unzoom scale tuned from {avg_b}% to {avg_u}%",
                        "baseline_value": avg_b,
                        "user_value": avg_u,
                        "codified_preference_key": "framing.punch_out_scale",
                        "codified_value": avg_u,
                    })
                    set_nested(codified_preferences, "framing.punch_out_scale", avg_u)

            # Visual cut frequency / Razor cutting
            if len(user_v2_items) != len(base_v2_items):
                differences.append({
                    "category": "timeline",
                    "description": f"Speaker Foreground clips count adjusted from {len(base_v2_items)} to {len(user_v2_items)} (visual camera angle reframing)",
                    "baseline_value": len(base_v2_items),
                    "user_value": len(user_v2_items),
                    "codified_preference_key": "timeline.visual_shot_cutting",
                    "codified_value": True,
                })
                set_nested(codified_preferences, "timeline.visual_shot_cutting", True)

    # -----------------------------------------------------------------------
    # 3. Background Blur & Opacity (Track V1)
    # -----------------------------------------------------------------------
    base_v1 = _find_track_by_name(base_vtracks, TRACK_V1_NAME)
    user_v1 = _find_track_by_name(user_vtracks, TRACK_V1_NAME)

    if base_v1 and user_v1:
        b_items = base_v1.get("items", [])
        u_items = user_v1.get("items", [])
        if b_items and u_items:
            b_blur = _extract_blur_effect_params(b_items[0]).get("blurriness", 45.0)
            u_blur = _extract_blur_effect_params(u_items[0]).get("blurriness", 45.0)
            if abs(b_blur - u_blur) > 1.0:
                differences.append({
                    "category": "framing",
                    "description": f"Background blur adjusted from {b_blur} to {u_blur}",
                    "baseline_value": b_blur,
                    "user_value": u_blur,
                    "codified_preference_key": "framing.background_blur",
                    "codified_value": u_blur,
                })
                set_nested(codified_preferences, "framing.background_blur", u_blur)

            b_op = _extract_opacity_effect_params(b_items[0]).get("opacity", 40.0)
            u_op = _extract_opacity_effect_params(u_items[0]).get("opacity", 40.0)
            if abs(b_op - u_op) > 1.0:
                differences.append({
                    "category": "framing",
                    "description": f"Background opacity adjusted from {b_op}% to {u_op}%",
                    "baseline_value": b_op,
                    "user_value": u_op,
                    "codified_preference_key": "framing.background_opacity",
                    "codified_value": u_op,
                })
                set_nested(codified_preferences, "framing.background_opacity", u_op)

    # -----------------------------------------------------------------------
    # 4. Watermark Transforms (Track V4)
    # -----------------------------------------------------------------------
    base_v4 = _find_track_by_name(base_vtracks, TRACK_V4_NAME)
    user_v4 = _find_track_by_name(user_vtracks, TRACK_V4_NAME)

    base_wm_enabled = bool(base_v4 and base_v4.get("enabled", True) and base_v4.get("items"))
    user_wm_enabled = bool(user_v4 and user_v4.get("enabled", True) and user_v4.get("items"))

    if base_wm_enabled and not user_wm_enabled:
        differences.append({
            "category": "watermark",
            "description": "User disabled or removed watermark from Track V4",
            "baseline_value": True,
            "user_value": False,
            "codified_preference_key": "watermark.enabled",
            "codified_value": False,
        })
        set_nested(codified_preferences, "watermark.enabled", False)
    elif not base_wm_enabled and user_wm_enabled:
        differences.append({
            "category": "watermark",
            "description": "User enabled or added watermark onto Track V4",
            "baseline_value": False,
            "user_value": True,
            "codified_preference_key": "watermark.enabled",
            "codified_value": True,
        })
        set_nested(codified_preferences, "watermark.enabled", True)
    elif base_wm_enabled and user_wm_enabled:
        b_wm_items = base_v4.get("items", [])
        u_wm_items = user_v4.get("items", [])
        if b_wm_items and u_wm_items:
            b_wm_motion = _extract_motion_effect_params(b_wm_items[0])
            u_wm_motion = _extract_motion_effect_params(u_wm_items[0])
            if b_wm_motion and u_wm_motion:
                b_wm_scale = round(b_wm_motion.get("scale", 28.0), 1)
                u_wm_scale = round(u_wm_motion.get("scale", 28.0), 1)
                if abs(b_wm_scale - u_wm_scale) > 0.5:
                    differences.append({
                        "category": "watermark",
                        "description": f"Watermark scale changed from {b_wm_scale}% to {u_wm_scale}%",
                        "baseline_value": b_wm_scale,
                        "user_value": u_wm_scale,
                        "codified_preference_key": "watermark.scale",
                        "codified_value": u_wm_scale,
                    })
                    set_nested(codified_preferences, "watermark.scale", u_wm_scale)

                b_wm_pos = b_wm_motion.get("position", [540.0, 280.0])
                u_wm_pos = u_wm_motion.get("position", [540.0, 280.0])
                if abs(b_wm_pos[0] - u_wm_pos[0]) > 1.0 or abs(b_wm_pos[1] - u_wm_pos[1]) > 1.0:
                    differences.append({
                        "category": "watermark",
                        "description": f"Watermark position shifted from ({b_wm_pos[0]}, {b_wm_pos[1]}) to ({u_wm_pos[0]}, {u_wm_pos[1]})",
                        "baseline_value": b_wm_pos,
                        "user_value": u_wm_pos,
                        "codified_preference_key": "watermark.position_y",
                        "codified_value": u_wm_pos[1],
                    })
                    set_nested(codified_preferences, "watermark.position_x", u_wm_pos[0])
                    set_nested(codified_preferences, "watermark.position_y", u_wm_pos[1])

    # -----------------------------------------------------------------------
    # 5. Consonant Tail Padding Heuristic (Dialogue Cuts on A1)
    # -----------------------------------------------------------------------
    base_a1 = _find_track_by_name(base_atracks, TRACK_A1_NAME)
    user_a1 = _find_track_by_name(user_atracks, TRACK_A1_NAME)

    if base_a1 and user_a1:
        b_a1_items = base_a1.get("items", [])
        u_a1_items = user_a1.get("items", [])

        # Match clips pairwise up to common count
        common_len = min(len(b_a1_items), len(u_a1_items))
        if common_len > 0:
            dur_diffs_sec = []
            for i in range(common_len):
                b_dur_ticks = b_a1_items[i].get("duration", 0)
                u_dur_ticks = u_a1_items[i].get("duration", 0)
                dur_diff_sec = ticks_to_seconds(u_dur_ticks - b_dur_ticks)
                dur_diffs_sec.append(dur_diff_sec)

            avg_dur_diff = sum(dur_diffs_sec) / len(dur_diffs_sec)
            # Detect significant uniform tail adjustment (> 15ms)
            if abs(avg_dur_diff) >= 0.015:
                base_pad = SAFE_DEFAULTS["timeline"]["consonant_padding_seconds"]
                inferred_pad = max(0.01, round(base_pad + avg_dur_diff, 3))
                differences.append({
                    "category": "timeline",
                    "description": f"Cuts consistently modified by {avg_dur_diff:+.3f}s; inferred consonant tail padding {inferred_pad}s",
                    "baseline_value": base_pad,
                    "user_value": inferred_pad,
                    "codified_preference_key": "timeline.consonant_padding_seconds",
                    "codified_value": inferred_pad,
                })
                set_nested(codified_preferences, "timeline.consonant_padding_seconds", inferred_pad)

    # -----------------------------------------------------------------------
    # 6. Total Timeline Duration Diff
    # -----------------------------------------------------------------------
    def _compute_timeline_end(tracks: List[Dict[str, Any]]) -> int:
        max_end = 0
        for tr in tracks:
            for item in tr.get("items", []):
                end_tick = item.get("start", 0) + item.get("duration", 0)
                if end_tick > max_end:
                    max_end = end_tick
        return max_end

    base_all_tracks = base_vtracks + base_atracks
    user_all_tracks = user_vtracks + user_atracks

    b_total_sec = round(ticks_to_seconds(_compute_timeline_end(base_all_tracks)), 1)
    u_total_sec = round(ticks_to_seconds(_compute_timeline_end(user_all_tracks)), 1)

    if abs(b_total_sec - u_total_sec) >= 1.0 and u_total_sec > 0:
        differences.append({
            "category": "duration",
            "description": f"Total clip duration edited from {b_total_sec}s to {u_total_sec}s",
            "baseline_value": b_total_sec,
            "user_value": u_total_sec,
            "codified_preference_key": "duration.target_seconds",
            "codified_value": u_total_sec,
        })
        set_nested(codified_preferences, "duration.target_seconds", u_total_sec)

    return {
        "differences": differences,
        "codified_preferences": codified_preferences,
        "baseline_sequence": base_seq.get("settings", {}).get("preset", "vertical"),
        "user_sequence": user_seq.get("settings", {}).get("preset", "vertical"),
    }


# ---------------------------------------------------------------------------
# CLI Command Implementations
# ---------------------------------------------------------------------------

def cmd_get(args: argparse.Namespace) -> int:
    store = PreferenceStore(args.project_dir)
    key = args.key
    val, src = store.get(key)

    if args.json:
        if key:
            print(json.dumps({"key": key, "value": val, "source_tier": src}, indent=2))
        else:
            resolved, prov = store.resolve()
            print(json.dumps({"preferences": resolved, "provenance": prov}, indent=2))
        return 0

    if key:
        if val is None and src is None:
            print(f"Key '{key}' not found in preferences.")
            return 1
        print(f"{key} = {json.dumps(val)} (source: [{src}])")
    else:
        resolved, prov = store.resolve()
        print("Resolved Hierarchical Preferences:")
        print(json.dumps(resolved, indent=2))
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    store = PreferenceStore(args.project_dir)
    scope = args.scope.lower()
    if scope not in ("project", "global"):
        sys.stderr.write("Error: --scope must be 'project' or 'global'\n")
        return 1

    parsed_value = parse_typed_value(args.value)
    store.set(args.key, parsed_value, scope=scope)

    if args.json:
        print(json.dumps({
            "status": "success",
            "key": args.key,
            "value": parsed_value,
            "scope": scope,
        }))
    else:
        print(f"Successfully set [{scope}] {args.key} = {json.dumps(parsed_value)}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    store = PreferenceStore(args.project_dir)
    resolved, provenance = store.resolve()
    flat = flatten_dict(resolved)

    if args.json:
        result = []
        for k, v in sorted(flat.items()):
            result.append({"key": k, "value": v, "source_tier": provenance.get(k, "unknown")})
        print(json.dumps(result, indent=2))
        return 0

    print("=" * 80)
    print(f"{'PREFERENCE KEY':<40} {'TIER':<12} {'VALUE'}")
    print("=" * 80)
    for k, v in sorted(flat.items()):
        tier = provenance.get(k, "default")
        val_str = json.dumps(v)
        if len(val_str) > 26:
            val_str = val_str[:23] + "..."
        print(f"{k:<40} [{tier:<8}] {val_str}")
    print("=" * 80)
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    store = PreferenceStore(args.project_dir)
    scope = args.scope.lower()
    if scope not in ("project", "global"):
        sys.stderr.write("Error: --scope must be 'project' or 'global'\n")
        return 1

    success = store.reset(args.key, scope=scope)
    msg = f"Reset {args.key or 'all preferences'} in [{scope}] scope"
    if args.json:
        print(json.dumps({"status": "success" if success else "not_found", "message": msg}))
    else:
        print(f"{msg}: {'Done' if success else 'No file or key found'}")
    return 0


def cmd_parse_feedback(args: argparse.Namespace) -> int:
    directives, proposed = parse_feedback_directives(args.text)

    if args.save:
        store = PreferenceStore(args.project_dir)
        flat = flatten_dict(proposed)
        for k, v in flat.items():
            store.set(k, v, scope=args.scope)

    output = {
        "text": args.text,
        "detected_directives_count": len(directives),
        "directives": directives,
        "proposed_preferences": proposed,
        "saved_to_scope": args.scope if args.save else None,
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"\n[Channel 1] Parsed {len(directives)} directive(s) from feedback:")
        print("-" * 70)
        for d in directives:
            print(f"• {d['directive']}: {d['explanation']}")
            print(f"  Matched text: \"{d['raw_match']}\" -> {d['key']} = {json.dumps(d['value'])}")
        print("-" * 70)
        print("Proposed Preference Updates:")
        print(json.dumps(proposed, indent=2))
        if args.save:
            print(f"\n[Saved] Codified preferences saved into [{args.scope}] scope.")
        else:
            print("\n[Notice] Pass --save to persist these updates to preferences.")
    return 0


def cmd_diff_project(args: argparse.Namespace) -> int:
    baseline = Path(args.baseline)
    user_edit = Path(args.user_edit)

    if not baseline.is_file():
        sys.stderr.write(f"Error: Baseline project not found: {baseline}\n")
        return 1
    if not user_edit.is_file():
        sys.stderr.write(f"Error: User edited project not found: {user_edit}\n")
        return 1

    try:
        diff_res = diff_project_heuristic(baseline, user_edit)
    except Exception as exc:
        sys.stderr.write(f"Error diffing projects: {exc}\n")
        return 1

    diffs = diff_res["differences"]
    codified = diff_res["codified_preferences"]

    if args.save and codified:
        store = PreferenceStore(args.project_dir)
        flat = flatten_dict(codified)
        for k, v in flat.items():
            store.set(k, v, scope=args.scope)

    output = {
        "baseline": str(baseline),
        "user_edit": str(user_edit),
        "differences_count": len(diffs),
        "differences": diffs,
        "codified_preferences": codified,
        "saved_to_scope": args.scope if args.save else None,
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"\n[Channel 2] Project Diffing Heuristic detected {len(diffs)} difference(s):")
        print("=" * 80)
        for d in diffs:
            print(f"[{d['category'].upper()}] {d['description']}")
            print(f"  Preference key: {d['codified_preference_key']} = {json.dumps(d['codified_value'])}")
        print("=" * 80)
        print("Codified Preferences Dictionary:")
        print(json.dumps(codified, indent=2))
        if args.save:
            print(f"\n[Saved] Codified preferences saved to [{args.scope}] scope.")
        else:
            print("\n[Notice] Pass --save to encode these modifications into preferences.")
    return 0


# ---------------------------------------------------------------------------
# Built-In Comprehensive Test Suite
# ---------------------------------------------------------------------------

class TestClippingPreferences(unittest.TestCase):
    """Built-in test suite verifying preference codification engine."""

    def setUp(self):
        import tempfile
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.temp_dir.name)
        self.global_dir = self.project_dir / "global_config"
        self.global_path = self.global_dir / GLOBAL_PREFERENCES_FILENAME

        # Point environment to test sandbox
        self.old_global_env = os.environ.get("CLIPPING_GLOBAL_PREFERENCES_PATH")
        os.environ["CLIPPING_GLOBAL_PREFERENCES_PATH"] = str(self.global_path)

        self.store = PreferenceStore(self.project_dir)

    def tearDown(self):
        if self.old_global_env:
            os.environ["CLIPPING_GLOBAL_PREFERENCES_PATH"] = self.old_global_env
        else:
            os.environ.pop("CLIPPING_GLOBAL_PREFERENCES_PATH", None)
        self.temp_dir.cleanup()

    def test_safe_defaults_integrity(self):
        """Ensure safe defaults contain all required keys and valid types."""
        self.assertEqual(SAFE_DEFAULTS["duration"]["target_seconds"], 45.0)
        self.assertEqual(SAFE_DEFAULTS["framing"]["default_preset"], "split_sandwich")
        self.assertEqual(SAFE_DEFAULTS["timeline"]["consonant_padding_seconds"], 0.08)
        self.assertEqual(SAFE_DEFAULTS["captions"]["words_per_line"], 3)
        self.assertEqual(SAFE_DEFAULTS["audio"]["dialogue_volume_db"], 0.0)
        self.assertTrue(SAFE_DEFAULTS["watermark"]["enabled"])

    def test_hierarchy_resolution_precedence(self):
        """Verify: Project > Campaign > Global > Safe Defaults."""
        # 1. Base default
        val, src = self.store.get("audio.bgm_volume_db")
        self.assertEqual(val, -20.0)
        self.assertEqual(src, "default")

        # 2. Global override
        self.store.set("audio.bgm_volume_db", -25.0, scope="global")
        val, src = self.store.get("audio.bgm_volume_db")
        self.assertEqual(val, -25.0)
        self.assertEqual(src, "global")

        # 3. Campaign override
        campaign_file = self.project_dir / CAMPAIGN_BRIEF_FILENAME
        with open(campaign_file, "w") as f:
            json.dump({
                "campaign_name": "Test Campaign",
                "audio": {"zero_background_music": True},
            }, f)
        # Recreate store so it discovers campaign file
        self.store = PreferenceStore(self.project_dir)
        val, src = self.store.get("audio.bgm_volume_db")
        self.assertEqual(val, -80.0)
        self.assertEqual(src, "campaign")

        # 4. Project override
        self.store.set("audio.bgm_volume_db", -15.0, scope="project")
        val, src = self.store.get("audio.bgm_volume_db")
        self.assertEqual(val, -15.0)
        self.assertEqual(src, "project")

    def test_deep_merge_and_dot_notation(self):
        """Verify deep merging and dot notation get/set/delete."""
        base = {"a": {"b": 1, "c": 2}, "d": 4}
        override = {"a": {"b": 10, "e": 3}}
        merged = deep_merge(base, override)
        self.assertEqual(merged["a"]["b"], 10)
        self.assertEqual(merged["a"]["c"], 2)
        self.assertEqual(merged["a"]["e"], 3)
        self.assertEqual(merged["d"], 4)

        d: Dict[str, Any] = {}
        set_nested(d, "x.y.z", 99)
        self.assertEqual(get_nested(d, "x.y.z"), 99)
        self.assertTrue(delete_nested(d, "x.y.z"))
        self.assertIsNone(get_nested(d, "x.y.z"))

    def test_channel_1_duration_directives(self):
        """Verify natural language duration parsing."""
        dirs, prefs = parse_feedback_directives("make it around 30 seconds")
        self.assertEqual(get_nested(prefs, "duration.target_seconds"), 30.0)

        dirs, prefs = parse_feedback_directives("target 40s")
        self.assertEqual(get_nested(prefs, "duration.target_seconds"), 40.0)

        dirs, prefs = parse_feedback_directives("keep it between 25 and 45 seconds")
        self.assertEqual(get_nested(prefs, "duration.target_seconds"), 35.0)
        self.assertEqual(get_nested(prefs, "duration.min_seconds"), 25.0)
        self.assertEqual(get_nested(prefs, "duration.max_seconds"), 45.0)

    def test_channel_1_framing_and_layout_directives(self):
        """Verify natural language speaker crop and layout directives."""
        dirs, prefs = parse_feedback_directives("center on host")
        self.assertEqual(get_nested(prefs, "framing.speaker_anchor_x"), 0.25)
        self.assertEqual(get_nested(prefs, "framing.speaker_anchor_y"), 0.45)

        dirs, prefs = parse_feedback_directives("crop to guest")
        self.assertEqual(get_nested(prefs, "framing.speaker_anchor_x"), 0.75)

        dirs, prefs = parse_feedback_directives("use stacked split layout")
        self.assertEqual(get_nested(prefs, "framing.default_preset"), "stacked_split")

        dirs, prefs = parse_feedback_directives("disable punch ins")
        self.assertFalse(get_nested(prefs, "framing.punch_in_enabled"))

        dirs, prefs = parse_feedback_directives("increase punch in zoom to 215%")
        self.assertEqual(get_nested(prefs, "framing.punch_in_scale"), 215.0)

    def test_channel_1_captions_directives(self):
        """Verify subtitle words per line, typography and color parsing."""
        dirs, prefs = parse_feedback_directives("one word at a time, highlight color gold")
        self.assertEqual(get_nested(prefs, "captions.words_per_line"), 1)
        self.assertEqual(get_nested(prefs, "captions.highlight_color"), "#FFD700")

        dirs, prefs = parse_feedback_directives("2 words per line, font size 64, highlight color #00FFCC")
        self.assertEqual(get_nested(prefs, "captions.words_per_line"), 2)
        self.assertEqual(get_nested(prefs, "captions.font_size"), 64)
        self.assertEqual(get_nested(prefs, "captions.highlight_color"), "#00FFCC")

    def test_channel_1_audio_and_padding_directives(self):
        """Verify audio volume and cut padding directives."""
        dirs, prefs = parse_feedback_directives("lower sfx volume to -6db and mute bgm")
        self.assertEqual(get_nested(prefs, "audio.sfx_volume_db"), -6.0)
        self.assertEqual(get_nested(prefs, "audio.bgm_volume_db"), -80.0)

        dirs, prefs = parse_feedback_directives("consonant padding 0.12s, silence threshold 0.35s")
        self.assertEqual(get_nested(prefs, "timeline.consonant_padding_seconds"), 0.12)
        self.assertEqual(get_nested(prefs, "timeline.silence_threshold_seconds"), 0.35)

    def _create_mock_remotion_project(
        self,
        bgm_vol: float = -20.0,
        sfx_vol: float = -2.0,
        speaker_anchor: Tuple[float, float] = (960.0, 540.0),
        v2_scale: float = 177.7778,
        punch_in: bool = True,
        blur: float = 45.0,
        watermark_scale: float = 28.0,
        clip_dur_sec: float = 10.0,
    ) -> Dict[str, Any]:
        """Helper to create minimal valid .remotion.json AST for diff testing."""
        dur_ticks = seconds_to_ticks(clip_dur_sec)

        v1_item = {
            "id": 101,
            "start": 0,
            "duration": dur_ticks,
            "effects": [
                {"effect": "gaussian_blur", "params": {"blurriness": {"value": {"Float": blur}}}},
                {"effect": "opacity", "params": {"opacity": {"value": {"Float": 40.0}}}},
            ],
        }

        v2_items = [
            {
                "id": 102,
                "start": 0,
                "duration": dur_ticks // 2,
                "effects": [
                    {
                        "effect": "motion",
                        "params": {
                            "scale": {"value": {"Float": v2_scale}},
                            "anchor": {"value": {"Vec2": list(speaker_anchor)}},
                            "position": {"value": {"Vec2": [540.0, 960.0]}},
                        },
                    }
                ],
            },
            {
                "id": 103,
                "start": dur_ticks // 2,
                "duration": dur_ticks // 2,
                "effects": [
                    {
                        "effect": "motion",
                        "params": {
                            "scale": {"value": {"Float": (199.1111 if punch_in else v2_scale)}},
                            "anchor": {"value": {"Vec2": list(speaker_anchor)}},
                            "position": {"value": {"Vec2": [540.0, 960.0]}},
                        },
                    }
                ],
            },
        ]

        v4_item = {
            "id": 104,
            "start": 0,
            "duration": dur_ticks,
            "effects": [
                {
                    "effect": "motion",
                    "params": {
                        "scale": {"value": {"Float": watermark_scale}},
                        "position": {"value": {"Vec2": [540.0, 280.0]}},
                    },
                }
            ],
        }

        a1_items = [
            {"id": 105, "start": 0, "duration": dur_ticks // 2},
            {"id": 106, "start": dur_ticks // 2, "duration": dur_ticks // 2},
        ]

        seq = {
            "settings": {"preset": "1080x1920 30"},
            "video_tracks": [
                {"name": TRACK_V1_NAME, "items": [v1_item]},
                {"name": TRACK_V2_NAME, "items": v2_items},
                {"name": TRACK_V3_NAME, "items": []},
                {"name": TRACK_V4_NAME, "items": [v4_item], "enabled": True},
            ],
            "audio_tracks": [
                {"name": TRACK_A1_NAME, "volume_db": 0.0, "items": a1_items},
                {"name": TRACK_A2_NAME, "volume_db": bgm_vol, "items": []},
                {"name": TRACK_A3_NAME, "volume_db": sfx_vol, "items": []},
            ],
        }

        return {
            "format": "remotion.project",
            "schema_version": 2,
            "project": {"items": {"8": {"kind": {"Sequence": seq}}}},
            "view": {"active_sequence": 8},
        }

    def test_channel_2_project_diffing_heuristic(self):
        """Verify Channel 2 diffing extracts track volume, anchor, blur, and timeline modifications."""
        baseline_data = self._create_mock_remotion_project(
            bgm_vol=-20.0,
            sfx_vol=-2.0,
            speaker_anchor=(960.0, 540.0),
            blur=45.0,
            clip_dur_sec=20.0,
        )
        user_data = self._create_mock_remotion_project(
            bgm_vol=-24.0,
            sfx_vol=-6.0,
            speaker_anchor=(480.0, 486.0),  # x_c=0.25, y_c=0.45 (Host framing)
            blur=60.0,
            watermark_scale=25.0,
            clip_dur_sec=16.0,  # Duration trimmed from 20s to 16s
        )

        base_file = self.project_dir / "baseline.remotion.json"
        user_file = self.project_dir / "user_edit.remotion.json"
        save_json_file(base_file, baseline_data)
        save_json_file(user_file, user_data)

        diff_res = diff_project_heuristic(base_file, user_file)
        diffs = diff_res["differences"]
        codified = diff_res["codified_preferences"]

        # Check detected diffs
        self.assertGreater(len(diffs), 0)
        self.assertEqual(get_nested(codified, "audio.bgm_volume_db"), -24.0)
        self.assertEqual(get_nested(codified, "audio.sfx_volume_db"), -6.0)
        self.assertEqual(get_nested(codified, "framing.speaker_anchor_x"), 0.25)
        self.assertEqual(get_nested(codified, "framing.speaker_anchor_y"), 0.45)
        self.assertEqual(get_nested(codified, "framing.background_blur"), 60.0)
        self.assertEqual(get_nested(codified, "watermark.scale"), 25.0)
        self.assertEqual(get_nested(codified, "duration.target_seconds"), 16.0)

    def test_cli_get_set_reset_workflow(self):
        """Verify CLI commands function cleanly."""
        # Set project preference
        self.store.set("captions.font_size", 80, scope="project")
        val, src = self.store.get("captions.font_size")
        self.assertEqual(val, 80)
        self.assertEqual(src, "project")

        # Reset key
        self.assertTrue(self.store.reset("captions.font_size", scope="project"))
        val, src = self.store.get("captions.font_size")
        self.assertEqual(val, 72)  # Falls back to default
        self.assertEqual(src, "default")


def run_unit_tests() -> int:
    """Run built-in test suite."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestClippingPreferences)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


# ---------------------------------------------------------------------------
# Main CLI Router
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dual-Channel Preference Codification Engine for Antigravity Clipping Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # get
    get_p = subparsers.add_parser("get", help="Get a resolved preference key or entire hierarchy")
    get_p.add_argument("key", nargs="?", default=None, help="Dot-notation key (e.g. audio.bgm_volume_db)")
    get_p.add_argument("--project-dir", "-p", default=None, help="Project directory (default: current directory)")
    get_p.add_argument("--json", action="store_true", help="Output raw JSON")

    # set
    set_p = subparsers.add_parser("set", help="Set a preference value in project or global scope")
    set_p.add_argument("key", help="Dot-notation key (e.g. framing.speaker_anchor_x)")
    set_p.add_argument("value", help="Value to set (parsed as bool, int, float, json, or string)")
    set_p.add_argument("--scope", "-s", choices=["project", "global"], default="project", help="Scope tier (default: project)")
    set_p.add_argument("--project-dir", "-p", default=None, help="Project directory")
    set_p.add_argument("--json", action="store_true", help="Output JSON response")

    # list
    list_p = subparsers.add_parser("list", help="List all preferences with source tier provenance")
    list_p.add_argument("--project-dir", "-p", default=None, help="Project directory")
    list_p.add_argument("--json", action="store_true", help="Output as JSON list")

    # reset
    reset_p = subparsers.add_parser("reset", help="Reset a key or entire file in specified scope")
    reset_p.add_argument("key", nargs="?", default=None, help="Key to reset (omit to reset entire scope file)")
    reset_p.add_argument("--scope", "-s", choices=["project", "global"], default="project", help="Scope tier")
    reset_p.add_argument("--project-dir", "-p", default=None, help="Project directory")
    reset_p.add_argument("--json", action="store_true", help="Output JSON response")

    # parse-feedback
    fb_p = subparsers.add_parser("parse-feedback", help="Channel 1: Parse natural language feedback directives")
    fb_p.add_argument("--text", "-t", required=True, help="Natural language feedback text")
    fb_p.add_argument("--project-dir", "-p", default=None, help="Project directory")
    fb_p.add_argument("--scope", "-s", choices=["project", "global"], default="project", help="Scope to save into")
    fb_p.add_argument("--save", action="store_true", help="Persist parsed preferences into specified scope")
    fb_p.add_argument("--json", action="store_true", help="Output JSON response")

    # diff-project
    diff_p = subparsers.add_parser("diff-project", help="Channel 2: Heuristic diffing between baseline and user .remotion.json")
    diff_p.add_argument("--baseline", "-b", required=True, help="Path to agent-generated baseline .remotion.json")
    diff_p.add_argument("--user-edit", "-u", required=True, help="Path to user-saved .remotion.json")
    diff_p.add_argument("--project-dir", "-p", default=None, help="Project directory")
    diff_p.add_argument("--scope", "-s", choices=["project", "global"], default="project", help="Scope to save into")
    diff_p.add_argument("--save", action="store_true", help="Persist codified preferences into specified scope")
    diff_p.add_argument("--json", action="store_true", help="Output JSON response")

    # test
    subparsers.add_parser("test", help="Run the built-in test suite")

    args = parser.parse_args()

    if args.subcommand == "get":
        return cmd_get(args)
    elif args.subcommand == "set":
        return cmd_set(args)
    elif args.subcommand == "list":
        return cmd_list(args)
    elif args.subcommand == "reset":
        return cmd_reset(args)
    elif args.subcommand == "parse-feedback":
        return cmd_parse_feedback(args)
    elif args.subcommand == "diff-project":
        return cmd_diff_project(args)
    elif args.subcommand == "test":
        return run_unit_tests()
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
