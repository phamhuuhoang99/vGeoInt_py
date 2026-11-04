"""Đánh giá model trên 10 ảnh test LabelAI (AP50 theo lớp) + lưu ảnh trực quan.

Baseline zero-shot (model DOTA gốc, map plane/helicopter/large vehicle):
    python scripts/evaluate.py --dota
Kết hợp DOTA (máy bay, trực thăng) + model xe tăng đã huấn luyện:
    python scripts/evaluate.py --tank-weights runs/obb/tank_obb/weights/best.pt
"""
import argparse
from pathlib import Path

import cv2

from common import ROOT, add_model_args, build_detector, load_gt, average_precision, print_table, draw


def main():
    ap = argparse.ArgumentParser()
    add_model_args(ap)
    ap.add_argument("--data", default=str(ROOT / "data" / "test_labai"))
    ap.add_argument("--conf", type=float, default=0.05)
    ap.add_argument("--iou", type=float, default=0.5, help="ngưỡng IoU tính là đúng")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    detect = build_detector(a)
    data = Path(a.data)
    tag = Path(a.tank_weights).stem + "+dota" if a.tank_weights else Path(a.weights).stem
    out = Path(a.out or ROOT / "runs" / "eval" / tag)
    out.mkdir(parents=True, exist_ok=True)

    preds, gts = {}, {}
    for img_path in sorted((data / "images").glob("*.jpg")):
        img = cv2.imread(str(img_path))
        h, w = img.shape[:2]
        gts[img_path.stem] = load_gt(data / "labels" / f"{img_path.stem}.txt", w, h)
        preds[img_path.stem] = detect(img, a.conf)
        vis = draw(img, [d for d in preds[img_path.stem] if d[1] >= 0.25], gts[img_path.stem])
        cv2.imwrite(str(out / img_path.name), vis)

    print_table(average_precision(preds, gts, a.iou), f"{tag}: IoU hộp xoay >= {a.iou}")
    print_table(average_precision(preds, gts, a.iou, hbb=True), f"{tag}: IoU hộp thẳng bao ngoài >= {a.iou}")
    print(f"\nẢnh trực quan (xanh lá = GT, màu = dự đoán conf>=0.25): {out}")


if __name__ == "__main__":
    main()
