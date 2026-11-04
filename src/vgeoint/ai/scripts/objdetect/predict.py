"""Phát hiện xe tăng/xe bọc thép, máy bay, trực thăng trên ảnh vệ tinh hoặc UAV.

Ảnh lớn (vệ tinh) được cắt tile chồng lấp rồi gộp bằng NMS xoay.
    python scripts/predict.py --source LabelAI/Anh-Goc --tank-weights runs/obb/tank_obb/weights/best.pt
    python scripts/predict.py --source anh_ve_tinh_lon.tif --tile 1024 --tank-weights ...
Kết quả: ảnh vẽ hộp + detections.csv trong runs/predict/
"""
import argparse
import csv
from pathlib import Path

import cv2

from common import ROOT, CLASSES, add_model_args, build_detector, draw

EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="ảnh hoặc thư mục ảnh")
    add_model_args(ap)
    ap.add_argument("--tile", type=int, default=1024, help="kích thước tile cho ảnh lớn")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--out", default=str(ROOT / "runs" / "predict"))
    a = ap.parse_args()

    src = Path(a.source)
    files = sorted(p for p in (src.iterdir() if src.is_dir() else [src]) if p.suffix.lower() in EXTS)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    detect = build_detector(a)

    with open(out / "detections.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["image", "class", "conf", "cx", "cy", "w", "h", "angle_rad",
                     "x1", "y1", "x2", "y2", "x3", "y3", "x4", "y4"])
        for p in files:
            img = cv2.imread(str(p))
            dets = detect(img, a.conf, a.tile)
            for c, conf, poly, xywhr in dets:
                wr.writerow([p.name, CLASSES[c], f"{conf:.3f}", *[f"{v:.1f}" for v in xywhr[:4]],
                             f"{xywhr[4]:.4f}", *[f"{v:.1f}" for v in poly.flatten()]])
            cv2.imwrite(str(out / f"{p.stem}.jpg"), draw(img, dets))
            counts = {k: sum(1 for d in dets if d[0] == i) for i, k in enumerate(CLASSES)}
            print(p.name, counts)
    print(f"Kết quả: {out}")


if __name__ == "__main__":
    main()
