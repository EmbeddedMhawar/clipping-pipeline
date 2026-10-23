---
name: clipping-assembly
description: Assemble 9:16 vertical video projects (.remotion.json + React/TypeScript composition bundle) for Remotion with multi-track layout (4V/3A stack), speaker ping-pong reframing, dead air excision with consonant buffer, and live Remotion Studio companion checkpoint gating.
---

# Timeline Assembly & Vertical Framing (clipping-assembly)

Step 4 timeline rough-cut assembly engine for the Antigravity Short-Form Clipping Pipeline. Transforms raw landscape footage into high-retention 9:16 vertical video projects (`.remotion.json` and `remotion/ClipComposition.tsx`) adhering to the Remotion 4.0 multi-track composition schema. Implements a 4-video / 3-audio track hierarchy, speaker ping-pong reframing, consonant-protected dead air excision, persistent brand watermarking, and triggers the live Remotion Studio companion checkpoint gate for operator review and preference codification.

Context pointers:
- Domain terminology: [`GLOSSARY.md`](../../GLOSSARY.md)
- Official Remotion skills & interactivity rules: [`skills/remotion-best-practices/SKILL.md`](../remotion-best-practices/SKILL.md), [`skills/remotion-best-practices/remotion-interactivity/REFERENCE.md`](../remotion-best-practices/remotion-interactivity/REFERENCE.md), [`docs/research/remotion-hyperframes-official-skills.md`](../../docs/research/remotion-hyperframes-official-skills.md)
- Native vertical assembly specification: [`docs/research/fcproj-assembly-spec.md`](../../docs/research/fcproj-assembly-spec.md)
- Architectural decisions: [`docs/adr/0001-project-local-json-state-file.md`](../../docs/adr/0001-project-local-json-state-file.md), [`docs/adr/0002-pre-digested-step-slices.md`](../../docs/adr/0002-pre-digested-step-slices.md), [`docs/adr/0003-strict-sequential-step-gating.md`](../../docs/adr/0003-strict-sequential-step-gating.md), [`docs/adr/0011-hardware-accelerated-proxy-generation.md`](../../docs/adr/0011-hardware-accelerated-proxy-generation.md), [`docs/adr/0012-remotion-and-hyperframes-rendering-engine.md`](../../docs/adr/0012-remotion-and-hyperframes-rendering-engine.md)
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

Execute native vertical project assembly using `RemotionBuilder` with high-precision time base (`TICKS_PER_SEC = 254016000000`):

```bash
python3 scripts/clipping_assembly.py assemble \
  --media <path/to/raw_video.mp4> \
  --proxy <path/to/raw/Proxies/<name>_Proxy.mp4> \
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
  * **Track V2 (`Speaker Foreground`)**: Crisp speaker foreground crop scaled to $177.78\%$ ($S_{fill}$) with dynamic speaker ping-pong reframing and rhetorical punch-ins ($1.06\times$, $1.12\times$, $1.22\times$). Phase-locked with dialogue on A1.
  * **Track V3 (`HUD & Overlays`)**: Dedicated layer for HyperFrames HTML/CSS/GSAP kinetic typography, chapter bumpers, and visual retention hooks.
  * **Track V4 (`Watermark`)**: Persistent campaign watermark logo scaled to $28.0\%$ centered at $(X=540, Y=280)$ spanning $100\%$ of timeline duration.
  * **Track A1 (`Dialogue`)**: Primary spoken speech at $0.0\text{ dB}$, phase-locked with V2 cuts.
  * **Track A2 (`Background Music`)**: Viral music bed ducked to $-18.0\text{ dB}$.
  * **Track A3 (`SFX`)**: Punctuation accents, swooshes, and audio hits set to $-4.0\text{ dB}$.

- **Visual Shot Boundary Cutting vs Speech Pauses**:
  * In multi-camera productions, camera angles switch *mid-sentence*, and reaction shots (gasps, laughter, mouth covering) occur while the other person is speaking.
  * Never slice clips exclusively along Whisper transcription sentence boundaries. Evaluate contact sheets or frame vision analysis to razor-cut on visual camera switches, framing active reactors or wide 2-shots appropriately.
  * In wide 2-shots, ping-pong dynamically between speakers or cut to the speaker delivering the punchline/hero phrase (e.g. razor-cutting mid-segment from $x_c \approx 0.28$ to $x_c \approx 0.72$).

- **Zero-Bleed Cut Boundary Alignment (+1 / -1 Frame Guard)**:
  * In multi-cam footage, cutting across raw float timestamps often leaks a single bleeding frame of the previous or subsequent camera shot (e.g., a 1-frame flash on a cut transition).
  * Every cut boundary must be aligned with true camera switch frames:
    - **In-Points**: Pad $+0.042\text{s}$ ($+1$ frame guard at 24fps) after a prior camera angle tail.
    - **Out-Points**: Trim $-0.042\text{s}$ ($-1$ frame guard at 24fps) before the next camera angle starts.
  * Ensures 100% clean, flicker-free cut transitions with zero bleeding past-frames.

- **Continuous Shot Preservation (Never Fragment Unbroken Takes)**:
  * When the physical camera angle does not switch (e.g., an unbroken reaction shot or an overhead desk peel), preserve the footage as **ONE continuous cut**.
  * Never slice a continuous take into artificial sub-cuts just to change zoom or pan. Use **multi-point keyframe animation** (`x_keyframes` and `punch_keyframes`) within the single cut item.

- **Multi-Point Kinetic Transformations (`x_keyframes` & `punch_keyframes`)**:
  * Instead of static crops or primitive 2-point linear pans across the entire cut, Remotion supports multi-point keyframe arrays:
    - `x_keyframes: Array<{ t: number, xc: number }>`
    - `punch_keyframes: Array<{ t: number, punch: number }>`
  * Evaluated deterministically with `interpolate(curSec, ..., { easing: Easing.inOut(Easing.quad) })`.
  * **Hard Crash Zooms**: 3–5 frame fast whip zooms (e.g. $t=4.29\text{s} \to t=4.46\text{s}$, $punch: 0.43\times \to 1.28\times$, $x_c: 0.37 \to 0.12$) to punch directly into revealed cards or facial reactions.

- **Offline Computer-Vision Pre-Pass (`scripts/cv_reframe_tracker.py`)**:
  * Execute offline face/pose detection in Python before Remotion rendering using OpenCV YuNet (`face_detection_yunet_2023mar.onnx`, 228 KB, <5ms per frame, 0 GPU bloat).
  * **Target Disambiguation**: In 2-shots, lock onto the intended speaker using minimum Euclidean horizontal distance to initial anchor.
  * **Virtual Tripod Deadband ($\pm 0.035$)**: Keep camera perfectly stationary during small head bobs; only track intentional leaning.
  * **Lookahead Smoothing**: Bidirectional EMA filter for smooth cinematic pans.
  * **RDP Simplification ($\epsilon = 0.005$)**: Condenses trajectory into sparse `{ t, xc }` keyframes stored cleanly in `Root.tsx` / `props.json`.

- **Mathematical Viewport Edge Clamping ($w_{\text{half}}$)**:
  * When punched in ($punch \ge 0.95$), visible half-width is:
    $$w_{\text{half}} = \frac{W_{\text{canvas}}}{2 \cdot W_{\text{src}} \cdot S} = \frac{1080}{2 \cdot 1920 \cdot \text{scale}}$$
  * Clamp $x_c$ to $[w_{\text{half}}, 1 - w_{\text{half}}]$ in `ClipComposition.tsx`. Mathematically guarantees that dynamic camera pans never expose the blurred background or black margin at the edges of the 16:9 source.

- **Real Speaker Identity Mapping (Zero Generic "Host/Guest")**:
  * Always tag speakers by their real names (e.g. `MatCrackz`, `YourRAGE`, `N3on`) across `cuts.json`, `Root.tsx`, and the HUD overlay badge. Generic `"host"`/`"guest"` strings cause tracking ambiguity in multi-guest setups and make Props editing confusing.

- **Statically Analyzable Remotion Root & Live Editing HUD Badge**:
  * In `Root.tsx`, declare composition `id` as a JSX string literal and `defaultProps` as an inline object literal so Remotion Studio's Props panel can edit and persist parameters directly back to source code without warnings.
  * Render a high-contrast HUD badge (`CUT #N | SPEAKER | xc: ... | punch: ...`) during Studio preview (`!isRendering && showDebugBadge`) to give the human editor instant frame-by-frame visual feedback, automatically excluded during final rendering.

- **Dynamic Punch-Outs & Safe-Zone Scaling for Overlays & Graphics**:
  * When on-screen graphics appear (e.g. trading card previews, valuation badges, lower thirds) or full-table celebratory reactions occur, standard foreground zoom ($177\%-209\%$) will cut off text and price tags.
  * Apply **Punch-Out Unzooms** with scale tuned down to **`70%–85%`** (e.g., $76.4\%$) and blurred background on V1 (`gaussian_blur: 45.0`, `opacity: 40.0%`). This ensures card artwork, autographs, and valuation callouts remain $100\%$ visible inside the 9:16 vertical safe zone.

- **Hardware-Decodable Proxy Workflow for Heavy Codecs (AV1)**:
  * When source footage is encoded in AV1 or heavy formats on systems without hardware decode support (e.g., Intel 8th-gen UHD Graphics 620), dual-track vertical compositing causes severe playback stutter in Remotion Studio.
  * Automatically generate and attach an ultra-fast H.264 Baseline half-resolution proxy via `scripts/generate_proxy.py` (or `ffmpeg`):
    ```bash
    mkdir -p <project-dir>/raw/Proxies
    ffmpeg -y -i <project-dir>/raw/<media>.mp4 \
      -vf "scale=960:540,format=yuv420p" \
      -c:v libx264 -preset ultrafast -tune fastdecode -crf 22 \
      -c:a aac -b:a 128k -movflags +faststart \
      <project-dir>/raw/Proxies/<media>_Proxy.mp4
    ```
  * `clipping_assembly.py` automatically links `<project-dir>/raw/Proxies/<media>_Proxy.mp4` into the `.remotion.json` Media item for `<OffthreadVideo>` playback.

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
1. Pings the live Remotion Studio companion (`scripts/gui_companion.py`). If active on port `9876`, sends `file.open` / `file.revert` to reload the newly assembled vertical timeline on the human editor's screen instantly.
2. Creates an unedited agent baseline copy (`baseline_<name>.remotion.json`).
3. Generates the interactive review artifact `checkpoint_clipping-assembly.md` with `RequestFeedback: true`.
4. Arms project file change detection (`.gui_companion_saved.flag`).

#### Operator Interactive Guidance
Direct the human operator to inspect the assembled vertical cut in Remotion Studio:
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
   If the operator adjusts clip framing, trims, or volume levels in the `.remotion.json` project and saves (`Ctrl+S`), run differential preference extraction:
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

### 5. Post-Step Summary & Conversation Handoff
Following approval:
1. Concisely summarize what was completed (vertical 9:16 `.remotion.json` timeline and React composition bundle assembled, multi-track audio/video mapped, dead air excised with consonant preservation, and GUI companion checkpoint cleared).
2. Instruct the user to open a new conversation to run Step 5 (`clipping-captions`).
3. Provide the exact copy-paste prompt formatted as:
   ```text
   Campaign: <Campaign Title> (<campaign-slug>) proceed with Step 5 (clipping-captions)
   ```

---

## Completion Criteria

This skill is complete ONLY when all five conditions are met:
1. `.remotion.json` vertical project file and `remotion/` React composition bundle are assembled and pass `clipping_assembly.py inspect --verify-cli`.
2. Standard 4V / 3A track stack is fully populated with exact scaling ($209.78\%$ V1, $177.78\%$ V2, $28\%$ V4) and audio baselines ($0\text{ dB}$ A1, $-18\text{ dB}$ A2, $-4\text{ dB}$ A3).
3. Dead air $> 0.40\text{s}$ is pruned with $0.08\text{s}$ consonant protection buffer.
4. `.clipping_state.json` has `steps["clipping-assembly"]` staged and review artifact `checkpoint_clipping-assembly.md` generated.
5. Checkpoint is reviewed/cleared and state engine registers approval via `clipping_state.py approve --step clipping-assembly`.
