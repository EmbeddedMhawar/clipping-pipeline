---
name: clipping-qc-packager
description: Audit audio loudness against -14 LUFS (EBU R128), verify rotated approved caption closers, validate platform duration bounds and safe zones, and format submission package for 30-minute Whop window.
---

# Quality Control & Whop Packaging (clipping-qc-packager)

Step 7 quality control (QC) and packaging engine for the Antigravity Short-Form Clipping Pipeline. Performs rigorous compliance auditing on assembled vertical video clips prior to multi-platform distribution. Purely decoupled from workspace channel portfolios and publishing mechanics (per ADR 0010), Step 7 ensures broadcast compliance: auditing dialogue and mix loudness against **-14.0 LUFS** (EBU R128 standard) with true peak $\le -1.0\text{ dBTP}$, enforcing campaign duration limits, selecting rotated approved caption closers from the campaign brief, verifying platform safe zones and persistent watermark visibility, enforcing zero background music beds and zero phonk rules, and structuring the ready-to-post package for immediate submission within the **30-minute Whop creator window**.

Context pointers:
- Domain terminology: [`GLOSSARY.md`](../../GLOSSARY.md) ("QC Packager", "Device Transfer Protocol", "Brand Cluster")
- Campaign brief schema: [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md)
- Architectural decisions: [`docs/adr/0010-dedicated-pipeline-publishing-step.md`](../../docs/adr/0010-dedicated-pipeline-publishing-step.md), [`docs/adr/0001-project-local-json-state-file.md`](../../docs/adr/0001-project-local-json-state-file.md), [`docs/adr/0002-pre-digested-step-slices.md`](../../docs/adr/0002-pre-digested-step-slices.md), [`docs/adr/0003-strict-sequential-step-gating.md`](../../docs/adr/0003-strict-sequential-step-gating.md)
- Step handoff protocol: [`docs/agents/step-handoff.md`](../../docs/agents/step-handoff.md)
- State engine CLI: `scripts/clipping_state.py`
- QC packager engine: `scripts/clipping_qc_packager.py`
- Downstream publisher engine: `scripts/clipping_publisher.py`

---

## Operating Protocol

Follow this 5-stage sequential protocol on every QC packaging invocation:

### 1. State & Pre-Flight Gate Inspection

Inspect pipeline readiness and verify that prerequisite Step 6 (`clipping-vfx-sfx`) has completed and cleared its checkpoint before executing quality control:

```bash
python3 scripts/clipping_state.py validate --step clipping-qc-packager --dir <project-dir>
```

- **Exit Code `0`**: Gate cleared. Proceed to step 2.
- **Exit Code `2`**: Pre-flight gate blocked. Prerequisite VFX/SFX step is incomplete or has an unreviewed checkpoint. Halt immediately. Premature transitions are strictly prohibited.
- Extract the isolated Step Slice:
  ```bash
  python3 scripts/clipping_state.py get-step-config --step clipping-qc-packager --dir <project-dir>
  ```
  *(Decoupled from `channels.json` per ADR 0010: receives target LUFS, duration bounds, caption closers, and Whop submission rules without portfolio queries).*

### 2. Audio Loudness Audit & EBU R128 Normalization

Audit the integrated loudness and true peak of the rendered master video against social platform broadcast standards:

- **Target Integrated Loudness**: `-14.0 LUFS` ($\pm 1.0\text{ LUFS}$ social video tolerance).
- **Maximum True Peak**: $\le -1.0\text{ dBTP}$ (prevent inter-sample clipping on mobile DACs).
- **Loudness Standard**: EBU R128 / ITU-R BS.1770-4.

If the input audio deviates from the $-14.0\text{ LUFS}$ target, apply 2-pass EBU R128 `loudnorm` audio normalization while lossless-copying the video stream (`-c:v copy`):

```bash
python3 scripts/clipping_qc_packager.py package \
  --project-dir <project-dir> \
  --target-lufs -14.0 \
  --max-true-peak -1.0
```

### 3. Caption Closer Rotation & Multi-Platform Copy Generation

To maximize viewership attribution and avoid spam-flagging from identical copy across multiple creator clips, dynamically rotate approved campaign closers:

1. **Closer Rotation**:
   Select an approved closer from `caption_closers` using deterministic rotation across project clips:
   * Example: `"watch the full episode @HardScopeTV on youtube #unpacked"`
2. **Platform-Specific Post Copy**:
   - **YouTube Shorts**: Tagged handle format (`@HardScopeTV`), headline hook, description body with closer, and campaign hashtags (`#unpacked #Shorts`).
   - **TikTok**: Plain-text handle syntax, caption hook, closer, and keyword tags within mobile character limits.
   - **Instagram Reels**: Plain-text handle syntax, line-break spaced caption structure, closer, and discovery hashtags.

### 4. Duration Bounds & Platform Safe Zones Audit

Perform strict automated validation of physical video bounds and layout constraints:

1. **Duration Bounds**:
   - Verify duration falls strictly within `[min_duration, max_duration]` (e.g. $7.0\text{s} \le T \le 60.0\text{s}$).
   - Evaluate against ideal target pacing ($25.0\text{s} - 45.0\text{s}$).
2. **Safe Zones & Aspect Ratio**:
   - Resolution must be exactly $1080 \times 1920$ (9:16 vertical).
   - Captions safe from bottom UI marquee (`MarginV=420` mic/chest zone).
   - Hook titles safe from top search header ($Y \ge 160\text{px}$).
   - Watermark verified active on Track V4, non-corner, spanning $100\%$ duration.
3. **Prohibited Edits Check**:
   - Confirm zero prohibited aesthetic artifacts (e.g. no aura, glow, skull icons, AI avatars, automated Opus Clip templates).
   - Confirm zero background music beds and zero phonk tracks.

### 5. Whop Packaging & Checkpoint Clearance

Generate the formal quality control artifact and submission manifest:

1. **Package Manifest (`qc_package.json`)**:
   Persist all audit results, loudness measurements, true peak values, rotated closer text, platform copy bundles, and Whop compliance checklist into `<project-dir>/qc_package.json`.
2. **Stage Interactive Review Checkpoint**:
   Trigger the pipeline checkpoint gate:
   ```bash
   python3 scripts/clipping_state.py checkpoint --step clipping-qc-packager --dir <project-dir>
   ```
   Renders `checkpoint_clipping-qc-packager.md` with `RequestFeedback: true` detailing the compliance card and Whop submission checklist.
3. **Approve Step to Unblock Downstream Step 8 (`clipping-publisher`)**:
   ```bash
   python3 scripts/clipping_state.py approve --step clipping-qc-packager --dir <project-dir>
   ```
   Verify downstream clearance:
   ```bash
   python3 scripts/clipping_state.py validate --step clipping-publisher --dir <project-dir>
   ```
   *(Exit code `0` confirms Step 8 is unblocked).*

---

## Completion Criteria

Execution of Step 7 (`clipping-qc-packager`) is complete ONLY when:
1. Master video loudness is verified or normalized to $-14.0\text{ LUFS} \pm 1.0\text{ LUFS}$ with true peak $\le -1.0\text{ dBTP}$.
2. Video duration is verified within `[min_duration, max_duration]` bounds.
3. An approved caption closer is selected and formatted across platform copy targets (YouTube Shorts, TikTok, Instagram Reels).
4. Watermark persistence, caption safe zones, and zero-BGM/zero-phonk rules are verified.
5. `qc_package.json` is generated and saved in the project directory.
6. Checkpoint `checkpoint_clipping-qc-packager.md` is generated with `RequestFeedback: true`.
7. Pipeline state records Step 7 as `"status": "completed"` and `"approved": true`.
8. Pre-flight gate check for Step 8 (`clipping-publisher`) exits with code `0`.
