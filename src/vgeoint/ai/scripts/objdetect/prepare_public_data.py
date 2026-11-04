"""Chuẩn bị dữ liệu huấn luyện 3 lớp (armored_vehicle, aircraft, helicopter) từ bộ công khai.

Nguồn 1 - DOTA v1.0 (tự tải qua Ultralytics, ~2 GB): lấy `plane` -> aircraft, `helicopter` -> helicopter.
Nguồn 2 - các bộ xe tăng / xe quân sự (vd. Roboflow Universe, xuất định dạng "YOLOv8" hoặc
          "YOLOv8 Oriented Bounding Boxes"), truyền bằng --extra. Tên lớp trong data.yaml của bộ đó
          được map theo từ khoá (xem KEYWORDS). bbox thẳng (5 số) được đổi thành OBB 4 góc.

    python scripts/prepare_public_data.py --extra D:/datasets/military-tanks --extra D:/datasets/apc
    python scripts/prepare_public_data.py --no-dota --extra ...     # bỏ DOTA

Kết quả: data/train/{images,labels}/{train,val} + data/dataset.yaml
"""
import argparse
import random
import shutil
from pathlib import Path

import cv2
import numpy as np
import yaml

from common import ROOT, CLASSES

OUT = ROOT / "data" / "train"
DOTA_KEEP = {0: 1, 11: 2}  # DOTA id: plane=0, helicopter=11
KEYWORDS = [  # (từ khoá trong tên lớp, lớp đích) - kiểm tra theo thứ tự
    (("helicopter", "heli"), 2),
    (("tank", "armor", "armour", "apc", "ifv", "military vehicle", "military_vehicle", "btr", "bmp", "t-72",
      "t72", "t-90", "howitzer", "artillery"), 0),
    (("plane", "aircraft", "airplane", "jet", "fighter", "bomber", "transport"), 1),
]
EXCLUDE = ("storage", "oil", "water", "fuel")  # "storage tank" không phải xe tăng
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def map_name(name):
    n = name.lower()
    if any(e in n for e in EXCLUDE):
        return None
    for keys, cls in KEYWORDS:
        if any(k in n for k in keys):
            return cls
    return None


def convert_line(line, cmap, box_scale=1.0):
    v = line.split()
    if not v or int(v[0]) not in cmap:
        return None
    cls = cmap[int(v[0])]
    nums = [float(x) for x in v[1:]]
    if len(nums) == 4:  # bbox thẳng xc yc w h -> 4 góc
        xc, yc, w, h = nums
        nums = [xc - w / 2, yc - h / 2, xc + w / 2, yc - h / 2, xc + w / 2, yc + h / 2, xc - w / 2, yc + h / 2]
    elif len(nums) >= 6 and len(nums) % 2 == 0 and len(nums) != 8:  # đa giác (segment) -> hộp xoay nhỏ nhất
        pts = np.array(nums, dtype=np.float32).reshape(-1, 2)
        nums = cv2.boxPoints(cv2.minAreaRect(pts)).flatten().tolist()
    elif len(nums) != 8:
        return None
    if box_scale != 1.0:  # co hộp quanh tâm (nhãn Roboflow rộng, bao cả bóng xe)
        pts = np.array(nums).reshape(4, 2)
        ctr = pts.mean(axis=0)
        nums = ((pts - ctr) * box_scale + ctr).flatten().tolist()
    nums = [min(max(x, 0.0), 1.0) for x in nums]
    return f"{cls} " + " ".join(f"{x:.6f}" for x in nums)


def add_split(img_dir, lbl_dir, cmap, split, prefix, max_n, neg_ratio, rng, box_scale=1.0):
    imgs = sorted(p for p in Path(img_dir).glob("*") if p.suffix.lower() in IMG_EXTS)
    pos, neg = [], []
    for p in imgs:
        lp = Path(lbl_dir) / f"{p.stem}.txt"
        lines = [l for l in (convert_line(x, cmap, box_scale) for x in lp.read_text().splitlines()) if l] if lp.exists() else []
        (pos if lines else neg).append((p, lines))
    rng.shuffle(pos)
    rng.shuffle(neg)
    if max_n:
        pos = pos[:max_n]
    neg = neg[:int(len(pos) * neg_ratio)]
    for p, lines in pos + neg:
        name = f"{prefix}_{p.stem}"
        shutil.copy(p, OUT / "images" / split / f"{name}{p.suffix.lower()}")
        (OUT / "labels" / split / f"{name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(pos), len(neg)


def prepare_dota(tile, max_n, rng):
    from ultralytics.data.utils import check_det_dataset
    from ultralytics.data.split_dota import split_trainval

    info = check_det_dataset("DOTAv1.yaml")  # tự tải nếu chưa có
    root = Path(info["path"])
    split_dir = root.parent / f"DOTAv1-split{tile}"
    if not (split_dir / "images" / "train").exists():
        print(f"Cắt tile {tile} cho DOTA -> {split_dir} (một lần, mất vài chục phút)...")
        split_trainval(data_root=str(root), save_dir=str(split_dir), crop_size=tile, gap=tile // 5, rates=[1.0])
    for split in ("train", "val"):
        n = add_split(split_dir / "images" / split, split_dir / "labels" / split, DOTA_KEEP, split,
                      "dota", max_n if split == "train" else max_n // 5, 0.1, rng)
        print(f"DOTA {split}: {n[0]} tile có đối tượng, {n[1]} tile nền")


def prepare_extra(path, max_n, rng, box_scale=1.0):
    path = Path(path)
    cfg = next(iter(path.glob("data.yaml")), None)
    names = yaml.safe_load(cfg.read_text())["names"] if cfg else {}
    if isinstance(names, list):
        names = dict(enumerate(names))
    cmap = {int(i): c for i, n in names.items() if (c := map_name(str(n))) is not None}
    print(f"{path.name}: map lớp {[(names[i], CLASSES[c]) for i, c in cmap.items()]}")
    if not cmap:
        print("  -> không có lớp nào khớp, bỏ qua (sửa KEYWORDS nếu cần)")
        return
    # Roboflow: train/ valid/ test/ mỗi thư mục có images/ labels/
    # không có valid/ thì dùng test/ làm tập val
    has_val = (path / "valid" / "images").exists() or (path / "val" / "images").exists()
    for src_split, split in (("train", "train"), ("valid", "val"), ("val", "val"),
                             ("test", "train" if has_val else "val")):
        d = path / src_split
        if (d / "images").exists():
            n = add_split(d / "images", d / "labels", cmap, split, f"x_{path.name}_{src_split}", max_n, 0.1,
                          rng, box_scale)
            print(f"  {src_split} -> {split}: {n[0]} ảnh có đối tượng, {n[1]} ảnh nền")


def prepare_labai(names, repeat, classes):
    """Thêm ảnh LabelAI (nhãn hộp xoay ôm sát, trích từ GeoHub) vào tập train, lặp lại `repeat` lần.

    Chỉ giữ các lớp trong `classes`; ảnh không còn nhãn nào (vd. ảnh sân bay khi chỉ giữ lớp xe tăng)
    trở thành ảnh nền -> dạy model không báo nhầm trên sân bê tông.
    """
    src = ROOT / "data" / "test_labai"
    for name in names:
        lines = [l for l in (src / "labels" / f"{name}.txt").read_text().splitlines()
                 if l.strip() and int(l.split()[0]) in classes]
        for r in range(repeat):
            shutil.copy(src / "images" / f"{name}.jpg", OUT / "images" / "train" / f"labai_{name}_{r}.jpg")
            (OUT / "labels" / "train" / f"labai_{name}_{r}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
        print(f"LabelAI {name}: {len(lines)} đối tượng x {repeat} bản")


def make_holdout(names):
    """Tập test riêng gồm các ảnh LabelAI KHÔNG dùng để train."""
    dst = ROOT / "data" / "test_holdout"
    if dst.exists():
        shutil.rmtree(dst)
    for d in ("images", "labels"):
        (dst / d).mkdir(parents=True)
    src = ROOT / "data" / "test_labai"
    for n in names:
        shutil.copy(src / "images" / f"{n}.jpg", dst / "images")
        shutil.copy(src / "labels" / f"{n}.txt", dst / "labels")
    print(f"Tập test giữ lại: {dst} ({', '.join(names)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", action="append", default=[], help="thư mục bộ dữ liệu YOLO (Roboflow export)")
    ap.add_argument("--no-dota", action="store_true")
    ap.add_argument("--tile", type=int, default=640)
    ap.add_argument("--max-dota", type=int, default=1500, help="số tile DOTA tối đa (CPU)")
    ap.add_argument("--max-extra", type=int, default=0, help="giới hạn ảnh mỗi bộ extra (0 = tất cả)")
    ap.add_argument("--extra-box-scale", type=float, default=1.0, help="co hộp của bộ extra (vd. 0.7)")
    ap.add_argument("--labai-train", default="", help="ảnh LabelAI đưa vào train, vd. image1,image3")
    ap.add_argument("--labai-holdout", default="", help="ảnh LabelAI giữ lại làm test, vd. image2,image4")
    ap.add_argument("--labai-repeat", type=int, default=25, help="số lần lặp mỗi ảnh LabelAI")
    ap.add_argument("--labai-classes", default="0", help="lớp giữ lại từ nhãn LabelAI (mặc định: chỉ xe tăng)")
    a = ap.parse_args()

    if OUT.exists():
        shutil.rmtree(OUT)
    for d in ("images", "labels"):
        for s in ("train", "val"):
            (OUT / d / s).mkdir(parents=True)
    rng = random.Random(0)
    if not a.no_dota:
        prepare_dota(a.tile, a.max_dota, rng)
    for e in a.extra:
        prepare_extra(e, a.max_extra, rng, a.extra_box_scale)
    if a.labai_train:
        prepare_labai(a.labai_train.split(","), a.labai_repeat, {int(c) for c in a.labai_classes.split(",")})
    if a.labai_holdout:
        make_holdout(a.labai_holdout.split(","))

    cfg = {"path": str(OUT), "train": "images/train", "val": "images/val",
           "test": str(ROOT / "data" / ("test_holdout" if a.labai_holdout else "test_labai") / "images"),
           "names": dict(enumerate(CLASSES))}
    (ROOT / "data" / "dataset.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    for s in ("train", "val"):
        counts = [0] * len(CLASSES)
        for f in (OUT / "labels" / s).glob("*.txt"):
            for l in f.read_text().split("\n"):
                if l.strip():
                    counts[int(l.split()[0])] += 1
        print(f"{s}: {len(list((OUT / 'images' / s).glob('*')))} ảnh, số đối tượng {dict(zip(CLASSES, counts))}")
    if not a.extra:
        print("\nCHÚ Ý: chưa có dữ liệu xe tăng/xe bọc thép (--extra) -> lớp armored_vehicle sẽ không học được.")


if __name__ == "__main__":
    main()
