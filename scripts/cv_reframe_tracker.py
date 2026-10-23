#!/usr/bin/env python3
"""Offline Computer-Vision Speaker/Reactionist Reframe Tracker for Short-Form Vertical Video.

Pipeline:
1. Detection: High-precision face detection via OpenCV YuNet CNN (or upper-body fallback),
   seeded with candidate x_center and disambiguated across multi-person two-shots.
2. 3-Stage Stabilization:
   - Deadband (Virtual Tripod Hysteresis) to eliminate micro-jitter
   - Lookahead smoothing (bidirectional moving average / One-Euro filter)
   - Viewport edge clamping to prevent canvas black borders
3. Keyframe Simplification:
   - Ramer-Douglas-Peucker (RDP) algorithm to generate sparse, clean { t, xc }
     keyframes for props.json and Remotion Studio Props editor.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

DEFAULT_MODEL_PATH = Path(__file__).parent / "face_detection_yunet_2023mar.onnx"
DEFAULT_DEADBAND = 0.035
DEFAULT_EPSILON = 0.005


def rdp_simplify(points: List[Tuple[float, float]], epsilon: float = 0.005) -> List[Tuple[float, float]]:
    """Ramer-Douglas-Peucker line simplification on 2D (t, xc) points."""
    if len(points) < 3:
        return points

    t0, x0 = points[0]
    t1, x1 = points[-1]
    dx = t1 - t0
    dy = x1 - x0
    dist_denom = math.hypot(dx, dy)
    if dist_denom == 0.0:
        return [points[0], points[-1]]

    dmax = 0.0
    index = 0
    for i in range(1, len(points) - 1):
        t, x = points[i]
        d = abs(dy * t - dx * x + t1 * x0 - x1 * t0) / dist_denom
        if d > dmax:
            index = i
            dmax = d

    if dmax > epsilon:
        rec1 = rdp_simplify(points[: index + 1], epsilon)
        rec2 = rdp_simplify(points[index:], epsilon)
        return rec1[:-1] + rec2
    else:
        return [points[0], points[-1]]


def apply_deadband(raw_points: List[Tuple[float, float]], deadband: float = DEFAULT_DEADBAND) -> List[Tuple[float, float]]:
    """Applies virtual tripod hysteresis: camera stays stationary while subject remains within ±deadband."""
    if not raw_points:
        return []

    cam = raw_points[0][1]
    stabilized: List[Tuple[float, float]] = []

    for t, x in raw_points:
        diff = x - cam
        if abs(diff) > deadband:
            if diff > 0:
                cam = x - deadband
            else:
                cam = x + deadband
        stabilized.append((t, cam))

    return stabilized


def apply_lookahead_smoothing(points: List[Tuple[float, float]], window_radius: int = 2) -> List[Tuple[float, float]]:
    """Applies bidirectional moving average window to eliminate high-frequency jitter."""
    if len(points) <= window_radius * 2:
        return points

    smoothed: List[Tuple[float, float]] = []
    n = len(points)

    for i in range(n):
        i_min = max(0, i - window_radius)
        i_max = min(n, i + window_radius + 1)
        sub_x = [points[j][1] for j in range(i_min, i_max)]
        smoothed.append((points[i][0], sum(sub_x) / len(sub_x)))

    return smoothed


def clamp_viewport_edges(
    points: List[Tuple[float, float]],
    punch_in: float = 1.0,
    canvas_w: int = 1080,
    src_w: int = 1920,
) -> List[Tuple[float, float]]:
    """Clamps xc so 9:16 vertical crop never pans past 16:9 edges (preventing black borders)."""
    scale = (1920.0 / 1080.0) * punch_in
    max_normalized_half_w = canvas_w / (2.0 * src_w * scale)  # ~0.1582 at 1.0x

    clamped: List[Tuple[float, float]] = []
    for t, x in points:
        c_x = max(max_normalized_half_w, min(1.0 - max_normalized_half_w, x))
        clamped.append((t, c_x))

    return clamped


class SpeakerCVTracker:
    """Tracks a single speaker or reactionist across a video segment using YuNet + fallback."""

    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH).resolve()
        if not self.model_path.is_file():
            raise FileNotFoundError(f"YuNet model not found at {self.model_path}")
        self.detector = cv2.FaceDetectorYN.create(
            str(self.model_path),
            "",
            (960, 540),
            0.35,  # score threshold
            0.30,  # nms threshold
            5000,
        )

    def track_segment(
        self,
        video_path: Path,
        start_sec: float,
        end_sec: float,
        seed_xc: float,
        punch_in: float = 1.0,
        deadband: float = DEFAULT_DEADBAND,
        epsilon: float = DEFAULT_EPSILON,
    ) -> List[Dict[str, float]]:
        """Tracks target in [start_sec, end_sec], producing stabilized RDP keyframes."""
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Failed to open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        start_f = max(0, int(round(start_sec * fps)))
        end_f = int(round(end_sec * fps))

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
        self.detector.setInputSize((960, 540))

        current_xc = seed_xc
        raw_samples: List[Tuple[float, float]] = []

        for f_idx in range(start_f, end_f + 1):
            ret, bgr = cap.read()
            if not ret:
                break

            t_rel = round((f_idx - start_f) / fps, 3)
            img = cv2.resize(bgr, (960, 540))
            _, faces = self.detector.detect(img)

            best_xc = None
            min_dist = float("inf")

            if faces is not None and len(faces) > 0:
                for f in faces:
                    x, y, w, h = f[0:4]
                    cx = float((x + w / 2.0) / 960.0)
                    dist = abs(cx - current_xc)
                    # Disambiguation: associate by nearest horizontal distance to active track
                    if dist < min_dist and dist < 0.25:
                        min_dist = dist
                        best_xc = cx

            if best_xc is not None:
                current_xc = best_xc

            raw_samples.append((t_rel, current_xc))

        cap.release()

        if not raw_samples:
            return [{"t": 0.0, "xc": round(seed_xc, 3)}]

        # 1. Deadband hysteresis
        db_pts = apply_deadband(raw_samples, deadband=deadband)

        # 2. Lookahead bidirectional smoothing
        smooth_pts = apply_lookahead_smoothing(db_pts, window_radius=3)

        # 3. Viewport edge clamping
        clamped_pts = clamp_viewport_edges(smooth_pts, punch_in=punch_in)

        # 4. RDP keyframe simplification
        simplified = rdp_simplify(clamped_pts, epsilon=epsilon)

        return [{"t": round(t, 2), "xc": round(x, 3)} for t, x in simplified]


def main():
    parser = argparse.ArgumentParser(description="CV Reframe Speaker Tracker")
    parser.add_argument("--video", required=True, help="Path to video file")
    parser.add_argument("--start", type=float, required=True, help="Start time in seconds")
    parser.add_argument("--end", type=float, required=True, help="End time in seconds")
    parser.add_argument("--seed-xc", type=float, default=0.5, help="Seed x_center (0..1)")
    parser.add_argument("--punch-in", type=float, default=1.0, help="Punch-in zoom multiplier")
    parser.add_argument("--deadband", type=float, default=DEFAULT_DEADBAND, help="Virtual tripod deadband")
    parser.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON, help="RDP epsilon tolerance")
    args = parser.parse_args()

    tracker = SpeakerCVTracker()
    keyframes = tracker.track_segment(
        video_path=Path(args.video),
        start_sec=args.start,
        end_sec=args.end,
        seed_xc=args.seed_xc,
        punch_in=args.punch_in,
        deadband=args.deadband,
        epsilon=args.epsilon,
    )

    print(json.dumps(keyframes, indent=2))


if __name__ == "__main__":
    main()
