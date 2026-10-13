"""
Standalone SORT + ByteTrack MOT evaluator for VISO dataset.

Does NOT require mmtracking. Uses only numpy/scipy.
Runs a detection model's cached predictions (or live inference) through
a Kalman-filter tracker and evaluates with py-motmetrics.

Architecture:
    Detection model (mmdet) → per-frame bboxes
           ↓
    ByteTrack / SORT tracker
           ↓
    MOT predictions saved as MOT-challenge CSV
           ↓
    py-motmetrics evaluation vs gt.txt

Usage:
    # Step 1: Run mmdet inference to get per-frame detections, save as pickle
    python scripts/run_mot.py --det-pkl detections/car_001.pkl --seq data-train/mot/car/001

    # Step 2: Run tracker + evaluate all sequences
    python scripts/run_mot.py --mode eval --mot-root data-train/mot --det-dir detections/

    # Quick test with gt detections (oracle tracker, upper-bound):
    python scripts/run_mot.py --mode eval --mot-root data-train/mot --use-gt-det

Dependencies:
    pip install motmetrics scipy numpy
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np

# NumPy 2.0 compatibility: np.asfarray was removed
if not hasattr(np, 'asfarray'):
    np.asfarray = lambda a, dtype=float: np.asarray(a, dtype=dtype)

# ---------------------------------------------------------------------------
# Kalman Filter (for SORT/ByteTrack)
# ---------------------------------------------------------------------------

class KalmanBoxTracker:
    """Tracks a single bounding box state [x1,y1,x2,y2,vx,vy,vw,vh]."""
    count = 0

    def __init__(self, bbox: np.ndarray):
        from scipy.linalg import block_diag
        KalmanBoxTracker.count += 1
        self.id = KalmanBoxTracker.count
        self.hits = 1
        self.hit_streak = 1
        self.age = 0
        self.time_since_update = 0
        self.history = []

        # State: [cx, cy, s, r, dcx, dcy, ds] where s=area, r=aspect ratio
        # Measurement: [cx, cy, s, r]
        dt = 1.0
        # Transition matrix F (7x7)
        self.F = np.eye(7)
        self.F[0, 4] = dt
        self.F[1, 5] = dt
        self.F[2, 6] = dt
        # Measurement matrix H (4x7)
        self.H = np.eye(4, 7)
        # Measurement noise R
        self.R = np.diag([1., 1., 10., 10.])
        # Process noise Q
        self.Q = np.diag([1., 1., 1., 1., 0.01, 0.01, 0.0001])
        # Covariance P
        self.P = np.diag([10., 10., 10., 10., 1e4, 1e4, 1e4])
        # State x
        x1, y1, x2, y2 = bbox[:4]
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        s = (x2 - x1) * (y2 - y1)
        r = (x2 - x1) / (y2 - y1 + 1e-6)
        self.x = np.array([[cx], [cy], [s], [r], [0.], [0.], [0.]])

    def _to_xyxy(self, state):
        cx = float(state[0, 0])
        cy = float(state[1, 0])
        s  = float(state[2, 0])
        r  = float(state[3, 0])
        w = np.sqrt(max(s * r, 0))
        h = s / (w + 1e-6)
        return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        self.age += 1
        if self.time_since_update > 0:
            self.hit_streak = 0
        self.time_since_update += 1
        return self._to_xyxy(self.x)

    def update(self, bbox: np.ndarray):
        x1, y1, x2, y2 = bbox[:4]
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        s = (x2 - x1) * (y2 - y1)
        r = (x2 - x1) / (y2 - y1 + 1e-6)
        z = np.array([[cx], [cy], [s], [r]])

        y_res = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y_res
        self.P = (np.eye(7) - K @ self.H) @ self.P
        self.time_since_update = 0
        self.hits += 1
        self.hit_streak += 1
        self.history = []

    def get_state(self):
        return self._to_xyxy(self.x)


# ---------------------------------------------------------------------------
# IoU utilities
# ---------------------------------------------------------------------------

def iou_batch(bb_test: np.ndarray, bb_gt: np.ndarray) -> np.ndarray:
    """Compute IoU between all pairs. Shape: (N, M)."""
    bb_gt_ = bb_gt[np.newaxis, :, :]   # (1, M, 4)
    bb_test_ = bb_test[:, np.newaxis, :]  # (N, 1, 4)
    xx1 = np.maximum(bb_test_[:, :, 0], bb_gt_[:, :, 0])
    yy1 = np.maximum(bb_test_[:, :, 1], bb_gt_[:, :, 1])
    xx2 = np.minimum(bb_test_[:, :, 2], bb_gt_[:, :, 2])
    yy2 = np.minimum(bb_test_[:, :, 3], bb_gt_[:, :, 3])
    w = np.maximum(0., xx2 - xx1)
    h = np.maximum(0., yy2 - yy1)
    inter = w * h
    area_test = (bb_test_[:, :, 2] - bb_test_[:, :, 0]) * \
                (bb_test_[:, :, 3] - bb_test_[:, :, 1])
    area_gt   = (bb_gt_[:, :, 2] - bb_gt_[:, :, 0]) * \
                (bb_gt_[:, :, 3] - bb_gt_[:, :, 1])
    union = area_test + area_gt - inter
    return inter / (union + 1e-6)


# ---------------------------------------------------------------------------
# SORT Tracker
# ---------------------------------------------------------------------------

class SORTTracker:
    def __init__(self, max_age: int = 3, min_hits: int = 3,
                 iou_threshold: float = 0.3):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.trackers: list[KalmanBoxTracker] = []
        self.frame_count = 0

    def update(self, detections: np.ndarray) -> np.ndarray:
        """
        detections: (N, 5) array of [x1, y1, x2, y2, score]
        Returns: (M, 5) array of [x1, y1, x2, y2, track_id]
        """
        from scipy.optimize import linear_sum_assignment

        self.frame_count += 1

        # Predict from existing trackers
        trks = np.zeros((len(self.trackers), 5))
        to_del = []
        for t, trk in enumerate(trks):
            pos = self.trackers[t].predict()
            trk[:] = [pos[0], pos[1], pos[2], pos[3], 0]
            if np.any(np.isnan(pos)):
                to_del.append(t)
        for t in reversed(to_del):
            self.trackers.pop(t)
        trks = np.delete(trks, to_del, axis=0)

        # Associate detections to trackers via IoU
        matched_indices = np.empty((0, 2), dtype=int)
        unmatched_dets = list(range(len(detections)))
        unmatched_trks = list(range(len(trks)))

        if len(detections) > 0 and len(trks) > 0:
            iou_mat = iou_batch(detections[:, :4], trks[:, :4])
            det_idx, trk_idx = linear_sum_assignment(-iou_mat)
            for d, t in zip(det_idx, trk_idx):
                if iou_mat[d, t] >= self.iou_threshold:
                    matched_indices = np.vstack([matched_indices, [d, t]])
            unmatched_dets = [d for d in range(len(detections))
                              if d not in matched_indices[:, 0]]
            unmatched_trks = [t for t in range(len(trks))
                              if t not in matched_indices[:, 1]]

        # Update matched trackers
        for d, t in matched_indices:
            self.trackers[t].update(detections[d])

        # Create new trackers for unmatched detections
        for d in unmatched_dets:
            self.trackers.append(KalmanBoxTracker(detections[d]))

        # Build result
        results = []
        for t in reversed(range(len(self.trackers))):
            trk = self.trackers[t]
            if trk.time_since_update < 1 and \
               (trk.hit_streak >= self.min_hits or self.frame_count <= self.min_hits):
                pos = trk.get_state()
                results.append([pos[0], pos[1], pos[2], pos[3], trk.id])
            # Remove dead trackers
            if trk.time_since_update > self.max_age:
                self.trackers.pop(t)

        return np.array(results) if results else np.empty((0, 5))


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_gt(gt_path: str) -> dict[int, np.ndarray]:
    """Load MOT gt.txt → {frame_id: (N,6) array [x1,y1,x2,y2,track_id,active]}"""
    gt: dict[int, list] = {}
    with open(gt_path) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 7:
                continue
            frame, tid, x, y, w, h, active = (
                int(parts[0]), int(parts[1]),
                float(parts[2]), float(parts[3]),
                float(parts[4]), float(parts[5]),
                int(parts[6]),
            )
            if active == 0:
                continue
            gt.setdefault(frame, []).append(
                [x, y, x + w, y + h, tid]
            )
    return {k: np.array(v) for k, v in gt.items()}


def xyxy_to_xywh(boxes: np.ndarray) -> np.ndarray:
    """Convert [x1,y1,x2,y2] → [x1,y1,w,h]."""
    r = boxes.copy()
    r[:, 2] = boxes[:, 2] - boxes[:, 0]
    r[:, 3] = boxes[:, 3] - boxes[:, 1]
    return r


# ---------------------------------------------------------------------------
# Per-sequence tracker runner
# ---------------------------------------------------------------------------

def run_sequence(
    seq_dir: str,
    detections: dict[int, np.ndarray],   # frame → (N,5) [x1,y1,x2,y2,score]
    tracker_cfg: dict,
    out_path: str,
) -> None:
    """Run SORT on one sequence and write MOT-format output."""
    KalmanBoxTracker.count = 0
    tracker = SORTTracker(**tracker_cfg)

    img_dir = os.path.join(seq_dir, "img")
    n_frames = len([f for f in os.listdir(img_dir) if f.endswith(".jpg")])

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as out_f:
        for frame_id in range(1, n_frames + 1):
            dets = detections.get(frame_id, np.empty((0, 5)))
            tracks = tracker.update(dets)
            for trk in tracks:
                x1, y1, x2, y2, tid = trk
                w, h = x2 - x1, y2 - y1
                out_f.write(
                    f"{frame_id},{int(tid)},{x1:.1f},{y1:.1f},{w:.1f},{h:.1f},1,-1,-1,-1\n"
                )


# ---------------------------------------------------------------------------
# py-motmetrics evaluation
# ---------------------------------------------------------------------------

def evaluate_mot(
    mot_root: str,
    pred_dir: str,
    classes: list[str] = None,
) -> None:
    try:
        import motmetrics as mm
    except ImportError:
        print("[ERROR] motmetrics not installed. Run: pip install motmetrics")
        sys.exit(1)

    if classes is None:
        classes = ["car", "plane", "ship", "train"]

    accs = []
    names = []

    for cls in classes:
        cls_path = os.path.join(mot_root, cls)
        if not os.path.isdir(cls_path):
            continue
        for seq_id in sorted(os.listdir(cls_path)):
            gt_path   = os.path.join(cls_path, seq_id, "gt", "gt.txt")
            pred_path = os.path.join(pred_dir, cls, seq_id + ".txt")
            if not os.path.exists(gt_path) or not os.path.exists(pred_path):
                continue

            gt_data   = load_gt(gt_path)
            pred_data = load_gt(pred_path)   # same format

            acc = mm.MOTAccumulator(auto_id=True)
            all_frames = sorted(set(list(gt_data.keys()) + list(pred_data.keys())))

            for fid in all_frames:
                gts  = gt_data.get(fid, np.empty((0, 5)))
                preds = pred_data.get(fid, np.empty((0, 5)))

                gt_ids  = gts[:, 4].astype(int).tolist()   if len(gts)  else []
                pr_ids  = preds[:, 4].astype(int).tolist() if len(preds) else []

                if len(gts) > 0 and len(preds) > 0:
                    dist = mm.distances.iou_matrix(
                        gts[:, :4], preds[:, :4], max_iou=0.5
                    )
                else:
                    dist = mm.distances.iou_matrix(
                        np.empty((0, 4)) if not len(gts)  else gts[:, :4],
                        np.empty((0, 4)) if not len(preds) else preds[:, :4],
                        max_iou=0.5,
                    )

                acc.update(gt_ids, pr_ids, dist)

            accs.append(acc)
            names.append(f"{cls}/{seq_id}")

    if not accs:
        print("[WARN] No sequences evaluated.")
        return

    mh = mm.metrics.create()
    summary = mh.compute_many(
        accs,
        metrics=["mota", "motp", "idf1", "num_switches", "mostly_tracked",
                 "mostly_lost", "num_false_positives", "num_misses"],
        names=names,
        generate_overall=True,
    )
    print("\n" + mm.io.render_summary(
        summary,
        formatters=mh.formatters,
        namemap=mm.io.motchallenge_metric_names,
    ))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run SORT tracker on VISO MOT data")
    parser.add_argument("--mode", choices=["track", "eval", "track+eval"],
                        default="track+eval")
    parser.add_argument("--mot-root", default=r"data-train/mot",
                        help="Root of MOT sequences")
    parser.add_argument("--det-dir",  default=r"data/mot_detections",
                        help="Directory with per-sequence detection pkl files")
    parser.add_argument("--pred-dir", default=r"data/mot_predictions",
                        help="Directory for tracker output CSV files")
    parser.add_argument("--use-gt-det", action="store_true",
                        help="Use ground-truth boxes as detections (oracle upper-bound)")
    parser.add_argument("--classes", nargs="*",
                        default=["car", "plane", "ship", "train"])
    parser.add_argument("--max-age",    type=int,   default=3)
    parser.add_argument("--min-hits",   type=int,   default=3)
    parser.add_argument("--iou-thr",    type=float, default=0.3)
    args = parser.parse_args()

    mot_root = os.path.abspath(args.mot_root)
    pred_dir = os.path.abspath(args.pred_dir)
    tracker_cfg = dict(
        max_age=args.max_age,
        min_hits=args.min_hits,
        iou_threshold=args.iou_thr,
    )

    if "track" in args.mode:
        for cls in args.classes:
            cls_path = os.path.join(mot_root, cls)
            if not os.path.isdir(cls_path):
                continue
            for seq_id in sorted(os.listdir(cls_path)):
                seq_dir  = os.path.join(cls_path, seq_id)
                gt_path  = os.path.join(seq_dir, "gt", "gt.txt")
                out_path = os.path.join(pred_dir, cls, seq_id + ".txt")

                if args.use_gt_det:
                    gt_data = load_gt(gt_path)
                    # Convert GT boxes to detection format (add dummy score=1.0)
                    detections = {}
                    for fid, boxes in gt_data.items():
                        scores = np.ones((len(boxes), 1))
                        dets = np.hstack([boxes[:, :4], scores])
                        detections[fid] = dets
                else:
                    # Load pre-computed detections from pkl
                    import pickle
                    det_file = os.path.join(
                        os.path.abspath(args.det_dir), cls, seq_id + ".pkl"
                    )
                    if not os.path.exists(det_file):
                        print(f"  [SKIP] no detections: {det_file}")
                        continue
                    with open(det_file, "rb") as f:
                        detections = pickle.load(f)

                print(f"[{cls}/{seq_id}] tracking -> {out_path}")
                run_sequence(seq_dir, detections, tracker_cfg, out_path)

    if "eval" in args.mode:
        evaluate_mot(mot_root, pred_dir, classes=args.classes)


if __name__ == "__main__":
    main()
