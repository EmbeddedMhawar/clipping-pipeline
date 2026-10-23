---
name: clipping-vfx-sfx
description: Composite mandatory persistent brand watermark, HyperFrames 0–3s kinetic title hook graphic, color stabs/shock VFX, and synchronized SFX transients onto Remotion timeline tracks V3/V4 and A3 with live companion checkpoint gating.
---

# Visual Effects & Sound Design Compositing (clipping-vfx-sfx)

Step 6 visual effects (VFX) and sound design (SFX) compositing engine for the Antigravity Short-Form Clipping Pipeline. Enforces campaign compliance across rewarded creator programs (Whop, YouTube Shorts, TikTok, Instagram Reels) by placing a **mandatory persistent brand watermark** strictly safe from UI corners and caption safe zones, generating agent-authored **HyperFrames** (HTML/CSS/GSAP with `data-start`/`data-duration`) 0–3s kinetic title overlays and persistent hook badges on **Track V3** (`HUD & Overlays`), compositing psychological pattern-interrupt color stabs (Crimson Red `#FF0000` shock, Neon Acid Green `#CCFF00` absurdity/flex), and inserting synchronized audio transients (whooshes, sub-bass boom hits, mechanical pops) on **Track A3** (`SFX`) ducked to `-4.0dB`, while strictly guaranteeing zero background music beds and zero phonk rules. Triggers the live Remotion Studio / HyperFrames companion checkpoint gate for real-time timeline review and preference codification into `.clipping_preferences.json`.

Context pointers:
- Domain terminology: [`GLOSSARY.md`](../../GLOSSARY.md)
- Official HyperFrames 12-point deterministic seek contract & CLI skills: [`skills/hyperframes/SKILL.md`](../hyperframes/SKILL.md), [`skills/hyperframes/references/format.md`](../hyperframes/references/format.md), [`skills/hyperframes-cli/SKILL.md`](../hyperframes-cli/SKILL.md), [`docs/research/remotion-hyperframes-official-skills.md`](../../docs/research/remotion-hyperframes-official-skills.md)
- Campaign brief schema: [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md)
- Architectural decisions: [`docs/adr/0001-project-local-json-state-file.md`](../../docs/adr/0001-project-local-json-state-file.md), [`docs/adr/0002-pre-digested-step-slices.md`](../../docs/adr/0002-pre-digested-step-slices.md), [`docs/adr/0003-strict-sequential-step-gating.md`](../../docs/adr/0003-strict-sequential-step-gating.md), [`docs/adr/0012-remotion-and-hyperframes-rendering-engine.md`](../../docs/adr/0012-remotion-and-hyperframes-rendering-engine.md)
- State engine CLI: `scripts/clipping_state.py`
- VFX & SFX engine: `scripts/clipping_vfx_sfx.py`
- GUI Companion sidecar: `scripts/gui_companion.py`
- Dual-channel preference codification: `scripts/clipping_preferences.py`

---

## Operating Protocol

Follow this 5-step sequence on every VFX/SFX execution:

### 1. State & Pre-Flight Gate Inspection

Inspect pipeline readiness and enforce prerequisite Step 5 (`clipping-captions`) completion before executing VFX/SFX injection:

```bash
python3 scripts/clipping_state.py validate --step clipping-vfx-sfx --dir <project-dir>
```

- **Exit Code `0`**: Gate cleared. Proceed to step 2.
- **Exit Code `2`**: Pre-flight gate blocked. Prerequisite captioning is incomplete or has an unreviewed checkpoint. Halt immediately.
- Extract the isolated Step Slice:
  ```bash
  python3 scripts/clipping_state.py get-step-config --step clipping-vfx-sfx --dir <project-dir>
  ```

### 2. VFX & SFX Asset Synthesis and Timeline Injection

Execute the VFX & SFX compositing engine using `clipping_vfx_sfx.py`:

```bash
python3 scripts/clipping_vfx_sfx.py generate \
  --project-dir <project-dir>
```

#### Core Specifications & Compliance Rules

1. **Persistent Brand Watermark (Track V4)**:
   - **Compliance Rule**: Mandatory across rewarded campaigns. Must persist across $100\%$ of clip duration.
   - **Disallowed Zones**: Strictly banned in the 4 screen corners (blocked by TikTok/Shorts UI HUD, profile icons, sound marquee) and chest/mic caption area (`margin_v: 420px`).
   - **Placement Anchor**: Top-center (`X=540px, Y=280px` in a 1080×1920 canvas) or bottom-center (`X=540px, Y=1380px` above captions).
   - **Scale & Opacity**: Scale factor `28.0%` (`0.28`), opacity `100.0%` (or `85.0%` per brief).
   - If no watermark asset file is provided, the engine automatically synthesizes a high-contrast brand badge PNG (`assets/watermark_brand.png`).

2. **0–3s Kinetic Title Overlays & Persistent Hook Badges (Track V3)**:
   - **Pattern Interrupt**: 0–2.8s dynamic curiosity title hook or full-duration persistent hook pill floating at `Y=160px` (`persistent_white_pill_overlay.png`).
   - **Safe Zone**: Upper third (`Y=160px` to `Y=300px`), clearing platform headers while floating comfortably above speaker faces.

3. **Color Stabs & Shock VFX (Track V3 via HyperFrames)**:
   - Authored as declarative HyperFrames HTML/CSS/GSAP compositions (`.hyperframes.html` with `data-composition-id`, `data-start`, `data-duration`) and rendered as transparent Apple ProRes 4444 (`yuva444p10le`) intermediate passes via `hyperframes render` or `ffmpeg`:
     - **Crimson Red Shock (`#FF0000`, 10–15 frames, ~0.45s)**: Placed at shock, screaming, and disbelief moments (derived from cues annotated with `*PURE SHOCK*`, `*SCREAMING CHAOS*`, `*MOUTH AGAPE*`). Set to `Difference` or `Add` blend mode with cubic opacity decay.
     - **Neon Acid Green Flex (`#CCFF00`, 10–14 frames, ~0.45s)**: Placed at high-value card pulls, flexes, and destiny moments (`*GRAIL PULL*`, `*100% DESTINY*`, `*CELEBRATION*`).
     - **White Bloom / Flash (`#FFFFFF`, 6–8 frames, ~0.22s)**: Placed at active speaker punch-ins and pacing transitions.

4. **Sound Design Transients (Track A3)**:
   - **Strict Zero-BGM & Zero-Phonk Rule**: No background music beds or phonk tracks permitted.
   - **Transient Pairings**:
     - Hook start ($T=0.0\text{s}$): Whoosh in transient (`whoosh_in.wav`) or acoustic pop (`pop_clean.wav`).
     - Shock stabs: Sub-bass boom impact (`sub_boom_tight.wav`) with exponential pitch drop (95Hz $\to$ 32Hz).
     - Flex moments: Fast frequency-swept whoosh accent (`whoosh_in.wav`).
   - **Ducking Level**: All SFX clips leveled to `-4.0dB` to preserve vocal clarity.

5. **Track Architecture in Remotion (`.remotion.json`)**:
   ```
   [Track V4]  Watermark (Persistent brand badge, scale 28%, Y=280)                         <-- STEP 6
   [Track V3]  HUD & Overlays (HyperFrames title hook badge, color stabs, ProRes VFX passes) <-- STEP 6
   [Track V2]  Speaker Foreground (1080x1920 Smart-Center Face Crop, Active Speaker)
   [Track V1]  Blurred Background (45px Gaussian blur, 40% opacity)
   ──────────────────────────────────────────────────────────────────────────────────
   [Track A1]  Dialogue (Master dialogue leveled to -3dB peak)
   [Track A2]  Background Music (Muted / Empty)
   [Track A3]  SFX (Sound design transients ducked to -4.0dB)                              <-- STEP 6
   ```

### 3. Live Companion Checkpoint & Preference Codification

The engine generates `vfx_manifest.json` and triggers the live Remotion Studio companion checkpoint gate:

```bash
python3 scripts/clipping_state.py checkpoint --step clipping-vfx-sfx --dir <project-dir>
```

The checkpoint gate:
1. Pings the live Remotion Studio companion (`scripts/gui_companion.py`). If active on port `9876`, sends `file.open` / `file.revert` to reload the project with the new HyperFrames VFX and SFX layers.
2. Generates the interactive review artifact `checkpoint_clipping-vfx-sfx.md` with `RequestFeedback: true`.
3. Records visual overlay count, SFX transient count, and compliance parameters into `.clipping_state.json`.

#### Operator Interactive Guidance
Direct the human operator to inspect the composite timeline in Remotion Studio:
```bash
python3 scripts/gui_companion.py seek --seconds 0.0
python3 scripts/gui_companion.py play
```

### 4. Feedback Registration & Step Approval

Collect human review or manual edits and approve the step:

1. **Option A: Register Chat Feedback / Directives**:
   ```bash
   python3 scripts/clipping_state.py checkpoint \
     --step clipping-vfx-sfx \
     --dir <project-dir> \
     --feedback "Shift watermark Y down by 20px and make red shock 5 frames longer"
   ```
2. **Option B: Approve Step to Unblock Downstream Pipeline**:
   ```bash
   python3 scripts/clipping_state.py approve --step clipping-vfx-sfx --dir <project-dir>
   ```
   Verify downstream Step 7 (`clipping-qc-packager`) is unblocked:
   ```bash
   python3 scripts/clipping_state.py validate --step clipping-qc-packager --dir <project-dir>
   ```
   Exit code `0` confirms the gate is cleared.

### 5. Post-Step Summary & Conversation Handoff

Following approval:
1. Concisely summarize what was completed (persistent watermark placed on Track V4, persistent hook badge on Track V3, color stabs composited, SFX transients inserted on Track A3 ducked to -4dB, zero-BGM rule verified, and companion checkpoint cleared).
2. Instruct the user to open a new conversation to run Step 7 (`clipping-qc-packager`).
3. Provide the exact copy-paste prompt formatted strictly as:
   ```text
   Campaign: <Campaign Title> (<campaign-slug>) proceed with Step 7 (clipping-qc-packager)
   ```

---
