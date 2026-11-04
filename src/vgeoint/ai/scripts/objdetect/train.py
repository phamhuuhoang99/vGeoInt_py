"""Fine-tune YOLO11-OBB (pretrained DOTA) cho 3 lớp trên CPU.

    python scripts/train.py                      # yolo11n-obb, 30 epoch
    python scripts/train.py --model yolo11s-obb.pt --epochs 50
Trọng số tốt nhất: runs/obb/tank_aircraft/weights/best.pt
"""
import argparse
import os

from ultralytics import YOLO

from common import ROOT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo11n-obb.pt")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--freeze", type=int, default=10, help="đóng băng backbone để train nhanh trên CPU")
    ap.add_argument("--name", default="tank_aircraft")
    ap.add_argument("--data", default=str(ROOT / "data" / "dataset.yaml"))
    ap.add_argument("--patience", type=int, default=10)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()

    if a.resume:
        YOLO(str(ROOT / "runs" / "obb" / a.name / "weights" / "last.pt")).train(resume=True)
        return
    YOLO(a.model).train(
        data=a.data,
        epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, device="cpu",
        workers=min(8, os.cpu_count() or 4), cache="ram", freeze=a.freeze,
        # ảnh nhìn từ trên xuống: xoay/lật tự do không làm sai ngữ nghĩa
        degrees=180, flipud=0.5, fliplr=0.5, mosaic=1.0, scale=0.5,
        patience=a.patience, project=str(ROOT / "runs" / "obb"), name=a.name, exist_ok=True,
    )


if __name__ == "__main__":
    main()
