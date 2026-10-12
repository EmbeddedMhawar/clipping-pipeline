# clipping-pipeline

> **Antigravity Plugin**: Enterprise-Grade Short-Form Video Clipping Pipeline for Creator Reward Campaigns  
> **Author**: Abderrahmane Mhawar  
> **Repository**: [https://github.com/EmbeddedMhawar/clipping-pipeline](https://github.com/EmbeddedMhawar/clipping-pipeline)

---

## Overview

`clipping-pipeline` is an Antigravity plugin designed to automate and formalize short-form vertical video clipping (TikTok, Instagram Reels, YouTube Shorts) for paid creator reward programs (such as Whop Creator Rewards, Clip Farm, and creator-specific clipping campaigns).

The pipeline unifies two proven frameworks:
1. **Cole Corcoran's AI Clipping Framework**: Strict Hook $\rightarrow$ Story $\rightarrow$ Payoff architecture, dead-air pruning ($>0.4$s), kinetic word-by-word subtitles, Tier-1 audience targeting ($\ge 40\%$ US/UK/CA), and 30-minute Whop submission compliance.
2. **Storyteller FilmCraft 8-Subagent Pipeline**: Gated modular execution where each editing and distribution step receives isolated, pre-digested configuration slices, strictly controlled by a deterministic state engine.

---

## Architecture & 8-Step Sequence

The pipeline executes as a sequential, gated 8-step process. Downstream editing and publishing subagents are blocked until upstream steps and pre-flight gates are validated and approved.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    CLIPPING PIPELINE WORKFLOW                                   │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                 │
│  [Step 1: clipping-guidelines]                                                                  │
│   - Ingests raw campaign brief (Markdown file, BrowserOS Neo raw_guidelines.md, or Prompt text) │
│   - Normalizes into campaign_brief.json & injects Tier-1 viral defaults                         │
│   - Generates interactive review artifact & requests human approval                             │
│                              │                                                                  │
│                              ▼  (Pre-flight Gate: guidelines_approved)                          │
│  [Step 2: clipping-transcription]                                                               │
│   - Speaker diarization, word-level timestamps, phonetic dictionary                             │
│                              │                                                                  │
│                              ▼                                                                  │
│  [Step 3: clipping-hook-hunter]                                                                 │
│   - 0-3s high-stakes hook discovery, curiosity gaps, 20-60s bounds                              │
│                              │                                                                  │
│                              ▼                                                                  │
│  [Step 4: clipping-assembly]                                                                    │
│   - 1080x1920 (9:16) smart-center layout, speaker x-anchors, dead air cut                       │
│                              │                                                                  │
│                              ▼                                                                  │
│  [Step 5: clipping-captions]                                                                    │
│   - Kinetic word-by-word subtitles in mic/chest safe zone (margin_v: 420)                       │
│                              │                                                                  │
│                              ▼                                                                  │
│  [Step 6: clipping-vfx-sfx]                                                                     │
│   - Persistent official watermark placement, transient SFX, zero music bed                      │
│                              │                                                                  │
│                              ▼                                                                  │
│  [Step 7: clipping-qc-packager]                                                                 │
│   - EBU R128 -14 LUFS loudness check, 12 approved closers, Whop metadata                        │
│                              │                                                                  │
│                              ▼  (Pre-flight Gate: clipping-qc-packager approved)                │
│  [Step 8: clipping-publisher]                                                                   │
│   - Brand Cluster matching, zero duplicate same-platform allocation, warmup gating              │
│   - YouTube Shorts upload (Data API v3 + BrowserOS Neo fallback)                                │
│   - TikTok & Instagram Reels mobile delivery with companion caption bundling                    │
│   - Quota staging in channels.json & publication_manifest persistence in state                  │
│                                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### The 8 Steps:
1. **`clipping-guidelines`**: Ingests campaign briefs, enforces non-negotiables, injects Tier-1 defaults (`[Default Applied]`), and produces a user approval artifact.
2. **`clipping-transcription`**: Generates diarized transcription with word timestamps and phonetic fixes.
3. **`clipping-hook-hunter`**: Ranks viral hooks and defines the 0–3s hook snippet and curiosity loops.
4. **`clipping-assembly`**: Sets up 9:16 vertical canvas, speaker framing, and removes dead air $>0.4$s (preserving 80ms consonant buffers).
5. **`clipping-captions`**: Renders high-contrast kinetic subtitles placed clear of mobile UI overlays.
6. **`clipping-vfx-sfx`**: Enforces persistent watermark placement and adds punctuation sound design without speech clashing.
7. **`clipping-qc-packager`**: Performs compliance audit (loudness, closers, metadata) and generates ready-to-post packages within the 30-minute Whop submission window (decoupled from channel distribution per ADR 0010).
8. **`clipping-publisher`**: Distributes clips across brand cluster channels with zero same-platform duplication, enforces warmup gating, uploads YouTube Shorts with BrowserOS Neo fallback, delivers mobile packages with caption bundling, stages portfolio quotas, and generates structured `publication_manifest` receipts.

---

## State Engine & Guidelines Ingestion

### 1. Ingest Guidelines & Normalize Brief (`scripts/ingest_guidelines.py`)

```bash
# Ingest raw markdown guidelines (or BrowserOS Neo raw_guidelines.md), inject Tier-1 defaults, and update state
python3 scripts/ingest_guidelines.py --file CAMPAIGN_GUIDELINES.md --dir /path/to/project

# Generate review artifact for user approval gate
python3 scripts/ingest_guidelines.py --file CAMPAIGN_GUIDELINES.md --dir /path/to/project --output-artifact campaign_brief_review.md
```

### 2. State Engine CLI (`scripts/clipping_state.py`)

The pipeline state is deterministically tracked in `.clipping_state.json` by the CLI state engine `scripts/clipping_state.py`:

```bash
# Initialize pipeline state in a workspace
python3 scripts/clipping_state.py init --dir /path/to/project

# Ingest normalized campaign brief and generate pre-digested step parameter slices
python3 scripts/clipping_state.py ingest-brief --brief /path/to/campaign_brief.json --dir /path/to/project

# Check current pipeline status and gate transitions
python3 scripts/clipping_state.py status --dir /path/to/project

# Approve campaign guidelines (unlocks downstream steps)
python3 scripts/clipping_state.py approve --step clipping-guidelines --dir /path/to/project

# Validate pre-flight transition gates before running a step
python3 scripts/clipping_state.py validate --step clipping-transcription --dir /path/to/project

# Retrieve isolated parameter slice for a specific subagent (avoids context bloat)
python3 scripts/clipping_state.py get-step-config --step clipping-captions --dir /path/to/project
```

### Pre-Flight Gate Enforcement:
- If a required prerequisite is not met, `validate` exits with code `2` and outputs a blocking message to `stderr`.
- An optional `--force` flag allows manual override for debugging or development, exiting with code `0` and a warning.

### 3. Publisher Engine CLI (`scripts/clipping_publisher.py`)

Step 8 executes multi-platform distribution and persists publication manifests:

```bash
# Check brand clusters and channel eligibility status
python3 scripts/clipping_publisher.py status --brand-cluster "My Brand" --channels channels.json

# Verify configured YouTube OAuth tokens
python3 scripts/clipping_publisher.py verify-tokens --channels channels.json

# Publish clip across eligible brand cluster channels
python3 scripts/clipping_publisher.py publish \
  --brand-cluster "My Brand" \
  --channels channels.json \
  --video /path/to/clip.mp4 \
  --clip-id "clip-001" \
  --caption-hook "Viral Hook Headline" \
  --caption-closer "Follow for part 2!" \
  --project-dir /path/to/project
```

---

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/EmbeddedMhawar/clipping-pipeline.git ~/Work/clipping-pipeline
```

### 2. Symlink into Antigravity Plugins Directory
```bash
mkdir -p ~/.gemini/config/plugins
ln -s ~/Work/clipping-pipeline ~/.gemini/config/plugins/clipping-pipeline
```

### 3. Verify Plugin Discovery
Restart Antigravity or verify via language server RPC inventory:
```bash
python3 tests/test_plugin_manifest.py
```

---

## Directory Structure

```text
clipping-pipeline/
├── plugin.json                 # Antigravity plugin manifest
├── README.md                   # Plugin documentation
├── GLOSSARY.md                 # Project domain glossary
├── scripts/
│   ├── clipping_state.py       # State engine CLI & pre-flight gate validator
│   ├── clipping_channels.py    # Channel portfolio & warmup management engine
│   ├── clipping_publisher.py   # Multi-platform publishing engine (Step 8)
│   └── ingest_guidelines.py    # Guidelines normalizer & review artifact generator
├── references/
│   ├── CAMPAIGN_BRIEF_SCHEMA.md    # Normalized schema specification & JSON schema
│   └── CHANNEL_PORTFOLIO_SCHEMA.md # Channel portfolio & warmup schema specification
├── skills/
│   ├── clipping-pipeline/      # Master orchestrator router skill
│   │   └── SKILL.md
│   ├── clipping-guidelines/    # Campaign ingestion & review gate skill
│   │   └── SKILL.md
│   ├── clipping-channels/      # Channel portfolio & warmup management skill
│   │   └── SKILL.md
│   └── clipping-publisher/     # Multi-platform publishing skill (Step 8)
│       └── SKILL.md
└── tests/
    ├── test_plugin_manifest.py         # Plugin manifest test suite
    ├── test_clipping_state.py          # State engine CLI & pre-flight test suite
    ├── test_clipping_publisher.py      # Publisher CLI & brand cluster test suite
    ├── test_guidelines_skill.py        # Guidelines ingestion & schema test suite
    ├── test_router_skill.py            # Master router skill test suite
    ├── test_publisher_skill.py         # Publisher skill test suite
    ├── test_channels.py                # Channel portfolio CLI test suite
    ├── test_channel_schema.py          # Channel schema validator test suite
    ├── test_channels_skill.py          # Channel companion skill test suite
    └── test_e2e_publishing_pipeline.py # End-to-end 8-step pipeline test suite
```

---

## License

MIT © Abderrahmane Mhawar
