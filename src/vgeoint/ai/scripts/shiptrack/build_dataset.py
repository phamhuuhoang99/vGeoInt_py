"""Step 2 of the YOLO-OBB workflow: cut scenes into tiles + YOLO-OBB label files.

Uses the reviewed candidates (labels/labels_accepted.json). Only open-water tiles are
kept (where the CFAR candidates were exhaustively reviewed); tiles touching the coast
buffer or nodata edge are skipped, so unlabelled harbour ships never become "background".

Layout (ultralytics OBB format, one line per ship: `0 x1 y1 x2 y2 x3 y3 x4 y4`, normalised):
  <out>/images/{train,val}/<scene>_<x>_<y>.png
  <out>/labels/{train,val}/<scene>_<x>_<y>.txt
  <out>/ships.yaml
"""
import argparse
import glob
import json
import os

import cv2
import numpy as np
import rasterio

from detect_ships import COASTAL, GREEN, NIR, cloud_mask, water_mask
from make_labels import MODEL_BANDS


def scene_image(path, coast_buffer_m=300.0):
    """Model input for a scene: uint8 HxWx3 (NIR,R,G) stretched on open-water pixels."""
    with rasterio.open(path) as src:
        data = src.read().astype(np.float32)
        res = src.res[0]
    valid = data[NIR] > 0
    wm = water_mask(data[GREEN], data[NIR], valid, res, coast_buffer_m)
    sea = wm & ~cloud_mask(data[COASTAL], wm)
    ref = sea if sea.sum() > 1e5 else valid
    img = np.zeros(data.shape[1:] + (3,), np.uint8)
    for i, b in enumerate(MODEL_BANDS):
        lo, hi = np.percentile(data[b][ref][::101], [0.5, 99.95])
        hi = lo + (hi - lo) * 4  # leave headroom so bright hulls keep texture
        img[..., i] = np.clip((data[b] - lo) / (hi - lo + 1e-6) * 255, 0, 255)
    img[~valid] = 0
    return img, sea, valid


def tiles(shape, size, stride):
    h, w = shape
    for y in list(range(0, max(h - size, 0), stride)) + [max(h - size, 0)]:
        for x in list(range(0, max(w - size, 0), stride)) + [max(w - size, 0)]:
            yield x, y


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir")
    ap.add_argument("label_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--val_scenes", default="20260415")
    ap.add_argument("--size", type=int, default=640)
    ap.add_argument("--stride", type=int, default=480)
    ap.add_argument("--neg_frac", type=float, default=0.25, help="share of land/cloud tiles kept")
    a = ap.parse_args()

    cands = json.load(open(os.path.join(a.label_dir, "candidates.json")))
    accepted = set(json.load(open(os.path.join(a.label_dir, "labels_accepted.json")))["accepted"])
    boxes = {}
    for c in cands:
        if c["id"] in accepted:
            boxes.setdefault(c["scene"], []).append(np.array(c["poly"], np.float32))

    added = os.path.join(a.label_dir, "labels_added.json")
    if os.path.exists(added):  # ships found later by the model and confirmed (active learning)
        for scene, polys in json.load(open(added)).items():
            if not scene.startswith("_"):
                boxes.setdefault(scene, []).extend(np.array(q, np.float32) for q in polys)
    rng = np.random.default_rng(0)

    for sub in ("images/train", "images/val", "labels/train", "labels/val", "preview"):
        os.makedirs(os.path.join(a.out_dir, sub), exist_ok=True)
    stats = {"train": [0, 0, 0], "val": [0, 0, 0]}  # tiles, positive tiles, boxes
    for p in sorted(glob.glob(os.path.join(a.input_dir, "*_AnalyticMS_8b.tif"))):
        scene = os.path.basename(p)[:23]
        split = "val" if any(scene.startswith(v) for v in a.val_scenes.split(",")) else "train"
        img, sea, valid = scene_image(p)
        sb = boxes.get(scene, [])

        prev = cv2.resize(img[..., ::-1], None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
        for b in sb:
            cv2.polylines(prev, [(b / 4).astype(np.int32)], True, (0, 255, 255), 1)

        for x, y in tiles(img.shape[:2], a.size, a.stride):
            s = sea[y:y + a.size, x:x + a.size]
            v = valid[y:y + a.size, x:x + a.size]
            if v.mean() < 0.999:
                continue  # scene edge
            if s.mean() < 0.95:
                # land / cloud tiles: hard negatives (no ships possible), a random subset.
                # Mixed coast tiles are skipped: moored ships there are not labelled.
                if s.mean() > 0.02 or rng.random() > a.neg_frac:
                    continue
            lines = []
            for b in sb:
                c = b.mean(0)
                if x <= c[0] < x + a.size and y <= c[1] < y + a.size:
                    q = np.clip((b - [x, y]) / a.size, 0, 1)
                    lines.append("0 " + " ".join(f"{t:.6f}" for t in q.ravel()))
            name = f"{scene}_{x}_{y}"
            cv2.imwrite(os.path.join(a.out_dir, "images", split, name + ".png"),
                        np.ascontiguousarray(img[y:y + a.size, x:x + a.size, ::-1]))
            with open(os.path.join(a.out_dir, "labels", split, name + ".txt"), "w") as f:
                f.write("\n".join(lines))
            cv2.rectangle(prev, (x // 4, y // 4), ((x + a.size) // 4, (y + a.size) // 4),
                          (0, 128, 255) if lines else (80, 80, 80), 1)
            st = stats[split]
            st[0] += 1
            st[1] += bool(lines)
            st[2] += len(lines)
        cv2.imwrite(os.path.join(a.out_dir, "preview", scene + ".jpg"), prev)

    root = os.path.abspath(a.out_dir).replace("\\", "/")
    with open(os.path.join(a.out_dir, "ships.yaml"), "w") as f:
        f.write(f"path: {root}\ntrain: images/train\nval: images/val\nnames:\n  0: ship\n")
    for k, (n, pos, nb) in stats.items():
        print(f"{k}: {n} tiles, {pos} with ships, {nb} ship boxes")
