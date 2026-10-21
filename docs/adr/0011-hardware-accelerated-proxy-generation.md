# 0011: Hardware-Accelerated Video Proxy Generation & Source Download Bridge

In long-form video clipping workflows, raw downloaded footage frequently utilizes modern compression formats (such as AV1, VP9, or high-bitrate 4K H.264/HEVC) that cause severe playback stutter, slow contact sheet extraction, and high CPU load during interactive timeline scrubbing in Remotion Studio. Furthermore, source video downloading from authenticated campaigns or YouTube URLs was previously uncoupled from automated proxy preparation.

To enable instantaneous seeking and butter-smooth scrubbing in Remotion Studio while minimizing rendering times, we introduce automated source video downloading via `yt-dlp` (`scripts/download_source.py`) chained immediately into hardware-accelerated proxy generation (`scripts/generate_proxy.py`).

## Status

Accepted

## Considered Options

- **Manual / NLE Internal Ingest Transcoding**: Relying on manual operator transcoding or editor internal background ingest. Rejected because agents require headless, automated proxy availability prior to Step 2 transcription, contact sheet generation, and timeline assembly without human friction.
- **Fixed CPU Transcoding (libx264)**: Encoding proxies exclusively via CPU (`libx264 -preset veryfast`). Rejected as the primary path because hardware acceleration (such as Intel/AMD VAAPI, NVIDIA NVENC, Apple VideoToolbox) provides 3x to 12x speedups while drastically lowering host CPU utilization.
- **Hardware-Probed Proxy Pipeline with CPU Fallback**: Automatically probing the host environment for active hardware acceleration (Linux VAAPI on `/dev/dri/renderD128`, NVIDIA NVENC, Apple VideoToolbox, Intel QSV) using an active 1-frame probe, defaulting to half-resolution (e.g. 960x540 for 1080p), a 1-second keyframe GOP interval, zero B-frames, and falling back gracefully to CPU `libx264` if hardware probes fail. Chosen for maximum performance across diverse developer machines.

## Consequences

- `scripts/generate_proxy.py` implements host hardware acceleration detection and proxy generation with canonical output at `<project_dir>/raw/Proxies/<slug>_Proxy.mp4`.
- Proxies default to half-resolution (e.g. 960x540 for 1080p) with short 1-second GOPs and `-bf 0` for responsive random-access scrubbing.
- `scripts/download_source.py` integrates `yt-dlp` downloading from campaign briefs or URLs and immediately chains proxy generation.
- `scripts/clipping_assembly.py` automatically links generated proxies into the `.remotion.json` Media item under `"proxy": {"File": {"path": str(proxy_path)}}`.
- `.clipping_state.json` tracks `raw_video_path` and `media_proxy_path` persistently across pipeline steps.
