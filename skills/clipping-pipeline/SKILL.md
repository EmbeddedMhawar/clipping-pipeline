---
name: clipping-pipeline
description: Master orchestrator router for the 7-step short-form video clipping pipeline. Inspects pipeline state, enforces pre-flight transition gates, isolates step configuration slices, and dispatches execution across the clipping lifecycle. Trigger on: clipping pipeline, clip short-form, run clipping workflow.
---

# Master Pipeline Router (clipping-pipeline)

Master router and orchestrator for the 7-step short-form video clipping pipeline. Inspects campaign state, validates pre-flight transition gates, prevents premature execution across unapproved stages, isolates configuration load, and manages dispatch across all editing phases.

---

## Standardized 7-Step Sequence

The clipping pipeline executes strictly in this sequential order:

1. `clipping-guidelines`: Ingest campaign brief, normalize rules, inject Cole Corcoran Tier-1 viral defaults (`[Default Applied]`), render review artifact, and secure human approval gate.
2. `clipping-transcription`: Extract high-fidelity audio, generate word-level timestamped transcripts, diarize speakers, and apply phonetic correction.
3. `clipping-hook-hunter`: Locate viral curiosity gaps and high-stakes statements, map 0–3s hook windows, score candidate moments, and enforce 20s–60s bounds.
4. `clipping-assembly`: Build 9:16 vertical canvas (1080×1920), anchor speaker x-coordinates, and prune dead air $>0.4$s with 80ms consonant buffer.
5. `clipping-captions`: Generate kinetic word-by-word captions in mic/chest safe zone (`margin_v: 420`), applying keyword emphasis and highlight colors.
6. `clipping-vfx-sfx`: Composite mandatory persistent watermark (disallowed in 4 corners), add title hook graphic, and inject subtle audio transient accents without loud background music beds.
7. `clipping-qc-packager`: Audit loudness against EBU R128 (-14 LUFS), verify rotated approved caption closers, validate platform compliance, and format for 30-minute Whop submission window.

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
- `clipping-guidelines`: Requires initialized state file.
- `clipping-transcription`: Blocked if `guidelines_approved == false`.
- `clipping-hook-hunter`: Blocked if `clipping-transcription` is not completed.
- `clipping-assembly`: Blocked if `clipping-hook-hunter` is not completed.
- `clipping-captions`: Blocked if `clipping-assembly` is not completed.
- `clipping-vfx-sfx`: Blocked if `clipping-captions` is not completed.
- `clipping-qc-packager`: Blocked if `clipping-vfx-sfx` is not completed.

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

Provide the resulting JSON payload directly to the executing step subagent.

### 5. Step Dispatch & Advance

1. Dispatch the target task to its dedicated skill or subagent with the extracted config slice.
2. Upon verified completion of the step's work, record step completion in the state engine:
   ```bash
   python3 scripts/clipping_state.py approve --step <target-step> --dir <project-dir>
   ```
3. Query `python3 scripts/clipping_state.py status --dir <project-dir>` to confirm advancement to the next step.
4. Repeat from Step 3 for the subsequent pipeline step until `clipping-qc-packager` is completed.

---

## Completion Criteria

The pipeline router execution is complete ONLY when:
1. Every executed step passed its pre-flight gate check (`clipping_state.py validate --step <step>`).
2. Campaign guidelines were approved with `guidelines_approved: true` before downstream editing commenced.
3. Each subagent operated strictly on its isolated configuration slice (`get-step-config`).
4. All 7 steps (`clipping-guidelines` through `clipping-qc-packager`) reflect `status: "completed"` and `"approved": true` in `scripts/clipping_state.py status`.
