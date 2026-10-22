---
name: clipping-captions
description: Generate kinetic 9:16 vertical captions in mic/chest safe zone (MarginV=420) with dual emotion/visual context comments (*emotion*), Neon Lime highlights, and native Remotion (@remotion/captions) caption track synchronization.
---

# Kinetic Captions & Emotion Styling (clipping-captions)

Step 5 captioning and kinetic typography engine for the Antigravity Short-Form Clipping Pipeline. Generates high-retention 9:16 vertical subtitles adhering to the **Zylok Viral Streamer Style** and synchronizes native caption tracks in Remotion (`.remotion.json` / `@remotion/captions`). Places subtitles strictly in the microphone/chest safe zone (`MarginV=420`, $Y \approx 1500$), segments speech into punchy 1–2 word bursts, highlights trigger keywords in Neon Lime (`#CCFF00`) and Crimson Red (`#FF0000`), reflects viral emotions and visual actions via asterisks (`*emotion or visual context comment*`), and triggers the live Remotion Studio companion checkpoint gate for operator review and preference codification.

Context pointers:
- Domain terminology: [`GLOSSARY.md`](../../GLOSSARY.md)
- Official Remotion Captions skill & schema (`Caption`, leading-space rule): [`skills/remotion-best-practices/remotion-captions/REFERENCE.md`](../remotion-best-practices/remotion-captions/REFERENCE.md), [`skills/remotion-best-practices/remotion-captions/display-captions.md`](../remotion-best-practices/remotion-captions/display-captions.md), [`docs/research/remotion-hyperframes-official-skills.md`](../../docs/research/remotion-hyperframes-official-skills.md)
- Campaign brief schema: [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md)
- Architectural decisions: [`docs/adr/0001-project-local-json-state-file.md`](../../docs/adr/0001-project-local-json-state-file.md), [`docs/adr/0002-pre-digested-step-slices.md`](../../docs/adr/0002-pre-digested-step-slices.md), [`docs/adr/0003-strict-sequential-step-gating.md`](../../docs/adr/0003-strict-sequential-step-gating.md), [`docs/adr/0012-remotion-and-hyperframes-rendering-engine.md`](../../docs/adr/0012-remotion-and-hyperframes-rendering-engine.md)
- Pipeline state engine: `scripts/clipping_state.py`
- Caption engine: `scripts/clipping_captions.py`
- Assembly engine: `scripts/clipping_assembly.py`
- GUI Companion sidecar: `scripts/gui_companion.py`
- Dual-channel preference codification: `scripts/clipping_preferences.py`

---

## Operating Protocol

Follow this 4-step sequence on every captioning execution:

### 1. State & Pre-Flight Gate Inspection

Inspect pipeline readiness and enforce prerequisite Step 4 (`clipping-assembly`) completion before executing caption styling:

```bash
python3 scripts/clipping_state.py validate --step clipping-captions --dir <project-dir>
```

- **Exit Code `0`**: Gate cleared. Proceed to step 2.
- **Exit Code `2`**: Pre-flight gate blocked. Prerequisite timeline assembly is incomplete or has an unreviewed checkpoint. Halt captioning immediately.
- Extract isolated Step Slice:
  ```bash
  python3 scripts/clipping_state.py get-step-config --step clipping-captions --dir <project-dir>
  ```

### 2. Kinetic Caption Generation & Dual Emotion Annotations

Execute caption generation using `clipping_captions.py`:

```bash
python3 scripts/clipping_captions.py generate \
  --project-dir <project-dir> \
  --words-per-line 2 \
  --margin-v 420
```

#### Captioning Specifications
- **Microphone / Chest Safe Zone**:
  * Set `MarginV=420` (Y ≈ 1500 on 1080×1920 canvas, or fractional height `margin: 0.2188` in Remotion).
  * Clears desktop boom microphones and table obstacles while floating safely above platform description UI and caption bars.
- **Dual Emotion & Visual Context Formatting**:
  * Every cue pairs an emotional reaction or physical action comment in asterisks with the spoken words:
    - Line 1: `*emotion or visual context comment*` (e.g. `*PURE SHOCK*`, `*EYES SHUT*`, `*HANDS SHAKING*`, `*SCREAMING CHAOS*`, `*GRAIL PULL*`, `*100% DESTINY*`, `*CELEBRATION*`).
    - Line 2: Spoken kinetic dialogue (1–2 words per line).
- **Zylok Viral Streamer Palette**:
  * **Pure White (`#FFFFFF`)**: Conversational dialogue.
  * **Neon Lime (`#CCFF00`)**: High-impact keywords, assets, card valuations, and grail pulls (`GRAIL`, `100%`, `ODDS`, `VALUE`, `$2,000`, `PULL`, `PACK`).
  * **Crimson Red (`#FF0000`)**: Extreme shock, screaming, and confrontation (`SCREAMING`, `WHAT?!`, `BE CAREFUL`, `SCARED`, `DEADASS`).
  * **Accent Gold (`#FFD700`)**: Emotion header tags (`*EMOTION*`).
- **Profanity Censorship**:
  * Automatically masks vulgar expletives with asterisks (`F*CK`, `SH*T`, `B*TCH`, `[ __ ]`).
- **Strict Non-Overlapping Timings**:
  * Cues enforce clean gaps; speech silences $> 0.25\text{s}$ clear the screen to prevent subtitle freezing.

### 3. Remotion Native Timeline Integration & Live Companion Checkpoint

The engine automatically updates the active `.remotion.json` project sequence with native `@remotion/captions` track `Dialogue Captions` and triggers the live Remotion Studio companion checkpoint gate:

```bash
python3 scripts/clipping_state.py checkpoint --step clipping-captions --dir <project-dir>
```

The checkpoint gate:
1. Pings the live Remotion Studio companion (`scripts/gui_companion.py`). If active on port `9876`, sends `file.open` / `file.revert` to reload the project with the new subtitle track.
2. Generates the interactive review artifact `checkpoint_clipping-captions.md` with `RequestFeedback: true`.
3. Records cue metrics, highlight counts, and emotion categories into `.clipping_state.json`.

#### Operator Interactive Guidance
Direct the human operator to inspect the subtitles in Remotion Studio:
```bash
python3 scripts/gui_companion.py seek --seconds 0.0
python3 scripts/gui_companion.py play
```

### 4. Feedback Registration & Step Approval

Collect human review or manual edits and approve the step:

1. **Option A: Register Chat Feedback / Directives**:
   ```bash
   python3 scripts/clipping_state.py checkpoint \
     --step clipping-captions \
     --dir <project-dir> \
     --feedback "Highlight 'Cooper Flagg' in lime and adjust margin to 400"
   ```
2. **Option B: Approve Step to Unblock Downstream Pipeline**:
   ```bash
   python3 scripts/clipping_state.py approve --step clipping-captions --dir <project-dir>
   ```
   Verify downstream Step 6 (`clipping-vfx-sfx`) is unblocked:
   ```bash
   python3 scripts/clipping_state.py validate --step clipping-vfx-sfx --dir <project-dir>
   ```
   Exit code `0` confirms the gate is cleared.

### 5. Post-Step Summary & Conversation Handoff
Following approval:
1. Concisely summarize what was completed (kinetic ASS and SRT subtitles generated, mic safe zone MarginV=420 enforced, dual emotion/visual comments applied, Remotion `@remotion/captions` track populated, and GUI companion checkpoint cleared).
2. Instruct the user to open a new conversation to run Step 6 (`clipping-vfx-sfx`).
3. Provide the exact copy-paste prompt formatted as:
   ```text
   Campaign: <Campaign Title> (<campaign-slug>) proceed with Step 6 (clipping-vfx-sfx)
   ```

---

## Completion Criteria

This skill is complete ONLY when all five conditions are met:
1. Subtitle files (`.ass`, `.srt`, and `captions.json`) are generated in the project directory.
2. Vertical mic safe zone (`MarginV=420`) and dual emotion/visual comments (`*emotion or visual context comment*`) are applied to every cue.
3. Native Remotion `.remotion.json` project sequence has `caption_tracks` updated with `Dialogue Captions`.
4. `.clipping_state.json` has `steps["clipping-captions"]` staged and review artifact `checkpoint_clipping-captions.md` generated with `RequestFeedback: true`.
5. Checkpoint is reviewed and state engine registers approval via `clipping_state.py approve --step clipping-captions`.
