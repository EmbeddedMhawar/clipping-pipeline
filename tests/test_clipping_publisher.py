#!/usr/bin/env python3
"""
tests/test_clipping_publisher.py

Unit and integration tests for scripts/clipping_publisher.py:
- Ticket #17: Brand Cluster Matching & Zero Duplicate Same-Platform Allocation Engine.
- Resolving workspace channels.json.
- Grouping and matching accounts by account_name (Brand Cluster).
- Enforcing zero duplicate same-platform allocation.
- Warmup gating for TikTok and Instagram Reels (blocking Cold Lurker, Account Cooldown).
- YouTube Shorts eligibility.
- CLI subcommands: status, publish, verify-tokens.

Zero external runtime dependencies (Python standard library only).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "clipping_publisher.py"

# Add scripts to sys.path so we can test public module functions directly
sys.path.insert(0, str(REPO_ROOT / "scripts"))


class TestClippingPublisherSlice1BrandCluster(unittest.TestCase):
    """Slice 1: Workspace channels resolution and brand cluster matching."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_publisher_s1_")
        self.channels_path = Path(self.tmpdir) / "channels.json"

        # Create sample channels.json with multiple brand clusters
        self.sample_portfolio = {
            "version": "1.0.0",
            "workspace_id": "test-workspace",
            "channels": [
                {
                    "id": "chan-yt-curious-01",
                    "platform": "YouTube Shorts",
                    "handle": "@CuriousClipsYT",
                    "account_name": "Curious Clips",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 4,
                        "posts_today": 0,
                    },
                },
                {
                    "id": "chan-tt-curious-01",
                    "platform": "TikTok",
                    "handle": "@curiousclips_tt",
                    "account_name": "Curious Clips",
                    "stage": "Seeding",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 1,
                        "posts_today": 0,
                    },
                },
                {
                    "id": "chan-ig-curious-01",
                    "platform": "Instagram Reels",
                    "handle": "@curiousclips_ig",
                    "account_name": "Curious Clips",
                    "stage": "Ramp-Up",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 3,
                        "posts_today": 1,
                    },
                },
                {
                    "id": "chan-yt-n3on-01",
                    "platform": "YouTube Shorts",
                    "handle": "@N3onClipsYT",
                    "account_name": "N3on Daily",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 4,
                        "posts_today": 0,
                    },
                },
            ],
        }
        self.channels_path.write_text(json.dumps(self.sample_portfolio, indent=2), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_script_exists_and_is_executable(self):
        """Verifies scripts/clipping_publisher.py exists, has shebang, and is executable."""
        self.assertTrue(SCRIPT_PATH.is_file(), f"Expected script at {SCRIPT_PATH}")
        content = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("#!/usr/bin/env python3"), "Must start with python3 shebang")
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK), "Script must be executable")

    def test_resolve_channels_path(self):
        """Verifies resolve_channels_path locates channels.json from explicit arg or directories."""
        import clipping_publisher

        # 1. Explicit arg
        resolved = clipping_publisher.resolve_channels_path(channels_arg=str(self.channels_path))
        self.assertEqual(resolved, self.channels_path.resolve())

        # 2. Project directory
        resolved_proj = clipping_publisher.resolve_channels_path(project_dir=Path(self.tmpdir))
        self.assertEqual(resolved_proj, self.channels_path.resolve())

        # 3. Subdirectory finds channels.json in parent directory
        subdir = Path(self.tmpdir) / "subdir"
        subdir.mkdir()
        resolved_sub = clipping_publisher.resolve_channels_path(project_dir=subdir)
        self.assertEqual(resolved_sub, self.channels_path.resolve())

        # 4. Truly isolated directory with no channels.json in tree returns None
        isolated_dir = tempfile.mkdtemp(prefix="test_isolated_")
        try:
            nonexistent = clipping_publisher.resolve_channels_path(project_dir=Path(isolated_dir))
            if not (Path.cwd() / "channels.json").is_file():
                self.assertIsNone(nonexistent)
        finally:
            shutil.rmtree(isolated_dir, ignore_errors=True)

    def test_load_portfolio(self):
        """Verifies load_portfolio loads valid channels.json data."""
        import clipping_publisher

        data = clipping_publisher.load_portfolio(self.channels_path)
        self.assertEqual(data.get("version"), "1.0.0")
        self.assertEqual(len(data.get("channels", [])), 4)

    def test_get_brand_clusters(self):
        """Verifies get_brand_clusters groups accounts by account_name."""
        import clipping_publisher

        clusters = clipping_publisher.get_brand_clusters(self.sample_portfolio)
        self.assertIn("Curious Clips", clusters)
        self.assertIn("N3on Daily", clusters)
        self.assertEqual(len(clusters["Curious Clips"]), 3)
        self.assertEqual(len(clusters["N3on Daily"]), 1)

    def test_match_brand_cluster(self):
        """Verifies match_brand_cluster finds accounts sharing the target account_name."""
        import clipping_publisher

        curious_accounts = clipping_publisher.match_brand_cluster(self.sample_portfolio, "Curious Clips")
        self.assertEqual(len(curious_accounts), 3)
        platforms = {c["platform"] for c in curious_accounts}
        self.assertEqual(platforms, {"YouTube Shorts", "TikTok", "Instagram Reels"})

        # Case-insensitive / whitespace-tolerant matching
        curious_ci = clipping_publisher.match_brand_cluster(self.sample_portfolio, "  curious clips  ")
        self.assertEqual(len(curious_ci), 3)

        # Unmatched brand cluster returns empty list
        empty = clipping_publisher.match_brand_cluster(self.sample_portfolio, "NonExistent")
        self.assertEqual(empty, [])


class TestClippingPublisherSlice2WarmupGating(unittest.TestCase):
    """Slice 2: Warmup gating for TikTok, Instagram Reels, and YouTube Shorts."""

    def test_tiktok_cold_lurker_strictly_blocked(self):
        """Verifies TikTok in Cold Lurker stage is strictly blocked."""
        import clipping_publisher

        chan = {
            "id": "chan-tt-cold",
            "platform": "TikTok",
            "handle": "@cold_clips",
            "account_name": "Cold Brand",
            "stage": "Cold Lurker",
            "status": "active",
            "posting_cadence": {"daily_post_limit": 0, "posts_today": 0},
        }
        eligible, reason = clipping_publisher.is_channel_warmed_up(chan)
        self.assertFalse(eligible)
        self.assertIn("Cold Lurker", reason)

    def test_instagram_account_cooldown_strictly_blocked(self):
        """Verifies Instagram channel in cooldown (by stage, status, or flag) is blocked."""
        import clipping_publisher

        # 1. By stage
        chan_stage = {
            "id": "chan-ig-cd1",
            "platform": "Instagram Reels",
            "handle": "@cd_clips1",
            "account_name": "CD Brand",
            "stage": "Account Cooldown",
            "status": "cooldown",
            "posting_cadence": {"daily_post_limit": 0, "posts_today": 0},
        }
        eligible, reason = clipping_publisher.is_channel_warmed_up(chan_stage)
        self.assertFalse(eligible)
        self.assertIn("cooldown", reason.lower())

        # 2. By cooldown.in_cooldown flag
        chan_flag = {
            "id": "chan-ig-cd2",
            "platform": "Instagram Reels",
            "handle": "@cd_clips2",
            "account_name": "CD Brand",
            "stage": "Seeding",
            "status": "active",
            "cooldown": {"in_cooldown": True, "reason": "0-view shadowban"},
            "posting_cadence": {"daily_post_limit": 1, "posts_today": 0},
        }
        eligible, reason = clipping_publisher.is_channel_warmed_up(chan_flag)
        self.assertFalse(eligible)
        self.assertIn("cooldown", reason.lower())

    def test_tiktok_seeding_ramp_mature_eligible_when_quota_available(self):
        """Verifies Seeding, Ramp-Up, Mature TikTok channels are eligible when quota remains."""
        import clipping_publisher

        for stage, limit in [("Seeding", 1), ("Ramp-Up", 3), ("Mature", 4)]:
            chan = {
                "id": f"chan-tt-{stage.lower()}",
                "platform": "TikTok",
                "handle": f"@{stage.lower()}_clips",
                "account_name": "Active Brand",
                "stage": stage,
                "status": "active",
                "posting_cadence": {"daily_post_limit": limit, "posts_today": 0},
            }
            eligible, reason = clipping_publisher.is_channel_warmed_up(chan)
            self.assertTrue(eligible, f"Expected {stage} to be eligible: {reason}")

    def test_quota_exhausted_blocked(self):
        """Verifies channels with posts_today >= daily_post_limit are blocked."""
        import clipping_publisher

        chan = {
            "id": "chan-tt-exhausted",
            "platform": "TikTok",
            "handle": "@exhausted_clips",
            "account_name": "Active Brand",
            "stage": "Seeding",
            "status": "active",
            "posting_cadence": {"daily_post_limit": 1, "posts_today": 1},
        }
        eligible, reason = clipping_publisher.is_channel_warmed_up(chan)
        self.assertFalse(eligible)
        self.assertIn("limit", reason.lower())

    def test_youtube_shorts_eligibility(self):
        """Verifies YouTube Shorts channel eligibility."""
        import clipping_publisher

        # Active YouTube Shorts channel is eligible
        yt_chan = {
            "id": "chan-yt-01",
            "platform": "YouTube Shorts",
            "handle": "@YTClips",
            "account_name": "YT Brand",
            "stage": "Mature",
            "status": "active",
            "posting_cadence": {"daily_post_limit": 4, "posts_today": 0},
        }
        eligible, _ = clipping_publisher.is_channel_warmed_up(yt_chan)
        self.assertTrue(eligible)

        # YouTube channel in cooldown or banned is blocked
        yt_cooldown = dict(yt_chan, status="cooldown")
        eligible, reason = clipping_publisher.is_channel_warmed_up(yt_cooldown)
        self.assertFalse(eligible)

        yt_banned = dict(yt_chan, status="banned")
        eligible, reason = clipping_publisher.is_channel_warmed_up(yt_banned)
        self.assertFalse(eligible)


class TestClippingPublisherSlice3PlatformAllocation(unittest.TestCase):
    """Slice 3: Platform allocation, deduplication, and zero duplicate same-platform rejection."""

    def setUp(self):
        self.valid_targets = [
            {
                "id": "chan-yt-01",
                "platform": "YouTube Shorts",
                "handle": "@yt",
                "account_name": "Brand",
                "stage": "Mature",
                "status": "active",
                "posting_cadence": {"daily_post_limit": 4, "posts_today": 0},
            },
            {
                "id": "chan-tt-01",
                "platform": "TikTok",
                "handle": "@tt",
                "account_name": "Brand",
                "stage": "Seeding",
                "status": "active",
                "posting_cadence": {"daily_post_limit": 1, "posts_today": 0},
            },
            {
                "id": "chan-ig-01",
                "platform": "Instagram Reels",
                "handle": "@ig",
                "account_name": "Brand",
                "stage": "Ramp-Up",
                "status": "active",
                "posting_cadence": {"daily_post_limit": 3, "posts_today": 0},
            },
        ]

    def test_validate_target_allocation_passes_for_distinct_platforms(self):
        """Verifies validate_target_allocation succeeds when each platform appears at most once."""
        import clipping_publisher

        # Should not raise
        clipping_publisher.validate_target_allocation(self.valid_targets)

    def test_validate_target_allocation_raises_on_duplicate_platform(self):
        """Verifies validate_target_allocation hard-fails when multiple channels share a platform."""
        import clipping_publisher

        duplicate_targets = [
            self.valid_targets[0],
            self.valid_targets[1],
            {
                "id": "chan-tt-02",
                "platform": "TikTok",
                "handle": "@tt2",
                "account_name": "Brand",
                "stage": "Ramp-Up",
                "status": "active",
                "posting_cadence": {"daily_post_limit": 3, "posts_today": 0},
            },
        ]
        with self.assertRaises(clipping_publisher.DuplicatePlatformError) as ctx:
            clipping_publisher.validate_target_allocation(duplicate_targets)
        self.assertIn("TikTok", str(ctx.exception))
        self.assertIn("chan-tt-01", str(ctx.exception))
        self.assertIn("chan-tt-02", str(ctx.exception))

    def test_validate_target_allocation_normalizes_platform_aliases(self):
        """Verifies validate_target_allocation detects duplicates even with platform aliases."""
        import clipping_publisher

        alias_targets = [
            {
                "id": "chan-yt-01",
                "platform": "YouTube Shorts",
                "handle": "@yt",
                "account_name": "Brand",
                "stage": "Mature",
                "status": "active",
            },
            {
                "id": "chan-yt-02",
                "platform": "shorts",
                "handle": "@yt2",
                "account_name": "Brand",
                "stage": "Mature",
                "status": "active",
            },
        ]
        with self.assertRaises(clipping_publisher.DuplicatePlatformError) as ctx:
            clipping_publisher.validate_target_allocation(alias_targets)
        self.assertIn("YouTube Shorts", str(ctx.exception))

    def test_select_platform_targets_allocates_one_per_platform(self):
        """Verifies select_platform_targets allocates at most 1 channel per platform."""
        import clipping_publisher

        allocated = clipping_publisher.select_platform_targets(self.valid_targets)
        self.assertEqual(len(allocated), 3)
        self.assertEqual(allocated["YouTube Shorts"]["id"], "chan-yt-01")
        self.assertEqual(allocated["TikTok"]["id"], "chan-tt-01")
        self.assertEqual(allocated["Instagram Reels"]["id"], "chan-ig-01")

    def test_select_platform_targets_filters_non_warmed_channels(self):
        """Verifies select_platform_targets filters out channels in Cold Lurker or Cooldown."""
        import clipping_publisher

        mixed_targets = [
            self.valid_targets[0],  # YT Mature -> eligible
            {
                "id": "chan-tt-cold",
                "platform": "TikTok",
                "handle": "@tt_cold",
                "account_name": "Brand",
                "stage": "Cold Lurker",
                "status": "active",
                "posting_cadence": {"daily_post_limit": 0, "posts_today": 0},
            },
            {
                "id": "chan-ig-cd",
                "platform": "Instagram Reels",
                "handle": "@ig_cd",
                "account_name": "Brand",
                "stage": "Account Cooldown",
                "status": "cooldown",
                "posting_cadence": {"daily_post_limit": 0, "posts_today": 0},
            },
        ]
        allocated = clipping_publisher.select_platform_targets(mixed_targets)
        self.assertEqual(len(allocated), 1)
        self.assertIn("YouTube Shorts", allocated)
        self.assertNotIn("TikTok", allocated)
        self.assertNotIn("Instagram Reels", allocated)

    def test_select_platform_targets_fails_on_duplicate_eligible_same_platform(self):
        """Verifies select_platform_targets hard-fails if multiple eligible channels exist for same platform."""
        import clipping_publisher

        duplicate_eligible = [
            self.valid_targets[1],  # TikTok Seeding, eligible
            {
                "id": "chan-tt-02",
                "platform": "TikTok",
                "handle": "@tt_alt",
                "account_name": "Brand",
                "stage": "Ramp-Up",
                "status": "active",
                "posting_cadence": {"daily_post_limit": 3, "posts_today": 0},
            },
        ]
        with self.assertRaises(clipping_publisher.DuplicatePlatformError) as ctx:
            clipping_publisher.select_platform_targets(duplicate_eligible)
        self.assertIn("TikTok", str(ctx.exception))

    def test_select_platform_targets_filters_by_requested_platforms(self):
        """Verifies select_platform_targets filters by requested platforms."""
        import clipping_publisher

        allocated = clipping_publisher.select_platform_targets(
            self.valid_targets, platforms=["YouTube Shorts", "TikTok"]
        )
        self.assertEqual(len(allocated), 2)
        self.assertIn("YouTube Shorts", allocated)
        self.assertIn("TikTok", allocated)
        self.assertNotIn("Instagram Reels", allocated)


class TestClippingPublisherSlice4CLI(unittest.TestCase):
    """Slice 4: CLI Subcommands (status, publish, verify-tokens)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_publisher_cli_")
        self.channels_path = Path(self.tmpdir) / "channels.json"

        self.portfolio_data = {
            "version": "1.0.0",
            "workspace_id": "cli-test-workspace",
            "channels": [
                {
                    "id": "chan-yt-01",
                    "platform": "YouTube Shorts",
                    "handle": "@CuriousYT",
                    "account_name": "Curious Media",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {"daily_post_limit": 4, "posts_today": 0},
                },
                {
                    "id": "chan-tt-01",
                    "platform": "TikTok",
                    "handle": "@CuriousTT",
                    "account_name": "Curious Media",
                    "stage": "Seeding",
                    "status": "active",
                    "posting_cadence": {"daily_post_limit": 1, "posts_today": 0},
                },
                {
                    "id": "chan-ig-01",
                    "platform": "Instagram Reels",
                    "handle": "@CuriousIG",
                    "account_name": "Curious Media",
                    "stage": "Ramp-Up",
                    "status": "active",
                    "posting_cadence": {"daily_post_limit": 3, "posts_today": 0},
                },
                # Cold Lurker brand cluster
                {
                    "id": "chan-tt-cold",
                    "platform": "TikTok",
                    "handle": "@ColdTT",
                    "account_name": "Cold Brand",
                    "stage": "Cold Lurker",
                    "status": "active",
                    "posting_cadence": {"daily_post_limit": 0, "posts_today": 0},
                },
                # Extra TikTok channel to test duplicate rejection
                {
                    "id": "chan-tt-dup",
                    "platform": "TikTok",
                    "handle": "@CuriousTT2",
                    "account_name": "Curious Duplicate",
                    "stage": "Seeding",
                    "status": "active",
                    "posting_cadence": {"daily_post_limit": 1, "posts_today": 0},
                },
            ],
        }
        self.channels_path.write_text(json.dumps(self.portfolio_data, indent=2), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_cli(self, args: List[str]) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(SCRIPT_PATH)] + args
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_status_subcommand_human_and_json(self):
        """Verifies 'status' displays brand clusters and supports --json flag."""
        # 1. Human-readable output
        res = self.run_cli(["status", "--channels", str(self.channels_path)])
        self.assertEqual(res.returncode, 0, f"status failed: {res.stderr}")
        self.assertIn("Curious Media", res.stdout)
        self.assertIn("Cold Brand", res.stdout)

        # 2. JSON output
        res_json = self.run_cli(["status", "--channels", str(self.channels_path), "--json"])
        self.assertEqual(res_json.returncode, 0)
        parsed = json.loads(res_json.stdout)
        self.assertIn("clusters", parsed)
        self.assertIn("Curious Media", parsed["clusters"])

    def test_status_filter_brand_cluster(self):
        """Verifies 'status --brand-cluster' filters display to target cluster."""
        res = self.run_cli([
            "status",
            "--channels", str(self.channels_path),
            "--brand-cluster", "Curious Media",
            "--json",
        ])
        self.assertEqual(res.returncode, 0)
        parsed = json.loads(res_json := res.stdout)
        data = json.loads(res_json)
        self.assertIn("Curious Media", data["clusters"])
        self.assertNotIn("Cold Brand", data["clusters"])

    def test_publish_allocates_brand_cluster_targets(self):
        """Verifies 'publish' matches brand cluster and allocates 1 channel per platform."""
        res = self.run_cli([
            "publish",
            "--brand-cluster", "Curious Media",
            "--channels", str(self.channels_path),
            "--dry-run",
            "--json",
        ])
        self.assertEqual(res.returncode, 0, f"publish failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "allocated")
        self.assertEqual(data.get("brand_cluster"), "Curious Media")
        targets = data.get("targets", {})
        self.assertEqual(len(targets), 3)
        self.assertEqual(targets["YouTube Shorts"]["id"], "chan-yt-01")
        self.assertEqual(targets["TikTok"]["id"], "chan-tt-01")
        self.assertEqual(targets["Instagram Reels"]["id"], "chan-ig-01")

    def test_publish_rejects_duplicate_same_platform_explicit(self):
        """Verifies 'publish' hard-fails when multiple channels on same platform are passed."""
        res = self.run_cli([
            "publish",
            "--channel-ids", "chan-tt-01,chan-tt-dup",
            "--channels", str(self.channels_path),
            "--dry-run",
        ])
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Duplicate channels targeted for platform 'TikTok'", res.stderr)

    def test_publish_filters_cold_lurker_in_cluster(self):
        """Verifies 'publish' filters out Cold Lurker channels during allocation."""
        res = self.run_cli([
            "publish",
            "--brand-cluster", "Cold Brand",
            "--channels", str(self.channels_path),
            "--dry-run",
            "--json",
        ])
        # Since Cold Brand only has Cold Lurker TikTok, no eligible targets remain
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("No eligible warmed-up channels", res.stderr)

    def test_publish_unknown_cluster_fails(self):
        """Verifies 'publish' fails with explicit error when brand cluster is not found."""
        res = self.run_cli([
            "publish",
            "--brand-cluster", "NonExistentBrand",
            "--channels", str(self.channels_path),
            "--dry-run",
        ])
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("No channels found matching brand cluster 'NonExistentBrand'", res.stderr)

    def test_verify_tokens_subcommand(self):
        """Verifies 'verify-tokens' checks YouTube channels and supports --json flag."""
        res = self.run_cli([
            "verify-tokens",
            "--channels", str(self.channels_path),
            "--json",
        ])
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertIn("youtube_channels", data)
        self.assertEqual(len(data["youtube_channels"]), 1)
        self.assertEqual(data["youtube_channels"][0]["id"], "chan-yt-01")


class TestClippingPublisherSlice5CaptionBundling(unittest.TestCase):
    """Slice 5: Caption formatting and companion caption.txt bundling."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_caption_bundling_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_format_caption_full_fields(self):
        """Verifies format_caption combines hook, body, hashtags, and closer into standard layout."""
        import clipping_publisher

        formatted = clipping_publisher.format_caption(
            hook="Stop making this clipping mistake!",
            body="Here is why your retention drops at 0:03 seconds.",
            hashtags=["#clipping", "#podcast", "#viral"],
            closer="Follow @curiousclips for daily breakdowns.",
        )
        expected = (
            "Stop making this clipping mistake!\n\n"
            "Here is why your retention drops at 0:03 seconds.\n\n"
            "#clipping #podcast #viral\n\n"
            "Follow @curiousclips for daily breakdowns."
        )
        self.assertEqual(formatted, expected)

    def test_format_caption_hashtags_as_string_and_normalizes_hash(self):
        """Verifies format_caption accepts string hashtags and ensures hash symbols."""
        import clipping_publisher

        formatted = clipping_publisher.format_caption(
            hook="Viral Hook",
            body="Clip body",
            hashtags="shorts, podcast, n3on",
            closer="Check link in bio",
        )
        self.assertIn("#shorts #podcast #n3on", formatted)

    def test_format_caption_omitted_optional_fields(self):
        """Verifies format_caption handles missing hook, body, hashtags, or closer cleanly."""
        import clipping_publisher

        # Only hook and hashtags
        formatted = clipping_publisher.format_caption(
            hook="Hook Only",
            hashtags=["#test"],
        )
        self.assertEqual(formatted, "Hook Only\n\n#test")

        # Empty returns empty string
        self.assertEqual(clipping_publisher.format_caption(), "")

    def test_bundle_caption_writes_file_alongside_video(self):
        """Verifies bundle_caption writes caption.txt in the same directory as the video file."""
        import clipping_publisher

        video_path = Path(self.tmpdir) / "output_clip.mp4"
        video_path.write_bytes(b"dummy mp4 content")

        caption_path = clipping_publisher.bundle_caption(
            target=video_path,
            hook="Test Hook",
            body="Test Body",
            hashtags=["#test"],
            closer="Test Closer",
        )

        expected_caption_file = Path(self.tmpdir) / "caption.txt"
        self.assertEqual(caption_path.resolve(), expected_caption_file.resolve())
        self.assertTrue(expected_caption_file.is_file())

        content = expected_caption_file.read_text(encoding="utf-8")
        self.assertIn("Test Hook", content)
        self.assertIn("Test Body", content)
        self.assertIn("#test", content)
        self.assertIn("Test Closer", content)

    def test_bundle_caption_writes_to_explicit_directory(self):
        """Verifies bundle_caption writes caption.txt into an explicit directory."""
        import clipping_publisher

        target_dir = Path(self.tmpdir) / "staged"
        caption_path = clipping_publisher.bundle_caption(
            target=target_dir,
            caption_content="Custom pre-formatted caption string",
        )

        self.assertEqual(caption_path, target_dir / "caption.txt")
        self.assertTrue(caption_path.is_file())
        self.assertEqual(caption_path.read_text(encoding="utf-8"), "Custom pre-formatted caption string")


class TestClippingPublisherSlice6MobileTransfer(unittest.TestCase):
    """Slice 6: Mobile device delivery protocols (cloud_folder, adb_push, local_qr, webhook)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_mobile_transfer_")
        self.video_file = Path(self.tmpdir) / "render_clip_01.mp4"
        self.video_file.write_bytes(b"\x00\x00\x00\x1cftypisom")
        self.caption_file = Path(self.tmpdir) / "caption.txt"
        self.caption_file.write_text("Hook: Watch this!\n\n#clipping", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_deliver_cloud_folder_copies_video_and_caption(self):
        """Verifies cloud_folder copies both the rendered MP4 and companion caption.txt to destination."""
        import clipping_publisher

        cloud_dest = Path(self.tmpdir) / "CloudStorage"
        channel = {
            "id": "chan-tt-01",
            "platform": "TikTok",
            "device_transfer": {
                "protocol": "cloud_folder",
                "target": str(cloud_dest),
                "enabled": True,
            },
        }

        res = clipping_publisher.deliver_mobile_channel(
            channel=channel,
            video_path=self.video_file,
            caption_path=self.caption_file,
            dry_run=False,
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["protocol"], "cloud_folder")
        self.assertTrue((cloud_dest / self.video_file.name).is_file())
        self.assertTrue((cloud_dest / "caption.txt").is_file())
        self.assertEqual(
            (cloud_dest / "caption.txt").read_text(encoding="utf-8"),
            "Hook: Watch this!\n\n#clipping",
        )

    def test_deliver_cloud_folder_dry_run_does_not_copy_files(self):
        """Verifies cloud_folder in dry_run mode does not perform filesystem copies."""
        import clipping_publisher

        cloud_dest = Path(self.tmpdir) / "CloudDryRun"
        channel = {
            "id": "chan-tt-01",
            "platform": "TikTok",
            "device_transfer": {
                "protocol": "cloud_folder",
                "target": str(cloud_dest),
                "enabled": True,
            },
        }

        res = clipping_publisher.deliver_mobile_channel(
            channel=channel,
            video_path=self.video_file,
            caption_path=self.caption_file,
            dry_run=True,
        )

        self.assertEqual(res["status"], "simulated")
        self.assertFalse(cloud_dest.exists())

    def test_deliver_adb_push_executes_transfer(self):
        """Verifies adb_push stages or executes push of video and caption to target path."""
        import clipping_publisher

        channel = {
            "id": "chan-ig-01",
            "platform": "Instagram Reels",
            "device_transfer": {
                "protocol": "adb_push",
                "target": "/sdcard/DCIM/Camera/",
                "enabled": True,
            },
        }

        res = clipping_publisher.deliver_mobile_channel(
            channel=channel,
            video_path=self.video_file,
            caption_path=self.caption_file,
            dry_run=False,
        )

        self.assertIn(res["status"], ("success", "simulated"))
        self.assertEqual(res["protocol"], "adb_push")
        self.assertEqual(res["adb_target"], "/sdcard/DCIM/Camera/")
        self.assertEqual(res["video_path"], str(self.video_file))
        self.assertEqual(res["caption_path"], str(self.caption_file))

    def test_deliver_local_qr_protocol(self):
        """Verifies local_qr produces local server download URLs for video and caption."""
        import clipping_publisher

        channel = {
            "id": "chan-tt-qr",
            "platform": "TikTok",
            "device_transfer": {
                "protocol": "local_qr",
                "target": "http://192.168.1.50:8080",
                "enabled": True,
            },
        }

        res = clipping_publisher.deliver_mobile_channel(
            channel=channel,
            video_path=self.video_file,
            caption_path=self.caption_file,
            dry_run=False,
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["protocol"], "local_qr")
        self.assertIn("192.168.1.50:8080", res["server_url"])
        self.assertIn("caption", res["caption_url"])

    def test_deliver_webhook_protocol(self):
        """Verifies webhook protocol prepares dispatch payload with video and caption."""
        import clipping_publisher

        channel = {
            "id": "chan-ig-hook",
            "platform": "Instagram Reels",
            "device_transfer": {
                "protocol": "webhook",
                "target": "https://api.telegram.org/bot123/sendVideo",
                "enabled": True,
            },
        }

        res = clipping_publisher.deliver_mobile_channel(
            channel=channel,
            video_path=self.video_file,
            caption_path=self.caption_file,
            dry_run=False,
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["protocol"], "webhook")
        self.assertEqual(res["webhook_url"], "https://api.telegram.org/bot123/sendVideo")

    def test_deliver_disabled_channel_raises_error(self):
        """Verifies deliver_mobile_channel raises ValueError if device transfer is disabled."""
        import clipping_publisher

        channel = {
            "id": "chan-tt-disabled",
            "platform": "TikTok",
            "device_transfer": {
                "protocol": "cloud_folder",
                "target": "/tmp",
                "enabled": False,
            },
        }

        with self.assertRaises(ValueError) as ctx:
            clipping_publisher.deliver_mobile_channel(
                channel=channel,
                video_path=self.video_file,
                caption_path=self.caption_file,
            )
        self.assertIn("disabled", str(ctx.exception).lower())


class TestClippingPublisherSlice7QuotaStaging(unittest.TestCase):
    """Slice 7: Quota staging in channels.json portfolio registry."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_quota_staging_")
        self.channels_path = Path(self.tmpdir) / "channels.json"
        self.portfolio_data = {
            "version": "1.0.0",
            "workspace_id": "quota-test",
            "channels": [
                {
                    "id": "chan-tt-01",
                    "platform": "TikTok",
                    "handle": "@test_tt",
                    "stage": "Seeding",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 1,
                        "posts_today": 0,
                    },
                    "post_log": [],
                },
                {
                    "id": "chan-ig-01",
                    "platform": "Instagram Reels",
                    "handle": "@test_ig",
                    "stage": "Ramp-Up",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 3,
                        "posts_today": 1,
                    },
                    "post_log": [],
                },
            ],
        }
        self.channels_path.write_text(json.dumps(self.portfolio_data, indent=2), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stage_channel_quota_increments_and_appends_log(self):
        """Verifies stage_channel_quota increments posts_today, sets last_post_date, and logs staged_mobile."""
        import clipping_publisher

        portfolio = clipping_publisher.load_portfolio(self.channels_path)
        chan = clipping_publisher.stage_channel_quota(
            portfolio=portfolio,
            channel_id="chan-tt-01",
            clip_id="clip-test-101",
            project="test-campaign",
            channels_path=self.channels_path,
        )

        self.assertEqual(chan["posting_cadence"]["posts_today"], 1)
        self.assertTrue(chan["posting_cadence"]["last_post_date"])
        self.assertEqual(len(chan["post_log"]), 1)
        log_entry = chan["post_log"][0]
        self.assertEqual(log_entry["clip_id"], "clip-test-101")
        self.assertEqual(log_entry["status"], "staged_mobile")
        self.assertEqual(log_entry["project"], "test-campaign")

        # Verify persistence on disk
        reloaded = clipping_publisher.load_portfolio(self.channels_path)
        reloaded_chan = next(c for c in reloaded["channels"] if c["id"] == "chan-tt-01")
        self.assertEqual(reloaded_chan["posting_cadence"]["posts_today"], 1)
        self.assertEqual(reloaded_chan["post_log"][0]["status"], "staged_mobile")

    def test_quota_staging_blocks_subsequent_channel_eligibility(self):
        """Verifies channel with limit 1 is immediately blocked by is_channel_warmed_up after staging."""
        import clipping_publisher

        portfolio = clipping_publisher.load_portfolio(self.channels_path)
        chan = next(c for c in portfolio["channels"] if c["id"] == "chan-tt-01")

        # Initially eligible
        eligible, _ = clipping_publisher.is_channel_warmed_up(chan)
        self.assertTrue(eligible)

        # Stage quota
        clipping_publisher.stage_channel_quota(
            portfolio=portfolio,
            channel_id="chan-tt-01",
            clip_id="clip-test-102",
        )

        # Now limit reached (1/1) -> blocked
        eligible_after, reason = clipping_publisher.is_channel_warmed_up(chan)
        self.assertFalse(eligible_after)
        self.assertIn("Daily post limit reached", reason)

    def test_stage_nonexistent_channel_raises_value_error(self):
        """Verifies stage_channel_quota raises ValueError when channel ID is not found."""
        import clipping_publisher

        portfolio = clipping_publisher.load_portfolio(self.channels_path)
        with self.assertRaises(ValueError) as ctx:
            clipping_publisher.stage_channel_quota(
                portfolio=portfolio,
                channel_id="non-existent-channel",
                clip_id="clip-001",
            )
        self.assertIn("non-existent-channel", str(ctx.exception))


class TestClippingPublisherSlice8PublishIntegration(unittest.TestCase):
    """Slice 8: End-to-end publish command integration with mobile delivery & quota staging."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_pub_int_")
        self.channels_path = Path(self.tmpdir) / "channels.json"
        self.cloud_folder = Path(self.tmpdir) / "CloudStorage"

        self.video_file = Path(self.tmpdir) / "test_clip.mp4"
        self.video_file.write_bytes(b"\x00\x00\x00\x1cftypmp42")

        self.portfolio_data = {
            "version": "1.0.0",
            "workspace_id": "int-test-workspace",
            "channels": [
                {
                    "id": "chan-tt-01",
                    "platform": "TikTok",
                    "handle": "@int_tt",
                    "account_name": "Int Brand",
                    "stage": "Seeding",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 1,
                        "posts_today": 0,
                    },
                    "device_transfer": {
                        "protocol": "cloud_folder",
                        "target": str(self.cloud_folder),
                        "enabled": True,
                    },
                    "post_log": [],
                },
                {
                    "id": "chan-ig-01",
                    "platform": "Instagram Reels",
                    "handle": "@int_ig",
                    "account_name": "Int Brand",
                    "stage": "Ramp-Up",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 3,
                        "posts_today": 0,
                    },
                    "device_transfer": {
                        "protocol": "local_qr",
                        "target": "http://127.0.0.1:8080",
                        "enabled": True,
                    },
                    "post_log": [],
                },
            ],
        }
        self.channels_path.write_text(json.dumps(self.portfolio_data, indent=2), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_cli(self, args: List[str]) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(SCRIPT_PATH)] + args
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_publish_executes_mobile_transfer_and_quota_staging(self):
        """Verifies publish subcommand delivers files to mobile target and stages quota in channels.json."""
        res = self.run_cli([
            "publish",
            "--brand-cluster", "Int Brand",
            "--channels", str(self.channels_path),
            "--video", str(self.video_file),
            "--clip-id", "clip-int-999",
            "--caption-hook", "Mindblowing Truth!",
            "--caption-body", "You won't believe what happened in this episode.",
            "--hashtags", "mindblown, podcast, clips",
            "--caption-closer", "Follow for more daily clips!",
            "--json",
        ])
        self.assertEqual(res.returncode, 0, f"publish failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "staged_mobile")
        self.assertEqual(data.get("clip_id"), "clip-int-999")

        # Verify cloud_folder received video and caption
        self.assertTrue((self.cloud_folder / "test_clip.mp4").is_file())
        caption_dest = self.cloud_folder / "caption.txt"
        self.assertTrue(caption_dest.is_file())
        caption_text = caption_dest.read_text(encoding="utf-8")
        self.assertIn("Mindblowing Truth!", caption_text)
        self.assertIn("#mindblown #podcast #clips", caption_text)
        self.assertIn("Follow for more daily clips!", caption_text)

        # Verify channels.json on disk has incremented posts_today and staged_mobile log
        portfolio = json.loads(self.channels_path.read_text(encoding="utf-8"))
        tt_chan = next(c for c in portfolio["channels"] if c["id"] == "chan-tt-01")
        self.assertEqual(tt_chan["posting_cadence"]["posts_today"], 1)
        self.assertEqual(len(tt_chan["post_log"]), 1)
        self.assertEqual(tt_chan["post_log"][0]["clip_id"], "clip-int-999")
        self.assertEqual(tt_chan["post_log"][0]["status"], "staged_mobile")

        ig_chan = next(c for c in portfolio["channels"] if c["id"] == "chan-ig-01")
        self.assertEqual(ig_chan["posting_cadence"]["posts_today"], 1)
        self.assertEqual(ig_chan["post_log"][0]["status"], "staged_mobile")

    def test_publish_dry_run_leaves_channels_json_untouched(self):
        """Verifies publish with --dry-run does not modify posts_today or create cloud files."""
        res = self.run_cli([
            "publish",
            "--brand-cluster", "Int Brand",
            "--channels", str(self.channels_path),
            "--video", str(self.video_file),
            "--clip-id", "clip-dry-1",
            "--dry-run",
            "--json",
        ])
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "allocated")

        # Destination folder should not exist
        self.assertFalse(self.cloud_folder.exists())

        # channels.json should have 0 posts_today
        portfolio = json.loads(self.channels_path.read_text(encoding="utf-8"))
        tt_chan = next(c for c in portfolio["channels"] if c["id"] == "chan-tt-01")
        self.assertEqual(tt_chan["posting_cadence"]["posts_today"], 0)
        self.assertEqual(len(tt_chan["post_log"]), 0)

    def test_publish_with_caption_file(self):
        """Verifies publish accepts --caption-file and delivers its content."""
        custom_cap = Path(self.tmpdir) / "source_caption.txt"
        custom_cap.write_text("Custom Preformatted Caption #custom", encoding="utf-8")

        res = self.run_cli([
            "publish",
            "--brand-cluster", "Int Brand",
            "--channels", str(self.channels_path),
            "--video", str(self.video_file),
            "--caption-file", str(custom_cap),
            "--json",
        ])
        self.assertEqual(res.returncode, 0)
        self.assertTrue((self.cloud_folder / "caption.txt").is_file())
        self.assertEqual(
            (self.cloud_folder / "caption.txt").read_text(encoding="utf-8"),
            "Custom Preformatted Caption #custom",
        )

    def test_publish_missing_video_error_when_executing(self):
        """Verifies publish without --video fails with clear error when not in dry_run."""
        res = self.run_cli([
            "publish",
            "--brand-cluster", "Int Brand",
            "--channels", str(self.channels_path),
        ])
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("video", res.stderr.lower())

    def test_publish_clip_programmatic_api(self):
        """Verifies publish_clip function can be invoked programmatically."""
        import clipping_publisher

        res = clipping_publisher.publish_clip(
            channels_path=self.channels_path,
            video_path=self.video_file,
            brand_cluster="Int Brand",
            caption_hook="API Hook",
            caption_body="API Body",
            hashtags=["#api"],
            caption_closer="API Closer",
            dry_run=False,
        )

        self.assertEqual(res["status"], "staged_mobile")
        self.assertEqual(len(res["publication_manifest"]), 2)
        self.assertTrue(Path(res["caption_file"]).is_file())


class TestClippingPublisherSlice9YouTubeTokenResolution(unittest.TestCase):
    """Slice 9: YouTube OAuth token resolution and refreshing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_yt_tokens_")
        self.config_dir = Path(self.tmpdir) / ".config" / "clipping-pipeline" / "youtube"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_resolve_token_from_channel_metadata_access_token(self):
        """Verifies resolve_youtube_token extracts access_token directly from channel metadata."""
        import clipping_publisher

        channel = {
            "id": "chan-yt-meta",
            "platform": "YouTube Shorts",
            "access_token": "ya29.direct_meta_token",
        }
        token = clipping_publisher.resolve_youtube_token(channel)
        self.assertEqual(token, "ya29.direct_meta_token")

    def test_resolve_token_from_channel_credentials_dict(self):
        """Verifies resolve_youtube_token extracts access_token from channel credentials dict."""
        import clipping_publisher

        channel = {
            "id": "chan-yt-cred",
            "platform": "YouTube Shorts",
            "credentials": {
                "access_token": "ya29.cred_dict_token",
            },
        }
        token = clipping_publisher.resolve_youtube_token(channel)
        self.assertEqual(token, "ya29.cred_dict_token")

    def test_resolve_token_from_custom_credentials_file(self):
        """Verifies resolve_youtube_token reads token from custom credentials_path file."""
        import clipping_publisher

        cred_file = Path(self.tmpdir) / "custom_token.json"
        cred_file.write_text(json.dumps({"access_token": "ya29.file_token"}), encoding="utf-8")

        channel = {
            "id": "chan-yt-custom-file",
            "platform": "YouTube Shorts",
            "credentials_path": str(cred_file),
        }
        token = clipping_publisher.resolve_youtube_token(channel)
        self.assertEqual(token, "ya29.file_token")

    def test_resolve_token_from_default_config_path(self):
        """Verifies resolve_youtube_token locates ~/.config/clipping-pipeline/youtube/<channel_id>_token.json."""
        import clipping_publisher
        from unittest.mock import patch

        default_token_file = self.config_dir / "chan-yt-default_token.json"
        default_token_file.write_text(json.dumps({"access_token": "ya29.default_config_token"}), encoding="utf-8")

        channel = {
            "id": "chan-yt-default",
            "platform": "YouTube Shorts",
        }
        with patch("pathlib.Path.home", return_value=Path(self.tmpdir)):
            token = clipping_publisher.resolve_youtube_token(channel)
            self.assertEqual(token, "ya29.default_config_token")

    def test_resolve_token_from_environment_variable(self):
        """Verifies resolve_youtube_token reads YOUTUBE_TOKEN_<CHAN_ID> env var."""
        import clipping_publisher
        from unittest.mock import patch

        channel = {
            "id": "chan-yt-env-01",
            "platform": "YouTube Shorts",
        }
        with patch.dict(os.environ, {"YOUTUBE_TOKEN_CHAN_YT_ENV_01": "ya29.env_token"}):
            token = clipping_publisher.resolve_youtube_token(channel)
            self.assertEqual(token, "ya29.env_token")

    def test_resolve_token_refreshes_via_oauth2_token_endpoint(self):
        """Verifies resolve_youtube_token calls Google OAuth2 token endpoint when refresh_token is present."""
        import clipping_publisher
        from unittest.mock import MagicMock, patch

        cred_file = Path(self.tmpdir) / "refresh_token.json"
        cred_data = {
            "client_id": "test-client-id.apps.googleusercontent.com",
            "client_secret": "test-secret",
            "refresh_token": "1//refresh_token_abc",
        }
        cred_file.write_text(json.dumps(cred_data), encoding="utf-8")

        channel = {
            "id": "chan-yt-refresh",
            "platform": "YouTube Shorts",
            "credentials_path": str(cred_file),
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "access_token": "ya29.refreshed_access_token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            token = clipping_publisher.resolve_youtube_token(channel)
            self.assertEqual(token, "ya29.refreshed_access_token")
            self.assertTrue(mock_urlopen.called)
            req = mock_urlopen.call_args[0][0]
            self.assertEqual(req.full_url, "https://oauth2.googleapis.com/token")

    def test_resolve_token_missing_returns_none(self):
        """Verifies resolve_youtube_token returns None when no credentials exist."""
        import clipping_publisher
        from unittest.mock import patch

        channel = {
            "id": "chan-yt-nonexistent",
            "platform": "YouTube Shorts",
        }
        with patch("pathlib.Path.home", return_value=Path(self.tmpdir)):
            token = clipping_publisher.resolve_youtube_token(channel)
            self.assertIsNone(token)


class TestClippingPublisherSlice10YouTubeApiUpload(unittest.TestCase):
    """Slice 10: Direct upload to YouTube Shorts via YouTube Data API v3."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_yt_upload_")
        self.video_path = Path(self.tmpdir) / "short.mp4"
        self.video_path.write_bytes(b"\x00\x00\x00\x1cftypmp42video_content")
        self.channel = {
            "id": "chan-yt-01",
            "platform": "YouTube Shorts",
            "handle": "@CuriousYT",
            "access_token": "ya29.valid_test_token",
        }

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_upload_youtube_shorts_api_success(self):
        """Verifies upload_youtube_shorts performs multipart API upload and returns video ID and URL."""
        import clipping_publisher
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": "yt_short_123",
            "snippet": {"title": "Viral Hook"},
            "status": {"privacyStatus": "public"},
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            res = clipping_publisher.upload_youtube_shorts(
                channel=self.channel,
                video_path=self.video_path,
                title="Viral Hook",
                description="Best clip ever #shorts",
                privacy_status="public",
            )

            self.assertEqual(res["status"], "published")
            self.assertEqual(res["video_id"], "yt_short_123")
            self.assertEqual(res["post_url"], "https://youtube.com/shorts/yt_short_123")
            self.assertEqual(res["privacy_status"], "public")
            self.assertEqual(res["channel_id"], "chan-yt-01")

            self.assertTrue(mock_urlopen.called)
            req = mock_urlopen.call_args[0][0]
            self.assertIn("https://www.googleapis.com/upload/youtube/v3/videos", req.full_url)
            self.assertEqual(req.headers.get("Authorization"), "Bearer ya29.valid_test_token")
            self.assertTrue(req.headers.get("Content-type", "").startswith("multipart/related; boundary="))
            self.assertIn(b"Viral Hook", req.data)
            self.assertIn(b"Best clip ever #shorts", req.data)
            self.assertIn(b"video_content", req.data)

    def test_upload_youtube_shorts_privacy_override(self):
        """Verifies upload_youtube_shorts accepts unlisted and private overrides."""
        import clipping_publisher
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": "yt_priv_456",
            "snippet": {"title": "Private Clip"},
            "status": {"privacyStatus": "unlisted"},
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            res = clipping_publisher.upload_youtube_shorts(
                channel=self.channel,
                video_path=self.video_path,
                title="Private Clip",
                description="Unlisted preview",
                privacy_status="unlisted",
            )

            self.assertEqual(res["privacy_status"], "unlisted")
            req = mock_urlopen.call_args[0][0]
            self.assertIn(b'"privacyStatus": "unlisted"', req.data)

    def test_upload_youtube_shorts_invalid_privacy_status_raises(self):
        """Verifies upload_youtube_shorts raises ValueError on invalid privacy status."""
        import clipping_publisher

        with self.assertRaises(ValueError) as ctx:
            clipping_publisher.upload_youtube_shorts(
                channel=self.channel,
                video_path=self.video_path,
                title="Bad Status",
                privacy_status="secret",
            )
        self.assertIn("privacy status", str(ctx.exception).lower())

    def test_upload_youtube_shorts_missing_video_raises(self):
        """Verifies upload_youtube_shorts raises FileNotFoundError when video file does not exist."""
        import clipping_publisher

        with self.assertRaises(FileNotFoundError):
            clipping_publisher.upload_youtube_shorts(
                channel=self.channel,
                video_path=Path(self.tmpdir) / "nonexistent.mp4",
                title="Missing Video",
            )


class TestClippingPublisherSlice11BrowserOSNeoFallback(unittest.TestCase):
    """Slice 11: Automated BrowserOS Neo fallback on missing credentials, auth errors, and quota exhaustion."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_yt_fallback_")
        self.video_path = Path(self.tmpdir) / "short.mp4"
        self.video_path.write_bytes(b"\x00\x00\x00\x1cftypmp42video_payload")
        self.channel = {
            "id": "chan-yt-02",
            "platform": "YouTube Shorts",
            "handle": "@CuriousYT2",
        }

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_trigger_browseros_neo_youtube_formats_plan_and_payload(self):
        """Verifies trigger_browseros_neo_youtube formats plan and stages payload targeting YouTube Studio."""
        import clipping_publisher

        res = clipping_publisher.trigger_browseros_neo_youtube(
            channel=self.channel,
            video_path=self.video_path,
            title="Studio Automation Clip",
            description="Testing fallback #shorts",
            reason="missing_credentials",
            privacy_status="unlisted",
        )

        self.assertEqual(res["status"], "fallback_browseros_neo")
        self.assertEqual(res["target_url"], "https://studio.youtube.com")
        self.assertEqual(res["post_url"], "https://studio.youtube.com")
        self.assertEqual(res["privacy_status"], "unlisted")
        self.assertEqual(res["channel_id"], "chan-yt-02")
        self.assertTrue(len(res["automation_plan"]) >= 5)

        # Verify staged payload file exists and has correct content
        payload_file = Path(res["staged_payload"])
        self.assertTrue(payload_file.is_file())
        staged_data = json.loads(payload_file.read_text(encoding="utf-8"))
        self.assertEqual(staged_data["channel_id"], "chan-yt-02")
        self.assertEqual(staged_data["title"], "Studio Automation Clip")
        self.assertEqual(staged_data["target_url"], "https://studio.youtube.com")

    def test_upload_fallback_on_missing_credentials(self):
        """Verifies upload_youtube_shorts automatically triggers BrowserOS Neo fallback when credentials are missing."""
        import clipping_publisher
        from unittest.mock import patch

        with patch("clipping_publisher.resolve_youtube_token", return_value=None):
            res = clipping_publisher.upload_youtube_shorts(
                channel=self.channel,
                video_path=self.video_path,
                title="Missing Token Clip",
                description="Desc",
                fallback_on_error=True,
            )

        self.assertEqual(res["status"], "fallback_browseros_neo")
        self.assertEqual(res["method"], "browseros_neo")
        self.assertIn("credentials", res["reason"].lower())
        self.assertEqual(res["post_url"], "https://studio.youtube.com")

    def test_upload_fallback_on_auth_error_http_401(self):
        """Verifies upload_youtube_shorts automatically triggers fallback on HTTP 401 auth error."""
        import clipping_publisher
        from io import BytesIO
        import urllib.error
        from unittest.mock import patch

        chan = dict(self.channel, access_token="ya29.bad_token")
        err_fp = BytesIO(b'{"error": {"code": 401, "message": "Invalid Credentials", "errors": [{"reason": "authError"}]}}')
        http_err = urllib.error.HTTPError(
            url="https://www.googleapis.com/upload/youtube/v3/videos",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=err_fp,
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            res = clipping_publisher.upload_youtube_shorts(
                channel=chan,
                video_path=self.video_path,
                title="Expired Token Clip",
                fallback_on_error=True,
            )

        self.assertEqual(res["status"], "fallback_browseros_neo")
        self.assertIn("autherror", res["reason"].lower())
        self.assertEqual(res["post_url"], "https://studio.youtube.com")

    def test_upload_fallback_on_quota_exceeded_http_403(self):
        """Verifies upload_youtube_shorts automatically triggers fallback on HTTP 403 quotaExceeded."""
        import clipping_publisher
        from io import BytesIO
        import urllib.error
        from unittest.mock import patch

        chan = dict(self.channel, access_token="ya29.valid_token_but_quota_out")
        err_fp = BytesIO(b'{"error": {"code": 403, "message": "The request cannot be completed because you have exceeded your quota.", "errors": [{"reason": "quotaExceeded"}]}}')
        http_err = urllib.error.HTTPError(
            url="https://www.googleapis.com/upload/youtube/v3/videos",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=err_fp,
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            res = clipping_publisher.upload_youtube_shorts(
                channel=chan,
                video_path=self.video_path,
                title="Quota Out Clip",
                fallback_on_error=True,
            )

        self.assertEqual(res["status"], "fallback_browseros_neo")
        self.assertIn("quotaexceeded", res["reason"].lower())
        self.assertEqual(res["post_url"], "https://studio.youtube.com")

    def test_upload_raises_when_fallback_disabled(self):
        """Verifies upload_youtube_shorts raises typed exceptions when fallback_on_error is False."""
        import clipping_publisher
        from io import BytesIO
        import urllib.error
        from unittest.mock import patch

        chan = dict(self.channel, access_token="ya29.test_token")
        err_fp = BytesIO(b'{"error": {"code": 403, "message": "Quota exceeded", "errors": [{"reason": "quotaExceeded"}]}}')
        http_err = urllib.error.HTTPError(
            url="https://www.googleapis.com/upload/youtube/v3/videos",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=err_fp,
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            with self.assertRaises(clipping_publisher.YouTubeQuotaError):
                clipping_publisher.upload_youtube_shorts(
                    channel=chan,
                    video_path=self.video_path,
                    title="Quota Error No Fallback",
                    fallback_on_error=False,
                )


class TestClippingPublisherSlice12YouTubePortfolioLoggingAndCli(unittest.TestCase):
    """Slice 12: End-to-end integration: channels.json quota logging and CLI publish."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_yt_cli_")
        self.channels_path = Path(self.tmpdir) / "channels.json"
        self.video_path = Path(self.tmpdir) / "test_clip.mp4"
        self.video_path.write_bytes(b"\x00\x00\x00\x1cftypmp42video_bytes_here")

        self.portfolio_data = {
            "version": "1.0.0",
            "workspace_id": "test-yt-cli",
            "channels": [
                {
                    "id": "chan-yt-cli-01",
                    "platform": "YouTube Shorts",
                    "handle": "@YTShortsCli",
                    "account_name": "Cli Brand",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 4,
                        "posts_today": 0,
                    },
                    "access_token": "ya29.valid_cli_token",
                    "post_log": [],
                },
                {
                    "id": "chan-yt-cli-fallback",
                    "platform": "YouTube Shorts",
                    "handle": "@YTRestricted",
                    "account_name": "Fallback Brand",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 4,
                        "posts_today": 0,
                    },
                    "post_log": [],
                },
            ],
        }
        self.channels_path.write_text(json.dumps(self.portfolio_data, indent=2), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_cli(self, args: List[str]) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(SCRIPT_PATH)] + args
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_youtube_upload_logs_to_channels_json(self):
        """Verifies successful upload logs video ID, post URL, and increments posts_today in channels.json."""
        import clipping_publisher
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": "yt_success_789",
            "snippet": {"title": "Logged Clip"},
            "status": {"privacyStatus": "public"},
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = clipping_publisher.publish_clip(
                channels_path=self.channels_path,
                video_path=self.video_path,
                brand_cluster="Cli Brand",
                clip_id="clip-logged-01",
                caption_hook="Logged Hook",
                dry_run=False,
            )

        self.assertEqual(res["status"], "published")
        self.assertEqual(len(res["publication_manifest"]), 1)
        entry = res["publication_manifest"][0]
        self.assertEqual(entry["video_id"], "yt_success_789")
        self.assertEqual(entry["post_url"], "https://youtube.com/shorts/yt_success_789")

        # Verify channels.json updated on disk
        updated_data = json.loads(self.channels_path.read_text(encoding="utf-8"))
        chan = next(c for c in updated_data["channels"] if c["id"] == "chan-yt-cli-01")
        self.assertEqual(chan["posting_cadence"]["posts_today"], 1)
        self.assertTrue(chan["posting_cadence"]["last_post_date"])
        self.assertEqual(len(chan["post_log"]), 1)
        log_item = chan["post_log"][0]
        self.assertEqual(log_item["clip_id"], "clip-logged-01")
        self.assertEqual(log_item["video_id"], "yt_success_789")
        self.assertEqual(log_item["post_url"], "https://youtube.com/shorts/yt_success_789")
        self.assertEqual(log_item["status"], "published")

    def test_youtube_fallback_logs_to_channels_json(self):
        """Verifies BrowserOS Neo fallback logs studio URL and increments posts_today in channels.json."""
        import clipping_publisher
        from unittest.mock import patch

        with patch("clipping_publisher.resolve_youtube_token", return_value=None):
            res = clipping_publisher.publish_clip(
                channels_path=self.channels_path,
                video_path=self.video_path,
                brand_cluster="Fallback Brand",
                clip_id="clip-fallback-01",
                dry_run=False,
            )

        self.assertEqual(res["status"], "staged_browseros_neo")
        self.assertEqual(len(res["publication_manifest"]), 1)
        entry = res["publication_manifest"][0]
        self.assertEqual(entry["status"], "fallback_browseros_neo")
        self.assertEqual(entry["post_url"], "https://studio.youtube.com")

        # Verify channels.json updated on disk
        updated_data = json.loads(self.channels_path.read_text(encoding="utf-8"))
        chan = next(c for c in updated_data["channels"] if c["id"] == "chan-yt-cli-fallback")
        self.assertEqual(chan["posting_cadence"]["posts_today"], 1)
        self.assertEqual(len(chan["post_log"]), 1)
        log_item = chan["post_log"][0]
        self.assertEqual(log_item["clip_id"], "clip-fallback-01")
        self.assertEqual(log_item["post_url"], "https://studio.youtube.com")
        self.assertEqual(log_item["status"], "staged_browseros_neo")

    def test_cli_publish_with_privacy_status(self):
        """Verifies CLI publish accepts --privacy-status unlisted and passes it through."""
        res = self.run_cli([
            "publish",
            "--brand-cluster", "Cli Brand",
            "--channels", str(self.channels_path),
            "--video", str(self.video_path),
            "--privacy-status", "unlisted",
            "--dry-run",
            "--json",
        ])
        self.assertEqual(res.returncode, 0, f"CLI publish failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "allocated")
        yt_entry = data["publication_manifest"][0]
        self.assertEqual(yt_entry.get("privacy_status"), "unlisted")


if __name__ == "__main__":
    unittest.main()
