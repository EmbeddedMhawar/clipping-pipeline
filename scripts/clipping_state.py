#!/usr/bin/env python3
"""
scripts/clipping_state.py

State engine CLI with pre-flight transition gates for the Antigravity
Short-Form Clipping Pipeline Plugin.
Zero external runtime dependencies (stdlib only).
"""

import argparse
import copy
import json
import os
import shutil
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Ensure sibling scripts can be imported cleanly
try:
    from scripts import gui_companion, clipping_preferences
except ImportError:
    try:
        import gui_companion
        import clipping_preferences
    except ImportError:
        _scripts_dir = Path(__file__).resolve().parent
        if str(_scripts_dir) not in sys.path:
            sys.path.insert(0, str(_scripts_dir))
        if str(_scripts_dir.parent) not in sys.path:
            sys.path.insert(0, str(_scripts_dir.parent))
        import gui_companion
        import clipping_preferences

STATE_FILENAME = ".clipping_state.json"
CHANNELS_FILENAME = "channels.json"

PLATFORM_ALIASES: Dict[str, str] = {
    "tiktok": "TikTok",
    "instagram": "Instagram Reels",
    "instagram reels": "Instagram Reels",
    "ig": "Instagram Reels",
    "reels": "Instagram Reels",
    "youtube": "YouTube Shorts",
    "youtube shorts": "YouTube Shorts",
    "yt": "YouTube Shorts",
    "shorts": "YouTube Shorts",
}

PIPELINE_STEPS: List[str] = [
    "clipping-guidelines",
    "clipping-transcription",
    "clipping-hook-hunter",
    "clipping-assembly",
    "clipping-captions",
    "clipping-vfx-sfx",
    "clipping-qc-packager",
    "clipping-publisher",
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
    "clipping-publisher": (
        "clipping-qc-packager",
        "Final QC packaging must be completed before distribution/publishing.",
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
    cp = step_data.get("checkpoint", {})
    if cp.get("staged") and not cp.get("reviewed"):
        return False
    return (
        step_data.get("status") in ("completed", "approved")
        or step_data.get("approved") is True
        or step_data.get("completed_at") is not None
    )


def _normalize_platform(plat: str) -> str:
    key = str(plat).strip().lower()
    return PLATFORM_ALIASES.get(key, plat)


def _resolve_channels_path(
    project_dir: Optional[Path] = None, channels_arg: Optional[str] = None
) -> Optional[Path]:
    if channels_arg:
        cp = Path(channels_arg).resolve()
        if cp.is_file():
            return cp
    base = project_dir if project_dir else Path.cwd()
    # 1. Project directory
    cand = base / CHANNELS_FILENAME
    if cand.is_file():
        return cand
    # 2. Parent directory (e.g. workspace level)
    cand_parent = base.parent / CHANNELS_FILENAME
    if cand_parent.is_file():
        return cand_parent
    # 3. Current working directory
    cand_cwd = Path.cwd() / CHANNELS_FILENAME
    if cand_cwd.is_file():
        return cand_cwd
    return None


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
        or ""
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
            "phonetic_dictionary", {}
        ),
        "diarization_speakers": brief.get("transcription", {}).get(
            "diarization_speakers", []
        ),
    }

    hook_hunter_slice = {
        "target_duration_range": [ideal_min, ideal_max],
        "hard_bounds": [min_dur, max_dur],
        "hook_window_seconds": float(
            brief.get("hook_hunter", {}).get("hook_window_seconds", 3.0)
        ),
        "priority_hook_topics": brief.get("hook_hunter", {}).get(
            "priority_hook_topics", []
        ),
        "manifest_path": brief.get("hook_hunter", {}).get(
            "manifest_path", "references/campaign_manifest.json"
        ),
    }

    assembly_slice = {
        "canvas": {"width": 1080, "height": 1920, "aspect": "9:16"},
        "layout": brief.get("assembly", {}).get("layout", "smart-center"),
        "speaker_x_anchors": brief.get("assembly", {}).get(
            "speaker_x_anchors", {}
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
            "trigger_keywords", []
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
        "clipping-publisher": {},
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

    # Checkpoint gate verification
    step_data = state.get("steps", {}).get(step_name, {})
    checkpoint = step_data.get("checkpoint")
    if checkpoint and checkpoint.get("staged", False):
        if not checkpoint.get("reviewed", False) and not getattr(args, "force", False):
            sys.stderr.write(
                f"Checkpoint Gate Blocked: Step '{step_name}' has an unresolved feedback checkpoint pending review. "
                f"Review artifact: {checkpoint.get('review_artifact', 'N/A')}. "
                f"Register feedback via 'checkpoint --step {step_name} --feedback \"...\"' or pass --force.\n"
            )
            return 2
        elif not checkpoint.get("reviewed", False) and getattr(args, "force", False):
            sys.stdout.write(
                f"[WARNING] Checkpoint gate bypassed with --force for step '{step_name}'.\n"
            )

    if step_name == "clipping-publisher":
        step_params = state.get("steps", {}).get(step_name, {}).get("params", {})
        pub_manifest = step_params.get("publication_manifest")
        if not pub_manifest and not getattr(args, "force", False):
            sys.stderr.write(
                "Error: Cannot approve 'clipping-publisher' without publication_manifest. "
                "Execute 'scripts/clipping_publisher.py publish' first, or pass --force.\n"
            )
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

    if checkpoint:
        checkpoint["reviewed"] = True
        checkpoint["cleared"] = True
        checkpoint["approved"] = True
        checkpoint["approved_at"] = now
        if state.get("checkpoint", {}).get("step") == step_name:
            state["checkpoint"]["reviewed"] = True
            state["checkpoint"]["cleared"] = True
            state["checkpoint"]["approved"] = True
            state["checkpoint"]["approved_at"] = now

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

    step_params = copy.deepcopy(state["steps"][step_name].get("params", {}))

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

    # Check 0: Step 1 guidelines advisory check for channels.json
    if step_name == "clipping-guidelines":
        channels_file = _resolve_channels_path(
            state_path.parent, getattr(args, "channels", None)
        )
        if not channels_file:
            sys.stderr.write(
                "[Notice] Workspace channel portfolio (channels.json) not found. "
                "Run 'python3 scripts/clipping_channels.py init' if managing multi-channel warmup.\n"
            )

    # Check 1: Any step after clipping-guidelines requires guidelines_approved == True
    if step_name != "clipping-guidelines":
        if not state.get("guidelines_approved", False):
            msg = f"Pre-flight Gate Blocked: Campaign guidelines must be approved before running '{step_name}'."
            if args.force:
                sys.stdout.write(f"[WARNING] Pre-flight gate bypassed with --force: {msg}\n")
                return 0
            sys.stderr.write(f"{msg}\n")
            return 2

    # Check 2: Sequential prerequisite step completion
    prereq_step, prereq_msg = PREFLIGHT_PREREQUISITES.get(step_name, (None, ""))
    if prereq_step:
        prereq_data = steps_state.get(prereq_step, {})
        prereq_cp = prereq_data.get("checkpoint", {})
        if prereq_cp.get("staged", False) and not prereq_cp.get("reviewed", False):
            msg = f"Pre-flight Gate Blocked: Prerequisite step '{prereq_step}' has an active feedback checkpoint pending review."
            if args.force:
                sys.stdout.write(f"[WARNING] Pre-flight gate bypassed with --force: {msg}\n")
                return 0
            sys.stderr.write(f"{msg}\n")
            return 2

        if not _is_step_completed(prereq_data):
            msg = f"Pre-flight Gate Blocked: {prereq_msg}"
            if args.force:
                sys.stdout.write(f"[WARNING] Pre-flight gate bypassed with --force: {msg}\n")
                return 0
            sys.stderr.write(f"{msg}\n")
            return 2

    print(f"Pre-flight Gate Passed: Step '{step_name}' is cleared to execute.")
    return 0


def _generate_review_artifact(
    artifact_path: Path,
    step_name: str,
    state: Dict[str, Any],
    companion_status: Dict[str, Any],
    project_file: Optional[Path],
    diff_results: Dict[str, Any],
    feedback: str,
    directives: List[Dict[str, Any]],
    reviewed: bool,
    timestamp: str,
) -> None:
    campaign = state.get("campaign", {})
    title = campaign.get("title", "Untitled Campaign")
    project = campaign.get("project", "default")
    step_params = state.get("steps", {}).get(step_name, {}).get("params", {})

    status_str = "REVIEWED / CLEARED" if reviewed else "PENDING HUMAN REVIEW (GATE PAUSED)"
    companion_str = (
        f"Active on port {companion_status.get('port')} (playhead {companion_status.get('playhead_seconds', 0.0):.2f}s)"
        if companion_status.get("active")
        else "Disconnected / Offline"
    )

    lines = [
        "---",
        "RequestFeedback: true",
        f"Summary: Checkpoint review for step '{step_name}' in project '{project}'",
        "UserFacing: true",
        "---",
        "",
        f"# Checkpoint Review: `{step_name}`",
        "",
        "> [!IMPORTANT]",
        f"> **Feedback Checkpoint State**: {status_str}",
        f"> Staged at `{timestamp}`. Downstream step execution and approval are gated until human feedback is registered.",
        "",
        "## Summary Metrics",
        f"- **Pipeline Step**: `{step_name}`",
        f"- **Campaign / Project**: `{title}` (`{project}`)",
        f"- **Review Status**: `{status_str}`",
        f"- **GUI Companion**: {companion_str}",
        f"- **Project File**: `{project_file.name if project_file else 'N/A'}`",
        "",
        "## Active Step Parameters Slice",
        "```json",
        json.dumps(step_params, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Codified Directives & Preferences",
    ]

    if feedback:
        lines.append(f"- **Chat Feedback**: \"{feedback}\"")
    else:
        lines.append("- **Chat Feedback**: *(None provided yet)*")

    if directives:
        lines.append("- **Parsed Directives**:")
        for d in directives:
            lines.append(f"  - `{d.get('directive')}`: {d.get('explanation')}")

    diffs = diff_results.get("differences", [])
    if diffs:
        lines.append(f"- **Detected Manual Timeline Edits ({len(diffs)})**:")
        for df in diffs:
            lines.append(f"  - **{df.get('category')}**: {df.get('description')}")
    else:
        lines.append("- **Manual Edits**: *(No unsaved GUI diffs detected)*")

    lines.extend([
        "",
        "## Operator Action Guidance",
        "1. **Inspect Timeline in FilmCraft**:",
        "   ```bash",
        "   python3 scripts/gui_companion.py seek --seconds 0.0",
        "   python3 scripts/gui_companion.py play",
        "   ```",
        "2. **Register Chat Directives / Feedback**:",
        "   ```bash",
        f"   python3 scripts/clipping_state.py checkpoint --step {step_name} --feedback \"<your instructions>\"",
        "   ```",
        "3. **Approve Step & Unblock Pipeline**:",
        "   ```bash",
        f"   python3 scripts/clipping_state.py approve --step {step_name}",
        "   ```",
        "",
    ])

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with open(artifact_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def cmd_checkpoint(args: argparse.Namespace) -> int:
    state_path = _get_state_path(args.dir)
    state = _load_state(state_path)
    project_dir = state_path.parent

    step_name = args.step
    if step_name not in PIPELINE_STEPS:
        sys.stderr.write(f"Error: Unknown step '{step_name}'\n")
        return 1

    steps_state = state.setdefault("steps", {})
    step_data = steps_state.setdefault(
        step_name,
        {
            "status": "pending",
            "approved": False,
            "completed_at": None,
            "params": {},
        },
    )

    # a) Pre-flight check: validates that the step has finished its execution data
    # (status == 'completed' or staged data ready)
    is_completed_or_staged = (
        step_data.get("status")
        in (
            "completed",
            "staged",
            "awaiting_approval",
            "awaiting_checkpoint",
            "checkpoint_reviewed",
            "approved",
        )
        or step_data.get("staged") is True
        or step_data.get("completed_at") is not None
        or (step_data.get("checkpoint", {}).get("staged") is True)
    )

    existing_fcproj = list(project_dir.glob("*.fcproj"))
    has_execution_data = is_completed_or_staged or bool(existing_fcproj)

    if not has_execution_data and not getattr(args, "force", False):
        sys.stderr.write(
            f"Pre-flight Gate Blocked: Step '{step_name}' has not finished execution data "
            f"(status is '{step_data.get('status')}'). Complete step execution or pass --force.\n"
        )
        return 2

    now = _get_utc_now_iso()

    # Resolve project files for companion & diffing
    project_file: Optional[Path] = None
    if getattr(args, "project_file", None):
        pf = Path(args.project_file)
        if pf.is_file():
            project_file = pf
    if not project_file:
        proj_name = state.get("campaign", {}).get("project")
        if proj_name:
            cand = project_dir / f"{proj_name}.fcproj"
            if cand.is_file():
                project_file = cand
        if not project_file:
            candidates = [
                p
                for p in project_dir.glob("*.fcproj")
                if not p.name.startswith("baseline_") and p.name != "baseline.fcproj"
            ]
            if candidates:
                project_file = candidates[0]
            elif existing_fcproj:
                project_file = existing_fcproj[0]

    # Resolve or initialize baseline file
    baseline_file: Optional[Path] = None
    if getattr(args, "baseline_file", None):
        bf = Path(args.baseline_file)
        if bf.is_file():
            baseline_file = bf
    if not baseline_file and project_file:
        cand_base = project_dir / f"baseline_{project_file.name}"
        if cand_base.is_file():
            baseline_file = cand_base
        elif (project_dir / "baseline.fcproj").is_file():
            baseline_file = project_dir / "baseline.fcproj"
        else:
            baseline_file = cand_base
            try:
                shutil.copy2(project_file, baseline_file)
            except Exception:
                pass

    # b) Companion sync: queries scripts/gui_companion.py status.
    # If GUI companion is active and project exists, triggers gui_companion.py reload
    # to refresh the timeline in FilmCraft, and starts/checks project file watcher.
    companion_status: Dict[str, Any] = {"active": False, "connected": False}
    try:
        health = gui_companion.check_health(base_dir=project_dir, timeout=1.0)
        if health.get("connected"):
            companion_status = {
                "active": True,
                "connected": True,
                "port": health.get("port"),
                "pid": health.get("pid"),
                "project_name": health.get("project_name"),
                "playhead_seconds": health.get("playhead_seconds"),
                "playhead_timecode": health.get("playhead_timecode"),
                "dirty": health.get("dirty"),
                "revision": health.get("revision"),
            }
            if project_file and project_file.is_file():
                try:
                    rel_res = gui_companion.reload_timeline(
                        project_path=str(project_file),
                        port=health.get("port"),
                        base_dir=project_dir,
                    )
                    companion_status["reloaded"] = True
                    companion_status["reload_action"] = rel_res.get("action")
                except Exception as ex:
                    companion_status["reload_error"] = str(ex)

            # Start/check project file watcher
            if project_file and project_file.is_file():
                watcher_flag = project_dir / gui_companion.DEFAULT_FLAG_FILENAME
                companion_status["watcher_flag_path"] = str(watcher_flag)
                companion_status["watcher_armed"] = True
    except Exception as e:
        companion_status["error"] = str(e)

    # c) Save detection / diffing: if the operator saved manual changes in FilmCraft
    # (detected via .gui_companion_saved.flag or mtime diff), automatically runs
    # scripts/clipping_preferences.py diff-project against the agent baseline and saves learned preferences.
    flag_file = project_dir / gui_companion.DEFAULT_FLAG_FILENAME
    flag_detected = flag_file.is_file()
    mtime_diff_detected = False
    prev_baseline_mtime = step_data.get("checkpoint", {}).get("baseline_mtime")

    if (
        project_file
        and project_file.is_file()
        and baseline_file
        and baseline_file.is_file()
    ):
        p_mtime = project_file.stat().st_mtime
        b_mtime = baseline_file.stat().st_mtime
        if p_mtime > b_mtime or (
            prev_baseline_mtime and p_mtime > prev_baseline_mtime
        ):
            mtime_diff_detected = True

    diff_triggered = (
        flag_detected or mtime_diff_detected or getattr(args, "diff_project", False)
    )
    diff_results: Dict[str, Any] = {}
    preferences_from_diff: Dict[str, Any] = {}

    if (
        diff_triggered
        and project_file
        and baseline_file
        and baseline_file.is_file()
        and project_file.is_file()
    ):
        try:
            diff_results = clipping_preferences.diff_project_heuristic(
                baseline_file, project_file
            )
            codified = diff_results.get("codified_preferences", {})
            preferences_from_diff = codified
            if codified:
                pref_store = clipping_preferences.PreferenceStore(
                    project_dir=project_dir
                )
                for k, v in clipping_preferences.flatten_dict(codified).items():
                    pref_store.set(k, v, scope="project")
                print(
                    f"[Checkpoint Diff] Codified {len(diff_results.get('differences', []))} preferences from FilmCraft edit into .clipping_preferences.json"
                )
            if flag_file.is_file():
                flag_file.unlink(missing_ok=True)
        except Exception as ex:
            diff_results["error"] = str(ex)

    # d) Chat feedback parsing: if --feedback "<text>" is passed, runs
    # scripts/clipping_preferences.py parse-feedback to codify directives.
    directives: List[Dict[str, Any]] = []
    preferences_from_chat: Dict[str, Any] = {}
    if args.feedback:
        try:
            directives, proposed = clipping_preferences.parse_feedback_directives(
                args.feedback
            )
            preferences_from_chat = proposed
            if proposed:
                pref_store = clipping_preferences.PreferenceStore(
                    project_dir=project_dir
                )
                for k, v in clipping_preferences.flatten_dict(proposed).items():
                    pref_store.set(k, v, scope="project")
                print(
                    f"[Checkpoint Feedback] Codified {len(directives)} directives into .clipping_preferences.json: '{args.feedback}'"
                )
        except Exception as ex:
            preferences_from_chat["error"] = str(ex)

    # Determine reviewed status:
    # If feedback was given, or auto_approve is set, or previously reviewed:
    is_reviewed = (
        bool(args.feedback)
        or bool(args.auto_approve)
        or (
            step_data.get("checkpoint", {}).get("reviewed", False)
            and not getattr(args, "diff_project", False)
        )
    )

    # g) Review artifact generation: renders markdown checkpoint review artifact
    # with summary metrics and RequestFeedback: true metadata.
    artifact_path = project_dir / f"checkpoint_{step_name}.md"
    _generate_review_artifact(
        artifact_path=artifact_path,
        step_name=step_name,
        state=state,
        companion_status=companion_status,
        project_file=project_file,
        diff_results=diff_results,
        feedback=args.feedback
        or step_data.get("checkpoint", {}).get("feedback", ""),
        directives=directives,
        reviewed=is_reviewed,
        timestamp=now,
    )

    # e) State tracking: records checkpoint status in .clipping_state.json:
    # "checkpoint": { "staged": true, "reviewed": false, "review_artifact": "...", "feedback": "...", "timestamp": "..." }
    checkpoint_record: Dict[str, Any] = {
        "staged": True,
        "reviewed": is_reviewed,
        "review_artifact": str(artifact_path),
        "feedback": args.feedback
        or step_data.get("checkpoint", {}).get("feedback", ""),
        "timestamp": now,
        "step": step_name,
        "preferences_updated": bool(preferences_from_diff or preferences_from_chat),
        "diff_detected": bool(diff_results.get("differences")),
        "companion_active": companion_status.get("active", False),
    }
    if project_file and project_file.is_file():
        checkpoint_record["project_file"] = str(project_file)
        checkpoint_record["baseline_mtime"] = project_file.stat().st_mtime
    if baseline_file and baseline_file.is_file():
        checkpoint_record["baseline_file"] = str(baseline_file)

    step_data["checkpoint"] = checkpoint_record
    state["checkpoint"] = checkpoint_record

    if not is_reviewed:
        step_data["status"] = "awaiting_checkpoint"
    else:
        step_data["status"] = "checkpoint_reviewed"

    # Auto-approve if requested
    if args.auto_approve:
        step_data["status"] = "completed"
        step_data["approved"] = True
        step_data["completed_at"] = now
        checkpoint_record["cleared"] = True
        checkpoint_record["approved"] = True
        checkpoint_record["approved_at"] = now
        if step_name == "clipping-guidelines":
            state["guidelines_approved"] = True
        current_idx = PIPELINE_STEPS.index(step_name)
        if current_idx + 1 < len(PIPELINE_STEPS):
            state["current_step"] = PIPELINE_STEPS[current_idx + 1]

    _save_state(state_path, state)

    if args.json:
        print(json.dumps(checkpoint_record, indent=2))
        return 0

    print("=" * 80)
    print(f"CHECKPOINT STATE GATE: {step_name}")
    print("=" * 80)
    print(
        f"Status:          {'[REVIEWED]' if is_reviewed else '[AWAITING HUMAN REVIEW - GATE PAUSED]'}"
    )
    print(f"Review Artifact: {artifact_path}")
    print(f"Feedback:        {checkpoint_record['feedback'] or '(None)'}")
    print(
        f"Companion Sync:  {'Connected (port ' + str(companion_status.get('port')) + ')' if companion_status.get('active') else 'Disconnected'}"
    )
    if diff_results.get("differences"):
        print(
            f"Project Diffs:   {len(diff_results['differences'])} edits codified into preferences"
        )
    if directives:
        print(
            f"Chat Directives: {len(directives)} directives parsed into preferences"
        )
    if args.auto_approve:
        print(
            f"Auto-Approve:    Step '{step_name}' approved. Next step: {state.get('current_step')}"
        )
    print("=" * 80)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state_path = _get_state_path(args.dir)
    state = _load_state(state_path)

    channels_file = _resolve_channels_path(
        state_path.parent, getattr(args, "channels", None)
    )

    if not channels_file:
        sys.stderr.write(
            "[Notice] Workspace channel portfolio (channels.json) not found. "
            "Run 'python3 scripts/clipping_channels.py init' if managing multi-channel warmup.\n"
        )
        state["portfolio_notice"] = (
            "[Notice] Workspace channel portfolio (channels.json) not found. "
            "Run 'python3 scripts/clipping_channels.py init' if managing multi-channel warmup."
        )

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
    if channels_file:
        print(f"Portfolio:    [CONFIGURED] {channels_file.name}")
    else:
        print("Portfolio:    [NOTICE] channels.json not found (run 'python3 scripts/clipping_channels.py init')")
    print(f"Current Step: {current_step}")
    print(f"Next Step:    {next_step or 'None (All steps completed)'}")
    checkpoint_info = state.get("checkpoint")
    if checkpoint_info:
        cp_step = checkpoint_info.get("step", "active")
        cp_rev = checkpoint_info.get("reviewed", False)
        cp_art = checkpoint_info.get("review_artifact", "N/A")
        print(f"Checkpoint:   {'[REVIEWED]' if cp_rev else '[AWAITING REVIEW - PAUSED]'} ({cp_step}) -> {cp_art}")
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
    p_ingest.add_argument("--channels", default=None, help="Path to channels.json")

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
    p_approve.add_argument(
        "--force",
        action="store_true",
        help="Force approve step bypassing validation checks",
    )

    # checkpoint
    p_checkpoint = subparsers.add_parser(
        "checkpoint",
        help="Interactive checkpoint state gate with GUI companion sync and preference codification",
    )
    p_checkpoint.add_argument(
        "--step",
        required=True,
        help="Step name to stage/review checkpoint for (e.g. clipping-assembly)",
    )
    p_checkpoint.add_argument(
        "--dir",
        default=None,
        help="Target project directory",
    )
    p_checkpoint.add_argument(
        "--feedback",
        default=None,
        help="Natural language operator feedback / directives to parse and codify",
    )
    p_checkpoint.add_argument(
        "--diff-project",
        action="store_true",
        help="Force differential analysis between baseline and user .fcproj",
    )
    p_checkpoint.add_argument(
        "--auto-approve",
        action="store_true",
        help="Automatically approve the step once checkpoint is staged/reviewed",
    )
    p_checkpoint.add_argument(
        "--project-file",
        default=None,
        help="Path to user/active .fcproj file (optional)",
    )
    p_checkpoint.add_argument(
        "--baseline-file",
        default=None,
        help="Path to baseline .fcproj file (optional)",
    )
    p_checkpoint.add_argument(
        "--force",
        action="store_true",
        help="Bypass execution pre-flight checks if step data is not yet finished",
    )
    p_checkpoint.add_argument(
        "--json",
        action="store_true",
        help="Output JSON response",
    )

    # get-step-config
    p_get = subparsers.add_parser("get-step-config", help="Get step configuration slice")
    p_get.add_argument("--step", required=True, help="Step name to retrieve params for")
    p_get.add_argument("--dir", default=None, help="Target project directory")
    p_get.add_argument("--channels", default=None, help="Path to channels.json")
    p_get.add_argument("--json", action="store_true", help="Output in JSON format (default)")

    # validate
    p_validate = subparsers.add_parser(
        "validate", help="Validate pre-flight gate for a step"
    )
    p_validate.add_argument("--step", required=True, help="Step to validate")
    p_validate.add_argument("--dir", default=None, help="Target project directory")
    p_validate.add_argument("--channels", default=None, help="Path to channels.json")
    p_validate.add_argument(
        "--force", action="store_true", help="Bypass gate failure with warning"
    )

    # status
    p_status = subparsers.add_parser("status", help="Show pipeline status")
    p_status.add_argument("--dir", default=None, help="Target project directory")
    p_status.add_argument("--channels", default=None, help="Path to channels.json")
    p_status.add_argument("--json", action="store_true", help="Output status as JSON")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "init": cmd_init,
        "ingest-brief": cmd_ingest_brief,
        "approve": cmd_approve,
        "checkpoint": cmd_checkpoint,
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
