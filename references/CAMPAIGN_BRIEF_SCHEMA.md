# Campaign Brief Schema Specification (v1.0.0)

> **File**: `references/CAMPAIGN_BRIEF_SCHEMA.md`  
> **Source**: Antigravity Short-Form Clipping Pipeline Plugin  
> **Compliance**: Cole Corcoran AI Clipping Framework & Paid Campaign Rules

This document defines the authoritative data contract for normalized campaign briefs (`campaign_brief.json`). All raw briefs ingested from markdown files, user prompt text, Notion pages, or URLs must be parsed or defaulted to conform to this specification before being ingested into `.clipping_state.json`.

---

## 1. Schema Hierarchy & Fields

### Root Level
- `version` (`string`, required): Contract version, e.g. `"1.0.0"`.
- `campaign` (`object`, required): Identity, sourcing, economics, and distribution scope.
- `global_rules` (`object`, required): Universal editing and compliance constraints applied across all clips.
- `platform_overrides` (`object`, optional): Platform-specific distribution and metadata requirements.
- `defaults_applied` (`array of string`, optional): Audit trail of Cole Corcoran Tier-1 defaults injected when absent from raw input.

---

### 2. `campaign` Object

| Field | Type | Required | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `title` | `string` | Yes | Human-facing campaign name | `"N3on x MPJ Clipping Campaign"` |
| `client` | `string` | Yes | Creator, brand, or host identity | `"Curious Mike"` |
| `project` | `string` | Yes | Kebab-case project slug | `"n3on-x-mpj"` |
| `source_video` | `object` | Yes | Source footage metadata | See sub-fields below |
| `economics` | `object` | Yes | Payout, minimums, and caps | See sub-fields below |
| `platforms` | `array[string]` | Yes | Target distribution channels | `["TikTok", "Instagram Reels", "YouTube Shorts"]` |
| `daily_post_limit` | `integer` | No | Max posts per account per day | `4` |

#### `source_video` Sub-fields:
- `url` (`string`): YouTube/VOD URL, e.g. `"https://www.youtube.com/watch?v=GfVYVEPSLIM"`.
- `channel` (`string`): Host/channel handle, e.g. `"@mpj"`.
- `duration` (`string`): Raw footage duration, e.g. `"1:36:59"`.

#### `economics` Sub-fields:
- `rate_per_1k_views` (`number`): USD payout per 1,000 verified views, e.g. `1.0`.
- `min_payout_views` (`integer`): View count threshold required to unlock payout, e.g. `2000`.
- `max_payout_views_per_clip` (`integer`): Maximum rewarded views per clip, e.g. `300000`.
- `max_dollar_per_clip` (`number`): Earnings ceiling per clip, e.g. `300.0`.

---

### 3. `global_rules` Object

Enforces Cole Corcoran viral video architecture and anti-disqualification rules.

| Field | Type | Description | Default Applied If Omitted |
| :--- | :--- | :--- | :--- |
| `duration` | `object` | Timing constraints: `{"min_seconds": 20.0, "max_seconds": 60.0, "ideal_min": 25.0, "ideal_max": 45.0}` | `[Default Applied]` 25s–45s |
| `tier1_geo_min_pct` | `number` | Minimum percentage of viewers from US, CA, UK combined | `40.0` `[Default Applied]` |
| `engagement_min_pct` | `number` | Minimum engagement ratio `(Likes + Comments) / Views` | `1.0` `[Default Applied]` |
| `watermark` | `object` | Watermark parameters: `{"required": true, "asset_path": "assets/watermark_yt_mpj.png", "persistent_entire_clip": true, "banned_corners": true}` | `[Default Applied]` |
| `caption_closers` | `array[string]`| Approved closers directing viewers to full episode (12 approved options) | `[Default Applied]` |
| `audio` | `object` | Audio standards: `{"zero_background_music": true, "zero_phonk": true, "loudness_target_lufs": -14.0}` | `[Default Applied]` -14 LUFS |
| `prohibited_edits` | `array[string]`| Banned visual styles: `["aura", "glow", "skull", "ai_avatar", "ai_broll", "opus_clips"]` | `[Default Applied]` |
| `single_post_per_edit` | `boolean` | True if each edit can only be submitted once across all accounts | `true` `[Default Applied]` |

---

### 4. `platform_overrides` Object

Accounts for platform-specific security policies, trust scoring, and handles.

- `youtube_shorts`:
  - `api_upload_allowed` (`boolean`): `true` (safe for automated upload via YouTube Data API v3).
  - `handle_format` (`string`): `"tagged"` (e.g. `@mpj` tagged in caption/description).
  - `bio_verification_code_required` (`boolean`): `true` (Whop channel bio verification code).
- `tiktok`:
  - `api_upload_allowed` (`boolean`): `false` (API uploads trigger 0-view shadowban; manual mobile only).
  - `handle_format` (`string`): `"plain_text"` (do NOT tag handle directly to avoid spam flags).
  - `bio_affiliate_disclaimer` (`string`): Fan page disclaimer text.
- `instagram_reels`:
  - `api_upload_allowed` (`boolean`): `false` (manual mobile posting required).
  - `handle_format` (`string`): `"plain_text"`.
  - `bio_affiliate_disclaimer` (`string`): Fan page disclaimer text.

---

### 5. `defaults_applied` Array

An array of strings recording every default applied when the input was silent.  
Example entries:
- `"duration: 25s–45s (bounds 20s–60s) [Default Applied]"`
- `"audio: normalized to -14 LUFS, zero background music beds [Default Applied]"`
- `"tier1_geo_min_pct: 40.0% US/CA/UK [Default Applied]"`
- `"engagement_min_pct: 1.0% [Default Applied]"`
- `"watermark: persistent, banned in 4 corners [Default Applied]"`
- `"caption_closers: 12 approved rotated closers [Default Applied]"`

---

## 6. Authoritative JSON Schema

The following JSON Schema validates any `campaign_brief.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "CampaignBrief",
  "description": "Normalized campaign brief for Antigravity short-form video clipping pipeline.",
  "type": "object",
  "required": ["version", "campaign", "global_rules"],
  "properties": {
    "version": {
      "type": "string",
      "default": "1.0.0"
    },
    "campaign": {
      "type": "object",
      "required": ["title", "client", "project", "source_video", "economics", "platforms"],
      "properties": {
        "title": { "type": "string" },
        "client": { "type": "string" },
        "project": { "type": "string" },
        "source_video": {
          "type": "object",
          "properties": {
            "url": { "type": "string" },
            "channel": { "type": "string" },
            "duration": { "type": "string" }
          }
        },
        "economics": {
          "type": "object",
          "required": ["rate_per_1k_views", "min_payout_views", "max_dollar_per_clip"],
          "properties": {
            "rate_per_1k_views": { "type": "number", "minimum": 0 },
            "min_payout_views": { "type": "integer", "minimum": 0 },
            "max_payout_views_per_clip": { "type": "integer", "minimum": 0 },
            "max_dollar_per_clip": { "type": "number", "minimum": 0 }
          }
        },
        "platforms": {
          "type": "array",
          "items": { "type": "string" }
        },
        "daily_post_limit": {
          "type": "integer",
          "default": 4
        }
      }
    },
    "global_rules": {
      "type": "object",
      "required": ["duration", "tier1_geo_min_pct", "engagement_min_pct", "watermark", "audio", "caption_closers"],
      "properties": {
        "duration": {
          "type": "object",
          "properties": {
            "min_seconds": { "type": "number", "default": 20.0 },
            "max_seconds": { "type": "number", "default": 60.0 },
            "ideal_min": { "type": "number", "default": 25.0 },
            "ideal_max": { "type": "number", "default": 45.0 }
          }
        },
        "tier1_geo_min_pct": {
          "type": "number",
          "default": 40.0
        },
        "engagement_min_pct": {
          "type": "number",
          "default": 1.0
        },
        "watermark": {
          "type": "object",
          "required": ["required"],
          "properties": {
            "required": { "type": "boolean", "default": true },
            "asset_path": { "type": "string" },
            "persistent_entire_clip": { "type": "boolean", "default": true },
            "banned_corners": { "type": "boolean", "default": true }
          }
        },
        "caption_closers": {
          "type": "array",
          "items": { "type": "string" }
        },
        "audio": {
          "type": "object",
          "properties": {
            "zero_background_music": { "type": "boolean", "default": true },
            "zero_phonk": { "type": "boolean", "default": true },
            "loudness_target_lufs": { "type": "number", "default": -14.0 }
          }
        },
        "prohibited_edits": {
          "type": "array",
          "items": { "type": "string" },
          "default": ["aura", "glow", "skull", "ai_avatar", "ai_broll", "opus_clips"]
        },
        "single_post_per_edit": {
          "type": "boolean",
          "default": true
        }
      }
    },
    "platform_overrides": {
      "type": "object",
      "properties": {
        "youtube_shorts": {
          "type": "object",
          "properties": {
            "api_upload_allowed": { "type": "boolean", "default": true },
            "handle_format": { "type": "string", "default": "tagged" },
            "bio_verification_code_required": { "type": "boolean", "default": true }
          }
        },
        "tiktok": {
          "type": "object",
          "properties": {
            "api_upload_allowed": { "type": "boolean", "default": false },
            "handle_format": { "type": "string", "default": "plain_text" },
            "bio_affiliate_disclaimer": { "type": "string" }
          }
        },
        "instagram_reels": {
          "type": "object",
          "properties": {
            "api_upload_allowed": { "type": "boolean", "default": false },
            "handle_format": { "type": "string", "default": "plain_text" },
            "bio_affiliate_disclaimer": { "type": "string" }
          }
        }
      }
    },
    "defaults_applied": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```
