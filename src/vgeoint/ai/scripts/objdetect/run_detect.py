"""Tanks / armoured vehicles or aircraft / helicopters on satellite or UAV images, for vGeoInt's
"Phát hiện đối tượng" menu.

Uses the code of D:/detecttank/scripts (copied unchanged in this folder): common.build_detector() with
  - tanks:    DOTA YOLO11-OBB for aircraft + the trained tank model; tank boxes on aircraft are dropped
              (the combination of predict.py --tank-weights), only armored_vehicle is kept;
  - aircraft: the DOTA model alone (plane -> aircraft, helicopter -> helicopter).
Large images are tiled and merged with rotated NMS (common.predict). Added here: GeoTIFFs are read
with rasterio (any band count / data type), and boxes of georeferenced images are written as
polygons in the image CRS (detections.geojson + shapefile/detections.shp) besides predict.py's
annotated images and detections.csv.
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # common.py

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from common import CLASSES, build_detector, draw  # noqa: E402

try:
    from vgeoint.ai.scripts._events import progress, result
except ImportError:  # stand-alone run outside the app
    def progress(*a, **k):
        pass

    def result(**k):
        pass

try:
    from vgeoint.ai.scripts._device import resolve_device
except ImportError:
    def resolve_device(requested="auto", log=print):
        import torch
        return "cuda:0" if requested != "cpu" and torch.cuda.is_available() else "cpu"

EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
TARGETS = {"tank": {0}, "aircraft": {1, 2}}  # class ids of common.CLASSES
VN_NAMES = {"armored_vehicle": "Xe tăng/xe bọc thép", "aircraft": "Máy bay", "helicopter": "Trực thăng"}


def log(message):
    print(message, flush=True)


def read_image(path):
    """BGR uint8 image + (affine transform, CRS WKT) when the file is georeferenced."""
    try:
        import warnings

        import rasterio

        with warnings.catch_warnings(), rasterio.open(path) as src:
            warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
            georef = None
            if src.crs is not None and not src.transform.is_identity:
                georef = (src.transform, src.crs.to_wkt())
            bands = [1, 2, 3] if src.count >= 3 else [1, 1, 1]
            arr = np.transpose(src.read(bands), (1, 2, 0))
    except Exception:
        img = cv2.imread(str(path))
        if img is None:
            raise RuntimeError(f"Không đọc được ảnh: {path}")
        return img, None
    if arr.dtype != np.uint8:  # 16-bit / float: stretch 1-99 %
        arr = arr.astype(np.float32)
        lo, hi = np.percentile(arr, 1), np.percentile(arr, 99)
        arr = np.clip((arr - lo) / max(hi - lo, 1e-6) * 255, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(arr[..., ::-1]), georef  # RGB -> BGR like cv2.imread


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True, help="image or folder of images")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--target", choices=sorted(TARGETS), required=True)
    ap.add_argument("--dota-weights", required=True, help="DOTA YOLO11-OBB (yolo11s-obb.pt)")
    ap.add_argument("--tank-weights", help="trained tank model (target tank)")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--tile", type=int, default=1024, help="tile size for large images (px)")
    ap.add_argument("--imgsz", type=int, default=1024)
    ap.add_argument("--tank-imgsz", type=int, default=1600)
    ap.add_argument("--device", default="auto")
    args = ap.parse_args()
    t0 = time.time()

    src = Path(args.source)
    files = sorted(p for p in (src.iterdir() if src.is_dir() else [src]) if p.suffix.lower() in EXTS)
    if not files:
        log(f"[ERROR] Không có ảnh ({', '.join(sorted(EXTS))}) trong {src}")
        return 1
    if args.target == "tank" and not (args.tank_weights and os.path.isfile(args.tank_weights)):
        log(f"[ERROR] Không tìm thấy model xe tăng: {args.tank_weights}")
        return 1
    log(f"Tìm thấy {len(files)} ảnh")
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    device = resolve_device(args.device, log)
    # common.build_detector() reads these options (predict.py's command line)
    options = SimpleNamespace(weights=args.dota_weights, dota=args.target == "aircraft",
                              tank_weights=args.tank_weights if args.target == "tank" else None,
                              imgsz=args.imgsz, tank_imgsz=args.tank_imgsz, tank_box_scale=1.0)
    from ultralytics import YOLO

    original_init = YOLO.__init__

    def init_on_device(self, *a, **k):  # common.predict() calls model.predict() without device
        original_init(self, *a, **k)
        self.overrides["device"] = device

    YOLO.__init__ = init_on_device
    detect = build_detector(options)
    keep = TARGETS[args.target]
    log(f"[OK] Mô hình: {Path(args.dota_weights).name}"
        + (f" + {Path(args.tank_weights).name}" if options.tank_weights else ""))

    features, total = [], {CLASSES[k]: 0 for k in sorted(keep)}
    with open(out / "detections.csv", "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["image", "class", "conf", "cx", "cy", "w", "h", "angle_rad",
                     "x1", "y1", "x2", "y2", "x3", "y3", "x4", "y4", "map_x", "map_y"])
        for i, p in enumerate(files, 1):
            progress(100 * (i - 1) / len(files), f"Ảnh {i}/{len(files)}")
            try:
                img, georef = read_image(p)
            except Exception as e:
                log(f"[WARN] Bỏ qua {p.name}: {e}")
                continue
            dets = [d for d in detect(img, args.conf, args.tile) if d[0] in keep]
            for c, conf, poly, xywhr in dets:
                map_x = map_y = ""
                if georef is not None:
                    tr = georef[0]
                    ring = [list(tr * (float(x), float(y))) for x, y in poly]
                    map_x, map_y = tr * (float(xywhr[0]), float(xywhr[1]))
                    features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]},
                                     "properties": {"image": p.name, "class": CLASSES[c], "loai": VN_NAMES[CLASSES[c]],
                                                    "conf": round(conf, 3), "crs": georef[1]}})
                wr.writerow([p.name, CLASSES[c], f"{conf:.3f}", *[f"{v:.1f}" for v in xywhr[:4]],
                             f"{xywhr[4]:.4f}", *[f"{v:.1f}" for v in poly.flatten()], map_x, map_y])
                total[CLASSES[c]] += 1
            cv2.imwrite(str(out / f"{p.stem}_det.jpg"), draw(img, dets))
            counts = {VN_NAMES[CLASSES[k]]: sum(1 for d in dets if d[0] == k) for k in sorted(keep)}
            log(f"Ảnh {i}/{len(files)} {p.name}: " + ", ".join(f"{v} {k.lower()}" for k, v in counts.items())
                + ("" if georef else " (ảnh không có toạ độ)"))

    if features:
        write_vectors(features, out)
    progress(100, "Xong")
    log("Tổng: " + ", ".join(f"{v} {VN_NAMES[k].lower()}" for k, v in total.items()))
    log(f"[OK] Xong trong {time.time() - t0:.1f} s")
    result(output_dir=str(out.resolve()), counts=total, georeferenced=len(features))
    return 0


def write_vectors(features, out: Path):
    """Polygons of the georeferenced images: GeoJSON + shapefile, in the CRS of the (first) image."""
    import geopandas as gpd
    from shapely.geometry import shape

    crs = features[0]["properties"]["crs"]
    rows = [{k: v for k, v in f["properties"].items() if k != "crs"} | {"geometry": shape(f["geometry"])}
            for f in features if f["properties"]["crs"] == crs]
    if len(rows) < len(features):
        log(f"[WARN] {len(features) - len(rows)} đối tượng ở ảnh khác hệ toạ độ không được xuất shapefile")
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    gdf.to_file(out / "detections.geojson", driver="GeoJSON")
    (out / "shapefile").mkdir(exist_ok=True)
    gdf.to_file(out / "shapefile" / "detections.shp", encoding="utf-8")
    log(f"[OK] {len(rows)} đối tượng có toạ độ -> shapefile/detections.shp")


if __name__ == "__main__":
    sys.exit(main())
