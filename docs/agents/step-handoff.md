# Step Handoff Protocol

Protocol for transitioning between steps in the 8-step Short-Form Clipping Pipeline across separate conversations.

## Why Multi-Conversation Handoff?

The clipping pipeline spans 8 sequential, computationally and analytically intensive phases (from guidelines ingestion, proxy download and Whisper transcription, to hook hunting, timeline assembly, kinetic captions, VFX/SFX compositing, QC packaging, and multi-platform publishing).

Running all 8 steps in a single conversation leads to:
1. **Context saturation & token bloat**: Large transcript segments, candidate timestamps, and `.remotion.json` track structures consume significant context.
2. **Attention degradation**: Models lose fidelity over specific guideline constraints (safe zones, loudness bounds, watermark positions) as conversations grow long.
3. **Hallucination risk**: Early discussion artifacts bleed into later editing instructions.

Because all pipeline state, parameter slices, proxy paths, and checkpoint decisions are persisted on disk (`.clipping_state.json`), each step executes with maximum focus in a fresh conversation.

## Mandatory Handoff Protocol

Upon completing and approving any pipeline step (via `python3 scripts/clipping_state.py approve --step <step>`):

### 1. Explain What Was Done
Provide the user with a concise summary of what was accomplished, including:
- Concrete outputs generated (e.g. proxy files, `transcript.json`, `contact_sheets.json`, `.remotion.json`, `.hyperframes.html`, renders).
- Decisions codified and state changes applied.
- Pre-flight clearance confirmed for the next step.

### 2. Instruct Conversation Handoff
Explicitly notify the user that to preserve context clarity, the next step should be executed in a new conversation.

### 3. Provide the Next-Step Prompt
Give the user the exact prompt to copy and paste into the new conversation, formatted strictly as:

```text
Campaign: <Campaign Title> (<campaign-slug>) proceed with Step <N> (<step-name>)
```

#### Field Substitutions:
- `<Campaign Title>`: The human-readable campaign title (from `state["campaign"]["title"]` or brief).
- `<campaign-slug>`: The project slug (from `state["campaign"]["project"]` or project directory name).
- `<N>`: The sequential step number (1–8) for the *next* step.
- `<step-name>`: The exact canonical step name for the *next* step:
  - Step 1: `clipping-guidelines`
  - Step 2: `clipping-transcription`
  - Step 3: `clipping-hook-hunter`
  - Step 4: `clipping-assembly`
  - Step 5: `clipping-captions`
  - Step 6: `clipping-vfx-sfx`
  - Step 7: `clipping-qc-packager`
  - Step 8: `clipping-publisher`

#### Concrete Example:
When Step 3 (`clipping-hook-hunter`) is approved for campaign "HardScope — Unpacked Episode 2":
```text
Campaign: HardScope — Unpacked Episode 2 (hardscope-unpacked-episode-2) proceed with Step 4 (clipping-assembly)
```
