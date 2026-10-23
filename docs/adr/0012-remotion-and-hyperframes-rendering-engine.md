# 0012: Remotion and HyperFrames Rendering & Motion Graphics Engine

Short-form vertical video clipping requires both a deterministic, frame-accurate multi-track video/audio/caption timeline compositor (Step 4 `clipping-assembly` and Step 5 `clipping-captions`) and an agile, agent-native motion graphics generator for 0–3s kinetic title hooks, HUD callouts, and pattern-interrupt color stabs (Step 6 `clipping-vfx-sfx`).

We adopt **Remotion** (`@remotion/core`, `@remotion/cli`, `@remotion/captions`) for core 9:16 vertical timeline assembly and caption track synchronization, paired with **HyperFrames** (HTML/CSS/GSAP compositions with `data-composition-id`, `data-start`, and `data-duration` attributes) for kinetic title hooks and VFX overlays.

## Status

Accepted

## Considered Options

- **Desktop NLE + Proprietary VFX Project Formats**: Coupling timeline assembly and motion graphics to desktop-specific NLE project files and JSX script bridges. Rejected in favor of web-native, declarative React/TypeScript (Remotion) and HTML/CSS/GSAP (HyperFrames) formats that AI coding agents can author, inspect, and diff directly without proprietary binary lock-in.
- **Remotion Only**: Using Remotion React components for both long-form source slicing and bespoke one-off motion graphics overlays. While Remotion excels at `<OffthreadVideo>` multi-track cutting and `@remotion/captions` pagination, pure HTML/CSS/GSAP via HyperFrames is faster and lighter for self-contained 0–3s title cards and color stab passes.
- **Hybrid Remotion + HyperFrames Pipeline**:
  - **Step 4 (`clipping-assembly`)**: `RemotionBuilder` constructs `<project_name>.remotion.json` (preserving the 4-video / 3-audio track stack, speaker ping-pong coordinates, and consonant-buffered dead air pruning) alongside an executable `remotion/` React/TypeScript bundle (`Root.tsx`, `ClipComposition.tsx`, `props.json`).
  - **Step 5 (`clipping-captions`)**: `inject_captions_into_remotion` populates native `@remotion/captions` tracks (`Dialogue Captions` and `Emotion Callouts` at `MarginV=420`) directly in `.remotion.json` and `remotion/props.json`.
  - **Step 6 (`clipping-vfx-sfx`)**: Synthesizes declarative `.hyperframes.html` HTML/CSS/GSAP compositions for 0–3s kinetic title hooks and shock/flex color stabs, renders overlay passes via `hyperframes render` (with deterministic `ffmpeg` fallback), and injects them onto Track V3/V4 and Track A3 of `.remotion.json`.

## Consequences

- `scripts/clipping_assembly.py` uses `RemotionBuilder` to output `.remotion.json` and `remotion/{Root.tsx,ClipComposition.tsx,props.json}` with zero external Python runtime dependencies.
- `scripts/clipping_captions.py` injects `@remotion/captions` tracks directly into `.remotion.json`.
- `scripts/clipping_vfx_sfx.py` authors `.hyperframes.html` compositions and composites them into `.remotion.json`.
- `scripts/gui_companion.py` and `scripts/clipping_preferences.py` manage live Remotion Studio companion reload/seek/watch operations and Channel 2 differential preference extraction on `.remotion.json` files.
