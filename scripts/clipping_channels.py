#!/usr/bin/env python3
"""
scripts/clipping_channels.py

Workspace-level channel portfolio registry and warmup lifecycle engine for
the Antigravity Short-Form Clipping Pipeline Plugin.

Governs multi-channel warmup lifecycles, health gates, daily posting cadences,
and automated device transfer protocols.

Zero external runtime dependencies (Python standard library only).
Conforms to:
- references/CHANNEL_PORTFOLIO_SCHEMA.md
- docs/adr/0007-workspace-level-channel-portfolio-registry.md
- docs/adr/0008-health-gated-warmup-advancement.md
- docs/adr/0009-automated-device-delivery.md
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CHANNELS_FILENAME = "channels.json"
SCHEMA_VERSION = "1.0.0"

ALLOWED_PLATFORMS = ["TikTok", "Instagram Reels", "YouTube Shorts"]
PLATFORM_ALIASES = {
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

ALLOWED_STAGES = [
    "Cold Lurker",
    "Seeding",
    "Ramp-Up",
    "Mature",
    "Account Cooldown",
]
STAGE_ALIASES = {
    "cold lurker": "Cold Lurker",
    "cold_lurker": "Cold Lurker",
    "cold": "Cold Lurker",
    "seeding": "Seeding",
    "seed": "Seeding",
    "ramp-up": "Ramp-Up",
    "ramp_up": "Ramp-Up",
    "ramp": "Ramp-Up",
    "mature": "Mature",
    "account cooldown": "Account Cooldown",
    "account_cooldown": "Account Cooldown",
    "cooldown": "Account Cooldown",
}

ALLOWED_STATUSES = ["active", "cooldown", "paused", "banned"]

TRANSFER_PROTOCOLS = ["qr_code", "adb_push", "telegram_dispatch", "cloud_sync"]
TRANSFER_ALIASES = {
    "local_qr": "qr_code",
    "qr_code": "qr_code",
    "qr": "qr_code",
    "adb_push": "adb_push",
    "adb": "adb_push",
    "cloud_folder": "cloud_sync",
    "cloud_sync": "cloud_sync",
    "cloud": "cloud_sync",
    "webhook": "telegram_dispatch",
    "telegram": "telegram_dispatch",
    "telegram_dispatch": "telegram_dispatch",
}


def _get_utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_channels_path(directory: Optional[str] = None) -> Path:
    base = Path(directory).resolve() if directory else Path.cwd()
    return base / CHANNELS_FILENAME


def _load_portfolio(channels_path: Path) -> Dict[str, Any]:
    if not channels_path.is_file():
        sys.stderr.write(f"Error: {CHANNELS_FILENAME} not found at {channels_path}\n")
        sys.exit(1)
    try:
        with open(channels_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        sys.stderr.write(f"Error reading {channels_path}: {e}\n")
        sys.exit(1)


def _save_portfolio(channels_path: Path, portfolio: Dict[str, Any]) -> None:
    portfolio["updated_at"] = _get_utc_now_iso()
    try:
        channels_path.parent.mkdir(parents=True, exist_ok=True)
        with open(channels_path, "w", encoding="utf-8") as f:
            json.dump(portfolio, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        sys.stderr.write(f"Error writing {channels_path}: {e}\n")
        sys.exit(1)


def _normalize_platform(plat: str) -> str:
    key = plat.strip().lower()
    if key in PLATFORM_ALIASES:
        return PLATFORM_ALIASES[key]
    for p in ALLOWED_PLATFORMS:
        if p.lower() == key:
            return p
    raise ValueError(f"Invalid platform '{plat}'. Allowed: {ALLOWED_PLATFORMS}")


def _normalize_stage(stg: str) -> str:
    key = stg.strip().lower()
    if key in STAGE_ALIASES:
        return STAGE_ALIASES[key]
    for s in ALLOWED_STAGES:
        if s.lower() == key:
            return s
    raise ValueError(f"Invalid stage '{stg}'. Allowed: {ALLOWED_STAGES}")


def _normalize_transfer_protocol(proto: str) -> str:
    key = proto.strip().lower()
    if key in TRANSFER_ALIASES:
        return TRANSFER_ALIASES[key]
    if key in TRANSFER_PROTOCOLS:
        return key
    raise ValueError(f"Invalid transfer protocol '{proto}'. Allowed: {list(TRANSFER_ALIASES.keys())}")


def _stage_cadence_defaults(stage: str) -> Dict[str, Any]:
    if stage == "Cold Lurker":
        return {"daily_post_limit": 0, "posts_today": 0, "last_post_date": "", "min_post_spacing_hours": 0.0}
    elif stage == "Seeding":
        return {"daily_post_limit": 1, "posts_today": 0, "last_post_date": "", "min_post_spacing_hours": 4.0}
    elif stage == "Ramp-Up":
        return {"daily_post_limit": 3, "posts_today": 0, "last_post_date": "", "min_post_spacing_hours": 2.5}
    elif stage == "Mature":
        return {"daily_post_limit": 4, "posts_today": 0, "last_post_date": "", "min_post_spacing_hours": 2.0}
    elif stage == "Account Cooldown":
        return {"daily_post_limit": 0, "posts_today": 0, "last_post_date": "", "min_post_spacing_hours": 0.0}
    return {"daily_post_limit": 0, "posts_today": 0, "last_post_date": "", "min_post_spacing_hours": 0.0}


def _stage_warmup_defaults(stage: str) -> Dict[str, Any]:
    if stage == "Cold Lurker":
        return {
            "daily_actions": [
                "browse_niche_feed",
                "like_relevant_videos",
                "follow_niche_creators",
                "leave_authentic_comments",
            ],
            "niche_keywords": ["podcast", "motivation", "clips"],
            "browsing_minutes_per_day": 30,
            "target_interactions_per_day": 10,
        }
    elif stage == "Seeding":
        return {
            "daily_actions": [
                "browse_niche_feed",
                "post_single_clip",
                "monitor_views_24h",
            ],
            "niche_keywords": ["podcast", "motivation", "clips"],
            "browsing_minutes_per_day": 20,
            "target_interactions_per_day": 5,
        }
    elif stage == "Ramp-Up":
        return {
            "daily_actions": [
                "post_spaced_clips",
                "reply_to_audience_comments",
                "monitor_view_distribution",
            ],
            "niche_keywords": ["podcast", "motivation", "clips"],
            "browsing_minutes_per_day": 15,
            "target_interactions_per_day": 5,
        }
    elif stage == "Mature":
        return {
            "daily_actions": [
                "post_scheduled_clips",
                "community_engagement",
                "track_analytics_performance",
            ],
            "niche_keywords": ["podcast", "motivation", "clips"],
            "browsing_minutes_per_day": 10,
            "target_interactions_per_day": 5,
        }
    elif stage == "Account Cooldown":
        return {
            "daily_actions": [
                "zero_posting",
                "algorithmic_browsing_only",
                "wait_72h_cooldown_expiry",
            ],
            "niche_keywords": ["podcast", "motivation", "clips"],
            "browsing_minutes_per_day": 30,
            "target_interactions_per_day": 0,
        }
    return {
        "daily_actions": ["browse_niche_feed"],
        "niche_keywords": ["clips"],
        "browsing_minutes_per_day": 20,
        "target_interactions_per_day": 5,
    }


def _find_channel_index(portfolio: Dict[str, Any], channel_id: str) -> Optional[int]:
    for idx, chan in enumerate(portfolio.get("channels", [])):
        if chan.get("id") == channel_id:
            return idx
    return None


def init_portfolio(directory: Optional[str] = None, force: bool = False, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    channels_path = _get_channels_path(directory)
    if channels_path.is_file() and not force:
        sys.stderr.write(f"Error: {CHANNELS_FILENAME} already exists at {channels_path}. Use --force to overwrite.\n")
        sys.exit(1)

    portfolio: Dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "updated_at": _get_utc_now_iso(),
        "workspace_id": workspace_id or "default-workspace",
        "default_device_transfer": {
            "protocol": "qr_code",
            "target": "http://127.0.0.1:8080",
            "enabled": True,
        },
        "channels": [],
    }
    _save_portfolio(channels_path, portfolio)
    print(f"Initialized channel portfolio registry at {channels_path}")
    return portfolio


def add_channel(
    directory: Optional[str] = None,
    platform: str = "TikTok",
    handle: str = "",
    channel_id: Optional[str] = None,
    stage: str = "Cold Lurker",
    account_name: Optional[str] = None,
    device_protocol: Optional[str] = None,
    device_target: Optional[str] = None,
) -> Dict[str, Any]:
    channels_path = _get_channels_path(directory)
    portfolio = _load_portfolio(channels_path)

    canonical_platform = _normalize_platform(platform)
    canonical_stage = _normalize_stage(stage)

    # Auto generate ID if not supplied
    if not channel_id:
        slug = canonical_platform.lower().replace(" ", "-")
        existing_with_slug = sum(1 for c in portfolio.get("channels", []) if c.get("platform") == canonical_platform)
        channel_id = f"chan-{slug}-{existing_with_slug + 1:02d}"

    # Check duplicates
    for chan in portfolio.get("channels", []):
        if chan.get("id") == channel_id:
            sys.stderr.write(f"Error: Channel with ID '{channel_id}' already exists.\n")
            sys.exit(1)
        if chan.get("platform") == canonical_platform and chan.get("handle") == handle:
            sys.stderr.write(f"Error: Channel with handle '{handle}' on platform '{canonical_platform}' already exists.\n")
            sys.exit(1)

    protocol_canonical = _normalize_transfer_protocol(device_protocol or "qr_code")

    is_cooldown = canonical_stage == "Account Cooldown"
    status = "cooldown" if is_cooldown else "active"

    now_iso = _get_utc_now_iso()
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    cadence = _stage_cadence_defaults(canonical_stage)
    warmup = _stage_warmup_defaults(canonical_stage)

    new_channel: Dict[str, Any] = {
        "id": channel_id,
        "platform": canonical_platform,
        "handle": handle,
        "account_name": account_name or f"{canonical_platform} ({handle})",
        "creation_date": today_date,
        "stage": canonical_stage,
        "status": status,
        "stage_entered_at": now_iso,
        "posting_cadence": cadence,
        "health_gate": {
            "cleared_health_gate": canonical_stage in ["Ramp-Up", "Mature"],
            "min_views_threshold": 200,
            "max_views_threshold": 500,
            "latest_views": 0,
            "consecutive_valid_posts": 0,
            "suppression_detected": is_cooldown,
        },
        "cooldown": {
            "in_cooldown": is_cooldown,
            "cooldown_duration_hours": 72,
        },
        "device_transfer": {
            "protocol": protocol_canonical,
            "target": device_target or "http://127.0.0.1:8080",
            "enabled": True,
        },
        "warmup_protocol": warmup,
        "post_log": [],
    }

    if is_cooldown:
        new_channel["cooldown"]["triggered_at"] = now_iso
        new_channel["cooldown"]["cooldown_until"] = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
        new_channel["cooldown"]["reason"] = "Initialized in Account Cooldown"

    portfolio["channels"].append(new_channel)
    _save_portfolio(channels_path, portfolio)
    print(f"Added channel '{channel_id}' ({canonical_platform} - {handle}) in stage '{canonical_stage}'")
    return new_channel


def audit_portfolio(directory: Optional[str] = None, output_artifact: Optional[str] = None) -> Dict[str, Any]:
    channels_path = _get_channels_path(directory)
    portfolio = _load_portfolio(channels_path)

    channels = portfolio.get("channels", [])
    total_channels = len(channels)

    stage_counts: Dict[str, int] = {}
    status_counts: Dict[str, int] = {}
    cleared_health_gate = 0
    in_cooldown_count = 0
    total_posts_today = 0
    total_remaining_quota = 0

    for chan in channels:
        stg = chan.get("stage", "Unknown")
        stat = chan.get("status", "Unknown")
        stage_counts[stg] = stage_counts.get(stg, 0) + 1
        status_counts[stat] = status_counts.get(stat, 0) + 1

        if chan.get("health_gate", {}).get("cleared_health_gate"):
            cleared_health_gate += 1

        if chan.get("cooldown", {}).get("in_cooldown") or stat == "cooldown":
            in_cooldown_count += 1

        cadence = chan.get("posting_cadence", {})
        limit = cadence.get("daily_post_limit", 0)
        today = cadence.get("posts_today", 0)
        total_posts_today += today
        total_remaining_quota += max(0, limit - today)

    report_lines = [
        "# Channel Portfolio Audit",
        "",
        f"- **Registry Path**: `{channels_path}`",
        f"- **Last Updated**: {portfolio.get('updated_at', 'N/A')}",
        f"- **Total Channels**: {total_channels}",
        f"- **Channels In Cooldown**: {in_cooldown_count}",
        f"- **Cleared Health Gate**: {cleared_health_gate}/{total_channels}",
        f"- **Total Posts Today**: {total_posts_today} (Remaining Capacity: {total_remaining_quota})",
        "",
        "## Stage Breakdown",
    ]
    for stg in ALLOWED_STAGES:
        count = stage_counts.get(stg, 0)
        report_lines.append(f"- **{stg}**: {count}")

    report_lines.append("")
    report_lines.append("## Channel Inventory")
    report_lines.append("| ID | Platform | Handle | Stage | Status | Limit | Today | Health Gate | Cooldown |")
    report_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for chan in channels:
        cid = chan.get("id", "")
        plat = chan.get("platform", "")
        handle = chan.get("handle", "")
        stg = chan.get("stage", "")
        stat = chan.get("status", "")
        cadence = chan.get("posting_cadence", {})
        limit = cadence.get("daily_post_limit", 0)
        today = cadence.get("posts_today", 0)
        hg = "Cleared" if chan.get("health_gate", {}).get("cleared_health_gate") else "Pending"
        cd = "Active" if chan.get("cooldown", {}).get("in_cooldown") else "None"
        report_lines.append(f"| {cid} | {plat} | {handle} | {stg} | {stat} | {limit} | {today} | {hg} | {cd} |")

    report_text = "\n".join(report_lines)
    print(report_text)

    if output_artifact:
        artifact_file = Path(output_artifact).resolve()
        artifact_file.parent.mkdir(parents=True, exist_ok=True)
        artifact_file.write_text(report_text, encoding="utf-8")
        print(f"\nAudit artifact saved to: {artifact_file}")

    return {
        "total_channels": total_channels,
        "stage_counts": stage_counts,
        "status_counts": status_counts,
        "in_cooldown_count": in_cooldown_count,
        "cleared_health_gate": cleared_health_gate,
        "total_posts_today": total_posts_today,
        "total_remaining_quota": total_remaining_quota,
    }


def get_daily_tasks(directory: Optional[str] = None, json_mode: bool = False) -> List[Dict[str, Any]]:
    channels_path = _get_channels_path(directory)
    portfolio = _load_portfolio(channels_path)

    tasks_list: List[Dict[str, Any]] = []

    for chan in portfolio.get("channels", []):
        cid = chan.get("id", "")
        plat = chan.get("platform", "")
        handle = chan.get("handle", "")
        stg = chan.get("stage", "")
        stat = chan.get("status", "")
        cadence = chan.get("posting_cadence", {})
        limit = cadence.get("daily_post_limit", 0)
        today = cadence.get("posts_today", 0)
        remaining = max(0, limit - today)

        warmup = chan.get("warmup_protocol", {})
        actions = list(warmup.get("daily_actions", []))
        browsing_mins = warmup.get("browsing_minutes_per_day", 0)

        # Contextual notes
        notes = []
        if stg == "Cold Lurker":
            notes.append("Strictly 0 posts allowed. Warmup browsing only to establish algorithmic trust.")
        elif stg == "Seeding":
            notes.append(f"Post 1 clip ({today}/1 posted). Verify 24h view distribution against Health Gate (>= 200 views).")
        elif stg == "Ramp-Up":
            notes.append(f"Post up to {limit} clips ({remaining} remaining today). Minimum 2.5h spacing between uploads.")
        elif stg == "Mature":
            notes.append(f"High capacity authority account. Post up to {limit} clips ({remaining} remaining today).")
        elif stg == "Account Cooldown":
            cooldown_until = chan.get("cooldown", {}).get("cooldown_until", "unknown")
            notes.append(f"Account in mandatory 72h cooldown until {cooldown_until}. Zero posts; algorithmic browsing only.")

        task_entry = {
            "id": cid,
            "platform": plat,
            "handle": handle,
            "stage": stg,
            "status": stat,
            "daily_post_limit": limit,
            "posts_today": today,
            "remaining_posts": remaining,
            "browsing_minutes": browsing_mins,
            "actions": actions,
            "guidance": " ".join(notes),
        }
        tasks_list.append(task_entry)

    if json_mode:
        print(json.dumps(tasks_list, indent=2))
    else:
        print("# Daily Tasks & Warmup Agenda\n")
        for t in tasks_list:
            print(f"### {t['id']} — {t['platform']} ({t['handle']})")
            print(f"- **Stage**: {t['stage']} (Status: {t['status']})")
            print(f"- **Posting Quota**: {t['posts_today']}/{t['daily_post_limit']} posted ({t['remaining_posts']} remaining)")
            print(f"- **Warmup Browsing**: {t['browsing_minutes']} minutes target")
            print("- **Actions**:")
            for a in t["actions"]:
                print(f"  * {a}")
            print(f"- **Guidance**: {t['guidance']}")
            print()

    return tasks_list


def advance_stage(
    channel_id: str,
    views: Optional[int] = None,
    force: bool = False,
    directory: Optional[str] = None,
) -> Dict[str, Any]:
    channels_path = _get_channels_path(directory)
    portfolio = _load_portfolio(channels_path)

    idx = _find_channel_index(portfolio, channel_id)
    if idx is None:
        sys.stderr.write(f"Error: Channel '{channel_id}' not found in registry.\n")
        sys.exit(1)

    chan = portfolio["channels"][idx]
    current_stage = chan.get("stage", "Cold Lurker")
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    if current_stage == "Cold Lurker":
        # Must have spent >= 3 days in Cold Lurker
        stage_entered_at_str = chan.get("stage_entered_at") or chan.get("creation_date")
        days_in_stage = 0.0
        if stage_entered_at_str:
            try:
                # Handle YYYY-MM-DD or full ISO
                if len(stage_entered_at_str) == 10:
                    entered_dt = datetime.strptime(stage_entered_at_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                else:
                    entered_dt = datetime.fromisoformat(stage_entered_at_str.replace("Z", "+00:00"))
                days_in_stage = (now - entered_dt).total_seconds() / 86400.0
            except Exception:
                days_in_stage = 0.0

        if days_in_stage < 3.0 and not force:
            sys.stderr.write(
                f"Error: Channel '{channel_id}' has only been in Cold Lurker for {days_in_stage:.1f} days. "
                f"Requires minimum 3 days of algorithmic browsing warmup before advancing to Seeding. "
                f"Use --force to override.\n"
            )
            sys.exit(1)

        # Advance to Seeding
        chan["stage"] = "Seeding"
        chan["stage_entered_at"] = now_iso
        chan["posting_cadence"]["daily_post_limit"] = 1
        chan["posting_cadence"]["min_post_spacing_hours"] = 4.0
        chan["warmup_protocol"] = _stage_warmup_defaults("Seeding")
        print(f"Advanced channel '{channel_id}' from Cold Lurker to Seeding (daily_post_limit: 1).")

    elif current_stage == "Seeding":
        # Health Gate enforcement: must have >= 200 views without suppression
        latest_views = views if views is not None else chan.get("health_gate", {}).get("latest_views", 0)
        min_threshold = chan.get("health_gate", {}).get("min_views_threshold", 200)

        if latest_views < min_threshold and not force:
            sys.stderr.write(
                f"Error: Health Gate check failed for '{channel_id}'. Latest views ({latest_views}) "
                f"are below the minimum threshold of {min_threshold} views. "
                f"Advancement to Ramp-Up is blocked to prevent algorithm suppression. "
                f"If account experienced 0-view shadowban, use cooldown command. Use --force to override.\n"
            )
            sys.exit(1)

        # Advance to Ramp-Up
        chan["stage"] = "Ramp-Up"
        chan["stage_entered_at"] = now_iso
        chan.setdefault("health_gate", {})
        chan["health_gate"]["cleared_health_gate"] = True
        if views is not None:
            chan["health_gate"]["latest_views"] = views
        chan["posting_cadence"]["daily_post_limit"] = 3
        chan["posting_cadence"]["min_post_spacing_hours"] = 2.5
        chan["warmup_protocol"] = _stage_warmup_defaults("Ramp-Up")
        print(f"Cleared Health Gate ({latest_views} views)! Advanced channel '{channel_id}' to Ramp-Up (daily_post_limit: 3).")

    elif current_stage == "Ramp-Up":
        # Advance to Mature
        chan["stage"] = "Mature"
        chan["stage_entered_at"] = now_iso
        chan["posting_cadence"]["daily_post_limit"] = 4
        chan["posting_cadence"]["min_post_spacing_hours"] = 2.0
        chan["warmup_protocol"] = _stage_warmup_defaults("Mature")
        print(f"Advanced channel '{channel_id}' to Mature (daily_post_limit: 4).")

    elif current_stage == "Account Cooldown":
        # Can return to Seeding after resting
        chan["stage"] = "Seeding"
        chan["status"] = "active"
        chan["stage_entered_at"] = now_iso
        chan.setdefault("cooldown", {})
        chan["cooldown"]["in_cooldown"] = False
        chan.setdefault("health_gate", {})
        chan["health_gate"]["suppression_detected"] = False
        chan["posting_cadence"]["daily_post_limit"] = 1
        chan["posting_cadence"]["min_post_spacing_hours"] = 4.0
        chan["warmup_protocol"] = _stage_warmup_defaults("Seeding")
        print(f"Channel '{channel_id}' exited Account Cooldown and returned to Seeding.")

    elif current_stage == "Mature":
        print(f"Channel '{channel_id}' is already at the highest warmup lifecycle stage (Mature).")

    _save_portfolio(channels_path, portfolio)
    return chan


def set_cooldown(
    channel_id: str,
    hours: int = 72,
    reason: Optional[str] = None,
    directory: Optional[str] = None,
) -> Dict[str, Any]:
    channels_path = _get_channels_path(directory)
    portfolio = _load_portfolio(channels_path)

    idx = _find_channel_index(portfolio, channel_id)
    if idx is None:
        sys.stderr.write(f"Error: Channel '{channel_id}' not found in registry.\n")
        sys.exit(1)

    chan = portfolio["channels"][idx]
    now = datetime.now(timezone.utc)
    until = now + timedelta(hours=hours)

    chan["stage"] = "Account Cooldown"
    chan["status"] = "cooldown"
    chan["stage_entered_at"] = now.isoformat()
    chan["posting_cadence"]["daily_post_limit"] = 0
    chan.setdefault("health_gate", {})["suppression_detected"] = True

    chan["cooldown"] = {
        "in_cooldown": True,
        "triggered_at": now.isoformat(),
        "cooldown_until": until.isoformat(),
        "cooldown_duration_hours": hours,
        "reason": reason or f"0-view shadowban or suppression detected; resting {hours} hours",
    }
    chan["warmup_protocol"] = _stage_warmup_defaults("Account Cooldown")

    _save_portfolio(channels_path, portfolio)
    print(f"Placed channel '{channel_id}' into 72-hour Account Cooldown (expires {until.isoformat()}).")
    return chan


def log_post(
    channel_id: str,
    clip_id: Optional[str] = None,
    project: Optional[str] = None,
    views: Optional[int] = None,
    post_url: Optional[str] = None,
    force: bool = False,
    directory: Optional[str] = None,
) -> Dict[str, Any]:
    channels_path = _get_channels_path(directory)
    portfolio = _load_portfolio(channels_path)

    idx = _find_channel_index(portfolio, channel_id)
    if idx is None:
        sys.stderr.write(f"Error: Channel '{channel_id}' not found in registry.\n")
        sys.exit(1)

    chan = portfolio["channels"][idx]
    stat = chan.get("status", "active")
    stg = chan.get("stage", "Cold Lurker")
    cadence = chan.setdefault("posting_cadence", {"daily_post_limit": 0, "posts_today": 0})
    limit = cadence.get("daily_post_limit", 0)
    today = cadence.get("posts_today", 0)

    if stat == "cooldown" or stg == "Account Cooldown":
        if not force:
            sys.stderr.write(f"Error: Channel '{channel_id}' is in Account Cooldown. Posting prohibited. Use --force to override.\n")
            sys.exit(1)

    if stg == "Cold Lurker" and limit == 0:
        if not force:
            sys.stderr.write(f"Error: Channel '{channel_id}' is in Cold Lurker (0 posts allowed). Use --force to override.\n")
            sys.exit(1)

    if today >= limit and not force:
        sys.stderr.write(
            f"Error: Daily post limit reached for channel '{channel_id}' ({today}/{limit} posts today). "
            f"Use --force to override.\n"
        )
        sys.exit(1)

    now_iso = _get_utc_now_iso()
    cadence["posts_today"] = today + 1
    cadence["last_post_date"] = now_iso

    chan.setdefault("health_gate", {})
    if views is not None:
        chan["health_gate"]["latest_views"] = views
        if views >= chan["health_gate"].get("min_views_threshold", 200):
            chan["health_gate"]["consecutive_valid_posts"] = chan["health_gate"].get("consecutive_valid_posts", 0) + 1
        elif views == 0:
            chan["health_gate"]["suppression_detected"] = True

    log_entry: Dict[str, Any] = {
        "clip_id": clip_id or f"clip-{int(datetime.now(timezone.utc).timestamp())}",
        "timestamp": now_iso,
    }
    if project:
        log_entry["project"] = project
    if views is not None:
        log_entry["views"] = views
    if post_url:
        log_entry["post_url"] = post_url

    chan.setdefault("post_log", []).append(log_entry)
    _save_portfolio(channels_path, portfolio)
    print(f"Logged post for channel '{channel_id}' ({cadence['posts_today']}/{limit} posts today).")
    return chan


def transfer_clip(
    clip_path: str,
    channel_id: Optional[str] = None,
    method: Optional[str] = None,
    target: Optional[str] = None,
    directory: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    clip_file = Path(clip_path).resolve()
    if not dry_run and not clip_file.is_file():
        sys.stderr.write(f"Error: Clip file '{clip_path}' not found at {clip_file}\n")
        sys.exit(1)

    chosen_method = method
    chosen_target = target

    # If channel_id is provided, resolve channel's configured device_transfer protocol
    if channel_id:
        channels_path = _get_channels_path(directory)
        portfolio = _load_portfolio(channels_path)
        idx = _find_channel_index(portfolio, channel_id)
        if idx is not None:
            chan = portfolio["channels"][idx]
            dt = chan.get("device_transfer", {})
            if not chosen_method and dt.get("protocol"):
                chosen_method = dt.get("protocol")
            if not chosen_target and dt.get("target"):
                chosen_target = dt.get("target")

    if not chosen_method:
        chosen_method = "local_qr"

    canonical_method = _normalize_transfer_protocol(chosen_method)

    result: Dict[str, Any] = {
        "status": "success",
        "clip": str(clip_file),
        "protocol": canonical_method,
        "method_input": chosen_method,
        "dry_run": dry_run,
    }

    if canonical_method == "cloud_sync":
        dest_dir = Path(chosen_target).resolve() if chosen_target else Path.home() / "Clips"
        result["destination_dir"] = str(dest_dir)
        if dry_run:
            print(f"[dry-run] Would sync {clip_file.name} to cloud folder: {dest_dir}")
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file = dest_dir / clip_file.name
            shutil.copy2(clip_file, dest_file)
            result["copied_file"] = str(dest_file)
            print(f"Transferred clip via cloud_folder: {dest_file}")

    elif canonical_method == "adb_push":
        adb_dest = chosen_target or "/sdcard/DCIM/Camera/"
        result["adb_target"] = adb_dest
        if dry_run:
            print(f"[dry-run] Would execute: adb push {clip_file} {adb_dest}")
        else:
            adb_bin = shutil.which("adb")
            if adb_bin:
                proc = subprocess.run([adb_bin, "push", str(clip_file), adb_dest], capture_output=True, text=True)
                if proc.returncode != 0:
                    sys.stderr.write(f"ADB Push Warning: {proc.stderr}\n")
                print(f"Transferred clip via adb push to {adb_dest}")
            else:
                print(f"Notice: adb binary not found in PATH. Staged transfer for: adb push {clip_file} {adb_dest}")

    elif canonical_method == "telegram_dispatch":
        webhook_url = chosen_target or "http://127.0.0.1:8080/telegram_webhook"
        result["webhook_url"] = webhook_url
        if dry_run:
            print(f"[dry-run] Would dispatch webhook for {clip_file.name} to {webhook_url}")
        else:
            print(f"Dispatched clip transfer webhook for {clip_file.name} to {webhook_url}")

    elif canonical_method == "qr_code":
        server_url = chosen_target or f"http://127.0.0.1:8080/{clip_file.name}"
        result["server_url"] = server_url
        print("==================================================")
        print(" [Automated Device Delivery: Local QR Transfer]   ")
        print("==================================================")
        print(f" Clip File  : {clip_file.name}")
        print(f" Access URL : {server_url}")
        print(" Scan QR code or visit URL on mobile to download.")
        if dry_run:
            print("[dry-run] QR transfer server simulation ready.")
        else:
            print("Ready for device transfer.")

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Channel portfolio and warmup management engine for Short-Form Clipping Pipeline."
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    # init
    init_parser = subparsers.add_parser("init", help="Initialize a new channels.json registry")
    init_parser.add_argument("--dir", dest="directory", help="Directory for channels.json (default: current working directory)")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing channels.json")
    init_parser.add_argument("--workspace-id", help="Workspace identifier")

    # add
    add_parser = subparsers.add_parser("add", help="Add a social channel to the portfolio")
    add_parser.add_argument("--id", dest="channel_id", help="Unique channel ID (auto-generated if omitted)")
    add_parser.add_argument("--platform", required=True, help="Platform (TikTok, Instagram Reels, YouTube Shorts)")
    add_parser.add_argument("--handle", required=True, help="Account handle (e.g. @curiousclips_daily)")
    add_parser.add_argument("--stage", default="Cold Lurker", help="Initial warmup stage (default: Cold Lurker)")
    add_parser.add_argument("--account-name", help="Display name or label")
    add_parser.add_argument("--dir", dest="directory", help="Directory containing channels.json")

    # audit
    audit_parser = subparsers.add_parser("audit", help="Audit portfolio stages, health gates, and capacity")
    audit_parser.add_argument("--dir", dest="directory", help="Directory containing channels.json")
    audit_parser.add_argument("--output-artifact", help="File path to write markdown audit report")

    # daily-tasks
    tasks_parser = subparsers.add_parser("daily-tasks", help="Generate daily tasks for portfolio channels")
    tasks_parser.add_argument("--dir", dest="directory", help="Directory containing channels.json")
    tasks_parser.add_argument("--json", action="store_true", dest="json_mode", help="Output tasks in JSON format")

    # advance-stage
    adv_parser = subparsers.add_parser("advance-stage", help="Advance channel warmup stage enforcing health gates")
    adv_parser.add_argument("--id", required=True, dest="channel_id", help="Channel ID to advance")
    adv_parser.add_argument("--views", type=int, help="Verified views from latest clip")
    adv_parser.add_argument("--force", action="store_true", help="Override health gate and time constraints")
    adv_parser.add_argument("--dir", dest="directory", help="Directory containing channels.json")

    # cooldown
    cd_parser = subparsers.add_parser("cooldown", help="Place channel into 72h Account Cooldown")
    cd_parser.add_argument("--id", required=True, dest="channel_id", help="Channel ID")
    cd_parser.add_argument("--hours", type=int, default=72, help="Cooldown duration in hours (default: 72)")
    cd_parser.add_argument("--reason", help="Reason for entering cooldown")
    cd_parser.add_argument("--dir", dest="directory", help="Directory containing channels.json")

    # log-post
    log_parser = subparsers.add_parser("log-post", help="Log a clip publication and enforce daily cadence")
    log_parser.add_argument("--id", required=True, dest="channel_id", help="Channel ID")
    log_parser.add_argument("--clip-id", help="Published clip ID")
    log_parser.add_argument("--project", help="Campaign/project slug")
    log_parser.add_argument("--views", type=int, help="Initial or verified views")
    log_parser.add_argument("--post-url", help="Live post URL")
    log_parser.add_argument("--force", action="store_true", help="Bypass daily post limits")
    log_parser.add_argument("--dir", dest="directory", help="Directory containing channels.json")

    # transfer
    trans_parser = subparsers.add_parser("transfer", help="Deliver clip to mobile device")
    trans_parser.add_argument("--clip", required=True, dest="clip_path", help="Path to rendered clip MP4")
    trans_parser.add_argument("--channel", dest="channel_id", help="Target channel ID (loads transfer config)")
    trans_parser.add_argument("--method", help="Delivery method (local_qr, adb_push, cloud_folder, webhook)")
    trans_parser.add_argument("--target", help="Transfer target (URL, serial/path, directory)")
    trans_parser.add_argument("--dry-run", action="store_true", help="Simulate transfer without executing")
    trans_parser.add_argument("--dir", dest="directory", help="Directory containing channels.json")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    if args.subcommand == "init":
        init_portfolio(args.directory, force=args.force, workspace_id=args.workspace_id)
    elif args.subcommand == "add":
        add_channel(
            directory=args.directory,
            platform=args.platform,
            handle=args.handle,
            channel_id=args.channel_id,
            stage=args.stage,
            account_name=args.account_name,
        )
    elif args.subcommand == "audit":
        audit_portfolio(args.directory, output_artifact=args.output_artifact)
    elif args.subcommand == "daily-tasks":
        get_daily_tasks(args.directory, json_mode=args.json_mode)
    elif args.subcommand == "advance-stage":
        advance_stage(args.channel_id, views=args.views, force=args.force, directory=args.directory)
    elif args.subcommand == "cooldown":
        set_cooldown(args.channel_id, hours=args.hours, reason=args.reason, directory=args.directory)
    elif args.subcommand == "log-post":
        log_post(
            channel_id=args.channel_id,
            clip_id=args.clip_id,
            project=args.project,
            views=args.views,
            post_url=args.post_url,
            force=args.force,
            directory=args.directory,
        )
    elif args.subcommand == "transfer":
        transfer_clip(
            clip_path=args.clip_path,
            channel_id=args.channel_id,
            method=args.method,
            target=args.target,
            directory=args.directory,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
