"""Step 4 of the YOLO-OBB workflow: run the trained detector over full scenes.

Sliding 640 px windows (overlap 160 px) -> oriented boxes in scene pixels -> merge
duplicates from overlapping windows -> per-ship attributes (size, axis, SuperDove
band-offset motion) -> CSV / GeoJSON in the same schema as detect_ships.py, so
link_tracks.py works on either.
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
from ultralytics import YOLO

from build_dataset import scene_image, tiles
from detect_ships import EARLY, LATE, NIR, band_centroid


def rotated_nms(dets, iou_thr=0.3):
    """dets: list of (conf, rect). Greedy NMS on rotated-rect IoU."""
    dets = sorted(dets, key=lambda d: -d[0])
    keep = []
    for conf, r in dets:
        ok = True
        for _, k in keep:
            inter, pts = cv2.rotatedRectangleIntersection(r, k)
            if inter == cv2.INTERSECT_NONE:
                continue
            ia = cv2.contourArea(cv2.convexHull(pts)) if pts is not None else 0
            u = r[1][0] * r[1][1] + k[1][0] * k[1][1] - ia
            if ia / max(u, 1e-6) > iou_thr or ia / max(min(r[1][0] * r[1][1], k[1][0] * k[1][1]), 1e-6) > 0.7:
                ok = False
                break
        if ok:
            keep.append((conf, r))
    return keep


def predict(model, path, out_dir, conf=0.25, size=640, stride=480, max_land_m=300.0):
    scene = os.path.basename(path)[:23]
    img, sea, valid = scene_image(path, coast_buffer_m=0.0)
    dets = []
    for x, y in tiles(img.shape[:2], size, stride):
        if not valid[y:y + size, x:x + size].any():
            continue
        res = model.predict(np.ascontiguousarray(img[y:y + size, x:x + size, ::-1]),
                            imgsz=size, conf=conf, verbose=False)[0]
        if res.obb is None:
            continue
        for (cx, cy, w, h, th), c in zip(res.obb.xywhr.cpu().numpy(), res.obb.conf.cpu().numpy()):
            gx, gy = cx + x, cy + y
            if not valid[int(gy), int(gx)]:
                continue
            dets.append((float(c), ((float(gx), float(gy)), (float(w), float(h)), float(np.degrees(th)))))
    dets = rotated_nms(dets)
    # drop detections inland: keep only those within max_land_m of open water
    # (ships moored at piers sit at the coarse water-mask edge, hence the tolerance)
    sc = 8
    wsmall = cv2.resize(sea.astype(np.uint8), (sea.shape[1] // sc, sea.shape[0] // sc),
                        interpolation=cv2.INTER_NEAREST)
    to_water = cv2.distanceTransform(1 - wsmall, cv2.DIST_L2, 5) * sc * 3.0
    dets = [d for d in dets
            if to_water[min(int(d[1][0][1] / sc), wsmall.shape[0] - 1),
                        min(int(d[1][0][0] / sc), wsmall.shape[1] - 1)] <= max_land_m]

    with rasterio.open(path) as src:
        data = src.read().astype(np.float32)
        tr, crs, r_m = src.transform, src.crs, src.res[0]
    band_bg = [np.median(data[b][sea][::211]) if sea.any() else 0 for b in range(8)]
    rows = []
    for c, rect in dets:
        (cx, cy), (w, h), ang = rect
        length, width = max(w, h), min(w, h)
        poly = cv2.boxPoints(rect)
        x0, y0 = np.floor(poly.min(0)).astype(int) - 8
        x1, y1 = np.ceil(poly.max(0)).astype(int) + 8
        x0, y0 = max(x0, 0), max(y0, 0)
        cents = [band_centroid(data[b, y0:y1, x0:x1], band_bg[b]) for b in range(8)]
        e = np.nanmean([cents[b] for b in EARLY], 0)
        l = np.nanmean([cents[b] for b in LATE], 0)
        dx, dy = l - e
        ex, ey = tr * (cx + 0.5, cy + 0.5)
        lon, lat = warp_transform(crs, "EPSG:4326", [ex], [ey])
        # long-side direction in image coords -> bearing from north (0-180)
        vx, vy = (poly[1] - poly[0]) if np.linalg.norm(poly[1] - poly[0]) >= np.linalg.norm(poly[2] - poly[1]) else (poly[2] - poly[1])
        axis = (np.degrees(np.arctan2(vx, -vy)) + 180) % 180
        geo_poly = [list(tr * (float(px) + 0.5, float(py) + 0.5)) for px, py in poly]
        plon, plat = warp_transform(crs, "EPSG:4326", [p[0] for p in geo_poly], [p[1] for p in geo_poly])
        rows.append(dict(scene=scene, id=len(rows), conf=round(c, 3), px=round(cx, 1), py=round(cy, 1),
                         easting=round(ex, 1), northing=round(ey, 1),
                         lon=round(lon[0], 6), lat=round(lat[0], 6),
                         length_m=round(length * r_m, 1), width_m=round(width * r_m, 1),
                         axis_deg=round(float(axis), 1),
                         band_shift_m=round(float(np.hypot(dx, dy) * r_m), 2),
                         motion_heading_deg=round(float((np.degrees(np.arctan2(dx, -dy)) + 360) % 360), 1),
                         poly_lonlat=json.dumps([[round(a, 6), round(b, 6)] for a, b in zip(plon, plat)])))

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, scene + "_ships.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["scene"])
        wr.writeheader()
        wr.writerows(rows)
    feats = []
    for r in rows:
        ring = json.loads(r["poly_lonlat"])
        props = {k: v for k, v in r.items() if k != "poly_lonlat"}
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]}})
    with open(os.path.join(out_dir, scene + "_ships.geojson"), "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)

    prev = cv2.resize(img[..., ::-1], None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    for r, (c, rect) in zip(rows, dets):
        cv2.polylines(prev, [(cv2.boxPoints(rect) / 4).astype(np.int32)], True, (0, 255, 255), 2)
        cv2.putText(prev, f"{c:.2f}", (int(r["px"] / 4) + 8, int(r["py"] / 4)), 0, 0.4, (0, 255, 255), 1)
    cv2.imwrite(os.path.join(out_dir, scene + "_quicklook.jpg"), prev, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(f"{scene}: {len(rows)} ships")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("weights")
    ap.add_argument("input_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--conf", type=float, default=0.25)
    a = ap.parse_args()
    m = YOLO(a.weights)
    for p in sorted(glob.glob(os.path.join(a.input_dir, "*_AnalyticMS_8b.tif"))):
        try:
            predict(m, p, a.out_dir, a.conf)
        except rasterio.errors.RasterioIOError as e:
            print(f"SKIP {os.path.basename(p)}: {e}")
