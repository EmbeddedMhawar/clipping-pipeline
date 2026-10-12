---
name: clipping-pipeline
description: Orchestrate short-form clipping pipeline and execution workflow across 7 gated stages with pre-flight transition checks.
---

# Master Pipeline Router (clipping-pipeline)

Master router and orchestrator for the 7-step short-form video clipping pipeline. Inspects campaign state, validates pre-flight transition gates, prevents premature execution across unapproved stages, isolates configuration load, and manages dispatch across all editing phases. Bridges workspace-level channel portfolio and warmup lifecycles (`channels.json`) into Step 7 packaging and automated mobile device delivery.

For campaign rules and data contracts, see [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md). For channel portfolio schema, see [`references/CHANNEL_PORTFOLIO_SCHEMA.md`](../../references/CHANNEL_PORTFOLIO_SCHEMA.md). For architectural decisions, see [`docs/adr/0001-workspace-level-channel-portfolio-registry.md`](../../docs/adr/0001-workspace-level-channel-portfolio-registry.md), [`docs/adr/0002-health-gated-warmup-advancement.md`](../../docs/adr/0002-health-gated-warmup-advancement.md), and [`docs/adr/0003-automated-device-delivery.md`](../../docs/adr/0003-automated-device-delivery.md). For step-isolated execution parameters, query `scripts/clipping_state.py get-step-config`.

---

## Standardized 7-Step Sequence

The clipping pipeline executes strictly in this sequential order:

1. `clipping-guidelines`: Ingest campaign brief, normalize rules, inject Cole Corcoran Tier-1 viral defaults (`[Default Applied]`), inspect workspace channel portfolio (`channels.json`) emitting a non-blocking advisory notice if uninitialized, render review artifact, and secure human approval gate.
2. `clipping-transcription`: Extract audio, generate word-level timestamped transcripts, diarize speakers, and apply phonetic correction.
3. `clipping-hook-hunter`: Locate viral curiosity gaps and 0–3s hook windows, scoring candidate moments within duration bounds.
4. `clipping-assembly`: Build 9:16 vertical canvas (1080×1920), anchor speaker positions, and prune dead air $>0.4$s with consonant buffer.
5. `clipping-captions`: Generate kinetic captions in mic/chest safe zone, applying keyword emphasis.
6. `clipping-vfx-sfx`: Composite mandatory persistent watermark, title hook graphic, and subtle audio transient accents.
7. `clipping-qc-packager`: Audit loudness against -14 LUFS, verify rotated approved caption closers, bridge with workspace channel portfolio (`channels.json`) to filter `eligible_channels` (matching platform, `health_status != 'cooldown'`, and `posts_today < daily_post_cap`), flag channels in cooldown or at daily capacity as ineligible with specific reasons, inject automated device transfer configurations (`device_transfer`), and format for 30-minute Whop submission window.

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
  - Halt all downstream steps (`clipping-transcription` through `clipping-qc-packager`).
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

### 4. Context-Isolated Configuration Extraction & Channel Portfolio Bridge

To prevent context window saturation and retain razor-sharp attention, do NOT pass entire brief files or full manifest documents into subagents.

Extract only the pre-digested configuration slice for the active step:
```bash
python3 scripts/clipping_state.py get-step-config --step <target-step> --dir <project-dir>
```

Consult [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md) for full schema definitions and allowable parameters. Provide the resulting JSON payload directly to the executing step subagent.

#### Step 7 Channel Portfolio Bridge & Device Delivery
When retrieving configuration for Step 7 (`clipping-qc-packager`), the state engine dynamically queries `channels.json` (per ADR 0001, ADR 0002, ADR 0003):
- **`eligible_channels`**: Accounts filtered to match campaign target platforms, verifying `health_status != 'cooldown'` (and not in `Account Cooldown` stage or suppression), and verifying remaining daily capacity (`posts_today < daily_post_cap` / `daily_post_limit`).
- **`ineligible_channels`**: Accounts currently in cooldown or at daily post limits are flagged as ineligible with explicit reasons (e.g. suppression cooldown, daily capacity reached, platform mismatch).
- **`device_transfer`**: Automated mobile device transfer configurations (`qr_code`, `adb_push`, `telegram_dispatch`, `cloud_sync`) from `channels.json` are passed into the Step 7 slice to eliminate friction for mobile-enforced platforms (`api_upload_allowed: false`).

### 5. Step Dispatch & Advance

1. Dispatch the target task to its dedicated skill or subagent with the extracted config slice.
2. For Step 7, execute mobile device delivery using the configured protocol:
   ```bash
   python3 scripts/clipping_channels.py transfer --clip <path/to/clip.mp4> --channel <channel-id>
   ```
   and record the publication in the channel portfolio registry:
   ```bash
   python3 scripts/clipping_channels.py log-post --id <channel-id> --clip-id <clip-id> --project <project-slug>
   ```
3. Upon verified completion of the step's work, record step completion in the state engine:
   ```bash
   python3 scripts/clipping_state.py approve --step <target-step> --dir <project-dir>
   ```
4. Query `python3 scripts/clipping_state.py status --dir <project-dir>` to confirm advancement to the next step.
5. Repeat from Step 3 for the subsequent pipeline step until `clipping-qc-packager` is completed.

---

## Completion Criteria

The pipeline router execution is complete ONLY when:
1. Every executed step passed its pre-flight gate check (`clipping_state.py validate --step <step>`).
2. Campaign guidelines were approved with `guidelines_approved: true` before downstream editing commenced.
3. Each subagent operated strictly on its isolated configuration slice (`get-step-config`).
4. Step 7 (`clipping-qc-packager`) performed eligible channel filtering against `channels.json` and prepared automated mobile device delivery.
5. All 7 steps (`clipping-guidelines` through `clipping-qc-packager`) reflect `status: "completed"` and `"approved": true` in `scripts/clipping_state.py status`.
