#!/usr/bin/env python3
"""
clipping_transcription.py - Step 2: Audio Extraction, Transcription, Diarization, and Visual Grounding.

Extracts high-fidelity dialogue audio (48kHz WAV), generates millisecond-accurate word-level
timestamped transcripts, diarizes host and guest speakers, applies phonetic and brand corrections,
and coordinates visual contact sheet generation for downstream viral hook hunting and timeline assembly.
"""

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_video_duration(video_path: Path) -> float:
    """Retrieve video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video_path.resolve())
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        try:
            data = json.loads(res.stdout)
            return float(data.get("format", {}).get("duration", 0.0))
        except (ValueError, KeyError, json.JSONDecodeError):
            pass
    return 0.0


def extract_audio(
    media_path: Path,
    output_wav: Path,
    sample_rate: int = 48000,
    channels: int = 2
) -> Path:
    """
    Extract high-fidelity dialogue audio from media file to 16-bit PCM WAV.
    Defaults to 48kHz stereo for master timeline fidelity.
    """
    media_path = Path(media_path).resolve()
    output_wav = Path(output_wav).resolve()
    output_wav.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(media_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        str(output_wav)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed: {res.stderr}")
    return output_wav


def apply_phonetic_fixes(text: str, phonetic_dict: Optional[Dict[str, str]] = None) -> str:
    """
    Apply phonetic word replacements (case-insensitive with word boundary preservation).
    """
    if not text or not phonetic_dict:
        return text

    modified = text
    for wrong, right in phonetic_dict.items():
        if wrong.lower() in modified.lower():
            pattern = re.compile(rf"\b{re.escape(wrong)}\b", re.IGNORECASE)
            modified = pattern.sub(right, modified)
    return modified


def parse_yt_json3_transcript(
    json3_path: Path,
    source_media: str,
    audio_path: str,
    duration: float,
    host_name: str = "MatCrackz",
    guest_name: str = "YourRAGE",
    phonetic_dict: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Parse YouTube automatic captions (json3 format) with millisecond word timestamps
    and speaker turn markers (isSpeakerChange).
    """
    with open(json3_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = data.get("events", [])
    segments: List[Dict[str, Any]] = []
    
    current_speaker = host_name
    seg_id = 0

    for ev in events:
        t_start = ev.get("tStartMs", 0) / 1000.0
        d_dur = ev.get("dDurationMs", 0) / 1000.0
        segs = ev.get("segs", [])
        if not segs:
            continue

        raw_text = "".join(s.get("utf8", "") for s in segs).strip()
        if not raw_text or raw_text == "\n":
            continue

        # Check speaker change anchor & toggle
        has_speaker_change = any(s.get("isSpeakerChange") for s in segs)
        
        # Recognize show host intro signature to reset anchor if needed
        if "WELCOME BACK TO UNPACKED" in raw_text.upper():
            current_speaker = host_name
        elif has_speaker_change:
            current_speaker = guest_name if current_speaker == host_name else host_name

        words_data: List[Dict[str, Any]] = []
        seg_end = round(t_start + d_dur, 3)

        for s_idx, s in enumerate(segs):
            w_raw = s.get("utf8", "")
            w_clean = w_raw.replace(">>", "").strip()
            if not w_clean:
                continue

            w_clean = apply_phonetic_fixes(w_clean, phonetic_dict)
            offset = s.get("tOffsetMs", 0) / 1000.0
            w_start = round(t_start + offset, 3)
            
            # Next word offset or segment boundary
            w_end = seg_end
            if s_idx + 1 < len(segs):
                next_offset = segs[s_idx + 1].get("tOffsetMs")
                if next_offset is not None:
                    w_end = round(t_start + (next_offset / 1000.0), 3)

            if w_end <= w_start:
                w_end = round(w_start + 0.18, 3)

            words_data.append({
                "word": w_clean,
                "start": w_start,
                "end": min(w_end, seg_end),
                "probability": 0.99
            })

        cleaned_text = apply_phonetic_fixes(raw_text.replace(">>", "").strip(), phonetic_dict)

        if words_data:
            segments.append({
                "id": seg_id,
                "speaker": current_speaker,
                "start": round(t_start, 3),
                "end": seg_end,
                "text": cleaned_text,
                "words": words_data
            })
            seg_id += 1

    total_words = sum(len(s.get("words", [])) for s in segments)
    actual_dur = segments[-1]["end"] if segments else duration

    return {
        "version": "1.0.0",
        "source_media": str(source_media),
        "audio_path": str(audio_path),
        "duration": round(actual_dur, 3),
        "language": "en",
        "speakers": [host_name, guest_name],
        "word_count": total_words,
        "segments_count": len(segments),
        "segments": segments
    }


def transcribe_with_whisper(
    media_path: Path,
    model_size: str = "base",
    device: str = "cpu",
    host_name: str = "MatCrackz",
    guest_name: str = "YourRAGE",
    phonetic_dict: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Transcribe media using local faster-whisper model with word-level timestamps.
    """
    from faster_whisper import WhisperModel

    compute_type = "int8" if device == "cpu" else "default"
    print(f"Loading faster-whisper model '{model_size}' (device={device}, compute_type={compute_type})...")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    print(f"Transcribing {media_path} with word-level timestamps...")
    segments_gen, info = model.transcribe(
        str(media_path.resolve()),
        word_timestamps=True,
        language="en",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    segments_data: List[Dict[str, Any]] = []
    current_speaker = host_name
    seg_id = 0

    for seg in segments_gen:
        text = seg.text.strip()
        words_data: List[Dict[str, Any]] = []
        if seg.words:
            for w in seg.words:
                w_fixed = apply_phonetic_fixes(w.word.strip(), phonetic_dict)
                words_data.append({
                    "word": w_fixed,
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "probability": round(w.probability, 3)
                })

        text_fixed = apply_phonetic_fixes(text, phonetic_dict)
        segments_data.append({
            "id": seg_id,
            "speaker": current_speaker,
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": text_fixed,
            "words": words_data
        })
        seg_id += 1

    total_words = sum(len(s.get("words", [])) for s in segments_data)

    return {
        "version": "1.0.0",
        "source_media": str(media_path),
        "audio_path": "",
        "duration": round(info.duration, 3),
        "language": info.language,
        "speakers": [host_name, guest_name],
        "word_count": total_words,
        "segments_count": len(segments_data),
        "segments": segments_data
    }


def execute_transcription_step(
    project_dir: Path,
    media_path: Optional[Path] = None,
    whisper_model: str = "base",
    force: bool = False
) -> Dict[str, Any]:
    """
    End-to-end Step 2 execution:
    1. Pre-flight verification & step config extraction
    2. Audio extraction to 48kHz WAV
    3. Word-level transcription (YouTube json3 priority with Whisper fallback)
    4. Diarization & phonetic correction
    5. Visual contact sheets generation
    6. State engine registration & parameter persistence
    """
    project_dir = Path(project_dir).resolve()
    state_file = project_dir / ".clipping_state.json"
    brief_file = project_dir / "campaign_brief.json"

    if not state_file.exists():
        raise FileNotFoundError(f"State file not found at {state_file}")

    with open(state_file, "r", encoding="utf-8") as f:
        state = json.load(f)

    brief: Dict[str, Any] = {}
    if brief_file.exists():
        with open(brief_file, "r", encoding="utf-8") as f:
            brief = json.load(f)

    # 1. Resolve raw video file
    raw_video = media_path
    if not raw_video:
        raw_dir = project_dir / "raw"
        if raw_dir.exists():
            mp4_candidates = [
                f for f in sorted(raw_dir.glob("*.mp4"))
                if not f.name.endswith("_Proxy.mp4")
            ]
            if mp4_candidates:
                raw_video = mp4_candidates[0]

    if not raw_video or not raw_video.exists():
        raise FileNotFoundError(f"Source video file not found in {project_dir / 'raw'}")

    video_dur = get_video_duration(raw_video)
    print(f"✓ Found source video: {raw_video.name} (duration: {video_dur:.2f}s)")

    # Check for proxy video
    proxy_cand = raw_video.parent / "Proxies" / f"{raw_video.stem}_Proxy.mp4"
    if proxy_cand.is_file():
        print(f"✓ Found proxy video: {proxy_cand.name}")
        rel_proxy = str(proxy_cand.resolve())
        try:
            rel_proxy = str(proxy_cand.resolve().relative_to(project_dir.resolve()))
        except ValueError:
            pass
        state["media_proxy_path"] = rel_proxy
        state.setdefault("steps", {}).setdefault("clipping-transcription", {}).setdefault("params", {})["media_proxy_path"] = rel_proxy
        state.setdefault("steps", {}).setdefault("clipping-assembly", {}).setdefault("params", {})["proxy_path"] = rel_proxy

    # 2. Extract 48kHz dialogue audio
    trans_params = state.get("steps", {}).get("clipping-transcription", {}).get("params", {})
    audio_rel = trans_params.get("media_audio_path") or f"raw/{raw_video.stem}_audio.wav"
    audio_path = project_dir / audio_rel
    sample_rate = trans_params.get("sample_rate", 48000)

    if not audio_path.exists() or force:
        print(f"Extracting {sample_rate}Hz WAV audio to {audio_path}...")
        extract_audio(raw_video, audio_path, sample_rate=sample_rate)
        print(f"✓ Audio extracted: {audio_path.name}")
    else:
        print(f"✓ Audio already extracted at: {audio_path.name}")

    # 3. Resolve speakers and phonetic dictionary
    speakers = trans_params.get("diarization_speakers") or ["MatCrackz", "YourRAGE"]
    host_name = speakers[0] if len(speakers) > 0 else "MatCrackz"
    guest_name = speakers[1] if len(speakers) > 1 else "YourRAGE"

    phonetic_dict = trans_params.get("phonetic_dictionary") or {
        "your age": "YourRAGE",
        "mat crackz": "MatCrackz",
        "matt cracks": "MatCrackz",
        "hard scope": "HardScope",
        "un packed": "Unpacked"
    }

    # 4. Generate or parse word-level transcript
    out_transcript = project_dir / "transcript.json"
    yt_json3_path = project_dir / "raw" / "yt_captions.en.json3"

    transcript_data: Dict[str, Any]
    if yt_json3_path.exists():
        print(f"Parsing YouTube word-level captions from {yt_json3_path.name} with speaker turns...")
        transcript_data = parse_yt_json3_transcript(
            json3_path=yt_json3_path,
            source_media=str(raw_video.relative_to(project_dir)),
            audio_path=str(audio_path.relative_to(project_dir)),
            duration=video_dur,
            host_name=host_name,
            guest_name=guest_name,
            phonetic_dict=phonetic_dict
        )
    else:
        print("Running faster-whisper transcription...")
        transcript_data = transcribe_with_whisper(
            media_path=audio_path,
            model_size=whisper_model,
            device="cpu",
            host_name=host_name,
            guest_name=guest_name,
            phonetic_dict=phonetic_dict
        )
        transcript_data["source_media"] = str(raw_video.relative_to(project_dir))
        transcript_data["audio_path"] = str(audio_path.relative_to(project_dir))

    # Save transcript.json
    with open(out_transcript, "w", encoding="utf-8") as f:
        json.dump(transcript_data, f, indent=2, ensure_ascii=False)
    print(f"✓ Transcript saved: {out_transcript} ({transcript_data['word_count']} words, {transcript_data['segments_count']} segments)")

    # 5. Ensure 4x4 visual contact sheets exist
    contact_dir = project_dir / "contact_sheets"
    contact_index = contact_dir / "contact_sheets.json"
    if not contact_index.exists() or force:
        print(f"Generating 4x4 contact sheets for visual grounding...")
        cmd_cs = [
            sys.executable,
            str(Path(__file__).parent / "generate_contact_sheets.py"),
            "-i", str(raw_video),
            "-o", str(contact_dir),
            "-m", "batch",
            "-d", "120",
            "-g", "4x4"
        ]
        res = subprocess.run(cmd_cs, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Contact sheets generation failed: {res.stderr}")
        print(f"✓ Contact sheets generated in: {contact_dir}")
    else:
        print(f"✓ Visual contact sheets verified at: {contact_dir}")

    # 6. Update step parameters in .clipping_state.json
    state["steps"]["clipping-transcription"]["params"].update({
        "media_audio_path": str(audio_path.relative_to(project_dir)),
        "transcript_path": "transcript.json",
        "sample_rate": sample_rate,
        "diarization_speakers": [host_name, guest_name],
        "phonetic_dictionary": phonetic_dict,
        "word_count": transcript_data["word_count"],
        "segments_count": transcript_data["segments_count"],
        "duration_seconds": transcript_data["duration"],
        "contact_sheets_path": "contact_sheets/contact_sheets.json"
    })

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    print(f"✓ Pipeline state step params updated in {state_file}")

    return transcript_data


def main():
    parser = argparse.ArgumentParser(
        description="Step 2: Audio extraction, transcription, diarization, and visual grounding."
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")

    trans_p = subparsers.add_parser("transcribe", help="Execute transcription and grounding workflow")
    trans_p.add_argument("--dir", default=".", help="Project directory")
    trans_p.add_argument("--media", default=None, help="Path to raw source video file")
    trans_p.add_argument("--model", default="base", help="Whisper model size (default: base)")
    trans_p.add_argument("--force", action="store_true", help="Force re-generation of audio, transcript, and sheets")

    args = parser.parse_args()
    if args.command == "transcribe" or not args.command:
        target_dir = Path(getattr(args, "dir", "."))
        media_p = Path(args.media) if getattr(args, "media", None) else None
        model_s = getattr(args, "model", "base")
        force_flag = getattr(args, "force", False)

        execute_transcription_step(
            project_dir=target_dir,
            media_path=media_p,
            whisper_model=model_s,
            force=force_flag
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
