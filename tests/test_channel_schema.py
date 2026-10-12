#!/usr/bin/env python3
"""
tests/test_channel_schema.py

Test suite for Ticket #10:
- references/CHANNEL_PORTFOLIO_SCHEMA.md (JSON schema and documentation)
- Domain standards validation for workspace-level channel portfolio registry (channels.json)
- Validation of valid and invalid channel portfolio fixtures against schema

Zero external runtime dependencies (Python standard library only).
"""

import json
import re
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCES_DIR = REPO_ROOT / "references"


def validate_json_schema(instance: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """
    Validates a JSON instance against a JSON schema definition.
    Zero external dependencies (pure Python standard library).
    Supports: type, required, properties, items, enum, minimum, maximum.
    """
    errors: List[str] = []

    # Type validation
    expected_type = schema.get("type")
    if expected_type:
        type_checks = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: (isinstance(v, (int, float)) and not isinstance(v, bool)),
            "boolean": lambda v: isinstance(v, bool),
        }
        check_fn = type_checks.get(expected_type)
        if check_fn and not check_fn(instance):
            errors.append(f"{path}: expected type '{expected_type}', got '{type(instance).__name__}'")
            return errors

    # Enum validation
    if "enum" in schema:
        allowed = schema["enum"]
        if instance not in allowed:
            errors.append(f"{path}: value '{instance}' not in allowed enum {allowed}")

    # Numeric bounds
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: value {instance} is less than minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: value {instance} is greater than maximum {schema['maximum']}")

    # Object validation
    if isinstance(instance, dict):
        required_fields = schema.get("required", [])
        for req in required_fields:
            if req not in instance:
                errors.append(f"{path}: missing required property '{req}'")

        properties = schema.get("properties", {})
        for prop_name, prop_val in instance.items():
            if prop_name in properties:
                prop_schema = properties[prop_name]
                prop_errors = validate_json_schema(prop_val, prop_schema, f"{path}.{prop_name}")
                errors.extend(prop_errors)

    # Array validation
    if isinstance(instance, list):
        items_schema = schema.get("items")
        if items_schema:
            for idx, item in enumerate(instance):
                item_errors = validate_json_schema(item, items_schema, f"{path}[{idx}]")
                errors.extend(item_errors)

    return errors


class TestChannelPortfolioSchemaDocument(unittest.TestCase):
    """Verifies references/CHANNEL_PORTFOLIO_SCHEMA.md exists and defines valid schema."""

    def setUp(self):
        self.schema_doc = REFERENCES_DIR / "CHANNEL_PORTFOLIO_SCHEMA.md"

    def test_schema_file_exists(self):
        self.assertTrue(
            self.schema_doc.is_file(),
            f"Expected schema doc at {self.schema_doc}",
        )

    def test_schema_contains_valid_json_schema_block(self):
        content = self.schema_doc.read_text(encoding="utf-8")
        # Extract json code block
        match = re.search(r"```(?:json|jsonc)\s*\n(\{.*?\})\n```", content, re.DOTALL)
        self.assertIsNotNone(
            match, "CHANNEL_PORTFOLIO_SCHEMA.md must contain a JSON schema code block"
        )
        schema_json = json.loads(match.group(1))
        self.assertIn("$schema", schema_json)
        self.assertEqual(schema_json.get("type"), "object")
        properties = schema_json.get("properties", {})
        self.assertIn("version", properties)
        self.assertIn("channels", properties)
        self.assertIn("updated_at", properties)

        # Validate channel items schema properties
        channels_schema = properties["channels"]
        self.assertEqual(channels_schema.get("type"), "array")
        item_schema = channels_schema.get("items", {})
        item_props = item_schema.get("properties", {})
        self.assertIn("id", item_props)
        self.assertIn("platform", item_props)
        self.assertIn("handle", item_props)
        self.assertIn("stage", item_props)
        self.assertIn("status", item_props)
        self.assertIn("posting_cadence", item_props)
        self.assertIn("health_gate", item_props)
        self.assertIn("cooldown", item_props)
        self.assertIn("device_transfer", item_props)

    def test_schema_documents_domain_standards(self):
        content = self.schema_doc.read_text(encoding="utf-8")
        required_terms = [
            "Cold Lurker",
            "Seeding",
            "Ramp-Up",
            "Mature",
            "Account Cooldown",
            "health_gate",
            "200",
            "500",
            "shadowban",
            "posting_cadence",
            "daily_post_limit",
            "device_transfer",
            "qr_code",
            "adb_push",
            "telegram_dispatch",
            "cloud_sync",
            "channels.json",
        ]
        for term in required_terms:
            self.assertIn(
                term.lower(),
                content.lower(),
                f"CHANNEL_PORTFOLIO_SCHEMA.md must document domain term '{term}'",
            )


class TestChannelPortfolioSchemaValidation(unittest.TestCase):
    """Validates sample valid and invalid fixtures against the authoritative schema."""

    def setUp(self):
        self.schema_doc = REFERENCES_DIR / "CHANNEL_PORTFOLIO_SCHEMA.md"
        if not self.schema_doc.is_file():
            self.skipTest("CHANNEL_PORTFOLIO_SCHEMA.md does not exist yet (TDD Red phase)")

        content = self.schema_doc.read_text(encoding="utf-8")
        match = re.search(r"```(?:json|jsonc)\s*\n(\{.*?\})\n```", content, re.DOTALL)
        if not match:
            self.skipTest("No JSON schema block found in CHANNEL_PORTFOLIO_SCHEMA.md")
        self.schema = json.loads(match.group(1))

    def test_valid_minimal_portfolio(self):
        minimal_fixture = {
            "version": "1.0.0",
            "updated_at": "2026-10-12T12:00:00Z",
            "channels": [],
        }
        errors = validate_json_schema(minimal_fixture, self.schema)
        self.assertEqual(errors, [], f"Minimal fixture should be valid: {errors}")

    def test_valid_comprehensive_portfolio_fixture(self):
        comprehensive_fixture = {
            "version": "1.0.0",
            "updated_at": "2026-10-12T12:00:00Z",
            "workspace_id": "default-workspace",
            "default_device_transfer": {
                "protocol": "qr_code",
                "target": "http://192.168.1.50:8080",
                "enabled": True,
            },
            "channels": [
                {
                    "id": "chan-tiktok-01",
                    "platform": "TikTok",
                    "handle": "@curiousclips_daily",
                    "account_name": "Curious Mike Clips #1",
                    "creation_date": "2026-10-01",
                    "stage": "Cold Lurker",
                    "status": "active",
                    "stage_entered_at": "2026-10-01T00:00:00Z",
                    "posting_cadence": {
                        "daily_post_limit": 0,
                        "posts_today": 0,
                        "last_post_date": "",
                        "min_post_spacing_hours": 0.0,
                    },
                    "health_gate": {
                        "cleared_health_gate": False,
                        "min_views_threshold": 200,
                        "max_views_threshold": 500,
                        "latest_views": 0,
                        "consecutive_valid_posts": 0,
                        "suppression_detected": False,
                    },
                    "cooldown": {
                        "in_cooldown": False,
                        "cooldown_duration_hours": 72,
                    },
                    "device_transfer": {
                        "protocol": "qr_code",
                        "target": "http://192.168.1.50:8080",
                        "enabled": True,
                    },
                    "warmup_protocol": {
                        "daily_actions": ["browse_niche_feed", "like_relevant_videos"],
                        "niche_keywords": ["podcast", "motivation", "clips"],
                        "browsing_minutes_per_day": 30,
                        "target_interactions_per_day": 10,
                    },
                    "post_log": [],
                },
                {
                    "id": "chan-tiktok-02",
                    "platform": "TikTok",
                    "handle": "@curiousmike_reels",
                    "account_name": "Curious Mike Clips #2",
                    "creation_date": "2026-09-20",
                    "stage": "Seeding",
                    "status": "active",
                    "stage_entered_at": "2026-10-05T00:00:00Z",
                    "posting_cadence": {
                        "daily_post_limit": 1,
                        "posts_today": 1,
                        "last_post_date": "2026-10-12T09:30:00Z",
                        "min_post_spacing_hours": 4.0,
                    },
                    "health_gate": {
                        "cleared_health_gate": False,
                        "min_views_threshold": 200,
                        "max_views_threshold": 500,
                        "latest_views": 320,
                        "consecutive_valid_posts": 1,
                        "suppression_detected": False,
                    },
                    "cooldown": {
                        "in_cooldown": False,
                        "cooldown_duration_hours": 72,
                    },
                    "device_transfer": {
                        "protocol": "adb_push",
                        "target": "emulator-5554:/sdcard/DCIM/Camera/",
                        "enabled": True,
                    },
                    "post_log": [
                        {
                            "clip_id": "clip-001",
                            "project": "n3on-x-mpj",
                            "timestamp": "2026-10-12T09:30:00Z",
                            "views": 320,
                            "post_url": "https://www.tiktok.com/@curiousmike_reels/video/123",
                        }
                    ],
                },
                {
                    "id": "chan-ig-01",
                    "platform": "Instagram Reels",
                    "handle": "@curiousmike_shorts",
                    "account_name": "Curious Mike IG",
                    "creation_date": "2026-09-01",
                    "stage": "Ramp-Up",
                    "status": "active",
                    "stage_entered_at": "2026-10-01T00:00:00Z",
                    "posting_cadence": {
                        "daily_post_limit": 3,
                        "posts_today": 2,
                        "last_post_date": "2026-10-12T11:00:00Z",
                        "min_post_spacing_hours": 2.5,
                    },
                    "health_gate": {
                        "cleared_health_gate": True,
                        "min_views_threshold": 200,
                        "max_views_threshold": 500,
                        "latest_views": 1250,
                        "consecutive_valid_posts": 5,
                        "suppression_detected": False,
                    },
                    "device_transfer": {
                        "protocol": "telegram_dispatch",
                        "target": "@MyPhoneTransferBot",
                        "enabled": True,
                    },
                    "post_log": [],
                },
                {
                    "id": "chan-yt-01",
                    "platform": "YouTube Shorts",
                    "handle": "@CuriousMikeShorts",
                    "account_name": "Curious Mike YT Shorts",
                    "creation_date": "2026-08-01",
                    "stage": "Mature",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": 4,
                        "posts_today": 3,
                        "last_post_date": "2026-10-12T10:15:00Z",
                        "min_post_spacing_hours": 2.0,
                    },
                    "health_gate": {
                        "cleared_health_gate": True,
                        "latest_views": 8500,
                        "suppression_detected": False,
                    },
                    "device_transfer": {
                        "protocol": "cloud_sync",
                        "target": "/home/mhawar/Nextcloud/Clips/",
                        "enabled": True,
                    },
                    "post_log": [],
                },
                {
                    "id": "chan-tiktok-03",
                    "platform": "TikTok",
                    "handle": "@curious_temp_pause",
                    "creation_date": "2026-10-05",
                    "stage": "Account Cooldown",
                    "status": "cooldown",
                    "posting_cadence": {
                        "daily_post_limit": 0,
                        "posts_today": 0,
                    },
                    "health_gate": {
                        "cleared_health_gate": False,
                        "latest_views": 0,
                        "suppression_detected": True,
                    },
                    "cooldown": {
                        "in_cooldown": True,
                        "triggered_at": "2026-10-11T12:00:00Z",
                        "cooldown_until": "2026-10-14T12:00:00Z",
                        "cooldown_duration_hours": 72,
                        "reason": "0-view shadowban detected; resting 72 hours",
                    },
                    "device_transfer": {
                        "protocol": "qr_code",
                    },
                },
            ],
        }
        errors = validate_json_schema(comprehensive_fixture, self.schema)
        self.assertEqual(errors, [], f"Comprehensive fixture should be valid: {errors}")

    def test_invalid_root_missing_required(self):
        invalid_fixture = {
            "version": "1.0.0",
            # missing "channels"
        }
        errors = validate_json_schema(invalid_fixture, self.schema)
        self.assertTrue(any("missing required property 'channels'" in e for e in errors))

    def test_invalid_channel_missing_required_fields(self):
        invalid_fixture = {
            "version": "1.0.0",
            "channels": [
                {
                    # missing id, platform, handle, stage, status
                    "account_name": "Incomplete Account"
                }
            ],
        }
        errors = validate_json_schema(invalid_fixture, self.schema)
        self.assertTrue(any("missing required property 'id'" in e for e in errors))
        self.assertTrue(any("missing required property 'platform'" in e for e in errors))
        self.assertTrue(any("missing required property 'handle'" in e for e in errors))
        self.assertTrue(any("missing required property 'stage'" in e for e in errors))
        self.assertTrue(any("missing required property 'status'" in e for e in errors))

    def test_invalid_lifecycle_stage(self):
        invalid_fixture = {
            "version": "1.0.0",
            "channels": [
                {
                    "id": "chan-01",
                    "platform": "TikTok",
                    "handle": "@test",
                    "stage": "Viral Mode",  # Invalid stage
                    "status": "active",
                }
            ],
        }
        errors = validate_json_schema(invalid_fixture, self.schema)
        self.assertTrue(any("not in allowed enum" in e for e in errors))

    def test_invalid_platform(self):
        invalid_fixture = {
            "version": "1.0.0",
            "channels": [
                {
                    "id": "chan-01",
                    "platform": "Twitter",  # Invalid platform
                    "handle": "@test",
                    "stage": "Cold Lurker",
                    "status": "active",
                }
            ],
        }
        errors = validate_json_schema(invalid_fixture, self.schema)
        self.assertTrue(any("not in allowed enum" in e for e in errors))

    def test_invalid_status(self):
        invalid_fixture = {
            "version": "1.0.0",
            "channels": [
                {
                    "id": "chan-01",
                    "platform": "TikTok",
                    "handle": "@test",
                    "stage": "Cold Lurker",
                    "status": "disqualified",  # Invalid status
                }
            ],
        }
        errors = validate_json_schema(invalid_fixture, self.schema)
        self.assertTrue(any("not in allowed enum" in e for e in errors))

    def test_invalid_device_transfer_protocol(self):
        invalid_fixture = {
            "version": "1.0.0",
            "channels": [
                {
                    "id": "chan-01",
                    "platform": "TikTok",
                    "handle": "@test",
                    "stage": "Cold Lurker",
                    "status": "active",
                    "device_transfer": {
                        "protocol": "bluetooth",  # Invalid protocol
                    },
                }
            ],
        }
        errors = validate_json_schema(invalid_fixture, self.schema)
        self.assertTrue(any("not in allowed enum" in e for e in errors))

    def test_invalid_negative_counts(self):
        invalid_fixture = {
            "version": "1.0.0",
            "channels": [
                {
                    "id": "chan-01",
                    "platform": "TikTok",
                    "handle": "@test",
                    "stage": "Cold Lurker",
                    "status": "active",
                    "posting_cadence": {
                        "daily_post_limit": -1,  # Invalid negative limit
                        "posts_today": 0,
                    },
                }
            ],
        }
        errors = validate_json_schema(invalid_fixture, self.schema)
        self.assertTrue(any("less than minimum" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
