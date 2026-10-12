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


if __name__ == "__main__":
    unittest.main()
