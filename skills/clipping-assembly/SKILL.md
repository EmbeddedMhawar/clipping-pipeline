---
name: clipping-assembly
description: Assemble 9:16 vertical video projects (.fcproj) for FilmCraft with multi-track layout (4V/3A stack), speaker ping-pong reframing, dead air excision with consonant buffer, and live FilmCraft companion checkpoint gating.
---

# Timeline Assembly & Vertical Framing (clipping-assembly)

Step 4 timeline rough-cut assembly engine for the Antigravity Short-Form Clipping Pipeline. Transforms raw landscape footage into high-retention 9:16 vertical video projects (`.fcproj`) adhering to Storyteller FilmCraft schema version 12. Implements a 4-video / 3-audio track hierarchy, speaker ping-pong reframing, consonant-protected dead air excision, persistent brand watermarking, and triggers the live FilmCraft companion checkpoint gate for operator review and preference codification.

Context pointers:
- Domain terminology: [`GLOSSARY.md`](../../GLOSSARY.md)
- Native `.fcproj` assembly specification: [`docs/research/fcproj-assembly-spec.md`](../../docs/research/fcproj-assembly-spec.md)
- Architectural decisions: [`docs/adr/0001-project-local-json-state-file.md`](../../docs/adr/0001-project-local-json-state-file.md), [`docs/adr/0002-pre-digested-step-slices.md`](../../docs/adr/0002-pre-digested-step-slices.md), [`docs/adr/0003-strict-sequential-step-gating.md`](../../docs/adr/0003-strict-sequential-step-gating.md)
- Pipeline state engine: `scripts/clipping_state.py`
- Assembly engine: `scripts/clipping_assembly.py`
- GUI Companion sidecar: `scripts/gui_companion.py`
- Dual-channel preference codification: `scripts/clipping_preferences.py`

---

## Operating Protocol

Follow this 4-step sequence on every assembly run:

### 1. State & Pre-Flight Gate Inspection

Inspect pipeline readiness and enforce prerequisite Step 3 (`clipping-hook-hunter`) completion before executing timeline assembly:

```bash
python3 scripts/clipping_state.py validate --step clipping-assembly --dir <project-dir>
```

- **Exit Code `0`**: Gate cleared. Proceed to step 2.
- **Exit Code `2`**: Pre-flight gate blocked. Prerequisite viral hook hunting is incomplete or has an unreviewed checkpoint. Halt assembly immediately.
- Extract isolated Step Slice:
  ```bash
  python3 scripts/clipping_state.py get-step-config --step clipping-assembly --dir <project-dir>
  ```

### 2. Vertical Canvas Assembly & Dead Air Excision

Execute native vertical project assembly using `FcprojBuilder` with high-precision time base (`TICKS_PER_SEC = 254016000000`):

```bash
python3 scripts/clipping_assembly.py assemble \
  --media <path/to/raw_video.mp4> \
  --cuts <path/to/cuts.json> \
  --output-dir <project-dir> \
  --project-dir <project-dir> \
  --watermark <path/to/watermark.png> \
  --bgm <path/to/bgm.mp3> \
  --bgm-volume -18.0 \
  --sfx-volume -4.0
```

#### Assembly Specifications
- **Multi-Track Stack (4V / 3A)**:
  * **Track V1 (`Blurred Background`)**: Oversized background fill scaled to $209.78\%$ ($S_{fill} \times 1.18$) with `gaussian_blur` (blurriness $45.0$, `repeat_edge: true`) and opacity $40.0\%$.
  * **Track V2 (`Speaker Foreground`)**: Crisp speaker foreground crop scaled to $177.78\%$ ($S_{fill}$) with dynamic speaker ping-pong reframing (Host $x_c = 0.25$, Guest $x_c = 0.75$, Center $x_c = 0.50$) and rhetorical punch-ins ($1.06\times$, $1.12\times$, $1.22\times$). Phase-locked with dialogue on A1.
  * **Track V3 (`HUD & Overlays`)**: Dedicated layer for EffectCraft kinetic typography, chapter bumpers, and visual retention hooks.
  * **Track V4 (`Watermark`)**: Persistent campaign watermark logo scaled to $28.0\%$ centered at $(X=540, Y=280)$ spanning $100\%$ of timeline duration.
  * **Track A1 (`Dialogue`)**: Primary spoken speech at $0.0\text{ dB}$, phase-locked with V2 cuts.
  * **Track A2 (`Background Music`)**: Viral music bed ducked to $-18.0\text{ dB}$.
  * **Track A3 (`SFX`)**: Punctuation accents, swooshes, and audio hits set to $-4.0\text{ dB}$.
- **Dead Air Pruning & Consonant Buffer**:
  * Silences $> 0.40\text{s}$ between spoken sentences are excised.
  * Spoken word endings retain a $\tau_{pad} = 0.08\text{s}$ ($80\text{ ms}$) consonant protection buffer.
  * Collision guard ensures padding never collides with subsequent cut start: $\min(0.08, \max(0.0, t_{start}[i+1] - t_{end}[i] - 0.01))$.
  * Minimum sub-cut duration is clamped to $0.04\text{s}$.
- **Sidecar Manifest Generation**:
  Generates `<project_name>.meta.json` recording cut durations, anchor coordinates, and audio track baselines.

### 3. Live Companion Checkpoint & Timeline Inspection

Upon assembly completion, the engine stages project parameters into `.clipping_state.json` and automatically triggers the interactive companion checkpoint gate:

```bash
python3 scripts/clipping_state.py checkpoint --step clipping-assembly --dir <project-dir>
```

The checkpoint gate:
1. Pings the live FilmCraft GUI companion (`scripts/gui_companion.py`). If active on port `9876`, sends `file.openProject` / `file.revert` to reload the newly assembled vertical timeline on the human editor's screen instantly.
2. Creates an unedited agent baseline copy (`baseline_<name>.fcproj`).
3. Generates the interactive review artifact `checkpoint_clipping-assembly.md` with `RequestFeedback: true`.
4. Arms project file change detection (`.gui_companion_saved.flag`).

#### Operator Interactive Guidance
Direct the human operator to inspect the assembled vertical cut in FilmCraft:
```bash
python3 scripts/gui_companion.py seek --seconds 0.0
python3 scripts/gui_companion.py play
```

### 4. Feedback Registration & Step Approval

Collect human review or manual edits and approve the step:

1. **Option A: Register Chat Feedback / Directives**:
   ```bash
   python3 scripts/clipping_state.py checkpoint \
     --step clipping-assembly \
     --dir <project-dir> \
     --feedback "Keep camera on host for the first 5 seconds and increase punch-in on the punchline"
   ```
2. **Option B: Codify Manual GUI Edits**:
   If the operator adjusts clip framing, trims, or volume levels directly in FilmCraft and saves (`Ctrl+S`), run differential preference extraction:
   ```bash
   python3 scripts/clipping_state.py checkpoint \
     --step clipping-assembly \
     --dir <project-dir> \
     --diff-project
   ```
3. **Approve Step to Unblock Downstream Pipeline**:
   ```bash
   python3 scripts/clipping_state.py approve --step clipping-assembly --dir <project-dir>
   ```
   Verify downstream Step 5 (`clipping-captions`) is unblocked:
   ```bash
   python3 scripts/clipping_state.py validate --step clipping-captions --dir <project-dir>
   ```
   Exit code `0` confirms the gate is cleared.

---

## Completion Criteria

This skill is complete ONLY when all five conditions are met:
1. `.fcproj` vertical project file is assembled with valid schema version 12 and passes `filmcraft-cli inspect sequence`.
2. Standard 4V / 3A track stack is fully populated with exact scaling ($209.78\%$ V1, $177.78\%$ V2, $28\%$ V4) and audio baselines ($0\text{ dB}$ A1, $-18\text{ dB}$ A2, $-4\text{ dB}$ A3).
3. Dead air $> 0.40\text{s}$ is pruned with $0.08\text{s}$ consonant protection buffer.
4. `.clipping_state.json` has `steps["clipping-assembly"]` staged and review artifact `checkpoint_clipping-assembly.md` generated.
5. Checkpoint is reviewed/cleared and state engine registers approval via `clipping_state.py approve --step clipping-assembly`.
