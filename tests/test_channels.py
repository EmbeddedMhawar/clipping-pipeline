#!/usr/bin/env python3
"""
tests/test_channels.py

Comprehensive test suite for Ticket #11:
- scripts/clipping_channels.py CLI and Python API
- Portfolio registry lifecycle: init, add, audit, daily-tasks, advance-stage, cooldown, log-post, transfer
- ADR 0001 (workspace-level registry)
- ADR 0002 (health-gated warmup advancement)
- ADR 0003 (automated device transfer protocols)
- Schema conformance against references/CHANNEL_PORTFOLIO_SCHEMA.md

Zero external runtime dependencies (Python standard library only).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "clipping_channels.py"
SCHEMA_PATH = REPO_ROOT / "references" / "CHANNEL_PORTFOLIO_SCHEMA.md"

# Import validate_json_schema from test_channel_schema
sys.path.insert(0, str(REPO_ROOT / "tests"))
from test_channel_schema import validate_json_schema


def get_schema() -> Dict[str, Any]:
    content = SCHEMA_PATH.read_text(encoding="utf-8")
    match = re.search(r"```(?:json|jsonc)\s*\n(\{.*?\})\n```", content, re.DOTALL)
    if not match:
        raise ValueError("Could not find JSON schema block in CHANNEL_PORTFOLIO_SCHEMA.md")
    return json.loads(match.group(1))


class TestClippingChannelsRedGreen(unittest.TestCase):
    """Tests for scripts/clipping_channels.py verifying full CLI and API functionality."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_channels_")
        self.schema = get_schema()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_cli(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess:
        """Helper to run scripts/clipping_channels.py with args."""
        cmd = [sys.executable, str(SCRIPT_PATH)] + args
        res = subprocess.run(cmd, capture_output=True, text=True)
        if check and res.returncode != 0:
            raise RuntimeError(
                f"CLI command failed with code {res.returncode}:\n"
                f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}"
            )
        return res

    def test_script_exists_and_is_executable(self):
        """Verifies scripts/clipping_channels.py exists, starts with shebang, and is executable."""
        self.assertTrue(
            SCRIPT_PATH.is_file(),
            f"Expected script to exist at {SCRIPT_PATH}",
        )
        content = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertTrue(
            content.startswith("#!/usr/bin/env python3"),
            "Script must start with #!/usr/bin/env python3",
        )
        self.assertTrue(
            os.access(SCRIPT_PATH, os.X_OK),
            "Script should be executable",
        )

    def test_init_creates_valid_registry(self):
        """Tests 'init' subcommand creates schema-compliant channels.json."""
        res = self.run_cli(["init", "--dir", self.tmpdir])
        self.assertEqual(res.returncode, 0)
        self.assertIn("Initialized channel portfolio registry", res.stdout)

        channels_file = Path(self.tmpdir) / "channels.json"
        self.assertTrue(channels_file.is_file())

        data = json.loads(channels_file.read_text(encoding="utf-8"))
        self.assertEqual(data.get("version"), "1.0.0")
        self.assertEqual(data.get("channels"), [])

        errors = validate_json_schema(data, self.schema)
        self.assertEqual(errors, [], f"channels.json must conform to schema: {errors}")

    def test_init_fails_without_force_if_exists(self):
        """Tests 'init' fails if channels.json exists and --force is not specified."""
        self.run_cli(["init", "--dir", self.tmpdir])
        res = self.run_cli(["init", "--dir", self.tmpdir], check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("already exists", res.stderr + res.stdout)

        # But with --force it succeeds
        res_force = self.run_cli(["init", "--dir", self.tmpdir, "--force"])
        self.assertEqual(res_force.returncode, 0)

    def test_add_channel_defaults_and_validation(self):
        """Tests 'add' subcommand populates Cold Lurker defaults and validates schema."""
        self.run_cli(["init", "--dir", self.tmpdir])

        res = self.run_cli([
            "add",
            "--platform", "TikTok",
            "--handle", "@curiousclips_daily",
            "--dir", self.tmpdir,
        ])
        self.assertEqual(res.returncode, 0)
        self.assertIn("Added channel", res.stdout)

        channels_file = Path(self.tmpdir) / "channels.json"
        data = json.loads(channels_file.read_text(encoding="utf-8"))
        self.assertEqual(len(data["channels"]), 1)
        chan = data["channels"][0]

        self.assertEqual(chan["platform"], "TikTok")
        self.assertEqual(chan["handle"], "@curiousclips_daily")
        self.assertEqual(chan["stage"], "Cold Lurker")
        self.assertEqual(chan["status"], "active")
        self.assertEqual(chan["posting_cadence"]["daily_post_limit"], 0)
        self.assertEqual(chan["posting_cadence"]["posts_today"], 0)
        self.assertEqual(chan["health_gate"]["cleared_health_gate"], False)
        self.assertEqual(chan["device_transfer"]["protocol"], "qr_code")

        errors = validate_json_schema(data, self.schema)
        self.assertEqual(errors, [], f"Added channel must conform to schema: {errors}")

    def test_add_channel_with_custom_id_and_stage(self):
        """Tests 'add' subcommand with custom ID, stage Seeding, and case normalization."""
        self.run_cli(["init", "--dir", self.tmpdir])

        res = self.run_cli([
            "add",
            "--id", "chan-ig-seed-01",
            "--platform", "instagram reels",
            "--handle", "@reels_seed",
            "--stage", "Seeding",
            "--dir", self.tmpdir,
        ])
        self.assertEqual(res.returncode, 0)

        channels_file = Path(self.tmpdir) / "channels.json"
        data = json.loads(channels_file.read_text(encoding="utf-8"))
        chan = data["channels"][0]
        self.assertEqual(chan["id"], "chan-ig-seed-01")
        self.assertEqual(chan["platform"], "Instagram Reels")
        self.assertEqual(chan["stage"], "Seeding")
        self.assertEqual(chan["posting_cadence"]["daily_post_limit"], 1)

        errors = validate_json_schema(data, self.schema)
        self.assertEqual(errors, [])

    def test_add_duplicate_fails(self):
        """Tests 'add' subcommand rejects duplicate IDs or handles."""
        self.run_cli(["init", "--dir", self.tmpdir])
        self.run_cli([
            "add",
            "--id", "chan-01",
            "--platform", "TikTok",
            "--handle", "@test_dup",
            "--dir", self.tmpdir,
        ])
        res = self.run_cli([
            "add",
            "--id", "chan-01",
            "--platform", "YouTube Shorts",
            "--handle", "@another",
            "--dir", self.tmpdir,
        ], check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("already exists", res.stderr + res.stdout)

    def test_audit_subcommand_and_artifact(self):
        """Tests 'audit' subcommand outputs summary and writes artifact file."""
        self.run_cli(["init", "--dir", self.tmpdir])
        self.run_cli(["add", "--platform", "TikTok", "--handle", "@clip1", "--dir", self.tmpdir])
        self.run_cli(["add", "--platform", "YouTube Shorts", "--handle", "@clip2", "--stage", "Mature", "--dir", self.tmpdir])

        artifact_path = Path(self.tmpdir) / "audit_report.md"
        res = self.run_cli([
            "audit",
            "--dir", self.tmpdir,
            "--output-artifact", str(artifact_path),
        ])
        self.assertEqual(res.returncode, 0)
        self.assertIn("Channel Portfolio Audit", res.stdout)
        self.assertTrue(artifact_path.is_file())
        artifact_content = artifact_path.read_text(encoding="utf-8")
        self.assertIn("Channel Portfolio Audit", artifact_content)
        self.assertIn("@clip1", artifact_content)
        self.assertIn("@clip2", artifact_content)

    def test_daily_tasks_text_and_json(self):
        """Tests 'daily-tasks' subcommand in text and JSON mode."""
        self.run_cli(["init", "--dir", self.tmpdir])
        self.run_cli(["add", "--id", "c1", "--platform", "TikTok", "--handle", "@cold", "--dir", self.tmpdir])
        self.run_cli(["add", "--id", "c2", "--platform", "Instagram Reels", "--handle", "@seed", "--stage", "Seeding", "--dir", self.tmpdir])

        res_text = self.run_cli(["daily-tasks", "--dir", self.tmpdir])
        self.assertEqual(res_text.returncode, 0)
        self.assertIn("Daily Tasks", res_text.stdout)
        self.assertIn("@cold", res_text.stdout)
        self.assertIn("@seed", res_text.stdout)

        res_json = self.run_cli(["daily-tasks", "--dir", self.tmpdir, "--json"])
        self.assertEqual(res_json.returncode, 0)
        tasks = json.loads(res_json.stdout)
        self.assertIsInstance(tasks, list)
        self.assertEqual(len(tasks), 2)
        cold_task = next(t for t in tasks if t["id"] == "c1")
        self.assertEqual(cold_task["stage"], "Cold Lurker")
        self.assertEqual(cold_task["daily_post_limit"], 0)
        self.assertTrue(len(cold_task["actions"]) > 0)

    def test_advance_stage_cold_lurker_time_gate(self):
        """Tests advance-stage enforces 3 days in Cold Lurker unless --force is used."""
        self.run_cli(["init", "--dir", self.tmpdir])
        self.run_cli(["add", "--id", "c1", "--platform", "TikTok", "--handle", "@cold", "--dir", self.tmpdir])

        # Without force, freshly created channel cannot advance
        res_fail = self.run_cli(["advance-stage", "--id", "c1", "--dir", self.tmpdir], check=False)
        self.assertNotEqual(res_fail.returncode, 0)
        self.assertIn("minimum 3 days", res_fail.stderr + res_fail.stdout)

        # With force, succeeds
        res_force = self.run_cli(["advance-stage", "--id", "c1", "--force", "--dir", self.tmpdir])
        self.assertEqual(res_force.returncode, 0)

        channels_file = Path(self.tmpdir) / "channels.json"
        data = json.loads(channels_file.read_text(encoding="utf-8"))
        chan = data["channels"][0]
        self.assertEqual(chan["stage"], "Seeding")
        self.assertEqual(chan["posting_cadence"]["daily_post_limit"], 1)

    def test_advance_stage_cold_lurker_after_3_days(self):
        """Tests advance-stage succeeds when stage_entered_at is >= 3 days ago without --force."""
        self.run_cli(["init", "--dir", self.tmpdir])
        self.run_cli(["add", "--id", "c1", "--platform", "TikTok", "--handle", "@cold", "--dir", self.tmpdir])

        # Modify stage_entered_at to 4 days ago
        channels_file = Path(self.tmpdir) / "channels.json"
        data = json.loads(channels_file.read_text(encoding="utf-8"))
        four_days_ago = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        data["channels"][0]["stage_entered_at"] = four_days_ago
        channels_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        res = self.run_cli(["advance-stage", "--id", "c1", "--dir", self.tmpdir])
        self.assertEqual(res.returncode, 0)
        data = json.loads(channels_file.read_text(encoding="utf-8"))
        self.assertEqual(data["channels"][0]["stage"], "Seeding")

    def test_advance_stage_health_gate_seeding_to_rampup(self):
        """Tests Health Gate (>= 200 views) to leave Seeding."""
        self.run_cli(["init", "--dir", self.tmpdir])
        self.run_cli(["add", "--id", "c1", "--platform", "TikTok", "--handle", "@seed", "--stage", "Seeding", "--dir", self.tmpdir])

        # Insufficient views (< 200) fails without --force
        res_fail = self.run_cli(["advance-stage", "--id", "c1", "--views", "120", "--dir", self.tmpdir], check=False)
        self.assertNotEqual(res_fail.returncode, 0)
        self.assertIn("Health Gate", res_fail.stderr + res_fail.stdout)

        # Views >= 200 clears Health Gate and advances to Ramp-Up
        res_ok = self.run_cli(["advance-stage", "--id", "c1", "--views", "285", "--dir", self.tmpdir])
        self.assertEqual(res_ok.returncode, 0)

        channels_file = Path(self.tmpdir) / "channels.json"
        data = json.loads(channels_file.read_text(encoding="utf-8"))
        chan = data["channels"][0]
        self.assertEqual(chan["stage"], "Ramp-Up")
        self.assertEqual(chan["health_gate"]["cleared_health_gate"], True)
        self.assertEqual(chan["health_gate"]["latest_views"], 285)
        self.assertEqual(chan["posting_cadence"]["daily_post_limit"], 3)

        # Ramp-Up to Mature
        res_mature = self.run_cli(["advance-stage", "--id", "c1", "--dir", self.tmpdir])
        self.assertEqual(res_mature.returncode, 0)
        data = json.loads(channels_file.read_text(encoding="utf-8"))
        self.assertEqual(data["channels"][0]["stage"], "Mature")
        self.assertEqual(data["channels"][0]["posting_cadence"]["daily_post_limit"], 4)

    def test_cooldown_subcommand(self):
        """Tests 'cooldown' triggers 72h suppression resting state."""
        self.run_cli(["init", "--dir", self.tmpdir])
        self.run_cli(["add", "--id", "c1", "--platform", "TikTok", "--handle", "@suppressed", "--stage", "Seeding", "--dir", self.tmpdir])

        res = self.run_cli(["cooldown", "--id", "c1", "--hours", "72", "--dir", self.tmpdir])
        self.assertEqual(res.returncode, 0)

        channels_file = Path(self.tmpdir) / "channels.json"
        data = json.loads(channels_file.read_text(encoding="utf-8"))
        chan = data["channels"][0]

        self.assertEqual(chan["stage"], "Account Cooldown")
        self.assertEqual(chan["status"], "cooldown")
        self.assertEqual(chan["posting_cadence"]["daily_post_limit"], 0)
        self.assertEqual(chan["health_gate"]["suppression_detected"], True)
        self.assertEqual(chan["cooldown"]["in_cooldown"], True)
        self.assertEqual(chan["cooldown"]["cooldown_duration_hours"], 72)
        self.assertIn("cooldown_until", chan["cooldown"])

        errors = validate_json_schema(data, self.schema)
        self.assertEqual(errors, [])

    def test_log_post_subcommand_and_cadence_enforcement(self):
        """Tests 'log-post' updates posting counters, logs entries, and enforces daily limits."""
        self.run_cli(["init", "--dir", self.tmpdir])
        self.run_cli(["add", "--id", "c1", "--platform", "TikTok", "--handle", "@poster", "--stage", "Seeding", "--dir", self.tmpdir])

        # Seeding limit is 1
        res = self.run_cli([
            "log-post",
            "--id", "c1",
            "--clip-id", "clip-001",
            "--project", "campaign-alpha",
            "--views", "350",
            "--post-url", "https://tiktok.com/@poster/123",
            "--dir", self.tmpdir,
        ])
        self.assertEqual(res.returncode, 0)

        channels_file = Path(self.tmpdir) / "channels.json"
        data = json.loads(channels_file.read_text(encoding="utf-8"))
        chan = data["channels"][0]
        self.assertEqual(chan["posting_cadence"]["posts_today"], 1)
        self.assertEqual(chan["health_gate"]["latest_views"], 350)
        self.assertEqual(len(chan["post_log"]), 1)
        self.assertEqual(chan["post_log"][0]["clip_id"], "clip-001")

        # Second post exceeds limit (1) -> should fail without --force
        res_exceed = self.run_cli([
            "log-post",
            "--id", "c1",
            "--clip-id", "clip-002",
            "--dir", self.tmpdir,
        ], check=False)
        self.assertNotEqual(res_exceed.returncode, 0)
        self.assertIn("Daily post limit", res_exceed.stderr + res_exceed.stdout)

        # But with --force, it logs
        res_force = self.run_cli([
            "log-post",
            "--id", "c1",
            "--clip-id", "clip-002",
            "--force",
            "--dir", self.tmpdir,
        ])
        self.assertEqual(res_force.returncode, 0)

        data = json.loads(channels_file.read_text(encoding="utf-8"))
        self.assertEqual(data["channels"][0]["posting_cadence"]["posts_today"], 2)

        errors = validate_json_schema(data, self.schema)
        self.assertEqual(errors, [])

    def test_transfer_subcommand_methods(self):
        """Tests 'transfer' subcommand across local_qr, adb_push, cloud_folder, and webhook."""
        # Create a mock rendered clip file
        clip_file = Path(self.tmpdir) / "test_clip.mp4"
        clip_file.write_bytes(b"dummy mp4 content")

        # Method 1: cloud_folder
        cloud_dest = Path(self.tmpdir) / "cloud_dest"
        cloud_dest.mkdir()
        res_cloud = self.run_cli([
            "transfer",
            "--clip", str(clip_file),
            "--method", "cloud_folder",
            "--target", str(cloud_dest),
        ])
        self.assertEqual(res_cloud.returncode, 0)
        self.assertTrue((cloud_dest / "test_clip.mp4").is_file())

        # Method 2: local_qr (dry-run or info mode)
        res_qr = self.run_cli([
            "transfer",
            "--clip", str(clip_file),
            "--method", "local_qr",
            "--dry-run",
        ])
        self.assertEqual(res_qr.returncode, 0)
        self.assertIn("QR", res_qr.stdout)

        # Method 3: adb_push (dry-run mode)
        res_adb = self.run_cli([
            "transfer",
            "--clip", str(clip_file),
            "--method", "adb_push",
            "--target", "/sdcard/DCIM/Camera/",
            "--dry-run",
        ])
        self.assertEqual(res_adb.returncode, 0)
        self.assertIn("adb push", res_adb.stdout)

        # Method 4: webhook (dry-run mode)
        res_webhook = self.run_cli([
            "transfer",
            "--clip", str(clip_file),
            "--method", "webhook",
            "--target", "https://api.telegram.org/bot123/sendVideo",
            "--dry-run",
        ])
        self.assertEqual(res_webhook.returncode, 0)
        self.assertIn("webhook", res_webhook.stdout.lower())

    def test_transfer_using_channel_config(self):
        """Tests 'transfer' looks up channel's device_transfer protocol from channels.json."""
        self.run_cli(["init", "--dir", self.tmpdir])
        self.run_cli([
            "add",
            "--id", "chan-sync",
            "--platform", "TikTok",
            "--handle", "@sync",
            "--dir", self.tmpdir,
        ])

        # Configure cloud_sync for this channel
        channels_file = Path(self.tmpdir) / "channels.json"
        cloud_dest = Path(self.tmpdir) / "phone_sync"
        cloud_dest.mkdir()
        data = json.loads(channels_file.read_text(encoding="utf-8"))
        data["channels"][0]["device_transfer"] = {
            "protocol": "cloud_sync",
            "target": str(cloud_dest),
            "enabled": True,
        }
        channels_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        clip_file = Path(self.tmpdir) / "clip.mp4"
        clip_file.write_bytes(b"sample video")

        res = self.run_cli([
            "transfer",
            "--clip", str(clip_file),
            "--channel", "chan-sync",
            "--dir", self.tmpdir,
        ])
        self.assertEqual(res.returncode, 0)
        self.assertTrue((cloud_dest / "clip.mp4").is_file())


if __name__ == "__main__":
    unittest.main()
