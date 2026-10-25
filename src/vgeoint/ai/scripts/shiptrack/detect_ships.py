"""Prototype ship detection for PlanetScope SuperDove 8-band (3B AnalyticMS) scenes.

Pipeline per scene:
  1. Water mask from NDWI (green vs NIR), smoothed so ships inside water stay "water".
  2. Cloud mask: bright in coastal-blue AND large connected area -> excluded (+ buffer).
  3. Candidates: NIR anomaly above local background (CFAR-like, robust sigma).
  4. Shape filter: area, length, elongation.
  5. Motion cue: SuperDove bands are captured at slightly different times, so a moving
     ship's centroid shifts between band groups (blue bands vs red/NIR bands).
     The shift vector gives heading; magnitude / inter-band delay gives speed.

Outputs: <out>/<scene>_ships.csv and <out>/<scene>_ships.geojson
"""
import argparse
import csv
import glob
import json
import os

import cv2
import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform

# band indices (0-based) in AnalyticMS_8b
COASTAL, BLUE, GREEN_I, GREEN, YELLOW, RED, REDEDGE, NIR = range(8)
EARLY = [COASTAL, BLUE, GREEN_I]   # band groups used for the motion offset
LATE = [RED, REDEDGE, NIR]


def robust_sigma(x):
    med = np.median(x)
    return med, 1.4826 * np.median(np.abs(x - med))


def water_mask(green, nir, valid, res=3.0, coast_buffer_m=600.0):
    ndwi = (green - nir) / (green + nir + 1e-6)
    small = cv2.resize(ndwi, None, fx=1 / 16, fy=1 / 16, interpolation=cv2.INTER_AREA)
    small = cv2.medianBlur(small.astype(np.float32), 5)
    # clouds / haze over sea pull NDWI towards 0, land is negative; open sea is ~0.4-0.5
    # haze lowers sea NDWI scene-to-scene, so pick the land/sea split per scene (Otsu)
    v = small[np.isfinite(small) & (small != 0)]
    u8 = np.clip((v + 1) * 127.5, 0, 255).astype(np.uint8)
    otsu, _ = cv2.threshold(u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thr = float(np.clip(otsu / 127.5 - 1, 0.0, 0.3))
    sm = (small > thr).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(sm)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, 4] > 0.02 * sm.size  # drop rivers, ponds, small inlets
    sea = keep[lab]
    # buffer from land/cloud only (not from the scene's nodata edge): harbours, river mouths,
    # piers and surf produce most false alarms, so the prototype stays offshore
    vsmall = cv2.resize(valid.astype(np.uint8), (small.shape[1], small.shape[0]),
                        interpolation=cv2.INTER_NEAREST) > 0
    land = vsmall & ~sea
    dist = cv2.distanceTransform((~land).astype(np.uint8), cv2.DIST_L2, 5) * 16 * res
    sm = (sea & (dist > coast_buffer_m)).astype(np.uint8)
    m = cv2.resize(sm, (green.shape[1], green.shape[0]), interpolation=cv2.INTER_NEAREST)
    return (m > 0) & valid


def cloud_mask(coastal, valid):
    med, sig = robust_sigma(coastal[valid][::97])  # valid = water pixels
    bright = ((coastal > med + 6 * sig) & valid).astype(np.uint8)
    small = cv2.resize(bright, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    n, lab, st, _ = cv2.connectedComponentsWithStats((small > 0).astype(np.uint8))
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, 4] > 60  # > ~60*64 px (~35 ha): clouds, not ships
    big = keep[lab].astype(np.uint8)
    big = cv2.dilate(big, np.ones((9, 9), np.uint8))
    return cv2.resize(big, (coastal.shape[1], coastal.shape[0]),
                      interpolation=cv2.INTER_NEAREST) > 0


def band_centroid(patch, bg):
    p = np.clip(patch - bg, 0, None)
    s = p.sum()
    if s <= 0:
        return np.nan, np.nan
    yy, xx = np.mgrid[:p.shape[0], :p.shape[1]]
    return (xx * p).sum() / s, (yy * p).sum() / s


def save_quicklook(data, sea, rows, path, scale=4):
    h, w = data.shape[1] // scale, data.shape[2] // scale
    img = np.zeros((h, w, 3), np.uint8)
    for i, b in enumerate([BLUE, GREEN, RED]):
        band = cv2.resize(data[b], (w, h), interpolation=cv2.INTER_AREA)
        v = band[band > 0]
        lo, hi = np.percentile(v, [1, 99]) if v.size else (0, 1)
        img[..., i] = np.clip((band - lo) / (hi - lo + 1e-6) * 255, 0, 255)
    edge = cv2.morphologyEx(cv2.resize(sea.astype(np.uint8), (w, h)), cv2.MORPH_GRADIENT,
                            np.ones((3, 3), np.uint8))
    img[edge > 0] = (255, 128, 0)
    for r in rows:
        c = (int(r["px"] / scale), int(r["py"] / scale))
        cv2.circle(img, c, 12, (0, 255, 255), 2)
        if r["band_shift_m"] > 6:  # likely moving: draw motion direction
            a = np.radians(r["motion_heading_deg"])
            cv2.arrowedLine(img, c, (int(c[0] + 30 * np.sin(a)), int(c[1] - 30 * np.cos(a))),
                            (0, 0, 255), 2, tipLength=0.4)
    cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, 85])


def detect(path, out_dir, k=6.0, min_area=6, max_area=6000, min_snr=25.0):
    scene = os.path.basename(path)[:23]
    with rasterio.open(path) as src:
        data = src.read().astype(np.float32)
        tr, crs, res = src.transform, src.crs, src.res[0]
    valid = data[NIR] > 0
    wm = water_mask(data[GREEN], data[NIR], valid, res)
    cm = cloud_mask(data[COASTAL], wm)
    sea = wm & ~cm

    nir = data[NIR]
    bg = cv2.blur(cv2.medianBlur(cv2.resize(nir, None, fx=0.25, fy=0.25), 5), (9, 9))
    bg = cv2.resize(bg, (nir.shape[1], nir.shape[0]), interpolation=cv2.INTER_LINEAR)
    resid = nir - bg
    _, sig = robust_sigma(resid[sea][::53])
    cand = ((resid > k * sig) & sea).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # group fragments of one ship (hull pieces, superstructure, deck cargo) within ~20 m
    grouped = cv2.dilate(cand, np.ones((7, 7), np.uint8))
    n, glab = cv2.connectedComponents(grouped, connectivity=8)
    lab = np.where(cand > 0, glab, 0).astype(np.int32)
    st = np.zeros((n, 5), np.int64)
    ys_all, xs_all = np.nonzero(lab)
    ids = lab[ys_all, xs_all]
    st[:, 0] = np.iinfo(np.int64).max
    st[:, 1] = np.iinfo(np.int64).max
    np.minimum.at(st[:, 0], ids, xs_all)
    np.minimum.at(st[:, 1], ids, ys_all)
    xmax = np.zeros(n, np.int64); ymax = np.zeros(n, np.int64)
    np.maximum.at(xmax, ids, xs_all)
    np.maximum.at(ymax, ids, ys_all)
    st[:, 2] = xmax - st[:, 0] + 1
    st[:, 3] = ymax - st[:, 1] + 1
    st[:, 4] = np.bincount(ids, minlength=n)
    band_bg = [np.median(data[b][sea][::211]) for b in range(8)]
    rows = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if not (min_area <= area <= max_area):
            continue
        ys, xs = np.nonzero(lab[y:y + h, x:x + w] == i)
        pts = np.stack([xs + x, ys + y], 1).astype(np.float32)
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(pts)
        length, width = max(rw, rh) + 1, min(rw, rh) + 1
        if length * res < 20 or length / width < 1.5 and area > 40:
            continue  # too small, or a big round blob (cloud/foam/platform)
        peak = float(resid[y:y + h, x:x + w][lab[y:y + h, x:x + w] == i].max() / sig)
        if peak < min_snr:
            continue  # weak: wakes, slicks, glint, turbid water
        pad = 8
        x0, y0 = max(x - pad, 0), max(y - pad, 0)
        x1, y1 = min(x + w + pad, nir.shape[1]), min(y + h + pad, nir.shape[0])
        cents = [band_centroid(data[b, y0:y1, x0:x1], band_bg[b]) for b in range(8)]
        e = np.nanmean([cents[b] for b in EARLY], 0)
        l = np.nanmean([cents[b] for b in LATE], 0)
        dx, dy = (l - e)  # pixels, image coords (y down)
        shift_m = float(np.hypot(dx, dy) * res)
        heading = float((np.degrees(np.arctan2(dx, -dy)) + 360) % 360)  # 0 = north
        ex, ey = tr * (cx + 0.5, cy + 0.5)
        lon, lat = warp_transform(crs, "EPSG:4326", [ex], [ey])
        # ship axis orientation (0-180, from north)
        if rw >= rh:
            axis = (ang + 90) % 180
        else:
            axis = ang % 180
        rows.append(dict(scene=scene, id=len(rows), px=round(cx, 1), py=round(cy, 1),
                         easting=round(ex, 1), northing=round(ey, 1),
                         lon=round(lon[0], 6), lat=round(lat[0], 6),
                         length_m=round(length * res, 1), width_m=round(width * res, 1),
                         axis_deg=round(float(axis), 1), peak_snr=round(peak, 1),
                         band_shift_m=round(shift_m, 2), motion_heading_deg=round(heading, 1)))

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, scene + "_ships.csv"), "w", newline="") as f:
        if rows:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
         "properties": r} for r in rows]}
    with open(os.path.join(out_dir, scene + "_ships.geojson"), "w") as f:
        json.dump(gj, f)
    save_quicklook(data, sea, rows, os.path.join(out_dir, scene + "_quicklook.jpg"))
    print(f"{scene}: {len(rows)} ships, sea px {sea.mean():.1%}, cloud px {cm.mean():.1%}")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--k", type=float, default=6.0)
    a = ap.parse_args()
    for p in sorted(glob.glob(os.path.join(a.input_dir, "*_AnalyticMS_8b.tif"))):
        try:
            detect(p, a.out_dir, k=a.k)
        except rasterio.errors.RasterioIOError as e:  # e.g. truncated download
            print(f"SKIP {os.path.basename(p)}: {e}")
