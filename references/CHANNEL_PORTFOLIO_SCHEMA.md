# Channel Portfolio Schema Specification (v1.0.0)

> **File**: `references/CHANNEL_PORTFOLIO_SCHEMA.md`  
> **Source**: Antigravity Short-Form Clipping Pipeline Plugin  
> **Architecture Decision Records**:  
> - [ADR 0001: Workspace-Level Channel Portfolio Registry](../docs/adr/0001-workspace-level-channel-portfolio-registry.md)  
> - [ADR 0002: Health-Gated Channel Warmup Advancement](../docs/adr/0002-health-gated-warmup-advancement.md)  
> - [ADR 0003: Automated Device Delivery for Mobile-Enforced Platforms](../docs/adr/0003-automated-device-delivery.md)  
> **Domain Standards**: [GLOSSARY.md](../GLOSSARY.md)

This document defines the authoritative data contract for the workspace-level channel portfolio registry (`channels.json`). All persistent channel identities, warmup lifecycle stages, health gates, daily posting cadences, and device transfer configurations must conform to this schema.

---

## 1. Architectural Overview

### Workspace-Level Registry (`channels.json`)
Per **ADR 0001**, channel identities and warmup states are decoupled from individual video project timelines (`.clipping_state.json`). They are stored in a centralized workspace-level `channels.json` registry file. Video clipping runs query this registry during posting allocation (Step 7 packaging) to identify eligible destination channels with available daily post quota, and update post logs without polluting single-video timeline state.

### Channel Warmup Lifecycle
Per **ADR 0002**, short-form platforms (TikTok, Instagram Reels, YouTube Shorts) enforce aggressive algorithmic trust filtering and shadowban mechanisms against newly created or bot-like accounts. Accounts progress through a deterministic 4-stage lifecycle governed by strict behavioral and cadence constraints:

1. **`Cold Lurker`**: Newly registered account (Day 1–3). 
   - 0 posts allowed (`daily_post_limit: 0`).
   - Behavioral warmup protocol only: 20–30 minutes daily of algorithmic niche content browsing, following niche accounts, authentic comments, and liking relevant videos.
2. **`Seeding`**: Initial post testing phase (Day 4–10).
   - Low cadence: 1 post per day (`daily_post_limit: 1`).
   - Mandatory evaluation against the empirical **Health Gate**.
3. **`Ramp-Up`**: Scale phase after clearing health gate (Day 11–21).
   - Moderate cadence: 2–3 posts per day (`daily_post_limit: 2` or `3`).
   - Minimum post spacing of 2.5–4 hours between uploads.
4. **`Mature`**: Established authority account (Day 22+).
   - Full capacity: up to 4 posts per day (`daily_post_limit: 4`, subject to campaign limits).
   - High algorithmic trust, reliable distribution into the FYP / Shorts feed.

### Health-Gated Advancement & Suppression Protection
Per **ADR 0002**, accounts in `Seeding` cannot advance to `Ramp-Up` solely based on elapsed calendar time. An account must clear an empirical **Health Gate**:
- **Baseline View Distribution**: Videos must clear 200–500 views without suppression, proving the account is not suffering from a 0-view shadowban or algorithmic penalty.
- **`Account Cooldown`**: If view suppression or a 0-view shadowban is detected, the channel is immediately transitioned into an `Account Cooldown` state (or `cooldown` status). A mandatory 72-hour zero-posting cooldown is triggered, accompanied by non-posting algorithmic browsing, before re-testing.

### Automated Device Transfer Protocols
Per **ADR 0003**, paid clipping reward programs and platform anti-spam rules strictly prohibit automated API uploads on TikTok and Instagram Reels (`api_upload_allowed: false`). Rendered clips must be manually published from mobile devices. To eliminate manual friction between desktop rendering and mobile publishing, each channel configures a **Device Transfer Protocol**:
- `qr_code`: Zero-dependency local HTTP QR code download server accessible from mobile browser on the local network.
- `adb_push`: Automated Android Debug Bridge file transfer pushing rendered MP4 directly to the device's DCIM / Camera gallery.
- `telegram_dispatch`: Automated delivery of the video package and caption text directly to a designated Telegram bot or chat.
- `cloud_sync`: Synchronization to a shared cloud folder (Nextcloud, Dropbox, Google Drive) mounted on mobile.

---

## 2. Schema Hierarchy & Fields

### Root Level Object

| Field | Type | Required | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `version` | `string` | Yes | Schema contract version | `"1.0.0"` |
| `updated_at` | `string` | No | ISO 8601 timestamp of last registry update | `"2026-10-12T12:00:00Z"` |
| `workspace_id` | `string` | No | Identifier for workspace portfolio scope | `"workspace-curiousmike"` |
| `default_device_transfer` | `object` | No | Default delivery protocol fallback across channels | See sub-fields below |
| `channels` | `array[object]`| Yes | List of managed social media channel accounts | Array of Channel objects |

---

### Channel Object Specification

| Field | Type | Required | Description | Example |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `string` | Yes | Unique immutable identifier for channel | `"chan-tiktok-01"` |
| `platform` | `string` | Yes | Target platform (`"TikTok"`, `"Instagram Reels"`, `"YouTube Shorts"`) | `"TikTok"` |
| `handle` | `string` | Yes | Account handle | `"@curiousclips_daily"` |
| `account_name` | `string` | No | Human-readable label or display name | `"Curious Mike Clips #1"` |
| `creation_date` | `string` | No | Account registration date (YYYY-MM-DD) | `"2026-10-01"` |
| `stage` | `string` | Yes | Warmup lifecycle stage (`"Cold Lurker"`, `"Seeding"`, `"Ramp-Up"`, `"Mature"`, `"Account Cooldown"`) | `"Seeding"` |
| `status` | `string` | Yes | Operational status (`"active"`, `"cooldown"`, `"paused"`, `"banned"`) | `"active"` |
| `stage_entered_at` | `string` | No | ISO 8601 timestamp when current stage began | `"2026-10-05T00:00:00Z"` |
| `posting_cadence` | `object` | No | Daily posting limits, counts, and spacing | See sub-fields below |
| `health_gate` | `object` | No | View threshold verification and shadowban tracking | See sub-fields below |
| `cooldown` | `object` | No | 72-hour suppression resting state details | See sub-fields below |
| `device_transfer` | `object` | No | Automated mobile device delivery mechanism | See sub-fields below |
| `warmup_protocol` | `object` | No | Behavioral browsing and engagement tasks | See sub-fields below |
| `post_log` | `array[object]`| No | Historical log of allocated posts on this channel | Array of PostLog items |

---

### Sub-Object Specifications

#### 1. `posting_cadence`
- `daily_post_limit` (`integer`, required, min: 0): Maximum allowed posts today based on stage and campaign rules.
- `posts_today` (`integer`, required, min: 0): Count of posts already published today.
- `last_post_date` (`string`): ISO 8601 timestamp or date of most recent post.
- `min_post_spacing_hours` (`number`, min: 0): Minimum required delay in hours between consecutive posts.

#### 2. `health_gate`
- `cleared_health_gate` (`boolean`, required): Whether the channel has empirically cleared the baseline view threshold.
- `min_views_threshold` (`integer`, default: 200): Minimum views required per post without suppression.
- `max_views_threshold` (`integer`, default: 500): Upper baseline view target confirming non-suppression.
- `latest_views` (`integer`, min: 0): View count from the latest published clip sample.
- `consecutive_valid_posts` (`integer`, min: 0): Number of consecutive posts meeting health threshold.
- `suppression_detected` (`boolean`, default: false): Flag indicating 0-view shadowban or distribution suppression.

#### 3. `cooldown`
- `in_cooldown` (`boolean`, default: false): True if account is in mandatory 72-hour zero-posting cooldown.
- `triggered_at` (`string`): ISO 8601 timestamp when cooldown was triggered.
- `cooldown_until` (`string`): ISO 8601 timestamp when the 72-hour cooldown expires.
- `cooldown_duration_hours` (`integer`, default: 72): Standard duration (72 hours).
- `reason` (`string`): Reason for entering cooldown (e.g. `"0-view shadowban detected"`).

#### 4. `device_transfer`
- `protocol` (`string`, required, enum: `["qr_code", "adb_push", "telegram_dispatch", "cloud_sync"]`): Delivery mechanism.
- `target` (`string`): Endpoint URL, ADB serial/path, Telegram bot/chat handle, or sync directory path.
- `enabled` (`boolean`, default: true): Whether delivery protocol is active.

#### 5. `warmup_protocol`
- `daily_actions` (`array[string]`): Action checklist (e.g. `["browse_niche_feed", "like_relevant_videos"]`).
- `niche_keywords` (`array[string]`): Topics and hashtags to search and watch during warmup browsing.
- `browsing_minutes_per_day` (`integer`, min: 0): Target duration of algorithmic session.
- `target_interactions_per_day` (`integer`, min: 0): Number of likes/comments/follows to perform.

#### 6. `post_log` Items
- `clip_id` (`string`, required): Identifier of the published clip package.
- `project` (`string`): Campaign or project slug (e.g. `"n3on-x-mpj"`).
- `timestamp` (`string`, required): ISO 8601 publication timestamp.
- `views` (`integer`, min: 0): Verified view count.
- `post_url` (`string`): Public URL of the live post.

---

## 3. Authoritative JSON Schema

The following JSON Schema validates any workspace-level `channels.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ChannelPortfolio",
  "description": "Workspace-level channel portfolio registry schema for multi-channel warmup lifecycles, health gates, posting cadences, and device delivery.",
  "type": "object",
  "required": ["version", "channels"],
  "properties": {
    "version": {
      "type": "string",
      "default": "1.0.0"
    },
    "updated_at": {
      "type": "string"
    },
    "workspace_id": {
      "type": "string"
    },
    "default_device_transfer": {
      "type": "object",
      "required": ["protocol"],
      "properties": {
        "protocol": {
          "type": "string",
          "enum": ["qr_code", "adb_push", "telegram_dispatch", "cloud_sync"]
        },
        "target": {
          "type": "string"
        },
        "enabled": {
          "type": "boolean",
          "default": true
        }
      }
    },
    "channels": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "platform", "handle", "stage", "status"],
        "properties": {
          "id": {
            "type": "string",
            "description": "Unique channel identifier, e.g. 'chan-tiktok-01'"
          },
          "platform": {
            "type": "string",
            "enum": ["TikTok", "Instagram Reels", "YouTube Shorts"],
            "description": "Target social media platform"
          },
          "handle": {
            "type": "string",
            "description": "Account handle, e.g. '@curiousclips_daily'"
          },
          "account_name": {
            "type": "string",
            "description": "Human-friendly label or display name"
          },
          "creation_date": {
            "type": "string",
            "description": "ISO date (YYYY-MM-DD) or timestamp when account was created"
          },
          "stage": {
            "type": "string",
            "enum": ["Cold Lurker", "Seeding", "Ramp-Up", "Mature", "Account Cooldown"],
            "description": "Current warmup lifecycle stage"
          },
          "status": {
            "type": "string",
            "enum": ["active", "cooldown", "paused", "banned"],
            "description": "Operational status of the account"
          },
          "stage_entered_at": {
            "type": "string",
            "description": "ISO timestamp when current stage was entered"
          },
          "posting_cadence": {
            "type": "object",
            "required": ["daily_post_limit", "posts_today"],
            "properties": {
              "daily_post_limit": {
                "type": "integer",
                "minimum": 0,
                "description": "Maximum posts allowed per day for current stage"
              },
              "posts_today": {
                "type": "integer",
                "minimum": 0,
                "description": "Number of posts published today"
              },
              "last_post_date": {
                "type": "string",
                "description": "Date or timestamp of last post"
              },
              "min_post_spacing_hours": {
                "type": "number",
                "minimum": 0,
                "description": "Minimum hours between posts"
              }
            }
          },
          "health_gate": {
            "type": "object",
            "required": ["cleared_health_gate"],
            "properties": {
              "cleared_health_gate": {
                "type": "boolean",
                "description": "True if account has cleared empirical view-count threshold without suppression"
              },
              "min_views_threshold": {
                "type": "integer",
                "default": 200,
                "description": "Minimum view count floor (e.g. 200 views)"
              },
              "max_views_threshold": {
                "type": "integer",
                "default": 500,
                "description": "Upper bounds for health gate baseline (e.g. 500 views)"
              },
              "latest_views": {
                "type": "integer",
                "minimum": 0,
                "description": "View count of most recent post sample"
              },
              "consecutive_valid_posts": {
                "type": "integer",
                "minimum": 0,
                "description": "Number of consecutive posts meeting health threshold"
              },
              "suppression_detected": {
                "type": "boolean",
                "default": false,
                "description": "True if 0-view shadowban or suppression is detected"
              }
            }
          },
          "cooldown": {
            "type": "object",
            "properties": {
              "in_cooldown": {
                "type": "boolean",
                "default": false
              },
              "triggered_at": {
                "type": "string"
              },
              "cooldown_until": {
                "type": "string"
              },
              "cooldown_duration_hours": {
                "type": "integer",
                "default": 72
              },
              "reason": {
                "type": "string"
              }
            }
          },
          "device_transfer": {
            "type": "object",
            "required": ["protocol"],
            "properties": {
              "protocol": {
                "type": "string",
                "enum": ["qr_code", "adb_push", "telegram_dispatch", "cloud_sync"],
                "description": "Mechanism used to deliver rendered clips to mobile device"
              },
              "target": {
                "type": "string",
                "description": "Destination address, device ID, chat ID, or path"
              },
              "enabled": {
                "type": "boolean",
                "default": true
              }
            }
          },
          "warmup_protocol": {
            "type": "object",
            "properties": {
              "daily_actions": {
                "type": "array",
                "items": {
                  "type": "string"
                },
                "description": "Platform-specific browsing/engagement tasks"
              },
              "niche_keywords": {
                "type": "array",
                "items": {
                  "type": "string"
                },
                "description": "Target topics/keywords to browse during warmup"
              },
              "browsing_minutes_per_day": {
                "type": "integer",
                "minimum": 0
              },
              "target_interactions_per_day": {
                "type": "integer",
                "minimum": 0
              }
            }
          },
          "post_log": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["clip_id", "timestamp"],
              "properties": {
                "clip_id": {
                  "type": "string"
                },
                "project": {
                  "type": "string"
                },
                "timestamp": {
                  "type": "string"
                },
                "views": {
                  "type": "integer",
                  "minimum": 0
                },
                "post_url": {
                  "type": "string"
                }
              }
            }
          }
        }
      }
    }
  }
}
```
