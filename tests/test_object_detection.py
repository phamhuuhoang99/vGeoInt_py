"""Phát hiện đối tượng (xe tăng / máy bay): the D:/detecttank code behind two dialogs."""

import json
import sys
import textwrap

import pytest

from vgeoint.common.paths import ROOT

AI_PYTHON = ROOT / ".pixi" / "envs" / "ai" / "python.exe"
SCRIPTS = ROOT / "src" / "vgeoint" / "ai" / "scripts" / "objdetect"

# Writes what run_detect.py writes: <image>_det.jpg, detections.csv and, for "geo" images, the shapefile.
FAKE_DETECT = textwrap.dedent('''
    import csv, json, os, sys
    from osgeo import gdal
    from vgeoint.ai.scripts._events import progress, result
    args = sys.argv[1:]
    out = args[args.index("--output-dir") + 1]
    target = args[args.index("--target") + 1]
    json.dump(args, open(os.environ["OBJ_ARGS_FILE"], "w"))
    os.makedirs(out, exist_ok=True)
    cls = "armored_vehicle" if target == "tank" else "aircraft"
    gdal.GetDriverByName("JPEG").CreateCopy(os.path.join(out, "image1_det.jpg"), gdal.GetDriverByName("MEM").Create("", 40, 30, 3))
    with open(os.path.join(out, "detections.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["image", "class", "conf", "cx", "cy", "w", "h", "angle_rad", "x1", "y1", "x2", "y2", "x3", "y3", "x4", "y4", "map_x", "map_y"])
        w.writerow(["image1.tif", cls, "0.910", "20.0", "15.0", "8", "6", "0.1", 16, 12, 24, 12, 24, 18, 16, 18, 585010, 2324992])
    print(f"Ảnh 1/1 image1.tif: 1 {cls}", flush=True)
    path = os.path.join(out, "detections.geojson")
    ring = [[585008, 2324994], [585012, 2324994], [585012, 2324991], [585008, 2324991], [585008, 2324994]]
    json.dump({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32648"}},
               "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                             "properties": {"image": "image1.tif", "class": cls, "loai": "x", "conf": 0.91}}]}, open(path, "w"))
    os.makedirs(os.path.join(out, "shapefile"), exist_ok=True)
    gdal.VectorTranslate(os.path.join(out, "shapefile", "detections.shp"), path, format="ESRI Shapefile")
    result(output_dir=out, counts={cls: 1}, georeferenced=1)
''')


@pytest.fixture(params=["tank", "aircraft"])
def obj(request, window, tmp_path, monkeypatch):
    from vgeoint.ai import runner
    from vgeoint.app.dialogs.object_detection import AircraftObjectDialog, TankObjectDialog
    from vgeoint.common.utils import settings
    from tests.conftest import make_raster

    settings().remove("ObjectDetection")
    scripts = tmp_path / "scripts"
    (scripts / "objdetect").mkdir(parents=True)
    (scripts / "objdetect" / "run_detect.py").write_text(FAKE_DETECT, encoding="utf-8")
    monkeypatch.setattr(runner, "SCRIPTS_DIR", scripts)
    monkeypatch.setenv("VGEOINT_AI_PYTHON", sys.executable)
    args_file = tmp_path / "obj_args.json"
    monkeypatch.setenv("OBJ_ARGS_FILE", str(args_file))
    images = tmp_path / "anh"
    images.mkdir()
    make_raster(images / "image1.tif")  # georeferenced (EPSG:32648)
    (images / "notes.txt").write_text("not an image")
    for name in ("dota.pt", "tank.pt"):
        (tmp_path / name).write_bytes(b"")
    dialog_class = TankObjectDialog if request.param == "tank" else AircraftObjectDialog
    dlg = dialog_class(window, window.map_canvas, window.layer_tree_view)
    dlg.edits["dota_weights"].setText(str(tmp_path / "dota.pt"))
    dlg.edits["tank_weights"].setText(str(tmp_path / "tank.pt"))
    dlg.images = images
    dlg.args = lambda: json.loads(args_file.read_text())
    dlg.errors = []
    monkeypatch.setattr("qgis.PyQt.QtWidgets.QMessageBox.critical", lambda *a: dlg.errors.append(a[2]))
    yield dlg
    dlg.close()


def test_menu(window):
    from vgeoint.app.dialogs.object_detection import AircraftObjectDialog, TankObjectDialog

    mb = window.menu_bar_
    assert [a.text() for a in mb.object_menu.actions()] == ["Xe tăng...", "Máy bay..."]
    for act, cls in ((mb.object_tank_act, TankObjectDialog), (mb.object_aircraft_act, AircraftObjectDialog)):
        act.trigger()
        dialogs = window.findChildren(cls)
        assert dialogs and dialogs[-1].isVisible() and not dialogs[-1].isModal()
        dialogs[-1].close()


def test_run_detects_and_adds_to_map(obj, qtbot):
    from qgis.core import QgsProject

    obj.run_btn.click()
    assert obj.errors[-1] == "Chưa chọn ảnh hoặc thư mục ảnh hợp lệ."
    obj._set_source(str(obj.images))
    assert "1 ảnh" in obj.count_label.text()  # notes.txt is not an image
    assert obj.edits["output_dir"].text() == f"{obj.images}_{obj.TARGET}"
    obj.run_btn.click()
    qtbot.waitUntil(lambda: obj.run_btn.isEnabled(), timeout=30000)

    args = obj.args()
    assert args[args.index("--target") + 1] == obj.TARGET
    assert ("--tank-weights" in args) == (obj.TARGET == "tank")
    assert obj.status_label.text().startswith("Hoàn thành ✔")
    assert [obj.image_list.item(i).text() for i in range(obj.image_list.count())] == ["image1"]
    assert obj.table.rowCount() == 1
    assert obj.table.item(0, 1).text() == ("Xe tăng/xe bọc thép" if obj.TARGET == "tank" else "Máy bay")

    group = QgsProject.instance().layerTreeRoot().findGroup(f"{obj.TITLE} - anh_{obj.TARGET}")
    assert group is not None and [n.name() for n in group.children()] == [obj.TITLE.split(": ")[-1], "image1"]
    layer = group.children()[0].layer()
    assert [c.label() for c in layer.renderer().categories()] == (
        ["Xe tăng/xe bọc thép"] if obj.TARGET == "tank" else ["Máy bay", "Trực thăng"])


def test_copied_code_is_complete():
    names = {p.name for p in SCRIPTS.glob("*.py")}
    assert names == {"common.py", "evaluate.py", "extract_gt_from_screens.py", "predict.py",
                     "prepare_public_data.py", "train.py", "run_detect.py"}


@pytest.mark.skipif(not AI_PYTHON.exists(), reason="ai environment not installed")
def test_real_script_parses_its_options():
    import subprocess

    from vgeoint.ai.runner import activated_environment

    env = activated_environment(str(AI_PYTHON))
    env["PYTHONPATH"] = str(ROOT / "src")
    out = subprocess.run([str(AI_PYTHON), str(SCRIPTS / "run_detect.py"), "--help"], capture_output=True,
                         text=True, encoding="utf-8", timeout=300, env=env)
    assert out.returncode == 0, out.stderr
    for option in ("--target", "--dota-weights", "--tank-weights", "--tile"):
        assert option in out.stdout
