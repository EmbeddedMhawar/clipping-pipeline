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
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

class YouTubePublishError(Exception):
    """Base exception for YouTube publishing failures."""
    pass


class YouTubeAuthError(YouTubePublishError):
    """Raised when YouTube OAuth credentials are missing, expired, or invalid."""
    pass


class YouTubeQuotaError(YouTubePublishError):
    """Raised when YouTube Data API quota is exceeded (quotaExceeded / HTTP 403)."""
    pass

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

TRANSFER_PROTOCOLS = ["local_qr", "adb_push", "cloud_folder", "webhook"]
TRANSFER_ALIASES = {
    "local_qr": "local_qr",
    "qr_code": "local_qr",
    "qr": "local_qr",
    "adb_push": "adb_push",
    "adb": "adb_push",
    "cloud_folder": "cloud_folder",
    "cloud_sync": "cloud_folder",
    "cloud": "cloud_folder",
    "webhook": "webhook",
    "telegram": "webhook",
    "telegram_dispatch": "webhook",
}


def normalize_transfer_protocol(proto: str) -> str:
    """Normalizes transfer protocol string or alias to canonical protocol identifier."""
    key = str(proto).strip().lower()
    if key in TRANSFER_ALIASES:
        return TRANSFER_ALIASES[key]
    for p in TRANSFER_PROTOCOLS:
        if p.lower() == key:
            return p
    return key


def normalize_platform(plat: str) -> str:
    """Normalizes platform string or alias to canonical platform name."""
    key = str(plat).strip().lower()
    if key in PLATFORM_ALIASES:
        return PLATFORM_ALIASES[key]
    for p in ALLOWED_PLATFORMS:
        if p.lower() == key:
            return p
    return plat.strip()


def format_caption(
    hook: Optional[str] = None,
    body: Optional[str] = None,
    hashtags: Optional[Union[str, List[str]]] = None,
    closer: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Formats a standard companion caption payload combining:
    - hook (headline title)
    - body / description (context, summary, or details)
    - hashtags (normalized with # prefix)
    - closer (campaign CTA or account closer)
    """
    actual_body = body if body is not None else description
    sections: List[str] = []

    if hook and hook.strip():
        sections.append(hook.strip())

    if actual_body and actual_body.strip():
        sections.append(actual_body.strip())

    if hashtags:
        if isinstance(hashtags, (list, tuple)):
            tags = [f"#{t.strip().lstrip('#')}" for t in hashtags if t.strip()]
            tag_str = " ".join(tags)
        elif isinstance(hashtags, str):
            h_str = hashtags.strip()
            tokens = [t.strip() for t in h_str.replace(",", " ").split() if t.strip()]
            tags = [f"#{t.lstrip('#')}" for t in tokens]
            tag_str = " ".join(tags)
        else:
            tag_str = ""

        if tag_str.strip():
            sections.append(tag_str.strip())

    if closer and closer.strip():
        sections.append(closer.strip())

    return "\n\n".join(sections)


def bundle_caption(
    target: Union[str, Path],
    caption_content: Optional[str] = None,
    hook: Optional[str] = None,
    body: Optional[str] = None,
    hashtags: Optional[Union[str, List[str]]] = None,
    closer: Optional[str] = None,
    filename: str = "caption.txt",
) -> Path:
    """
    Generates and bundles companion caption.txt alongside the rendered MP4 video
    or within the destination staging directory.
    """
    target_path = Path(target)
    if target_path.is_file():
        dest_dir = target_path.parent
    else:
        dest_dir = target_path

    dest_dir.mkdir(parents=True, exist_ok=True)
    out_file = dest_dir / filename

    if caption_content is None:
        caption_content = format_caption(
            hook=hook,
            body=body,
            hashtags=hashtags,
            closer=closer,
        )

    out_file.write_text(caption_content, encoding="utf-8")
    return out_file


def deliver_mobile_channel(
    channel: Dict[str, Any],
    video_path: Union[str, Path],
    caption_path: Optional[Union[str, Path]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Transfers rendered MP4 video and companion caption.txt to mobile device
    via the channel's configured device transfer protocol (cloud_folder, adb_push, local_qr, webhook).
    """
    dt = channel.get("device_transfer", {})
    if dt.get("enabled") is False:
        raise ValueError(
            f"Device transfer is disabled for channel '{channel.get('id', 'unknown')}'"
        )

    raw_proto = dt.get("protocol") or "local_qr"
    protocol = normalize_transfer_protocol(raw_proto)
    target = dt.get("target")

    v_path = Path(video_path).resolve()
    c_path = Path(caption_path).resolve() if caption_path else None

    # Validate video existence if not dry_run
    if not dry_run and not v_path.is_file():
        raise FileNotFoundError(f"Video file not found: {v_path}")

    status_str = "simulated" if dry_run else "success"

    result: Dict[str, Any] = {
        "status": status_str,
        "channel_id": channel.get("id"),
        "platform": normalize_platform(channel.get("platform", "")),
        "protocol": protocol,
        "video_path": str(v_path),
        "caption_path": str(c_path) if c_path else None,
        "dry_run": dry_run,
    }

    if protocol == "cloud_folder":
        dest_dir = Path(target).resolve() if target else Path.home() / "Clips"
        result["destination_dir"] = str(dest_dir)
        dest_video = dest_dir / v_path.name
        dest_caption = dest_dir / (c_path.name if c_path else "caption.txt")
        result["copied_video"] = str(dest_video)
        result["copied_caption"] = str(dest_caption) if c_path else None

        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(v_path, dest_video)
            if c_path and c_path.is_file():
                shutil.copy2(c_path, dest_caption)

    elif protocol == "adb_push":
        adb_dest = target or "/sdcard/DCIM/Camera/"
        result["adb_target"] = adb_dest

        if not dry_run:
            adb_bin = shutil.which("adb")
            if adb_bin:
                proc_vid = subprocess.run(
                    [adb_bin, "push", str(v_path), adb_dest],
                    capture_output=True,
                    text=True,
                )
                if proc_vid.returncode != 0:
                    sys.stderr.write(f"ADB Push Video Warning: {proc_vid.stderr}\n")
                if c_path and c_path.is_file():
                    proc_cap = subprocess.run(
                        [adb_bin, "push", str(c_path), adb_dest],
                        capture_output=True,
                        text=True,
                    )
                    if proc_cap.returncode != 0:
                        sys.stderr.write(f"ADB Push Caption Warning: {proc_cap.stderr}\n")
            else:
                # Stage transfer when adb is not found in PATH
                result["status"] = "staged"

    elif protocol == "local_qr":
        base_url = target or "http://127.0.0.1:8080"
        server_url = f"{base_url.rstrip('/')}/{v_path.name}"
        caption_url = f"{base_url.rstrip('/')}/caption.txt"
        result["server_url"] = server_url
        result["caption_url"] = caption_url

    elif protocol == "webhook":
        webhook_url = target or "http://127.0.0.1:8080/telegram_webhook"
        result["webhook_url"] = webhook_url

    return result


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


def resolve_state_path(
    project_dir: Optional[Union[str, Path]] = None,
    state_arg: Optional[Union[str, Path]] = None,
) -> Optional[Path]:
    """
    Resolves the absolute path to .clipping_state.json:
    1. Explicit state_arg if provided and exists
    2. project_dir / .clipping_state.json
    3. project_dir.parent / .clipping_state.json
    4. Current working directory / .clipping_state.json (if project_dir not specified)
    """
    if state_arg:
        sp = Path(state_arg).resolve()
        if sp.is_file():
            return sp

    if project_dir:
        base = Path(project_dir).resolve()
        cand = base / STATE_FILENAME
        if cand.is_file():
            return cand
        cand_parent = base.parent / STATE_FILENAME
        if cand_parent.is_file():
            return cand_parent
        return None

    cand_cwd = Path.cwd() / STATE_FILENAME
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


def save_portfolio(channels_path: Union[str, Path], portfolio: Dict[str, Any]) -> None:
    """Saves the channels.json portfolio registry updating updated_at timestamp."""
    path = Path(channels_path)
    portfolio["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)
        f.write("\n")


def stage_channel_quota(
    portfolio: Dict[str, Any],
    channel_id: str,
    clip_id: str,
    status: str = "staged_mobile",
    project: Optional[str] = None,
    channels_path: Optional[Union[str, Path]] = None,
    timestamp: Optional[str] = None,
    post_url: Optional[str] = None,
    video_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Immediately increments posting_cadence.posts_today, updates last_post_date,
    and appends a post entry to post_log to preserve warmup quotas.
    Optionally persists updated portfolio to channels.json if channels_path is provided.
    Returns the modified channel dictionary.
    """
    target_chan: Optional[Dict[str, Any]] = None
    for chan in portfolio.get("channels", []):
        if chan.get("id") == channel_id:
            target_chan = chan
            break

    if target_chan is None:
        raise ValueError(f"Channel '{channel_id}' not found in portfolio")

    now_iso = timestamp or datetime.now(timezone.utc).isoformat()

    cadence = target_chan.setdefault("posting_cadence", {})
    cadence["posts_today"] = cadence.get("posts_today", 0) + 1
    cadence["last_post_date"] = now_iso

    log_entry: Dict[str, Any] = {
        "clip_id": clip_id,
        "timestamp": now_iso,
        "status": status,
    }
    if project:
        log_entry["project"] = project
    if post_url:
        log_entry["post_url"] = post_url
    if video_id:
        log_entry["video_id"] = video_id

    target_chan.setdefault("post_log", []).append(log_entry)

    if channels_path:
        save_portfolio(channels_path, portfolio)

    return target_chan


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
        if "daily_post_limit" in cadence:
            if daily_post_limit <= 0:
                return False, "Channel has daily_post_limit of 0"
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

    env_keys = [
        f"YOUTUBE_TOKEN_{chan_id.upper().replace('-', '_')}",
        "YOUTUBE_ACCESS_TOKEN",
        "YOUTUBE_TOKEN",
    ]
    for env_k in env_keys:
        if os.environ.get(env_k):
            return True, "configured", f"env:{env_k}"

    return False, "missing", str(default_path)


def refresh_youtube_token(
    cred_data: Dict[str, Any],
    token_uri: str = "https://oauth2.googleapis.com/token",
) -> str:
    """
    Refreshes an OAuth 2.0 access token using a refresh token and client credentials.
    Makes a POST request to Google OAuth2 token endpoint.
    """
    client_id = cred_data.get("client_id")
    client_secret = cred_data.get("client_secret")
    refresh_token = cred_data.get("refresh_token")

    if not refresh_token:
        raise YouTubeAuthError("Cannot refresh OAuth token: 'refresh_token' is missing")
    if not client_id:
        raise YouTubeAuthError("Cannot refresh OAuth token: 'client_id' is missing")

    endpoint = cred_data.get("token_uri") or cred_data.get("token_url") or token_uri

    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    encoded_data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=encoded_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            access_token = data.get("access_token")
            if not access_token:
                raise YouTubeAuthError("Refresh response missing 'access_token'")
            return str(access_token)
    except urllib.error.HTTPError as e:
        err_msg = ""
        try:
            err_msg = e.read().decode("utf-8", errors="replace")
        finally:
            e.close()
        raise YouTubeAuthError(f"OAuth token refresh failed with HTTP {e.code}: {err_msg}")
    except Exception as e:
        raise YouTubeAuthError(f"OAuth token refresh connection failed: {e}")


def resolve_youtube_token(
    channel: Dict[str, Any],
    refresh_if_needed: bool = True,
) -> Optional[str]:
    """
    Resolves YouTube OAuth access token for a channel:
    1. Direct token in channel dictionary ('token' or 'access_token').
    2. Credentials dict in channel dictionary ('credentials').
    3. Custom credentials_path or token_path from channel metadata.
    4. Default ~/.config/clipping-pipeline/youtube/<channel_id>_token.json.
    5. Environment variable YOUTUBE_TOKEN_<CHAN_ID>, YOUTUBE_ACCESS_TOKEN, or YOUTUBE_TOKEN.

    If credentials contain refresh_token and client_id, and access_token is missing,
    it refreshes the token via Google OAuth2 token endpoint.

    Returns access token string or None if credentials are missing.
    """
    # 1. Direct in channel dictionary
    if channel.get("access_token"):
        return str(channel["access_token"]).strip()
    if channel.get("token"):
        return str(channel["token"]).strip()

    # 2. In credentials sub-dict
    creds = channel.get("credentials")
    if isinstance(creds, dict):
        if creds.get("access_token"):
            return str(creds["access_token"]).strip()
        if creds.get("refresh_token") and creds.get("client_id") and refresh_if_needed:
            return refresh_youtube_token(creds)

    # 3 & 4. File-based credentials
    chan_id = channel.get("id", "")
    custom_path = channel.get("credentials_path") or channel.get("token_path")
    candidate_paths: List[Path] = []
    if custom_path:
        candidate_paths.append(Path(custom_path).expanduser().resolve())

    default_path = (
        Path.home()
        / ".config"
        / "clipping-pipeline"
        / "youtube"
        / f"{chan_id}_token.json"
    )
    candidate_paths.append(default_path)

    for p in candidate_paths:
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8").strip()
                if content.startswith("{"):
                    data = json.loads(content)
                    if data.get("access_token"):
                        return str(data["access_token"]).strip()
                    if data.get("refresh_token") and data.get("client_id") and refresh_if_needed:
                        return refresh_youtube_token(data)
                elif content:
                    return content
            except YouTubeAuthError:
                raise
            except Exception as e:
                sys.stderr.write(f"Warning reading credentials at {p}: {e}\n")

    # 5. Environment variables
    env_keys = [
        f"YOUTUBE_TOKEN_{chan_id.upper().replace('-', '_')}",
        "YOUTUBE_ACCESS_TOKEN",
        "YOUTUBE_TOKEN",
    ]
    for env_k in env_keys:
        val = os.environ.get(env_k)
        if val:
            val = val.strip()
            if val.startswith("{"):
                try:
                    data = json.loads(val)
                    if data.get("access_token"):
                        return str(data["access_token"]).strip()
                    if data.get("refresh_token") and data.get("client_id") and refresh_if_needed:
                        return refresh_youtube_token(data)
                except YouTubeAuthError:
                    raise
                except Exception:
                    pass
            elif val:
                return val

    return None


VALID_PRIVACY_STATUSES = ("public", "unlisted", "private")


def trigger_browseros_neo_youtube(
    channel: Dict[str, Any],
    video_path: Union[str, Path],
    title: str,
    description: str = "",
    reason: str = "missing_credentials",
    privacy_status: str = "public",
    clip_id: Optional[str] = None,
    project: Optional[str] = None,
    channels_path: Optional[Union[str, Path]] = None,
    portfolio: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Fallback orchestrator that formats BrowserOS Neo studio automation plan/payload
    targeting YouTube Studio (https://studio.youtube.com), stages upload payload,
    and returns fallback execution descriptor.
    """
    v_path = Path(video_path).resolve()
    actual_clip_id = clip_id or v_path.stem
    priv_norm = str(privacy_status).strip().lower()
    chan_id = channel.get("id", "yt-chan")

    staging_dir = v_path.parent / "browseros_staging" if v_path.parent.exists() else Path.cwd() / "browseros_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    payload_file = staging_dir / f"browseros_upload_{chan_id}.json"

    now_iso = datetime.now(timezone.utc).isoformat()
    session_label = f"youtube-upload-{chan_id}"

    automation_plan = [
        "1. Open tab in BrowserOS Neo at https://studio.youtube.com",
        "2. Click 'CREATE' -> 'Upload videos'",
        f"3. Select video file: {v_path}",
        f"4. Set title: {title}",
        f"5. Set description: {description}",
        f"6. Select visibility: {priv_norm}",
        "7. Complete checks and publish Shorts video",
    ]

    staged_payload = {
        "channel_id": chan_id,
        "handle": channel.get("handle"),
        "platform": "YouTube Shorts",
        "video_path": str(v_path),
        "title": title,
        "description": description,
        "privacy_status": priv_norm,
        "fallback_reason": reason,
        "target_url": "https://studio.youtube.com",
        "staged_at": now_iso,
        "automation_plan": automation_plan,
        "browseros_session": {
            "name": session_label,
            "category": "publishing",
            "url": "https://studio.youtube.com",
        },
    }
    payload_file.write_text(json.dumps(staged_payload, indent=2), encoding="utf-8")

    if channels_path:
        target_portfolio = portfolio or load_portfolio(channels_path)
        stage_channel_quota(
            portfolio=target_portfolio,
            channel_id=chan_id,
            clip_id=actual_clip_id,
            status="staged_browseros_neo",
            project=project,
            channels_path=channels_path,
            post_url="https://studio.youtube.com",
            video_id=None,
        )

    return {
        "status": "fallback_browseros_neo",
        "platform": "YouTube Shorts",
        "channel_id": chan_id,
        "handle": channel.get("handle"),
        "method": "browseros_neo",
        "target_url": "https://studio.youtube.com",
        "post_url": "https://studio.youtube.com",
        "video_id": None,
        "video_path": str(v_path),
        "title": title,
        "description": description,
        "privacy_status": priv_norm,
        "reason": reason,
        "automation_plan": automation_plan,
        "staged_payload": str(payload_file),
        "session_label": session_label,
    }


def upload_youtube_shorts(
    channel: Dict[str, Any],
    video_path: Union[str, Path],
    title: str,
    description: str = "",
    privacy_status: str = "public",
    clip_id: Optional[str] = None,
    project: Optional[str] = None,
    channels_path: Optional[Union[str, Path]] = None,
    portfolio: Optional[Dict[str, Any]] = None,
    fallback_on_error: bool = True,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Performs YouTube Data API v3 upload using OAuth access token resolved from credentials.
    Defaults to public visibility, accepting unlisted or private overrides.
    Automatically triggers BrowserOS Neo fallback upon missing credentials,
    auth errors, or quotaExceeded (HTTP 403).
    """
    priv_norm = str(privacy_status).strip().lower()
    if priv_norm not in VALID_PRIVACY_STATUSES:
        raise ValueError(
            f"Invalid privacy status '{privacy_status}'. Must be one of: {', '.join(VALID_PRIVACY_STATUSES)}"
        )

    v_path = Path(video_path).resolve()
    if not v_path.is_file():
        raise FileNotFoundError(f"Video file not found at {v_path}")

    resolved_token = token
    if not resolved_token:
        try:
            resolved_token = resolve_youtube_token(channel)
        except Exception as e:
            if fallback_on_error:
                return trigger_browseros_neo_youtube(
                    channel=channel,
                    video_path=v_path,
                    title=title,
                    description=description,
                    reason=f"Token resolution error: {e}",
                    privacy_status=priv_norm,
                    clip_id=clip_id,
                    project=project,
                    channels_path=channels_path,
                    portfolio=portfolio,
                )
            raise

    if not resolved_token:
        if fallback_on_error:
            return trigger_browseros_neo_youtube(
                channel=channel,
                video_path=v_path,
                title=title,
                description=description,
                reason="missing_credentials",
                privacy_status=priv_norm,
                clip_id=clip_id,
                project=project,
                channels_path=channels_path,
                portfolio=portfolio,
            )
        raise YouTubeAuthError(f"Missing YouTube OAuth credentials for channel '{channel.get('id')}'")

    url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=multipart&part=snippet,status"
    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": priv_norm,
            "selfDeclaredMadeForKids": False,
        },
    }

    boundary = f"===============clipping_{int(datetime.now(timezone.utc).timestamp())}==============="
    delimiter = f"\r\n--{boundary}\r\n".encode("utf-8")
    close_delim = f"\r\n--{boundary}--\r\n".encode("utf-8")

    meta_part = (
        b"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        + json.dumps(metadata, ensure_ascii=False).encode("utf-8")
    )

    video_data = v_path.read_bytes()
    video_part = (
        b"Content-Type: video/mp4\r\n\r\n"
        + video_data
    )

    body = b"".join([
        b"--" + boundary.encode("utf-8") + b"\r\n",
        meta_part,
        delimiter,
        video_part,
        close_delim,
    ])

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {resolved_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            parsed_err = json.loads(err_body)
            err_obj = parsed_err.get("error", {})
            err_msg = err_obj.get("message", "")
            reasons = [item.get("reason", "") for item in err_obj.get("errors", [])]
        except Exception:
            err_msg = str(e)
            reasons = []
        finally:
            e.close()

        is_quota = (
            e.code == 403
            and ("quotaExceeded" in reasons or "quota" in err_msg.lower() or "quotaexceeded" in err_body.lower())
        )
        is_auth = (
            e.code == 401
            or "invalidCredentials" in reasons
            or "authError" in reasons
        )

        if is_quota:
            reason_msg = f"quotaExceeded: YouTube Data API daily quota exhausted ({err_msg or 'HTTP 403'})"
            if fallback_on_error:
                return trigger_browseros_neo_youtube(
                    channel=channel,
                    video_path=v_path,
                    title=title,
                    description=description,
                    reason=reason_msg,
                    privacy_status=priv_norm,
                    clip_id=clip_id,
                    project=project,
                    channels_path=channels_path,
                    portfolio=portfolio,
                )
            raise YouTubeQuotaError(reason_msg)

        if is_auth:
            reason_msg = f"authError: YouTube OAuth token invalid or expired ({err_msg or 'HTTP 401'})"
            if fallback_on_error:
                return trigger_browseros_neo_youtube(
                    channel=channel,
                    video_path=v_path,
                    title=title,
                    description=description,
                    reason=reason_msg,
                    privacy_status=priv_norm,
                    clip_id=clip_id,
                    project=project,
                    channels_path=channels_path,
                    portfolio=portfolio,
                )
            raise YouTubeAuthError(reason_msg)

        if fallback_on_error:
            reason_msg = f"HTTP {e.code}: {err_msg}"
            return trigger_browseros_neo_youtube(
                channel=channel,
                video_path=v_path,
                title=title,
                description=description,
                reason=reason_msg,
                privacy_status=priv_norm,
                clip_id=clip_id,
                project=project,
                channels_path=channels_path,
                portfolio=portfolio,
            )
        raise YouTubePublishError(f"YouTube upload failed with HTTP {e.code}: {err_msg}")

    except Exception as e:
        if fallback_on_error:
            return trigger_browseros_neo_youtube(
                channel=channel,
                video_path=v_path,
                title=title,
                description=description,
                reason=f"Upload error: {e}",
                privacy_status=priv_norm,
                clip_id=clip_id,
                project=project,
                channels_path=channels_path,
                portfolio=portfolio,
            )
        raise

    video_id = resp_data.get("id") or "unknown_id"
    post_url = f"https://youtube.com/shorts/{video_id}"

    if channels_path:
        target_portfolio = portfolio or load_portfolio(channels_path)
        actual_clip_id = clip_id or v_path.stem
        stage_channel_quota(
            portfolio=target_portfolio,
            channel_id=channel["id"],
            clip_id=actual_clip_id,
            status="published",
            project=project,
            channels_path=channels_path,
            post_url=post_url,
            video_id=video_id,
        )

    return {
        "status": "published",
        "platform": "YouTube Shorts",
        "channel_id": channel.get("id"),
        "handle": channel.get("handle"),
        "method": "direct_api",
        "video_id": video_id,
        "post_url": post_url,
        "privacy_status": priv_norm,
        "title": title,
        "clip_id": clip_id or v_path.stem,
        "response": resp_data,
    }


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


def publish_clip(
    channels_path: Union[str, Path],
    video_path: Optional[Union[str, Path]] = None,
    brand_cluster: Optional[str] = None,
    channel_ids: Optional[Union[str, List[str]]] = None,
    platforms: Optional[Union[str, List[str]]] = None,
    clip_id: Optional[str] = None,
    caption_hook: Optional[str] = None,
    caption_body: Optional[str] = None,
    hashtags: Optional[Union[str, List[str]]] = None,
    caption_closer: Optional[str] = None,
    caption_file: Optional[Union[str, Path]] = None,
    privacy_status: str = "public",
    dry_run: bool = False,
    project: Optional[str] = None,
    project_dir: Optional[Union[str, Path]] = None,
    state_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Executes or simulates multi-platform publishing for a clip across brand cluster channels.
    Delivers rendered video and bundled caption.txt to mobile channels (TikTok, Instagram Reels),
    executes YouTube Shorts upload (with BrowserOS Neo fallback), stages daily posting quotas
    in channels.json, and persists publication_manifest into .clipping_state.json.
    """
    p_path = Path(channels_path).resolve()
    portfolio = load_portfolio(p_path)

    allocated: Dict[str, Dict[str, Any]] = {}
    cluster_name = brand_cluster

    if channel_ids:
        if isinstance(channel_ids, str):
            raw_ids = [i.strip() for i in channel_ids.split(",") if i.strip()]
        else:
            raw_ids = list(channel_ids)

        id_map = {c.get("id"): c for c in portfolio.get("channels", [])}
        target_channels = []
        for cid in raw_ids:
            if cid not in id_map:
                raise ValueError(f"Channel ID '{cid}' not found in portfolio")
            target_channels.append(id_map[cid])

        validate_target_allocation(target_channels)

        for c in target_channels:
            warmed, reason = is_channel_warmed_up(c)
            if not warmed:
                raise ValueError(
                    f"Target channel '{c.get('id')}' is not eligible for publishing: {reason}"
                )

        for c in target_channels:
            plat = normalize_platform(c.get("platform", ""))
            allocated[plat] = c

        if not cluster_name:
            cluster_name = target_channels[0].get("account_name") or "Custom Selection"

    elif brand_cluster:
        matched = match_brand_cluster(portfolio, brand_cluster)
        if not matched:
            raise ValueError(f"No channels found matching brand cluster '{brand_cluster}'")

        if platforms:
            req_platforms = (
                [p.strip() for p in platforms.split(",") if p.strip()]
                if isinstance(platforms, str)
                else list(platforms)
            )
        else:
            req_platforms = None

        allocated = select_platform_targets(
            matched, platforms=req_platforms, enforce_warmup=True
        )

        if not allocated:
            raise ValueError(
                f"No eligible warmed-up channels found in brand cluster '{brand_cluster}'"
            )
    else:
        raise ValueError("Either --brand-cluster or --channel-ids must be specified")

    v_path: Optional[Path] = None
    if video_path:
        v_path = Path(video_path).resolve()
        if not dry_run and not v_path.is_file():
            raise FileNotFoundError(f"Video file not found at {v_path}")
    elif not dry_run:
        channels_needing_video = [
            c
            for c in allocated.values()
            if normalize_platform(c.get("platform", "")) in ("TikTok", "Instagram Reels", "YouTube Shorts")
        ]
        if channels_needing_video:
            raise ValueError("Video file required for publishing")

    caption_content = ""
    c_path: Optional[Path] = None

    if caption_file:
        c_src = Path(caption_file).resolve()
        if not c_src.is_file():
            raise FileNotFoundError(f"Caption file not found at {c_src}")
        caption_content = c_src.read_text(encoding="utf-8")
    else:
        caption_content = format_caption(
            hook=caption_hook,
            body=caption_body,
            hashtags=hashtags,
            closer=caption_closer,
        )

    if v_path:
        if caption_content:
            c_path = bundle_caption(v_path, caption_content=caption_content)
        else:
            candidate_cap = v_path.parent / "caption.txt"
            if candidate_cap.is_file():
                c_path = candidate_cap

    now_iso = datetime.now(timezone.utc).isoformat()
    actual_clip_id = (
        clip_id
        or (v_path.stem if v_path else f"clip-{int(datetime.now(timezone.utc).timestamp())}")
    )

    publication_manifest: List[Dict[str, Any]] = []

    for plat, chan in allocated.items():
        if plat in ("TikTok", "Instagram Reels"):
            dummy_video = v_path or (p_path.parent / "simulated.mp4")
            transfer_res = deliver_mobile_channel(
                channel=chan,
                video_path=dummy_video,
                caption_path=c_path,
                dry_run=dry_run,
            )

            if not dry_run:
                stage_channel_quota(
                    portfolio=portfolio,
                    channel_id=chan["id"],
                    clip_id=actual_clip_id,
                    status="staged_mobile",
                    project=project,
                    channels_path=p_path,
                )

            entry = {
                "clip_id": actual_clip_id,
                "brand_cluster": cluster_name,
                "timestamp": now_iso,
                "status": "staged_mobile" if not dry_run else "simulated",
                "platform": plat,
                "channel_id": chan.get("id"),
                "handle": chan.get("handle"),
                "delivery_method": transfer_res.get("protocol"),
                "protocol": transfer_res.get("protocol"),
                "post_url": transfer_res.get("server_url") or transfer_res.get("webhook_url"),
                "transfer": transfer_res,
                "caption_bundled": bool(c_path and c_path.is_file()) if not dry_run else bool(caption_content),
            }
            publication_manifest.append(entry)

        elif plat == "YouTube Shorts":
            if dry_run:
                has_token, tok_status, _ = check_youtube_token(chan)
                entry = {
                    "clip_id": actual_clip_id,
                    "brand_cluster": cluster_name,
                    "timestamp": now_iso,
                    "status": "simulated",
                    "platform": plat,
                    "channel_id": chan.get("id"),
                    "handle": chan.get("handle"),
                    "delivery_method": "direct_api" if has_token else "browseros_neo",
                    "method": "direct_api" if has_token else "browseros_neo",
                    "token_status": tok_status,
                    "privacy_status": privacy_status,
                    "post_url": "https://youtube.com/shorts/simulated" if has_token else "https://studio.youtube.com",
                }
                publication_manifest.append(entry)
            else:
                yt_res = upload_youtube_shorts(
                    channel=chan,
                    video_path=v_path,
                    title=caption_hook or actual_clip_id,
                    description=caption_content,
                    privacy_status=privacy_status,
                    clip_id=actual_clip_id,
                    project=project,
                    channels_path=p_path,
                    portfolio=portfolio,
                    fallback_on_error=True,
                )
                yt_res.setdefault("clip_id", actual_clip_id)
                yt_res.setdefault("brand_cluster", cluster_name)
                yt_res.setdefault("timestamp", now_iso)
                yt_res.setdefault("delivery_method", yt_res.get("method", "direct_api"))
                publication_manifest.append(yt_res)

    if dry_run:
        overall_status = "allocated"
    elif any(entry.get("platform") in ("TikTok", "Instagram Reels") for entry in publication_manifest):
        overall_status = "staged_mobile"
    elif any(entry.get("status") in ("fallback_browseros_neo", "staged_browseros_neo") for entry in publication_manifest):
        overall_status = "staged_browseros_neo"
    else:
        overall_status = "published"

    saved_state_path: Optional[str] = None
    if not dry_run:
        s_path = resolve_state_path(project_dir=project_dir, state_arg=state_path)
        if s_path is None:
            cand_p = p_path.parent / STATE_FILENAME
            if cand_p.is_file():
                s_path = cand_p
            elif (Path.cwd() / STATE_FILENAME).is_file():
                s_path = Path.cwd() / STATE_FILENAME
            elif v_path and (v_path.parent / STATE_FILENAME).is_file():
                s_path = v_path.parent / STATE_FILENAME

        if s_path and s_path.is_file():
            try:
                with open(s_path, "r", encoding="utf-8") as f:
                    state_data = json.load(f)

                if "steps" not in state_data:
                    state_data["steps"] = {}
                if "clipping-publisher" not in state_data["steps"]:
                    state_data["steps"]["clipping-publisher"] = {
                        "status": "pending",
                        "approved": False,
                        "completed_at": None,
                        "params": {},
                    }

                step8 = state_data["steps"]["clipping-publisher"]
                if "params" not in step8:
                    step8["params"] = {}

                step8["params"]["publication_manifest"] = publication_manifest
                step8["params"]["clip_id"] = actual_clip_id
                step8["params"]["brand_cluster"] = cluster_name
                step8["params"]["timestamp"] = now_iso
                step8["params"]["status"] = overall_status
                state_data["updated_at"] = now_iso

                with open(s_path, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                saved_state_path = str(s_path)
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to update state at {s_path}: {e}\n")

    return {
        "status": overall_status,
        "brand_cluster": cluster_name,
        "clip_id": actual_clip_id,
        "video_path": str(v_path) if v_path else None,
        "caption_file": str(c_path) if c_path else None,
        "dry_run": dry_run,
        "allocated_count": len(allocated),
        "targets": allocated,
        "publication_manifest": publication_manifest,
        "state_path": saved_state_path,
    }


def cmd_publish(args: argparse.Namespace) -> int:
    channels_path = resolve_channels_path(args.project_dir, args.channels)
    if not channels_path or not channels_path.is_file():
        sys.stderr.write(f"Error: {CHANNELS_FILENAME} not found\n")
        return 1

    if not args.brand_cluster and not args.channel_ids:
        sys.stderr.write("Error: Either --brand-cluster or --channel-ids must be specified\n")
        return 1

    try:
        res = publish_clip(
            channels_path=channels_path,
            video_path=args.video_path,
            brand_cluster=args.brand_cluster,
            channel_ids=args.channel_ids,
            platforms=args.platforms,
            clip_id=args.clip_id,
            caption_hook=args.caption_hook,
            caption_body=args.caption_body,
            hashtags=args.hashtags,
            caption_closer=args.caption_closer,
            caption_file=args.caption_file,
            privacy_status=getattr(args, "privacy_status", "public"),
            dry_run=args.dry_run,
            project=getattr(args, "project", None),
            project_dir=getattr(args, "project_dir", None),
            state_path=getattr(args, "state", None),
        )
    except (ValueError, FileNotFoundError, DuplicatePlatformError) as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1

    if args.json:
        sys.stdout.write(json.dumps(res, indent=2) + "\n")
        return 0

    if args.dry_run:
        sys.stdout.write(
            f"Allocated {res['allocated_count']} platform targets for brand cluster '{res['brand_cluster']}':\n"
        )
        for plat, chan in res.get("targets", {}).items():
            sys.stdout.write(
                f"  {plat}: {chan.get('handle')} ({chan.get('id')}) "
                f"[{chan.get('stage')} - {chan.get('status')}]\n"
            )
        return 0

    sys.stdout.write(
        f"Published clip '{res['clip_id']}' to brand cluster '{res['brand_cluster']}' "
        f"({res['allocated_count']} targets):\n"
    )
    for entry in res.get("publication_manifest", []):
        plat = entry.get("platform")
        cid = entry.get("channel_id")
        h = entry.get("handle")
        st = entry.get("status")
        proto = entry.get("protocol") or "n/a"
        cap_note = " (caption bundled)" if entry.get("caption_bundled") else ""
        sys.stdout.write(f"  [{st}] {plat:16} {h:20} ({cid}) via {proto}{cap_note}\n")

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
    p_pub.add_argument("--caption-hook", default=None, help="Hook headline title for companion caption")
    p_pub.add_argument("--caption-body", "--caption-desc", dest="caption_body", default=None, help="Description body text for companion caption")
    p_pub.add_argument("--hashtags", default=None, help="Comma-separated or space-separated hashtags")
    p_pub.add_argument("--caption-closer", default=None, help="Approved campaign closer CTA for companion caption")
    p_pub.add_argument("--caption-file", default=None, help="Path to existing caption text file")
    p_pub.add_argument("--privacy-status", choices=["public", "unlisted", "private"], default="public", help="YouTube Shorts privacy visibility status (default: public)")
    p_pub.add_argument("--project", default=None, help="Campaign or project slug")
    p_pub.add_argument("--state", "--state-file", dest="state", default=None, help="Path to .clipping_state.json")
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
