#!/usr/bin/env python3
"""
scripts/clipping_state.py

State engine CLI with pre-flight transition gates for the Antigravity
Short-Form Clipping Pipeline Plugin.
Zero external runtime dependencies (stdlib only).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

STATE_FILENAME = ".clipping_state.json"

PIPELINE_STEPS: List[str] = [
    "clipping-guidelines",
    "clipping-transcription",
    "clipping-hook-hunter",
    "clipping-assembly",
    "clipping-captions",
    "clipping-vfx-sfx",
    "clipping-qc-packager",
]

PREFLIGHT_PREREQUISITES: Dict[str, Tuple[Optional[str], str]] = {
    "clipping-guidelines": (
        None,
        "",
    ),
    "clipping-transcription": (
        "clipping-guidelines",
        "Campaign guidelines must be approved before running transcription.",
    ),
    "clipping-hook-hunter": (
        "clipping-transcription",
        "Transcription must be completed before running hook hunting.",
    ),
    "clipping-assembly": (
        "clipping-hook-hunter",
        "Viral hook selection must be completed before timeline assembly.",
    ),
    "clipping-captions": (
        "clipping-assembly",
        "Timeline rough-cut assembly must be completed before captioning.",
    ),
    "clipping-vfx-sfx": (
        "clipping-captions",
        "Captions must be completed before VFX/SFX injection.",
    ),
    "clipping-qc-packager": (
        "clipping-vfx-sfx",
        "VFX/SFX must be completed before final QC and packaging.",
    ),
}


def _get_utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_state_path(project_dir: Optional[str]) -> Path:
    base = Path(project_dir).resolve() if project_dir else Path.cwd()
    return base / STATE_FILENAME


def _load_state(state_path: Path) -> Dict[str, Any]:
    if not state_path.is_file():
        sys.stderr.write(f"Error: {STATE_FILENAME} not found at {state_path}\n")
        sys.exit(1)
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        sys.stderr.write(f"Error reading {state_path}: {e}\n")
        sys.exit(1)


def _save_state(state_path: Path, state: Dict[str, Any]) -> None:
    state["updated_at"] = _get_utc_now_iso()
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        sys.stderr.write(f"Error writing to {state_path}: {e}\n")
        sys.exit(1)


def _is_step_completed(step_data: Dict[str, Any]) -> bool:
    return (
        step_data.get("status") in ("completed", "approved")
        or step_data.get("approved") is True
        or step_data.get("completed_at") is not None
    )


def cmd_init(args: argparse.Namespace) -> int:
    state_path = _get_state_path(args.dir)
    if state_path.is_file() and not args.force:
        sys.stderr.write(
            f"Error: {STATE_FILENAME} already exists at {state_path}. Use --force to overwrite.\n"
        )
        return 1

    now = _get_utc_now_iso()
    state: Dict[str, Any] = {
        "version": "1.0.0",
        "created_at": now,
        "updated_at": now,
        "current_step": "clipping-guidelines",
        "guidelines_approved": False,
        "campaign": {},
        "approval": {
            "approved": False,
            "timestamp": None,
            "approved_by": None,
            "notes": None,
            "overrides": {},
        },
        "steps": {
            step: {
                "status": "pending",
                "approved": False,
                "completed_at": None,
                "params": {},
            }
            for step in PIPELINE_STEPS
        },
    }

    _save_state(state_path, state)
    print(f"Initialized clipping pipeline state at {state_path}")
    return 0


def _parse_scalar(val: str) -> Any:
    val_lower = val.lower()
    if val_lower == "true":
        return True
    if val_lower == "false":
        return False
    if val_lower == "null" or val_lower == "none":
        return None
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        pass
    try:
        return json.loads(val)
    except Exception:
        return val


def cmd_ingest_brief(args: argparse.Namespace) -> int:
    state_path = _get_state_path(args.dir)
    state = _load_state(state_path)

    brief_path = Path(args.brief).resolve()
    if not brief_path.is_file():
        sys.stderr.write(f"Error: Brief file not found at {brief_path}\n")
        return 1

    try:
        with open(brief_path, "r", encoding="utf-8") as f:
            brief = json.load(f)
    except Exception as e:
        sys.stderr.write(f"Error parsing brief JSON: {e}\n")
        return 1

    # Extract or synthesize normalized campaign metadata
    raw_campaign = brief.get("campaign", {})
    raw_global_rules = brief.get("global_rules", {})
    raw_overrides = brief.get("platform_overrides", {})

    campaign_title = raw_campaign.get("title") or brief.get("title", "Untitled Campaign")
    client = raw_campaign.get("client") or brief.get("client", "Unknown Client")
    project = raw_campaign.get("project") or brief.get("project", "default-project")
    source_video = raw_campaign.get("source_video", {})
    source_url = (
        source_video.get("url")
        or raw_campaign.get("source_url")
        or brief.get("source_url", "")
    )
    platforms = raw_campaign.get("platforms") or [
        "TikTok",
        "Instagram Reels",
        "YouTube Shorts",
    ]
    economics = raw_campaign.get("economics", {})
    daily_post_limit = raw_campaign.get("daily_post_limit", 4)

    # Global rules & Tier-1 Defaults
    duration_rule = raw_global_rules.get("duration", {})
    min_dur = float(duration_rule.get("min_seconds", 20.0))
    max_dur = float(duration_rule.get("max_seconds", 60.0))
    ideal_min = float(duration_rule.get("ideal_min", 25.0))
    ideal_max = float(duration_rule.get("ideal_max", 45.0))

    tier1_geo = float(raw_global_rules.get("tier1_geo_min_pct", 40.0))
    engagement_min = float(raw_global_rules.get("engagement_min_pct", 1.0))

    watermark_rule = raw_global_rules.get("watermark", {})
    watermark_req = watermark_rule.get("required", True)
    watermark_asset = (
        watermark_rule.get("asset_path")
        or watermark_rule.get("asset")
        or "assets/watermark_yt_mpj.png"
    )

    caption_closers = (
        raw_global_rules.get("caption_closers")
        or raw_campaign.get("caption_closers")
        or []
    )

    audio_rule = raw_global_rules.get("audio", {})
    zero_bgm = audio_rule.get("zero_background_music", True)
    zero_phonk = audio_rule.get("zero_phonk", True)
    loudness_lufs = float(audio_rule.get("loudness_target_lufs", -14.0))

    # Pre-digested parameter slices per step
    guidelines_slice = {
        "campaign_title": campaign_title,
        "client": client,
        "project": project,
        "source_url": source_url,
        "platforms": platforms,
        "economics": economics,
        "daily_post_limit": daily_post_limit,
        "guidelines_source": str(brief_path),
    }

    transcription_slice = {
        "media_audio_path": brief.get("transcription", {}).get(
            "media_audio_path", f"raw/{project}_audio.wav"
        ),
        "sample_rate": brief.get("transcription", {}).get("sample_rate", 48000),
        "phonetic_dictionary": brief.get("transcription", {}).get(
            "phonetic_dictionary",
            {
                "ADIN": "Adin",
                "KICK": "Kick",
                "DUBAI": "Dubai",
                "MPJ": "MPJ",
                "STREAMERS": "streamers",
            },
        ),
        "diarization_speakers": brief.get("transcription", {}).get(
            "diarization_speakers", ["Speaker 1", "Speaker 2"]
        ),
    }

    hook_hunter_slice = {
        "target_duration_range": [ideal_min, ideal_max],
        "hard_bounds": [min_dur, max_dur],
        "hook_window_seconds": float(
            brief.get("hook_hunter", {}).get("hook_window_seconds", 3.0)
        ),
        "priority_hook_topics": brief.get("hook_hunter", {}).get(
            "priority_hook_topics",
            ["faked death", "dubai jail", "bank balance", "falling off fear"],
        ),
        "manifest_path": brief.get("hook_hunter", {}).get(
            "manifest_path", "references/campaign_manifest.json"
        ),
    }

    assembly_slice = {
        "canvas": {"width": 1080, "height": 1920, "aspect": "9:16"},
        "layout": brief.get("assembly", {}).get("layout", "smart-center"),
        "speaker_x_anchors": brief.get("assembly", {}).get(
            "speaker_x_anchors", {"N3on": 0.49, "MPJ": 0.53}
        ),
        "dead_air_threshold_seconds": float(
            brief.get("assembly", {}).get("dead_air_threshold_seconds", 0.4)
        ),
        "consonant_buffer_ms": int(
            brief.get("assembly", {}).get("consonant_buffer_ms", 80)
        ),
        "punch_ins_enabled": brief.get("assembly", {}).get("punch_ins_enabled", True),
    }

    captions_slice = {
        "caption_style": brief.get("captions", {}).get(
            "caption_style", "zylok_kinetic"
        ),
        "words_per_line_range": brief.get("captions", {}).get(
            "words_per_line_range", [1, 2]
        ),
        "margin_v": int(brief.get("captions", {}).get("margin_v", 420)),
        "primary_color": brief.get("captions", {}).get("primary_color", "#FFFFFF"),
        "highlight_colors": brief.get("captions", {}).get(
            "highlight_colors",
            {
                "neon_lime": "#CCFF00",
                "crimson_shock": "#FF0000",
            },
        ),
        "trigger_keywords": brief.get("captions", {}).get(
            "trigger_keywords",
            [
                "N3ON",
                "MPJ",
                "DUBAI",
                "JAIL",
                "DEATH",
                "MONEY",
                "MILLION",
                "BANK",
                "STREAMER",
                "NBA",
            ],
        ),
    }

    vfx_sfx_slice = {
        "watermark_required": watermark_req,
        "watermark_asset": watermark_asset,
        "watermark_track": "V3",
        "watermark_scale": 0.28,
        "watermark_position": "bottom-center",
        "disallowed_zones": [
            "top-left",
            "top-right",
            "bottom-left",
            "bottom-right",
            "caption-area",
        ],
        "title_hook_overlay": {"enabled": True, "start_time": 0.0, "duration": 2.5},
        "sound_design": {
            "allow_background_music": not zero_bgm,
            "allow_phonk": not zero_phonk,
            "sfx_transients": ["whoosh_in", "sub_boom_hit"],
            "dialogue_ducking_db": -3.0,
        },
    }

    qc_packager_slice = {
        "target_loudness_lufs": loudness_lufs,
        "loudness_standard": "EBU R128",
        "min_duration": min_dur,
        "max_duration": max_dur,
        "caption_closers": caption_closers,
        "submission_rules": {
            "whop_window_minutes": 30,
            "tier1_min_pct": tier1_geo,
            "engagement_min_pct": engagement_min,
            "min_views_for_payout": economics.get("min_payout_views", 2000),
        },
        "platform_overrides": raw_overrides,
    }

    state["campaign"] = {
        "title": campaign_title,
        "client": client,
        "project": project,
        "source_url": source_url,
        "platforms": platforms,
        "economics": economics,
        "daily_post_limit": daily_post_limit,
    }
    state["guidelines_approved"] = False

    if "steps" not in state:
        state["steps"] = {}

    step_slices = {
        "clipping-guidelines": guidelines_slice,
        "clipping-transcription": transcription_slice,
        "clipping-hook-hunter": hook_hunter_slice,
        "clipping-assembly": assembly_slice,
        "clipping-captions": captions_slice,
        "clipping-vfx-sfx": vfx_sfx_slice,
        "clipping-qc-packager": qc_packager_slice,
    }

    for step_name in PIPELINE_STEPS:
        if step_name not in state["steps"]:
            state["steps"][step_name] = {
                "status": "pending",
                "approved": False,
                "completed_at": None,
                "params": {},
            }
        state["steps"][step_name]["params"] = step_slices.get(step_name, {})

    state["steps"]["clipping-guidelines"]["status"] = "awaiting_approval"
    state["steps"]["clipping-guidelines"]["approved"] = False

    _save_state(state_path, state)
    print(f"Ingested brief from {brief_path} and sliced step configurations.")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    state_path = _get_state_path(args.dir)
    state = _load_state(state_path)

    step_name = args.step or "clipping-guidelines"
    if step_name not in PIPELINE_STEPS:
        sys.stderr.write(f"Error: Unknown step '{step_name}'\n")
        return 1

    overrides_dict: Dict[str, Any] = {}
    if args.override:
        for item in args.override:
            if "=" in item:
                k, v = item.split("=", 1)
                overrides_dict[k.strip()] = _parse_scalar(v.strip())
            else:
                overrides_dict[item.strip()] = True

    now = _get_utc_now_iso()
    if "steps" not in state:
        state["steps"] = {}
    if step_name not in state["steps"]:
        state["steps"][step_name] = {
            "status": "pending",
            "approved": False,
            "completed_at": None,
            "params": {},
        }

    state["steps"][step_name]["status"] = "completed"
    state["steps"][step_name]["approved"] = True
    state["steps"][step_name]["completed_at"] = now

    if step_name == "clipping-guidelines":
        state["guidelines_approved"] = True
        state["approval"] = {
            "approved": True,
            "timestamp": now,
            "approved_by": args.by or "human",
            "notes": args.notes,
            "overrides": overrides_dict,
        }

    # Advance current_step if applicable
    current_idx = PIPELINE_STEPS.index(step_name)
    if current_idx + 1 < len(PIPELINE_STEPS):
        state["current_step"] = PIPELINE_STEPS[current_idx + 1]

    _save_state(state_path, state)
    print(f"Approved step '{step_name}'. Guidelines approved: {state.get('guidelines_approved')}")
    return 0


def cmd_get_step_config(args: argparse.Namespace) -> int:
    state_path = _get_state_path(args.dir)
    state = _load_state(state_path)

    step_name = args.step
    if step_name not in state.get("steps", {}):
        sys.stderr.write(f"Error: Step '{step_name}' not found in state steps.\n")
        return 1

    step_params = state["steps"][step_name].get("params", {})
    print(json.dumps(step_params, indent=2, ensure_ascii=False))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    state_path = _get_state_path(args.dir)
    if not state_path.is_file():
        sys.stderr.write(
            f"Pre-flight Gate Blocked: {STATE_FILENAME} not found. Run init first.\n"
        )
        return 2

    state = _load_state(state_path)
    step_name = args.step
    if step_name not in PIPELINE_STEPS:
        sys.stderr.write(f"Error: Unknown step '{step_name}'\n")
        return 1

    steps_state = state.get("steps", {})

    # Check 1: Any step after clipping-guidelines requires guidelines_approved == True
    if step_name != "clipping-guidelines":
        if not state.get("guidelines_approved", False):
            msg = "Pre-flight Gate Blocked: Campaign guidelines must be approved before running transcription."
            if args.force:
                sys.stdout.write(f"[WARNING] Pre-flight gate bypassed with --force: {msg}\n")
                return 0
            sys.stderr.write(f"{msg}\n")
            return 2

    # Check 2: Sequential prerequisite step completion
    prereq_step, prereq_msg = PREFLIGHT_PREREQUISITES.get(step_name, (None, ""))
    if prereq_step:
        prereq_data = steps_state.get(prereq_step, {})
        if not _is_step_completed(prereq_data):
            msg = f"Pre-flight Gate Blocked: {prereq_msg}"
            if args.force:
                sys.stdout.write(f"[WARNING] Pre-flight gate bypassed with --force: {msg}\n")
                return 0
            sys.stderr.write(f"{msg}\n")
            return 2

    print(f"Pre-flight Gate Passed: Step '{step_name}' is cleared to execute.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state_path = _get_state_path(args.dir)
    state = _load_state(state_path)

    if args.json:
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0

    campaign = state.get("campaign", {})
    campaign_title = campaign.get("title", "Unconfigured Campaign")
    project = campaign.get("project", "default")
    client = campaign.get("client", "Unassigned")
    guidelines_appr = state.get("guidelines_approved", False)
    current_step = state.get("current_step", PIPELINE_STEPS[0])
    steps = state.get("steps", {})

    # Determine next runnable step
    next_step = None
    for step in PIPELINE_STEPS:
        s_data = steps.get(step, {})
        if not _is_step_completed(s_data):
            next_step = step
            break

    print("=" * 80)
    print("CLIPPING PIPELINE STATUS")
    print("=" * 80)
    print(f"Campaign:     {campaign_title} ({project})")
    print(f"Client:       {client}")
    print(f"Guidelines:   {'[APPROVED]' if guidelines_appr else '[AWAITING APPROVAL / PENDING]'}")
    print(f"Current Step: {current_step}")
    print(f"Next Step:    {next_step or 'None (All steps completed)'}")
    print("-" * 80)
    print(f"{'STEP':<26} {'STATUS':<20} {'APPROVED':<10} {'COMPLETED AT':<20}")
    print("-" * 80)
    for step in PIPELINE_STEPS:
        s_data = steps.get(step, {})
        status = s_data.get("status", "pending")
        approved = str(s_data.get("approved", False))
        completed_at = s_data.get("completed_at") or "-"
        print(f"{step:<26} {status:<20} {approved:<10} {completed_at:<20}")
    print("=" * 80)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clipping Pipeline State Engine CLI (clipping_state.py)"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # init
    p_init = subparsers.add_parser("init", help="Initialize .clipping_state.json")
    p_init.add_argument("--dir", default=None, help="Target project directory")
    p_init.add_argument(
        "--force", action="store_true", help="Force overwrite existing state file"
    )

    # ingest-brief
    p_ingest = subparsers.add_parser("ingest-brief", help="Ingest campaign brief JSON")
    p_ingest.add_argument("--brief", required=True, help="Path to campaign_brief.json")
    p_ingest.add_argument("--dir", default=None, help="Target project directory")

    # approve
    p_approve = subparsers.add_parser("approve", help="Approve step / guidelines")
    p_approve.add_argument(
        "--step",
        default="clipping-guidelines",
        help="Step to approve (default: clipping-guidelines)",
    )
    p_approve.add_argument(
        "--override",
        nargs="*",
        help="Optional key=value overrides to store in approval record",
    )
    p_approve.add_argument("--notes", default=None, help="Approval notes")
    p_approve.add_argument("--by", default="human", help="Approver identity")
    p_approve.add_argument("--dir", default=None, help="Target project directory")

    # get-step-config
    p_get = subparsers.add_parser("get-step-config", help="Get step configuration slice")
    p_get.add_argument("--step", required=True, help="Step name to retrieve params for")
    p_get.add_argument("--dir", default=None, help="Target project directory")
    p_get.add_argument("--json", action="store_true", help="Output in JSON format (default)")

    # validate
    p_validate = subparsers.add_parser(
        "validate", help="Validate pre-flight gate for a step"
    )
    p_validate.add_argument("--step", required=True, help="Step to validate")
    p_validate.add_argument("--dir", default=None, help="Target project directory")
    p_validate.add_argument(
        "--force", action="store_true", help="Bypass gate failure with warning"
    )

    # status
    p_status = subparsers.add_parser("status", help="Show pipeline status")
    p_status.add_argument("--dir", default=None, help="Target project directory")
    p_status.add_argument("--json", action="store_true", help="Output status as JSON")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "init": cmd_init,
        "ingest-brief": cmd_ingest_brief,
        "approve": cmd_approve,
        "get-step-config": cmd_get_step_config,
        "validate": cmd_validate,
        "status": cmd_status,
    }

    cmd_fn = dispatch.get(args.command)
    if not cmd_fn:
        parser.print_help()
        sys.exit(1)

    code = cmd_fn(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
