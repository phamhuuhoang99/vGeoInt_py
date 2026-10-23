# -*- coding: utf-8 -*-
"""
Detect & Draw - phát hiện đối tượng trên ảnh UAV GeoTIFF đa thời gian,
lưu tọa độ, nối các tọa độ cùng một đối tượng thành quỹ đạo và vẽ lên ảnh.

Copied from D:/detectandraw/detect_and_draw.py (run by the "Phát hiện quỹ đạo trên ảnh UAV" dialog,
vgeoint.app.dialogs.uav_trajectory). Changes: default model from the app's models folder, OpenCV
GeoTIFF warnings silenced, and a final machine-readable result event for the dialog.

Ví dụ:
    python detect_and_draw.py --input-dir D:\\data\\uav --output-dir D:\\data\\out

Đầu ra (trong --output-dir):
    annotated/<ảnh>_det.jpg     bbox + ID + quỹ đạo tới thời điểm đó
    trajectories_summary.jpg    toàn bộ quỹ đạo vẽ trên ảnh cuối
    detections.csv              tọa độ pixel + địa lý của từng đối tượng
    points.geojson / tracks.geojson / segments.geojson
"""

import argparse
import colorsys
import csv
import math
import os
import re
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

warnings.filterwarnings("ignore")
# OpenCV prints a warning per unknown GeoTIFF tag (georeferencing tags) for every image it reads.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

import cv2
import numpy as np
import rasterio
import geopandas as gpd
from pyproj import CRS, Geod, Transformer
from scipy.optimize import linear_sum_assignment
from shapely.geometry import LineString, Point

SAHI_AVAILABLE = False
try:
    # Tắt backend numba của SAHI (hay lỗi trên Windows)
    try:
        import sahi.postprocess.backends as sahi_backends

        sahi_backends._backend = "numpy"
        sahi_backends._resolved_cache = "numpy"
    except Exception:
        pass
    from sahi import AutoDetectionModel
    from sahi.predict import get_sliced_prediction

    SAHI_AVAILABLE = True
except ImportError:
    pass

from ultralytics import YOLO

try:
    from vgeoint.ai.scripts._events import result
except ImportError:  # stand-alone run outside the app
    def result(**data):
        pass

DEFAULT_MODEL = os.path.join(os.environ.get("VGEOINT_MODELS_DIR", os.path.dirname(os.path.abspath(__file__))),
                             "yolo26x.pt")
VEHICLE_CLASSES = ["car", "truck", "bus", "motorcycle", "bicycle"]
ALL_CLASSES = VEHICLE_CLASSES + ["person"]
# Lớp đưa vào model; main() đặt lại theo --classes (luôn gồm mọi loại xe để khung tin cậy thấp
# bị gán nhầm lớp vẫn nối tiếp được track của lớp đã chọn)
TARGET_CLASSES = set(VEHICLE_CLASSES)
# Nhóm lớp: YOLO hay nhầm car/truck/bus giữa các frame nên ghép trong cùng nhóm không bị phạt
CLASS_GROUP = {
    "person": "person",
    "bicycle": "two_wheel",
    "motorcycle": "two_wheel",
    "car": "vehicle",
    "truck": "vehicle",
    "bus": "vehicle",
}
VALID_EXTS = {".tif", ".tiff", ".jpg", ".jpeg", ".png"}
GEOD = Geod(ellps="WGS84")


def log(msg):
    print(msg, flush=True)


# ----------------------------------------------------------------------------
# Thời gian & quét thư mục
# ----------------------------------------------------------------------------
def parse_timestamp_from_filename(path):
    """Trích thời gian từ tên file (YYYYMMDD_HHMMSS[_mmm], DJI_YYYYMMDDHHMMSS, dd-mm-yyyy), fallback mtime."""
    stem = Path(path).stem

    m = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?:_(\d{3}))?", stem)
    if m:
        ms = int(m.group(7)) if m.group(7) else 0
        return datetime(*map(int, m.groups()[:6]), ms * 1000)

    m = re.search(r"DJI_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", stem)
    if m:
        return datetime(*map(int, m.groups()))

    m = re.search(r"(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})", stem)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = re.search(r"(\d{1,2})[-_.](\d{1,2})[-_.](\d{4})", stem)
    if m:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))

    return datetime.fromtimestamp(os.path.getmtime(path))


def time_label(dt):
    return f"{dt.strftime('%H:%M:%S')}.{dt.microsecond // 1000:03d} {dt.strftime('%d/%m/%Y')}"


TIME_FORMATS = [
    "%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
    "%Y:%m:%d %H:%M:%S.%f", "%Y:%m:%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S",
]


def parse_time_string(s):
    s = s.strip()
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def find_metadata_file(input_dir):
    for name in ("metadata.txt", "metadata.csv"):
        p = os.path.join(input_dir, name)
        if os.path.isfile(p):
            return p
    return None


def load_metadata_times(path):
    """
    Đọc file metadata thời gian chụp, mỗi dòng: <tên ảnh>;<thời gian>
    (chấp nhận phân cách ; , hoặc tab; dòng tiêu đề tự bỏ qua). Trả về {tên file (lower): datetime}.
    """
    times = {}
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = re.split(r"[;\t,]", line, maxsplit=1)
            if len(parts) < 2:
                continue
            dt = parse_time_string(parts[1])
            if dt is not None:
                times[os.path.basename(parts[0].strip()).lower()] = dt
    return times


def scan_input_directory(input_dir, interval, metadata_path=None):
    meta = {}
    metadata_path = metadata_path or find_metadata_file(input_dir)
    if metadata_path:
        meta = load_metadata_times(metadata_path)
        log(f"[OK] Đọc thời gian chụp từ {os.path.basename(metadata_path)}: {len(meta)} ảnh")

    files = []
    for entry in sorted(os.listdir(input_dir)):
        full = os.path.join(input_dir, entry)
        if not os.path.isfile(full) or Path(entry).suffix.lower() not in VALID_EXTS:
            continue
        if any(k in entry.lower() for k in ["_det", "_mask", "_preview", "_output"]):
            continue
        t = meta.get(entry.lower())
        if t is None:
            if meta:
                log(f"[WARN] {entry} không có trong metadata -> lấy thời gian từ tên file")
            t = parse_timestamp_from_filename(full)
        files.append((t, full))
    files.sort(key=lambda x: (x[0], x[1]))

    # Nếu thời gian trùng nhau (không đọc được từ tên file) thì gán đều theo --interval
    times = [t for t, _ in files]
    if len(set(times)) < len(times):
        log(f"[WARN] Không xác định được mốc thời gian riêng cho từng ảnh -> "
            f"giả định cách nhau {interval} s theo thứ tự tên file.")
        files = sorted(files, key=lambda x: x[1])
        base = times[0] if times else datetime(1970, 1, 1)
        files = [(base + timedelta(seconds=i * interval), p) for i, (_, p) in enumerate(files)]
    return files


# ----------------------------------------------------------------------------
# Đọc ảnh & detect
# ----------------------------------------------------------------------------
def read_rgb(path):
    """
    Đọc ảnh/GeoTIFF thành RGB uint8 HxWx3, kèm transform, CRS và mask vùng có dữ liệu
    (bool HxW, lấy từ band alpha / nodata; None nếu toàn ảnh hợp lệ).
    """
    transform, crs, valid = None, None, None
    try:
        with rasterio.open(path) as src:
            if src.count >= 3:
                arr = np.transpose(src.read([1, 2, 3]), (1, 2, 0))
            else:
                g = src.read(1)
                arr = np.stack([g, g, g], axis=-1)
            if not src.transform.is_identity:
                transform = src.transform
            crs = src.crs
            m = src.dataset_mask() > 0
            if not m.all():
                valid = m
    except Exception:
        bgr = cv2.imread(path, cv2.IMREAD_COLOR)
        if bgr is None:
            raise RuntimeError(f"Không đọc được ảnh: {path}")
        arr = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    if arr.dtype != np.uint8:
        arr = arr.astype(np.float32)
        lo, hi = np.percentile(arr, 1), np.percentile(arr, 99)
        arr = np.clip((arr - lo) / max(hi - lo, 1e-6) * 255.0, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(arr), transform, crs, valid


FOUR_WHEEL = {"car", "truck", "bus"}
MERGE_PART_CONF = 0.03  # ngưỡng tìm mảnh thùng xe tải (chỉ dùng để gộp)


def merge_truck_parts(dets, px_m, args, gap_m=0.5, max_diag_m=18.0):
    """
    Model COCO hay tách xe tải nhìn từ trên xuống thành nhiều khung (cabin "car" + thùng "truck"/"car").
    Gộp lại thành một khung "truck" khi:
      1) một khung tin cậy cao cỡ cabin/ô tô (đường chéo <= 7 m) + một khung tin cậy thấp (>= 0.05)
         LỚN HƠN nó nhưng không quá cỡ thùng xe (đường chéo <= 15 m) nằm sát/chồng nhau
         (hai ô tô đỗ cạnh nhau đều tin cậy cao nên không bị gộp), hoặc
      2) hai khung tin cậy cao chồng lên nhau và ít nhất một khung là truck/bus.
    Khung gộp phải có đường chéo <= max_diag_m. Trả về (dets mới, số lần gộp).
    """
    gap = gap_m / px_m
    area = lambda b: max(b[2] - b[0], 1) * max(b[3] - b[1], 1)
    n_merge = 0
    changed = True
    while changed:
        changed = False
        for i in range(len(dets)):
            for j in range(len(dets)):
                if i == j:
                    continue
                a, b = dets[i], dets[j]
                if a["class"] not in FOUR_WHEEL or b["class"] not in FOUR_WHEEL:
                    continue
                ba, bb = a["bbox"], b["bbox"]
                dx = max(0.0, max(ba[0], bb[0]) - min(ba[2], bb[2]))
                dy = max(0.0, max(ba[1], bb[1]) - min(ba[3], bb[3]))
                touching = dx <= gap and dy <= gap
                overlap = dx == 0 and dy == 0
                if not touching:
                    continue
                strong_a, strong_b = a["score"] >= args.conf, b["score"] >= args.conf
                diag_a = math.hypot(ba[2] - ba[0], ba[3] - ba[1]) * px_m
                diag_b = math.hypot(bb[2] - bb[0], bb[3] - bb[1]) * px_m
                rule1 = (strong_a and not strong_b and area(bb) > area(ba) and b["score"] >= 0.05
                         and diag_a <= 7.0 and diag_b <= 15.0)
                rule2 = strong_a and strong_b and overlap and ("truck" in (a["class"], b["class"])
                                                                or "bus" in (a["class"], b["class"])) and i < j
                if not (rule1 or rule2):
                    continue
                u = [min(ba[0], bb[0]), min(ba[1], bb[1]), max(ba[2], bb[2]), max(ba[3], bb[3])]
                if math.hypot(u[2] - u[0], u[3] - u[1]) * px_m > max_diag_m:
                    continue
                merged = {"bbox": u, "cx": (u[0] + u[2]) / 2, "cy": (u[1] + u[3]) / 2,
                          "class": "bus" if "bus" in (a["class"], b["class"]) else "truck",
                          "score": max(a["score"], b["score"]), "merged": True}
                dets = [d for k, d in enumerate(dets) if k not in (i, j)] + [merged]
                n_merge += 1
                changed = True
                break
            if changed:
                break
    return dets, n_merge


def filter_nodata(dets, valid, min_valid):
    """Bỏ các khung phần lớn nằm trên vùng không có dữ liệu (mép đen của ảnh nắn)."""
    if valid is None:
        return dets, 0
    h, w = valid.shape
    kept = []
    for d in dets:
        x1, y1, x2, y2 = [int(round(v)) for v in d["bbox"]]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, max(x2, x1 + 1)), min(h, max(y2, y1 + 1))
        patch = valid[y1:y2, x1:x2]
        if patch.size and patch.mean() >= min_valid:
            kept.append(d)
    return kept, len(dets) - len(kept)


def color_hist(rgb, bbox):
    """Histogram HSV (đã chuẩn hóa) của phần lõi khung, dùng để so ngoại hình giữa các thời điểm."""
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = bbox
    mx, my = (x2 - x1) * 0.15, (y2 - y1) * 0.15
    x1, y1 = int(max(0, x1 + mx)), int(max(0, y1 + my))
    x2, y2 = int(min(w, max(x2 - mx, x1 + 1))), int(min(h, max(y2 - my, y1 + 1)))
    hsv = cv2.cvtColor(np.ascontiguousarray(rgb[y1:y2, x1:x2]), cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [12, 6, 6], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def pixel_size_m(transform, crs, w, h, gsd):
    """Kích thước 1 pixel (m) tại tâm ảnh."""
    if transform is None:
        return gsd
    if crs is not None and CRS.from_user_input(crs).is_geographic:
        x0, y0 = transform * (w / 2, h / 2)
        x1, _ = transform * (w / 2 + 1, h / 2)
        _, y1 = transform * (w / 2, h / 2 + 1)
        return math.sqrt(GEOD.inv(x0, y0, x1, y0)[2] * GEOD.inv(x0, y0, x0, y1)[2])
    return math.sqrt(abs(transform.a * transform.e))


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def is_duplicate(a, b):
    """Trùng nếu IoU cao, hoặc phần lớn khung nhỏ nằm trong khung lớn (hay gặp khi gộp các góc xoay)."""
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return iou(a, b) > 0.45 or (smaller > 0 and inter / smaller > 0.6)


def unrotate_box(box, k, w, h):
    """Đổi bbox trên ảnh np.rot90(img, k) về tọa độ ảnh gốc (rộng w, cao h)."""
    x1, y1, x2, y2 = box
    if k == 0:
        return [x1, y1, x2, y2]
    if k == 1:  # xoay ngược chiều kim đồng hồ 90°: gốc (x, y) = (w - y', x')
        return [w - y2, x1, w - y1, x2]
    if k == 2:
        return [w - x2, h - y2, w - x1, h - y1]
    return [y1, h - x2, y2, h - x1]  # k == 3: gốc (x, y) = (y', h - x')


def detect_raw(model, is_sahi, img, args, device, conf, imgsz=None):
    raw = []
    if is_sahi:
        res = get_sliced_prediction(
            img, model,
            slice_height=args.tile_size, slice_width=args.tile_size,
            overlap_height_ratio=args.overlap, overlap_width_ratio=args.overlap,
            postprocess_type="NMS", verbose=0,
        )
        for o in res.object_prediction_list:
            name = o.category.name.lower()
            score = float(o.score.value)
            if name in TARGET_CLASSES and score >= conf:
                raw.append((list(map(float, o.bbox.to_xyxy())), name, score))
    else:
        # Ultralytics coi mảng numpy là BGR, còn ảnh ở đây là RGB
        bgr = np.ascontiguousarray(img[..., ::-1])
        extra = {"imgsz": imgsz} if imgsz else {}
        for r in model(bgr, conf=conf, device=device, verbose=False, **extra):
            if r.boxes is None:
                continue
            for b in r.boxes:
                name = model.names.get(int(b.cls[0]), "").lower()
                score = float(b.conf[0])
                if name in TARGET_CLASSES and score >= conf:
                    raw.append((b.xyxy[0].cpu().numpy().astype(float).tolist(), name, score))
    return raw


def run_detection(model, is_sahi, img, args, device, conf=None, imgsz=None):
    """
    Trả về list dict {bbox, cx, cy, class, score} (tọa độ pixel ảnh gốc).
    Model COCO kém với xe nhìn thẳng từ trên xuống ở một số hướng, nên mặc định
    detect trên ảnh xoay 0/90/180/270° rồi gộp (tắt bằng --no-tta).
    """
    conf = args.conf if conf is None else conf
    h, w = img.shape[:2]
    raw = []
    for k in ((0,) if args.no_tta else (0, 1, 2, 3)):
        im = img if k == 0 else np.ascontiguousarray(np.rot90(img, k))
        for box, name, score in detect_raw(model, is_sahi, im, args, device, conf, imgsz):
            raw.append((unrotate_box(box, k, w, h), name, score))
        del im

    # NMS không phân lớp: một xe bị nhận cả car và truck thì giữ box điểm cao nhất
    raw.sort(key=lambda x: x[2], reverse=True)
    kept = []
    for cand in raw:
        if not any(is_duplicate(cand[0], k[0]) for k in kept):
            kept.append(cand)

    return [
        {
            "bbox": bbox,
            "cx": (bbox[0] + bbox[2]) / 2.0,
            "cy": (bbox[1] + bbox[3]) / 2.0,
            "class": name,
            "score": score,
        }
        for bbox, name, score in kept
    ]


# ----------------------------------------------------------------------------
# Hình học
# ----------------------------------------------------------------------------
class Geo:
    """Quy đổi khoảng cách/hướng trong hệ tọa độ chung."""

    def __init__(self, crs, gsd):
        self.crs = crs
        self.gsd = gsd  # chỉ dùng khi ảnh không có georeference (đơn vị pixel)
        self.geographic = crs is not None and CRS.from_user_input(crs).is_geographic

    def distance(self, p1, p2):
        if self.geographic:
            return GEOD.inv(p1[0], p1[1], p2[0], p2[1])[2]
        d = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        return d if self.crs is not None else d * self.gsd

    def delta_m(self, a, b):
        """Độ dời (đông, bắc) tính bằng mét từ detection a tới b."""
        dx, dy = b["geo_x"] - a["geo_x"], b["geo_y"] - a["geo_y"]
        if self.geographic:
            lat = math.radians((a["geo_y"] + b["geo_y"]) / 2)
            return dx * 111320.0 * math.cos(lat), dy * 110540.0
        if self.crs is None:
            return dx * self.gsd, dy * self.gsd
        return dx, dy

    def heading(self, p1, p2):
        """Góc phương vị 0°=Bắc, 90°=Đông."""
        if self.geographic:
            return (GEOD.inv(p1[0], p1[1], p2[0], p2[1])[0] + 360.0) % 360.0
        return (math.degrees(math.atan2(p2[0] - p1[0], p2[1] - p1[1])) + 360.0) % 360.0


def compass(deg):
    names = [
        ("Bắc", "N"), ("Bắc - Đông Bắc", "NNE"), ("Đông Bắc", "NE"), ("Đông - Đông Bắc", "ENE"),
        ("Đông", "E"), ("Đông - Đông Nam", "ESE"), ("Đông Nam", "SE"), ("Nam - Đông Nam", "SSE"),
        ("Nam", "S"), ("Nam - Tây Nam", "SSW"), ("Tây Nam", "SW"), ("Tây - Tây Nam", "WSW"),
        ("Tây", "W"), ("Tây - Tây Bắc", "WNW"), ("Tây Bắc", "NW"), ("Bắc - Tây Bắc", "NNW"),
    ]
    return names[int(round((deg % 360.0) / 22.5)) % 16]


# ----------------------------------------------------------------------------
# Ghép quỹ đạo (Hungarian)
# ----------------------------------------------------------------------------
def link_tracks(frames, geo, args):
    """Gán track_id cho mọi detection; trả về dict track_id -> list detection theo thời gian."""
    """
    Ghép 2 vòng mỗi frame (kiểu ByteTrack):
      1) track đang hoạt động <-> khung tin cậy cao (score >= --conf); khung cao chưa ghép tạo track mới.
      2) track chưa ghép <-> khung tin cậy thấp (--low-conf <= score < --conf), điều kiện chặt hơn
         và bỏ qua nhãn lớp (lớp của khung yếu hay sai). Khung yếu không bao giờ tạo track mới.
    """
    tracks = {}
    next_id = 1
    BIG = 1e9

    def assign(active, dets, weak):
        """Hungarian giữa các track active và dets; trả về {chỉ số det: track_id}."""
        if not active or not dets:
            return {}
        cost = np.full((len(active), len(dets)), BIG)
        for i, tid in enumerate(active):
            for j, d in enumerate(dets):
                c = match_cost(tracks[tid], d, geo, args, weak)
                if c is not None:
                    cost[i, j] = c
        rows, cols = linear_sum_assignment(cost)
        return {c: active[r] for r, c in zip(rows, cols) if cost[r, c] < BIG}

    for fi, fr in enumerate(frames):
        strong = [d for d in fr["detections"] if d["strong"]]
        weak = [d for d in fr["detections"] if not d["strong"]]
        active = [tid for tid, pts in tracks.items() if fi - pts[-1]["frame_idx"] <= args.max_gap + 1]

        m1 = assign(active, strong, weak=False)
        for j, tid in m1.items():
            strong[j]["track_id"] = tid
            tracks[tid].append(strong[j])

        rest = [tid for tid in active if tid not in m1.values()]
        m2 = assign(rest, weak, weak=True)
        kept_weak = []
        for j, tid in m2.items():
            d = weak[j]
            d["raw_class"], d["class"] = d["class"], tracks[tid][-1]["class"]
            d["track_id"] = tid
            tracks[tid].append(d)
            kept_weak.append(d)

        for j, d in enumerate(strong):
            if j not in m1:
                d["track_id"] = next_id
                tracks[next_id] = [d]
                next_id += 1
        fr["detections"] = strong + kept_weak
        fr["weak_unused"] = [d for j, d in enumerate(weak) if j not in m2]

    return tracks


def extend_backward(frames, tracks, geo, args):
    """
    Ngưỡng kép theo chiều ngược thời gian: track bắt đầu ở frame k (từ khung tin cậy cao) được nối
    lùi về các frame trước bằng khung tin cậy thấp chưa dùng. Cần thiết khi xe chỉ "yếu" ở ảnh đầu
    (vòng xuôi không bao giờ tạo track từ khung yếu). Dùng đúng luật ghép của khung yếu, trên trục
    thời gian lật ngược. Trả về số điểm được thêm.
    """
    BIG = 1e9
    tref = frames[-1]["time"]
    mirror = lambda d: dict(d, time=tref + (tref - d["time"]))
    added = 0
    for fi in range(len(frames) - 2, -1, -1):
        cands = frames[fi].get("weak_unused", [])
        if not cands:
            continue
        active = [tid for tid, pts in tracks.items()
                  if pts[0]["frame_idx"] > fi and pts[0]["frame_idx"] - fi <= args.max_gap + 1]
        if not active:
            continue
        cost = np.full((len(active), len(cands)), BIG)
        for i, tid in enumerate(active):
            rev = [mirror(p) for p in reversed(tracks[tid])]  # điểm sớm nhất thành "cuối"
            for j, d in enumerate(cands):
                c = match_cost(rev, mirror(d), geo, args, weak=True)
                if c is not None:
                    cost[i, j] = c
        rows, cols = linear_sum_assignment(cost)
        used = set()
        for r, c in zip(rows, cols):
            if cost[r, c] >= BIG:
                continue
            tid, d = active[r], cands[c]
            d["raw_class"], d["class"] = d["class"], tracks[tid][0]["class"]
            d["track_id"] = tid
            tracks[tid].insert(0, d)
            frames[fi]["detections"].append(d)
            used.add(c)
            added += 1
        frames[fi]["weak_unused"] = [d for j, d in enumerate(cands) if j not in used]
    return added


def match_cost(pts, d, geo, args, weak):
    """Chi phí nối detection d vào cuối track pts; None nếu không hợp lệ."""
    last = pts[-1]
    dt = (d["time"] - last["time"]).total_seconds()
    if dt <= 0:
        return None
    dist = geo.distance((last["geo_x"], last["geo_y"]), (d["geo_x"], d["geo_y"]))
    gate = max(args.min_gate, args.max_speed / 3.6 * dt * 1.35)
    if args.max_link_dist > 0:
        # 2 ảnh cách nhau lâu -> bán kính theo vận tốc rất lớn, dễ nối nhầm vật ở xa; giới hạn tuyệt đối
        gate = min(gate, args.max_link_dist)
    if dist > gate:
        return None

    # Ngoại hình: màu (khoảng cách Bhattacharyya 0..1) và kích thước thực
    app = cv2.compareHist(last["hist"], d["hist"], cv2.HISTCMP_BHATTACHARYYA)
    size_ratio = max(last["size_m"], d["size_m"]) / max(min(last["size_m"], d["size_m"]), 1e-6)
    if weak:
        # Khung yếu: không tin nhãn lớp, dựa vào kích thước và màu với ngưỡng chặt hơn
        if app > args.max_appearance * 0.8 or size_ratio > 1.8:
            return None
    else:
        if app > args.max_appearance or size_ratio > 2.5:
            return None
        # Không nối xe 4 bánh với xe 2 bánh (car/truck/bus <-> motorcycle/bicycle)
        if CLASS_GROUP[last["class"]] != CLASS_GROUP[d["class"]]:
            return None

    # Chuyển động: nếu track đã có vận tốc, dự đoán vị trí tiếp theo (vận tốc không đổi)
    pos_err = dist
    if len(pts) >= 2:
        prev = pts[-2]
        dt_prev = (last["time"] - prev["time"]).total_seconds()
        if dt_prev > 0:
            vx, vy = geo.delta_m(prev, last)
            vx, vy = vx / dt_prev, vy / dt_prev
            ax, ay = geo.delta_m(last, d)
            pos_err = math.hypot(ax - vx * dt, ay - vy * dt)
            v_prev, v_now = math.hypot(vx, vy), math.hypot(ax, ay) / dt
            # Đang chạy (> 2 m/s) mà quay ngược > 100° trong 1 bước -> không phải cùng xe
            if v_prev > 2 and v_now > 2:
                cosang = (vx * ax / dt + vy * ay / dt) / (v_prev * v_now)
                if cosang < math.cos(math.radians(100)):
                    return None
            # Giới hạn gia tốc: lệch so với vị trí dự đoán không quá min_gate + a*dt^2/2
            if pos_err > args.min_gate + 0.5 * args.max_accel * dt * dt:
                return None
    if weak and pos_err > 0.5 * gate:
        return None
    return pos_err / gate + app + 0.5 * math.log(size_ratio)


# ----------------------------------------------------------------------------
# Detect lại vùng dự đoán (lấp chỗ trống của quỹ đạo)
# ----------------------------------------------------------------------------
def predict_position(pts, t, geo):
    """
    Vị trí (geo_x, geo_y) dự đoán tại thời điểm t và độ bất định (m).
    t nằm giữa 2 điểm -> nội suy tuyến tính; ngoài khoảng -> ngoại suy theo vận tốc 2 điểm gần nhất.
    """
    before = [p for p in pts if p["time"] < t]
    after = [p for p in pts if p["time"] > t]
    if before and after:
        a, b = before[-1], after[0]
        r = (t - a["time"]).total_seconds() / (b["time"] - a["time"]).total_seconds()
        x = a["geo_x"] + r * (b["geo_x"] - a["geo_x"])
        y = a["geo_y"] + r * (b["geo_y"] - a["geo_y"])
        span = geo.distance((a["geo_x"], a["geo_y"]), (b["geo_x"], b["geo_y"]))
        return x, y, max(4.0, 0.25 * span)
    ref = before[-2:] if before else after[:2]
    if len(ref) < 2:
        return None
    a, b = ref
    dt_ab = (b["time"] - a["time"]).total_seconds()
    if dt_ab <= 0:
        return None
    base = b if before else a
    r = (t - base["time"]).total_seconds() / dt_ab
    x = base["geo_x"] + r * (b["geo_x"] - a["geo_x"])
    y = base["geo_y"] + r * (b["geo_y"] - a["geo_y"])
    step = geo.distance((base["geo_x"], base["geo_y"]), (x, y))
    return x, y, max(5.0, 0.35 * step)


def redetect_in_window(yolo, fr, common_crs, px, py, radius_m, obj_m, args, device):
    """
    Cắt vùng quanh (px, py) của frame, phóng to để vật nhỏ rõ hơn rồi detect ở ngưỡng thấp.
    Trả về list detection (tọa độ pixel của frame gốc, đã có hist/size_m).
    """
    with rasterio.open(fr["path"]) as src:
        px_m = pixel_size_m(fr["transform"], fr["crs"], src.width, src.height, args.gsd)
        half = int(radius_m / px_m + 1.5 * obj_m / px_m) + 16
        c0, r0 = max(0, int(px) - half), max(0, int(py) - half)
        c1, r1 = min(src.width, int(px) + half), min(src.height, int(py) + half)
        if c1 - c0 < 32 or r1 - r0 < 32:
            return []
        win = rasterio.windows.Window(c0, r0, c1 - c0, r1 - r0)
        bands = [1, 2, 3] if src.count >= 3 else [1, 1, 1]
        crop = np.ascontiguousarray(np.transpose(src.read(bands, window=win), (1, 2, 0)))
        valid = src.dataset_mask(window=win) > 0
    if crop.dtype != np.uint8:
        crop = cv2.normalize(crop, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    # Phóng to nhiều mức (kết quả của model rất nhạy với cỡ vật), gộp lại bằng NMS
    raw = []
    for factor in (1.5, 2.0, 2.5, 3.0):
        big = cv2.resize(crop, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
        # Chạy đúng cỡ ảnh đã phóng to (mặc định YOLO sẽ thu về 640 px, mất tác dụng phóng to)
        imgsz = int(min(2560, math.ceil(max(big.shape[:2]) / 32) * 32))
        for d in run_detection(yolo, False, big, args, device, conf=args.low_conf, imgsz=imgsz):
            raw.append(dict(d, bbox=[v / factor for v in d["bbox"]]))
    raw.sort(key=lambda d: -d["score"])
    dets = []
    for d in raw:
        if not any(is_duplicate(d["bbox"], k["bbox"]) for k in dets):
            dets.append(d)
    out = []
    for d in dets:
        b = d["bbox"]
        d_local = dict(d, bbox=b)
        if not filter_nodata([d_local], valid, args.min_valid)[0]:
            continue
        d_local["hist"] = color_hist(crop, b)
        d_local["size_m"] = math.sqrt(max(b[2] - b[0], 1) * max(b[3] - b[1], 1)) * px_m
        d_local["bbox"] = [b[0] + c0, b[1] + r0, b[2] + c0, b[3] + r0]
        d_local["cx"] = (d_local["bbox"][0] + d_local["bbox"][2]) / 2.0
        d_local["cy"] = (d_local["bbox"][1] + d_local["bbox"][3]) / 2.0
        out.append(d_local)
    return out


def redetect_gaps(frames, tracks, geo, yolo, common_crs, args, device):
    """
    Với mỗi track (>= 2 điểm) bị thiếu ở frame nào trong khoảng nó tồn tại (hoặc tối đa --max-gap
    frame trước/sau), detect lại quanh vị trí dự đoán. Trả về số điểm được bổ sung.
    """
    added = 0
    for tid, pts in tracks.items():
        if len(pts) < 2:
            continue
        have = {p["frame_idx"] for p in pts}
        first, last = min(have), max(have)
        todo = [k for k in range(max(0, first - args.max_gap), min(len(frames), last + args.max_gap + 1))
                if k not in have]
        # Xử lý từ trong ra ngoài để ngoại suy dùng được điểm vừa bổ sung
        todo.sort(key=lambda k: 0 if first < k < last else abs(k - first) if k < first else abs(k - last))
        for k in todo:
            fr = frames[k]
            if fr["transform"] is None:
                continue
            pred = predict_position(pts, fr["time"], geo)
            if pred is None:
                continue
            gx, gy, radius = pred
            px, py = FrameProjector(fr, common_crs, 1.0)(gx, gy)
            ref = min(pts, key=lambda p: abs((p["time"] - fr["time"]).total_seconds()))
            cands = redetect_in_window(yolo, fr, common_crs, px, py, radius, ref["size_m"], args, device)

            best, best_c = None, None
            for d in cands:
                if any(is_duplicate(d["bbox"], o["bbox"]) for o in fr["detections"]):
                    continue  # khung này đã thuộc track khác
                cgx, cgy = pixel_to_common(fr, common_crs, d["cx"], d["cy"])
                err = geo.distance((gx, gy), (cgx, cgy))
                app = cv2.compareHist(ref["hist"], d["hist"], cv2.HISTCMP_BHATTACHARYYA)
                ratio = max(ref["size_m"], d["size_m"]) / max(min(ref["size_m"], d["size_m"]), 1e-6)
                # Vị trí dự đoán + kích thước đã chặt; màu của xe nhỏ dễ lẫn nền nên dùng ngưỡng màu thường
                if err > radius or app > args.max_appearance or ratio > 1.8:
                    continue
                c = err / radius + app + 0.5 * math.log(ratio)
                if best_c is None or c < best_c:
                    best, best_c = dict(d, geo_x=cgx, geo_y=cgy), c
            if best is None:
                continue
            best.update(frame_idx=k, time=fr["time"], file=os.path.basename(fr["path"]), track_id=tid,
                        strong=False, source="redetect", raw_class=best["class"])
            best["class"] = ref["class"]
            fr["detections"].append(best)
            pts.append(best)
            pts.sort(key=lambda p: p["frame_idx"])
            have.add(k)
            added += 1
    return added


def covers(fr, common_crs, gx, gy):
    """Frame có dữ liệu ảnh tại tọa độ chung (gx, gy) không."""
    if fr["transform"] is None:
        return False
    px, py = FrameProjector(fr, common_crs, 1.0)(gx, gy)
    with rasterio.open(fr["path"]) as src:
        if not (0 <= px < src.width and 0 <= py < src.height):
            return False
        return bool(src.dataset_mask(window=rasterio.windows.Window(px, py, 1, 1))[0, 0] > 0)


def split_unconfirmed_gaps(frames, tracks, geo, common_crs):
    """
    Liên kết bỏ qua ảnh (a ở frame i, b ở frame j > i+1) chỉ được giữ khi xe không thể thấy ở các ảnh
    giữa (vị trí dự đoán nằm ngoài vùng phủ). Nếu ảnh giữa CÓ phủ vị trí đó mà kể cả detect lại cũng
    không thấy xe -> liên kết không đáng tin -> tách track tại đó. Trả về (tracks mới, số lần tách).
    """
    new_tracks, n_split = {}, 0
    next_id = max(tracks) + 1 if tracks else 1
    for tid, pts in tracks.items():
        pts = sorted(pts, key=lambda p: p["frame_idx"])
        pieces, cur = [], [pts[0]]
        for a, b in zip(pts, pts[1:]):
            ok = True
            for k in range(a["frame_idx"] + 1, b["frame_idx"]):
                pred = predict_position([a, b], frames[k]["time"], geo)
                if pred is not None and covers(frames[k], common_crs, pred[0], pred[1]):
                    ok = False
                    break
            if ok:
                cur.append(b)
            else:
                pieces.append(cur)
                cur = [b]
                n_split += 1
        pieces.append(cur)
        for i, piece in enumerate(pieces):
            nid = tid if i == 0 else next_id
            if i > 0:
                next_id += 1
            for p in piece:
                p["track_id"] = nid
            new_tracks[nid] = piece
    return new_tracks, n_split


def pixel_to_common(fr, common_crs, cx, cy):
    """Pixel của frame -> tọa độ trong hệ tọa độ chung."""
    gx, gy = fr["transform"] * (cx, cy)
    if fr["crs"] is not None and common_crs is not None \
            and CRS.from_user_input(fr["crs"]) != CRS.from_user_input(common_crs):
        gx, gy = Transformer.from_crs(fr["crs"], common_crs, always_xy=True).transform(gx, gy)
    if fr.get("corr") is not None:
        gx, gy = apply_affine(fr["corr"], gx, gy)
    return float(gx), float(gy)


# ----------------------------------------------------------------------------
# Căn chỉnh ảnh giữa các thời điểm (bù sai số nắn ảnh)
# ----------------------------------------------------------------------------
def apply_affine(A, x, y):
    return A[0, 0] * x + A[0, 1] * y + A[0, 2], A[1, 0] * x + A[1, 1] * y + A[1, 2]


def _render_on_grid(path, grid_transform, w, h, crs):
    """Kết xuất band xanh lá + mask của ảnh lên lưới chung (độ phân giải thấp)."""
    from rasterio.warp import reproject, Resampling
    gray = np.zeros((h, w), np.uint8)
    mask = np.zeros((h, w), np.uint8)
    with rasterio.open(path) as src:
        band = 2 if src.count >= 3 else 1
        reproject(rasterio.band(src, band), gray, dst_transform=grid_transform, dst_crs=crs,
                  resampling=Resampling.average)
        reproject(src.dataset_mask(), mask, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=grid_transform, dst_crs=crs, resampling=Resampling.nearest)
    return gray, mask


def estimate_alignment(path_ref, path_mov, crs, res_m=0.15):
    """
    Ước lượng phép biến đổi (đồng dạng) đưa tọa độ của ảnh path_mov về khớp ảnh path_ref,
    dựa trên điểm đặc trưng ORB ở vùng chồng lấn. Trả về (A 3x3 trên tọa độ crs, số inlier, độ lệch m)
    hoặc None nếu không đủ tin cậy.
    """
    from rasterio.warp import transform_bounds
    from rasterio.transform import from_origin
    bs = []
    for p in (path_ref, path_mov):
        with rasterio.open(p) as src:
            bs.append(transform_bounds(src.crs, crs, *src.bounds))
    l, b = max(bs[0][0], bs[1][0]), max(bs[0][1], bs[1][1])
    r, t = min(bs[0][2], bs[1][2]), min(bs[0][3], bs[1][3])
    if r <= l or t <= b:
        return None
    if CRS.from_user_input(crs).is_geographic:
        lat = math.radians((b + t) / 2)
        xres, yres = res_m / (111320.0 * math.cos(lat)), res_m / 110540.0
    else:
        xres = yres = res_m
    w, h = int((r - l) / xres), int((t - b) / yres)
    if w < 200 or h < 200:
        return None
    scale = max(1.0, max(w, h) / 4000.0)
    xres, yres = xres * scale, yres * scale
    w, h = int((r - l) / xres), int((t - b) / yres)
    G = from_origin(l, t, xres, yres)

    g1, m1 = _render_on_grid(path_ref, G, w, h, crs)
    g2, m2 = _render_on_grid(path_mov, G, w, h, crs)
    k = np.ones((15, 15), np.uint8)
    m = cv2.erode(((m1 > 0) & (m2 > 0)).astype(np.uint8) * 255, k)
    if m.mean() < 255 * 0.05:
        return None
    # Ảnh đã nắn cùng tỉ lệ -> chỉ ước lượng độ dời. SIFT + ratio test cho cặp điểm khớp sạch.
    sift = cv2.SIFT_create(6000)
    k1, d1 = sift.detectAndCompute(g1, m)
    k2, d2 = sift.detectAndCompute(g2, m)
    if d1 is None or d2 is None or len(k1) < 30 or len(k2) < 30:
        return None
    knn = cv2.BFMatcher(cv2.NORM_L2).knnMatch(d2, d1, k=2)
    matches = [p[0] for p in knn if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(matches) < 30:
        return None
    p_mov = np.float32([k2[x.queryIdx].pt for x in matches])
    p_ref = np.float32([k1[x.trainIdx].pt for x in matches])
    shifts = p_ref - p_mov
    # Bỏ phiếu: độ dời được nhiều cặp điểm ủng hộ nhất (trong bán kính 2 px). Ảnh nắn méo không đều
    # nên chỉ một phần điểm ủng hộ; phần sai lệch cục bộ còn lại do kiểm tra cục bộ xử lý.
    tol = 2.0
    best, best_n = None, 0
    for i in range(len(shifts)):
        n = int((np.abs(shifts - shifts[i]).max(axis=1) <= tol).sum())
        if n > best_n:
            best, best_n = shifts[i], n
    inl = np.abs(shifts - best).max(axis=1) <= tol
    if best_n < 30:
        return None
    dx, dy = np.median(shifts[inl], axis=0)
    shift_m = math.hypot(dx, dy) * res_m * scale
    if shift_m > 30:
        return None
    M = np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], dtype=float)
    Gm = np.array([[G.a, G.b, G.c], [G.d, G.e, G.f], [0, 0, 1]])
    A = Gm @ M @ np.linalg.inv(Gm)
    return A, int(inl.sum()), shift_m


def align_frames(frames, common_crs, args):
    """Gán frame['corr'] (tọa độ frame -> tọa độ đã căn về ảnh đầu) và cập nhật tọa độ detection."""
    I = np.eye(3)
    for fi, fr in enumerate(frames):
        fr["corr"], fr["corr_inv"] = I, I
        fr["aligned"] = fi == 0  # ảnh này đã căn được về hệ chung (ảnh đầu) hay chưa
        fr["pair_ok"] = True      # cặp (ảnh trước, ảnh này) có vị trí tương đối tin cậy không
        if fi == 0 or fr["transform"] is None or frames[0]["transform"] is None:
            continue
        est = estimate_alignment(frames[fi - 1]["path"], fr["path"], common_crs)
        if est is not None:
            A, n, shift = est
            fr["corr"] = frames[fi - 1]["corr"] @ A
            src = f"ảnh {fi}"
        else:
            est = estimate_alignment(frames[0]["path"], fr["path"], common_crs)
            if est is None:
                log(f"  [WARN] Không căn chỉnh được ảnh {fi + 1} (ít điểm chung) -> giữ nguyên tọa độ")
                fr["pair_ok"] = False
                continue
            A, n, shift = est
            fr["corr"] = A
            src = "ảnh 1"
        fr["corr_inv"] = np.linalg.inv(fr["corr"])
        # Căn theo ảnh trước mà ảnh trước chưa căn được thì chuỗi vẫn đứt
        fr["aligned"] = src == "ảnh 1" or frames[fi - 1]["aligned"]
        # Căn trực tiếp theo ảnh trước -> cặp này ổn; căn theo ảnh 1 -> chỉ ổn nếu ảnh trước cũng đã căn về ảnh 1
        fr["pair_ok"] = src != "ảnh 1" or frames[fi - 1]["aligned"]
        log(f"  Căn ảnh {fi + 1} theo {src}: lệch {shift:.2f} m ({n} điểm khớp)")
        for d in fr["detections"]:
            d["geo_x"], d["geo_y"] = apply_affine(fr["corr"], d["geo_x"], d["geo_y"])


# ----------------------------------------------------------------------------
# Kiểm tra xe đứng yên bằng ảnh
# ----------------------------------------------------------------------------
def _read_gray(path, c0, r0, c1, r1):
    with rasterio.open(path) as src:
        win = rasterio.windows.Window(int(c0), int(r0), int(c1 - c0), int(r1 - r0))
        bands = [1, 2, 3] if src.count >= 3 else [1]
        a = src.read(bands, window=win, boundless=True, fill_value=0)
    a = np.transpose(a, (1, 2, 0))
    if a.dtype != np.uint8:
        a = cv2.normalize(a, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return cv2.cvtColor(np.ascontiguousarray(a), cv2.COLOR_RGB2GRAY) if a.shape[2] == 3 else a[..., 0]


def local_displacement(a, b, fr_a, fr_b, common_crs, args, work_res=0.06):
    """
    Độ dời THẬT (m) của xe từ detection a (frame a) tới detection b (frame b), sau khi bù sai lệch
    nắn ảnh cục bộ. None nếu không căn được.

    Ảnh nắn lệch nhau không đều nên căn cục bộ: lấy vùng nền ~20 m quanh a (che chiếc xe đi),
    tìm chỗ khớp nhất ở frame b; nền tĩnh chiếm phần lớn nên vị trí khớp chính là chỗ của "cùng
    mặt đất" ở frame b. Xe đứng yên thì b nằm đúng chỗ đó.
    """
    with rasterio.open(fr_a["path"]) as src:
        pm_a = pixel_size_m(fr_a["transform"], fr_a["crs"], src.width, src.height, args.gsd)
    with rasterio.open(fr_b["path"]) as src:
        pm_b = pixel_size_m(fr_b["transform"], fr_b["crs"], src.width, src.height, args.gsd)
    x1, y1, x2, y2 = a["bbox"]
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    obj_m = max(x2 - x1, y2 - y1) * pm_a
    ctx_m = max(20.0, 4 * obj_m)
    search_m = 8.0  # sai lệch cục bộ tối đa giữa 2 ảnh nắn (sau căn toàn ảnh)

    h_ctx = ctx_m / 2 / pm_a
    ctx = _read_gray(fr_a["path"], cx - h_ctx, cy - h_ctx, cx + h_ctx, cy + h_ctx)
    f_a = pm_a / work_res
    ctx = cv2.resize(ctx, None, fx=f_a, fy=f_a, interpolation=cv2.INTER_AREA)

    gx, gy = pixel_to_common(fr_a, common_crs, cx, cy)
    ox, oy = FrameProjector(fr_b, common_crs, 1.0)(gx, gy)  # cùng điểm theo căn toàn ảnh, px frame b
    h_s = (ctx_m / 2 + search_m) / pm_b
    area = _read_gray(fr_b["path"], ox - h_s, oy - h_s, ox + h_s, oy + h_s)
    f_b = pm_b / work_res
    area = cv2.resize(area, None, fx=f_b, fy=f_b, interpolation=cv2.INTER_AREA)
    if area.shape[0] <= ctx.shape[0] or area.shape[1] <= ctx.shape[1] or (area == 0).mean() > 0.4:
        return None, None

    # Mask: bỏ chiếc xe (rộng thêm 50%) và vùng không có dữ liệu
    mask = (ctx > 0).astype(np.uint8) * 255
    ow, oh = (x2 - x1) * f_a, (y2 - y1) * f_a
    mc, mr = ctx.shape[1] / 2, ctx.shape[0] / 2
    mask[max(0, int(mr - oh * 0.75)):int(mr + oh * 0.75), max(0, int(mc - ow * 0.75)):int(mc + ow * 0.75)] = 0
    if mask.mean() < 255 * 0.35 or ctx[mask > 0].std() < 6:
        return None, None
    res = cv2.matchTemplate(area, ctx, cv2.TM_CCOEFF_NORMED, mask=mask)
    res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
    _, peak, _, (bx, by) = cv2.minMaxLoc(res)
    if peak < 0.3:
        return None, None

    # Vị trí "cùng mặt đất" của tâm a trong frame b (px gốc), so với tâm detection b
    gc = (ox - h_s) + (bx + mc) / f_b
    gr = (oy - h_s) + (by + mr) / f_b
    bcx, bcy = (b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2
    disp = math.hypot(bcx - gc, bcy - gr) * pm_b

    # "Còn ở chỗ cũ": ảnh chiếc xe a so với đúng chỗ đó (đã căn cục bộ) ở frame b, xê dịch <= 0.5 m
    patch = ctx[max(0, int(mr - oh / 2)):int(mr + oh / 2), max(0, int(mc - ow / 2)):int(mc + ow / 2)]
    stay = None
    if patch.size >= 64 and patch.std() >= 6:
        mg = 0.5 / work_res
        tc, tr = bx + mc, by + mr
        win = area[max(0, int(tr - oh / 2 - mg)):int(tr + oh / 2 + mg), max(0, int(tc - ow / 2 - mg)):int(tc + ow / 2 + mg)]
        if win.shape[0] >= patch.shape[0] and win.shape[1] >= patch.shape[1]:
            stay = float(cv2.matchTemplate(win, patch, cv2.TM_CCOEFF_NORMED).max())
    return disp, stay


def is_stationary(pts, frames, common_crs, args):
    """
    Track là vật đứng yên nếu (đo theo cả 2 chiều, lấy trung vị):
      - độ dời thật (đã bù sai lệch nắn cục bộ) < --static-dist, hoặc
      - chỗ cũ của vật ở ảnh sau vẫn còn chính vật đó (độ giống >= --static-stay): xe đỗ, hoặc 2 vật
        cố định (mái nhà...) bị nối nhầm với nhau.
    Trả về (True/False/None, độ dời trung vị m, độ giống "còn ở chỗ cũ").
    """
    disps, stays = [], []
    for a, b in zip(pts, pts[1:]):
        fa, fb = frames[a["frame_idx"]], frames[b["frame_idx"]]
        dd, st = local_displacement(a, b, fa, fb, common_crs, args)
        if dd is not None:
            disps.append(dd)
        if st is not None:
            stays.append(st)
        dd2, st2 = local_displacement(b, a, fb, fa, common_crs, args)
        if dd2 is not None:
            disps.append(dd2)
        if st2 is not None:
            stays.append(st2)
    med = float(np.median(disps)) if disps else None
    stay = float(np.median(stays)) if stays else None
    if med is None and stay is None:
        return None, None, None
    static = (med is not None and med < args.static_dist) or (stay is not None and stay >= args.static_stay)
    return static, med, stay


def track_stats(tracks, geo):
    """Tính đoạn (segment) + tổng hợp cho các track có >= 2 điểm."""
    track_rows, seg_rows = [], []
    for tid, pts in tracks.items():
        for p in pts:
            p.update(seg_dist_m=0.0, seg_spd_kmh=0.0, heading_deg=None, dir_code="")
        if len(pts) < 2:
            continue
        speeds = []
        for k in range(1, len(pts)):
            a, b = pts[k - 1], pts[k]
            pa, pb = (a["geo_x"], a["geo_y"]), (b["geo_x"], b["geo_y"])
            dist = geo.distance(pa, pb)
            dt = (b["time"] - a["time"]).total_seconds()
            spd = dist / dt * 3.6 if dt > 0 else 0.0
            hd = geo.heading(pa, pb)
            dir_vn, dir_code = compass(hd)
            b.update(seg_dist_m=round(dist, 2), seg_spd_kmh=round(spd, 2),
                     heading_deg=round(hd, 1), dir_code=dir_code)
            speeds.append(spd)
            seg_rows.append({
                "track_id": tid, "seg_idx": k,
                "start_time": time_label(a["time"]), "end_time": time_label(b["time"]),
                "dist_m": round(dist, 2), "dt_s": round(dt, 3),
                "speed_kmh": round(spd, 2), "heading_deg": round(hd, 1),
                "direction": dir_vn, "dir_code": dir_code,
                "geometry": LineString([pa, pb]),
            })

        first, last = pts[0], pts[-1]
        hd = geo.heading((first["geo_x"], first["geo_y"]), (last["geo_x"], last["geo_y"]))
        dir_vn, dir_code = compass(hd)
        classes = [p["class"] for p in pts]
        track_rows.append({
            "track_id": tid,
            "class": max(set(classes), key=classes.count),
            "num_pts": len(pts),
            "start_time": time_label(first["time"]),
            "end_time": time_label(last["time"]),
            "duration_s": round((last["time"] - first["time"]).total_seconds(), 3),
            "tot_dist_m": round(sum(p["seg_dist_m"] for p in pts[1:]), 2),
            "avg_spd_k": round(float(np.mean(speeds)), 2),
            "max_spd_k": round(max(speeds), 2),
            "heading_deg": round(hd, 1),
            "direction": dir_vn,
            "dir_code": dir_code,
            "geometry": LineString([(p["geo_x"], p["geo_y"]) for p in pts]),
        })
    return track_rows, seg_rows


# ----------------------------------------------------------------------------
# Vẽ
# ----------------------------------------------------------------------------
def track_color(tid):
    h = (tid * 0.61803398875) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.85, 1.0)
    return int(b * 255), int(g * 255), int(r * 255)  # BGR


class FrameProjector:
    """Đổi tọa độ chung (geo_x, geo_y) -> pixel của một frame cụ thể (đã scale để vẽ)."""

    def __init__(self, fr, common_crs, scale):
        self.inv = ~fr["transform"] if fr["transform"] is not None else None
        self.scale = scale
        self.to_frame = None
        if self.inv is not None and fr["crs"] is not None and common_crs is not None \
                and CRS.from_user_input(fr["crs"]) != CRS.from_user_input(common_crs):
            self.to_frame = Transformer.from_crs(common_crs, fr["crs"], always_xy=True)

        # Tọa độ chung đã được căn chỉnh về ảnh đầu; muốn vẽ lên frame này phải bỏ phần hiệu chỉnh
        self.corr_inv = fr.get("corr_inv")

    def __call__(self, x, y):
        if self.corr_inv is not None:
            x, y = apply_affine(self.corr_inv, x, y)
        if self.inv is None:
            px, py = x, -y  # ảnh không georef: geo = (px, -py)
        else:
            if self.to_frame is not None:
                x, y = self.to_frame.transform(x, y)
            px, py = self.inv * (x, y)
        return int(round(px * self.scale)), int(round(py * self.scale))


def put_label(img, text, org, color, fs, th):
    (tw, th_), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
    x, y = org
    y = max(y, th_ + base + 2)
    cv2.rectangle(img, (x, y - th_ - base - 2), (x + tw + 4, y), color, -1)
    cv2.putText(img, text, (x + 2, y - base), cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), th, cv2.LINE_AA)


def prepare_canvas(path, max_size):
    rgb = read_rgb(path)[0]
    h, w = rgb.shape[:2]
    scale = min(1.0, max_size / float(max(h, w)))
    if scale < 1.0:
        rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    canvas = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    th = max(2, int(round(min(canvas.shape[:2]) / 400)))
    fs = max(0.5, th * 0.35)
    return canvas, scale, th, fs


CHECK_COLOR = (160, 160, 160)  # xám: track cần kiểm tra
STATIC_COLOR = (255, 160, 0)   # xanh dương: phương tiện đứng yên (--keep-static)
STATUS_STATIC, STATUS_MOVING = "đứng yên", "di chuyển"


def dashed_line(img, p1, p2, color, th, dash=12):
    """Vẽ đoạn thẳng nét đứt từ p1 tới p2."""
    length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if length < 1:
        return
    n = max(1, int(length // dash))
    for i in range(0, n, 2):
        a, b = i / n, min(1.0, (i + 1) / n)
        q1 = (int(p1[0] + (p2[0] - p1[0]) * a), int(p1[1] + (p2[1] - p1[1]) * a))
        q2 = (int(p1[0] + (p2[0] - p1[0]) * b), int(p1[1] + (p2[1] - p1[1]) * b))
        cv2.line(img, q1, q2, color, th, cv2.LINE_AA)


def draw_tracks(canvas, proj, tracks, upto_idx, th, fs, min_len, with_speed=False, speeds=None):
    for tid, pts in tracks.items():
        pts_vis = [p for p in pts if p["frame_idx"] <= upto_idx]
        if len(pts_vis) < max(2, min_len):
            continue
        check = pts_vis[0].get("need_check", 0)
        is_static = pts_vis[0].get("status") == STATUS_STATIC
        color = CHECK_COLOR if check else STATIC_COLOR if is_static else track_color(tid)
        xy = [proj(p["geo_x"], p["geo_y"]) for p in pts_vis]
        if check:
            for q1, q2 in zip(xy, xy[1:]):
                dashed_line(canvas, q1, q2, color, th, dash=6 * th)
        else:
            cv2.polylines(canvas, [np.array(xy, np.int32)], False, color, th, cv2.LINE_AA)
        for q in xy:
            cv2.circle(canvas, q, th + 2, color, -1, cv2.LINE_AA)
        if not is_static:
            cv2.arrowedLine(canvas, xy[-2], xy[-1], color, th + 1, cv2.LINE_AA, tipLength=0.3)
        if with_speed:
            text = f"#{tid}"
            if speeds and tid in speeds:
                text += f" {speeds[tid]:.1f}km/h"
            if is_static:
                text = f"#{tid} stopped"
            if check:
                text += " (?)"
            put_label(canvas, text, (xy[-1][0] + 6, xy[-1][1] - 6), color, fs, max(1, th - 1))


def draw_frame(fr, fi, tracks, common_crs, args, out_path):
    canvas, scale, th, fs = prepare_canvas(fr["path"], args.max_draw_size)
    proj = FrameProjector(fr, common_crs, scale)

    draw_tracks(canvas, proj, tracks, fi, th, fs, args.min_track_len)

    for d in fr["detections"]:
        check = d.get("need_check", 0)
        is_static = d.get("status") == STATUS_STATIC
        color = CHECK_COLOR if check else STATIC_COLOR if is_static else track_color(d["track_id"])
        x1, y1, x2, y2 = [int(round(v * scale)) for v in d["bbox"]]
        if check:
            for q1, q2 in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))):
                dashed_line(canvas, q1, q2, color, th, dash=4 * th)
        else:
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, th)
        mark = ("" if d["source"] == "detect" else "*") + (" stopped" if is_static else "") + (" (?)" if check else "")
        put_label(canvas, f"#{d['track_id']} {d['class']} {d['score']:.2f}{mark}", (x1, y1 - 2),
                  color, fs, max(1, th - 1))

    put_label(canvas, f"{time_label(fr['time'])}  |  {len(fr['detections'])} objects",
              (10, int(30 * fs) + 10), (255, 255, 255), fs, max(1, th - 1))
    cv2.imwrite(out_path, canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])


def draw_summary(frames, tracks, track_rows, common_crs, args, out_path):
    fi = len(frames) - 1
    canvas, scale, th, fs = prepare_canvas(frames[fi]["path"], args.max_draw_size)
    proj = FrameProjector(frames[fi], common_crs, scale)
    speeds = {r["track_id"]: r["avg_spd_k"] for r in track_rows}
    draw_tracks(canvas, proj, tracks, fi, th, fs, args.min_track_len, with_speed=True, speeds=speeds)
    put_label(canvas, f"{time_label(frames[0]['time'])} -> {time_label(frames[-1]['time'])}  |  "
                      f"{sum(1 for r in track_rows if r['num_pts'] >= args.min_track_len)} tracks",
              (10, int(30 * fs) + 10), (255, 255, 255), fs, max(1, th - 1))
    cv2.imwrite(out_path, canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])


# ----------------------------------------------------------------------------
# Xuất dữ liệu
# ----------------------------------------------------------------------------
def write_shapefile(rows, path, crs, fields):
    """
    Ghi Shapefile (UTF-8, kèm .cpg/.prj). fields: list (tên cột trong rows, tên cột SHP <= 10 ký tự).
    Xóa bộ file cũ cùng tên trước khi ghi.
    """
    base = os.path.splitext(path)[0]
    try:
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            if os.path.exists(base + ext):
                os.remove(base + ext)
    except PermissionError:
        log(f"[ERROR] Không ghi được {os.path.basename(path)}: file đang được mở ở chương trình khác "
            f"(QGIS/ArcGIS?). Hãy gỡ layer rồi chạy lại.")
        return False
    data = [{shp: r.get(src) for src, shp in fields} | {"geometry": r["geometry"]} for r in rows]
    if data:
        gdf = gpd.GeoDataFrame(data, geometry="geometry", crs=crs)
    else:
        gdf = gpd.GeoDataFrame(columns=[shp for _, shp in fields] + ["geometry"], geometry="geometry", crs=crs)
    gdf.to_file(path, driver="ESRI Shapefile", encoding="utf-8")


def write_vector(rows, path, crs, columns):
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs) if rows else \
        gpd.GeoDataFrame(columns=columns + ["geometry"], geometry="geometry", crs=crs)
    if os.path.exists(path):
        os.remove(path)
    gdf.to_file(path, driver="GeoJSON")


def main():
    ap = argparse.ArgumentParser(description="Detect, draw & link objects across multi-temporal UAV GeoTIFFs")
    ap.add_argument("--input-dir", required=True, help="Thư mục ảnh GeoTIFF đa thời gian")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--classes", default=",".join(VEHICLE_CLASSES),
                    help=f"Lớp cần theo dõi, cách nhau dấu phẩy. Có: {', '.join(ALL_CLASSES)}")
    ap.add_argument("--conf", type=float, default=0.25, help="Ngưỡng tin cậy")
    ap.add_argument("--max-speed", type=float, default=90.0, help="Vận tốc tối đa (km/h) để giới hạn ghép")
    ap.add_argument("--low-conf", type=float, default=0.08,
                    help="Ngưỡng tin cậy thấp: khung trong [low-conf, conf) chỉ dùng để nối tiếp track có sẵn")
    ap.add_argument("--no-redetect", action="store_true",
                    help="Không detect lại (phóng to) quanh vị trí dự đoán khi track bị thiếu điểm")
    ap.add_argument("--min-speed", type=float, default=5.0,
                    help="Bỏ phương tiện có vận tốc trung bình nhỏ hơn (km/h); 0 = giữ tất cả")
    ap.add_argument("--no-align", action="store_true",
                    help="Không căn chỉnh ảnh giữa các thời điểm (mặc định có căn bằng điểm đặc trưng)")
    ap.add_argument("--min-track-score-2w", type=float, default=0.3,
                    help="Như --min-track-score nhưng cho xe máy/xe đạp (model cho điểm thấp hơn với xe nhỏ)")
    ap.add_argument("--min-track-score", type=float, default=0.45,
                    help="Bỏ track không có khung nào đạt độ tin cậy này (lọc nhận nhầm)")
    ap.add_argument("--keep-static", action="store_true",
                    help="Không loại xe đứng yên mà giữ lại với trạng thái 'đứng yên' (vẽ màu xanh dương)")
    ap.add_argument("--static-dist", type=float, default=3.0,
                    help="Xe có độ dời thật (đã bù lệch nắn ảnh cục bộ) nhỏ hơn số mét này là đứng yên; 0 = tắt")
    ap.add_argument("--static-stay", type=float, default=0.6,
                    help="Độ giống (0..1) giữa vật và chỗ cũ của nó ở ảnh sau để coi là vật đứng yên")
    ap.add_argument("--no-merge-trucks", action="store_true",
                    help="Không gộp các khung cabin + thùng của xe tải thành một khung")
    ap.add_argument("--max-link-dist", type=float, default=60.0,
                    help="Khoảng cách nối tối đa (m) giữa 2 lần xuất hiện, bất kể 2 ảnh cách nhau bao lâu; 0 = không giới hạn")
    ap.add_argument("--max-accel", type=float, default=6.0,
                    help="Gia tốc tối đa (m/s²) khi kiểm tra một điểm có thuộc track đang chạy không")
    ap.add_argument("--min-gate", type=float, default=5.0, help="Bán kính ghép tối thiểu (m)")
    ap.add_argument("--max-gap", type=int, default=2, help="Số frame tối đa một đối tượng được phép mất dấu")
    ap.add_argument("--max-appearance", type=float, default=0.6,
                    help="Ngưỡng khác biệt màu (Bhattacharyya 0..1) tối đa để nối 2 khung")
    ap.add_argument("--min-track-len", type=int, default=2, help="Số điểm tối thiểu để vẽ quỹ đạo")
    ap.add_argument("--tile-size", type=int, default=640)
    ap.add_argument("--overlap", type=float, default=0.2)
    ap.add_argument("--device", default="auto", help="auto | cpu | cuda:0")
    ap.add_argument("--no-sahi", action="store_true", help="Không cắt tile, chạy YOLO trực tiếp")
    ap.add_argument("--no-tta", action="store_true",
                    help="Chỉ detect ở hướng gốc (nhanh gấp 4 nhưng dễ sót xe nhìn từ trên xuống)")
    ap.add_argument("--max-draw-size", type=int, default=6000, help="Cạnh dài tối đa của ảnh vẽ (px)")
    ap.add_argument("--min-valid", type=float, default=0.9,
                    help="Tỉ lệ diện tích khung tối thiểu phải nằm trên vùng có dữ liệu (lọc mép đen)")
    ap.add_argument("--metadata", default=None,
                    help="File thời gian chụp (<tên ảnh>;<thời gian>). Mặc định tự tìm metadata.txt trong --input-dir")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="Khoảng thời gian giả định giữa các ảnh (s) khi không đọc được thời gian")
    ap.add_argument("--gsd", type=float, default=0.05,
                    help="m/pixel, chỉ dùng khi ảnh KHÔNG có georeference")
    args = ap.parse_args()

    t0 = time.time()
    os.makedirs(args.output_dir, exist_ok=True)
    ann_dir = os.path.join(args.output_dir, "annotated")
    os.makedirs(ann_dir, exist_ok=True)

    if args.device == "auto":
        import torch
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device

    global TARGET_CLASSES
    selected = {c.strip().lower() for c in args.classes.split(",") if c.strip()}
    unknown = selected - set(ALL_CLASSES)
    if unknown or not selected:
        log(f"[ERROR] --classes không hợp lệ: {args.classes}. Chọn trong: {', '.join(ALL_CLASSES)}")
        return 1
    TARGET_CLASSES = set(VEHICLE_CLASSES) | selected
    log(f"Đối tượng theo dõi: {', '.join(c for c in ALL_CLASSES if c in selected)}")

    items = scan_input_directory(args.input_dir, args.interval, args.metadata)
    if not items:
        log(f"[ERROR] Không có ảnh hợp lệ trong {args.input_dir}")
        return 1
    log(f"Tìm thấy {len(items)} ảnh:")
    for t, p in items:
        log(f"  [{time_label(t)}] {os.path.basename(p)}")

    # --- Model ---
    log(f"Load model {args.model} trên {device} ...")
    is_sahi = SAHI_AVAILABLE and not args.no_sahi
    if is_sahi:
        model = AutoDetectionModel.from_pretrained(
            model_type="ultralytics", model_path=args.model,
            confidence_threshold=min(args.conf, args.low_conf, MERGE_PART_CONF), device=device,
        )
    else:
        model = YOLO(args.model)
    yolo = model.model if is_sahi else model  # model Ultralytics gốc, dùng để detect lại vùng nhỏ
    log(f"[OK] {'SAHI sliced inference' if is_sahi else 'Ultralytics YOLO'}")

    # --- Detect từng frame ---
    frames = []
    common_crs = None
    to_common = {}
    for fi, (t, path) in enumerate(items):
        rgb, transform, crs, valid = read_rgb(path)
        if transform is None:
            log(f"[WARN] {os.path.basename(path)} không có georeference -> dùng tọa độ pixel (gsd={args.gsd} m/px)")
        if common_crs is None and crs is not None and transform is not None:
            common_crs = crs

        part_conf = min(args.conf, args.low_conf, MERGE_PART_CONF) if not args.no_merge_trucks else min(args.conf, args.low_conf)
        dets = run_detection(model, is_sahi, rgb, args, device, conf=part_conf)
        dets, n_drop = filter_nodata(dets, valid, args.min_valid)
        if n_drop:
            log(f"  bỏ {n_drop} khung nằm trên vùng không có dữ liệu (mép ảnh)")
        px_m = pixel_size_m(transform, crs, rgb.shape[1], rgb.shape[0], args.gsd)
        if not args.no_merge_trucks:
            dets, n_merge = merge_truck_parts(dets, px_m, args)
            if n_merge:
                log(f"  gộp {n_merge} cặp khung thành xe tải (cabin + thùng)")
        # Mảnh rất yếu chỉ dùng để gộp; mảnh lẻ còn lại dưới --low-conf thì bỏ
        dets = [d for d in dets if d["score"] >= min(args.conf, args.low_conf)]
        for d in dets:
            d["hist"] = color_hist(rgb, d["bbox"])
            x1, y1, x2, y2 = d["bbox"]
            d["size_m"] = math.sqrt(max(x2 - x1, 1) * max(y2 - y1, 1)) * px_m
        del rgb, valid

        tf = None
        if crs is not None and common_crs is not None and transform is not None \
                and CRS.from_user_input(crs) != CRS.from_user_input(common_crs):
            key = str(crs)
            if key not in to_common:
                to_common[key] = Transformer.from_crs(crs, common_crs, always_xy=True)
            tf = to_common[key]

        for d in dets:
            if transform is not None:
                gx, gy = transform * (d["cx"], d["cy"])
                if tf is not None:
                    gx, gy = tf.transform(gx, gy)
            else:
                gx, gy = d["cx"], -d["cy"]
            # Khung tin cậy cao chỉ giữ lớp được chọn; khung thấp giữ mọi lớp (chỉ để nối tiếp track)
            strong = d["score"] >= args.conf
            if strong and d["class"] not in selected:
                d["drop"] = True
            d.update(frame_idx=fi, time=t, file=os.path.basename(path),
                     geo_x=float(gx), geo_y=float(gy), track_id=None,
                     strong=strong, source="detect" if strong else "low_conf")

        dets = [d for d in dets if not d.get("drop")]
        frames.append({"path": path, "time": t, "transform": transform, "crs": crs, "detections": dets})
        counts = {}
        for d in dets:
            if d["strong"]:
                counts[d["class"]] = counts.get(d["class"], 0) + 1
        n_weak = sum(1 for d in dets if not d["strong"])
        log(f"Frame {fi + 1}/{len(items)} {os.path.basename(path)}: {sum(counts.values())} đối tượng {counts}"
            f" (+{n_weak} khung tin cậy thấp)")

    geo = Geo(common_crs, args.gsd)

    # --- Căn chỉnh ảnh (bù sai số nắn giữa các thời điểm) ---
    if not args.no_align and len(frames) > 1:
        log("Căn chỉnh ảnh giữa các thời điểm...")
        align_frames(frames, common_crs, args)

    # --- Nối quỹ đạo ---
    tracks = link_tracks(frames, geo, args)
    n_back = extend_backward(frames, tracks, geo, args)
    n_low = sum(1 for fr in frames for d in fr["detections"] if d["source"] == "low_conf")
    log(f"Ghép thêm {n_low} điểm từ khung tin cậy thấp (trong đó {n_back} điểm nối ngược thời gian)")
    if not args.no_redetect:
        n_re = redetect_gaps(frames, tracks, geo, yolo, common_crs, args, device)
        log(f"Detect lại vùng dự đoán: bổ sung {n_re} điểm")
    tracks, n_split = split_unconfirmed_gaps(frames, tracks, geo, common_crs)
    if n_split:
        log(f"Tách {n_split} liên kết bỏ qua ảnh không được xác nhận (ảnh giữa có phủ nhưng không thấy xe)")

    # Loại bỏ phương tiện không có đường đi (ít hơn min_track_len điểm) khỏi mọi đầu ra
    min_len = max(2, args.min_track_len)
    keep = {tid for tid, pts in tracks.items() if len(pts) >= min_len}
    n_removed = sum(1 for tid in tracks if tid not in keep)
    tracks = {tid: pts for tid, pts in tracks.items() if tid in keep}
    for fr in frames:
        fr["detections"] = [d for d in fr["detections"] if d["track_id"] in keep]
    if n_removed:
        log(f"Loại bỏ {n_removed} phương tiện không có đường đi (< {min_len} điểm)")

    def drop(ids):
        nonlocal tracks
        tracks = {tid: pts for tid, pts in tracks.items() if tid not in ids}
        for fr in frames:
            fr["detections"] = [d for d in fr["detections"] if d["track_id"] not in ids]

    # Lọc track theo độ tin cậy: phải có ít nhất một khung đạt ngưỡng của nhóm xe
    # (xe máy/xe đạp nhỏ nên model cho điểm thấp hơn -> ngưỡng riêng --min-track-score-2w)
    def track_threshold(pts):
        classes = [p["class"] for p in pts]
        cls = max(set(classes), key=classes.count)
        return args.min_track_score_2w if CLASS_GROUP.get(cls) == "two_wheel" else args.min_track_score
    weak_tracks = {tid for tid, pts in tracks.items() if max(p["score"] for p in pts) < track_threshold(pts)}
    if weak_tracks:
        drop(weak_tracks)
        log(f"Loại bỏ {len(weak_tracks)} track có độ tin cậy thấp (không khung nào >= "
            f"{args.min_track_score:g} ô tô / {args.min_track_score_2w:g} xe 2 bánh)")

    # Kiểm tra đứng yên bằng ảnh: chỗ xe đứng ở ảnh trước vẫn còn chính chiếc xe đó ở ảnh sau
    static = set()  # track đứng yên (chỉ còn trong kết quả khi --keep-static)
    if args.static_dist > 0:
        for tid, pts in tracks.items():
            st, score, stay = is_stationary(pts, frames, common_crs, args)
            log(f"  track #{tid}: độ dời thật {score if score is None else round(score, 1)} m, "
                f"còn ở chỗ cũ {stay if stay is None else round(stay, 2)} -> {'đứng yên' if st else 'di chuyển'}")
            if st:
                static.add(tid)
        if static and not args.keep_static:
            drop(static)
            log(f"Loại bỏ {len(static)} phương tiện/vật đứng yên (kiểm tra bằng ảnh)")
            static = set()

    track_rows, seg_rows = track_stats(tracks, geo)

    # Loại bỏ phương tiện đứng yên (vận tốc trung bình < --min-speed)
    if args.min_speed > 0:
        slow = {r["track_id"] for r in track_rows if r["avg_spd_k"] < args.min_speed}
        if slow and args.keep_static:
            static |= slow
        elif slow:
            tracks = {tid: pts for tid, pts in tracks.items() if tid not in slow}
            for fr in frames:
                fr["detections"] = [d for d in fr["detections"] if d["track_id"] not in slow]
            track_rows = [r for r in track_rows if r["track_id"] not in slow]
            seg_rows = [r for r in seg_rows if r["track_id"] not in slow]
            log(f"Loại bỏ {len(slow)} phương tiện đứng yên (vận tốc TB < {args.min_speed:g} km/h)")

    # Trạng thái từng phương tiện (chỉ có "đứng yên" khi --keep-static, nếu không xe đứng yên đã bị loại)
    for tid, pts in tracks.items():
        for p in pts:
            p["status"] = STATUS_STATIC if tid in static else STATUS_MOVING
    for r in track_rows:
        r["status"] = STATUS_STATIC if r["track_id"] in static else STATUS_MOVING
    if args.keep_static and static:
        log(f"Giữ lại {len(static)} phương tiện đứng yên (trạng thái '{STATUS_STATIC}')")

    # Đánh dấu "cần kiểm tra": track < 3 điểm mà mọi đoạn đều đi qua ảnh không căn chỉnh được
    # (sai lệch nắn ảnh có thể khiến vật đứng yên trông như đang chạy, mà không có điểm thứ 3 để đối chiếu)
    def seg_unaligned(a, b):
        return any(not frames[k].get("pair_ok", True) for k in range(a["frame_idx"] + 1, b["frame_idx"] + 1))
    flagged = set()
    if not args.no_align:
        for tid, pts in tracks.items():
            if len(pts) < 3 and all(seg_unaligned(a, b) for a, b in zip(pts, pts[1:])):
                flagged.add(tid)
    for tid, pts in tracks.items():
        for p in pts:
            p["need_check"] = int(tid in flagged)
    for r in track_rows:
        r["need_check"] = int(r["track_id"] in flagged)
        r["note"] = "cần kiểm tra: ảnh không căn chỉnh được" if r["need_check"] else ""
    if flagged:
        log(f"Đánh dấu {len(flagged)} track cần kiểm tra (chỉ dựa vào cặp ảnh không căn chỉnh được, < 3 điểm)")

    # --- Vẽ ---
    for fi, fr in enumerate(frames):
        out = os.path.join(ann_dir, f"{Path(fr['path']).stem}_det.jpg")
        draw_frame(fr, fi, tracks, common_crs, args, out)
        log(f"[OK] Vẽ {out}")
    summary_path = os.path.join(args.output_dir, "trajectories_summary.jpg")
    draw_summary(frames, tracks, track_rows, common_crs, args, summary_path)

    # --- Xuất tọa độ ---
    all_dets = [d for fr in frames for d in fr["detections"]]
    csv_path = os.path.join(args.output_dir, "detections.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["frame", "time", "file", "track_id", "class", "score",
                    "px_x", "px_y", "x1", "y1", "x2", "y2", "geo_x", "geo_y",
                    "seg_dist_m", "seg_spd_kmh", "heading_deg", "dir_code", "source", "can_kiem_tra", "trang_thai"])
        for d in all_dets:
            w.writerow([d["frame_idx"] + 1, time_label(d["time"]), d["file"], d["track_id"],
                        d["class"], round(d["score"], 3), round(d["cx"], 1), round(d["cy"], 1),
                        *[round(v, 1) for v in d["bbox"]], d["geo_x"], d["geo_y"],
                        d["seg_dist_m"], d["seg_spd_kmh"], d["heading_deg"], d["dir_code"], d["source"],
                        d.get("need_check", 0), d.get("status", STATUS_MOVING)])

    point_rows = [{
        "track_id": d["track_id"], "frame": d["frame_idx"] + 1, "time": time_label(d["time"]),
        "file": d["file"], "class": d["class"], "score": round(d["score"], 3),
        "seg_dist_m": d["seg_dist_m"], "seg_spd_k": d["seg_spd_kmh"],
        "heading_deg": d["heading_deg"], "dir_code": d["dir_code"], "source": d["source"],
        "need_check": d.get("need_check", 0), "status": d.get("status", STATUS_MOVING),
        "geometry": Point(d["geo_x"], d["geo_y"]),
    } for d in all_dets]
    write_vector(point_rows, os.path.join(args.output_dir, "points.geojson"), common_crs, ["track_id"])
    write_vector(track_rows, os.path.join(args.output_dir, "tracks.geojson"), common_crs, ["track_id"])
    write_vector(seg_rows, os.path.join(args.output_dir, "segments.geojson"), common_crs, ["track_id"])

    # Shapefile: 1 = điểm phương tiện, 2 = đường đi phương tiện
    shp_dir = os.path.join(args.output_dir, "shapefile")
    os.makedirs(shp_dir, exist_ok=True)
    for r, d in zip(point_rows, all_dets):
        r["x"], r["y"] = d["geo_x"], d["geo_y"]
    shp_points = os.path.join(shp_dir, "1_diem_phuong_tien.shp")
    shp_tracks = os.path.join(shp_dir, "2_duong_di_phuong_tien.shp")
    write_shapefile(point_rows, shp_points, common_crs, [
        ("track_id", "track_id"), ("frame", "frame"), ("time", "thoi_gian"), ("file", "ten_anh"),
        ("class", "loai"), ("score", "do_tin"), ("x", "x"), ("y", "y"),
        ("seg_dist_m", "qd_doan_m"), ("seg_spd_k", "van_toc"), ("heading_deg", "huong_deg"),
        ("dir_code", "huong"), ("source", "nguon"), ("need_check", "kiem_tra"), ("status", "trang_thai"),
    ])
    write_shapefile(track_rows, shp_tracks, common_crs, [
        ("track_id", "track_id"), ("class", "loai"), ("num_pts", "so_diem"),
        ("start_time", "bat_dau"), ("end_time", "ket_thuc"), ("duration_s", "tg_s"),
        ("tot_dist_m", "qd_m"), ("avg_spd_k", "v_tb_kmh"), ("max_spd_k", "v_max_kmh"),
        ("heading_deg", "huong_deg"), ("direction", "huong"), ("dir_code", "ma_huong"),
        ("need_check", "kiem_tra"), ("note", "ghi_chu"), ("status", "trang_thai"),
    ])

    # --- Tóm tắt ---
    log("=" * 60)
    log(f"Tổng điểm phát hiện: {len(all_dets)} | Quỹ đạo (>=2 điểm): {len(track_rows)}")
    for r in sorted(track_rows, key=lambda r: -r["num_pts"]):
        log(f"  #{r['track_id']:<4} {r['class']:<10} {r['num_pts']} điểm | "
            f"{r['tot_dist_m']:.1f} m | TB {r['avg_spd_k']:.1f} km/h | "
            f"hướng {r['heading_deg']:.0f}° ({r['dir_code']})" + ("  [CẦN KIỂM TRA]" if r["need_check"] else "")
            + ("  [ĐỨNG YÊN]" if r["status"] == STATUS_STATIC else ""))
    log("=" * 60)
    log(f"Ảnh vẽ: {ann_dir}")
    log(f"Ảnh tổng hợp: {summary_path}")
    log(f"Tọa độ: {csv_path} + points/tracks/segments.geojson")
    log(f"Shapefile 1 - điểm phương tiện: {shp_points}")
    log(f"Shapefile 2 - đường đi phương tiện: {shp_tracks}")
    log(f"Xong trong {time.time() - t0:.1f} s")
    result(output_dir=os.path.abspath(args.output_dir), tracks=len(track_rows), points=len(all_dets),
           summary=os.path.abspath(summary_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
