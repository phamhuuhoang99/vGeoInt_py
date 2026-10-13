from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np

try:
    import torch
except Exception:  # pragma: no cover
    torch = None

# Reduce chance of OpenMP duplicate runtime crashes on Windows.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


# Generate distinct colours per track ID (HSV hue rotation).
_TRACK_COLORS: dict[int, tuple[int, int, int]] = {}


def _color_for(tid: int) -> tuple[int, int, int]:
    if tid not in _TRACK_COLORS:
        hue = int((tid * 47) % 180)  # golden-ratio-ish spread
        bgr = cv2.cvtColor(np.uint8([[[hue, 220, 255]]]), cv2.COLOR_HSV2BGR)[0, 0]
        _TRACK_COLORS[tid] = (int(bgr[0]), int(bgr[1]), int(bgr[2]))
    return _TRACK_COLORS[tid]


# Stores centre-point history for every track ID.
_TRACK_HISTORY: dict[int, list[tuple[int, int]]] = {}


def draw_tracks(
    frame: np.ndarray,
    tracks: np.ndarray,
    draw_trails: bool = True,
    trail_len: int = 0,
) -> np.ndarray:
    """Draw bounding boxes, IDs, and optional motion trails.

    Args:
        trail_len: max number of past points to keep (0 = unlimited).
    """
    out = frame.copy()

    active_ids: set[int] = set()
    for trk in tracks:
        x1, y1, x2, y2, tid = trk
        tid = int(tid)
        active_ids.add(tid)
        cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)

        # Update history
        hist = _TRACK_HISTORY.setdefault(tid, [])
        hist.append((cx, cy))
        if trail_len > 0 and len(hist) > trail_len:
            _TRACK_HISTORY[tid] = hist[-trail_len:]

        color = _color_for(tid)
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)

    # Draw trajectory trails
    if draw_trails:
        for tid, hist in _TRACK_HISTORY.items():
            if len(hist) < 2:
                continue
            color = _color_for(tid)
            for i in range(1, len(hist)):
                cv2.line(out, hist[i - 1], hist[i], color, 2, cv2.LINE_AA)

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect and track objects in a video")
    parser.add_argument("--video", required=True, help="Input video path")
    parser.add_argument("--checkpoint", required=True, help="MMDet checkpoint path")
    parser.add_argument(
        "--config",
        default="configs/viso/faster_rcnn_r50_fpn_viso.py",
        help="MMDet config path",
    )
    parser.add_argument("--out", default="outputs/track_002.mp4", help="Output video path")
    parser.add_argument("--score-thr", type=float, default=0.05)
    parser.add_argument("--max-frames", type=int, default=0, help="0 means all frames")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--max-age", type=int, default=3)
    parser.add_argument("--min-hits", type=int, default=3)
    parser.add_argument("--iou-thr", type=float, default=0.3)
    parser.add_argument("--trail-len", type=int, default=0,
                        help="Max trail length per track (0 = unlimited)")
    parser.add_argument("--no-trails", action="store_true",
                        help="Disable trajectory trails")
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"[ERROR] Video not found: {video_path}")
        return 2

    cfg_path = Path(args.config)
    ckpt_path = Path(args.checkpoint)
    if not cfg_path.exists():
        print(f"[ERROR] Config not found: {cfg_path}")
        return 2
    if not ckpt_path.exists():
        print(f"[ERROR] Checkpoint not found: {ckpt_path}")
        return 2

    # Import after argv/env setup so missing deps fail clearly.
    try:
        from mmdet.apis import init_detector, inference_detector
    except Exception as exc:  # pragma: no cover
        print(f"[ERROR] Failed importing mmdet APIs: {exc}")
        return 3

    # Ensure the directory containing run_mot.py is on sys.path.
    _scripts_dir = str(Path(r"/scripts"))
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)
    try:
        from run_mot import SORTTracker
    except Exception as exc:
        print(f"[ERROR] Failed importing SORTTracker: {exc}")
        print(f"  __file__ resolved to: {Path(__file__).resolve()}")
        print(f"  sys.path: {sys.path[:5]}")
        return 3

    requested_device = args.device
    resolved_device = requested_device

    # If CUDA is requested but unavailable, transparently fall back to CPU.
    if requested_device.lower().startswith("cuda"):
        cuda_available = bool(torch is not None and torch.cuda.is_available())
        if not cuda_available:
            print("[WARN] CUDA device requested but no NVIDIA GPU/driver found. Falling back to CPU.")
            resolved_device = "cpu"

    print(f"Loading detector on device: {resolved_device}")
    try:
        model = init_detector(str(cfg_path), str(ckpt_path), device=resolved_device)
    except RuntimeError as exc:
        err_msg = str(exc).lower()
        if resolved_device != "cpu" and ("cuda" in err_msg or "nvidia" in err_msg):
            print("[WARN] Failed to initialize detector on CUDA. Retrying on CPU...")
            model = init_detector(str(cfg_path), str(ckpt_path), device="cpu")
            resolved_device = "cpu"
        else:
            raise

    if resolved_device != requested_device:
        print(f"[INFO] Device switched from '{requested_device}' to '{resolved_device}'.")

    tracker = SORTTracker(max_age=args.max_age, min_hits=args.min_hits, iou_threshold=args.iou_thr)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[ERROR] Cannot open video: {video_path}")
        return 4

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps if fps > 0 else 25.0, (width, height))

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame_idx += 1
        if args.max_frames > 0 and frame_idx > args.max_frames:
            break

        result = inference_detector(model, frame)
        bboxes = result.pred_instances.bboxes.detach().cpu().numpy()
        scores = result.pred_instances.scores.detach().cpu().numpy()

        keep = scores >= args.score_thr
        if np.any(keep):
            dets = np.hstack([bboxes[keep], scores[keep, np.newaxis]])
        else:
            dets = np.empty((0, 5), dtype=np.float32)

        tracks = tracker.update(dets)
        vis = draw_tracks(frame, tracks,
                          draw_trails=not args.no_trails,
                          trail_len=args.trail_len)
        cv2.putText(
            vis,
            f"frame={frame_idx} det={len(dets)} trk={len(tracks)}",
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        writer.write(vis)

        if frame_idx % 50 == 0:
            print(f"processed {frame_idx} frames")

    cap.release()
    writer.release()
    print(f"Done. Output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
