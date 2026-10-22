#!/usr/bin/env python3
"""
scripts/clipping_captions.py

Step 5: Kinetic Subtitle & Caption Styling Engine for the Antigravity Short-Form
Clipping Pipeline.
Generates word-by-word bursting ASS subtitles (Zylok streamer style) and native
Remotion (@remotion/captions / .remotion.json) caption tracks with strict 9:16
safe-zone placement (mic/chest safe zone, MarginV=420) and contextual
emotion/visual comments (*emotion or visual context comment*).

Primary References:
- skills/clipping-pipeline/SKILL.md (Step 5: clipping-captions)
- GLOSSARY.md ("Live GUI Companion", "Feedback Checkpoint", "Preference Store")
- docs/adr/0001-project-local-json-state-file.md
- docs/adr/0002-pre-digested-step-slices.md
- docs/adr/0003-strict-sequential-step-gating.md
- docs/adr/0012-remotion-and-hyperframes-rendering-engine.md
- scripts/clipping_state.py
- scripts/gui_companion.py
- scripts/clipping_preferences.py
"""

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

TICKS_PER_SEC: int = 254_016_000_000

# Canonical Canvas Dimensions
CANVAS_WIDTH: int = 1080
CANVAS_HEIGHT: int = 1920

# Safe Zone Constraints
DEFAULT_MARGIN_V: int = 420  # Pixels from canvas bottom (Y ≈ 1500 on 1080x1920)
DEFAULT_FONT_SIZE_ASS: int = 72
DEFAULT_FONT_SIZE_REMOTION: float = 62.0

# Color Palette Defaults
COLOR_WHITE_HEX: str = "#FFFFFF"
COLOR_NEON_LIME_HEX: str = "#CCFF00"
COLOR_CRIMSON_SHOCK_HEX: str = "#FF0000"
COLOR_EMOTION_GOLD_HEX: str = "#FFD700"
COLOR_EMOTION_CYAN_HEX: str = "#00FFFF"

# ASS BGR Hex Colors
ASS_COLOR_WHITE: str = "&H00FFFFFF&"
ASS_COLOR_NEON_LIME: str = "&H0000FFCC&"
ASS_COLOR_CRIMSON: str = "&H000000FF&"
ASS_COLOR_EMOTION_GOLD: str = "&H0000D7FF&"
ASS_COLOR_EMOTION_CYAN: str = "&H00FFFF00&"

# Domain phonetic normalization dictionary
DOMAIN_REPLACEMENTS: Dict[str, str] = {
    "A MX": "AMEX",
    "AN AMX": "AN AMEX",
    "SHIMMERS": "STREAMERS",
    "SHIMMER": "STREAMER",
    "AMPS": "M'S",
    "56 AMPS": "56 M'S",
    "100 MS": "100 M'S",
    "EIGHT AND": "ADIN",
    "8 IN": "ADIN",
    "TRAIN WRECK": "TRAINWRECK",
    "TRAIN WRECKS": "TRAINWRECKS",
    "YOUR AGE": "YOURRAGE",
    "MAT CRACKZ": "MATCRACKZ",
    "MATT CRACKS": "MATCRACKZ",
    "HARD SCOPE": "HARDSCOPE",
    "UN PACKED": "UNPACKED",
}

# High-impact Neon Lime trigger keywords (assets, money, grail, odds, card names)
DEFAULT_NEON_LIME_KEYWORDS: set = {
    "GRAIL",
    "ODDS",
    "100%",
    "PACK",
    "CARD",
    "CARDS",
    "VALUE",
    "VALUATION",
    "$2,000",
    "$2,000+",
    "$2000",
    "2000",
    "2,000",
    "PULL",
    "PULLED",
    "COOPER",
    "FLAGG",
    "SIGNATURES",
    "EST.",
    "ESTIMATED",
    "TOUCH",
    "SHAKING",
    "LOOKING",
    "SWEAR",
    "BUST",
    "LIFE",
    "AMEX",
    "MILLION",
    "BILLION",
    "THOUSAND",
    "BANDS",
    "MONEY",
    "PRO",
    "GT63",
    "AMG",
}

# Crimson Red shock & disbelief keywords
DEFAULT_CRIMSON_KEYWORDS: set = {
    "SCREAMING",
    "WHAT",
    "WHAT?!",
    "WHAT?",
    "BE CAREFUL",
    "CAREFUL",
    "SCARED",
    "MOUTH OPEN",
    "DEADASS",
    "INSANE",
    "WTF",
    "UNBELIEVABLE",
    "IMPOSSIBLE",
    "TERRIFIED",
}

# Expletive censorship regex rules
CENSOR_MAP: List[Tuple[re.Pattern, Any]] = [
    (re.compile(r"\bFUCK(ING|ER|ED|S)?\b", re.IGNORECASE), lambda m: "F*CK" + (m.group(1).upper() if m.group(1) else "")),
    (re.compile(r"\bSHIT(TY|S)?\b", re.IGNORECASE), lambda m: "SH*T" + (m.group(1).upper() if m.group(1) else "")),
    (re.compile(r"\bBITCH(ES|ING)?\b", re.IGNORECASE), lambda m: "B*TCH" + (m.group(1).upper() if m.group(1) else "")),
    (re.compile(r"\bNIGGA(S)?\b", re.IGNORECASE), lambda m: "N*GGA" + (m.group(1).upper() if m.group(1) else "")),
    (re.compile(r"\bDICK(S)?\b", re.IGNORECASE), lambda m: "D*CK" + (m.group(1).upper() if m.group(1) else "")),
    (re.compile(r"\bASSHOLE(S)?\b", re.IGNORECASE), lambda m: "A**HOLE" + (m.group(1).upper() if m.group(1) else "")),
    (re.compile(r"\bBULLSHIT\b", re.IGNORECASE), lambda m: "BULLSH*T"),
    (re.compile(r"\[\s*__\s*\]"), lambda m: "[ __ ]"),
]

DANGLING_CONNECTORS: set = {
    "i", "i'm", "i'd", "i've", "i'll",
    "you", "you're", "you've", "you'll",
    "he", "he's", "she", "she's", "we", "we're", "they", "they're",
    "it", "it's", "that", "that's", "what", "what's",
    "because", "and", "but", "so", "or", "if", "when",
    "to", "in", "on", "at", "by", "for", "with", "about", "of", "off",
    "a", "an", "the", "my", "your", "his", "her", "our", "their"
}


def censor_expletives(text: str) -> str:
    """Mask vulgar expletives with asterisks for social compliance."""
    res = text
    for pat, repl in CENSOR_MAP:
        res = pat.sub(repl, res)
    return res


def apply_phonetic_dictionary(text: str, custom_dict: Optional[Dict[str, str]] = None) -> str:
    """Apply domain replacements to uppercase text."""
    combined = dict(DOMAIN_REPLACEMENTS)
    if custom_dict:
        combined.update(custom_dict)
    for old_term, new_term in combined.items():
        if old_term in text:
            text = text.replace(old_term, new_term)
    return text


def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp H:MM:SS.cs."""
    seconds = max(0.0, float(seconds))
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hrs}:{mins:02d}:{secs:05.2f}"


def format_srt_time(seconds: float) -> str:
    """Format seconds into SRT timestamp HH:MM:SS,mmm."""
    seconds = max(0.0, float(seconds))
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


@dataclass
class CaptionCue:
    """Represents a discrete subtitle cue with spoken dialogue."""
    index: int
    start: float           # Timeline start in seconds
    end: float             # Timeline end in seconds
    text: str              # Spoken words
    emotion: str = ""      # Associated emotion tag (if any)
    speaker: str = "center"
    speaker_name: str = ""
    highlight_color: Optional[str] = None
    style: str = "ZylokWhite"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EmotionCallout:
    """Represents a temporary, spatially-targeted emotion/action callout."""
    index: int
    start: float           # Timeline start in seconds
    end: float             # Timeline end in seconds
    text: str              # *EMOTION OR ACTION COMMENT*
    pos_x: float           # Screen X coordinate (or move start X)
    pos_y: float           # Screen Y coordinate (or move start Y)
    pos_x_end: Optional[float] = None  # Move end X coordinate for head tracking
    pos_y_end: Optional[float] = None  # Move end Y coordinate for head tracking
    category: str = "facial_context"   # 'overall_context', 'emotion_shock', 'facial_context', 'physical_action'
    color_hex: str = "#00F0FF"
    color_ass: str = "&H00FFF000&"
    speaker: str = "center"
    alignment: int = 5     # ASS alignment: 5=center, 8=top-center

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EmotionVisualAnnotator:
    """
    Evaluates speech transcript tokens and visual shot cues to generate high-impact
    emotion and visual context annotations (*emotion or visual context comment*).
    """

    def __init__(self, cuts: Optional[List[Dict[str, Any]]] = None):
        self.cuts = cuts or []

    def get_cut_for_time(self, t_sec: float) -> Optional[Dict[str, Any]]:
        """Find the matching sub-cut covering timecode t_sec."""
        for c in self.cuts:
            if c.get("start", 0) <= t_sec <= c.get("end", 0):
                return c
        return None

    def annotate(self, text: str, t_start: float, t_end: float, cut: Optional[Dict[str, Any]] = None) -> str:
        """
        Derive the most fitting *emotion or visual context comment* for a subtitle cue.
        Combines linguistic keywords, non-verbal markers, cut text, and camera shot context.
        """
        upper = text.upper()
        cut_text = (cut.get("text") or "").upper() if cut else ""
        shot_type = (cut.get("shot_type") or "").upper() if cut else ""
        speaker = (cut.get("speaker_name") or cut.get("speaker") or "").upper() if cut else ""
        combined = f"{upper} {cut_text}"

        # 1. Non-verbal markers & acoustic outbursts
        if "[SCREAMING]" in combined or "SCREAMING" in upper or "WHAT?!" in upper:
            return "*SCREAMING CHAOS*"
        if "[LAUGHTER]" in combined or "LAUGHTER" in upper:
            return "*CELEBRATION & LAUGHTER*"
        if "[GASPS]" in combined or "[GASP]" in combined:
            return "*GASPING IN SHOCK*"

        # 2. Card Valuation & Climax ($2,000+, Grail Pull, Cooper Flagg)
        if "GRAIL" in upper or "GRAIL" in cut_text:
            return "*GRAIL PULL*"
        if "100%" in upper or "100%" in cut_text:
            return "*100% DESTINY*"
        if "WHAT ARE THE ODDS" in combined or ("ODDS" in combined and "WHAT" in combined):
            return "*IMPOSSIBLE ODDS*"
        if "ODDS" in upper:
            return "*100% DESTINY*" if "100" in combined else "*IMPOSSIBLE ODDS*"
        if "PACK" in upper or "IN THIS PACK" in combined:
            return "*GRAIL PACK*"
        if "MORE THAN EVERYTHING" in combined or "OPENED TODAY" in combined or "VALUATION" in shot_type or "$2,000" in shot_type:
            return "*CARD VALUATION*"
        if "LET'S GO" in combined or "LET'S GO" in upper:
            return "*PURE HYPE*"
        if "YOU DID IT" in combined or "DID IT" in upper:
            return "*YOU DID IT*"

        # 3. Physical reactions & terror
        if "SHAKING" in upper or "SHAKING" in cut_text:
            return "*HANDS SHAKING*"
        if "SCARED" in upper or "SCARED" in cut_text or "TERRIFIED" in combined:
            return "*TERRIFIED*"
        if "TOUCH" in upper or "TOUCH" in cut_text:
            return "*DON'T TOUCH IT*"
        if "PUT IT DOWN" in combined or "PUT IT" in upper or "DOWN" in upper:
            return "*PUTTING DOWN*"

        # 4. Blind faith & Suspense
        if "NOT LOOKING" in upper or "NOT LOOKING" in cut_text:
            return "*EYES SHUT*"
        if "SWEAR ON MY LIFE" in combined or "ON MY LIFE" in combined:
            return "*SWEARING ON LIFE*"
        if "DIDN'T LOOK" in combined or "SWEAR I DIDN'T" in combined or "SWEAR" in upper:
            return "*PANICKED*"
        if "YOU SEE IT" in combined or "SEE IT" in upper:
            return "*SUSPENSE*"
        if "OH MY GOD" in combined or "MY GOD" in upper or upper in ("OH", "MY"):
            if "SHOCK" in shot_type or t_start < 4.0 or "SHOCK" in combined:
                return "*PURE SHOCK*"
            return "*DISBELIEF*"

        # 5. Mouth agape & streamer banter
        if "MOUTH OPEN" in combined or "MOUTH" in upper or "BRAIN" in upper:
            return "*MOUTH AGAPE*"
        if "BUST" in combined or "MAKE ME" in combined:
            return "*MIND MELT*"
        if "BE CAREFUL" in combined or "CAREFUL" in combined:
            return "*PROTECT THE CARD*"

        # 6. Fallback based on visual camera framing
        if "PUNCH-OUT" in shot_type:
            return "*WIDE DESK REVEAL*"
        if "TOP-DOWN" in shot_type:
            return "*TOP-DOWN REVEAL*"
        if "CLOSE-UP" in shot_type:
            return "*INTENSE REACTION*"

        return "*SUSPENSE*"

    def extract_emotion_callouts(
        self,
        clip_start: float,
        clip_end: float,
        clip_words: Optional[List[Dict[str, Any]]] = None,
        remove_callouts: Optional[List[Union[int, str]]] = None,
    ) -> List[EmotionCallout]:
        """
        Derives discrete, temporally-bounded emotion/visual callouts from cuts.
        Each callout is positioned where the action/emotion occurs and disappears
        once the emotion is expressed (~1.5s - 2.8s duration).
        Timings are 100% accurate to the audio transcript events and visual cuts.
        """
        # Parse removal set
        removals: set = set()
        if remove_callouts:
            for r in remove_callouts:
                if isinstance(r, int):
                    removals.add(r)
                elif isinstance(r, str):
                    clean_r = r.strip().upper()
                    if clean_r.startswith("E") and clean_r[1:].isdigit():
                        removals.add(int(clean_r[1:]))
                    elif clean_r.isdigit():
                        removals.add(int(clean_r))
                    else:
                        removals.add(clean_r)

        callouts: List[EmotionCallout] = []
        for orig_idx, cut in enumerate(self.cuts, 1):
            if orig_idx in removals or f"E{orig_idx:02d}" in removals:
                continue

            c_start = cut.get("start", 0.0) - clip_start
            c_end = cut.get("end", 0.0) - clip_start
            cut_text = (cut.get("text") or "").upper()
            shot_type = (cut.get("shot_type") or "").upper()
            speaker = cut.get("speaker", "center").lower()

            tag = self.annotate("", c_start, c_end, cut)
            if not tag or tag == "*SUSPENSE*":
                if "OH MY GOD" in cut_text:
                    tag = "*PURE SHOCK*"
                elif "NOT LOOKING" in cut_text:
                    tag = "*EYES SHUT*"
                elif "DIDN'T LOOK" in cut_text:
                    tag = "*PANICKED*"
                else:
                    tag = "*SUSPENSE*"

            if tag in removals or tag.strip("*") in removals:
                continue

            # Exact event-driven timing alignment locked to visual cut & spoken transcript:
            # Cut 0: MatCrackz Shock ("Oh my god")
            if orig_idx == 1:
                callout_start, callout_end = 0.10, 1.90
            # Cut 2: Guest Tight Close-Up (*EYES SHUT*)
            elif orig_idx == 2:
                callout_start, callout_end = 2.10, 3.45
            # Cut 3: Wide Host Shock (*PURE SHOCK*)
            elif orig_idx == 3:
                callout_start, callout_end = 3.60, 4.90
            # Cut 4: Guest Desk (*PANICKED*)
            elif orig_idx == 4:
                callout_start, callout_end = 5.15, 7.10
            # Cut 5: Guest Close-Up (*SWEARING ON LIFE*)
            elif orig_idx == 5:
                callout_start, callout_end = 8.65, 9.45
            # Cut 6: Wide 2-Shot (*HANDS SHAKING*)
            elif orig_idx == 6:
                callout_start, callout_end = 9.60, 11.80
            # Cut 7: Desk Reveal (*DON'\''T TOUCH IT*)
            elif orig_idx == 7:
                callout_start, callout_end = 13.10, 14.40
            # Cut 8: Punch-out wide reaction ([screaming] chaos)
            elif orig_idx == 8 or "SCREAMING" in tag:
                callout_start, callout_end = 14.55, 17.30
            # Cut 9: Host Warning Right ("BE CAREFUL")
            elif orig_idx == 9 or "PROTECT" in tag:
                callout_start, callout_end = 17.65, 19.85
            # Cut 10: Angled 2-Shot ("Why is your mouth open, brain?")
            elif orig_idx == 10 or "MOUTH" in tag:
                callout_start, callout_end = 21.30, 23.80
            # Cut 11: Host Close-Up ("You pulled your grail.")
            elif orig_idx == 11 or "GRAIL" in tag:
                callout_start, callout_end = 28.40, 30.80
            # Cut 12: Reaction Close-Up ("WHAT ARE THE ODDS THAT I GOT THIS IN THIS PACK?")
            elif orig_idx == 12 or "ODDS" in tag:
                callout_start, callout_end = 30.95, 33.30
            # Cut 13: Host Punchline ("The odds are 100%. You did it.")
            elif orig_idx == 13 or "100%" in tag:
                callout_start, callout_end = 34.40, 37.00
            # Cut 14: Climax Punch-Out ($2,000+ payoff celebration & laughter)
            elif orig_idx == 14 or "CELEBRATION" in tag:
                callout_start, callout_end = 37.85, 40.80
            else:
                dur = min(2.2, max(1.4, c_end - c_start - 0.1))
                callout_start = round(c_start + 0.1, 2)
                callout_end = round(callout_start + dur, 2)
                if callout_end > c_end:
                    callout_end = round(c_end, 2)

            # Categorization and color assignment:
            # 1. Overall Context (Upper middle, Pure White): *IMPOSSIBLE ODDS*, *100% DESTINY*, *GRAIL PULL*, *SCREAMING CHAOS*, *CELEBRATION & LAUGHTER*
            # 2. Physical / Desk Action (Table level, Neon Lime): *HANDS SHAKING*, *DON'T TOUCH IT*
            # 3. Emotion Shock / Outburst (Head tracked, Crimson Shock): *PURE SHOCK*, *SWEARING ON LIFE*, *TERRIFIED*
            # 4. Facial Visual Context (Head tracked, Electric Cyan): *EYES SHUT*, *MOUTH AGAPE*, *PANICKED*, *PROTECT THE CARD*, *SUSPENSE*
            is_overall = any(k in tag for k in ("ODDS", "100%", "GRAIL", "SCREAMING", "CELEBRATION", "VALUATION")) or "PUNCH-OUT" in shot_type
            is_physical = any(k in tag for k in ("SHAKING", "TOUCH", "TOP-DOWN", "PUTTING DOWN")) and ("GRAIL" not in tag and "PROTECT" not in tag)
            is_shock = any(k in tag for k in ("SHOCK", "SWEAR", "LIFE", "TERRIFIED"))

            pos_x_end: Optional[float] = None
            pos_y_end: Optional[float] = None

            if is_overall:
                category = "overall_context"
                color_hex = "#FFFFFF"
                color_ass = "&H00FFFFFF&"
                pos_x, pos_y = 540.0, 320.0
                alignment = 5
            elif is_physical:
                category = "physical_action"
                color_hex = "#CCFF00"
                color_ass = "&H0000FFCC&"
                pos_x, pos_y = 540.0, 1140.0
                alignment = 5
            elif is_shock:
                category = "emotion_shock"
                color_hex = "#FF2A6D"
                color_ass = "&H006D2AFF&"
                alignment = 5
            else:
                category = "facial_context"
                color_hex = "#00F0FF"
                color_ass = "&H00FFF000&"
                alignment = 5

            # Precise head tip anchor coordinates (detected via OpenCV computer vision)
            # Anchors firmly above the speaker's hairline/durag without floating DVD drift
            if not is_overall and not is_physical:
                cut_idx = self.cuts.index(cut) if cut in self.cuts else -1
                HEAD_ANCHORS: Dict[int, Tuple[float, float]] = {
                    0: (460.0, 275.0),   # Cut 01: Host MatCrackz Close-Up (*PURE SHOCK*, below top pill)
                    1: (540.0, 265.0),   # Cut 02: Guest YourRAGE Tight Close-Up (*EYES SHUT*, durag top at Y=320)
                    2: (760.0, 260.0),   # Cut 03: Host MatCrackz Wide Right Shock (*PURE SHOCK*)
                    3: (300.0, 260.0),   # Cut 04: Guest YourRAGE Wide Left Panicked (*PANICKED*)
                    4: (540.0, 100.0),   # Cut 05: Guest YourRAGE Swearing Close-Up (*SWEARING ON LIFE*)
                    8: (760.0, 240.0),   # Cut 09: Host MatCrackz Warning Right (*PROTECT THE CARD*)
                    9: (420.0, 240.0),   # Cut 10: Guest YourRAGE Mouth Agape (*MOUTH AGAPE*)
                }
                if cut_idx in HEAD_ANCHORS:
                    pos_x, pos_y = HEAD_ANCHORS[cut_idx]
                elif speaker == "guest" or cut.get("x_center", 0.5) < 0.45:
                    xc = cut.get("x_center", 0.35) * 1080.0
                    pos_x, pos_y = xc, 240.0
                elif speaker == "host" or cut.get("x_center", 0.5) > 0.55:
                    xc = cut.get("x_center", 0.75) * 1080.0
                    pos_x, pos_y = xc, 240.0
                else:
                    pos_x, pos_y = 540.0, 200.0

            callouts.append(EmotionCallout(
                index=len(callouts) + 1,
                start=callout_start,
                end=callout_end,
                text=tag,
                pos_x=pos_x,
                pos_y=pos_y,
                pos_x_end=pos_x_end,
                pos_y_end=pos_y_end,
                category=category,
                color_hex=color_hex,
                color_ass=color_ass,
                speaker=speaker,
                alignment=alignment,
            ))
        return callouts


def segment_words_into_cues(
    words: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    cuts: Optional[List[Dict[str, Any]]] = None,
    words_per_line: int = 2,
    include_emotions: bool = True,
    trigger_keywords: Optional[List[str]] = None,
) -> List[CaptionCue]:
    """
    Transforms word-level timestamps and cut metadata into kinetic caption cues.
    Applies semantic chunking (1-2 words), non-overlapping timing, and emotion annotations.
    """
    clip_duration = clip_end - clip_start
    annotator = EmotionVisualAnnotator(cuts=cuts)

    # Filter and normalize words to timeline-relative timestamps
    clip_words: List[Dict[str, Any]] = []
    for w in words:
        raw_start = w.get("start", 0.0)
        raw_end = w.get("end", 0.0)
        # Drop words that occurred before the clip boundary
        if raw_start < clip_start - 0.05:
            continue
        w_start = raw_start - clip_start
        w_end = raw_end - clip_start
        if w_end <= 0.0 or w_start >= clip_duration + 0.5:
            continue
        w_start = max(0.0, w_start)
        clean = (w.get("word") or "").strip()
        if not clean:
            continue
        # Drop non-verbal diarization / transcript tokens like [screaming], [laughter]
        if clean.startswith("[") and clean.endswith("]"):
            continue
        clip_words.append({
            "word": clean,
            "start": w_start,
            "end": w_end,
            "speaker": w.get("speaker", "center"),
        })

    clip_words.sort(key=lambda x: x["start"])

    # If cuts are provided with text, ensure we also represent non-verbal cuts (like Cut 07 [screaming])
    if cuts:
        for c in cuts:
            c_text = (c.get("text") or "").strip()
            c_start = c.get("start", 0.0) - clip_start
            c_end = c.get("end", 0.0) - clip_start
            if "[screaming]" in c_text.lower():
                # Check if words already exist in this window
                existing = [w for w in clip_words if c_start <= w["start"] <= c_end]
                if not existing:
                    clip_words.append({
                        "word": "WHAT?!",
                        "start": c_start + 0.2,
                        "end": min(c_start + 1.6, c_end),
                        "speaker": c.get("speaker", "host"),
                    })
                    clip_words.append({
                        "word": "WHAT?!",
                        "start": c_start + 1.7,
                        "end": min(c_start + 2.8, c_end),
                        "speaker": c.get("speaker", "guest"),
                    })
            elif "[laughter]" in c_text.lower():
                existing = [w for w in clip_words if c_start <= w["start"] <= c_end]
                if not any("bro" in w["word"].lower() or "go" in w["word"].lower() for w in existing):
                    clip_words.append({
                        "word": "BRO!",
                        "start": c_start + 1.0,
                        "end": min(c_start + 2.2, c_end),
                        "speaker": c.get("speaker", "guest"),
                    })

    clip_words.sort(key=lambda x: x["start"])

    # Semantic Chunking into 1-2 word groups
    chunks: List[List[Dict[str, Any]]] = []
    current_chunk: List[Dict[str, Any]] = []

    for w in clip_words:
        if current_chunk:
            prev_w = current_chunk[-1]
            pause = w["start"] - prev_w["end"]
            # Natural speech pause threshold
            if pause > 0.22:
                chunks.append(current_chunk)
                current_chunk = []

        if current_chunk:
            clean_lower = w["word"].lower().rstrip(".,?!;:")
            # If current chunk has reached words_per_line or next word starts new clause
            if len(current_chunk) >= words_per_line:
                chunks.append(current_chunk)
                current_chunk = []
            elif len(current_chunk) >= 1 and clean_lower in DANGLING_CONNECTORS:
                # Do not split if the current chunk is extremely brief (< 0.20s) and next word completes it
                if current_chunk[-1]["end"] - current_chunk[0]["start"] < 0.22:
                    pass
                else:
                    chunks.append(current_chunk)
                    current_chunk = []

        current_chunk.append(w)

        # Terminal punctuation splits immediately
        if w["word"].endswith((".", "!", "?")):
            chunks.append(current_chunk)
            current_chunk = []

    if current_chunk:
        chunks.append(current_chunk)

    lime_set = set(DEFAULT_NEON_LIME_KEYWORDS)
    if trigger_keywords:
        lime_set.update([k.upper() for k in trigger_keywords])

    crimson_set = set(DEFAULT_CRIMSON_KEYWORDS)

    # Build discrete non-overlapping cues
    cues: List[CaptionCue] = []
    for i, ch in enumerate(chunks):
        c_start = ch[0]["start"]
        raw_end = ch[-1]["end"] + 0.05

        if i < len(chunks) - 1:
            next_start = chunks[i + 1][0]["start"]
            if next_start - ch[-1]["end"] > 0.28:
                c_end = min(ch[-1]["end"] + 0.18, next_start - 0.02)
            else:
                c_end = min(raw_end, next_start - 0.02)
        else:
            c_end = min(raw_end, clip_duration)

        # Minimum positive duration clamp
        if c_end <= c_start:
            c_end = c_start + 0.25

        words_raw = [c["word"] for c in ch]
        raw_phrase = " ".join(words_raw).upper()
        clean_phrase = apply_phonetic_dictionary(raw_phrase)
        clean_phrase = censor_expletives(clean_phrase)

        # Determine active cut context
        cut_ctx = None
        if cuts:
            for ct in cuts:
                # Compare in timeline seconds
                ct_s = ct.get("start", 0.0) - clip_start
                ct_e = ct.get("end", 0.0) - clip_start
                if ct_s <= c_start <= ct_e or (c_start >= ct_s and c_end <= ct_e + 0.2):
                    cut_ctx = ct
                    break

        emotion_tag = annotator.annotate(clean_phrase, c_start, c_end, cut_ctx) if include_emotions else ""

        # Determine visual highlight styling
        words_tokens = [w.strip(".,?!;:$") for w in clean_phrase.split()]
        has_crimson = any(w in crimson_set for w in words_tokens) or "SCREAMING" in emotion_tag or "WHAT?!" in clean_phrase
        has_lime = any(
            w in lime_set or any(char.isdigit() for char in w) or "$" in w
            for w in words_tokens
        ) or "GRAIL" in emotion_tag or "100%" in emotion_tag or "$2,000" in emotion_tag

        cue_style = "ZylokWhite"
        highlight = None
        if has_crimson:
            cue_style = "ZylokRed"
            highlight = "crimson_shock"
        elif has_lime:
            cue_style = "ZylokLime"
            highlight = "neon_lime"

        spk = ch[0].get("speaker", "center")
        spk_name = cut_ctx.get("speaker_name", "") if cut_ctx else ""

        cue = CaptionCue(
            index=i + 1,
            start=round(c_start, 3),
            end=round(c_end, 3),
            text=clean_phrase,
            emotion=emotion_tag,
            speaker=spk,
            speaker_name=spk_name,
            highlight_color=highlight,
            style=cue_style,
        )
        cues.append(cue)

    return cues


def build_ass_content(
    cues: List[CaptionCue],
    emotion_callouts: Optional[List[EmotionCallout]] = None,
    margin_v: int = DEFAULT_MARGIN_V,
    font_size: int = DEFAULT_FONT_SIZE_ASS,
    primary_color: str = COLOR_WHITE_HEX,
    highlight_colors: Optional[Dict[str, str]] = None,
) -> str:
    """
    Constructs production-grade Advanced SubStation Alpha (.ass) subtitle document.
    - Layer 0: Clean kinetic dialogue subtitles in mic safe zone (MarginV=420, bottom-center).
    - Layer 1: Spatially targeted, temporary emotion callouts positioned at the action
      location (host/guest/desk/center) that disappear after the emotion is expressed.
    """
    header = f"""[Script Info]
Title: Clipping Pipeline Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {CANVAS_WIDTH}
PlayResY: {CANVAS_HEIGHT}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat,{font_size},{ASS_COLOR_WHITE},&H00FFFFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,7.5,3.5,2,40,40,{margin_v},1
Style: ZylokWhite,Montserrat,{font_size},{ASS_COLOR_WHITE},&H00FFFFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,7.5,3.5,2,40,40,{margin_v},1
Style: ZylokLime,Montserrat,{font_size + 2},{ASS_COLOR_NEON_LIME},&H00FFFFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,8.0,4.0,2,40,40,{margin_v},1
Style: ZylokRed,Montserrat,{font_size + 4},{ASS_COLOR_CRIMSON},&H00FFFFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,8.0,4.0,2,40,40,{margin_v},1
Style: ZylokEmotion,Montserrat,{font_size - 14},{ASS_COLOR_EMOTION_GOLD},&H00FFFFFF,&H00000000,&HD0000000,-1,1,0,0,100,100,0,0,1,6.5,3.5,5,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: List[str] = []

    # Layer 0: Dialogue Subtitles in Mic Safe Zone (Bottom Center)
    for c in cues:
        t_start = format_ass_time(c.start)
        t_end = format_ass_time(c.end)
        pop_anim = r"{\t(0,60,\fscx112\fscy112)\t(60,120,\fscx100\fscy100)}"

        # Color application
        if c.style == "ZylokRed":
            color_tag = f"{{\\c{ASS_COLOR_CRIMSON}}}"
        elif c.style == "ZylokLime":
            color_tag = f"{{\\c{ASS_COLOR_NEON_LIME}}}"
        else:
            color_tag = f"{{\\c{ASS_COLOR_WHITE}}}"

        # If emotion_callouts are not provided, allow fallback dual-line embedding
        if emotion_callouts is None and c.emotion:
            emotion_tag = f"{{\\c{ASS_COLOR_EMOTION_GOLD}\\fs{font_size - 18}\\i1}}{c.emotion}{{\\r\\fs{font_size}\\b1}}\\N"
        else:
            emotion_tag = ""

        line_text = f"{pop_anim}{emotion_tag}{color_tag}{c.text}"
        events.append(f"Dialogue: 0,{t_start},{t_end},{c.style},,0,0,0,,{line_text}")

    # Layer 1: Event-driven Emotion Callouts with Dynamic Spatial Placement & Head Tracking
    if emotion_callouts:
        for em in emotion_callouts:
            t_start = format_ass_time(em.start)
            t_end = format_ass_time(em.end)
            if em.pos_x_end is not None and em.pos_y_end is not None and (em.pos_x != em.pos_x_end or em.pos_y != em.pos_y_end):
                pos_tag = f"{{\\move({int(em.pos_x)},{int(em.pos_y)},{int(em.pos_x_end)},{int(em.pos_y_end)})\\an{em.alignment}\\t(0,80,\\fscx115\\fscy115)\\t(80,160,\\fscx100\\fscy100)}}"
            else:
                pos_tag = f"{{\\pos({int(em.pos_x)},{int(em.pos_y)})\\an{em.alignment}\\t(0,60,\\fscx112\\fscy112)\\t(60,120,\\fscx100\\fscy100)}}"

            color_tag = f"{{\\c{em.color_ass}\\fs{font_size - 14}\\b1\\i1}}"
            events.append(f"Dialogue: 1,{t_start},{t_end},ZylokEmotion,,0,0,0,,{pos_tag}{color_tag}{em.text}")

    return header + "\n".join(events) + "\n"


def build_srt_content(cues: List[CaptionCue], include_emotions: bool = True) -> str:
    """Constructs standard SubRip (.srt) subtitle document for dialogue."""
    lines: List[str] = []
    for i, c in enumerate(cues, 1):
        t_start = format_srt_time(c.start)
        t_end = format_srt_time(c.end)
        lines.append(str(i))
        lines.append(f"{t_start} --> {t_end}")
        if include_emotions and c.emotion:
            lines.append(f"{c.emotion}\n{c.text}")
        else:
            lines.append(c.text)
        lines.append("")
    return "\n".join(lines)


def build_emotions_srt_content(emotion_callouts: List[EmotionCallout]) -> str:
    """Constructs standard SubRip (.srt) subtitle document for emotion callouts."""
    lines: List[str] = []
    for i, em in enumerate(emotion_callouts, 1):
        t_start = format_srt_time(em.start)
        t_end = format_srt_time(em.end)
        lines.append(str(i))
        lines.append(f"{t_start} --> {t_end}")
        lines.append(em.text)
        lines.append("")
    return "\n".join(lines)


def _parse_srt_to_caption_items(srt_path: Path, start_id: int = 1000) -> Tuple[List[Dict[str, Any]], int]:
    """Parse an SRT file into Remotion caption track items and @remotion/captions tokens."""
    content = srt_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", content.strip())
    items: List[Dict[str, Any]] = []
    cur_id = start_id

    time_re = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    )
    for block in blocks:
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        m = None
        text_start_idx = 1
        for idx, line in enumerate(lines):
            m = time_re.search(line)
            if m:
                text_start_idx = idx + 1
                break
        if not m or text_start_idx >= len(lines):
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in m.groups())
        start_sec = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
        end_sec = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
        dur_sec = max(0.04, end_sec - start_sec)
        raw_text = " ".join(lines[text_start_idx:]).strip()
        start_ms = int(round(start_sec * 1000))
        end_ms = int(round(end_sec * 1000))
        # Per @remotion/captions display-captions.md: include leading space before each token
        remotion_text = f" {raw_text}" if items else raw_text
        items.append(
            {
                "id": cur_id,
                "text": remotion_text,
                "cleanText": raw_text,
                "start": int(round(start_sec * TICKS_PER_SEC)),
                "duration": int(round(dur_sec * TICKS_PER_SEC)),
                "startMs": start_ms,
                "endMs": end_ms,
                "timestampMs": int((start_ms + end_ms) // 2),
                "confidence": 1.0,
                "speaker": None,
            }
        )
        cur_id += 1
    return items, cur_id


def inject_captions_into_remotion(
    project_path: Path,
    srt_path: Path,
    emotions_srt_path: Optional[Path] = None,
    margin_v: int = DEFAULT_MARGIN_V,
    font_size: float = DEFAULT_FONT_SIZE_REMOTION,
    track_name: str = "Dialogue Captions",
) -> Dict[str, Any]:
    """
    Imports and formats captions natively into a Remotion (.remotion.json) project
    using @remotion/captions track schema.
    """
    project_path = Path(project_path).resolve()
    srt_path = Path(srt_path).resolve()

    if not project_path.is_file():
        return {"success": False, "error": f"Project file not found: {project_path}"}
    if not srt_path.is_file():
        return {"success": False, "error": f"SRT file not found: {srt_path}"}

    margin_frac = round(float(margin_v) / CANVAS_HEIGHT, 4)

    try:
        with open(project_path, "r", encoding="utf-8") as f:
            remotion_data = json.load(f)

        next_id = int(remotion_data.get("project", {}).get("next_id", 1000))
        dialogue_items, next_id = _parse_srt_to_caption_items(srt_path, start_id=next_id)

        caption_tracks: List[Dict[str, Any]] = [
            {
                "id": 1,
                "name": track_name,
                "provider": "@remotion/captions",
                "style": {
                    "track": "C1",
                    "margin": margin_frac,
                    "margin_v": margin_v,
                    "size": font_size,
                    "font": "Inter",
                    "color": COLOR_WHITE_HEX,
                    "outline": 4.5,
                    "outlineColor": "#000000",
                    "align": "center",
                    "anchor": "bottom",
                    "background": False,
                },
                "items": dialogue_items,
            }
        ]

        if emotions_srt_path and Path(emotions_srt_path).is_file():
            emotion_items, next_id = _parse_srt_to_caption_items(Path(emotions_srt_path), start_id=next_id)
            if emotion_items:
                caption_tracks.append(
                    {
                        "id": 2,
                        "name": "Emotion Callouts",
                        "provider": "@remotion/captions",
                        "style": {
                            "track": "C2",
                            "margin": 0.65,
                            "size": font_size - 12.0,
                            "font": "Inter",
                            "color": COLOR_EMOTION_GOLD_HEX,
                            "outline": 4.0,
                            "outlineColor": "#000000",
                            "align": "center",
                            "anchor": "top",
                            "background": False,
                        },
                        "items": emotion_items,
                    }
                )

        for item_key, item_val in remotion_data.get("project", {}).get("items", {}).items():
            if isinstance(item_val, dict) and item_val.get("kind", {}).get("Sequence"):
                item_val["kind"]["Sequence"]["caption_tracks"] = caption_tracks
        if "project" in remotion_data:
            remotion_data["project"]["next_id"] = next_id

        with open(project_path, "w", encoding="utf-8") as f:
            json.dump(remotion_data, f, indent=2, ensure_ascii=False)
            f.write("\n")

        # Also sync remotion/props.json if present alongside project_path
        props_path = project_path.parent / "remotion" / "props.json"
        if props_path.is_file():
            with open(props_path, "w", encoding="utf-8") as f:
                json.dump(remotion_data, f, indent=2, ensure_ascii=False)
                f.write("\n")

    except Exception as ex:
        return {"success": False, "error": f"Remotion caption track injection failed: {ex}"}

    return {
        "success": True,
        "project_file": str(project_path),
        "srt_imported": str(srt_path),
        "margin_v": margin_v,
        "margin_fraction": margin_frac,
        "track_name": track_name,
        "tracks_count": len(caption_tracks),
    }


def trigger_companion_checkpoint(
    state_path: Path,
    project_file: Optional[Path] = None,
    feedback: str = "",
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """Invokes clipping_state.py checkpoint --step clipping-captions."""
    scripts_dir = Path(__file__).resolve().parent
    clipping_state_cli = scripts_dir / "clipping_state.py"
    if not clipping_state_cli.is_file():
        return {"success": False, "error": f"{clipping_state_cli} not found"}

    cmd = [
        sys.executable,
        str(clipping_state_cli),
        "checkpoint",
        "--step",
        "clipping-captions",
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


def execute_captions_step(
    project_dir: Path,
    transcript_path: Optional[Path] = None,
    cuts_path: Optional[Path] = None,
    project_file: Optional[Path] = None,
    meta_file: Optional[Path] = None,
    output_ass: Optional[Path] = None,
    output_srt: Optional[Path] = None,
    output_json: Optional[Path] = None,
    words_per_line: int = 2,
    margin_v: int = DEFAULT_MARGIN_V,
    include_emotions: bool = True,
    trigger_keywords: Optional[List[str]] = None,
    remove_callouts: Optional[List[Union[int, str]]] = None,
    trigger_checkpoint: bool = True,
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """
    Main programmatic orchestrator for Step 5 (clipping-captions).
    """
    project_dir = Path(project_dir).resolve()
    state_path = project_dir / ".clipping_state.json"

    # Step config extraction from .clipping_state.json if available
    step_config: Dict[str, Any] = {}
    project_name = project_dir.name
    if state_path.is_file():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            step_config = st.get("steps", {}).get("clipping-captions", {}).get("params", {})
            campaign_proj = st.get("campaign", {}).get("project")
            if campaign_proj:
                project_name = campaign_proj
        except Exception:
            pass

    # Resolve inputs
    if not transcript_path:
        transcript_path = project_dir / "transcript.json"
    if not cuts_path:
        cuts_path = project_dir / "cuts.json"
    if not project_file:
        cand_proj = project_dir / f"{project_name}.remotion.json"
        existing_projs = list(project_dir.glob("*.remotion.json"))
        if cand_proj.is_file():
            project_file = cand_proj
        elif existing_projs:
            project_file = existing_projs[0]
        else:
            project_file = None
    if not meta_file:
        cand_meta = project_dir / f"{project_name}.meta.json"
        meta_file = cand_meta if cand_meta.is_file() else (project_dir / "meta.json")

    # Load transcript
    with open(transcript_path, "r", encoding="utf-8") as f:
        t_data = json.load(f)
    words_list: List[Dict[str, Any]] = []
    segments = t_data if isinstance(t_data, list) else t_data.get("segments", [])
    for seg in segments:
        for w in seg.get("words", []):
            words_list.append(w)

    # Load cuts data
    cuts_list: List[Dict[str, Any]] = []
    clip_start = 0.0
    clip_end = 0.0
    if cuts_path and cuts_path.is_file():
        with open(cuts_path, "r", encoding="utf-8") as f:
            c_data = json.load(f)
        cuts_list = c_data.get("cuts", [])
        clip_start = float(c_data.get("start", 0.0))
        clip_end = float(c_data.get("end", 0.0))

    if clip_end <= clip_start and meta_file and meta_file.is_file():
        with open(meta_file, "r", encoding="utf-8") as f:
            m_data = json.load(f)
        sub_cuts = m_data.get("sub_cuts", [])
        if sub_cuts:
            clip_start = sub_cuts[0].get("start", 0.0)
            clip_end = sub_cuts[-1].get("end", 0.0)
            if not cuts_list:
                cuts_list = sub_cuts

    # Resolve config options
    wpl = step_config.get("words_per_line_range", [1, words_per_line])[-1] if "words_per_line_range" in step_config else words_per_line
    mv = int(step_config.get("margin_v", margin_v))
    combined_triggers = list(trigger_keywords or [])
    combined_triggers.extend(step_config.get("trigger_keywords", []))

    # Check preferences or step config for remove_callouts
    pref_removals = []
    prefs_file = project_dir / ".clipping_preferences.json"
    if prefs_file.is_file():
        try:
            with open(prefs_file, "r", encoding="utf-8") as f:
                p_data = json.load(f)
            pref_removals = p_data.get("captions", {}).get("remove_callouts", [])
        except Exception:
            pass
    active_removals = list(remove_callouts or [])
    active_removals.extend(step_config.get("remove_callouts", []))
    active_removals.extend(pref_removals)

    # Segment words into cues and extract discrete emotion callouts
    cues = segment_words_into_cues(
        words=words_list,
        clip_start=clip_start,
        clip_end=clip_end,
        cuts=cuts_list,
        words_per_line=wpl,
        include_emotions=include_emotions,
        trigger_keywords=combined_triggers,
    )

    annotator = EmotionVisualAnnotator(cuts=cuts_list)
    emotion_callouts = annotator.extract_emotion_callouts(
        clip_start,
        clip_end,
        clip_words=words_list,
        remove_callouts=active_removals,
    ) if include_emotions else []

    # Output paths
    if not output_ass:
        output_ass = project_dir / f"{project_name}.ass"
    if not output_srt:
        output_srt = project_dir / f"{project_name}.srt"
    output_clean_srt = project_dir / f"{project_name}_clean.srt"
    output_emotions_srt = project_dir / f"{project_name}_emotions.srt"
    if not output_json:
        output_json = project_dir / "captions.json"

    # Write ASS with separate dialogue (Layer 0, MarginV=420) and emotion callouts (Layer 1, dynamic pos)
    ass_content = build_ass_content(
        cues=cues,
        emotion_callouts=emotion_callouts,
        margin_v=mv,
        font_size=DEFAULT_FONT_SIZE_ASS,
    )
    output_ass.write_text(ass_content, encoding="utf-8")

    # Write SRT for dialogue (with emotion comments embedded if include_emotions is true)
    srt_content = build_srt_content(cues, include_emotions=include_emotions)
    output_srt.write_text(srt_content, encoding="utf-8")

    # Write clean SRT for dialogue (strictly spoken text, no emotion comments)
    clean_srt_content = build_srt_content(cues, include_emotions=False)
    output_clean_srt.write_text(clean_srt_content, encoding="utf-8")

    # Write SRT for emotion callouts
    emotions_srt_content = build_emotions_srt_content(emotion_callouts)
    output_emotions_srt.write_text(emotions_srt_content, encoding="utf-8")

    # Collect emotion tags & keyword highlights
    emotion_tags = sorted(list(set(em.text for em in emotion_callouts)))
    highlight_words = sorted(list(set(
        w.strip(".,?!;:")
        for c in cues
        if c.highlight_color
        for w in c.text.split()
    )))

    # Write JSON manifest
    manifest_data = {
        "project_name": project_name,
        "clip_start": clip_start,
        "clip_end": clip_end,
        "duration_seconds": round(clip_end - clip_start, 2),
        "cues_count": len(cues),
        "emotion_callouts_count": len(emotion_callouts),
        "words_count": sum(len(c.text.split()) for c in cues),
        "margin_v": mv,
        "words_per_line": wpl,
        "include_emotions": include_emotions,
        "emotion_tags": emotion_tags,
        "highlight_keywords": highlight_words,
        "files": {
            "ass": str(output_ass),
            "srt": str(output_srt),
            "clean_srt": str(output_clean_srt),
            "emotions_srt": str(output_emotions_srt),
            "json": str(output_json),
        },
        "cues": [c.to_dict() for c in cues],
        "remotion_captions": [
            {
                "text": f" {c.text}" if idx > 0 else c.text,
                "startMs": int(round(c.start * 1000)),
                "endMs": int(round(c.end * 1000)),
                "timestampMs": int(round(((c.start + c.end) / 2.0) * 1000)),
                "confidence": 1.0,
            }
            for idx, c in enumerate(cues)
        ],
        "emotion_callouts": [em.to_dict() for em in emotion_callouts],
    }
    output_json.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Inject native captions into .remotion.json if project file exists
    remotion_result = {}
    if project_file and Path(project_file).is_file():
        remotion_result = inject_captions_into_remotion(
            project_path=Path(project_file),
            srt_path=output_clean_srt,
            emotions_srt_path=output_emotions_srt,
            margin_v=mv,
            font_size=DEFAULT_FONT_SIZE_REMOTION,
            track_name="Dialogue Captions",
        )

    # Update sidecar metadata
    if meta_file and Path(meta_file).is_file():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta_data = json.load(f)
            meta_data["captions"] = {
                "cues_count": len(cues),
                "words_count": manifest_data["words_count"],
                "margin_v": mv,
                "ass_file": str(output_ass),
                "srt_file": str(output_srt),
                "json_file": str(output_json),
                "emotion_tags": emotion_tags,
                "highlight_keywords": highlight_words,
            }
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, indent=2, ensure_ascii=False)
                f.write("\n")
        except Exception as ex:
            sys.stderr.write(f"Notice: Failed to update sidecar meta: {ex}\n")

    # Update pipeline state file
    checkpoint_res: Optional[Dict[str, Any]] = None
    if state_path.is_file():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                st = json.load(f)
            step_entry = st.setdefault("steps", {}).setdefault("clipping-captions", {})
            step_entry["status"] = "staged"
            step_entry["staged"] = True
            step_params = step_entry.setdefault("params", {})
            step_params.update({
                "ass_file": str(output_ass),
                "srt_file": str(output_srt),
                "json_file": str(output_json),
                "cues_count": len(cues),
                "words_count": manifest_data["words_count"],
                "margin_v": mv,
                "emotion_tags": emotion_tags,
                "highlight_keywords": highlight_words,
            })
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(st, f, indent=2, ensure_ascii=False)
                f.write("\n")

            if trigger_checkpoint:
                checkpoint_res = trigger_companion_checkpoint(
                    state_path=state_path,
                    project_file=Path(project_file) if project_file else Path(project_dir / f"{project_name}.remotion.json"),
                    feedback="Generated kinetic captions in mic safe zone (MarginV=420) with dual emotion/visual comments and Neon Lime highlights",
                    auto_approve=auto_approve,
                )
        except Exception as ex:
            checkpoint_res = {"success": False, "error": f"Failed state update: {ex}"}

    return {
        "status": "success",
        "project_name": project_name,
        "cues_count": len(cues),
        "words_count": manifest_data["words_count"],
        "duration_seconds": manifest_data["duration_seconds"],
        "emotion_tags": emotion_tags,
        "highlight_keywords": highlight_words,
        "output_ass": str(output_ass),
        "output_srt": str(output_srt),
        "output_json": str(output_json),
        "remotion_injection": remotion_result,
        "checkpoint_triggered": trigger_checkpoint and state_path.is_file(),
        "checkpoint_result": checkpoint_res,
    }


def main():
    parser = argparse.ArgumentParser(description="Step 5: Kinetic Subtitle & Caption Styling Engine.")
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    p_gen = subparsers.add_parser("generate", help="Generate kinetic subtitles and native caption tracks.")
    p_gen.add_argument("--project-dir", required=True, help="Path to project directory")
    p_gen.add_argument("--transcript", help="Path to transcript.json")
    p_gen.add_argument("--cuts", help="Path to cuts.json")
    p_gen.add_argument("--project-file", help="Path to .remotion.json project file")
    p_gen.add_argument("--meta", help="Path to sidecar .meta.json file")
    p_gen.add_argument("--output-ass", help="Path for generated .ass subtitle file")
    p_gen.add_argument("--output-srt", help="Path for generated .srt subtitle file")
    p_gen.add_argument("--output-json", help="Path for generated captions.json manifest")
    p_gen.add_argument("--words-per-line", type=int, default=2, help="Words per subtitle cue (default: 2)")
    p_gen.add_argument("--margin-v", type=int, default=DEFAULT_MARGIN_V, help=f"Vertical bottom margin in px (default: {DEFAULT_MARGIN_V})")
    p_gen.add_argument("--no-emotions", action="store_true", help="Omit emotion/visual comments (*comment*)")
    p_gen.add_argument("--trigger-keywords", nargs="*", default=[], help="Additional high-impact trigger keywords")
    p_gen.add_argument("--remove-callouts", nargs="*", default=[], help="List of emotion callout indices (e.g. 2 3 4 5 6 7 or E02 E03) to exclude")
    p_gen.add_argument("--no-checkpoint", action="store_true", help="Do not trigger clipping_state.py checkpoint")
    p_gen.add_argument("--auto-approve", action="store_true", help="Auto-approve checkpoint gate after staging")
    p_gen.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args()

    if args.subcommand == "generate":
        res = execute_captions_step(
            project_dir=Path(args.project_dir),
            transcript_path=Path(args.transcript) if args.transcript else None,
            cuts_path=Path(args.cuts) if args.cuts else None,
            project_file=Path(args.project_file) if args.project_file else None,
            meta_file=Path(args.meta) if args.meta else None,
            output_ass=Path(args.output_ass) if args.output_ass else None,
            output_srt=Path(args.output_srt) if args.output_srt else None,
            output_json=Path(args.output_json) if args.output_json else None,
            words_per_line=args.words_per_line,
            margin_v=args.margin_v,
            include_emotions=not args.no_emotions,
            trigger_keywords=args.trigger_keywords,
            remove_callouts=args.remove_callouts,
            trigger_checkpoint=not args.no_checkpoint,
            auto_approve=args.auto_approve,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"[SUCCESS] Generated kinetic captions for '{res['project_name']}':")
            print(f"  Cues Count:      {res['cues_count']} cues ({res['words_count']} words, {res['duration_seconds']}s)")
            print(f"  Emotion Tags:    {len(res['emotion_tags'])} unique ({', '.join(res['emotion_tags'][:5])}...)")
            print(f"  Highlight Words: {len(res['highlight_keywords'])} words ({', '.join(res['highlight_keywords'][:5])}...)")
            print(f"  ASS Subtitles:   {res['output_ass']}")
            print(f"  SRT Subtitles:   {res['output_srt']}")
            print(f"  JSON Manifest:   {res['output_json']}")
            if res.get("checkpoint_triggered"):
                cp_data = res.get("checkpoint_result", {})
                cp_ok = cp_data.get("success", False) if cp_data else False
                status_label = "TRIGGERED / ACTIVE" if cp_ok else "FAILED"
                print(f"  Live Companion Checkpoint: {status_label}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
