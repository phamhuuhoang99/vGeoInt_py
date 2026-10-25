"""Ship detection + tracks from multi-date PlanetScope SuperDove scenes, for vGeoInt's
"Phát hiện quỹ đạo bằng ảnh vệ tinh" dialog.

Runs the steps of BAO_CAO_GIAI_PHAP.md (the scripts of this folder, copied unchanged from
D:/detectship/shiptrack) one after the other:

  1. detection per scene: predict_scene.py (YOLO-OBB, trained weights) or detect_ships.py (CFAR rules)
     -> <out>/<scene>_ships.csv / .geojson / _quicklook.jpg
  2. link_tracks.py      -> all_detections_tracked.csv, tracks.geojson
  3. export_shapefile.py -> shapefile/ships_points.shp, ships_boxes.shp, tracks_lines.shp
  4. plot_tracks.py      -> tracks_overview.png

Training (make_labels.py, build_dataset.py, train_obb.py, review_predictions.py) stays a
command-line workflow, see BAO_CAO_GIAI_PHAP.md.
"""

import argparse
import glob
import os
import runpy
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # the scripts import each other by module name

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

PATTERN = "*_AnalyticMS_8b.tif"  # PlanetScope SuperDove 3B AnalyticMS 8-band scenes


def log(message):
    print(message, flush=True)


def run_script(name, *args):
    """Run one of the copied scripts as `python <name> args...` in this process."""
    saved = sys.argv
    sys.argv = [os.path.join(HERE, name), *map(str, args)]
    try:
        runpy.run_path(sys.argv[0], run_name="__main__")
    finally:
        sys.argv = saved


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input-dir", required=True, help="folder with *_AnalyticMS_8b.tif scenes")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--method", choices=["yolo", "cfar"], default="yolo")
    ap.add_argument("--weights", help="YOLO-OBB weights (method yolo)")
    ap.add_argument("--conf", type=float, default=0.25, help="YOLO confidence threshold")
    ap.add_argument("--k", type=float, default=6.0, help="CFAR threshold (sigma)")
    ap.add_argument("--gate-m", type=float, default=800.0, help="max distance between dates (m)")
    ap.add_argument("--moving-m", type=float, default=15.0, help="band shift above which a ship is 'moving' (m)")
    ap.add_argument("--device", default="auto")
    args = ap.parse_args()
    t0 = time.time()

    scenes = sorted(glob.glob(os.path.join(args.input_dir, PATTERN)))
    if not scenes:
        log(f"[ERROR] Không có ảnh PlanetScope 8 băng ({PATTERN}) trong {args.input_dir}")
        return 1
    log(f"Tìm thấy {len(scenes)} cảnh:")
    for p in scenes:
        log(f"  {os.path.basename(p)}")
    os.makedirs(args.output_dir, exist_ok=True)

    # 1. Detection
    import rasterio

    if args.method == "yolo":
        if not args.weights or not os.path.isfile(args.weights):
            log(f"[ERROR] Không tìm thấy trọng số YOLO-OBB: {args.weights}")
            return 1
        from predict_scene import predict
        from ultralytics import YOLO

        device = resolve_device(args.device, log)
        model = YOLO(args.weights)
        model.overrides["device"] = device  # predict_scene.predict() calls model.predict() without device
        log(f"[OK] Mô hình YOLO-OBB: {args.weights}")
        detect_one = lambda p: predict(model, p, args.output_dir, args.conf)  # noqa: E731
    else:
        from detect_ships import detect

        log("[OK] Phát hiện theo luật (CFAR), không dùng mô hình")
        detect_one = lambda p: detect(p, args.output_dir, k=args.k)  # noqa: E731

    n_ok = 0
    for i, p in enumerate(scenes, 1):
        progress(100 * (i - 1) / (len(scenes) + 1), f"Cảnh {i}/{len(scenes)}")
        log(f"Cảnh {i}/{len(scenes)}: {os.path.basename(p)} ...")
        try:
            rows = detect_one(p)
            n_ok += 1
            log(f"  -> {len(rows)} tàu")
        except rasterio.errors.RasterioIOError as e:  # e.g. truncated download
            log(f"[WARN] Bỏ qua {os.path.basename(p)}: {e}")
    if not n_ok:
        log("[ERROR] Không đọc được cảnh nào")
        return 1

    # 2-4. Tracks, shapefiles, overview map (the scripts' own command lines)
    progress(100 * len(scenes) / (len(scenes) + 1), "Ghép quỹ đạo")
    log("Ghép tàu giữa các ngày (link_tracks.py)...")
    run_script("link_tracks.py", args.output_dir, "--gate_m", args.gate_m)
    log("Xuất shapefile (export_shapefile.py)...")
    run_script("export_shapefile.py", args.output_dir, "--moving_m", args.moving_m)
    log("Vẽ bản đồ tổng quan (plot_tracks.py)...")
    try:
        run_script("plot_tracks.py", args.output_dir)
    except Exception as e:  # e.g. no ship seen on two dates: nothing to zoom on
        log(f"[WARN] Không vẽ được tracks_overview.png: {e}")

    progress(100, "Xong")
    log(f"[OK] Xong trong {time.time() - t0:.1f} s")
    result(output_dir=os.path.abspath(args.output_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
