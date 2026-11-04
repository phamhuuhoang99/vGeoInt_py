"""Trích nhãn YOLO-OBB cho 10 ảnh test từ ảnh chụp màn hình GeoHub (LabelAI/Annotation).

Cách làm:
  1. Tìm vị trí + tỉ lệ của ảnh gốc trong screenshot bằng template matching đa tỉ lệ.
  2. Cắt vùng canvas, resize về kích thước ảnh gốc.
  3. Lớp phủ màu của mỗi hộp làm thay đổi màu pixel -> so với ảnh gốc để lấy mask phủ,
     tách viền (màu đậm) ra để các hộp sát nhau không dính vào nhau.
  4. Mỗi thành phần liên thông -> minAreaRect -> 4 đỉnh, chuẩn hoá -> file .txt.

Chạy: python scripts/extract_gt_from_screens.py
Kết quả: data/test_labai/{images,labels,vis}
"""
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")  # in tiếng Việt trên console Windows
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "LabelAI"
OUT = ROOT / "data" / "test_labai"

CLASSES = ["armored_vehicle", "aircraft", "helicopter"]

# Màu (tông) của lớp phủ trên GeoHub -> lớp của mình. Xác định theo chú giải trên từng ảnh.
# hue theo OpenCV (0-180). Màu xám (nhà/hầm chứa máy bay) bị bỏ qua nhờ ngưỡng độ bão hoà.
HUE = {"red": (0, 12), "red2": (165, 180), "yellow": (20, 40), "cyan": (80, 100), "blue": (105, 135)}
IMAGE_CLASSES = {
    # ảnh: {tông màu: lớp}
    "image1": {"red": 0, "red2": 0},
    "image2": {"red": 0, "red2": 0},
    "image3": {"red": 0, "red2": 0},
    "image4": {"red": 0, "red2": 0},
    "image5": {"red": 0, "red2": 0},
    "image6": {"red": 1, "red2": 1, "yellow": 1},
    "image7": {"yellow": 1},
    "image8": {"red": 1, "red2": 1},
    "image9": {"blue": 1},
    "image10": {"cyan": 2},
}
# Số hộp GeoHub hiển thị ("Tổng: N", không tính hầm chứa) - dùng để kiểm tra.
EXPECTED = {"image1": 3, "image2": 2, "image3": 9, "image4": 15, "image5": 24,
            "image6": 9, "image7": 6, "image8": 6, "image9": 3, "image10": 4}


def locate(shot_gray, orig_gray):
    """Trả về (x, y, scale) của ảnh gốc trong screenshot."""
    h, w = orig_gray.shape
    canvas = shot_gray[:, 195:1630]  # vùng hiển thị ảnh của GeoHub
    best = (-1, 0, 0, 1.0)
    for s in np.arange(0.8, 2.2, 0.01):
        tw, th = int(round(w * s)), int(round(h * s))
        if tw > canvas.shape[1] or th > canvas.shape[0]:
            break
        t = cv2.resize(orig_gray, (tw, th), interpolation=cv2.INTER_AREA)
        r = cv2.matchTemplate(canvas, t, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(r)
        if mv > best[0]:
            best = (mv, ml[0] + 195, ml[1], s)
    # tinh chỉnh tỉ lệ
    mv0, x0, y0, s0 = best
    for s in np.arange(s0 - 0.01, s0 + 0.01, 0.001):
        tw, th = int(round(w * s)), int(round(h * s))
        t = cv2.resize(orig_gray, (tw, th), interpolation=cv2.INTER_AREA)
        r = cv2.matchTemplate(canvas, t, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(r)
        if mv > best[0]:
            best = (mv, ml[0] + 195, ml[1], s)
    return best


def hue_mask(hsv, lo, hi, sat_min):
    return ((hsv[..., 0] >= lo) & (hsv[..., 0] <= hi) & (hsv[..., 1] >= sat_min))


def extract(name):
    orig = cv2.imread(str(SRC / "Anh-Goc" / f"{name}.jpg"))
    shot = cv2.imread(str(SRC / "Annotation" / f"{name}.png"))
    h, w = orig.shape[:2]
    score, x, y, s = locate(cv2.cvtColor(shot, cv2.COLOR_BGR2GRAY), cv2.cvtColor(orig, cv2.COLOR_BGR2GRAY))

    # Làm việc ở độ phân giải screenshot (viền mảnh 1-2px), ảnh gốc phóng lên cho khớp.
    tw, th = int(round(w * s)), int(round(h * s))
    crop = shot[y:y + th, x:x + tw].astype(np.int16)
    up = cv2.resize(orig, (tw, th), interpolation=cv2.INTER_CUBIC).astype(np.int16)
    diff = np.abs(crop - up).sum(axis=2)
    hsv_shot = cv2.cvtColor(crop.astype(np.uint8), cv2.COLOR_BGR2HSV)
    # Màu của phần chênh lệch (crop - up) chỉ hướng về màu lớp phủ.
    delta = np.clip(crop - up + 128, 0, 255).astype(np.uint8)
    hsv_delta = cv2.cvtColor(delta, cv2.COLOR_BGR2HSV)

    boxes = []
    for cls in sorted(set(IMAGE_CLASSES[name].values())):
        tint = np.zeros(diff.shape, bool)
        edge = np.zeros(diff.shape, bool)
        for color, c in IMAGE_CLASSES[name].items():  # gộp các tông cùng lớp (đỏ nằm ở 2 đầu dải hue)
            if c != cls:
                continue
            lo, hi = HUE[color]
            tint |= (diff > 30) & hue_mask(hsv_delta, lo, hi, 25)
            # Viền: pixel gần như thuần màu lớp (bão hoà cao, sáng)
            edge |= hue_mask(hsv_shot, lo, hi, 170) & (hsv_shot[..., 2] > 150)
        tint = tint.astype(np.uint8) * 255
        tint = cv2.morphologyEx(tint, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        edge = cv2.dilate(edge.astype(np.uint8) * 255, np.ones((3, 3), np.uint8))
        interior = cv2.bitwise_and(tint, cv2.bitwise_not(edge))
        interior = cv2.morphologyEx(interior, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(interior, 8)
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] < 150 * s * s:
                continue
            pts = np.column_stack(np.where(lab == i))[:, ::-1].astype(np.float32)
            (cx, cy), (bw, bh), ang = cv2.minAreaRect(pts)
            # bù lại phần viền đã cắt bỏ
            rect = ((cx, cy), (bw + 3, bh + 3), ang)
            poly = cv2.boxPoints(rect) / s  # về toạ độ ảnh gốc
            boxes.append((cls, poly))
    return orig, boxes, score, s


def main():
    for d in ("images", "labels", "vis"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    colors = [(0, 0, 255), (0, 255, 255), (255, 255, 0)]
    total_ok = True
    for name in sorted(IMAGE_CLASSES, key=lambda n: int(n[5:])):
        orig, boxes, score, s = extract(name)
        h, w = orig.shape[:2]
        shutil.copy(SRC / "Anh-Goc" / f"{name}.jpg", OUT / "images" / f"{name}.jpg")
        lines, vis = [], orig.copy()
        for cls, poly in boxes:
            p = poly.copy()
            p[:, 0] = np.clip(p[:, 0], 0, w - 1) / w
            p[:, 1] = np.clip(p[:, 1], 0, h - 1) / h
            lines.append(f"{cls} " + " ".join(f"{v:.6f}" for v in p.flatten()))
            cv2.polylines(vis, [poly.astype(np.int32)], True, colors[cls], 2)
        (OUT / "labels" / f"{name}.txt").write_text("\n".join(lines) + "\n")
        cv2.imwrite(str(OUT / "vis" / f"{name}.jpg"), vis)
        ok = len(boxes) == EXPECTED[name]
        total_ok &= ok
        print(f"{name}: {len(boxes):3d} hộp (GeoHub: {EXPECTED[name]:3d}) "
              f"match={score:.3f} scale={s:.3f} {'OK' if ok else 'KIỂM TRA LẠI'}")
    if not total_ok:
        print("\nMột số ảnh lệch số lượng: xem data/test_labai/vis và sửa nhãn bằng tay nếu cần.")


if __name__ == "__main__":
    main()
