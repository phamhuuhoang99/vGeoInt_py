"""Active-learning helper: chip mosaics of model detections that are NOT yet labelled.

Reviewing these finds ships the CFAR proposer missed (add them to labels) and the
model's false alarms (hard negatives). Accepted new ships go into
labels/labels_added.json as {"<scene>": [[[x,y]*4], ...]} pixel polygons.
"""
import argparse
import glob
import json
import os

import cv2
import numpy as np
import pandas as pd

from build_dataset import scene_image

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir")
    ap.add_argument("pred_dir")
    ap.add_argument("label_dir")
    ap.add_argument("out_dir")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    cands = json.load(open(os.path.join(a.label_dir, "candidates.json")))
    acc = set(json.load(open(os.path.join(a.label_dir, "labels_accepted.json")))["accepted"])
    for p in sorted(glob.glob(os.path.join(a.input_dir, "*_AnalyticMS_8b.tif"))):
        scene = os.path.basename(p)[:23]
        d = pd.read_csv(os.path.join(a.pred_dir, scene + "_ships.csv"))
        lab = np.array([[c["cx"], c["cy"]] for c in cands if c["scene"] == scene and c["id"] in acc])
        if len(lab):
            dist = np.hypot(d.px.values[:, None] - lab[None, :, 0], d.py.values[:, None] - lab[None, :, 1]).min(1)
        else:
            dist = np.full(len(d), np.inf)
        new = d[dist > 30].reset_index(drop=True)
        print(scene, f"{len(d)} predicted, {len(d) - len(new)} match labels, {len(new)} to review")
        if not len(new):
            continue
        img = scene_image(p, coast_buffer_m=0.0)[0]
        tiles = []
        for _, r in new.iterrows():
            chip = int(max(80, 2.0 * r.length_m / 3))
            x0, y0 = int(r.px) - chip // 2, int(r.py) - chip // 2
            pad = np.zeros((chip, chip, 3), np.uint8)
            xs0, ys0 = max(x0, 0), max(y0, 0)
            xs1, ys1 = min(x0 + chip, img.shape[1]), min(y0 + chip, img.shape[0])
            pad[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0] = img[ys0:ys1, xs0:xs1]
            t = cv2.resize(np.ascontiguousarray(pad[..., ::-1]), (192, 192), interpolation=cv2.INTER_NEAREST)
            cv2.putText(t, f"{scene[4:8]}-{r.id} {r.conf:.2f}", (3, 14), 0, 0.45, (255, 255, 255), 1)
            tiles.append(t)
        tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % 8)
        sheet = np.vstack([np.hstack(tiles[i:i + 8]) for i in range(0, len(tiles), 8)])
        cv2.imwrite(os.path.join(a.out_dir, f"review_pred_{scene}.png"), sheet)
