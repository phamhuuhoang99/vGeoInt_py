"""Hàm dùng chung: đọc nhãn, suy luận theo tile, NMS xoay, tính AP."""
from pathlib import Path
import sys

import cv2
import numpy as np
import torch
from shapely.geometry import Polygon

sys.stdout.reconfigure(encoding="utf-8")  # in tiếng Việt trên console Windows
ROOT = Path(__file__).resolve().parents[1]
CLASSES = ["armored_vehicle", "aircraft", "helicopter"]

# Lớp của model DOTA gốc -> lớp của mình (dùng cho baseline zero-shot)
DOTA_MAP = {"plane": 1, "helicopter": 2, "large vehicle": 0}
# Chế độ kết hợp: model DOTA chỉ lo máy bay/trực thăng, model xe tăng lo armored_vehicle
DOTA_AIR_MAP = {"plane": 1, "helicopter": 2}


def load_gt(label_path, w, h):
    """Đọc nhãn YOLO-OBB -> list (cls, poly[4,2] theo pixel)."""
    out = []
    p = Path(label_path)
    if not p.exists():
        return out
    for line in p.read_text().split("\n"):
        v = line.split()
        if len(v) != 9:
            continue
        poly = np.array(v[1:], dtype=np.float32).reshape(4, 2) * [w, h]
        out.append((int(v[0]), poly))
    return out


def _tiles(w, h, tile, overlap):
    step = int(tile * (1 - overlap))
    xs = list(range(0, max(w - tile, 0) + 1, step)) or [0]
    ys = list(range(0, max(h - tile, 0) + 1, step)) or [0]
    if xs[-1] + tile < w:
        xs.append(w - tile)
    if ys[-1] + tile < h:
        ys.append(h - tile)
    return [(x, y) for y in ys for x in xs]


def rotated_nms(xywhr, scores, iou=0.3):
    if len(scores) == 0:
        return np.zeros(0, dtype=int)
    from ultralytics.utils.metrics import batch_probiou
    b = torch.as_tensor(xywhr, dtype=torch.float32)
    s = torch.as_tensor(scores, dtype=torch.float32)
    order = s.argsort(descending=True)
    ious = batch_probiou(b[order], b[order]).triu_(diagonal=1)
    keep = (ious.max(dim=0).values < iou)
    return order[keep].numpy()


def predict(model, img, class_map=None, imgsz=640, conf=0.25, tile=None, overlap=0.2):
    """Suy luận 1 ảnh (BGR). Ảnh lớn hơn `tile` sẽ được cắt tile chồng lấp rồi gộp NMS.

    class_map: dict {tên lớp của model: id lớp của mình}; None = giữ nguyên id lớp của model.
    Trả về list (cls, conf, poly[4,2], xywhr[5]).
    """
    h, w = img.shape[:2]
    tile = tile or max(h, w)
    names = model.names
    all_xywhr, all_poly, all_conf, all_cls = [], [], [], []
    for x0, y0 in _tiles(w, h, tile, overlap):
        crop = img[y0:y0 + tile, x0:x0 + tile]
        r = model.predict(crop, imgsz=imgsz, conf=conf, verbose=False)[0]
        if r.obb is None or len(r.obb) == 0:
            continue
        for xywhr, poly, c, k in zip(r.obb.xywhr.cpu().numpy(), r.obb.xyxyxyxy.cpu().numpy(),
                                     r.obb.conf.cpu().numpy(), r.obb.cls.cpu().numpy().astype(int)):
            if class_map is not None:
                if names[k] not in class_map:
                    continue
                k = class_map[names[k]]
            xywhr = xywhr.copy()
            xywhr[:2] += (x0, y0)
            all_xywhr.append(xywhr)
            all_poly.append(poly + (x0, y0))
            all_conf.append(float(c))
            all_cls.append(int(k))
    dets = []
    all_cls = np.array(all_cls)
    for k in np.unique(all_cls):
        idx = np.where(all_cls == k)[0]
        keep = rotated_nms(np.array(all_xywhr)[idx], np.array(all_conf)[idx])
        for j in idx[keep]:
            dets.append((int(k), all_conf[j], all_poly[j], all_xywhr[j]))
    return dets


def add_model_args(ap):
    ap.add_argument("--weights", default=str(ROOT / "weights" / "yolo11s-obb.pt"))
    ap.add_argument("--dota", action="store_true", help="--weights là model DOTA gốc: map lớp sang 3 lớp")
    ap.add_argument("--tank-weights", default=None,
                    help="model xe tăng; khi có thì --weights (DOTA) chỉ dùng cho máy bay/trực thăng")
    ap.add_argument("--imgsz", type=int, default=1024)
    ap.add_argument("--tank-imgsz", type=int, default=1600,
                    help="phóng ảnh lên cho model xe tăng (xe trong ảnh test nhỏ hơn dữ liệu train)")
    ap.add_argument("--tank-box-scale", type=float, default=1.0,
                    help="thu nhỏ hộp xe tăng quanh tâm: nhãn train (Roboflow) là hộp thẳng rộng, "
                         "bao cả bóng xe -> model chỉ train bằng Roboflow (tank_obb) cần 0.65; model tank_ft dùng 1.0")


def build_detector(a):
    """Trả về hàm detect(img, conf, tile) dùng 1 model hoặc kết hợp DOTA + model xe tăng."""
    from ultralytics import YOLO
    main = YOLO(a.weights)
    if not a.tank_weights:
        cmap = DOTA_MAP if a.dota else None
        return lambda img, conf, tile=None: predict(main, img, cmap, imgsz=a.imgsz, conf=conf, tile=tile)
    tank = YOLO(a.tank_weights)

    def detect(img, conf, tile=None):
        air = predict(main, img, DOTA_AIR_MAP, imgsz=a.imgsz, conf=conf, tile=tile)
        tanks = [scale_box(d, a.tank_box_scale)
                 for d in predict(tank, img, None, imgsz=a.tank_imgsz, conf=conf, tile=tile) if d[0] == 0]
        # model xe tăng chưa từng thấy máy bay -> hay báo nhầm trên thân máy bay/trực thăng: bỏ các hộp đó
        tanks = [t for t in tanks
                 if not any(cv2.pointPolygonTest(d[2].astype(np.float32), tuple(map(float, t[3][:2])), False) >= 0
                            for d in air if d[1] >= 0.25)]
        return air + tanks
    return detect


def scale_box(det, f):
    """Co/giãn hộp xoay quanh tâm theo hệ số f."""
    if f == 1.0:
        return det
    c, conf, poly, xywhr = det
    ctr = poly.mean(axis=0)
    xywhr = xywhr.copy()
    xywhr[2:4] *= f
    return c, conf, (poly - ctr) * f + ctr, xywhr


def _hbb(p):
    x0, y0 = p.min(axis=0)
    x1, y1 = p.max(axis=0)
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def poly_iou(a, b, hbb=False):
    if hbb:  # so khớp theo hộp thẳng bao ngoài (công bằng cho model học từ nhãn hộp thẳng)
        a, b = _hbb(a), _hbb(b)
    pa, pb = Polygon(a), Polygon(b)
    if not pa.is_valid or not pb.is_valid:
        pa, pb = pa.buffer(0), pb.buffer(0)
    inter = pa.intersection(pb).area
    union = pa.area + pb.area - inter
    return inter / union if union > 0 else 0.0


def average_precision(preds, gts, iou_thr=0.5, hbb=False):
    """preds/gts: dict ảnh -> list (cls, conf, poly) / (cls, poly). Trả về {cls: (AP, P, R, nGT)}."""
    res = {}
    for k in range(len(CLASSES)):
        n_gt = sum(1 for g in gts.values() for c, _ in g if c == k)
        cand = [(conf, im, poly) for im, p in preds.items() for c, conf, poly, *_ in p if c == k]
        cand.sort(key=lambda t: -t[0])
        used = {im: np.zeros(len(g), bool) for im, g in gts.items()}
        tp = np.zeros(len(cand))
        for i, (_, im, poly) in enumerate(cand):
            best, bj = 0.0, -1
            for j, (c, gpoly) in enumerate(gts.get(im, [])):
                if c != k or used[im][j]:
                    continue
                iou = poly_iou(poly, gpoly, hbb)
                if iou > best:
                    best, bj = iou, j
            if best >= iou_thr:
                tp[i] = 1
                used[im][bj] = True
        if n_gt == 0:
            continue
        ctp = np.cumsum(tp)
        rec = ctp / n_gt
        prec = ctp / (np.arange(len(tp)) + 1)
        # AP nội suy 101 điểm (kiểu COCO)
        ap = np.mean([prec[rec >= t].max() if np.any(rec >= t) else 0 for t in np.linspace(0, 1, 101)])
        p = prec[-1] if len(prec) else 0.0
        r = rec[-1] if len(rec) else 0.0
        res[CLASSES[k]] = (ap, p, r, n_gt)
    return res


def print_table(res, title):
    print(f"\n== {title} ==")
    print(f"{'lớp':18s} {'nGT':>5s} {'P':>6s} {'R':>6s} {'AP50':>6s}")
    for name, (ap, p, r, n) in res.items():
        print(f"{name:18s} {n:5d} {p:6.3f} {r:6.3f} {ap:6.3f}")
    if res:
        print(f"{'mAP50':18s} {'':5s} {'':6s} {'':6s} {np.mean([v[0] for v in res.values()]):6.3f}")


COLORS = [(0, 0, 255), (0, 255, 255), (255, 255, 0)]


def draw(img, dets, gts=None):
    vis = img.copy()
    for c, poly in gts or []:
        cv2.polylines(vis, [poly.astype(np.int32)], True, (0, 255, 0), 1)
    for c, conf, poly, *_ in dets:
        p = poly.astype(np.int32)
        cv2.polylines(vis, [p], True, COLORS[c], 2)
        cv2.putText(vis, f"{CLASSES[c][:4]} {conf:.2f}", tuple(p[0]), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, COLORS[c], 1, cv2.LINE_AA)
    return vis
