from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np

# Try importing onnxruntime
try:
    import onnxruntime as ort
except ImportError:
    print("[ERROR] onnxruntime not installed. Please run: pip install onnxruntime (or onnxruntime-gpu)")
    sys.exit(1)

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

def preprocess_image(img: np.ndarray, target_size: tuple[int, int] = (1024, 1024)) -> tuple[np.ndarray, float]:
    """Resize keeping aspect ratio, convert to RGB, normalize, and pad to divisible by 32."""
    h, w = img.shape[:2]
    # Resize keeping aspect ratio
    scale = min(target_size[0] / h, target_size[1] / w)
    new_h = int(h * scale)
    new_w = int(w * scale)
    resized = cv2.resize(img, (new_w, new_h))
    
    # Pad to divisible by 32
    pad_h = (32 - new_h % 32) % 32
    pad_w = (32 - new_w % 32) % 32
    padded = cv2.copyMakeBorder(resized, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=0)
    
    # Convert BGR to RGB
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    
    # Normalize with standard MMDetection ImageNet values
    mean = np.array([123.675, 116.28, 103.53], dtype=np.float32)
    std = np.array([58.395, 57.12, 57.375], dtype=np.float32)
    norm = (rgb.astype(np.float32) - mean) / std
    
    # Transpose to BCHW
    tensor = norm.transpose(2, 0, 1)
    tensor = np.expand_dims(tensor, axis=0) # [1, 3, H, W]
    
    return tensor, scale

def main() -> int:
    parser = argparse.ArgumentParser(description="Detect and track objects in a video using ONNX Runtime")
    parser.add_argument("--video", required=True, help="Input video path")
    parser.add_argument("--model", required=True, help="Path to exported model.onnx file")
    parser.add_argument("--out", default="outputs/track_002.mp4", help="Output video path")
    parser.add_argument("--score-thr", type=float, default=0.05)
    parser.add_argument("--max-frames", type=int, default=0, help="0 means all frames")
    parser.add_argument("--device", default="cuda:0", help="cuda:0 or cpu")
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

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"[ERROR] ONNX Model not found: {model_path}")
        return 2

    # Ensure the directory containing run_mot.py is on sys.path.
    _scripts_dir = str(Path(__file__).parent)
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)
    try:
        from run_mot import SORTTracker
    except Exception as exc:
        print(f"[ERROR] Failed importing SORTTracker: {exc}")
        return 3

    # Setup ONNX Runtime Session Options and register custom operator DLL
    session_options = ort.SessionOptions()
    dll_name = 'mmdeploy_onnxruntime_ops.dll' if os.name == 'nt' else 'libmmdeploy_onnxruntime_ops.so'
    
    search_paths = [
        Path(_scripts_dir) / dll_name,
        Path(_scripts_dir).parent / 'onnx_output' / dll_name,
        Path(os.getcwd()) / dll_name,
        model_path.parent / dll_name
    ]
    
    dll_path = None
    for p in search_paths:
        if p.exists():
            dll_path = str(p)
            break
            
    if dll_path:
        print(f"Registering custom operators library from: {dll_path}")
        session_options.register_custom_ops_library(dll_path)
    else:
        print("[WARN] mmdeploy_onnxruntime_ops library not found. Running without custom ops (this will fail if model contains custom nodes).")

    # Select Providers
    providers = ['CPUExecutionProvider']
    if args.device.lower().startswith("cuda"):
        available = ort.get_available_providers()
        if 'CUDAExecutionProvider' in available:
            providers.insert(0, 'CUDAExecutionProvider')
            print("Running on device: CUDA (GPU)")
        else:
            print("[WARN] CUDA device requested but CUDAExecutionProvider not available. Running on CPU.")
            print("Running on device: CPU")
    else:
        print("Running on device: CPU")

    print(f"Loading ONNX Session from {model_path}...")
    try:
        session = ort.InferenceSession(str(model_path), session_options, providers=providers)
    except Exception as e:
        print(f"[ERROR] Failed to initialize ONNX Runtime session: {e}")
        return 4

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

        # Preprocess frame (resize, pad, format to tensor)
        tensor, scale = preprocess_image(frame, target_size=(1024, 1024))
        
        # Inference using ONNX Runtime
        # Inputs: {'input': tensor}
        # Outputs: [dets, labels]
        try:
            outputs = session.run(None, {'input': tensor})
            dets_out = outputs[0][0]  # Shape: [num_dets, 5] (x1, y1, x2, y2, score)
            
            # Scale coordinates back to original frame coordinates
            bboxes = dets_out[:, :4] / scale
            scores = dets_out[:, 4]
        except Exception as e:
            print(f"[ERROR] Inference failed at frame {frame_idx}: {e}")
            break

        # Filter by threshold
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
