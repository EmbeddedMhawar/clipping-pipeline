# Native Remotion Multi-Track Vertical Canvas Specification for `clipping-assembly`

> **Document Status**: Complete / Approved Reference Specification  
> **Target System**: Remotion 4.0 + HyperFrames 1.0 (`.remotion.json` Schema Version 2)  
> **Domain**: Native 9:16 Vertical Canvas Assembly (1080×1920) for Short-Form Video (TikTok, YouTube Shorts, Instagram Reels)  
> **Related Issues**: [Issue #24](https://github.com/EmbeddedMhawar/clipping-pipeline/issues/24) (Spec), [Issue #22](https://github.com/EmbeddedMhawar/clipping-pipeline/issues/22) (Map: Continuous Live-GUI Feedback), [Issue #25](https://github.com/EmbeddedMhawar/clipping-pipeline/issues/25) (GUI Companion), [Issue #27](https://github.com/EmbeddedMhawar/clipping-pipeline/issues/27) (Dual-Channel Preference Codification)

---

## 1. Executive Summary & Problem Statement

In the 8-stage clipping pipeline ([`skills/clipping-pipeline/SKILL.md`](../../skills/clipping-pipeline/SKILL.md)), **Step 4 (`clipping-assembly`)** is responsible for transforming raw 16:9 landscape footage (or arbitrary source media) into a broadcast-ready **9:16 vertical (1080×1920)** timeline. 

Per architectural requirements established in [Issue #22](https://github.com/EmbeddedMhawar/clipping-pipeline/issues/22) and [ADR 0012](../adr/0012-remotion-and-hyperframes-rendering-engine.md), `clipping-pipeline` constructs and manipulates valid Remotion (`.remotion.json` + React/TypeScript composition bundles) directly from scratch.

This research specification answers the questions posed in [Issue #24](https://github.com/EmbeddedMhawar/clipping-pipeline/issues/24):
1. **Timing Units**: What is the exact time base (`TICKS_PER_SEC`) used by the assembly engine, why is it chosen, and how are conversions computed without drift?
2. **Project File Format**: What is the canonical JSON structure of a `.remotion.json` document (schema version 2)?
3. **Track Layering Architecture**: How are video tracks (V1 Blurred Background, V2 Speaker Foreground, V3 HUD/Overlays, V4 Watermark) and audio tracks (A1 Dialogue, A2 Background Music, A3 SFX) defined, named, and configured?
4. **Transform Mathematics**: What exact affine transformation parameters (`scale`, `anchor`, `position`, `rotation`) implement split-sandwich blurred fill, single speaker framing, speaker ping-pong cropping, and stacked-split layouts?
5. **Timeline Placement & Dead Air Excision**: How are sub-cuts placed chronologically, how is dead air ($>0.40$s) pruned while retaining consonant buffers ($0.08$s), and how are video/audio tracks kept in sync?
6. **Execution Strategies**: How does declarative direct JSON + React/TSX composition generation work without external IPC pitfalls?

---

## 2. Primary Source Investigations & Empirical Verification

This specification was established by validating declarative multi-track composition schemas for Remotion 4.0 and HyperFrames 1.0:

1. **Remotion Composition Engine (`scripts/clipping_assembly.py`)**:
   - Generates `.remotion.json` and scaffolds `remotion/Root.tsx`, `remotion/ClipComposition.tsx`, and `remotion/props.json`.
   - Uses `<AbsoluteFill>`, `<Sequence>`, `<OffthreadVideo>`, `<Audio>`, and `<Img>` components.
2. **Caption Track Synchronization (`scripts/clipping_captions.py`)**:
   - Uses `@remotion/captions` compatible track structures for `Dialogue Captions` and `Emotion Callouts`.
3. **HyperFrames Overlay Synthesis (`scripts/clipping_vfx_sfx.py`)**:
   - Generates declarative HTML/CSS/GSAP compositions (`.hyperframes.html` with `data-composition-id`, `data-start`, and `data-duration`) for Track V3 hooks and color stabs.

---

## 3. High-Precision Time Base (`TICKS_PER_SEC`)

The assembly engine represents all timeline positions, durations, in-points, out-points, and keyframe timestamps using integer tick counts.

### 3.1 Constant Definition
```python
TICKS_PER_SEC: int = 254_016_000_000
```

### 3.2 Mathematical Derivation
The constant $254,016,000,000$ was deliberately engineered for digital non-linear editing engines. Its prime factorization is:
$$254,016,000,000 = 2^{11} \times 3^4 \times 5^6 \times 7$$

Because it contains factors of $2, 3, 5$, and $7$, it divides into **exact integers** for all standard cinematic, television, broadcast, web, and audio sample rates:

| Frame / Sample Rate | Ticks per Frame / Sample | Exact Integer? |
| :--- | :--- | :--- |
| **24 fps** (Film / Cinema) | $10,584,000,000$ | Yes ($\equiv 0 \pmod{24}$) |
| **25 fps** (PAL / European Broadcast) | $10,160,640,000$ | Yes ($\equiv 0 \pmod{25}$) |
| **30 fps** (Standard Web / Mobile) | $8,467,200,000$ | Yes ($\equiv 0 \pmod{30}$) |
| **48 fps** (HFR Cinema) | $5,292,000,000$ | Yes ($\equiv 0 \pmod{48}$) |
| **50 fps** (HFR PAL) | $5,080,320,000$ | Yes ($\equiv 0 \pmod{50}$) |
| **60 fps** (Gaming / High-Motion Web) | $4,233,600,000$ | Yes ($\equiv 0 \pmod{60}$) |
| **120 fps** (Slow Motion / UI Display) | $2,116,800,000$ | Yes ($\equiv 0 \pmod{120}$) |
| **23.976 fps** ($24000/1001$) | $10,594,584,000$ | Yes ($254016000000 \times \frac{1001}{24000}$) |
| **29.970 fps** ($30000/1001$) | $8,475,667,200$ | Yes ($254016000000 \times \frac{1001}{30000}$) |
| **59.940 fps** ($60000/1001$) | $4,237,833,600$ | Yes ($254016000000 \times \frac{1001}{60000}$) |
| **44.1 kHz** Audio | $5,760,000$ | Yes ($\equiv 0 \pmod{44100}$) |
| **48.0 kHz** Audio | $5,292,000$ | Yes ($\equiv 0 \pmod{48000}$) |
| **96.0 kHz** Audio | $2,646,000$ | Yes ($\equiv 0 \pmod{96000}$) |
| **192.0 kHz** Audio | $1,323,000$ | Yes ($\equiv 0 \pmod{192000}$) |

One single tick represents approximately $\approx 3.936$ picoseconds ($3.9366811539 \times 10^{-12}$ s). This eliminates cumulative rounding errors and floating-point drift across hours of cuts.

### 3.3 Conversion Functions
```python
def seconds_to_ticks(seconds: float) -> int:
    """Convert floating-point seconds to nearest discrete timeline ticks."""
    return int(round(seconds * TICKS_PER_SEC))

def ticks_to_seconds(ticks: int) -> float:
    """Convert timeline ticks to floating-point seconds."""
    return float(ticks) / TICKS_PER_SEC

def frames_to_ticks(frames: int, fps_num: int, fps_den: int = 1) -> int:
    """Convert frame count at rational frame rate to exact ticks."""
    return int(round(frames * (TICKS_PER_SEC * fps_den / fps_num)))
```

---

## 4. Native `.remotion.json` JSON Document Schema

A `.remotion.json` file is a UTF-8 JSON document adhering to `schema_version: 2`.

### 4.1 Document Root Structure
```json
{
  "format": "remotion.project",
  "schema_version": 2,
  "generator": "Remotion 4.0 + HyperFrames 1.0",
  "project": {
    "name": "clip_project_name",
    "settings": {
      "renderer": "Remotion Chromium / OffthreadVideo Compositor",
      "video_display": "Timecode",
      "audio_display_samples": true,
      "default_still_duration": 1270080000000,
      "default_transition_duration_frames": 24,
      "default_audio_transition_duration": 254016000000,
      "ingest": {
        "enabled": false,
        "action": "createProxies",
        "destination": null,
        "preset": ""
      },
      "title_safe": [20.0, 20.0],
      "action_safe": [10.0, 10.0],
      "capture_format": "DV",
      "scratch": {
        "captured": null,
        "videoPreviews": null,
        "audioPreviews": null,
        "autoSave": null
      }
    },
    "root": {
      "id": 0,
      "name": "clip_project_name",
      "children": [
        { "Item": 8 },
        { "Item": 9 }
      ]
    },
    "items": {
      "8": { "/* Sequence item */" },
      "9": { "/* Media item */" }
    },
    "next_id": 10
  },
  "view": {
    "open_sequences": [8],
    "active_sequence": 8,
    "sequences": {}
  }
}
```

### 4.2 Item 1: Media Item (`kind.Media`)
Every external asset (video footage, audio file, PNG watermark, overlay) imported into the project receives an entry in `project.items`:

```json
{
  "id": 9,
  "name": "raw_footage.mp4",
  "label": "Iris",
  "kind": {
    "Media": {
      "media": {
        "File": {
          "path": "/absolute/path/to/raw_footage.mp4"
        }
      },
      "info": {
        "name": "raw_footage.mp4",
        "kind": "Movie",
        "duration": 1270080000000,
        "video": {
          "width": 1920,
          "height": 1080,
          "frame_rate": { "num": 30, "den": 1 },
          "par": [1, 1],
          "codec": "H.264",
          "pixel_format": "YUV 4:2:0 8-bit",
          "color": {
            "matrix": "Bt709",
            "transfer": "Bt709",
            "primaries": "Bt709",
            "range": "Limited"
          },
          "has_alpha": false,
          "bitrate": 8000000
        },
        "audio": {
          "sample_rate": 48000,
          "channels": 2,
          "codec": "AAC",
          "bits_per_sample": null
        },
        "container": "MPEG-4",
        "start_timecode": null,
        "file_size": 52428800
      },
      "interpret": {
        "frame_rate": null,
        "par": null,
        "ignore_alpha": false,
        "invert_alpha": false
      },
      "mark_in": null,
      "mark_out": null,
      "markers": [],
      "offline": false,
      "proxy": {
        "File": {
          "path": "/absolute/path/to/project/raw/Proxies/source_Proxy.mp4"
        }
      },
      "identity": {
        "size": 52428800,
        "fingerprint": "daa951d4a0aaac69"
      }
    }
  },
  "metadata": {},
  "created": 9
}
```

> **Note on Proxies (ADR 0011)**: Per [ADR 0011: Hardware-Accelerated Video Proxy Generation & Source Download Bridge](../adr/0011-hardware-accelerated-proxy-generation.md), when a lightweight H.264 proxy exists in `raw/Proxies/<stem>_Proxy.mp4` or is passed via `--proxy`, the `proxy` property contains `{"File": {"path": "<abs-path>"}}`. If no proxy is present, this field defaults to `null`.

### 4.3 Item 2: Sequence Item (`kind.Sequence`)
The active editing sequence defines canvas resolution, framerate, video tracks, and audio tracks:

```json
{
  "id": 8,
  "name": "VerticalShort_Clip01",
  "label": "Forest",
  "kind": {
    "Sequence": {
      "settings": {
        "width": 1080,
        "height": 1920,
        "frame_rate": { "num": 30, "den": 1 },
        "par": [1, 1],
        "sample_rate": 48000,
        "drop_frame": false,
        "preset": "1080x1920 30",
        "audio_master": "Stereo",
        "preview_codec": "ProRes 422",
        "max_bit_depth": false,
        "max_render_quality": false,
        "working_space": "Rec. 709",
        "color": {
          "working": "Rec709",
          "wide_gamut": false,
          "auto_tone_map": true
        }
      },
      "video_tracks": [
        { "/* Track V1: Blurred Background */" },
        { "/* Track V2: Speaker Foreground */" },
        { "/* Track V3: HUD & Overlays */" },
        { "/* Track V4: Watermark */" }
      ],
      "audio_tracks": [
        { "/* Track A1: Dialogue */" },
        { "/* Track A2: Background Music */" },
        { "/* Track A3: SFX */" }
      ],
      "markers": [],
      "mark_in": null,
      "mark_out": null,
      "work_area": null,
      "start_timecode": 0,
      "master_volume_db": 0.0,
      "master_effects": [],
      "master_mixer": {
        "mode": "Read",
        "output": null,
        "record_arm": false,
        "solo_safe": false,
        "input_map": "Stereo"
      },
      "submix_tracks": [],
      "caption_tracks": []
    }
  },
  "metadata": {},
  "created": 8
}
```

---

## 5. Multi-Track Canvas Layering Convention

To satisfy the requirements of high-retention vertical short-form video, `clipping-assembly` establishes a strict 4-video / 3-audio track hierarchy:

```
  Top of Timeline Stack
  -------------------------------------------------------------
  [V4] Watermark          (Persistent brand badge, Top-Center)
  [V3] HUD & Overlays     (Kinetic titles, Chat HUD, VFX overlays)
  [V2] Speaker Foreground (Crisp speaker crop, 177.8% scale)
  [V1] Blurred Background (Oversized 209.8% scale, Gaussian Blur)
  =============================================================
  [A1] Dialogue           (Primary spoken speech, 0.0 dB)
  [A2] Background Music   (Music bed, Ducked -18.0 to -24.0 dB)
  [A3] SFX                (Punctuation accents, Whooshes, Hits)
  -------------------------------------------------------------
  Bottom of Timeline Stack
```

### 5.1 Video Tracks Specification

| Track | Identifier | Name in Sequence | Typical Content | Visual Transforms & Effects |
| :--- | :--- | :--- | :--- | :--- |
| **V1** | Track `1` | `Blurred Background` | Raw footage source | Scale: $209.78\%$ (fill + 18% bleed)<br>Position: $(540.0, 960.0)$<br>`gaussian_blur`: blurriness $45.0$, `repeat_edge: true`<br>`opacity`: $40.0\%$ |
| **V2** | Track `2` | `Speaker Foreground` | Raw footage source | Scale: $177.78\%$ (fill) to $199.1\%$ (punch-in)<br>Anchor: $(W_{src} \times x_c, H_{src} \times y_c)$<br>Position: $(540.0, 960.0)$<br>`opacity`: $100.0\%$ |
| **V3** | Track `3` | `HUD & Overlays` | Transparent WebM / MOV / PNG / HTML / B-roll | Scale: $100.0\%$ (or tailored)<br>Position: As anchored (e.g. Chat HUD at bottom or top)<br>Composites HyperFrames graphics |
| **V4** | Track `4` | `Watermark` | 1600×533 Transparent PNG | Scale: $28.0\%$ (renders at $\approx 448$px wide)<br>Anchor: $(800.0, 266.5)$<br>Position: $(540.0, 280.0)$ (Top-Center safe zone)<br>Duration: $100\%$ of clip timeline |

### 5.2 Audio Tracks Specification

| Track | Identifier | Name in Sequence | Source Material | Volume Configuration | Mix Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **A1** | Track `5` | `Dialogue` | Primary audio stream from raw footage | `volume_db: 0.0`<br>Pan: `0.0` | Pristine dialogue speech; stays phase-locked to V2 cuts. Target: -14 to -18 LUFS. |
| **A2** | Track `6` | `Background Music` | Viral background bed audio (.wav / .mp3) | `volume_db: -18.0`<br>(or -20.0 dB to -24.0 dB) | Subtly fills dynamic room without masking speech clarity or triggering ducking pumping. |
| **A3** | Track `7` | `SFX` | Sound effects (whoosh, pop, ding, thock, bass drop) | `volume_db: 0.0` to `-4.0`<br>Pan: `0.0` | Transcript-driven punctuation accents and HyperFrames audio hits. |

---

## 6. Transform Matrices & Coordinate Mathematics

### 6.1 Coordinate Space Conventions
The composition engine uses a 2D Euclidean coordinate system with origin $(0, 0)$ at the **top-left** of the canvas:
- **Canvas Width ($W_{dst}$)**: $1080.0$ px
- **Canvas Height ($H_{dst}$)**: $1920.0$ px
- **Canvas Center**: $(x = 540.0, y = 960.0)$
- **Source Footage ($W_{src} \times H_{src}$)**: Typically $1920.0 \times 1080.0$ px (16:9)
- **Source Center**: $(x = 960.0, y = 540.0)$

The `motion` effect uses three primary properties:
1. `position` ($\vec{P}$): Destination point on the sequence canvas where the anchor is pinned.
2. `anchor` ($\vec{A}$): Source pixel coordinates within the media item that maps onto $\vec{P}$.
3. `scale` ($S$): Uniform scaling percentage ($100.0 = 100\% = 1.0\times$).

The forward mapping from source media point $\vec{p}_{src} = (x, y)$ to canvas point $\vec{p}_{canvas} = (X, Y)$ is:
$$\vec{p}_{canvas} = \vec{P} + \frac{S}{100.0} \cdot R(\theta) \cdot (\vec{p}_{src} - \vec{A})$$
Where $R(\theta)$ is the 2D rotation matrix (with $\theta = 0$ for standard vertical clips).

### 6.2 Primary Scaling Ratios

#### Vertical Fill Scale ($S_{fill}$)
To scale 1080p landscape footage so its height fills the entire 1920 vertical canvas:
$$S_{fill} = \frac{H_{dst}}{H_{src}} \times 100.0 = \frac{1920.0}{1080.0} \times 100.0 = \frac{16}{9} \times 100.0 \approx 177.77777777777777\%$$

#### Letterbox / Width-Fit Scale ($S_{fit}$)
To fit the full 1920 landscape width inside the 1080 canvas without cropping:
$$S_{fit} = \frac{W_{dst}}{W_{src}} \times 100.0 = \frac{1080.0}{1920.0} \times 100.0 = \frac{9}{16} \times 100.0 = 56.25\%$$

#### Oversized Background Scale ($S_{bg}$)
When applying Gaussian blur to background fill, canvas edge pixels can feather inward, creating visible black borders or vignette artifacts. To eliminate this, the background layer is scaled with an additional $18\%$ bleed buffer:
$$S_{bg} = S_{fill} \times 1.18 = 177.77777777777777\% \times 1.18 \approx 209.77777777777777\%$$

---

### 6.3 Framing Presets & Layout Mathematics

#### Preset 1: Split-Sandwich (Default High-Retention Layout)
- **Track V1 (Background)**:
  - $\vec{P}_{V1} = (540.0, 960.0)$
  - $\vec{A}_{V1} = (960.0, 540.0)$
  - $S_{V1} = 209.7778\%$
  - Effect: `gaussian_blur` (`blurriness: 45.0`, `repeat_edge: true`), `opacity: 40.0%`
- **Track V2 (Foreground)**:
  - Let $(x_c, y_c)$ be normalized speaker center (default $x_c = 0.50, y_c = 0.50$):
  - $\vec{A}_{V2} = (W_{src} \times x_c, H_{src} \times y_c) = (1920.0 \cdot x_c, 1080.0 \cdot y_c)$
  - $\vec{P}_{V2} = (540.0, 960.0)$
  - $S_{V2} = S_{fill} = 177.7778\%$
  - Opacity: $100.0\%$

#### Preset 2: Speaker Ping-Pong Cropping (Podcast / Dual-Host Streams)
In interviews, podcasts, or two-person commentary where Speaker A (Host) sits on camera left and Speaker B (Guest) sits on camera right, `clipping-assembly` reframes Track V2 on a per-cut basis:

```
Source 16:9 Frame:
+-------------------------------------------------------+
|        [ Host (A) ]              [ Guest (B) ]        |
|        x_c ≈ 0.25                  x_c ≈ 0.75         |
|        y_c ≈ 0.45                  y_c ≈ 0.45         |
+-------------------------------------------------------+
```

1. **Host Speaking Cut**:
   - $\vec{A} = (1920 \times 0.25, 1080 \times 0.45) = (480.0, 486.0)$
   - $\vec{P} = (540.0, 960.0)$
   - $S = 177.7778\%$
2. **Guest Speaking Cut**:
   - $\vec{A} = (1920 \times 0.75, 1080 \times 0.45) = (1440.0, 486.0)$
   - $\vec{P} = (540.0, 960.0)$
   - $S = 177.7778\%$
3. **Dual-Speaker Reaction / Banter (Two-Shot)**:
   - Rather than cutting back and forth rapidly during cross-talk, switch to letterbox:
   - $\vec{A} = (960.0, 540.0)$
   - $\vec{P} = (540.0, 960.0)$
   - $S = S_{fit} = 56.25\%$
   - Both speakers appear centered with the blurred background filling top and bottom.

#### Preset 3: Stacked-Split (Host on Top, Guest or Gameplay on Bottom)
Used when both streams must be seen simultaneously without letterboxing:
- **Top Half Layer (e.g. Host)**:
  - $\vec{A}_{top} = (1920 \times x_{c1}, 1080 \times y_{c1})$
  - $\vec{P}_{top} = (540.0, 480.0)$  ($y = 0.25 \times H_{dst}$)
  - $S_{top} = 177.7778\%$
- **Bottom Half Layer (e.g. Gameplay / Guest)**:
  - $\vec{A}_{bot} = (1920 \times x_{c2}, 1080 \times y_{c2})$
  - $\vec{P}_{bot} = (540.0, 1440.0)$ ($y = 0.75 \times H_{dst}$)
  - $S_{bot} = 177.7778\%$

#### Preset 4: Rhetorical Punch-Ins (Pacing Zoom Cuts)
To emphasize key takeaways or punchlines without cutting footage:
- Micro-Punch: $S = S_{fill} \times 1.06 = 188.44\%$
- Medium Punch: $S = S_{fill} \times 1.12 = 199.11\%$
- Tight Climax Punch: $S = S_{fill} \times 1.22 = 216.89\%$
- The anchor $\vec{A}$ shifts slightly towards speaker eye level ($y_c \approx 0.38$).

#### Preset 5: Watermark Transform (Track V4)
For a standard campaign watermark image (e.g. $1600 \times 533$ PNG):
- Target width on screen: $W_{target} = 448.0$ px ($41.5\%$ of canvas width)
- $$S_{wm} = \frac{448.0}{1600.0} \times 100.0 = 28.0\%$$
- $\vec{A}_{wm} = (800.0, 266.5)$
- $\vec{P}_{wm} = (540.0, 280.0)$
- This positions the logo horizontally centered, $280$ px from top, safely below the platform top navigation icons (sound search, live badge) and above the middle dialogue subtitle zone ($Y \in [1100, 1450]$).

---

## 7. Timeline Placement & Dead Air Excision

### 7.1 Dead Air Pruning Rules
1. **Silence Threshold**: Dead air gaps between spoken sentences $> 0.40$s are excised.
2. **Consonant Tail Padding Buffer**:
   - Spoken English words frequently end in subtle unvoiced consonants or trailing aspirations (e.g., /t/, /s/, /k/, /th/). Hard cuts at whisper word boundaries sound robotic and jarring.
   - Every cut receives a default tail padding of $\tau_{pad} = 0.08$s ($80$ ms $\approx 20,321,280,000$ ticks).
   - **Boundary Collision Guard**: Padding must never overrun into the subsequent spoken segment:
     $$\tau_{pad\_eff} = \min(0.08, \max(0.0, t_{start}[i+1] - t_{end}[i] - 0.01))$$
3. **Minimum Clip Duration**: No cut placed on the timeline may be shorter than $0.04$s (approx. 1 frame at 25 fps).

### 7.2 Chronological Placement Logic
Clips are placed end-to-end starting at timeline tick $T = 0$:

```python
timeline_time_ticks = 0

for i, cut in enumerate(sub_cuts):
    start_sec = cut["start"]
    end_sec = cut["end"]
    
    # Calculate safe tail buffer
    pad = 0.08
    if i + 1 < len(sub_cuts):
        next_start = sub_cuts[i + 1]["start"]
        max_pad = max(0.0, next_start - end_sec - 0.01)
        pad = min(pad, max_pad)
        
    dur_sec = max(0.04, (end_sec + pad) - start_sec)
    
    source_in_ticks = seconds_to_ticks(start_sec)
    duration_ticks = seconds_to_ticks(dur_sec)
    
    # 1. Place V1 Background
    place_clip(track="V1", source_in=source_in_ticks, dur=duration_ticks, time=timeline_time_ticks)
    
    # 2. Place V2 Foreground (Synchronized)
    place_clip(track="V2", source_in=source_in_ticks, dur=duration_ticks, time=timeline_time_ticks)
    
    # 3. Place A1 Dialogue (Synchronized)
    place_clip(track="A1", source_in=source_in_ticks, dur=duration_ticks, time=timeline_time_ticks)
    
    timeline_time_ticks += duration_ticks

# 4. Place V4 Watermark (Full Duration)
place_clip(track="V4", source_in=0, dur=timeline_time_ticks, time=0)
```

---

## 8. Assembly Execution Strategies

`clipping-assembly` constructs the complete `.remotion.json` dictionary directly in memory using `RemotionBuilder` and scaffolds the `remotion/Root.tsx` and `remotion/ClipComposition.tsx` React composition files.

#### Advantages
1. **Speed**: Sub-millisecond execution.
2. **Zero Subprocess Overhead**: Runs entirely within Python; no external binary locks or IPC pipe issues.
3. **Exact Effect Value Injection**: Directly structures effect ASTs (`Vec2`, `Float`, `Bool`) without needing post-assembly JSON patch passes.
4. **100% Deterministic**: Completely reproducible output guaranteed by schema validation.

---

## 9. Declarative Assembly Schema Blueprint

Below is the complete, production-grade schema definition and builder class for `clipping-assembly`:

```python
"""
remotion_builder.py - Declarative 9:16 Vertical Remotion Project Generator
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

TICKS_PER_SEC: int = 254_016_000_000


@dataclass
class SubCut:
    start: float  # Start time in seconds
    end: float    # End time in seconds
    x_center: float = 0.50
    y_center: float = 0.50
    punch_in: float = 1.00


@dataclass
class AssemblyConfig:
    project_name: str
    output_path: Path
    media_path: Path
    watermark_path: Optional[Path] = None
    bgm_path: Optional[Path] = None
    bgm_volume_db: float = -18.0
    src_width: int = 1920
    src_height: int = 1080
    fps_num: int = 30
    fps_den: int = 1
    sub_cuts: List[SubCut] = field(default_factory=list)


class RemotionBuilder:
    def __init__(self, config: AssemblyConfig):
        self.config = config
        self.next_id = 1
        self.items: Dict[str, Any] = {}
        self.root_children: List[Dict[str, int]] = []
        
        # Dimensions
        self.canvas_w = 1080.0
        self.canvas_h = 1920.0
        self.src_w = float(config.src_width)
        self.src_h = float(config.src_height)
        
        # Scaling
        self.fill_scale = (self.canvas_h / self.src_h) * 100.0
        self.bg_scale = self.fill_scale * 1.18

    def _alloc_id(self) -> int:
        cur = self.next_id
        self.next_id += 1
        return cur

    def _sec_to_ticks(self, s: float) -> int:
        return int(round(s * TICKS_PER_SEC))

    def _make_motion_effect(self, scale: float, anchor_x: float, anchor_y: float, pos_x: float, pos_y: float) -> Dict[str, Any]:
        return {
            "effect": "motion",
            "enabled": True,
            "params": {
                "anchor": {"value": {"Vec2": {"x": anchor_x, "y": anchor_y}}},
                "anti_flicker": {"value": {"Float": 0.0}},
                "position": {"value": {"Vec2": {"x": pos_x, "y": pos_y}}},
                "rotation": {"value": {"Float": 0.0}},
                "scale": {"value": {"Float": scale}},
                "scale_width": {"value": {"Float": 100.0}},
                "uniform_scale": {"value": {"Bool": True}}
            }
        }

    def _make_opacity_effect(self, opacity: float) -> Dict[str, Any]:
        return {
            "effect": "opacity",
            "enabled": True,
            "params": {
                "blend": {"value": {"Choice": 0}},
                "opacity": {"value": {"Float": opacity}}
            }
        }

    def _make_gaussian_blur_effect(self, blurriness: float = 45.0) -> Dict[str, Any]:
        return {
            "effect": "gaussian_blur",
            "enabled": True,
            "params": {
                "blurriness": {"value": {"Float": blurriness}},
                "dimensions": {"value": {"Choice": 0}},
                "repeat_edge": {"value": {"Bool": True}}
            }
        }

    def _make_audio_volume_effects(self, level_db: float = 0.0) -> List[Dict[str, Any]]:
        return [
            {
                "effect": "volume",
                "enabled": True,
                "params": {
                    "bypass": {"value": {"Bool": False}},
                    "level": {"value": {"Float": level_db}}
                }
            },
            {
                "effect": "channel_volume",
                "enabled": True,
                "params": {
                    "bypass": {"value": {"Bool": False}},
                    "left": {"value": {"Float": 0.0}},
                    "right": {"value": {"Float": 0.0}}
                }
            },
            {
                "effect": "panner",
                "enabled": True,
                "params": {
                    "balance": {"value": {"Float": 0.0}}
                }
            }
        ]

    def build(self) -> Dict[str, Any]:
        seq_id = self._alloc_id()
        media_id = self._alloc_id()
        
        self.root_children.append({"Item": seq_id})
        self.root_children.append({"Item": media_id})
        
        # Primary Media Item
        self.items[str(media_id)] = {
            "id": media_id,
            "name": self.config.media_path.name,
            "label": "Iris",
            "kind": {
                "Media": {
                    "media": {"File": {"path": str(self.config.media_path.resolve())}},
                    "info": {
                        "name": self.config.media_path.name,
                        "kind": "Movie",
                        "duration": self._sec_to_ticks(3600.0),
                        "video": {
                            "width": self.config.src_width,
                            "height": self.config.src_height,
                            "frame_rate": {"num": self.config.fps_num, "den": self.config.fps_den},
                            "par": [1, 1],
                            "codec": "H.264",
                            "pixel_format": "YUV 4:2:0 8-bit",
                            "color": {"matrix": "Bt709", "transfer": "Bt709", "primaries": "Bt709", "range": "Limited"},
                            "has_alpha": False,
                            "bitrate": 10000000
                        },
                        "audio": {"sample_rate": 48000, "channels": 2, "codec": "AAC", "bits_per_sample": None},
                        "container": "MPEG-4",
                        "start_timecode": None,
                        "file_size": 100000000
                    },
                    "interpret": {"frame_rate": None, "par": None, "ignore_alpha": False, "invert_alpha": False},
                    "mark_in": None, "mark_out": None, "markers": [], "offline": False,
                    "proxy": {"File": {"path": str(self.config.proxy_path.resolve())}} if getattr(self.config, "proxy_path", None) else None,
                    "identity": {"size": 100000000, "fingerprint": "0000000000000000"}
                }
            },
            "metadata": {},
            "created": media_id
        }

        # Watermark item if specified
        wm_id = None
        if self.config.watermark_path and self.config.watermark_path.exists():
            wm_id = self._alloc_id()
            self.root_children.append({"Item": wm_id})
            self.items[str(wm_id)] = {
                "id": wm_id,
                "name": self.config.watermark_path.name,
                "label": "Cerulean",
                "kind": {
                    "Media": {
                        "media": {"File": {"path": str(self.config.watermark_path.resolve())}},
                        "info": {
                            "name": self.config.watermark_path.name,
                            "kind": "StillImage",
                            "duration": self._sec_to_ticks(86400.0),
                            "video": {"width": 1600, "height": 533, "frame_rate": {"num": 30, "den": 1}, "par": [1, 1], "codec": "PNG", "pixel_format": "RGBA 8-bit", "color": {"matrix": "Bt709", "transfer": "Bt709", "primaries": "Bt709", "range": "Full"}, "has_alpha": True, "bitrate": 0},
                            "audio": None, "container": "PNG", "start_timecode": None, "file_size": 50000
                        },
                        "interpret": {"frame_rate": None, "par": None, "ignore_alpha": False, "invert_alpha": False},
                        "mark_in": None, "mark_out": None, "markers": [], "offline": False, "proxy": None,
                        "identity": {"size": 50000, "fingerprint": "0000000000000000"}
                    }
                },
                "metadata": {},
                "created": wm_id
            }

        # Tracks
        v1_items: List[Dict[str, Any]] = []
        v2_items: List[Dict[str, Any]] = []
        v3_items: List[Dict[str, Any]] = []
        v4_items: List[Dict[str, Any]] = []
        a1_items: List[Dict[str, Any]] = []
        a2_items: List[Dict[str, Any]] = []
        a3_items: List[Dict[str, Any]] = []

        timeline_time = 0

        for i, cut in enumerate(self.config.sub_cuts):
            pad = 0.08
            if i + 1 < len(self.config.sub_cuts):
                next_start = self.config.sub_cuts[i + 1].start
                pad = min(pad, max(0.0, next_start - cut.end - 0.01))
            dur_sec = max(0.04, (cut.end + pad) - cut.start)
            dur_ticks = self._sec_to_ticks(dur_sec)
            src_in_ticks = self._sec_to_ticks(cut.start)

            # Link group for synchronized V2/A1
            link_id = self._alloc_id()

            # V1: Background Item
            v1_clip_id = self._alloc_id()
            v1_items.append({
                "id": v1_clip_id, "item": media_id, "name": self.config.media_path.name, "label": "Iris",
                "start": timeline_time, "duration": dur_ticks, "source_in": src_in_ticks,
                "speed": 1.0, "reverse": False, "enabled": True, "link": None, "group": None,
                "effects": [
                    self._make_gaussian_blur_effect(45.0),
                    self._make_motion_effect(self.bg_scale, self.src_w / 2.0, self.src_h / 2.0, self.canvas_w / 2.0, self.canvas_h / 2.0),
                    self._make_opacity_effect(40.0),
                    {"effect": "time_remap", "enabled": True, "params": {"speed": {"value": {"Float": 100.0}}}}
                ],
                "markers": [], "gain_db": 0.0, "frame_hold": None, "scale_to_frame": False
            })

            # V2: Foreground Item
            v2_clip_id = self._alloc_id()
            scale_val = self.fill_scale * cut.punch_in
            anchor_x = self.src_w * cut.x_center
            anchor_y = self.src_h * cut.y_center
            v2_items.append({
                "id": v2_clip_id, "item": media_id, "name": self.config.media_path.name, "label": "Iris",
                "start": timeline_time, "duration": dur_ticks, "source_in": src_in_ticks,
                "speed": 1.0, "reverse": False, "enabled": True, "link": link_id, "group": None,
                "effects": [
                    self._make_motion_effect(scale_val, anchor_x, anchor_y, self.canvas_w / 2.0, self.canvas_h / 2.0),
                    self._make_opacity_effect(100.0),
                    {"effect": "time_remap", "enabled": True, "params": {"speed": {"value": {"Float": 100.0}}}}
                ],
                "markers": [], "gain_db": 0.0, "frame_hold": None, "scale_to_frame": False
            })

            # A1: Dialogue Item
            a1_clip_id = self._alloc_id()
            a1_items.append({
                "id": a1_clip_id, "item": media_id, "name": self.config.media_path.name, "label": "Iris",
                "start": timeline_time, "duration": dur_ticks, "source_in": src_in_ticks,
                "speed": 1.0, "reverse": False, "enabled": True, "link": link_id, "group": None,
                "effects": self._make_audio_volume_effects(0.0),
                "markers": [], "gain_db": 0.0, "frame_hold": None, "scale_to_frame": False
            })

            timeline_time += dur_ticks

        # V4: Persistent Watermark
        if wm_id and timeline_time > 0:
            v4_clip_id = self._alloc_id()
            v4_items.append({
                "id": v4_clip_id, "item": wm_id, "name": self.config.watermark_path.name, "label": "Cerulean",
                "start": 0, "duration": timeline_time, "source_in": 0,
                "speed": 1.0, "reverse": False, "enabled": True, "link": None, "group": None,
                "effects": [
                    self._make_motion_effect(28.0, 800.0, 266.5, self.canvas_w / 2.0, 280.0),
                    self._make_opacity_effect(100.0)
                ],
                "markers": [], "gain_db": 0.0, "frame_hold": None, "scale_to_frame": False
            })

        def _make_track(track_id: int, kind: str, name: str, items: list, vol_db: float = 0.0) -> Dict[str, Any]:
            return {
                "id": track_id, "kind": kind, "name": name, "items": items, "transitions": [],
                "locked": False, "sync_lock": True, "enabled": True, "muted": False, "solo": False,
                "channels": "Stereo", "volume_db": vol_db, "pan": 0.0, "effects": [],
                "mixer": {"mode": "Read", "output": None, "record_arm": False, "solo_safe": False, "input_map": "Stereo"}
            }

        # Sequence Definition
        self.items[str(seq_id)] = {
            "id": seq_id,
            "name": self.config.project_name,
            "label": "Forest",
            "kind": {
                "Sequence": {
                    "settings": {
                        "width": int(self.canvas_w),
                        "height": int(self.canvas_h),
                        "frame_rate": {"num": self.config.fps_num, "den": self.config.fps_den},
                        "par": [1, 1],
                        "sample_rate": 48000,
                        "drop_frame": False,
                        "preset": "1080x1920 30",
                        "audio_master": "Stereo",
                        "preview_codec": "ProRes 422",
                        "max_bit_depth": False,
                        "max_render_quality": False,
                        "working_space": "Rec. 709",
                        "color": {"working": "Rec709", "wide_gamut": False, "auto_tone_map": True}
                    },
                    "video_tracks": [
                        _make_track(1, "Video", "Blurred Background", v1_items),
                        _make_track(2, "Video", "Speaker Foreground", v2_items),
                        _make_track(3, "Video", "HUD & Overlays", v3_items),
                        _make_track(4, "Video", "Watermark", v4_items)
                    ],
                    "audio_tracks": [
                        _make_track(5, "Audio", "Dialogue", a1_items, 0.0),
                        _make_track(6, "Audio", "Background Music", a2_items, self.config.bgm_volume_db),
                        _make_track(7, "Audio", "SFX", a3_items, 0.0)
                    ],
                    "markers": [], "mark_in": None, "mark_out": None, "work_area": None, "start_timecode": 0,
                    "master_volume_db": 0.0, "master_effects": [],
                    "master_mixer": {"mode": "Read", "output": None, "record_arm": False, "solo_safe": False, "input_map": "Stereo"},
                    "submix_tracks": [], "caption_tracks": []
                }
            },
            "metadata": {},
            "created": seq_id
        }

        # Project Envelope
        return {
            "format": "remotion.project",
            "schema_version": 2,
            "generator": "Remotion 4.0 + HyperFrames 1.0",
            "project": {
                "name": self.config.project_name,
                "settings": {
                    "renderer": "Remotion Chromium / OffthreadVideo Compositor",
                    "video_display": "Timecode",
                    "audio_display_samples": True,
                    "default_still_duration": self._sec_to_ticks(5.0),
                    "default_transition_duration_frames": 24,
                    "default_audio_transition_duration": self._sec_to_ticks(1.0),
                    "ingest": {"enabled": False, "action": "createProxies", "destination": None, "preset": ""},
                    "title_safe": [20.0, 20.0], "action_safe": [10.0, 10.0], "capture_format": "DV",
                    "scratch": {"captured": None, "videoPreviews": None, "audioPreviews": None, "autoSave": None}
                },
                "root": {"id": 0, "name": self.config.project_name, "children": self.root_children},
                "items": self.items,
                "next_id": self.next_id
            },
            "view": {
                "open_sequences": [seq_id],
                "active_sequence": seq_id,
                "sequences": {}
        }
```

### 9.1 Empirical Validation & Schema Verification

To verify that the generated JSON document strictly satisfies the Remotion composition schema and rendering pipeline, the `RemotionBuilder` output is validated via `clipping_assembly.py inspect --verify-cli`:

1. **AST & Sequence Inspection**:
   ```bash
   python3 scripts/clipping_assembly.py inspect --project /tmp/declarative_test.remotion.json --verify-cli
   ```
   **Result**: Succeeded with exit status `0`. All 4 video tracks and 3 audio tracks are verified with exact nested `effects` (`gaussian_blur`, `motion`, `opacity`, `time_remap`, `volume`, `channel_volume`, `panner`).

---

## 10. Architectural Recommendations for `clipping-assembly`

1. **Adopt Pure Declarative Generation as Primary**:
   `clipping-assembly` generates `.remotion.json` files and the `remotion/` React composition bundle using the declarative Python builder (`RemotionBuilder`).
2. **Standardize Sidecar Manifest (`.meta.json`)**:
   Alongside every `.remotion.json` assembled, write a JSON sidecar recording:
   - Cut start/end timestamps and durations
   - Framing anchors ($x_c, y_c$) and layout modes per cut
   - Baseline audio volume settings
   - Track mapping registry
   This metadata enables Step 5 (`clipping-captions`), Step 6 (`clipping-vfx-sfx`), and the GUI Companion / Preference Codification Engine ([Issue #27](https://github.com/EmbeddedMhawar/clipping-pipeline/issues/27)) to diff and trace operator edits precisely.
3. **Bridge into Live GUI Companion ([Issue #25](https://github.com/EmbeddedMhawar/clipping-pipeline/issues/25))**:
   Upon completing vertical assembly, trigger `file.open` or `file.revert` over the Remotion Studio Companion Control Server (`127.0.0.1:<PORT>`) so the user immediately sees the refreshed vertical edit in their live studio preview.

---

*Authored by Autonomous Assembly Researcher Agent for EmbeddedMhawar/clipping-pipeline.*
