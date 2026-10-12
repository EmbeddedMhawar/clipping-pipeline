#!/usr/bin/env python3
"""
scripts/clipping_publisher.py

Step 8 Publisher Engine for the Antigravity Short-Form Clipping Pipeline.
Governs Brand Cluster matching, zero duplicate same-platform allocation,
warmup gating, mobile device transfer with caption bundling, and YouTube Shorts
publishing.

Zero external runtime dependencies (Python standard library only).
Conforms to:
- docs/adr/0010-dedicated-pipeline-publishing-step.md
- references/CHANNEL_PORTFOLIO_SCHEMA.md
- GLOSSARY.md
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

CHANNELS_FILENAME = "channels.json"
STATE_FILENAME = ".clipping_state.json"

ALLOWED_PLATFORMS = ["YouTube Shorts", "TikTok", "Instagram Reels"]
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


def normalize_platform(plat: str) -> str:
    """Normalizes platform string or alias to canonical platform name."""
    key = str(plat).strip().lower()
    if key in PLATFORM_ALIASES:
        return PLATFORM_ALIASES[key]
    for p in ALLOWED_PLATFORMS:
        if p.lower() == key:
            return p
    return plat.strip()


def resolve_channels_path(
    project_dir: Optional[Union[str, Path]] = None,
    channels_arg: Optional[Union[str, Path]] = None,
) -> Optional[Path]:
    """
    Resolves the absolute path to channels.json:
    1. Explicit channels_arg if provided and exists
    2. project_dir / channels.json
    3. project_dir.parent / channels.json (workspace level)
    4. Current working directory / channels.json
    """
    if channels_arg:
        cp = Path(channels_arg).resolve()
        if cp.is_file():
            return cp

    base = Path(project_dir).resolve() if project_dir else Path.cwd()

    cand = base / CHANNELS_FILENAME
    if cand.is_file():
        return cand

    cand_parent = base.parent / CHANNELS_FILENAME
    if cand_parent.is_file():
        return cand_parent

    cand_cwd = Path.cwd() / CHANNELS_FILENAME
    if cand_cwd.is_file():
        return cand_cwd

    return None


def load_portfolio(channels_path: Union[str, Path]) -> Dict[str, Any]:
    """Loads and parses the channels.json portfolio registry."""
    path = Path(channels_path)
    if not path.is_file():
        raise FileNotFoundError(f"{CHANNELS_FILENAME} not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_brand_clusters(portfolio: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Groups accounts in the portfolio by account_name (Brand Cluster).
    Returns mapping of brand cluster name to list of channel dicts.
    """
    clusters: Dict[str, List[Dict[str, Any]]] = {}
    for chan in portfolio.get("channels", []):
        name = chan.get("account_name")
        if not name:
            name = chan.get("handle") or chan.get("id")
        clusters.setdefault(name, []).append(chan)
    return clusters


def match_brand_cluster(
    portfolio: Dict[str, Any], brand_cluster_name: str
) -> List[Dict[str, Any]]:
    """
    Matches accounts sharing the target account_name across platforms.
    Performs case-insensitive, whitespace-trimmed comparison.
    """
    target = brand_cluster_name.strip().lower()
    matched: List[Dict[str, Any]] = []
    for chan in portfolio.get("channels", []):
        name = (chan.get("account_name") or "").strip().lower()
        if name == target:
            matched.append(chan)
    return matched


def is_channel_warmed_up(channel: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Evaluates whether a channel is eligible for publication based on its
    platform, warmup lifecycle stage, operational status, and posting cadence.

    Enforces:
    - Zero posting during Account Cooldown or when status == "cooldown" / in_cooldown == True
    - Strict blocking of TikTok and Instagram Reels in "Cold Lurker"
    - daily_post_limit > 0 and posts_today < daily_post_limit
    - YouTube Shorts eligibility when active and not in cooldown
    """
    status = (channel.get("status") or "active").strip().lower()
    if status == "cooldown":
        return False, "Channel operational status is 'cooldown'"
    if status in ("banned", "paused"):
        return False, f"Channel operational status is '{status}'"

    cooldown_info = channel.get("cooldown", {})
    if isinstance(cooldown_info, dict) and cooldown_info.get("in_cooldown") is True:
        reason = cooldown_info.get("reason", "unspecified")
        return False, f"Channel cooldown is active (reason: {reason})"

    stage = (channel.get("stage") or "").strip()
    if stage == "Account Cooldown":
        return False, "Lifecycle stage is 'Account Cooldown'"

    platform = normalize_platform(channel.get("platform", ""))
    cadence = channel.get("posting_cadence") or {}
    daily_post_limit = cadence.get("daily_post_limit", 0)
    posts_today = cadence.get("posts_today", 0)

    if platform in ("TikTok", "Instagram Reels"):
        if stage == "Cold Lurker":
            return False, "Cold Lurker stage strictly prohibits posting"
        if daily_post_limit <= 0:
            return False, f"Channel has daily_post_limit of 0 for stage '{stage}'"
        if posts_today >= daily_post_limit:
            return False, f"Daily post limit reached ({posts_today}/{daily_post_limit} posts today)"
    elif platform == "YouTube Shorts":
        if "daily_post_limit" in cadence and daily_post_limit > 0:
            if posts_today >= daily_post_limit:
                return False, f"Daily post limit reached ({posts_today}/{daily_post_limit} posts today)"

    return True, "Channel is eligible and warmed up for publishing"


class DuplicatePlatformError(ValueError):
    """Raised when multiple channels targeting the same platform are allocated."""
    pass


def validate_target_allocation(channels: List[Dict[str, Any]]) -> None:
    """
    Validates that candidate target channels strictly satisfy zero same-platform duplication.
    Enforces at most 1 channel per platform across the target set.

    Raises:
        DuplicatePlatformError: If more than one channel targets the same platform.
    """
    seen: Dict[str, List[Dict[str, Any]]] = {}
    for chan in channels:
        plat = normalize_platform(chan.get("platform", ""))
        seen.setdefault(plat, []).append(chan)

    duplicates = {plat: chans for plat, chans in seen.items() if len(chans) > 1}
    if duplicates:
        details = []
        for plat, chans in duplicates.items():
            chan_ids = [c.get("id") or c.get("handle") or "unknown" for c in chans]
            details.append(f"platform '{plat}': {', '.join(chan_ids)}")
        msg = (
            f"Duplicate channels targeted for {'; '.join(details)}. "
            "Zero same-platform duplication enforced (at most 1 channel per platform per run)."
        )
        raise DuplicatePlatformError(msg)


def select_platform_targets(
    channels: List[Dict[str, Any]],
    platforms: Optional[List[str]] = None,
    enforce_warmup: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """
    Selects and validates channel targets across platforms.
    Filters candidate channels by requested platforms and warmup readiness.
    Enforces zero duplicate same-platform allocation.

    Returns:
        Dict mapping canonical platform name to selected channel dict.
    Raises:
        DuplicatePlatformError: If multiple eligible channels share a platform.
    """
    candidates = list(channels)

    if platforms:
        allowed_plats = {normalize_platform(p) for p in platforms}
        candidates = [
            c for c in candidates if normalize_platform(c.get("platform", "")) in allowed_plats
        ]

    if enforce_warmup:
        candidates = [c for c in candidates if is_channel_warmed_up(c)[0]]

    # Enforce zero same-platform duplication across candidates
    validate_target_allocation(candidates)

    allocated: Dict[str, Dict[str, Any]] = {}
    for c in candidates:
        plat = normalize_platform(c.get("platform", ""))
        allocated[plat] = c

    return allocated


def check_youtube_token(channel: Dict[str, Any]) -> Tuple[bool, str, str]:
    """
    Checks whether a YouTube channel has configured OAuth credentials.
    Checks:
    1. Custom credentials_path or token_path in channel metadata
    2. Default ~/.config/clipping-pipeline/youtube/<channel_id>_token.json
    3. Environment variable YOUTUBE_TOKEN_<channel_id> or YOUTUBE_API_KEY
    """
    chan_id = channel.get("id", "")
    custom_path = channel.get("credentials_path") or channel.get("token_path")
    if custom_path:
        p = Path(custom_path).expanduser().resolve()
        if p.is_file():
            return True, "configured", str(p)

    default_path = (
        Path.home()
        / ".config"
        / "clipping-pipeline"
        / "youtube"
        / f"{chan_id}_token.json"
    )
    if default_path.is_file():
        return True, "configured", str(default_path)

    env_var_name = f"YOUTUBE_TOKEN_{chan_id.upper().replace('-', '_')}"
    if os.environ.get(env_var_name) or os.environ.get("YOUTUBE_API_KEY"):
        return True, "configured", f"env:{env_var_name}"

    return False, "missing", str(default_path)


def cmd_status(args: argparse.Namespace) -> int:
    channels_path = resolve_channels_path(args.project_dir, args.channels)
    if not channels_path or not channels_path.is_file():
        sys.stderr.write(f"Error: {CHANNELS_FILENAME} not found\n")
        return 1

    try:
        portfolio = load_portfolio(channels_path)
    except Exception as e:
        sys.stderr.write(f"Error loading {channels_path}: {e}\n")
        return 1

    clusters = get_brand_clusters(portfolio)
    if args.brand_cluster:
        target = args.brand_cluster.strip().lower()
        clusters = {k: v for k, v in clusters.items() if k.strip().lower() == target}

    if args.json:
        payload: Dict[str, Any] = {
            "version": portfolio.get("version", "1.0.0"),
            "workspace_id": portfolio.get("workspace_id", ""),
            "channels_path": str(channels_path),
            "total_channels": len(portfolio.get("channels", [])),
            "total_clusters": len(clusters),
            "clusters": {},
        }
        for name, chans in clusters.items():
            payload["clusters"][name] = []
            for c in chans:
                warmed, reason = is_channel_warmed_up(c)
                payload["clusters"][name].append({
                    "id": c.get("id"),
                    "platform": normalize_platform(c.get("platform", "")),
                    "handle": c.get("handle"),
                    "stage": c.get("stage"),
                    "status": c.get("status"),
                    "eligible": warmed,
                    "eligibility_reason": reason,
                    "posting_cadence": c.get("posting_cadence", {}),
                })
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0

    sys.stdout.write(f"=== Channel Portfolio Brand Clusters ({len(clusters)}) ===\n")
    sys.stdout.write(f"Registry: {channels_path}\n\n")
    for name, chans in clusters.items():
        sys.stdout.write(f"Brand Cluster: '{name}' ({len(chans)} accounts)\n")
        for c in chans:
            warmed, reason = is_channel_warmed_up(c)
            plat = normalize_platform(c.get("platform", ""))
            cadence = c.get("posting_cadence", {})
            limit = cadence.get("daily_post_limit", 0)
            today = cadence.get("posts_today", 0)
            elig_mark = "[ELIGIBLE]" if warmed else f"[BLOCKED: {reason}]"
            sys.stdout.write(
                f"  - {plat:16} {c.get('handle', ''):20} ({c.get('id', '')}) "
                f"Stage: {c.get('stage', ''):14} Status: {c.get('status', ''):8} "
                f"Posts: {today}/{limit}  {elig_mark}\n"
            )
        sys.stdout.write("\n")

    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    channels_path = resolve_channels_path(args.project_dir, args.channels)
    if not channels_path or not channels_path.is_file():
        sys.stderr.write(f"Error: {CHANNELS_FILENAME} not found\n")
        return 1

    try:
        portfolio = load_portfolio(channels_path)
    except Exception as e:
        sys.stderr.write(f"Error loading {channels_path}: {e}\n")
        return 1

    allocated: Dict[str, Dict[str, Any]] = {}
    brand_cluster = args.brand_cluster

    if args.channel_ids:
        raw_ids = [i.strip() for i in args.channel_ids.split(",") if i.strip()]
        id_map = {c.get("id"): c for c in portfolio.get("channels", [])}
        target_channels = []
        for cid in raw_ids:
            if cid not in id_map:
                sys.stderr.write(f"Error: Channel ID '{cid}' not found in portfolio\n")
                return 1
            target_channels.append(id_map[cid])

        try:
            validate_target_allocation(target_channels)
        except DuplicatePlatformError as e:
            sys.stderr.write(f"Error: {e}\n")
            return 1

        for c in target_channels:
            warmed, reason = is_channel_warmed_up(c)
            if not warmed:
                sys.stderr.write(
                    f"Error: Target channel '{c.get('id')}' is not eligible for publishing: {reason}\n"
                )
                return 1

        for c in target_channels:
            plat = normalize_platform(c.get("platform", ""))
            allocated[plat] = c

        if not brand_cluster:
            brand_cluster = target_channels[0].get("account_name") or "Custom Selection"

    elif args.brand_cluster:
        matched = match_brand_cluster(portfolio, args.brand_cluster)
        if not matched:
            sys.stderr.write(
                f"Error: No channels found matching brand cluster '{args.brand_cluster}'\n"
            )
            return 1

        req_platforms = (
            [p.strip() for p in args.platforms.split(",") if p.strip()]
            if args.platforms
            else None
        )

        try:
            allocated = select_platform_targets(
                matched, platforms=req_platforms, enforce_warmup=True
            )
        except DuplicatePlatformError as e:
            sys.stderr.write(f"Error: {e}\n")
            return 1

        if not allocated:
            sys.stderr.write(
                f"Error: No eligible warmed-up channels found in brand cluster '{args.brand_cluster}'\n"
            )
            return 1

    else:
        sys.stderr.write("Error: Either --brand-cluster or --channel-ids must be specified\n")
        return 1

    if args.json:
        output: Dict[str, Any] = {
            "status": "allocated",
            "brand_cluster": brand_cluster,
            "clip_id": args.clip_id,
            "video_path": args.video_path,
            "dry_run": args.dry_run,
            "allocated_count": len(allocated),
            "targets": allocated,
        }
        sys.stdout.write(json.dumps(output, indent=2) + "\n")
        return 0

    sys.stdout.write(
        f"Allocated {len(allocated)} platform targets for brand cluster '{brand_cluster}':\n"
    )
    for plat, chan in allocated.items():
        sys.stdout.write(
            f"  {plat}: {chan.get('handle')} ({chan.get('id')}) "
            f"[{chan.get('stage')} - {chan.get('status')}]\n"
        )

    return 0


def cmd_verify_tokens(args: argparse.Namespace) -> int:
    channels_path = resolve_channels_path(args.project_dir, args.channels)
    if not channels_path or not channels_path.is_file():
        sys.stderr.write(f"Error: {CHANNELS_FILENAME} not found\n")
        return 1

    try:
        portfolio = load_portfolio(channels_path)
    except Exception as e:
        sys.stderr.write(f"Error loading {channels_path}: {e}\n")
        return 1

    yt_channels = [
        c
        for c in portfolio.get("channels", [])
        if normalize_platform(c.get("platform", "")) == "YouTube Shorts"
    ]

    if args.channel_id:
        yt_channels = [c for c in yt_channels if c.get("id") == args.channel_id]

    results = []
    for c in yt_channels:
        has_token, status_label, path_used = check_youtube_token(c)
        results.append({
            "id": c.get("id"),
            "handle": c.get("handle"),
            "account_name": c.get("account_name"),
            "status": c.get("status"),
            "token_status": status_label,
            "token_configured": has_token,
            "token_path": path_used,
        })

    if args.json:
        payload = {
            "workspace_id": portfolio.get("workspace_id", ""),
            "channels_path": str(channels_path),
            "total_youtube_channels": len(yt_channels),
            "youtube_channels": results,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0

    sys.stdout.write(f"=== YouTube Shorts Token Verification ({len(results)} channels) ===\n")
    for r in results:
        status_tag = "[CONFIGURED]" if r["token_configured"] else "[MISSING]"
        sys.stdout.write(
            f"  - {r['id']} ({r['handle']}) | Account: {r['account_name']} | "
            f"Token: {r['token_status']} {status_tag}\n"
            f"    Path/Ref: {r['token_path']}\n"
        )

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Clipping Publisher: Step 8 Multi-Platform Publishing Engine"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Publisher subcommands")

    # status
    p_status = subparsers.add_parser("status", help="Show brand clusters and channel status")
    p_status.add_argument("--channels", default=None, help="Path to channels.json")
    p_status.add_argument("--project-dir", default=None, help="Project directory")
    p_status.add_argument("--brand-cluster", "--account-name", dest="brand_cluster", default=None, help="Filter by brand cluster")
    p_status.add_argument("--json", action="store_true", help="Output JSON format")

    # publish
    p_pub = subparsers.add_parser("publish", help="Publish clip across eligible brand cluster channels")
    p_pub.add_argument("--brand-cluster", "--account-name", dest="brand_cluster", default=None, help="Target brand cluster")
    p_pub.add_argument("--channels", default=None, help="Path to channels.json")
    p_pub.add_argument("--project-dir", default=None, help="Project directory")
    p_pub.add_argument("--channel-ids", default=None, help="Comma-separated channel IDs to target")
    p_pub.add_argument("--platforms", default=None, help="Comma-separated target platforms")
    p_pub.add_argument("--clip-id", default=None, help="Clip identifier")
    p_pub.add_argument("--video", "--video-path", dest="video_path", default=None, help="Path to rendered MP4 video")
    p_pub.add_argument("--dry-run", action="store_true", help="Validate allocation without executing transfers")
    p_pub.add_argument("--json", action="store_true", help="Output JSON format")

    # verify-tokens
    p_tok = subparsers.add_parser("verify-tokens", help="Verify YouTube tokens and channel credentials")
    p_tok.add_argument("--channels", default=None, help="Path to channels.json")
    p_tok.add_argument("--project-dir", default=None, help="Project directory")
    p_tok.add_argument("--channel-id", default=None, help="Specific channel ID to verify")
    p_tok.add_argument("--json", action="store_true", help="Output JSON format")

    args = parser.parse_args(argv)
    if not args.subcommand:
        parser.print_help()
        return 1

    if args.subcommand == "status":
        return cmd_status(args)
    elif args.subcommand == "publish":
        return cmd_publish(args)
    elif args.subcommand == "verify-tokens":
        return cmd_verify_tokens(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
