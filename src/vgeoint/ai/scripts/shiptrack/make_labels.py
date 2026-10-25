"""Step 1 of the YOLO-OBB workflow: propose oriented-box label candidates for review.

Candidates come from two CFAR-style detectors on open water:
  - bright: NIR above local background (white/red hulls, deck structures)
  - dark:   visible bands below local background (dark hulls on hazy / turbid water)
Each candidate gets an oriented box from the minimum-area rectangle of its pixels.

Outputs in <out_dir>:
  candidates.json          all candidates (scene, id, polygon in pixel coords, kind, snr)
  review_<scene>_<k>.png   numbered chip mosaics to accept/reject candidates by eye
The accepted ids are then listed in labels_accepted.json (see build_dataset.py).
"""
import argparse
import glob
import json
import os

import cv2
import numpy as np
import rasterio

from detect_ships import (BLUE, COASTAL, GREEN, NIR, RED, cloud_mask, robust_sigma,
                          water_mask)

MODEL_BANDS = [NIR, RED, GREEN]  # false-colour input for the detector (ships pop in NIR)


def scene_stretch(data, valid):
    """Per-scene percentile stretch of MODEL_BANDS -> uint8 HxWx3."""
    out = np.zeros(data.shape[1:] + (3,), np.uint8)
    for i, b in enumerate(MODEL_BANDS):
        lo, hi = np.percentile(data[b][valid][::101], [0.5, 99.9])
        out[..., i] = np.clip((data[b] - lo) / (hi - lo + 1e-6) * 255, 0, 255)
    return out


def local_resid(band):
    bg = cv2.blur(cv2.medianBlur(cv2.resize(band, None, fx=0.25, fy=0.25), 5), (9, 9))
    return band - cv2.resize(bg, (band.shape[1], band.shape[0]), interpolation=cv2.INTER_LINEAR)


def components(mask, score, sig, min_snr, kind, res):
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    grouped = cv2.dilate(mask, np.ones((7, 7), np.uint8))
    n, glab, st, _ = cv2.connectedComponentsWithStats(grouped, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, _ = st[i]
        if w * h > 250 * 250 or max(w, h) * res < 20:
            continue
        sub = (glab[y:y + h, x:x + w] == i) & (mask[y:y + h, x:x + w] > 0)
        if sub.sum() < 6:
            continue
        peak = float(score[y:y + h, x:x + w][sub].max())
        snr = peak / sig
        if snr < min_snr:
            continue
        # keep the hull, not the faint foam/wake around it
        hull = sub & (score[y:y + h, x:x + w] > max(0.3 * peak, 6 * sig))
        if hull.sum() >= 4:
            sub = hull
        ys, xs = np.nonzero(sub)
        rect = cv2.minAreaRect(np.stack([xs + x, ys + y], 1).astype(np.float32))
        (cx, cy), (rw, rh), ang = rect
        rect = ((cx, cy), (rw + 1, rh + 1), ang)
        aspect = max(rw, rh) / (min(rw, rh) + 1)
        if aspect < 1.3 and sub.sum() > 60:
            continue  # big round blob
        if kind == "dark" and (aspect < 2.5 or not 40 <= max(rw, rh) * res <= 400):
            continue  # dark slicks / algae lines: only keep hull-shaped dark targets
        out.append(dict(kind=kind, snr=round(float(snr), 1), cx=round(cx, 1), cy=round(cy, 1),
                        poly=cv2.boxPoints(rect).round(1).tolist()))
    return out


def propose(path, coast_buffer_m=300.0):
    with rasterio.open(path) as src:
        data = src.read().astype(np.float32)
        res = src.res[0]
    valid = data[NIR] > 0
    wm = water_mask(data[GREEN], data[NIR], valid, res, coast_buffer_m)
    sea = wm & ~cloud_mask(data[COASTAL], wm)

    r_nir = local_resid(data[NIR])
    _, s_nir = robust_sigma(r_nir[sea][::53])
    bright = components((r_nir > 6 * s_nir) & sea, r_nir, s_nir, 20, "bright", res)

    vis = (data[BLUE] + data[GREEN] + data[RED]) / 3
    r_vis = -local_resid(vis)
    _, s_vis = robust_sigma(r_vis[sea][::53])
    dark = components((r_vis > 6 * s_vis) & sea, r_vis, s_vis, 15, "dark", res)

    # a dark hull next to its bright wake/superstructure shows up in both: keep the bright one
    keep_dark = [d for d in dark
                 if all(np.hypot(d["cx"] - b["cx"], d["cy"] - b["cy"]) > 30 for b in bright)]
    return data, valid, bright + keep_dark


def save_review(img, cands, scene, out_dir, per_sheet=48):
    tiles = []
    for c in cands:
        p = np.array(c["poly"])
        chip = int(max(64, 1.6 * np.ptp(p, 0).max()))
        zoom = 192 / chip
        x0, y0 = int(c["cx"]) - chip // 2, int(c["cy"]) - chip // 2
        pad = np.zeros((chip, chip, 3), np.uint8)
        xs0, ys0 = max(x0, 0), max(y0, 0)
        xs1, ys1 = min(x0 + chip, img.shape[1]), min(y0 + chip, img.shape[0])
        pad[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0] = img[ys0:ys1, xs0:xs1]
        # RGB(NIR,R,G) -> BGR for cv2 so NIR shows as red
        t = cv2.resize(np.ascontiguousarray(pad[..., ::-1]), (192, 192),
                       interpolation=cv2.INTER_NEAREST)
        poly = ((np.array(c["poly"]) - [x0, y0]) * zoom).astype(np.int32)
        cv2.polylines(t, [poly], True, (0, 255, 255), 1)
        cv2.putText(t, f'{c["id"]} {c["kind"][0]}{c["snr"]:.0f}', (3, 14), 0, 0.45,
                    (255, 255, 255), 1)
        tiles.append(t)
    for k in range(0, len(tiles), per_sheet):
        sheet = tiles[k:k + per_sheet]
        sheet += [np.zeros_like(tiles[0])] * (per_sheet - len(sheet))
        rows = [np.hstack(sheet[r:r + 8]) for r in range(0, per_sheet, 8)]
        cv2.imwrite(os.path.join(out_dir, f"review_{scene}_{k // per_sheet}.png"), np.vstack(rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir")
    ap.add_argument("out_dir")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    allc = []
    for p in sorted(glob.glob(os.path.join(a.input_dir, "*_AnalyticMS_8b.tif"))):
        scene = os.path.basename(p)[:23]
        data, valid, cands = propose(p)
        for i, c in enumerate(cands):
            c.update(scene=scene, id=f"{scene[4:8]}-{i}")
        # chips shown as an NIR/R/G false-colour composite, same as the model input
        save_review(scene_stretch(data, valid), cands, scene, a.out_dir)
        allc += cands
        print(scene, len(cands), "candidates",
              sum(c["kind"] == "dark" for c in cands), "dark")
    with open(os.path.join(a.out_dir, "candidates.json"), "w") as f:
        json.dump(allc, f)
