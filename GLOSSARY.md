# Clipping Pipeline

A modular, stateful short-form video clipping system that decomposes the video editing and campaign compliance workflow into discrete agent skills.

## Language

**Campaign Brief**:
A normalized configuration document (`campaign_brief.json`) declaring all hard rules, payout thresholds, platform tags, and compliance bounds for a video campaign.
_Avoid_: Guidelines doc, rule sheet, client prompt, campaign spec

**State File**:
The canonical project-local JSON document (`.clipping_state.json`) recording active pipeline progress, approved steps, and pre-digested step parameters.
_Avoid_: Cache, session store, pipeline memory

**Step Slice**:
A pre-digested parameter subset extracted from the campaign brief into the state file, tailored exclusively to a single downstream step skill.
_Avoid_: Sub-config, partial brief, step parameters

**Transition Gate**:
A strict pre-flight check in the state engine preventing downstream skills from executing until prior steps are approved.
_Avoid_: Checkpoint, blocker, step barrier

**Router Skill**:
The top-level orchestrator skill (`clipping-pipeline`) that inspects state and coordinates the 7-step sequence without performing editing tasks directly.
_Avoid_: Master agent, manager skill, pipeline runner

**Step Skill**:
An atomic, modular skill responsible for one vertical phase of the clipping pipeline (such as `clipping-guidelines` or `clipping-hook-hunter`).
_Avoid_: Sub-skill, worker skill, task script

**Tier-1 Safe Default**:
A baseline viral parameter (e.g. 25s–45s duration, 0–3s hook) automatically injected when a campaign brief is silent on a requirement.
_Avoid_: Fallback setting, system preset

**Web Brief Ingestion**:
The process of extracting campaign rules and payout tables from authenticated creator dashboards (e.g. Whop, Notion) using the dedicated agent browser (`BrowserOS Neo`) and saving them to `raw_guidelines.md`.
_Avoid_: Web scraping, headless scraping, URL pulling

**Channel Portfolio**:
The collection of social accounts across platforms operated by a creator, tracked persistently across multiple video projects.
_Avoid_: Account fleet, channel list, profile set

**Channel Warmup Lifecycle**:
The deterministic 4-stage progression (`Cold Lurker` → `Seeding` → `Ramp-Up` → `Mature`) governing account activity to prevent platform shadowbans.
_Avoid_: Account journey, warmup phase, seasoning process

**Warmup Protocol**:
The specific behavioral constraints (e.g. browsing niche content, 0 posts, engagement intervals) assigned to a channel based on its warmup stage.
_Avoid_: Warming routine, warmup guide, daily checklist

**Portfolio Registry**:
The workspace-level JSON database (`channels.json`) storing persistent channel identities, creation dates, active stages, and daily post counters.
_Avoid_: Channel database, account store, user profile config

**Posting Cadence**:
The daily post ceiling and time spacing enforced on a channel according to its current warmup stage and campaign limits.
_Avoid_: Post frequency, posting schedule, daily rate

**Health Gate**:
The empirical view-count threshold (clearing 200–500 views without suppression) required before advancing a channel from Seeding to Ramp-Up.
_Avoid_: View checkpoint, algorithm check, traffic test

**Account Cooldown**:
A mandatory 72-hour zero-posting resting state triggered when a channel experiences view suppression or a 0-view shadowban.
_Avoid_: Shadowban pause, account timeout, penalty box

**Posting Allocation**:
The assignment of an approved video clip package to specific eligible channels that possess remaining daily post quota.
_Avoid_: Channel dispatch, post routing, distribution target

**Daily Task Protocol**:
The generated set of platform-specific browsing, engagement, or posting actions assigned to a channel for the current day.
_Avoid_: Daily checklist, warmup routine, daily agenda

**Device Transfer Protocol**:
The configured mechanism (such as local QR code server, ADB push, Telegram dispatch, or cloud sync) used to deliver rendered clips directly to the creator's mobile device for manual posting.
_Avoid_: File send, phone sync, video transfer

**QC Packager**:
The Step 7 skill (`clipping-qc-packager`) dedicated purely to audio/visual quality control (-14 LUFS loudness audit, caption closers check, metadata compliance) and Whop submission packaging.
_Avoid_: QC manager, publishing manager, step 7 dispatcher

**Publisher Skill**:
The Step 8 skill (`clipping-publisher`) responsible for querying eligible channels, uploading directly to YouTube Shorts (via YouTube Data API v3 with BrowserOS Neo fallback), and transferring rendered clips to creator mobile devices for warmed-up Instagram and TikTok accounts.
_Avoid_: Uploader bot, post sender, manual distributor

**Warmed-Up Channel**:
An account whose lifecycle stage allows active posting (`daily_post_limit > 0`—specifically `Seeding`, `Ramp-Up`, or `Mature`), and is not subject to an active `Account Cooldown`.
_Avoid_: Seasoned account, ready channel, aged profile

**Brand Cluster**:
A group of channel accounts across different platforms (e.g. YouTube Shorts, TikTok, Instagram Reels) that share the same `account_name` and creator identity.
_Avoid_: Channel family, account group, profile bundle

**Cross-Platform Distribution**:
Publishing a single approved video clip across different social platforms within the same brand cluster, while strictly prohibiting posting the identical clip to multiple channels on the same platform.
_Avoid_: Multi-posting, duplicate broadcasting, spray-and-pray


