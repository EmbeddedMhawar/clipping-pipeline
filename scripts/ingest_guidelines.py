#!/usr/bin/env python3
"""
scripts/ingest_guidelines.py

Ingestion normalizer for short-form clipping campaign guidelines.
Parses raw markdown, text, or JSON briefs, injects Cole Corcoran Tier-1 defaults
[Default Applied], outputs normalized campaign_brief.json, updates .clipping_state.json,
and generates the interactive review artifact.

Zero external runtime dependencies (Python standard library only).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

COLE_CORCORAN_DEFAULTS = {
    "duration": {
        "min_seconds": 20.0,
        "max_seconds": 60.0,
        "ideal_min": 25.0,
        "ideal_max": 45.0,
    },
    "tier1_geo_min_pct": 40.0,
    "engagement_min_pct": 1.0,
    "watermark": {
        "required": True,
        "asset_path": "assets/watermark_yt_mpj.png",
        "persistent_entire_clip": True,
        "banned_corners": True,
    },
    "audio": {
        "zero_background_music": True,
        "zero_phonk": True,
        "loudness_target_lufs": -14.0,
    },
    "prohibited_edits": [
        "aura",
        "glow",
        "skull",
        "ai_avatar",
        "ai_broll",
        "opus_clips",
    ],
    "single_post_per_edit": True,
    "caption_closers": [
        "watch the full episode @mpj on youtube",
        "full episode is on @mpj on youtube",
        "the whole thing is up on @mpj on youtube",
        "go watch the full one @mpj on youtube",
        "full ep is on @mpj on youtube",
        "this is from the full episode @mpj on youtube",
        "catch the rest @mpj on youtube",
        "the full sit down is on @mpj on youtube",
        "watch it all @mpj on youtube",
        "full interview is on @mpj on youtube",
        "rest of it is on @mpj on youtube",
        "whole episode @mpj on youtube",
    ],
    "platform_overrides": {
        "youtube_shorts": {
            "api_upload_allowed": True,
            "handle_format": "tagged",
            "bio_verification_code_required": True,
        },
        "tiktok": {
            "api_upload_allowed": False,
            "handle_format": "plain_text",
            "bio_affiliate_disclaimer": "fan page of @curiousmike\nnot affiliated",
        },
        "instagram_reels": {
            "api_upload_allowed": False,
            "handle_format": "plain_text",
            "bio_affiliate_disclaimer": "fan page of @curiousmike\nnot affiliated",
        },
    },
}


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def parse_raw_guidelines_text(text: str) -> Tuple[Dict[str, Any], List[str]]:
    """
    Parses unstructured or markdown guidelines into a normalized dictionary,
    injecting Cole Corcoran Tier-1 defaults marked with [Default Applied].
    """
    defaults_applied: List[str] = []

    # Title extraction
    title_match = re.search(r"^#\s+(.+?)(?:\s+Guidelines)?$", text, re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
    else:
        title_line = [line.strip() for line in text.splitlines() if line.strip()]
        title = title_line[0] if title_line else "Untitled Campaign"
        if len(title) > 60:
            title = title[:60].strip()

    # Project slug
    slug_source = title
    if "clipping campaign" in slug_source.lower():
        slug_source = re.sub(r"(?i)\s*clipping\s+campaign.*", "", slug_source)
    project_slug = slugify(slug_source) or "default-project"

    # Client extraction
    client = "Unknown Client"
    client_match = re.search(
        r"(?:\*\*|\b)(?:Channel|Creator|Host|Client)\**:\s*(?:`?@?([a-zA-Z0-9_.]+)`?)?\s*(?:\(([^)]+)\))?",
        text,
        re.IGNORECASE,
    )
    if client_match and (client_match.group(1) or client_match.group(2)):
        handle = client_match.group(1)
        name = client_match.group(2)
        if name:
            client = name.strip()
        elif handle:
            client = f"@{handle.strip()}"
    elif "curious mike" in text.lower():
        client = "Curious Mike"
    elif "mpj" in text.lower():
        client = "Curious Mike"

    # Source video
    yt_url_match = re.search(r"https?://(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+)", text)
    source_url = yt_url_match.group(0) if yt_url_match else ""

    channel_match = re.search(r"(?:\*\*|\b)Channel\**:\s*`?(@[a-zA-Z0-9_.]+)`?", text, re.IGNORECASE)
    channel = channel_match.group(1) if channel_match else ("@mpj" if "mpj" in text.lower() else "")

    duration_match = re.search(r"\((\d{1,2}:\d{2}(?::\d{2})?)\)", text)
    source_duration = duration_match.group(1) if duration_match else ""

    # Economics
    rate_match = re.search(r"\$(\d+(?:\.\d+)?)\s+per\s+1,?000\s+views", text, re.IGNORECASE)
    rate_per_1k = float(rate_match.group(1)) if rate_match else 1.0

    min_payout_match = re.search(r"\$(\d+(?:\.\d+)?)\s*\(([\d,]+)\s+views\s+minimum\)", text, re.IGNORECASE)
    if min_payout_match:
        min_payout_views = int(min_payout_match.group(2).replace(",", ""))
    else:
        min_views_search = re.search(r"([\d,]+)\s+views\s+(?:minimum|floor)", text, re.IGNORECASE)
        min_payout_views = int(min_views_search.group(1).replace(",", "")) if min_views_search else 2000

    max_dollar_match = re.search(r"(?:Maximum|Max|Cap).*?\$(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    max_dollar_per_clip = float(max_dollar_match.group(1)) if max_dollar_match else 300.0

    max_views_match = re.search(r"capped\s+at\s+([\d,]+)\s+views", text, re.IGNORECASE)
    if max_views_match:
        max_payout_views = int(max_views_match.group(1).replace(",", ""))
    else:
        max_payout_views = int((max_dollar_per_clip / rate_per_1k) * 1000) if rate_per_1k > 0 else 300000

    # Platforms
    platforms: List[str] = []
    if re.search(r"\btiktok\b", text, re.IGNORECASE):
        platforms.append("TikTok")
    if re.search(r"\b(?:instagram|reels)\b", text, re.IGNORECASE):
        platforms.append("Instagram Reels")
    if re.search(r"\b(?:youtube|shorts)\b", text, re.IGNORECASE):
        platforms.append("YouTube Shorts")
    if not platforms:
        platforms = ["TikTok", "Instagram Reels", "YouTube Shorts"]
        defaults_applied.append("platforms: [TikTok, Instagram Reels, YouTube Shorts] [Default Applied]")

    # Daily post limit
    post_limit_match = re.search(r"(\d+)\s+to\s+(\d+)\s+clips/day", text, re.IGNORECASE)
    daily_post_limit = int(post_limit_match.group(2)) if post_limit_match else 4

    # Global rules - Duration
    duration_rule: Dict[str, float] = {}
    dur_range_match = re.search(r"(\d+)\s+to\s+(\d+)\s+seconds(?:\s*\(ideal:\s*(\d+)\s+to\s+(\d+)\s+seconds\))?", text, re.IGNORECASE)
    if dur_range_match:
        duration_rule["min_seconds"] = float(dur_range_match.group(1))
        duration_rule["max_seconds"] = float(dur_range_match.group(2))
        duration_rule["ideal_min"] = float(dur_range_match.group(3)) if dur_range_match.group(3) else 25.0
        duration_rule["ideal_max"] = float(dur_range_match.group(4)) if dur_range_match.group(4) else 45.0
    else:
        duration_rule = dict(COLE_CORCORAN_DEFAULTS["duration"])
        defaults_applied.append("duration: 25s–45s ideal (bounds 20s–60s) [Default Applied]")

    # Tier-1 Geo
    tier1_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:Tier-?1|US,\s*Canada,\s*UK)", text, re.IGNORECASE)
    if tier1_match:
        tier1_geo = float(tier1_match.group(1))
    else:
        tier1_geo = COLE_CORCORAN_DEFAULTS["tier1_geo_min_pct"]
        defaults_applied.append(f"tier1_geo_min_pct: {tier1_geo}% US/CA/UK [Default Applied]")

    # Engagement floor
    eng_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*Engagement", text, re.IGNORECASE)
    if eng_match:
        engagement_min = float(eng_match.group(1))
    else:
        engagement_min = COLE_CORCORAN_DEFAULTS["engagement_min_pct"]
        defaults_applied.append(f"engagement_min_pct: {engagement_min}% (likes+comments/views) [Default Applied]")

    # Watermark
    watermark_asset_match = re.search(r"assets/[a-zA-Z0-9_.-]+(?:png|webp)", text)
    if watermark_asset_match:
        watermark_asset = watermark_asset_match.group(0)
    else:
        watermark_asset = COLE_CORCORAN_DEFAULTS["watermark"]["asset_path"]
        if "watermark" not in text.lower():
            defaults_applied.append(f"watermark: {watermark_asset} persistent, banned in 4 corners [Default Applied]")

    watermark_req = True
    watermark_rule = {
        "required": watermark_req,
        "asset_path": watermark_asset,
        "persistent_entire_clip": True,
        "banned_corners": True,
    }

    # Caption Closers
    closers: List[str] = []
    # Search for numbered closers list
    closer_matches = re.findall(r"^\s*\d+\.\s*`?([a-zA-Z0-9\s@_-]+?)`?\s*$", text, re.MULTILINE)
    if closer_matches and len(closer_matches) >= 4:
        closers = [c.strip() for c in closer_matches]
    else:
        closers = list(COLE_CORCORAN_DEFAULTS["caption_closers"])
        defaults_applied.append("caption_closers: 12 approved rotated closers [Default Applied]")

    # Audio
    audio_rule = dict(COLE_CORCORAN_DEFAULTS["audio"])
    if "phonk" not in text.lower() and "background music" not in text.lower() and "lufs" not in text.lower():
        defaults_applied.append("audio: dialogue normalized to -14 LUFS, zero background music beds [Default Applied]")

    # Prohibited Edits
    prohibited_edits = list(COLE_CORCORAN_DEFAULTS["prohibited_edits"])
    if not any(k in text.lower() for k in ["aura", "glow", "skull", "ai_avatar"]):
        defaults_applied.append("prohibited_edits: [aura, glow, skull, ai_avatar, ai_broll, opus_clips] [Default Applied]")

    # Single post rule
    single_post = True
    if "one clip, one post" not in text.lower() and "posted once" not in text.lower():
        defaults_applied.append("single_post_per_edit: true ('One Clip, One Post' anti-duplication rule) [Default Applied]")

    # Platform overrides
    platform_overrides = json.loads(json.dumps(COLE_CORCORAN_DEFAULTS["platform_overrides"]))
    # Extract bio templates if present
    ig_bio_match = re.search(r"Instagram Bio:?\s*```(?:text)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if ig_bio_match:
        platform_overrides["instagram_reels"]["bio_affiliate_disclaimer"] = ig_bio_match.group(1).strip()
    elif "fan page of" in text:
        platform_overrides["instagram_reels"]["bio_affiliate_disclaimer"] = "fan page of @curiousmike\nnot affiliated"

    tiktok_bio_match = re.search(r"TikTok Bio:?\s*```(?:text)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if tiktok_bio_match:
        platform_overrides["tiktok"]["bio_affiliate_disclaimer"] = tiktok_bio_match.group(1).strip()

    normalized_brief: Dict[str, Any] = {
        "version": "1.0.0",
        "campaign": {
            "title": title,
            "client": client,
            "project": project_slug,
            "source_video": {
                "url": source_url,
                "channel": channel,
                "duration": source_duration,
            },
            "economics": {
                "rate_per_1k_views": rate_per_1k,
                "min_payout_views": min_payout_views,
                "max_payout_views_per_clip": max_payout_views,
                "max_dollar_per_clip": max_dollar_per_clip,
            },
            "platforms": platforms,
            "daily_post_limit": daily_post_limit,
        },
        "global_rules": {
            "duration": duration_rule,
            "tier1_geo_min_pct": tier1_geo,
            "engagement_min_pct": engagement_min,
            "watermark": watermark_rule,
            "caption_closers": closers,
            "audio": audio_rule,
            "prohibited_edits": prohibited_edits,
            "single_post_per_edit": single_post,
        },
        "platform_overrides": platform_overrides,
        "defaults_applied": defaults_applied,
    }

    return normalized_brief, defaults_applied


def format_review_artifact(brief: Dict[str, Any]) -> str:
    """
    Formats the Markdown Review Artifact for the human approval gate.
    Contains:
    1. Campaign Summary & Economics
    2. Strict Non-Negotiable Rules
    3. Platform Specific Overrides
    4. Tier-1 Viral Defaults Injected
    5. Action Required: Approval Gate Prompt
    """
    campaign = brief.get("campaign", {})
    title = campaign.get("title", "Campaign Brief")
    client = campaign.get("client", "Unassigned")
    project = campaign.get("project", "default")
    source_video = campaign.get("source_video", {})
    economics = campaign.get("economics", {})
    platforms = campaign.get("platforms", [])
    daily_limit = campaign.get("daily_post_limit", 4)

    rules = brief.get("global_rules", {})
    duration = rules.get("duration", {})
    tier1 = rules.get("tier1_geo_min_pct", 40.0)
    engagement = rules.get("engagement_min_pct", 1.0)
    watermark = rules.get("watermark", {})
    audio = rules.get("audio", {})
    closers = rules.get("caption_closers", [])
    prohibited = rules.get("prohibited_edits", [])
    overrides = brief.get("platform_overrides", {})
    defaults = brief.get("defaults_applied", [])

    lines = [
        f"# Campaign Brief Review: {title}",
        "",
        "> **Notice**: This campaign brief has been ingested and normalized. Please review the extracted rules, financials, and injected Tier-1 Cole Corcoran defaults below before approving.",
        "",
        "## 1. Campaign Summary & Economics",
        "",
        f"- **Campaign Title**: {title}",
        f"- **Client / Creator**: {client}",
        f"- **Project Slug**: `{project}`",
        f"- **Source Video**: [{source_video.get('url', 'N/A')}]({source_video.get('url', '#')}) (Channel: `{source_video.get('channel', 'N/A')}`, Duration: `{source_video.get('duration', 'N/A')}`)",
        f"- **Pay Rate**: **${economics.get('rate_per_1k_views', 1.0):.2f} per 1,000 verified views**",
        f"- **Minimum Qualification**: **{economics.get('min_payout_views', 2000):,} views** (Under threshold earns $0.00)",
        f"- **Maximum Cap Per Clip**: **${economics.get('max_dollar_per_clip', 300.0):.2f}** ({economics.get('max_payout_views_per_clip', 300000):,} views cap)",
        f"- **Eligible Platforms**: {', '.join(platforms)}",
        f"- **Posting Frequency**: Up to {daily_limit} posts/day per account",
        "",
        "## 2. Strict Non-Negotiable Rules",
        "",
        f"1. **Audience Geography**: Minimum **{tier1}% Tier-1 Viewers** (US, Canada, UK combined).",
        f"2. **Engagement Rate**: Minimum **{engagement}%** `(Likes + Comments) / Views >= {engagement / 100:.2f}`.",
        f"3. **Persistent Watermark**: Mandatory official watermark (`{watermark.get('asset_path', 'assets/watermark_yt_mpj.png')}`) visible entire clip, banned in all 4 corners.",
        f"4. **Audio & Loudness**: Original dialogue normalized to **{audio.get('loudness_target_lufs', -14.0)} LUFS**; zero phonk music, zero loud background music beds.",
        f"5. **Duration Bounds**: Ideal target **{duration.get('ideal_min', 25.0)}s–{duration.get('ideal_max', 45.0)}s** (hard bounds {duration.get('min_seconds', 20.0)}s–{duration.get('max_seconds', 60.0)}s).",
        f"6. **Prohibited Edits**: {', '.join(prohibited)} (instant rejection).",
        "7. **Anti-Duplication**: One Clip, One Post (each unique edit posted only once across accounts).",
        f"8. **Mandatory Rotated Closers**: Every post caption must conclude with one of the **{len(closers)} approved closers**.",
        "",
        "## 3. Platform Specific Overrides",
        "",
        "| Platform | Upload Method | Handle Tagging | Bio / Disclaimer Rule |",
        "| :--- | :--- | :--- | :--- |",
    ]

    yt_ov = overrides.get("youtube_shorts", {})
    tt_ov = overrides.get("tiktok", {})
    ig_ov = overrides.get("instagram_reels", {})

    lines.append(
        f"| **YouTube Shorts** | {'API & Web Safe' if yt_ov.get('api_upload_allowed') else 'Manual Mobile Only'} | Tagged (`{yt_ov.get('handle_format', 'tagged')}`) | {'Whop Bio Verification Code Required' if yt_ov.get('bio_verification_code_required') else 'None'} |"
    )
    lines.append(
        f"| **TikTok** | {'API Allowed' if tt_ov.get('api_upload_allowed') else 'Manual Mobile Only (API = 0-view lock)'} | Plain Text (`{tt_ov.get('handle_format', 'plain_text')}`) | Bio Disclaimer Mandatory |"
    )
    lines.append(
        f"| **Instagram Reels** | {'API Allowed' if ig_ov.get('api_upload_allowed') else 'Manual Mobile Only'} | Plain Text (`{ig_ov.get('handle_format', 'plain_text')}`) | Bio Disclaimer Mandatory |"
    )

    lines.extend([
        "",
        "## 4. Tier-1 Viral Defaults Injected",
        "",
    ])

    if defaults:
        for d in defaults:
            lines.append(f"- [x] `{d}`")
    else:
        lines.append("- *(None: all parameters were explicitly specified in the source brief)*")

    lines.extend([
        "",
        "## 5. Action Required: Approval Gate Prompt",
        "",
        "Downstream editing steps (`clipping-transcription`, `clipping-hook-hunter`, etc.) are currently **blocked** until you approve this campaign brief.",
        "",
        "To approve and unblock the pipeline, run:",
        "```bash",
        f"python3 scripts/clipping_state.py approve --step clipping-guidelines --dir {Path(project).resolve() if os.path.exists(project) else '.'}",
        "```",
        "Or provide custom overrides with:",
        "```bash",
        "python3 scripts/clipping_state.py approve --step clipping-guidelines --override rate_per_1k_views=1.50 --notes 'Custom rate approved'",
        "```",
    ])

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest, normalize, and format campaign clipping guidelines."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", "-f", help="Path to raw markdown or text guidelines file")
    group.add_argument("--text", "-t", help="Raw guidelines text string")
    group.add_argument("--brief", "-b", help="Existing campaign_brief.json to review/update")

    parser.add_argument("--dir", "-d", default=None, help="Target project directory")
    parser.add_argument(
        "--output-brief",
        default=None,
        help="Path to write normalized campaign_brief.json",
    )
    parser.add_argument(
        "--output-artifact",
        default=None,
        help="Path to write campaign_brief_review.md",
    )
    parser.add_argument(
        "--no-state-update",
        action="store_true",
        help="Skip calling clipping_state.py ingest-brief",
    )
    parser.add_argument(
        "--print-artifact",
        action="store_true",
        help="Print review artifact to stdout",
    )

    args = parser.parse_args()

    project_dir = Path(args.dir).resolve() if args.dir else Path.cwd()
    out_brief_path = (
        Path(args.output_brief).resolve()
        if args.output_brief
        else project_dir / "campaign_brief.json"
    )

    # 1. Parse or load brief
    if args.brief:
        brief_file = Path(args.brief).resolve()
        if not brief_file.is_file():
            sys.stderr.write(f"Error: Brief file not found at {brief_file}\n")
            sys.exit(1)
        with open(brief_file, "r", encoding="utf-8") as f:
            brief = json.load(f)
    elif args.file:
        raw_file = Path(args.file).resolve()
        if not raw_file.is_file():
            sys.stderr.write(f"Error: Guidelines file not found at {raw_file}\n")
            sys.exit(1)
        raw_text = raw_file.read_text(encoding="utf-8")
        brief, _ = parse_raw_guidelines_text(raw_text)
    else:
        brief, _ = parse_raw_guidelines_text(args.text)

    # 2. Write normalized campaign_brief.json
    out_brief_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_brief_path, "w", encoding="utf-8") as f:
        json.dump(brief, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Normalized campaign brief written to {out_brief_path}")

    # 3. Generate review artifact
    artifact_content = format_review_artifact(brief)

    if args.output_artifact:
        art_path = Path(args.output_artifact).resolve()
        art_path.parent.mkdir(parents=True, exist_ok=True)
        art_path.write_text(artifact_content, encoding="utf-8")
        print(f"Review artifact written to {art_path}")

    if args.print_artifact:
        print("\n" + "=" * 80)
        print(artifact_content)
        print("=" * 80 + "\n")

    # 4. Integrate with state engine unless skipped
    if not args.no_state_update:
        scripts_dir = Path(__file__).resolve().parent
        state_cli = scripts_dir / "clipping_state.py"
        if state_cli.is_file():
            state_file = project_dir / ".clipping_state.json"
            if not state_file.is_file():
                # Automatically initialize state if missing
                init_cmd = [sys.executable, str(state_cli), "init", "--dir", str(project_dir)]
                subprocess.run(init_cmd, check=True)

            ingest_cmd = [
                sys.executable,
                str(state_cli),
                "ingest-brief",
                "--brief",
                str(out_brief_path),
                "--dir",
                str(project_dir),
            ]
            res = subprocess.run(ingest_cmd, capture_output=True, text=True)
            if res.returncode != 0:
                sys.stderr.write(f"Failed to update clipping state: {res.stderr}\n")
                sys.exit(res.returncode)
            else:
                print(f"Updated .clipping_state.json with pre-digested step parameter slices.")


if __name__ == "__main__":
    main()
