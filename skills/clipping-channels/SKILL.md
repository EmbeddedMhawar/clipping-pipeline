---
name: clipping-channels
description: Manage workspace channel portfolio, multi-platform account warmup lifecycles, health gates, and mobile device delivery.
---

# Channel Portfolio & Account Warmup Management (clipping-channels)

Workspace-level companion skill for the Short-Form Clipping Pipeline. Governs persistent channel identities, multi-platform warmup lifecycles, empirical health gates, daily posting cadences, and automated device transfer protocols for mobile-enforced social platforms.

See [`references/CHANNEL_PORTFOLIO_SCHEMA.md`](../../references/CHANNEL_PORTFOLIO_SCHEMA.md) for authoritative schema specifications, [`GLOSSARY.md`](../../GLOSSARY.md) for domain terminology, and architecture decisions in [`docs/adr/0001-workspace-level-channel-portfolio-registry.md`](../../docs/adr/0001-workspace-level-channel-portfolio-registry.md), [`docs/adr/0002-health-gated-warmup-advancement.md`](../../docs/adr/0002-health-gated-warmup-advancement.md), and [`docs/adr/0003-automated-device-delivery.md`](../../docs/adr/0003-automated-device-delivery.md).

---

## Operating Protocol

Execute this structured protocol when discovering creator channels, onboarding new accounts, planning daily warmup tasks, verifying health gates, or delivering rendered clips for manual mobile publishing:

### 1. Onboarding Interview Protocol (Account & Infrastructure Discovery)

When onboarding a creator or setting up a workspace portfolio, conduct a structured interview to discover all accounts and transfer capabilities:

1. **Account Identification & Platform Scope**:
   - Query creator for all accounts across target platforms: **TikTok**, **Instagram Reels**, and **YouTube Shorts**.
   - Collect exact account handles (e.g. `@curiousclips_daily`, `@mikeclips_official`).
   - Assign or confirm human-readable account names.

2. **Account Age & Post History**:
   - Determine account creation date and historical activity level.
   - Catalog existing post history: brand new registration (Day 1), active posting, or dormant profile.
   - Initial stage categorization:
     * New account (< 3 days, 0 posts) $\rightarrow$ `Cold Lurker`.
     * Recently created (Day 4–10, initial posts) $\rightarrow$ `Seeding`.
     * Established account clearing baseline algorithmic views $\rightarrow$ `Ramp-Up` or `Mature`.

3. **Shadowban & Algorithmic Health Check**:
   - Inspect recent post views for signs of 0-view shadowbans or distribution suppression.
   - If an account has experienced an abrupt drop to 0 views or algorithmic penalty, flag it immediately for `Account Cooldown`.

4. **Preferred Device Transfer Discovery**:
   Identify the creator's preferred delivery mechanism for manual mobile posting (per ADR 0003, mobile-enforced platforms prohibit API uploads):
   - `local_qr`: Zero-dependency local QR code download server accessible from mobile browser on the local Wi-Fi network.
   - `adb_push`: Direct USB/wireless file push via Android Debug Bridge into the mobile device gallery (`/sdcard/DCIM/Camera/`).
   - `cloud_folder`: Synchronized local/cloud folder (Nextcloud, Dropbox, Google Drive) mounted on creator's mobile device.
   - `webhook`: Automated dispatch to a Telegram bot or webhook endpoint delivering the clip and caption.

---

### 2. Portfolio Registry Initialization & Channel Ingestion

Initialize the workspace-level `channels.json` database if not already present:

```bash
python3 scripts/clipping_channels.py init --workspace-id <workspace-id>
```

Add discovered channels into the portfolio:

```bash
python3 scripts/clipping_channels.py add \
  --platform "TikTok" \
  --handle "@curiousclips_daily" \
  --stage "Cold Lurker" \
  --account-name "Curious Mike Clips #1"
```

Repeat for all discovered handles across platforms:

```bash
python3 scripts/clipping_channels.py add \
  --platform "Instagram Reels" \
  --handle "@curiousclips_ig" \
  --stage "Seeding" \
  --account-name "Curious Reels #1"
```

---

### 3. Diagnostic Portfolio Audit & Review Artifact

Execute a comprehensive audit of all portfolio channels to inspect stage distribution, health gate status, cooldown states, and daily posting capacity:

```bash
python3 scripts/clipping_channels.py audit \
  --output-artifact channel_portfolio_audit.md
```

The resulting `channel_portfolio_audit.md` diagnostic artifact provides:
- **Registry Summary**: Total registered channels, channels in cooldown, channels clearing health gate.
- **Posting Capacity**: Total posts published today and remaining quota across the portfolio.
- **Stage Breakdown**: Count of channels currently in `Cold Lurker`, `Seeding`, `Ramp-Up`, `Mature`, and `Account Cooldown`.
- **Channel Inventory Table**: Structured table displaying ID, platform, handle, stage, operational status, `daily_post_limit`, `posts_today`, Health Gate status, and cooldown state.

Present this diagnostic report to the user to align on active posting capacity before allocating video clips.

---

### 4. 4-Stage Warmup Protocol & Daily Task Checklists

Per **ADR 0002**, short-form algorithms enforce trust filtering. Accounts advance through a deterministic 4-stage lifecycle governed by strict behavioral and cadence constraints:

| Stage | Lifecycle Window | Daily Post Limit | Min Post Spacing | Daily Warmup Protocol Checklist |
| :--- | :--- | :--- | :--- | :--- |
| **`Cold Lurker`** | Day 1–3 | **0 posts** | N/A | • 20–30 mins algorithmic browsing in target niche<br>• Like 5–10 relevant videos<br>• Follow 3–5 niche creator accounts<br>• Leave 2–3 authentic comments (no spam) |
| **`Seeding`** | Day 4–10 | **1 post** | 4.0 hours | • 20 mins niche feed browsing<br>• Publish 1 test clip<br>• Monitor 24h view distribution against Health Gate<br>• Reply to viewer comments |
| **`Ramp-Up`** | Day 11–21 | **2–3 posts** | 2.5 hours | • 15 mins niche feed browsing<br>• Publish 2–3 spaced clips (min 2.5h spacing)<br>• Monitor view stability<br>• Engage with audience |
| **`Mature`** | Day 22+ | **Up to 4 posts** | 2.0 hours | • 10 mins community engagement<br>• Publish up to 4 scheduled clips (subject to campaign cap)<br>• Review analytics performance |

Generate the current day's actionable task agenda for all channels:

```bash
python3 scripts/clipping_channels.py daily-tasks
```

Or for machine-readable automation pipelines:

```bash
python3 scripts/clipping_channels.py daily-tasks --json
```

---

### 5. Health Gate Verification & 72-Hour Account Cooldown

#### Empirical Health Gate Enforcement
Advancing an account from `Seeding` to `Ramp-Up` **cannot** rely solely on elapsed calendar days. To avoid wasting edited clip assets on algorithmic dead-ends:
- **View-Count Baseline**: The account must clear an empirical Health Gate of **200–500 views** without suppression on published clips.
- When an account meets the threshold, advance it to `Ramp-Up`:
  ```bash
  python3 scripts/clipping_channels.py advance-stage \
    --id chan-tiktok-01 \
    --views 340
  ```
- If advancement is attempted with `< 200` views, the CLI strictly blocks transition unless overridden with `--force`.

#### 72-Hour Account Cooldown Protocol
If an account experiences a 0-view shadowban, sudden algorithmic suppression, or community guideline strike:
1. Immediately place the account into `Account Cooldown`:
   ```bash
   python3 scripts/clipping_channels.py cooldown \
     --id chan-tiktok-01 \
     --hours 72 \
     --reason "0-view shadowban detected on latest upload"
   ```
2. **Behavioral Protocol during Cooldown**:
   - **Zero posting allowed** (`daily_post_limit: 0`).
   - Algorithmic browsing only: 20–30 minutes daily of organic browsing and genuine interactions to reset trust score.
   - Do not delete suppressed videos (deleting multiple videos triggers spam flags; make private if necessary).
3. **Cooldown Expiry & Re-Testing**:
   After 72 hours, advance the channel out of cooldown back into `Seeding` for a single-clip test post:
   ```bash
   python3 scripts/clipping_channels.py advance-stage --id chan-tiktok-01
   ```

---

### 6. Post Logging & Device Transfer Execution

#### Logging Published Clips
When a clip is allocated and published to a channel, record the event to track daily quotas and spacing:

```bash
python3 scripts/clipping_channels.py log-post \
  --id chan-tiktok-01 \
  --clip-id clip-001 \
  --project curiousmike-n3on \
  --views 450 \
  --post-url "https://www.tiktok.com/@curiousclips_daily/video/123456789"
```

#### Executing Mobile Device Delivery
When Step 7 (`clipping-qc-packager`) packages an approved clip, trigger automated device delivery to transfer the rendered MP4 to the creator's device:

```bash
# Transfer via channel's configured device protocol (e.g. local_qr, adb_push, cloud_folder, webhook)
python3 scripts/clipping_channels.py transfer \
  --clip exports/clip_001.mp4 \
  --channel chan-tiktok-01
```

Or specify transfer method explicitly:

```bash
# Local QR Code Download Server
python3 scripts/clipping_channels.py transfer \
  --clip exports/clip_001.mp4 \
  --method local_qr

# Android Debug Bridge Direct Push
python3 scripts/clipping_channels.py transfer \
  --clip exports/clip_001.mp4 \
  --method adb_push \
  --target "/sdcard/DCIM/Camera/"

# Cloud Directory Sync
python3 scripts/clipping_channels.py transfer \
  --clip exports/clip_001.mp4 \
  --method cloud_folder \
  --target "~/Dropbox/Clips"

# Telegram Webhook Dispatch
python3 scripts/clipping_channels.py transfer \
  --clip exports/clip_001.mp4 \
  --method webhook \
  --target "http://127.0.0.1:8080/telegram_webhook"
```

---

## CLI Commands Reference

All portfolio operations are executed via `scripts/clipping_channels.py`:

| Command | Usage | Description |
| :--- | :--- | :--- |
| `init` | `python3 scripts/clipping_channels.py init [--dir <dir>] [--workspace-id <id>] [--force]` | Initialize a new `channels.json` registry |
| `add` | `python3 scripts/clipping_channels.py add --platform <platform> --handle <handle> [--stage <stage>] [--account-name <name>] [--id <id>]` | Register a new channel account |
| `audit` | `python3 scripts/clipping_channels.py audit [--output-artifact <file.md>]` | Audit channel portfolio status and output diagnostic report |
| `daily-tasks` | `python3 scripts/clipping_channels.py daily-tasks [--json]` | Generate daily warmup routines and posting agenda |
| `advance-stage` | `python3 scripts/clipping_channels.py advance-stage --id <id> [--views <views>] [--force]` | Advance channel lifecycle stage enforcing Health Gate checks |
| `cooldown` | `python3 scripts/clipping_channels.py cooldown --id <id> [--hours <hours>] [--reason <reason>]` | Trigger 72-hour zero-posting Account Cooldown |
| `log-post` | `python3 scripts/clipping_channels.py log-post --id <id> [--clip-id <id>] [--project <slug>] [--views <views>] [--force]` | Log clip publication and enforce daily posting cadence |
| `transfer` | `python3 scripts/clipping_channels.py transfer --clip <path> [--channel <id>] [--method <method>] [--target <target>] [--dry-run]` | Deliver rendered video clip to mobile device |

---

## Completion Criteria

The channel management workflow is complete ONLY when:
1. `channels.json` is initialized and valid against [`references/CHANNEL_PORTFOLIO_SCHEMA.md`](../../references/CHANNEL_PORTFOLIO_SCHEMA.md).
2. All creator accounts have been cataloged with verified platform, handle, age, and initial stage.
3. Diagnostic artifact `channel_portfolio_audit.md` has been rendered showing accurate capacity and stage counts.
4. Daily task agenda is generated via `scripts/clipping_channels.py daily-tasks` for all non-mature channels.
5. Channels advancing from `Seeding` have empirically cleared the 200–500 view Health Gate.
