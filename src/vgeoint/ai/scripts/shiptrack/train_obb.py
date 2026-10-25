"""Step 3 of the YOLO-OBB workflow: fine-tune a DOTA-pretrained YOLO11-OBB on the tiles.

Ships are tiny in number, so augmentation does the heavy lifting: free rotation and
flips (ships have no preferred orientation from orbit), mosaic, mild scale/colour jitter.
"""
import argparse

from ultralytics import YOLO

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("data", help="dataset yaml from build_dataset.py")
    ap.add_argument("--model", default="yolo11s-obb.pt")
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--name", default="ships_v1")
    a = ap.parse_args()
    YOLO(a.model).train(
        data=a.data, imgsz=640, epochs=a.epochs, batch=16, workers=4, patience=60,
        degrees=180, flipud=0.5, fliplr=0.5, mosaic=1.0, scale=0.3, translate=0.1,
        hsv_h=0.0, hsv_s=0.3, hsv_v=0.3, close_mosaic=20,
        project="runs", name=a.name, exist_ok=True, plots=True,
    )
