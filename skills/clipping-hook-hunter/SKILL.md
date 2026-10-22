---
name: clipping-hook-hunter
description: Locate viral curiosity gaps and 0–3s hook windows by evaluating transcript word timings alongside visual contact sheets, scoring candidate moments within duration bounds, and generating targeted candidate contact sheets.
---

# Viral Hook Hunting & Candidate Ranking (clipping-hook-hunter)

Step 3 of the Short-Form Video Clipping Pipeline. Analyzes word-level timestamped transcripts (`transcript.json`) and visual contact sheets (`contact_sheets/contact_sheets.json`) to discover, score, and rank viral short-form candidate clips (TikTok, YouTube Shorts, Instagram Reels) within strict campaign duration bounds. Evaluates candidate moments against the 5 viral retention pillars: 0–3s opening pattern interrupts, visual reaction spikes (streamer freak-outs, face palms, desk slams, physical humor), infinite loop viability, speech density, and comedic gag markers. Generates targeted candidate contact sheets (`candidates/sheet_<id>.jpg`) and stages the feedback checkpoint gate for human clip selection.

Context pointers:
- Domain terminology: [`GLOSSARY.md`](../../GLOSSARY.md)
- Campaign brief schema: [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md)
- Architectural decisions: [`docs/adr/0001-project-local-json-state-file.md`](../../docs/adr/0001-project-local-json-state-file.md), [`docs/adr/0002-pre-digested-step-slices.md`](../../docs/adr/0002-pre-digested-step-slices.md), [`docs/adr/0003-strict-sequential-step-gating.md`](../../docs/adr/0003-strict-sequential-step-gating.md)
- Pipeline state engine: `scripts/clipping_state.py`
- Hook hunter engine: `scripts/clipping_hook_hunter.py`
- Contact sheets generator: `scripts/generate_contact_sheets.py`

---

## Operating Protocol

Follow this deterministic sequence on every viral hook hunting run:

### 1. State & Pre-Flight Gate Inspection

Enforce that Step 2 (`clipping-transcription`) is completed and approved before running hook hunting:

```bash
python3 scripts/clipping_state.py validate --step clipping-hook-hunter --dir <project-dir>
```

- **Exit Code `0`**: Gate cleared. Proceed to candidate discovery.
- **Exit Code `2`**: Pre-flight gate blocked. Prerequisite transcription is incomplete or unapproved. Halt immediately.
- Extract isolated Step Slice:
  ```bash
  python3 scripts/clipping_state.py get-step-config --step clipping-hook-hunter --dir <project-dir>
  ```

### 2. Candidate Discovery & Viral Scoring

Execute the hook hunter CLI engine:

```bash
python3 scripts/clipping_hook_hunter.py hunt --dir <project-dir>
```

Optional arguments:
- `--media <path>`: Explicit path to raw video file for targeted candidate contact sheet generation.
- `--output <path>`: Output destination for candidates JSON (default: `<project-dir>/candidates.json`).
- `--no-sheets`: Skip generating targeted candidate contact sheets.
- `--no-checkpoint`: Skip staging the feedback checkpoint in `.clipping_state.json`.
- `--json`: Output machine-readable JSON summary.

#### The 5 Viral Pillars Evaluated:
1. **0–3s Opening Hook Strength (0–10)**: Evaluates the opening window for pattern interrupts, high-stakes dollar figures, direct questions, or extreme streamer disbelief.
2. **Visual Reaction Spikes & Physical Humor (0–10)**: Inspects visual contact sheets for physical comedy, trembling hands, screaming, hysterical laughter, or desk slams that dialogue transcripts miss.
3. **Infinite Loop Viability (0–10)**: Tests whether the final thought/cadence phonetically or syntactically bridges back into the opening hook phrase.
4. **Comedic Gag & Inaudible Markers**: Identifies muddled creator outbursts or audio gag points (`*INAUDIBLE*`, `[laughter]`).
5. **Speech Density & Conversational Cadence**: Calculates words per second (target: 2.4–3.8 wps) and dead air ratio to ensure fast, engaging pacing.

### 3. Targeted Candidate Contact Sheets

To provide complete visual verification for candidate selection, the hook hunter invokes `scripts/generate_contact_sheets.py` in `-m candidates` mode with a 3×3 grid:

```bash
python3 scripts/generate_contact_sheets.py \
  -i <raw-video.mp4> \
  -o <project-dir>/contact_sheets/candidates \
  -m candidates \
  -c <project-dir>/candidates.json \
  -g 3x3
```

This outputs high-density visual grids (`candidate_<slug>.jpg`) with burnt-in timecodes capturing every key reaction frame across the candidate moment.

### 4. Interactive Checkpoint Gate & Candidate Selection

1. The hook hunter writes `candidates.json` and stages `checkpoint_clipping_hook_hunter.md` in `<project-dir>`.
2. A structured Markdown artifact (`RequestFeedback: true`) is rendered for the operator displaying the ranked candidate table with viral scores, hook quotes, and contact sheet visual cues.
3. The human operator selects their preferred candidate clip ID (or provides boundary adjustments).
4. Upon user confirmation, record step approval:
   ```bash
   python3 scripts/clipping_state.py approve --step clipping-hook-hunter --dir <project-dir>
   ```
5. Pipeline state unblocks Step 4 (`clipping-assembly`).

### 5. Post-Step Summary & Conversation Handoff
Following approval:
1. Concisely summarize what was completed (candidate viral hooks scored, contact sheet visual hooks verified, and winning candidate clip selected).
2. Instruct the user to open a new conversation to run Step 4 (`clipping-assembly`).
3. Provide the exact copy-paste prompt formatted as:
   ```text
   Campaign: <Campaign Title> (<campaign-slug>) proceed with Step 4 (clipping-assembly)
   ```
