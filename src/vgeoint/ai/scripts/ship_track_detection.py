# -*- coding: utf-8 -*-
"""
Ship Detection & Sequential Trajectory Tracking Pipeline for vGeoInt_v2
Detects ships in multi-temporal satellite images/videos and tracks trajectories across dates.
Enhanced with detailed logging for real-time progress tracking in vGeoInt GUI.
"""

import argparse
import sys
import os
import re
import cv2
import numpy as np
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
    import torch
    import torchvision
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
    from torchvision.models.detection.mask_rcnn import MaskRCNNPredictor

    log_progress("[OK] PyTorch and TorchVision loaded successfully")
except ImportError as e:
    missing_deps.append("torch/torchvision")
    log_error(f"Missing PyTorch/TorchVision: {e}")

try:
    import rasterio
    from rasterio.transform import xy
    from rasterio.windows import Window

    log_progress("[OK] Rasterio loaded successfully")
except ImportError as e:
    missing_deps.append("rasterio")
    log_error(f"Missing Rasterio: {e}")

try:
    from shapely.geometry import Point, Polygon, LineString
    import geopandas as gpd

    log_progress("[OK] GeoPandas and Shapely loaded successfully")
except ImportError as e:
    missing_deps.append("geopandas/shapely")
    log_error(f"Missing GeoPandas/Shapely: {e}")

try:
    from scipy.spatial.distance import cdist
    from scipy.optimize import linear_sum_assignment

    log_progress("[OK] SciPy loaded successfully")
except ImportError as e:
    missing_deps.append("scipy")
    log_error(f"Missing SciPy: {e}")

if missing_deps:
    DEPENDENCIES_AVAILABLE = False
    log_error(f"Missing dependencies: {', '.join(missing_deps)}")
    log_error("Please install required packages:")
    log_error(
        "pip install torch torchvision opencv-python rasterio geopandas shapely scipy"
    )
else:
    log_progress("[OK] All Python dependencies loaded successfully")


def build_maskrcnn_model(num_classes=2):
    """Khởi tạo mô hình Mask R-CNN ResNet50-FPN"""
    model = torchvision.models.detection.maskrcnn_resnet50_fpn(weights=None)
    in_features = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = FastRCNNPredictor(in_features, num_classes)

    in_features_mask = model.roi_heads.mask_predictor.conv5_mask.in_channels
    model.roi_heads.mask_predictor = MaskRCNNPredictor(
        in_features_mask, 256, num_classes
    )
    return model


def load_model_weights(model, weights_path, device):
    """Load trọng số đã huấn luyện vào mô hình"""
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"Không tìm thấy file trọng số tại: {weights_path}")
    log_progress(f"Loading weights from {weights_path}...")
    checkpoint = torch.load(weights_path, map_location=device)
    if isinstance(checkpoint, dict) and "model" in checkpoint:
        model.load_state_dict(checkpoint["model"])
    elif isinstance(checkpoint, dict) and "state_dict" in checkpoint:
        model.load_state_dict(checkpoint["state_dict"])
    else:
        model.load_state_dict(checkpoint)
    model.to(device)
    model.eval()
    log_progress(f"[OK] Model weights loaded successfully on {device}")
    return model


def parse_date_from_filename(filename):
    """
    Trích xuất ngày tháng từ tên file/thư mục.
    Hỗ trợ các định dạng:
    - dd-mm-yyyy, dd-m-yyyy (ví dụ: 04-4-2026, 04-04-2026, 15-04-2026)
    - dd_mm_yyyy, dd_m_yyyy
    - yyyy-mm-dd, yyyy_mm_dd
    - dd-mm, dd_mm (ví dụ: 04-4, 07-4, 15-4)
    """
    stem = Path(filename).stem

    # 1. dd-mm-yyyy or dd_mm_yyyy or dd.mm.yyyy
    match_dmy = re.search(r"(\d{1,2})[-_.](\d{1,2})[-_.](\d{4})", stem)
    if match_dmy:
        d, m, y = (
            int(match_dmy.group(1)),
            int(match_dmy.group(2)),
            int(match_dmy.group(3)),
        )
        dt = datetime(y, m, d)
        return dt, f"{d:02d}-{m:02d}-{y}"

    # 2. yyyy-mm-dd or yyyy_mm_dd
    match_ymd = re.search(r"(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})", stem)
    if match_ymd:
        y, m, d = (
            int(match_ymd.group(1)),
            int(match_ymd.group(2)),
            int(match_ymd.group(3)),
        )
        dt = datetime(y, m, d)
        return dt, f"{d:02d}-{m:02d}-{y}"

    # 3. dd-mm or dd_mm (assume current/default year 2026)
    match_dm = re.search(r"(\d{1,2})[-_](\d{1,2})", stem)
    if match_dm:
        d, m = int(match_dm.group(1)), int(match_dm.group(2))
        dt = datetime(2026, m, d)
        return dt, f"{d:02d}-{m:02d}"

    # Fallback to alphanumeric sort key
    return datetime(1970, 1, 1), stem


def scan_input_directory(input_dir):
    """
    Quét toàn bộ ảnh / GeoTIFF / video trong thư mục đầu vào và sắp xếp theo ngày.
    """
    valid_exts = {
        ".tif",
        ".tiff",
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".img",
        ".mp4",
        ".avi",
        ".mov",
        ".mkv",
    }
    found_items = []

    if not os.path.exists(input_dir):
        log_error(f"Input directory does not exist: {input_dir}")
        return []

    # Check entries in input_dir
    entries = sorted(os.listdir(input_dir))
    for entry in entries:
        full_path = os.path.join(input_dir, entry)
        if os.path.isfile(full_path):
            ext = os.path.splitext(entry)[1].lower()
            if ext in valid_exts:
                dt, date_str = parse_date_from_filename(entry)
                found_items.append((dt, date_str, full_path))
        elif os.path.isdir(full_path):
            # Check if directory itself represents a date and contains an image
            sub_files = [
                f
                for f in os.listdir(full_path)
                if os.path.splitext(f)[1].lower() in valid_exts
            ]
            if sub_files:
                target_file = os.path.join(full_path, sub_files[0])
                dt, date_str = parse_date_from_filename(entry)
                found_items.append((dt, date_str, target_file))

    # Sort by parsed datetime
    found_items.sort(key=lambda x: (x[0], x[1]))
    log_progress(f"Found {len(found_items)} sequential data files in {input_dir}:")
    for dt, date_str, path in found_items:
        log_progress(f"  - [{date_str}] -> {os.path.basename(path)}")

    return [(date_str, path) for _, date_str, path in found_items]


def is_valid_ship_geometry(
    poly, min_area_m2=30, max_area_m2=40000, min_aspect_ratio=1.5
):
    """
    Bộ lọc đặc trưng hình học loại bỏ nhiễu:
    - Area: Loại bỏ vệt quá nhỏ hoặc quá lớn.
    - Aspect Ratio: Tàu thuyền thường thuôn dài.
    - Solidity: Loại bỏ vệt loang lổ.
    """
    area = poly.area
    if area < min_area_m2 or area > max_area_m2:
        return False

    rect = poly.minimum_rotated_rectangle
    rect_coords = list(rect.exterior.coords)
    if len(rect_coords) >= 3:
        edge1 = Point(rect_coords[0]).distance(Point(rect_coords[1]))
        edge2 = Point(rect_coords[1]).distance(Point(rect_coords[2]))
        length = max(edge1, edge2)
        width = min(edge1, edge2)

        if width == 0 or (length / width) < min_aspect_ratio:
            return False

    if poly.convex_hull.area > 0:
        solidity = poly.area / poly.convex_hull.area
        if solidity < 0.50:
            return False

    return True


def apply_spatial_nms(polygons, scores, iou_threshold=0.3):
    """NMS địa lý - Mức iou_threshold=0.3 cân bằng giữa lọc duplicate và giữ tàu sát nhau."""
    if len(polygons) == 0:
        return []

    indices = np.argsort(scores)[::-1]
    keep = []

    while len(indices) > 0:
        current_idx = indices[0]
        keep.append(current_idx)
        current_poly = polygons[current_idx]

        rest_indices = indices[1:]
        filtered_indices = []

        for idx in rest_indices:
            other_poly = polygons[idx]
            if current_poly.intersects(other_poly):
                intersection = current_poly.intersection(other_poly).area
                union = current_poly.union(other_poly).area
                iou = intersection / union if union > 0 else 0
                if iou < iou_threshold:
                    filtered_indices.append(idx)
            else:
                filtered_indices.append(idx)

        indices = np.array(filtered_indices)

    return keep


def detect_ship_centroids_arcgis_style(
    model,
    image_path,
    confidence_threshold=0.60,
    min_pixels=30,
    max_pixels=30000,
    tile_size=256,
    padding=32,
    batch_size=16,
    device="cuda",
):
    """
    Phát hiện tàu thuyền trên ảnh GeoTIFF hoặc ảnh thông thường bằng Mask R-CNN.
    """
    detected_polygons = []
    detected_scores = []
    core_size = tile_size - 2 * padding

    # Kiểm tra xem có phải rasterio mở được không
    is_spatial = False
    crs = "EPSG:4326"
    transform = None
    img_w, img_h = 0, 0

    try:
        src = rasterio.open(image_path)
        if src.crs is not None and src.transform is not None:
            is_spatial = True
            crs = src.crs
            transform = src.transform
        img_w, img_h = src.width, src.height
        has_rasterio = True
    except Exception:
        has_rasterio = False
        src = None

    if has_rasterio and src is not None:
        with src:
            tiles = []
            for y in range(0, img_h, core_size):
                for x in range(0, img_w, core_size):
                    win_x = max(0, x - padding)
                    win_y = max(0, y - padding)
                    win_w = min(tile_size, img_w - win_x)
                    win_h = min(tile_size, img_h - win_y)

                    window = Window(win_x, win_y, win_w, win_h)
                    tiles.append((x, y, win_x, win_y, window))

            log_progress(
                f"Processing raster: {os.path.basename(image_path)} ({img_w}x{img_h}, {len(tiles)} tiles)..."
            )

            for i in range(0, len(tiles), batch_size):
                batch_info = tiles[i : i + batch_size]
                batch_tensors = []
                valid_metadata = []

                for orig_x, orig_y, win_x, win_y, window in batch_info:
                    try:
                        read_bands = [1, 2, 3] if src.count >= 3 else [1] * 3
                        rgb_tile = src.read(read_bands, window=window)
                    except Exception:
                        continue

                    if rgb_tile.shape[1] != tile_size or rgb_tile.shape[2] != tile_size:
                        padded_tile = np.zeros(
                            (3, tile_size, tile_size), dtype=rgb_tile.dtype
                        )
                        padded_tile[:, : rgb_tile.shape[1], : rgb_tile.shape[2]] = (
                            rgb_tile
                        )
                        rgb_tile = padded_tile

                    if np.all(rgb_tile == 0):
                        continue

                    img_tensor = torch.from_numpy(rgb_tile / 255.0).float()
                    batch_tensors.append(img_tensor.to(device))
                    valid_metadata.append((orig_x, orig_y, win_x, win_y))

                if not batch_tensors:
                    continue

                with torch.no_grad():
                    preds = model(batch_tensors)

                for (orig_x, orig_y, win_x, win_y), pred in zip(valid_metadata, preds):
                    masks = pred["masks"].cpu().numpy()
                    scores = pred["scores"].cpu().numpy()

                    for j, score in enumerate(scores):
                        if score >= confidence_threshold:
                            binary_mask = masks[j, 0] > 0.5
                            pixel_area = binary_mask.sum()

                            if not (min_pixels <= pixel_area <= max_pixels):
                                continue

                            contours, _ = cv2.findContours(
                                binary_mask.astype(np.uint8),
                                cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE,
                            )

                            for contour in contours:
                                if len(contour) < 3:
                                    continue

                                tile_centroid_x = contour[:, 0, 0].mean()
                                tile_centroid_y = contour[:, 0, 1].mean()

                                abs_centroid_x = win_x + tile_centroid_x
                                abs_centroid_y = win_y + tile_centroid_y

                                in_core_x = (
                                    orig_x <= abs_centroid_x < orig_x + core_size
                                )
                                in_core_y = (
                                    orig_y <= abs_centroid_y < orig_y + core_size
                                )

                                if not (in_core_x and in_core_y):
                                    continue

                                geo_coords = []
                                for pt in contour:
                                    px_x = win_x + pt[0][0]
                                    px_y = win_y + pt[0][1]
                                    if is_spatial and transform is not None:
                                        geo_x, geo_y = xy(transform, px_y, px_x)
                                    else:
                                        geo_x, geo_y = float(px_x), float(-px_y)
                                    geo_coords.append((geo_x, geo_y))

                                if len(geo_coords) >= 3:
                                    poly = Polygon(geo_coords)
                                    if not poly.is_valid:
                                        poly = poly.buffer(0)
                                    if poly.is_empty:
                                        continue

                                    detected_polygons.append(poly)
                                    detected_scores.append(score)
    else:
        # Fallback OpenCV image reading
        cv_img = cv2.imread(image_path)
        if cv_img is None:
            log_error(f"Cannot read image with OpenCV: {image_path}")
            return np.array([]), str(crs)

        img_h, img_w = cv_img.shape[:2]
        rgb_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        tensor = (
            torch.from_numpy(rgb_img.transpose(2, 0, 1) / 255.0)
            .float()
            .unsqueeze(0)
            .to(device)
        )

        with torch.no_grad():
            preds = model(tensor)

        pred = preds[0]
        masks = pred["masks"].cpu().numpy()
        scores = pred["scores"].cpu().numpy()

        for j, score in enumerate(scores):
            if score >= confidence_threshold:
                binary_mask = masks[j, 0] > 0.5
                pixel_area = binary_mask.sum()
                if not (min_pixels <= pixel_area <= max_pixels):
                    continue

                contours, _ = cv2.findContours(
                    binary_mask.astype(np.uint8),
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE,
                )

                for contour in contours:
                    if len(contour) < 3:
                        continue
                    coords = [(float(pt[0][0]), float(-pt[0][1])) for pt in contour]
                    poly = Polygon(coords)
                    if poly.is_valid and not poly.is_empty:
                        detected_polygons.append(poly)
                        detected_scores.append(score)

    # Áp dụng NMS
    keep_indices = apply_spatial_nms(
        detected_polygons, detected_scores, iou_threshold=0.3
    )

    final_centroids = []
    for idx in keep_indices:
        poly = detected_polygons[idx]
        final_centroids.append((poly.centroid.x, poly.centroid.y))

    return np.array(final_centroids), str(crs)


def track_sequential_ships(centroids_dict, dates, max_step_distance=30000):
    """
    Ghép nối quỹ đạo di chuyển của tàu qua nhiều mốc thời gian bằng thuật toán Hungarian.
    """
    date_keys = [k for k in dates if len(centroids_dict.get(k, [])) > 0]
    if len(date_keys) < 2:
        log_progress(
            "[WARN] Khong du moc thoi gian (>= 2) de ghep noi chuoi di chuyen."
        )
        return []

    active_tracks = []
    first_key = date_keys[0]
    for pt in centroids_dict[first_key]:
        active_tracks.append(
            {"points": {first_key: pt}, "last_point": pt, "last_date": first_key}
        )

    for t in range(1, len(date_keys)):
        curr_date = date_keys[t]
        curr_pts = centroids_dict[curr_date]

        if len(curr_pts) == 0 or len(active_tracks) == 0:
            continue

        prev_pts = np.array([tr["last_point"] for tr in active_tracks])
        dist_matrix = cdist(prev_pts, curr_pts, metric="euclidean")

        row_ind, col_ind = linear_sum_assignment(dist_matrix)

        assigned_curr = set()
        for r, c in zip(row_ind, col_ind):
            if dist_matrix[r, c] <= max_step_distance:
                active_tracks[r]["points"][curr_date] = curr_pts[c]
                active_tracks[r]["last_point"] = curr_pts[c]
                active_tracks[r]["last_date"] = curr_date
                assigned_curr.add(c)

        for c in range(len(curr_pts)):
            if c not in assigned_curr:
                active_tracks.append(
                    {
                        "points": {curr_date: curr_pts[c]},
                        "last_point": curr_pts[c],
                        "last_date": curr_date,
                    }
                )

    # Chỉ giữ lại các con tàu xuất hiện ở ít nhất 2 mốc thời gian
    valid_tracks = [tr for tr in active_tracks if len(tr["points"]) >= 2]
    return valid_tracks


def export_spatial_outputs(tracks, all_centroids_dict, crs_str, output_dir):
    """
    Xuất dữ liệu quỹ đạo di chuyển (LineString) và tâm tàu (Point) ra GeoJSON và Shapefile.
    """
    os.makedirs(output_dir, exist_ok=True)
    lines_geom, lines_ship_ids, lines_dates, lines_distances = [], [], [], []
    points_geom, points_ship_ids, points_dates = [], [], []

    for idx, tr in enumerate(tracks):
        ship_id = f"Ship_{idx+1:03d}"
        pts_dict = tr["points"]

        sorted_dates = sorted(pts_dict.keys())
        coord_list = [pts_dict[d] for d in sorted_dates]

        total_dist = sum(
            Point(coord_list[i]).distance(Point(coord_list[i + 1]))
            for i in range(len(coord_list) - 1)
        )

        lines_geom.append(LineString(coord_list))
        lines_ship_ids.append(ship_id)
        lines_dates.append(" -> ".join(sorted_dates))
        lines_distances.append(round(total_dist, 2))

        for d in sorted_dates:
            points_geom.append(Point(pts_dict[d]))
            points_ship_ids.append(ship_id)
            points_dates.append(f"Ngay_{d}")

    # If no multi-date tracks, export all detected points anyway
    if len(points_geom) == 0:
        for d, pts in all_centroids_dict.items():
            for pt_idx, pt in enumerate(pts):
                points_geom.append(Point(pt))
                points_ship_ids.append(f"Pt_{pt_idx+1:03d}")
                points_dates.append(f"Ngay_{d}")

    # 1. Xuất file Đường di chuyển (Lines)
    lines_geojson = os.path.join(output_dir, "ship_trajectories_lines.geojson")
    lines_shp = os.path.join(output_dir, "ship_trajectories_lines.shp")

    if lines_geom:
        gdf_lines = gpd.GeoDataFrame(
            {
                "ship_id": lines_ship_ids,
                "path_dates": lines_dates,
                "total_dist": lines_distances,
                "geometry": lines_geom,
            },
            crs=crs_str,
        )
        gdf_lines.to_file(lines_geojson, driver="GeoJSON")
        try:
            gdf_lines.to_file(lines_shp, driver="ESRI Shapefile")
        except Exception as e:
            log_progress(f"[WARN] Could not export lines to shapefile: {e}")
    else:
        # Create empty GeoJSON / Shapefile
        empty_lines = gpd.GeoDataFrame(
            columns=["ship_id", "path_dates", "total_dist", "geometry"], crs=crs_str
        )
        empty_lines.to_file(lines_geojson, driver="GeoJSON")

    # 2. Xuất file Tâm tàu (Points)
    points_geojson = os.path.join(output_dir, "ship_centroids_points.geojson")
    points_shp = os.path.join(output_dir, "ship_centroids_points.shp")

    if points_geom:
        gdf_points = gpd.GeoDataFrame(
            {
                "ship_id": points_ship_ids,
                "date_mark": points_dates,
                "marker-color": "#ff0000",
                "marker-size": "medium",
                "stroke": "#ff0000",
                "fill": "#ff0000",
                "geometry": points_geom,
            },
            crs=crs_str,
        )
        gdf_points.to_file(points_geojson, driver="GeoJSON")
        try:
            gdf_points.to_file(points_shp, driver="ESRI Shapefile")
        except Exception as e:
            log_progress(f"[WARN] Could not export points to shapefile: {e}")
    else:
        empty_points = gpd.GeoDataFrame(
            columns=["ship_id", "date_mark", "geometry"], crs=crs_str
        )
        empty_points.to_file(points_geojson, driver="GeoJSON")

    log_progress("=== KET XUAT HOAN TAT DU LIEU KHONG GIAN ===")
    log_progress(f"  1. File duong di (Lines): {lines_geojson}")
    log_progress(f"  2. File tam thuyen (Points): {points_geojson}")
    log_progress(f"  Total trajectories tracked: {len(tracks)}")
    log_progress(f"  Total ship points: {len(points_geom)}")


def main():
    parser = argparse.ArgumentParser(
        description="Ship Detection & Sequential Trajectory Tracking"
    )
    parser.add_argument(
        "--input",
        "--input-dir",
        required=True,
        dest="input_dir",
        help="Directory containing sequential date images or videos",
    )
    parser.add_argument("--model", required=True, help="Model weights path (.pth)")
    parser.add_argument(
        "--output",
        "--output-dir",
        required=True,
        dest="output_dir",
        help="Output directory for results",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.60,
        help="Confidence threshold (0.1 - 1.0)",
    )
    parser.add_argument(
        "--max-distance",
        type=float,
        default=30000.0,
        help="Max distance step (m) for tracking",
    )
    parser.add_argument(
        "--device", default="auto", help="Computing device: auto, cuda, or cpu"
    )
    parser.add_argument(
        "--min-pixels", type=int, default=30, help="Min ship pixel area"
    )
    parser.add_argument(
        "--max-pixels", type=int, default=30000, help="Max ship pixel area"
    )
    parser.add_argument(
        "--tile-size", type=int, default=256, help="Tile size for scanning"
    )
    parser.add_argument(
        "--batch-size", type=int, default=16, help="Batch size for inference"
    )

    args = parser.parse_args()

    log_progress("=== vGeoInt_v2 Ship Tracking Started ===")
    log_progress(f"Input Directory: {args.input_dir}")
    log_progress(f"Model: {args.model}")
    log_progress(f"Output Directory: {args.output_dir}")
    log_progress(f"Confidence Threshold: {args.confidence}")
    log_progress(f"Max Step Distance: {args.max_distance} m")

    if not DEPENDENCIES_AVAILABLE:
        log_error("Required dependencies are not available")
        sys.exit(1)

    if not os.path.exists(args.input_dir):
        log_error(f"Input directory does not exist: {args.input_dir}")
        sys.exit(1)

    if not os.path.exists(args.model):
        log_error(f"Model file does not exist: {args.model}")
        sys.exit(1)

    # Device selection
    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device(args.device)
    log_progress(f"[OK] Using compute device: {device}")

    # 1. Scan files
    files_list = scan_input_directory(args.input_dir)
    if not files_list:
        log_error("No valid image/video files found in the input directory")
        sys.exit(1)

    dates = [item[0] for item in files_list]

    # 2. Build and load model
    start_time = time.time()
    model = build_maskrcnn_model(num_classes=2)
    model = load_model_weights(model, args.model, device)

    # 3. Detect centroids per date
    crs_system = None
    centroids_data = {}

    for date_key, img_path in files_list:
        if os.path.exists(img_path):
            log_progress(
                f"Detecting ships for date [{date_key}]: {os.path.basename(img_path)}..."
            )
            centroids, crs_str = detect_ship_centroids_arcgis_style(
                model,
                img_path,
                confidence_threshold=args.confidence,
                min_pixels=args.min_pixels,
                max_pixels=args.max_pixels,
                tile_size=args.tile_size,
                padding=32,
                batch_size=args.batch_size,
                device=device,
            )
            if crs_str is not None:
                crs_system = crs_str
            centroids_data[date_key] = centroids
            log_progress(
                f"[OK] Date [{date_key}]: Detected {len(centroids)} ship centroids"
            )
        else:
            log_progress(f"[WARN] Skipped missing file: {img_path}")
            centroids_data[date_key] = np.empty((0, 2))

    if crs_system is None:
        crs_system = "EPSG:4326"

    # 4. Track sequential ships across dates
    log_progress("Tracking sequential ship trajectories using Hungarian matching...")
    tracks = track_sequential_ships(
        centroids_data, dates=dates, max_step_distance=args.max_distance
    )
    log_progress(f"[OK] Built {len(tracks)} multi-date ship trajectories")

    # 5. Export outputs
    export_spatial_outputs(tracks, centroids_data, crs_system, args.output_dir)

    elapsed = time.time() - start_time
    log_progress(f"[OK] Total processing time: {elapsed:.2f} seconds")
    log_progress("Ship tracking completed successfully!")
    log_progress("=== Process Finished ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
