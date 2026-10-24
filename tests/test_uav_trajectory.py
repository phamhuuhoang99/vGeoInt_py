"""Phát hiện quỹ đạo trên ảnh UAV: the Qt port of the Detect & Draw Tkinter GUI."""

import json
import sys
import textwrap

import pytest

from qgis.PyQt.QtCore import Qt

from vgeoint.common.paths import ROOT

AI_PYTHON = ROOT / ".pixi" / "envs" / "ai" / "python.exe"

# Writes what detect_and_draw.py writes (summary, annotated frames, tracks/points GeoJSON) and prints its
# log lines; records its arguments.
FAKE_DETECT_AND_DRAW = textwrap.dedent('''
    import json, os, sys
    import numpy as np
    from osgeo import gdal
    from vgeoint.ai.scripts._events import result
    args = sys.argv[1:]
    out = args[args.index("--output-dir") + 1]
    json.dump(args, open(os.environ["UAV_ARGS_FILE"], "w"))
    if "--fail" in os.environ.get("UAV_MODE", ""):
        print("[ERROR] Không có ảnh hợp lệ")
        sys.exit(1)
    os.makedirs(os.path.join(out, "annotated"), exist_ok=True)
    print("Tìm thấy 2 ảnh:", flush=True)
    print("[OK] SAHI sliced inference", flush=True)
    for i, name in enumerate(("DJI_0523_V", "DJI_0524_V"), 1):
        print(f"Frame {i}/2 {name}.tif: 3 đối tượng {{'car': 3}} (+0 khung tin cậy thấp)", flush=True)
    for name in ("DJI_0523_V", "DJI_0524_V"):
        path = os.path.join(out, "annotated", name + "_det.jpg")
        gdal.GetDriverByName("JPEG").CreateCopy(path, gdal.GetDriverByName("MEM").Create("", 40, 30, 3))
        print(f"[OK] Vẽ {path}", flush=True)
    gdal.GetDriverByName("JPEG").CreateCopy(os.path.join(out, "trajectories_summary.jpg"),
                                            gdal.GetDriverByName("MEM").Create("", 40, 30, 3))
    crs = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32648"}}
    tracks = {"type": "FeatureCollection", "crs": crs, "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[585000, 2325000], [585020, 2325005]]},
         "properties": {"track_id": 1, "class": "car", "num_pts": 2, "start_time": "16:29:27.000 28/03/2026",
                        "end_time": "16:29:29.000 28/03/2026", "tot_dist_m": 20.6, "avg_spd_k": 37.1,
                        "max_spd_k": 37.1, "heading_deg": 76, "direction": "Đông", "dir_code": "E",
                        "status": "di chuyển", "need_check": 0}},
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[585100, 2325100], [585101, 2325100]]},
         "properties": {"track_id": 2, "class": "truck", "num_pts": 2, "start_time": "", "end_time": "",
                        "tot_dist_m": 1.0, "avg_spd_k": 1.8, "max_spd_k": 1.8, "heading_deg": 90,
                        "direction": "Đông", "dir_code": "E", "status": "đứng yên", "need_check": 1}},
    ]}
    json.dump(tracks, open(os.path.join(out, "tracks.geojson"), "w", encoding="utf-8"), ensure_ascii=False)
    points = {"type": "FeatureCollection", "crs": crs, "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [585000, 2325000]},
         "properties": {"track_id": 1, "time": "16:29:27.000 28/03/2026"}}]}
    json.dump(points, open(os.path.join(out, "points.geojson"), "w", encoding="utf-8"))
    if os.environ.get("UAV_MODE") != "geojson-only":
        from osgeo import ogr
        os.makedirs(os.path.join(out, "shapefile"), exist_ok=True)
        for src, shp in (("tracks.geojson", "2_duong_di_phuong_tien.shp"), ("points.geojson", "1_diem_phuong_tien.shp")):
            gdal.VectorTranslate(os.path.join(out, "shapefile", shp), os.path.join(out, src), format="ESRI Shapefile")
    print("Xong trong 1.0 s", flush=True)
    result(output_dir=out, tracks=2, points=1)
''')


@pytest.fixture
def uav(window, tmp_path, monkeypatch):
    from vgeoint.ai import runner
    from vgeoint.app.dialogs.uav_trajectory import SETTINGS_KEY, UavTrajectoryDialog
    from vgeoint.common.utils import settings

    settings().remove(SETTINGS_KEY)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "detect_and_draw.py").write_text(FAKE_DETECT_AND_DRAW, encoding="utf-8")
    monkeypatch.setattr(runner, "SCRIPTS_DIR", scripts)
    monkeypatch.setenv("VGEOINT_AI_PYTHON", sys.executable)
    args_file = tmp_path / "uav_args.json"
    monkeypatch.setenv("UAV_ARGS_FILE", str(args_file))

    from tests.conftest import make_raster

    images = tmp_path / "oto3"
    images.mkdir()
    for i, name in enumerate(("DJI_20260328162927_0523_V.tif", "DJI_20260328162929_0524_V.tif",
                              "DJI_20260328162927_0523_V_buildings_mask.tif")):
        make_raster(images / name, seed=i)
    model = tmp_path / "yolo26x.pt"
    model.write_bytes(b"")
    dlg = UavTrajectoryDialog(window, window.map_canvas, window.layer_tree_view)
    dlg.edits["model"].setText(str(model))
    dlg.images = images
    dlg.args = lambda: json.loads(args_file.read_text())
    monkeypatch.setattr("qgis.PyQt.QtWidgets.QMessageBox.critical", lambda *a: dlg.__dict__.setdefault("errors", []).append(a[2]))
    yield dlg
    dlg.close()


def test_menu_opens_the_dialog(window):
    from vgeoint.app.dialogs.uav_trajectory import UavTrajectoryDialog

    mb = window.menu_bar_
    assert [a.text() for a in mb.trajectory_menu.actions()] == ["Phát hiện quỹ đạo trên ảnh UAV..."]
    mb.uav_trajectory_act.trigger()
    dialogs = window.findChildren(UavTrajectoryDialog)
    assert dialogs and dialogs[-1].isVisible() and not dialogs[-1].isModal()
    dialogs[-1].close()


def test_defaults_and_input_folder(uav):
    assert uav.windowTitle() == "Phát hiện quỹ đạo trên ảnh UAV"
    assert [k for k, c in uav.class_checks.items() if c.isChecked()] == ["car", "truck", "bus", "motorcycle", "bicycle"]
    assert uav.spins["conf"].value() == 0.25 and uav.spins["tile_size"].value() == 640
    uav.edits["input_dir"].setText(str(uav.images))
    assert "3 ảnh" in uav.count_label.text() and "tên file" in uav.count_label.text()
    uav.set_classes([])
    uav.run_btn.click()
    assert uav.errors[-1] == "Chưa chọn thư mục kết quả."
    uav.edits["output_dir"].setText(str(uav.images) + "_ketqua")
    uav.run_btn.click()
    assert uav.errors[-1] == "Hãy chọn ít nhất một loại đối tượng cần theo dõi."


def test_wheel_scrolls_the_panel_without_changing_parameters(uav, qtbot):
    from qgis.PyQt.QtCore import QPoint, QPointF
    from qgis.PyQt.QtGui import QWheelEvent
    from qgis.PyQt.QtWidgets import QApplication

    uav.resize(900, 400)  # the parameter panel needs a scroll bar
    uav.show()
    qtbot.waitExposed(uav)
    bar = uav.param_scroll.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum() // 2)
    start = bar.value()

    spin = uav.spins["conf"]
    for widget, value in ((spin, spin.value()), (uav.device_combo, uav.device_combo.currentText())):
        centre = QPointF(widget.rect().center())
        event = QWheelEvent(centre, QPointF(widget.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, -120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                            False)
        QApplication.sendEvent(widget, event)
        assert (widget.value() if widget is spin else widget.currentText()) == value
    assert bar.value() > start  # scrolled down instead


def test_run_shows_results_and_adds_tracks_to_map(uav, qtbot):
    from qgis.core import QgsProject

    out = str(uav.images) + "_ketqua"
    uav.edits["input_dir"].setText(str(uav.images))
    uav.edits["output_dir"].setText(out)
    uav.spins["conf"].setValue(0.3)
    uav.switches["no_tta"].setChecked(True)
    uav.switches["keep_static"].setChecked(True)
    uav.class_checks["person"].setChecked(True)
    uav.run_btn.click()
    assert not uav.run_btn.isEnabled() and uav.stop_btn.isEnabled()
    qtbot.waitUntil(lambda: uav.run_btn.isEnabled(), timeout=30000)

    args = uav.args()
    # Same command line as the Tkinter GUI built
    assert args[:6] == ["--input-dir", str(uav.images), "--output-dir", out, "--model", uav.edits["model"].text()]
    assert args[args.index("--conf") + 1] == "0.3" and args[args.index("--device") + 1] == "auto"
    assert "--no-tta" in args and "--keep-static" in args and "--no-sahi" not in args
    assert args[args.index("--classes") + 1] == "car,truck,bus,motorcycle,bicycle,person"

    assert uav.status_label.text() == "Hoàn thành ✔" and uav.progress.value() == 100
    assert [uav.image_list.item(i).text() for i in range(uav.image_list.count())] == [
        "★ Tổng hợp quỹ đạo", "DJI_0523_V", "DJI_0524_V"]
    assert uav.viewer._item is not None
    assert uav.track_table.rowCount() == 2
    headers = [uav.track_table.horizontalHeaderItem(c).text() for c in range(uav.track_table.columnCount())]
    row = {h: uav.track_table.item(0, c).text() for c, h in enumerate(headers)}
    assert row["ID"] == "1" and row["Hướng"] == "76° Đông (E)" and row["Trạng thái"] == "di chuyển"
    assert "Frame 2/2" in uav.log_edit.toPlainText()

    # "Thêm quỹ đạo lên bản đồ khi xong" is on by default: shapefiles + the UAV images (not the mask)
    group = QgsProject.instance().layerTreeRoot().findGroup("Quỹ đạo UAV - oto3_ketqua")
    assert group is not None and [n.name() for n in group.children()] == [
        "Đường đi phương tiện", "Điểm phương tiện", "Ảnh UAV"]
    tracks = QgsProject.instance().mapLayersByName("Đường đi phương tiện")[0]
    assert tracks.source().replace("\\", "/").endswith("shapefile/2_duong_di_phuong_tien.shp")
    assert tracks.featureCount() == 2
    images = group.findGroup("Ảnh UAV").children()
    assert [n.name() for n in images] == ["DJI_20260328162929_0524_V", "DJI_20260328162927_0523_V"]
    assert [n.itemVisibilityChecked() for n in images] == [True, False]  # only the latest shown
    points = QgsProject.instance().mapLayersByName("Điểm phương tiện")[0]
    assert points.labelsEnabled()
    # Shapefile fields of the fake run keep the GeoJSON names ("time", "avg_spd_k")
    assert points.labeling().settings().fieldName == "'#' || \"track_id\" || ' ' || left(\"time\", 12)"
    # One colour per vehicle, the colours of detect_and_draw.py's images (BGR there)
    import ast
    import colorsys

    from vgeoint.app.dialogs.uav_trajectory import track_color

    # detect_and_draw.py needs the ai packages: take only its track_color() function (the real script; the
    # fixture points the runner at the fake one)
    tree = ast.parse((ROOT / "src/vgeoint/ai/scripts/detect_and_draw.py").read_text(encoding="utf-8"))
    namespace = {"colorsys": colorsys}
    exec(compile(ast.Module([n for n in tree.body if getattr(n, "name", "") == "track_color"], []), "x", "exec"),
         namespace)
    image_color = namespace["track_color"]

    categories = tracks.renderer().categories()
    assert [c.label() for c in categories] == ["#1", "#2"]
    assert [c.symbol().color().name() for c in categories] == [track_color(1).name(), track_color(2).name()]
    assert track_color(1).name() != track_color(2).name()
    b, g, r = image_color(1)
    assert track_color(1).getRgb()[:3] == (r, g, b)
    assert [c.symbol().color().name() for c in points.renderer().categories()] == [track_color(1).name()]
    assert tracks.labelsEnabled()
    assert tracks.labeling().settings().fieldName == (
        "'#' || \"track_id\" || ' · ' || 'TB ' || format_number(\"avg_spd_k\", 1) || ' km/h'")

    # Settings are remembered for the next time
    from vgeoint.app.dialogs.uav_trajectory import load_settings

    assert load_settings()["conf"] == 0.3 and load_settings()["input_dir"] == str(uav.images)


def test_results_without_shapefile_use_geojson(uav, qtbot, monkeypatch):
    from qgis.core import QgsProject

    monkeypatch.setenv("UAV_MODE", "geojson-only")
    uav.edits["input_dir"].setText(str(uav.images))
    uav.edits["output_dir"].setText(str(uav.images) + "_ketqua")
    uav.run_btn.click()
    qtbot.waitUntil(lambda: uav.run_btn.isEnabled(), timeout=30000)
    tracks = QgsProject.instance().mapLayersByName("Đường đi phương tiện")[0]
    assert tracks.source().replace("\\", "/").split("|")[0].endswith("oto3_ketqua/tracks.geojson")


def test_failed_run(uav, qtbot, monkeypatch):
    monkeypatch.setenv("UAV_MODE", "--fail")
    uav.edits["input_dir"].setText(str(uav.images))
    uav.edits["output_dir"].setText(str(uav.images) + "_ketqua")
    uav.run_btn.click()
    qtbot.waitUntil(lambda: uav.run_btn.isEnabled(), timeout=30000)
    assert uav.status_label.text().startswith("Lỗi (mã 1)")
    assert "Không có ảnh hợp lệ" in uav.log_edit.toPlainText()


@pytest.mark.skipif(not AI_PYTHON.exists(), reason="ai environment not installed")
def test_real_script_parses_its_options():
    """The copied detect_and_draw.py runs in the ai environment (imports ultralytics/SAHI/rasterio)."""
    import subprocess

    from vgeoint.ai.runner import activated_environment, script_path

    env = activated_environment(str(AI_PYTHON))
    env["PYTHONPATH"] = str(ROOT / "src")
    out = subprocess.run([str(AI_PYTHON), str(script_path("detect_and_draw.py")), "--help"], capture_output=True,
                         text=True, encoding="utf-8", timeout=300, env=env)
    assert out.returncode == 0, out.stderr
    for option in ("--min-track-score-2w", "--keep-static", "--no-align", "--classes"):
        assert option in out.stdout
