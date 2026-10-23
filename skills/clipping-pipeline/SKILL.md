---
name: clipping-pipeline
description: Orchestrate short-form clipping pipeline and execution workflow across 8 gated stages with pre-flight transition checks.
---

# Master Pipeline Router (clipping-pipeline)

Master router and orchestrator for the 8-step short-form video clipping pipeline. Inspects campaign state, validates pre-flight transition gates, prevents premature execution across unapproved stages, isolates configuration load, and manages dispatch across all editing and publishing phases. Bridges workspace-level channel portfolio and warmup lifecycles (`channels.json`) into Step 8 publishing and automated mobile device delivery.

For campaign rules and data contracts, see [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md). For channel portfolio schema, see [`references/CHANNEL_PORTFOLIO_SCHEMA.md`](../../references/CHANNEL_PORTFOLIO_SCHEMA.md). For architectural decisions, see [`docs/adr/0007-workspace-level-channel-portfolio-registry.md`](../../docs/adr/0007-workspace-level-channel-portfolio-registry.md), [`docs/adr/0008-health-gated-warmup-advancement.md`](../../docs/adr/0008-health-gated-warmup-advancement.md), [`docs/adr/0009-automated-device-delivery.md`](../../docs/adr/0009-automated-device-delivery.md), [`docs/adr/0010-dedicated-pipeline-publishing-step.md`](../../docs/adr/0010-dedicated-pipeline-publishing-step.md), and [`docs/adr/0011-hardware-accelerated-proxy-generation.md`](../../docs/adr/0011-hardware-accelerated-proxy-generation.md). For step-isolated execution parameters, query `scripts/clipping_state.py get-step-config`.

---

## Standardized 8-Step Sequence

The clipping pipeline executes strictly in this sequential order:

1. `clipping-guidelines`: Ingest campaign brief, normalize rules, inject Cole Corcoran Tier-1 viral defaults (`[Default Applied]`), inspect workspace channel portfolio (`channels.json`) emitting a non-blocking advisory notice if uninitialized, render review artifact, and secure human approval gate.
2. `clipping-transcription`: Acquire source footage and generate hardware-accelerated proxy (`python3 scripts/download_source.py --dir <project-dir>`), extract audio, generate word-level timestamped transcripts, diarize speakers, apply phonetic correction, and generate **3×3 / 4×4 Timestamped Contact Sheets** (`python3 scripts/generate_contact_sheets.py -i <raw_video> -o <project-dir>/contact_sheets -m batch -d 120 -g 4x4`) to ground downstream agents visually.
3. `clipping-hook-hunter`: Locate viral curiosity gaps and 0–3s hook windows by evaluating Whisper JSON alongside contact sheets (identifying visual reaction spikes, streamer freak-outs, and physical comedy that transcripts miss), scoring candidate moments within duration bounds. Candidate verification generates targeted sheets (`-m candidates -c candidates.json`).
4. `clipping-assembly`: Build 9:16 vertical canvas (1080×1920), multi-camera visual shot reframing with safe-zone graphic punch-outs (70%–85%), hardware-friendly H.264 proxy pipeline, and consonant-buffered dead air excision.
5. `clipping-captions`: Generate kinetic captions in mic/chest safe zone, applying keyword emphasis.
6. `clipping-vfx-sfx`: Composite mandatory persistent watermark, title hook graphic, and subtle audio transient accents.
7. `clipping-qc-packager`: Audit loudness against -14 LUFS, verify rotated approved caption closers, ensure duration bounds, and format for 30-minute Whop submission window (pure QC decoupled from channel distribution per ADR 0010).
8. `clipping-publisher`: Match Brand Clusters (`account_name`), enforce zero same-platform duplication, enforce warmup gating, deliver mobile packages with companion `caption.txt`, upload YouTube Shorts via Data API v3 with BrowserOS Neo fallback, stage daily posting quotas in `channels.json`, and record structured `publication_manifest` in `.clipping_state.json`.

---

## Operating Protocol

Follow this deterministic orchestration loop on every invocation:

### 1. State Inspection & Campaign Readiness

Inspect the current pipeline state:
```bash
python3 scripts/clipping_state.py status --dir <project-dir>
```
Or for machine-readable inspection:
```bash
python3 scripts/clipping_state.py status --dir <project-dir> --json
```

- If `.clipping_state.json` does not exist, initialize project state:
  ```bash
  python3 scripts/clipping_state.py init --dir <project-dir>
  ```
- Identify `current_step`, `next_step`, and `guidelines_approved` status.
- **Channel Portfolio Bridge Check**:
  During pipeline status inspection and Step 1 guidelines validation, the state engine verifies the presence of the workspace-level `channels.json` registry. If `channels.json` is missing, a non-blocking advisory notice is emitted:
  ```
  [Notice] Workspace channel portfolio (channels.json) not found. Run 'python3 scripts/clipping_channels.py init' if managing multi-channel warmup.
  ```
  This advisory notice does not halt pipeline execution, but alerts the operator that channel portfolio management is unconfigured. To initialize the portfolio registry, run:
  ```bash
  python3 scripts/clipping_channels.py init --workspace-id <workspace-id>
  ```

### 2. Guidelines Approval Gate Check & Handoff

Before any editing or downstream analysis can proceed, campaign guidelines must be validated and approved:

- If `.clipping_state.json` was just initialized or `guidelines_approved` is `false`:
  - Hand off immediately to `clipping-guidelines`.
  - Ingest the raw campaign brief, generate `campaign_brief.json`, and present `campaign_brief_review.md` with `RequestFeedback: true`.
  - Halt all downstream steps (`clipping-transcription` through `clipping-publisher`).
  - Do not proceed until human approval is confirmed via:
    ```bash
    python3 scripts/clipping_state.py approve --step clipping-guidelines --dir <project-dir>
    ```

### 3. Pre-Flight Transition Gate Enforcement

Before launching any step, evaluate its pre-flight validation gate:
```bash
python3 scripts/clipping_state.py validate --step <target-step> --dir <project-dir>
```

#### Transition Gate Rules
Each stage requires its immediate predecessor to be completed and approved in `.clipping_state.json`. `clipping-guidelines` must be approved (`guidelines_approved: true`) before any downstream editing commences. Verify gate clearance dynamically via `python3 scripts/clipping_state.py validate --step <target-step> --dir <project-dir>`.

#### Gate Exit Codes
- **Exit Code `0`**: Gate cleared. Proceed with execution.
- **Exit Code `2`**: Pre-flight gate blocked. Prerequisite step incomplete or unapproved. Execution must stop immediately. Premature transitions are prohibited.
- **Bypass Flag (`--force`)**: In editorial override scenarios, `--force` bypasses the gate with a logged warning. Use only when explicitly commanded by the user.

### 4. Context-Isolated Configuration Extraction

To prevent context window saturation and retain razor-sharp attention, do NOT pass entire brief files or full manifest documents into subagents.

Extract only the pre-digested configuration slice for the active step:
```bash
python3 scripts/clipping_state.py get-step-config --step <target-step> --dir <project-dir>
```

Consult [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md) for full schema definitions and allowable parameters. Provide the resulting JSON payload directly to the executing step subagent.

- **Step 7 (`clipping-qc-packager`)**: Focuses purely on EBU R128 loudness verification (-14 LUFS), duration bounds, caption closers, and Whop compliance packaging (decoupled from channel distribution per ADR 0010).
- **Step 8 (`clipping-publisher`)**: Queries workspace channel portfolio (`channels.json`) to select `eligible_channels` across brand clusters, strictly verifying `health_status != 'cooldown'` (excluding accounts in `Account Cooldown`), enforcing daily post capacity (`posts_today < daily_post_cap` / `daily_post_limit`), executing automated mobile `device_transfer` delivery with companion `caption.txt`, uploading YouTube Shorts via Data API v3 with BrowserOS Neo fallback, and persisting `publication_manifest`.

### 5. Step Dispatch & Advance

1. Dispatch the target task to its dedicated skill or subagent with the extracted config slice.
2. For Step 8, execute multi-platform distribution:
   ```bash
   python3 scripts/clipping_publisher.py publish \
     --brand-cluster "<brand-cluster>" \
     --channels channels.json \
     --video <path/to/clip.mp4> \
     --clip-id "<clip-id>" \
     --project-dir <project-dir>
   ```
   This generates and writes `publication_manifest` into `.clipping_state.json`.
3. Upon verified completion of the step's work, record step completion in the state engine:
   ```bash
   python3 scripts/clipping_state.py approve --step <target-step> --dir <project-dir>
   ```
   For Step 8 (`clipping-publisher`), approval validates that `publication_manifest` is present and non-empty.
4. Query `python3 scripts/clipping_state.py status --dir <project-dir>` to confirm advancement to the next step.

### 6. Post-Step Summary & Multi-Conversation Handoff Protocol

To eliminate context window saturation, avoid hallucination drift, and ensure step-isolated execution, the pipeline requires a multi-conversation handoff after each approved step.

After each step is approved (via `python3 scripts/clipping_state.py approve --step <target-step> --dir <project-dir>`):
1. **Explain What Was Done**: Provide a concise summary of the outputs generated, gates passed, and state modifications committed (e.g. proxy generated, transcript saved, candidate selected, timeline assembled).
2. **Conversation Handoff Instruction**: Instruct the user that they must paste a prompt in another conversation to run the subsequent step.
3. **Format Next-Step Prompt**: Output the exact prompt for the user to copy-paste into the new conversation, dynamically formatted as:
   ```text
   Campaign: <Campaign Title> (<campaign-slug>) proceed with Step <N> (<step-name>)
   ```
   *Example*:
   ```text
   Campaign: HardScope — Unpacked Episode 2 (hardscope-unpacked-episode-2) proceed with Step 4 (clipping-assembly)
   ```
   *(Always override the campaign title, slug, step number, and step name with the values relevant to the project and next step).*

---

## Completion Criteria

The pipeline router execution is complete ONLY when:
1. Every executed step passed its pre-flight gate check (`clipping_state.py validate --step <step>`).
2. Campaign guidelines were approved with `guidelines_approved: true` before downstream editing commenced.
3. Each subagent operated strictly on its isolated configuration slice (`get-step-config`).
4. Step 7 (`clipping-qc-packager`) performed audio/video quality control and Whop packaging.
5. Step 8 (`clipping-publisher`) verified brand clustering, zero same-platform duplicate allocation, executed multi-platform publishing/transfers, and persisted `publication_manifest`.
6. All 8 steps (`clipping-guidelines` through `clipping-publisher`) reflect `status: "completed"` and `"approved": true` in `scripts/clipping_state.py status`.
