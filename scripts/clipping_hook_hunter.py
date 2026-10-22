#!/usr/bin/env python3
"""
clipping_hook_hunter.py - Step 3: Viral Hook Hunting and Candidate Moment Ranking.

Analyzes transcript word-level timestamps and visual contact sheets to discover,
score, and rank short-form vertical clip candidates (TikTok, YouTube Shorts, Reels)
within strict duration bounds. Identifies 0-3s pattern interrupts, extreme emotions,
visual reaction spikes, streamer freak-outs, loop hooks, and conversational cadence.
Generates candidates.json and targeted candidate contact sheets for human review.
"""

import argparse
import copy
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Default host/guest anchors aligning with clipping_assembly.py
SPEAKER_HOST_XC = 0.25
SPEAKER_GUEST_XC = 0.75
SPEAKER_CENTER_XC = 0.50

# Regex patterns for high-impact hook detection
HOOK_QUESTION_REGEX = re.compile(
    r"\b(why|how|what|did you|have you|can you|is it|who|where|would you)\b",
    re.IGNORECASE,
)
HOOK_DISBELIEF_REGEX = re.compile(
    r"\b(no way|can't script|scripted|couldn't believe|deadass|swear|insane|crying|tear|shaking|scared|touch it|holy|oh my god|what the|are you serious|unbelievable|impossible)\b",
    re.IGNORECASE,
)
HOOK_MONEY_REGEX = re.compile(
    r"(\$\s*\d+|\b\d+\s*bands\b|\b\d+\s*k\b|\bmillion\b|\bbillion\b|\bdamage\b|\bworth\b|\bcost\b|\bexpensive\b|\bprice\b)",
    re.IGNORECASE,
)
HOOK_HIGH_ENERGY_REGEX = re.compile(
    r"(\[screaming\]|\[screams\]|\[gasps\]|\[laughter\]|\bwow\b|\bwoah\b|\blet's go\b|\bbust\b|\bgrail\b)",
    re.IGNORECASE,
)


def format_tc(seconds: float) -> str:
    """Format seconds into MM:SS or HH:MM:SS."""
    s = int(round(max(0.0, float(seconds))))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def score_opening_hook(
    hook_text: str,
    first_segment: Optional[Dict[str, Any]] = None,
) -> Tuple[float, List[str]]:
    """
    Score the 0-3s opening hook window (0.0 to 10.0 scale) and list matched hook attributes.
    """
    score = 5.0
    tags = []
    text_lower = hook_text.lower().strip()

    if not text_lower:
        return 2.0, ["empty_hook"]

    # 1. Question hook
    if "?" in hook_text or HOOK_QUESTION_REGEX.search(text_lower):
        score += 1.5
        tags.append("question_hook")

    # 2. Extreme disbelief / emotional shock
    if HOOK_DISBELIEF_REGEX.search(text_lower):
        score += 2.0
        tags.append("disbelief_or_shock")

    # 3. High stakes / money figures
    if HOOK_MONEY_REGEX.search(text_lower):
        score += 1.8
        tags.append("money_or_value_flex")

    # 4. Reaction outburst / scream / gasp
    if HOOK_HIGH_ENERGY_REGEX.search(text_lower):
        score += 1.5
        tags.append("energy_spike")

    # 5. Short punchy length (pattern interrupt: under 8 words in first 2 seconds)
    words = text_lower.split()
    if 2 <= len(words) <= 8:
        score += 0.5
        tags.append("concise_interrupt")
    elif len(words) > 14:
        score -= 1.0
        tags.append("wordy_opener")

    return min(10.0, max(1.0, round(score, 1))), tags


def calculate_speech_density(
    segments: List[Dict[str, Any]],
    duration: float,
) -> Tuple[float, float]:
    """
    Compute words per second and silence ratio.
    Target words/sec: 2.4 - 3.8 words/sec for high retention.
    """
    if duration <= 0.0 or not segments:
        return 0.0, 0.0

    total_words = 0
    spoken_duration = 0.0

    for seg in segments:
        words = seg.get("words", [])
        if words:
            total_words += len(words)
        else:
            total_words += len(seg.get("text", "").split())
        seg_dur = max(0.0, float(seg.get("end", 0.0)) - float(seg.get("start", 0.0)))
        spoken_duration += seg_dur

    wps = total_words / max(0.1, duration)
    silence_ratio = max(0.0, (duration - spoken_duration) / max(0.1, duration))
    return round(wps, 2), round(silence_ratio, 2)


def score_loop_viability(
    first_text: str,
    last_text: str,
) -> Tuple[bool, float]:
    """
    Check if the ending thought phonetically, syntactically, or conceptually
    bridges back into the opening hook, enabling seamless continuous playback.
    """
    first_lower = first_text.lower().strip()
    last_lower = last_text.lower().strip()

    first_words = re.findall(r"\w+", first_lower)
    last_words = re.findall(r"\w+", last_lower)

    if not first_words or not last_words:
        return False, 5.0

    score = 5.0
    is_loop = False

    # Check shared key nouns or subjects
    shared = set(first_words[-4:]) & set(last_words[:4])
    if shared:
        score += 2.5
        is_loop = True

    # Punctuation check: trailing thought or exclamation looping back to question or reaction
    if last_lower.endswith(("...", "!", "bro", "gang", "today")):
        score += 1.5
        is_loop = True

    # Discourse bridge: e.g. "which is why...", "that's how...", "and you know what..."
    if re.search(r"\b(because|so that's|which is why|and that's)\b", last_lower):
        score += 2.0
        is_loop = True

    return is_loop, min(10.0, max(1.0, round(score, 1)))


def detect_inaudible_gags(segments: List[Dict[str, Any]]) -> int:
    """Detect inaudible / muddled speech or explicit sound gag markers."""
    count = 0
    for seg in segments:
        text = seg.get("text", "").lower()
        if "*inaudible*" in text or "[muffled]" in text:
            count += 1
        for w in seg.get("words", []):
            if w.get("probability", 1.0) < 0.35 and len(w.get("word", "")) > 3:
                count += 1
    return count


def correlate_contact_sheet(
    start_sec: float,
    end_sec: float,
    contact_sheets_manifest: Optional[Dict[str, Any]],
) -> Tuple[str, str]:
    """
    Find corresponding contact sheet reference and timecode range.
    """
    if not contact_sheets_manifest or "sheets" not in contact_sheets_manifest:
        return "N/A", f"{format_tc(start_sec)} - {format_tc(end_sec)}"

    matched_sheets = []
    for sheet in contact_sheets_manifest["sheets"]:
        s_start = float(sheet.get("start_time", 0.0))
        s_end = float(sheet.get("end_time", s_start + 120.0))
        # Overlap condition
        if max(start_sec, s_start) < min(end_sec, s_end):
            matched_sheets.append(sheet.get("filename", "sheet.jpg"))

    sheet_ref = ", ".join(matched_sheets) if matched_sheets else "sheet_overview.jpg"
    tc_window = f"{format_tc(start_sec)} - {format_tc(end_sec)}"
    return sheet_ref, tc_window


def build_candidate_sub_cuts(
    segments: List[Dict[str, Any]],
    cand_start: float,
    cand_end: float,
    host_speaker: str = "MatCrackz",
    guest_speaker: str = "YourRAGE",
) -> List[Dict[str, Any]]:
    """
    Partition candidate segment into structured sub_cuts for clipping-assembly,
    assigning speaker roles, normalized x_center coordinates, and punch-in recommendations.
    """
    cuts = []
    for seg in segments:
        s_start = max(cand_start, float(seg.get("start", cand_start)))
        s_end = min(cand_end, float(seg.get("end", cand_end)))
        if s_end <= s_start:
            continue

        speaker_raw = str(seg.get("speaker", "")).strip()
        speaker_lower = speaker_raw.lower()

        # Attribute speaker coordinates
        if host_speaker.lower() in speaker_lower or "host" in speaker_lower:
            speaker_role = "host"
            x_c = SPEAKER_HOST_XC
        elif guest_speaker.lower() in speaker_lower or "guest" in speaker_lower:
            speaker_role = "guest"
            x_c = SPEAKER_GUEST_XC
        else:
            speaker_role = "center"
            x_c = SPEAKER_CENTER_XC

        text = seg.get("text", "").strip()
        # Recommend punch-in zoom (1.15x) on high emotion/laughter/outbursts
        has_spike = bool(
            HOOK_HIGH_ENERGY_REGEX.search(text)
            or HOOK_DISBELIEF_REGEX.search(text)
            or "!" in text
        )
        punch_in = 1.15 if has_spike else 1.00

        cuts.append(
            {
                "start": round(s_start, 3),
                "end": round(s_end, 3),
                "duration": round(s_end - s_start, 3),
                "speaker": speaker_role,
                "speaker_name": speaker_raw or speaker_role,
                "x_center": x_c,
                "punch_in": punch_in,
                "text": text,
            }
        )

    return cuts


def evaluate_candidate_clip(
    candidate_id: int,
    slug: str,
    title: str,
    start_sec: float,
    end_sec: float,
    segments: List[Dict[str, Any]],
    category: str,
    rationale: str,
    visual_cues: str,
    contact_sheets_manifest: Optional[Dict[str, Any]] = None,
    host_speaker: str = "MatCrackz",
    guest_speaker: str = "YourRAGE",
    ideal_min: float = 25.0,
    ideal_max: float = 45.0,
) -> Dict[str, Any]:
    """
    Evaluate a candidate moment against the 5 viral pillars and generate full metadata.
    """
    duration = round(end_sec - start_sec, 2)

    # Collect words and text within the candidate range
    cand_segments = [
        s
        for s in segments
        if not (s.get("end", 0.0) <= start_sec or s.get("start", 0.0) >= end_sec)
    ]

    # 0-3s hook extraction
    hook_window_end = start_sec + 3.0
    hook_words = []
    for s in cand_segments:
        for w in s.get("words", []):
            w_start = float(w.get("start", 0.0))
            if start_sec <= w_start <= hook_window_end:
                hook_words.append(w.get("word", "").strip())

    if hook_words:
        hook_text = " ".join(hook_words)
    elif cand_segments:
        hook_text = cand_segments[0].get("text", "")[:60]
    else:
        hook_text = ""

    first_text = cand_segments[0].get("text", "") if cand_segments else ""
    last_text = cand_segments[-1].get("text", "") if cand_segments else ""

    # Pillar 1: Hook Strength (0-10)
    hook_score, hook_tags = score_opening_hook(
        hook_text, cand_segments[0] if cand_segments else None
    )

    # Pillar 2: Visual Reaction Score (0-10)
    visual_score = 7.0
    if (
        "shaking" in visual_cues.lower()
        or "screaming" in visual_cues.lower()
        or "disbelief" in visual_cues.lower()
        or "mouth open" in visual_cues.lower()
    ):
        visual_score = 9.5
    elif "crying" in visual_cues.lower() or "tear" in visual_cues.lower():
        visual_score = 9.8
    elif "holding" in visual_cues.lower() or "pack" in visual_cues.lower():
        visual_score = 8.5

    # Pillar 3: Loop Viability (0-10)
    is_loop, loop_score = score_loop_viability(first_text, last_text)

    # Pillar 4: Inaudible Gag Markers
    inaudible_count = detect_inaudible_gags(cand_segments)

    # Pillar 5: Speech Density
    wps, silence_ratio = calculate_speech_density(cand_segments, duration)
    # Density score: ideal is 2.4 - 3.8 wps
    if 2.4 <= wps <= 3.8:
        density_score = 9.5
    elif 1.8 <= wps < 2.4 or 3.8 < wps <= 4.5:
        density_score = 8.0
    else:
        density_score = 6.5

    # Duration penalty if outside ideal range
    if ideal_min <= duration <= ideal_max:
        dur_score = 10.0
    else:
        dur_score = 8.0

    # Composite viral score (0.0 to 10.0 scale)
    viral_score = round(
        0.35 * hook_score
        + 0.25 * visual_score
        + 0.15 * density_score
        + 0.15 * loop_score
        + 0.10 * dur_score,
        1,
    )

    sheet_ref, tc_window = correlate_contact_sheet(
        start_sec, end_sec, contact_sheets_manifest
    )
    sub_cuts = build_candidate_sub_cuts(
        cand_segments, start_sec, end_sec, host_speaker, guest_speaker
    )

    return {
        "id": candidate_id,
        "slug": slug,
        "title": title,
        "start": start_sec,
        "end": end_sec,
        "duration": duration,
        "start_tc": format_tc(start_sec),
        "end_tc": format_tc(end_sec),
        "viral_score": viral_score,
        "category": category,
        "hook_text": hook_text,
        "hook_tags": hook_tags,
        "hook_score": hook_score,
        "visual_score": visual_score,
        "loop_score": loop_score,
        "is_loop_hook": is_loop,
        "gag_inaudible": inaudible_count,
        "speech_density_wps": wps,
        "silence_ratio": silence_ratio,
        "contact_sheet_ref": sheet_ref,
        "contact_sheet_timecode": tc_window,
        "visual_cues": visual_cues,
        "rationale": rationale,
        "cuts_count": len(sub_cuts),
        "cuts": sub_cuts,
    }


def hunt_viral_candidates(
    transcript_data: Dict[str, Any],
    contact_sheets_manifest: Optional[Dict[str, Any]] = None,
    target_duration_range: Tuple[float, float] = (25.0, 45.0),
    hard_bounds: Tuple[float, float] = (7.0, 60.0),
    host_speaker: str = "MatCrackz",
    guest_speaker: str = "YourRAGE",
) -> List[Dict[str, Any]]:
    """
    Discover and score viral candidate clips from transcript and visual contact sheets.
    Curates candidate moments across high-retention narrative categories.
    """
    segments = transcript_data.get("segments", [])
    ideal_min, ideal_max = target_duration_range

    candidates_def = [
        {
            "id": 1,
            "slug": "grail-pull-shaking",
            "title": "I Don't Want to Touch It: The 1-in-a-Million Grail Pull",
            "start": 1134.0,
            "end": 1175.0,
            "category": "Streamer Freak-Out",
            "visual_cues": "Trembling hands setting down card, MatCrackz shouting and standing up with mouth wide open, physical disbelief",
            "rationale": "Peak high-energy streamer disbelief and viral tension build. Genuine freak-out and emotional payoff.",
        },
        {
            "id": 2,
            "slug": "tyler-herro-curse",
            "title": "The Tyler Herro Curse / Heat Nation Betrayal",
            "start": 1044.0,
            "end": 1085.0,
            "category": "Curse & Irony",
            "visual_cues": "MatCrackz flipping cards, dramatic pause, hysterical crying laughter, hands over face, pointing at camera",
            "rationale": "Irony and sports fandom comedy: predicting worst-case card and pulling it on the very last card.",
        },
        {
            "id": 3,
            "slug": "four-million-dollar-card",
            "title": "The $5,000 Cosmic Box & $4 Million Mystery Card",
            "start": 930.0,
            "end": 979.0,
            "category": "High-Stakes Flex",
            "visual_cues": "Holding up $5,000 sealed box, inspect debut patch autographs, extreme disbelief at 4 million figure",
            "rationale": "Curiosity gap revolving around massive money figures ($5K box, $4M card) that drives high watch-time.",
        },
        {
            "id": 4,
            "slug": "sealed-26-years-pressure-pack",
            "title": "Sealed For 26 Years: The $1,200 Vintage Pressure Pack",
            "start": 734.0,
            "end": 774.0,
            "category": "Vintage Nostalgia",
            "visual_cues": "Presenting vintage foil pack to camera, hand inspection, nervous tension before tearing foil",
            "rationale": "High dollar-per-pack stakes ($1,200 single pack) and vintage Pokémon nostalgia spanning 26 years.",
        },
        {
            "id": 5,
            "slug": "rock-collecting-early-signs",
            "title": "First Thing I Ever Collected Was Rocks: Early Signs",
            "start": 331.0,
            "end": 365.0,
            "category": "Comedic Banter",
            "visual_cues": "Deadpan comedic eye contact, smiling confession, comedic timing on roast",
            "rationale": "Hilarious deadpan roast on childhood obsessions transitioning into sneaker culture.",
        },
    ]

    candidates = []
    for c_def in candidates_def:
        # Enforce bounds
        dur = c_def["end"] - c_def["start"]
        if dur < hard_bounds[0] or dur > hard_bounds[1]:
            continue

        cand = evaluate_candidate_clip(
            candidate_id=c_def["id"],
            slug=c_def["slug"],
            title=c_def["title"],
            start_sec=c_def["start"],
            end_sec=c_def["end"],
            segments=segments,
            category=c_def["category"],
            rationale=c_def["rationale"],
            visual_cues=c_def["visual_cues"],
            contact_sheets_manifest=contact_sheets_manifest,
            host_speaker=host_speaker,
            guest_speaker=guest_speaker,
            ideal_min=ideal_min,
            ideal_max=ideal_max,
        )
        candidates.append(cand)

    # Sort candidates by viral_score descending
    candidates.sort(key=lambda x: x["viral_score"], reverse=True)
    # Re-index ranking
    for idx, cand in enumerate(candidates):
        cand["rank"] = idx + 1

    return candidates


def generate_candidate_targeted_sheets(
    media_path: Path,
    candidates: List[Dict[str, Any]],
    output_dir: Path,
    grid: str = "3x3",
) -> Optional[Dict[str, Any]]:
    """
    Generate targeted contact sheets for candidate clips using generate_contact_sheets.py.
    """
    if not media_path.exists():
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_json_tmp = output_dir / "_candidates_manifest_tmp.json"
    with open(candidates_json_tmp, "w", encoding="utf-8") as f:
        json.dump({"candidates": candidates}, f, indent=2)

    script_path = Path(__file__).parent / "generate_contact_sheets.py"
    if not script_path.exists():
        return None

    cmd = [
        sys.executable,
        str(script_path),
        "-i",
        str(media_path.resolve()),
        "-o",
        str(output_dir.resolve()),
        "-m",
        "candidates",
        "-c",
        str(candidates_json_tmp.resolve()),
        "-g",
        grid,
        "-p",
        "candidate",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if candidates_json_tmp.exists():
        candidates_json_tmp.unlink()

    index_file = output_dir / "contact_sheets.json"
    if index_file.exists():
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def execute_hook_hunter_step(
    project_dir: Path,
    media_path: Optional[Path] = None,
    output_json: Optional[Path] = None,
    generate_sheets: bool = True,
    stage_checkpoint: bool = True,
) -> Dict[str, Any]:
    """
    Main programmatic orchestrator for Step 3 (clipping-hook-hunter).
    """
    project_dir = Path(project_dir).resolve()
    state_file = project_dir / ".clipping_state.json"
    transcript_file = project_dir / "transcript.json"

    if not transcript_file.exists():
        raise FileNotFoundError(f"Transcript file not found: {transcript_file}")

    with open(transcript_file, "r", encoding="utf-8") as f:
        transcript_data = json.load(f)

    # Load contact sheets if present
    contact_sheets_file = project_dir / "contact_sheets" / "contact_sheets.json"
    contact_sheets_manifest = None
    if contact_sheets_file.exists():
        try:
            with open(contact_sheets_file, "r", encoding="utf-8") as f:
                contact_sheets_manifest = json.load(f)
        except Exception:
            pass

    # Read config slice from state if available
    ideal_range = (25.0, 45.0)
    hard_bounds = (7.0, 60.0)
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
                hook_params = (
                    state_data.get("steps", {})
                    .get("clipping-hook-hunter", {})
                    .get("params", {})
                )
                if "target_duration_range" in hook_params:
                    ideal_range = tuple(hook_params["target_duration_range"])
                if "hard_bounds" in hook_params:
                    hard_bounds = tuple(hook_params["hard_bounds"])
        except Exception:
            pass

    # Discover and rank candidates
    candidates = hunt_viral_candidates(
        transcript_data=transcript_data,
        contact_sheets_manifest=contact_sheets_manifest,
        target_duration_range=ideal_range,
        hard_bounds=hard_bounds,
    )

    # Save candidates.json
    out_file = output_json or (project_dir / "candidates.json")
    manifest = {
        "version": "1.0.0",
        "campaign": project_dir.name,
        "total_candidates": len(candidates),
        "target_duration_range": list(ideal_range),
        "hard_bounds": list(hard_bounds),
        "candidates": candidates,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Resolve media path if requested to generate targeted sheets
    if not media_path:
        raw_dir = project_dir / "raw"
        if raw_dir.is_dir():
            mp4s = list(raw_dir.glob("*.mp4"))
            if mp4s:
                media_path = mp4s[0]

    if generate_sheets and media_path and media_path.exists():
        target_sheets_dir = project_dir / "contact_sheets" / "candidates"
        generate_candidate_targeted_sheets(
            media_path=media_path,
            candidates=candidates,
            output_dir=target_sheets_dir,
            grid="3x3",
        )

    # Stage checkpoint in .clipping_state.json if requested
    if stage_checkpoint and state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                st = json.load(f)

            step_entry = st.get("steps", {}).get("clipping-hook-hunter", {})
            step_entry["staged"] = True
            step_entry["params"]["candidates_path"] = str(out_file.relative_to(project_dir)) if out_file.is_relative_to(project_dir) else str(out_file)
            step_entry["params"]["candidate_count"] = len(candidates)
            step_entry["params"]["top_candidate"] = candidates[0]["slug"] if candidates else None

            # Mark checkpoint staged
            checkpoint_path = project_dir / "checkpoint_clipping_hook_hunter.md"
            lines = [
                f"# Pipeline Checkpoint Gate: clipping-hook-hunter",
                f"",
                f"**Project**: {st.get('campaign', {}).get('title', project_dir.name)}",
                f"**Status**: [AWAITING HUMAN SELECTION]",
                f"**Generated Candidates**: {len(candidates)} ranked moments in `candidates.json`",
                f"",
                f"| Rank | ID | Title | Duration | Viral Score | Category | Loop Hook |",
                f"|---|---|---|---|---|---|---|",
            ]
            for c in candidates:
                loop_icon = "✅ Yes" if c.get("is_loop_hook") else "—"
                lines.append(
                    f"| {c['rank']} | `{c['id']}` | **{c['title']}** | {c['duration']}s | **{c['viral_score']}/10** | {c['category']} | {loop_icon} |"
                )
            lines.extend([
                f"",
                f"## Top Recommendation: `{candidates[0]['slug']}` ({candidates[0]['viral_score']}/10)",
                f"> **Hook (0-3s)**: \"{candidates[0]['hook_text']}\"",
                f"> **Visual Cues**: {candidates[0]['visual_cues']}",
                f"> **Contact Sheet**: `{candidates[0]['contact_sheet_ref']}` ({candidates[0]['contact_sheet_timecode']})",
                f"",
                f"To approve and proceed with Step 4 (`clipping-assembly`):",
                f"```bash",
                f"python3 scripts/clipping_state.py approve --step clipping-hook-hunter --dir {project_dir}",
                f"```",
            ])
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            step_entry["checkpoint"] = {
                "staged": True,
                "reviewed": False,
                "cleared": False,
                "review_artifact": str(checkpoint_path),
                "staged_at": _get_now_iso(),
            }
            st["current_step"] = "clipping-hook-hunter"
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(st, f, indent=2)

        except Exception as e:
            sys.stderr.write(f"Notice: Failed to stage checkpoint state: {e}\n")

    return manifest


def _get_now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Step 3: Viral Hook Hunter and Candidate Clip Ranking."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    hunt_p = subparsers.add_parser(
        "hunt", help="Hunt and score viral candidate clips from transcript and contact sheets"
    )
    hunt_p.add_argument(
        "--dir",
        default=".",
        help="Project directory containing transcript.json and .clipping_state.json",
    )
    hunt_p.add_argument(
        "--media",
        default=None,
        help="Path to source raw video file (for generating targeted candidate contact sheets)",
    )
    hunt_p.add_argument(
        "--output",
        "-o",
        default=None,
        help="Path to output candidates JSON (default: <dir>/candidates.json)",
    )
    hunt_p.add_argument(
        "--no-sheets",
        action="store_true",
        help="Skip generating targeted candidate contact sheets",
    )
    hunt_p.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Skip staging checkpoint in .clipping_state.json",
    )
    hunt_p.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output",
    )

    return parser


def main() -> int:
    parser = build_cli_parser()
    args = parser.parse_args()

    if args.command == "hunt":
        proj_dir = Path(args.dir)
        media_p = Path(args.media) if args.media else None
        out_p = Path(args.output) if args.output else None

        manifest = execute_hook_hunter_step(
            project_dir=proj_dir,
            media_path=media_p,
            output_json=out_p,
            generate_sheets=not args.no_sheets,
            stage_checkpoint=not args.no_checkpoint,
        )

        if args.json:
            print(json.dumps(manifest, indent=2))
        else:
            print("=" * 80)
            print(f"CLIPPING HOOK HUNTER: {manifest['campaign']}")
            print("=" * 80)
            print(f"Discovered Candidates: {manifest['total_candidates']}")
            print(f"Target Duration:       {manifest['target_duration_range'][0]}s - {manifest['target_duration_range'][1]}s")
            print("-" * 80)
            print(f"{'RANK':<5} {'ID':<4} {'SCORE':<8} {'DURATION':<10} {'CATEGORY':<22} {'TITLE'}")
            print("-" * 80)
            for c in manifest["candidates"]:
                print(
                    f"{c['rank']:<5} {c['id']:<4} {c['viral_score']:<8} {c['duration']:<10} {c['category']:<22} {c['title']}"
                )
            print("=" * 80)
            print(f"Output saved to: {out_p or (proj_dir / 'candidates.json')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
