---
name: clipping-transcription
description: Extract audio, generate word-level timestamped transcripts, diarize speakers, apply phonetic correction, and generate visual contact sheets.
---

# Audio Extraction & Word-Level Transcription (clipping-transcription)

Step 2 of the Short-Form Clipping Pipeline. Extracts high-fidelity dialogue audio (48kHz WAV), generates millisecond-accurate word-level timestamped transcripts, diarizes host and guest speakers, applies phonetic and brand corrections, and generates 3×3 or 4×4 visual contact sheets (`contact_sheets.json`) to visually ground downstream viral hook hunting (`clipping-hook-hunter`) and timeline assembly (`clipping-assembly`).

Context pointers:
- Domain terminology: [`GLOSSARY.md`](../../GLOSSARY.md)
- Campaign Brief Schema: [`references/CAMPAIGN_BRIEF_SCHEMA.md`](../../references/CAMPAIGN_BRIEF_SCHEMA.md)
- Architectural decisions: [`docs/adr/0011-hardware-accelerated-proxy-generation.md`](../../docs/adr/0011-hardware-accelerated-proxy-generation.md)
- Pipeline state engine: `scripts/clipping_state.py`
- Source downloader & proxy engine: `scripts/download_source.py` & `scripts/generate_proxy.py`
- Transcription engine: `scripts/clipping_transcription.py`
- Contact sheets generator: `scripts/generate_contact_sheets.py`

---

## Operating Protocol

Follow this sequential protocol on every transcription run:

### 1. State & Pre-Flight Gate Inspection

Enforce that Step 1 (`clipping-guidelines`) is approved before executing transcription:

```bash
python3 scripts/clipping_state.py validate --step clipping-transcription --dir <project-dir>
```

- **Exit Code `0`**: Gate cleared. Proceed with execution.
- **Exit Code `2`**: Pre-flight gate blocked. Guidelines unapproved. Halt immediately.
- Extract isolated Step Slice:
  ```bash
  python3 scripts/clipping_state.py get-step-config --step clipping-transcription --dir <project-dir>
  ```

### 2. Source Video Download & Hardware Proxy Generation (If not already present)

If the raw video is not yet downloaded in `<project-dir>/raw/`, download the source media from `campaign_brief.json` and immediately generate a hardware-accelerated editing proxy:

```bash
python3 scripts/download_source.py --dir <project-dir>
```

This downloads `<project-dir>/raw/<slug>.mp4` via `yt-dlp` and generates `<project-dir>/raw/Proxies/<slug>_Proxy.mp4` with a 1-second GOP and half-resolution (e.g. 960×540 for 1080p), utilizing host hardware silicon (VAAPI, NVENC, VideoToolbox, QSV, or CPU `libx264`).

### 3. Audio Extraction & Word-Level Transcription

Execute the transcription CLI engine:

```bash
python3 scripts/clipping_transcription.py transcribe --dir <project-dir>
```

Optional arguments:
- `--media <path>`: Explicit path to raw video file if located outside `<project-dir>/raw/`.
- `--model <base|small|medium|large-v3>`: Faster-Whisper model size (defaults to `base`).
- `--force`: Force re-extraction of audio and re-transcription.

#### Processing Pipeline:
1. **Audio Extraction**: Extracts 16-bit PCM WAV at 48kHz stereo to `<project-dir>/raw/<project>_audio.wav`.
2. **Word-Level Timing**: Ingests millisecond-accurate word timings and probabilities (`word`, `start`, `end`, `probability`).
3. **Speaker Diarization**: Alternates and attributes speaker turns between Host (e.g. `MatCrackz`, $x_c = 0.25$) and Guest (e.g. `YourRAGE`, $x_c = 0.75$).
4. **Phonetic & Brand Fixes**: Applies word boundary regex substitutions from `phonetic_dictionary` (e.g. correcting misheard creator names, show titles, and brand vocabulary).
5. **Visual Contact Sheets**: Automatically generates 4×4 contact sheets (`sheet_0001.jpg` ... `sheet_NNNN.jpg`) and `contact_sheets.json` index with burnt-in timecodes at 120s intervals (`python3 scripts/generate_contact_sheets.py`).

### 4. Verification & Pipeline State Approval

Confirm that `<project-dir>/transcript.json` and `<project-dir>/contact_sheets/contact_sheets.json` exist, then record step completion in the state engine:

```bash
python3 scripts/clipping_state.py approve --step clipping-transcription --dir <project-dir>
```

Verify state advancement:

```bash
python3 scripts/clipping_state.py status --dir <project-dir>
```

Pre-flight gate for Step 3 (`clipping-hook-hunter`) is now unblocked.

### 5. Post-Step Summary & Conversation Handoff
Following approval:
1. Concisely summarize what was completed (source download / hardware-accelerated proxy generation, 48kHz audio extraction, word-level Whisper transcription, speaker diarization, phonetic correction, and contact sheet generation).
2. Instruct the user to open a new conversation to run Step 3 (`clipping-hook-hunter`).
3. Provide the exact copy-paste prompt formatted as:
   ```text
   Campaign: <Campaign Title> (<campaign-slug>) proceed with Step 3 (clipping-hook-hunter)
   ```
