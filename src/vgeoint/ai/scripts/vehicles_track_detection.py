# -*- coding: utf-8 -*-
"""
Vehicle Detection & Trajectory Tracking Pipeline for vGeoInt_v2
Detects vehicles in multi-temporal aerial/UAV images/GeoTIFFs and tracks trajectories.
Calculates segment speeds, movement directions (headings/azimuths), trajectory durations, and overall average metrics.
Enhanced with detailed logging for real-time progress tracking in vGeoInt GUI.
"""

import argparse
import sys
import os
import re
import math
import warnings
import time
from datetime import datetime
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        import codecs

        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, errors="replace")
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, errors="replace")

warnings.filterwarnings("ignore")

# Machine-readable events for vGeoInt (see vgeoint.ai.runner); no-ops when run stand-alone.
try:
    from vgeoint.ai.scripts._events import result
except ImportError:

    def result(**data):
        pass


def log_progress(message, flush=True):
    """Print progress message with safe encoding handling"""
    try:
        safe_message = (
            message.replace("✓", "[OK]")
            .replace("❌", "[ERROR]")
            .replace("⚠️", "[WARN]")
        )
        print(safe_message, flush=flush)
    except UnicodeEncodeError:
        ascii_message = message.encode("ascii", errors="replace").decode("ascii")
        print(ascii_message, flush=flush)


def log_error(message, flush=True):
    """Print error message with safe encoding handling"""
    try:
        safe_message = (
            message.replace("✓", "[OK]")
            .replace("❌", "[ERROR]")
            .replace("⚠️", "[WARN]")
        )
        print(safe_message, file=sys.stderr, flush=flush)
    except UnicodeEncodeError:
        ascii_message = message.encode("ascii", errors="replace").decode("ascii")
        print(ascii_message, file=sys.stderr, flush=flush)


# Check dependencies
DEPENDENCIES_AVAILABLE = True
missing_deps = []

try:
    import numpy as np
    import cv2
    import rasterio
    from shapely.geometry import Point, LineString
    import geopandas as gpd
    from pyproj import Geod
    from scipy.optimize import linear_sum_assignment

    log_progress("[OK] Core spatial libraries loaded successfully")
except ImportError as e:
    missing_deps.append(f"spatial/geo libraries ({e})")
    log_error(f"Missing core dependency: {e}")

SAHI_AVAILABLE = False
try:
    # Disable numba backend in SAHI to avoid Windows numba initialization crash
    try:
        import sahi.postprocess.backends as sahi_backends

        sahi_backends._backend = "numpy"
        sahi_backends._resolved_cache = "numpy"
    except Exception:
        pass

    from sahi import AutoDetectionModel
    from sahi.predict import get_sliced_prediction

    SAHI_AVAILABLE = True
    log_progress("[OK] SAHI inference framework loaded successfully")
except ImportError as e:
    log_progress(
        f"[WARN] SAHI not available ({e}), will fallback to Ultralytics YOLO if needed"
    )

YOLO_AVAILABLE = False
try:
    from ultralytics import YOLO

    YOLO_AVAILABLE = True
    log_progress("[OK] Ultralytics YOLO loaded successfully")
except ImportError as e:
    missing_deps.append("ultralytics")
    log_error(f"Missing Ultralytics YOLO: {e}")

if missing_deps:
    DEPENDENCIES_AVAILABLE = False
    log_error(f"Missing dependencies: {', '.join(missing_deps)}")


def parse_timestamp_from_filename(filename):
    """
    Trích xuất ngày giờ và mili-giây từ tên file/thư mục.
    Định dạng mục tiêu chính: 20260328_162146_477_DJI_0260_V.JPG
    - YYYYMMDD_HHMMSS_mmm
    Định dạng nhãn đầu ra yêu cầu: 16:21:46.477 28/03/2026
    """
    stem = Path(filename).stem

    # 1. Khớp dạng YYYYMMDD_HHMMSS_mmm (ví dụ: 20260328_162146_477)
    match1 = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(\d{3})", stem)
    if match1:
        y, m, d = int(match1.group(1)), int(match1.group(2)), int(match1.group(3))
        h, mi, s = int(match1.group(4)), int(match1.group(5)), int(match1.group(6))
        ms = int(match1.group(7))
        dt = datetime(y, m, d, h, mi, s, ms * 1000)
        label = f"{h:02d}:{mi:02d}:{s:02d}.{ms:03d} {d:02d}/{m:02d}/{y:04d}"
        return dt, label

    # 2. Khớp dạng YYYYMMDD_HHMMSS (không có ms)
    match2 = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", stem)
    if match2:
        y, m, d = int(match2.group(1)), int(match2.group(2)), int(match2.group(3))
        h, mi, s = int(match2.group(4)), int(match2.group(5)), int(match2.group(6))
        dt = datetime(y, m, d, h, mi, s, 0)
        label = f"{h:02d}:{mi:02d}:{s:02d}.000 {d:02d}/{m:02d}/{y:04d}"
        return dt, label

    # 3. Khớp dạng DJI_YYYYMMDDHHMMSS_
    match3 = re.search(r"DJI_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_", stem)
    if match3:
        y, m, d = int(match3.group(1)), int(match3.group(2)), int(match3.group(3))
        h, mi, s = int(match3.group(4)), int(match3.group(5)), int(match3.group(6))
        dt = datetime(y, m, d, h, mi, s, 0)
        label = f"{h:02d}:{mi:02d}:{s:02d}.000 {d:02d}/{m:02d}/{y:04d}"
        return dt, label

    # 4. Fallback: ngày tháng dạng dd-mm-yyyy hoặc yyyy-mm-dd
    match4 = re.search(r"(\d{1,2})[-_.](\d{1,2})[-_.](\d{4})", stem)
    if match4:
        d, m, y = int(match4.group(1)), int(match4.group(2)), int(match4.group(3))
        dt = datetime(y, m, d, 0, 0, 0, 0)
        label = f"00:00:00.000 {d:02d}/{m:02d}/{y:04d}"
        return dt, label

    # Fallback theo thời gian file
    if os.path.exists(filename):
        mtime = os.path.getmtime(filename)
        dt = datetime.fromtimestamp(mtime)
        ms = int(dt.microsecond / 1000)
        label = f"{dt.strftime('%H:%M:%S')}.{ms:03d} {dt.strftime('%d/%m/%Y')}"
        return dt, label

    dt = datetime(1970, 1, 1, 0, 0, 0, 0)
    return dt, "00:00:00.000 01/01/1970"


def scan_input_directory(input_dir):
    """Quét và tìm tất cả các file ảnh/GeoTIFF trong thư mục"""
    valid_exts = {".tif", ".tiff", ".jpg", ".jpeg", ".png"}
    found_items = []

    if not os.path.exists(input_dir):
        log_error(f"Input directory does not exist: {input_dir}")
        return []

    entries = sorted(os.listdir(input_dir))
    for entry in entries:
        full_path = os.path.join(input_dir, entry)
        if os.path.isfile(full_path):
            ext = os.path.splitext(entry)[1].lower()
            if ext in valid_exts:
                dt, label = parse_timestamp_from_filename(entry)
                found_items.append((dt, label, full_path))
        elif os.path.isdir(full_path):
            sub_files = [
                f
                for f in os.listdir(full_path)
                if os.path.splitext(f)[1].lower() in valid_exts
            ]
            if sub_files:
                target_file = os.path.join(full_path, sub_files[0])
                dt, label = parse_timestamp_from_filename(entry)
                found_items.append((dt, label, target_file))

    found_items.sort(key=lambda x: x[0])
    log_progress(f"Tìm thấy {len(found_items)} tệp ảnh/GeoTIFF hợp lệ trong thư mục:")
    for dt, label, path in found_items:
        log_progress(f"  - [{label}] -> {os.path.basename(path)}")

    return found_items


def calculate_real_distance(p1, p2, crs):
    """Tính khoảng cách thực tế (mét) trên hệ tọa độ không gian hoặc mặt cầu"""
    x1, y1 = p1[0], p1[1]
    x2, y2 = p2[0], p2[1]
    if crs and hasattr(crs, "is_projected") and crs.is_projected:
        return math.hypot(x2 - x1, y2 - y1)
    else:
        try:
            geod = Geod(ellps="WGS84")
            _, _, distance_m = geod.inv(x1, y1, x2, y2)
            return distance_m
        except Exception:
            return math.hypot(x2 - x1, y2 - y1)


def calculate_heading(p1, p2, crs):
    """
    Tính góc phương vị hướng di chuyển (Azimuth/Bearing) từ p1 đến p2 theo độ (0° - 360°).
    0° = Bắc (North), 90° = Đông (East), 180° = Nam (South), 270° = Tây (West).
    """
    x1, y1 = p1[0], p1[1]
    x2, y2 = p2[0], p2[1]

    if not (crs and hasattr(crs, "is_projected") and crs.is_projected):
        try:
            geod = Geod(ellps="WGS84")
            fwd_az, _, _ = geod.inv(x1, y1, x2, y2)
            return (fwd_az + 360.0) % 360.0
        except Exception:
            pass

    dx = x2 - x1
    dy = y2 - y1
    rad = math.atan2(dx, dy)
    return (math.degrees(rad) + 360.0) % 360.0


def heading_to_compass_name(deg):
    """Chuyển đổi góc phương vị (độ) thành tên 16 hướng la bàn tiếng Việt và ký hiệu quốc tế"""
    directions = [
        ("Bắc", "N"),
        ("Bắc - Đông Bắc", "NNE"),
        ("Đông Bắc", "NE"),
        ("Đông - Đông Bắc", "ENE"),
        ("Đông", "E"),
        ("Đông - Đông Nam", "ESE"),
        ("Đông Nam", "SE"),
        ("Nam - Đông Nam", "SSE"),
        ("Nam", "S"),
        ("Nam - Tây Nam", "SSW"),
        ("Tây Nam", "SW"),
        ("Tây - Tây Nam", "WSW"),
        ("Tây", "W"),
        ("Tây - Tây Bắc", "WNW"),
        ("Tây Bắc", "NW"),
        ("Bắc - Tây Bắc", "NNW"),
    ]
    idx = int(round((deg % 360.0) / 22.5)) % 16
    return directions[idx][0], directions[idx][1]


def run_detection(
    model_obj,
    is_sahi,
    img_path,
    target_classes,
    conf_thresh,
    slice_size,
    overlap,
    device,
):
    """
    Chạy phát hiện đối tượng trên 1 ảnh (bằng SAHI hoặc Ultralytics trực tiếp).
    """
    detected_boxes = []

    if is_sahi:
        # Đảm bảo SAHI sử dụng numpy backend (tránh numba issue)
        try:
            import sahi.postprocess.backends as sahi_backends

            sahi_backends._backend = "numpy"
            sahi_backends._resolved_cache = "numpy"
        except Exception:
            pass

        result = get_sliced_prediction(
            img_path,
            model_obj,
            slice_height=slice_size,
            slice_width=slice_size,
            overlap_height_ratio=overlap,
            overlap_width_ratio=overlap,
            postprocess_type="NMS",
            verbose=0,
        )
        for obj in result.object_prediction_list:
            cname = obj.category.name.lower()
            if cname not in target_classes:
                continue
            bbox = obj.bbox.to_xyxy()
            cx_px = (bbox[0] + bbox[2]) / 2.0
            cy_px = (bbox[1] + bbox[3]) / 2.0
            score = float(obj.score.value)
            norm_class = "motorcycle" if cname in ["person", "bicycle"] else cname
            detected_boxes.append((cx_px, cy_px, norm_class, score))
    else:
        results = model_obj(img_path, conf=conf_thresh, device=device, verbose=False)
        for res in results:
            if res.boxes is not None:
                for b in res.boxes:
                    cls_id = int(b.cls[0].cpu().numpy())
                    cname = model_obj.names.get(cls_id, "").lower()
                    if cname not in target_classes:
                        continue
                    coords = b.xyxy[0].cpu().numpy()
                    cx_px = (coords[0] + coords[2]) / 2.0
                    cy_px = (coords[1] + coords[3]) / 2.0
                    score = float(b.conf[0].cpu().numpy())
                    norm_class = (
                        "motorcycle" if cname in ["person", "bicycle"] else cname
                    )
                    detected_boxes.append((cx_px, cy_px, norm_class, score))

    return detected_boxes


def main():
    parser = argparse.ArgumentParser(
        description="Vehicle Detection & Tracking for Aerial/UAV Images"
    )
    parser.add_argument(
        "--input-dir",
        "--input",
        required=True,
        help="Path to folder containing multi-temporal aerial images",
    )
    parser.add_argument(
        "--model",
        default="yolov8x.pt",
        help="Path to YOLO weights (.pt) or standard model name",
    )
    parser.add_argument(
        "--output-dir",
        "--output",
        required=True,
        help="Path to directory for saving output shapefiles and geojsons",
    )
    parser.add_argument(
        "--confidence",
        "--conf",
        type=float,
        default=0.10,
        help="Confidence threshold (default: 0.10)",
    )
    parser.add_argument(
        "--max-distance",
        "--max-dist",
        type=float,
        default=50.0,
        dest="max_distance",
        help="Max distance step (m)",
    )
    parser.add_argument(
        "--max-speed",
        type=float,
        default=90.0,
        help="Max speed constraint in km/h (default: 90.0)",
    )
    parser.add_argument(
        "--tile-size",
        "--slice-size",
        type=int,
        default=512,
        dest="slice_size",
        help="Tile / Slice size (default: 512)",
    )
    parser.add_argument(
        "--overlap", type=float, default=0.20, help="Overlap ratio (default: 0.20)"
    )
    parser.add_argument(
        "--device", default="auto", help="Computing device: auto, cuda, or cpu"
    )

    args = parser.parse_args()

    log_progress("=== vGeoInt_v2 Vehicle Tracking Started ===")
    log_progress(f"Input Directory: {args.input_dir}")
    log_progress(f"Model: {args.model}")
    log_progress(f"Output Directory: {args.output_dir}")
    log_progress(f"Confidence Threshold: {args.confidence}")
    log_progress(f"Max Speed Constraint: {args.max_speed} km/h")

    if not DEPENDENCIES_AVAILABLE:
        log_error("Missing essential dependencies. Exiting.")
        sys.exit(1)

    if not os.path.exists(args.input_dir):
        log_error(f"Input directory does not exist: {args.input_dir}")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    # Chọn thiết bị tính toán
    if args.device == "auto":
        import torch

        device_str = "cuda:0" if torch.cuda.is_available() else "cpu"
    else:
        device_str = args.device
    log_progress(f"[OK] Compute device: {device_str}")

    # 1. Quét file và sắp xếp theo mốc thời gian
    items = scan_input_directory(args.input_dir)
    if len(items) < 2:
        log_error(
            f"Cần ít nhất 2 tệp ảnh hợp lệ để theo dõi quỹ đạo! Tìm thấy: {len(items)}"
        )
        sys.exit(1)

    # 2. Khởi tạo mô hình
    target_classes = {"motorcycle", "person", "bicycle", "car", "truck", "bus", "van"}
    model_obj = None
    is_sahi = False

    log_progress(f"Loading detection model: {args.model}...")
    if SAHI_AVAILABLE:
        try:
            # Đảm bảo SAHI sử dụng numpy backend
            try:
                import sahi.postprocess.backends as sahi_backends

                sahi_backends._backend = "numpy"
                sahi_backends._resolved_cache = "numpy"
            except Exception:
                pass

            model_obj = AutoDetectionModel.from_pretrained(
                model_type="yolov8",
                model_path=args.model,
                confidence_threshold=args.confidence,
                device=device_str,
            )
            is_sahi = True
            log_progress("[OK] SAHI AutoDetectionModel initialized successfully")
        except Exception as e:
            log_progress(
                f"[WARN] Failed initializing SAHI model: {e}. Falling back to Ultralytics YOLO directly..."
            )

    if model_obj is None and YOLO_AVAILABLE:
        model_obj = YOLO(args.model)
        is_sahi = False
        log_progress("[OK] Ultralytics YOLO initialized successfully")

    if model_obj is None:
        log_error("Could not initialize any detection model!")
        sys.exit(1)

    # 3. Phát hiện đối tượng trên từng Frame
    start_time = time.time()
    all_detections = []
    native_crs = None
    max_speed_ms = args.max_speed / 3.6

    for frame_idx, (dt, label, file_path) in enumerate(items, start=1):
        filename = os.path.basename(file_path)
        transform = None

        try:
            with rasterio.open(file_path) as src:
                transform = src.transform
                if native_crs is None and src.crs is not None:
                    native_crs = src.crs
        except Exception:
            transform = None

        log_progress(f"Frame {frame_idx}/{len(items)}: {filename} [{label}]...")

        boxes = run_detection(
            model_obj,
            is_sahi,
            file_path,
            target_classes,
            args.confidence,
            args.slice_size,
            args.overlap,
            device_str,
        )

        for cx_px, cy_px, norm_class, score in boxes:
            if transform is not None:
                geo_x, geo_y = rasterio.transform.xy(
                    transform, cy_px, cx_px, offset="center"
                )
            else:
                geo_x, geo_y = float(cx_px), float(-cy_px)

            point = Point(float(geo_x), float(geo_y))
            detection = {
                "frame": frame_idx,
                "timestamp": dt,
                "label": label,
                "time_mark": label,
                "file_name": filename,
                "class": norm_class,
                "score": round(score, 3),
                "geo_x": float(geo_x),
                "geo_y": float(geo_y),
                "geometry": point,
                "track_id": None,
                "seg_dist_m": 0.0,
                "seg_dt_s": 0.0,
                "seg_spd_k": 0.0,
                "seg_spd_ms": 0.0,
                "heading_deg": 0.0,
                "direction": "",
                "dir_code": "",
            }
            all_detections.append(detection)

        log_progress(f"  -> Phát hiện {len(boxes)} đối tượng.")

    if native_crs is None:
        native_crs = "EPSG:4326"

    log_progress(f"[OK] Tổng cộng phát hiện: {len(all_detections)} điểm đối tượng.")
    if len(all_detections) == 0:
        log_error(
            "Không phát hiện được đối tượng nào. Vui lòng kiểm tra lại ảnh và ngưỡng tin cậy!"
        )
        sys.exit(1)

    # 4. Phân nhóm & So khớp Track (Hungarian Matching)
    log_progress("Đang ghép nối quỹ đạo di chuyển (Hungarian matching)...")
    frame_groups = {}
    for d in all_detections:
        frame_groups.setdefault(d["frame"], []).append(d)

    tracks = {}
    next_track_id = 1

    first_frame = min(frame_groups.keys())
    for det in frame_groups[first_frame]:
        det["track_id"] = next_track_id
        tracks[next_track_id] = [det]
        next_track_id += 1

    sorted_frames = sorted(frame_groups.keys())

    for current_frame in sorted_frames:
        if current_frame == first_frame:
            continue

        detections = frame_groups[current_frame]
        active_track_ids = [
            tid for tid, pts in tracks.items() if pts[-1]["frame"] < current_frame
        ]

        if not active_track_ids:
            for det in detections:
                det["track_id"] = next_track_id
                tracks[next_track_id] = [det]
                next_track_id += 1
            continue

        BIG_COST = 1e6
        cost_matrix = np.full((len(active_track_ids), len(detections)), BIG_COST)
        match_info = {}

        for i, tid in enumerate(active_track_ids):
            last_det = tracks[tid][-1]
            for j, cur_det in enumerate(detections):
                dt = (cur_det["timestamp"] - last_det["timestamp"]).total_seconds()
                if dt <= 0:
                    continue

                dist_m = calculate_real_distance(
                    (last_det["geo_x"], last_det["geo_y"]),
                    (cur_det["geo_x"], cur_det["geo_y"]),
                    native_crs,
                )

                max_dist = max(5.0, max_speed_ms * dt * 1.35)
                if dist_m <= max_dist:
                    cost_matrix[i, j] = dist_m
                    match_info[(i, j)] = (dist_m, dt)

        row_ind, col_ind = linear_sum_assignment(cost_matrix)
        matched_dets = set()

        for r, c in zip(row_ind, col_ind):
            if cost_matrix[r, c] < BIG_COST:
                dist_m, dt = match_info[(r, c)]
                speed_ms = (dist_m / dt) if dt > 0 else 0.0
                speed_kmh = speed_ms * 3.6

                det = detections[c]
                tid = active_track_ids[r]
                last_det = tracks[tid][-1]

                # Tính hướng di chuyển của đoạn
                heading_deg = calculate_heading(
                    (last_det["geo_x"], last_det["geo_y"]),
                    (det["geo_x"], det["geo_y"]),
                    native_crs,
                )
                dir_vn, dir_code = heading_to_compass_name(heading_deg)

                det["track_id"] = tid
                det["seg_dist_m"] = round(dist_m, 2)
                det["seg_dt_s"] = round(dt, 3)
                det["seg_spd_k"] = round(speed_kmh, 2)
                det["seg_spd_ms"] = round(speed_ms, 2)
                det["heading_deg"] = round(heading_deg, 1)
                det["direction"] = dir_vn
                det["dir_code"] = dir_code

                tracks[tid].append(det)
                matched_dets.add(c)

        for c, det in enumerate(detections):
            if c not in matched_dets:
                det["track_id"] = next_track_id
                tracks[next_track_id] = [det]
                next_track_id += 1

    # 5. Xây dựng dữ liệu từng đoạn (Segments) và toàn tuyến (Tracks)
    trajectory_rows = []
    segment_rows = []
    all_segment_speeds_kmh = []
    all_segment_headings = []

    for tid, pts in tracks.items():
        if len(pts) >= 2:
            pts_sorted = sorted(pts, key=lambda d: d["timestamp"])
            line = LineString([p["geometry"] for p in pts_sorted])

            seg_speeds = []
            seg_headings = []
            for s_idx in range(len(pts_sorted) - 1):
                p1 = pts_sorted[s_idx]
                p2 = pts_sorted[s_idx + 1]
                s_dist = calculate_real_distance(
                    (p1["geo_x"], p1["geo_y"]), (p2["geo_x"], p2["geo_y"]), native_crs
                )
                s_dt = (p2["timestamp"] - p1["timestamp"]).total_seconds()
                s_spd_ms = (s_dist / s_dt) if s_dt > 0 else 0.0
                s_spd_kmh = s_spd_ms * 3.6

                s_heading = calculate_heading(
                    (p1["geo_x"], p1["geo_y"]), (p2["geo_x"], p2["geo_y"]), native_crs
                )
                s_dir_vn, s_dir_code = heading_to_compass_name(s_heading)

                seg_speeds.append(s_spd_kmh)
                seg_headings.append(s_heading)
                all_segment_speeds_kmh.append(s_spd_kmh)
                all_segment_headings.append(s_heading)

                seg_line = LineString([p1["geometry"], p2["geometry"]])
                segment_rows.append(
                    {
                        "track_id": tid,
                        "seg_idx": s_idx + 1,
                        "start_time": p1["label"],
                        "end_time": p2["label"],
                        "dist_m": round(s_dist, 2),
                        "dt_s": round(s_dt, 3),
                        "speed_kmh": round(s_spd_kmh, 2),
                        "speed_ms": round(s_spd_ms, 2),
                        "heading_deg": round(s_heading, 1),
                        "direction": s_dir_vn,
                        "dir_code": s_dir_code,
                        "heading": f"{s_heading:.1f}° ({s_dir_code})",
                        "geometry": seg_line,
                    }
                )

            total_dist = sum(p["seg_dist_m"] for p in pts_sorted[1:])
            duration = (
                pts_sorted[-1]["timestamp"] - pts_sorted[0]["timestamp"]
            ).total_seconds()
            avg_speed = np.mean(seg_speeds) if seg_speeds else 0.0
            max_speed = max(seg_speeds) if seg_speeds else 0.0
            min_speed = min(seg_speeds) if seg_speeds else 0.0

            overall_heading = calculate_heading(
                (pts_sorted[0]["geo_x"], pts_sorted[0]["geo_y"]),
                (pts_sorted[-1]["geo_x"], pts_sorted[-1]["geo_y"]),
                native_crs,
            )
            t_dir_vn, t_dir_code = heading_to_compass_name(overall_heading)

            trajectory_rows.append(
                {
                    "track_id": tid,
                    "class": pts_sorted[0]["class"],
                    "num_pts": len(pts_sorted),
                    "start_time": pts_sorted[0]["label"],
                    "end_time": pts_sorted[-1]["label"],
                    "duration_s": round(duration, 3),
                    "tot_dist_m": round(total_dist, 2),
                    "avg_spd_k": round(avg_speed, 2),
                    "max_spd_k": round(max_speed, 2),
                    "min_spd_k": round(min_speed, 2),
                    "heading_deg": round(overall_heading, 1),
                    "direction": t_dir_vn,
                    "dir_code": t_dir_code,
                    "heading": f"{overall_heading:.1f}° ({t_dir_code})",
                    "seg_spds": ", ".join(f"{s:.1f}" for s in seg_speeds),
                    "seg_dirs": ", ".join(f"{h:.0f}°" for h in seg_headings),
                    "geometry": line,
                }
            )

    # Tính vận tốc trung bình của tất cả các đoạn
    overall_avg_speed_kmh = (
        float(np.mean(all_segment_speeds_kmh)) if all_segment_speeds_kmh else 0.0
    )
    overall_avg_speed_ms = overall_avg_speed_kmh / 3.6

    # Tính hướng di chuyển trung bình/chủ đạo (vector circular mean)
    if all_segment_headings:
        sin_sum = sum(math.sin(math.radians(h)) for h in all_segment_headings)
        cos_sum = sum(math.cos(math.radians(h)) for h in all_segment_headings)
        avg_heading_rad = math.atan2(sin_sum, cos_sum)
        overall_avg_heading = (math.degrees(avg_heading_rad) + 360.0) % 360.0
        dom_dir_vn, dom_dir_code = heading_to_compass_name(overall_avg_heading)
        dom_dir_str = f"{dom_dir_vn} ({dom_dir_code}) - {overall_avg_heading:.1f}°"
    else:
        dom_dir_str = "--"

    # 6. Xuất các tệp GeoJSON và Shapefile
    # 6.1. File Điểm (Points)
    point_rows = []
    for d in all_detections:
        point_rows.append(
            {
                "track_id": d["track_id"] if d["track_id"] is not None else 0,
                "frame": d["frame"],
                "label": d["label"],
                "time_mark": d["time_mark"],
                "class": d["class"],
                "score": d["score"],
                "seg_dist_m": d["seg_dist_m"],
                "seg_spd_k": d["seg_spd_k"],
                "seg_spd_ms": d["seg_spd_ms"],
                "heading_deg": d["heading_deg"],
                "direction": d["direction"],
                "dir_code": d["dir_code"],
                "geometry": d["geometry"],
            }
        )

    gdf_points = gpd.GeoDataFrame(point_rows, geometry="geometry", crs=native_crs)
    points_geojson = os.path.join(args.output_dir, "vehicle_points.geojson")
    points_shp = os.path.join(args.output_dir, "vehicle_points.shp")
    gdf_points.to_file(points_geojson, driver="GeoJSON")
    try:
        gdf_points.to_file(points_shp, driver="ESRI Shapefile", encoding="utf-8")
    except Exception as e:
        log_progress(f"[WARN] Could not export points shapefile: {e}")

    # 6.2. File Toàn tuyến (Tracks)
    tracks_geojson = os.path.join(args.output_dir, "vehicle_tracks.geojson")
    tracks_shp = os.path.join(args.output_dir, "vehicle_tracks.shp")
    if trajectory_rows:
        gdf_tracks = gpd.GeoDataFrame(
            trajectory_rows, geometry="geometry", crs=native_crs
        )
        gdf_tracks.to_file(tracks_geojson, driver="GeoJSON")
        try:
            gdf_tracks.to_file(tracks_shp, driver="ESRI Shapefile", encoding="utf-8")
        except Exception as e:
            log_progress(f"[WARN] Could not export tracks shapefile: {e}")
    else:
        empty_tracks = gpd.GeoDataFrame(
            columns=["track_id", "geometry"], crs=native_crs
        )
        empty_tracks.to_file(tracks_geojson, driver="GeoJSON")

    # 6.3. File Từng đoạn (Segments)
    segments_geojson = os.path.join(args.output_dir, "vehicle_segments.geojson")
    segments_shp = os.path.join(args.output_dir, "vehicle_segments.shp")
    if segment_rows:
        gdf_segs = gpd.GeoDataFrame(segment_rows, geometry="geometry", crs=native_crs)
        gdf_segs.to_file(segments_geojson, driver="GeoJSON")
        try:
            gdf_segs.to_file(segments_shp, driver="ESRI Shapefile", encoding="utf-8")
        except Exception as e:
            log_progress(f"[WARN] Could not export segments shapefile: {e}")
    else:
        empty_segs = gpd.GeoDataFrame(columns=["track_id", "geometry"], crs=native_crs)
        empty_segs.to_file(segments_geojson, driver="GeoJSON")

    # 7. In tóm tắt kết quả chuẩn xác
    log_progress("\n==================================================")
    log_progress("=== KẾT QUẢ THEO DÕI PHƯƠNG TIỆN ===")
    log_progress(f" [RESULT] Total Tracks: {len(trajectory_rows)}")
    log_progress(f" [RESULT] Total Points: {len(all_detections)}")
    log_progress(f" [RESULT] Total Segments: {len(segment_rows)}")
    log_progress(
        f" [RESULT] Vận tốc trung bình: {overall_avg_speed_kmh:.2f} km/h ({overall_avg_speed_ms:.2f} m/s)"
    )
    log_progress(f" [RESULT] Overall Average Speed: {overall_avg_speed_kmh:.2f} km/h")
    log_progress(f" [RESULT] Hướng di chuyển chủ đạo: {dom_dir_str}")
    log_progress(f" [RESULT] Dominant Direction: {dom_dir_str}")
    log_progress("--------------------------------------------------")
    for row in trajectory_rows:
        log_progress(
            f"  Track #{row['track_id']} ({row['class']}): "
            f"{row['num_pts']} điểm | "
            f"Quãng đường = {row['tot_dist_m']} m | "
            f"Hướng = {row['heading']} | "
            f"Vận tốc TB = {row['avg_spd_k']} km/h | "
            f"Vận tốc từng đoạn: [{row['seg_spds']}] km/h"
        )
    log_progress("==================================================")
    log_progress(f" 1. File điểm (nhãn ngày giờ, hướng): {points_geojson}")
    log_progress(f" 2. File toàn tuyến (vận tốc, hướng tổng quát): {tracks_geojson}")
    log_progress(
        f" 3. File từng đoạn (vận tốc, góc phương vị & hướng): {segments_geojson}"
    )

    result(
        avg_speed_kmh=round(overall_avg_speed_kmh, 2),
        tracks=len(trajectory_rows),
        points=len(all_detections),
        segments=len(segment_rows),
        direction=dom_dir_str,
        points_file=points_geojson,
        tracks_file=tracks_geojson,
        segments_file=segments_geojson,
    )

    elapsed = time.time() - start_time
    log_progress(f"[OK] Hoàn thành toàn bộ tiến trình trong {elapsed:.2f} giây.")
    log_progress("=== Process Finished ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

