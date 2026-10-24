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

**Topic Segment**:
A bounded segment of raw interview or podcast footage containing a coherent subject, story, or argument from which multiple distinct clip variations can be extracted.
_Avoid_: Raw clip, video chunk, footage cut

**Variation Profile**:
A declarative style specification governing pacing, 0–3s hook formulation, framing logic, caption typography, and audio-visual treatment to transform a topic segment into a unique video edit.
_Avoid_: Edit style, video preset, custom variation

**Drama Cut**:
A variation profile focused on emotional extremity, starting with the most vulnerable or shocking statement, aggressive reaction punch-ins, bold kinetic highlights, and subtle riser sound effects.
_Avoid_: Shock cut, emotional edit, fast cut

**Debate Bait Cut**:
A variation profile engineered for high comment engagement (≥ 1%), opening with a provocative on-screen question card and rapid back-and-forth reaction cuts between speakers.
_Avoid_: Argument cut, question video, debate clip

**Narrative Cut**:
A variation profile optimized for high completion rate and watch time, opening with an unresolved curiosity loop, conversational pacing, and contextual B-roll or screenshot overlays.
_Avoid_: Story cut, documentary edit, long cut

**Speaker Framing Anchor**:
Smart-center vertical framing lock ensuring the active speaking subject is continuously centered in the 9:16 canvas unless deliberately replaced by contextual visual cutaways.
_Avoid_: Face tracking crop, center crop, auto-reframe

**Channel Profile Mapping**:
The deterministic pairing between a Variation Profile and a specific channel in the Portfolio Registry based on channel niche and editorial persona.
_Avoid_: Channel assignment, post binding, account targeting

**Live GUI Companion**:
A persistent background desktop process of Remotion Studio or HyperFrames Preview (`scripts/gui_companion.py`) running alongside the agent during pipeline execution, providing real-time visual playback and timeline inspection.
_Avoid_: External editor, desktop viewer, GUI watcher

**Feedback Checkpoint**:
A dedicated interactive pause state in the state engine (`clipping_state.py`) where downstream step approval is blocked until the operator inspects the live timeline in the GUI companion and provides directives or confirms approval.
_Avoid_: Step pause, review gate, user wait

**Bi-directional Preference Codification**:
The automated extraction and persistent storage of human editorial preferences derived both from interactive chat directives and from diffing manual timeline modifications against agent-generated baselines.
_Avoid_: Feedback recording, preference saving, preference capture

**Project Diffing Heuristic**:
The differential analysis of `.remotion.json` and `.hyperframes.html` project files comparing user-edited project files against agent-generated project baselines to detect and encode editorial preferences.
_Avoid_: Project comparison, file diffing, timeline diff

**Preference Store**:
The 3-tier hierarchical JSON configuration storage (`.clipping_preferences.json` project-level, `campaign_brief.json` campaign-level, and `~/.config/clipping-pipeline/preferences.json` user-level) governing editing parameters across pipeline runs.
_Avoid_: Settings file, preference cache, config store

**Video Proxy**:
A lightweight, fast-decoding edit copy of the high-resolution source video (typically half-resolution, e.g. 960×540, H.264, 1-second keyframe GOP interval, zero B-frames) stored in `raw/Proxies/<stem>_Proxy.mp4` per [ADR 0011](docs/adr/0011-hardware-accelerated-proxy-generation.md) for smooth scrubbing and timeline inspection in Remotion Studio without altering final master export resolution.
_Avoid_: Preview file, low-res copy, thumbnail video, draft video

**Hardware-Accelerated Proxy Generation**:
The offloading of video scaling and H.264 compression to host graphics hardware silicon (Linux VAAPI via `/dev/dri/renderD128`, NVIDIA NVENC, Apple Silicon VideoToolbox, or Intel QSV) per [ADR 0011](docs/adr/0011-hardware-accelerated-proxy-generation.md), with automatic fallback to CPU (`libx264 -preset veryfast`).
_Avoid_: GPU transcode, hardware encode, fast rendering
