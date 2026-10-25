"""Phát hiện quỹ đạo bằng ảnh vệ tinh: the shiptrack code of D:/detectship behind a dialog."""

import json
import sys
import textwrap

import pytest

from vgeoint.common.paths import ROOT

AI_PYTHON = ROOT / ".pixi" / "envs" / "ai" / "python.exe"
SCRIPTS = ROOT / "src" / "vgeoint" / "ai" / "scripts" / "shiptrack"

# Writes the outputs of run_pipeline.py (overview, quicklooks, shapefiles) and records its arguments.
FAKE_PIPELINE = textwrap.dedent('''
    import json, os, sys
    from osgeo import gdal
    from vgeoint.ai.scripts._events import progress, result
    args = sys.argv[1:]
    out = args[args.index("--output-dir") + 1]
    json.dump(args, open(os.environ["SAT_ARGS_FILE"], "w"))
    os.makedirs(os.path.join(out, "shapefile"), exist_ok=True)
    print("Cảnh 1/2: 20260404_031749_59_251f_3B_AnalyticMS_8b.tif ...", flush=True)
    progress(50, "Cảnh 2/2")
    for name in ("tracks_overview.png", "20260404_031749_59_251f_quicklook.jpg", "20260415_032035_76_251f_quicklook.jpg"):
        driver = "PNG" if name.endswith("png") else "JPEG"
        gdal.GetDriverByName(driver).CreateCopy(os.path.join(out, name), gdal.GetDriverByName("MEM").Create("", 40, 30, 3))
    def write(name, features):
        path = os.path.join(out, name + ".geojson")
        json.dump({"type": "FeatureCollection", "features": features}, open(path, "w", encoding="utf-8"))
        gdal.VectorTranslate(os.path.join(out, "shapefile", name + ".shp"), path, format="ESRI Shapefile")
    write("tracks_lines", [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[115.40, 5.20], [115.401, 5.201]]},
                            "properties": {"track": 3, "n_obs": 2, "dates": "2026-04-04,2026-04-15", "first": "2026-04-04",
                                           "last": "2026-04-15", "dist_m": 140.2, "bearing": 45.0, "length_m": 288.0}}])
    write("ships_points", [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [115.40, 5.20]},
                            "properties": {"track": 3, "date": "2026-04-04"}},
                           {"type": "Feature", "geometry": {"type": "Point", "coordinates": [115.5, 5.1]},
                            "properties": {"track": 7, "date": "2026-04-15"}}])
    write("ships_boxes", [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[115.40, 5.20], [115.401, 5.20], [115.401, 5.201], [115.40, 5.20]]]},
                           "properties": {"track": 3}}])
    print("[OK] Xong trong 1.0 s", flush=True)
    result(output_dir=out)
''')


@pytest.fixture
def sat(window, tmp_path, monkeypatch):
    from vgeoint.ai import runner
    from vgeoint.app.dialogs.satellite_trajectory import SETTINGS_KEY, SatelliteTrajectoryDialog
    from vgeoint.common.utils import settings
    from tests.conftest import make_raster

    settings().remove(SETTINGS_KEY)
    scripts = tmp_path / "scripts"
    (scripts / "shiptrack").mkdir(parents=True)
    (scripts / "shiptrack" / "run_pipeline.py").write_text(FAKE_PIPELINE, encoding="utf-8")
    monkeypatch.setattr(runner, "SCRIPTS_DIR", scripts)
    monkeypatch.setenv("VGEOINT_AI_PYTHON", sys.executable)
    args_file = tmp_path / "sat_args.json"
    monkeypatch.setenv("SAT_ARGS_FILE", str(args_file))

    scenes = tmp_path / "planet"
    scenes.mkdir()
    for i, name in enumerate(("20260404_031749_59_251f_3B_AnalyticMS_8b.tif", "20260415_032035_76_251f_3B_AnalyticMS_8b.tif")):
        make_raster(scenes / name, bands=8, seed=i)
    (scenes / "20260404_031749_59_251f_metadata.json").write_text("{}")
    weights = tmp_path / "ship_obb_v2.pt"
    weights.write_bytes(b"")
    dlg = SatelliteTrajectoryDialog(window, window.map_canvas, window.layer_tree_view)
    dlg.edits["weights"].setText(str(weights))
    dlg.scenes = scenes
    dlg.args = lambda: json.loads(args_file.read_text())
    dlg.errors = []
    monkeypatch.setattr("qgis.PyQt.QtWidgets.QMessageBox.critical", lambda *a: dlg.errors.append(a[2]))
    yield dlg
    dlg.close()


def test_menu_has_both_trajectory_items(window):
    from vgeoint.app.dialogs.satellite_trajectory import SatelliteTrajectoryDialog

    mb = window.menu_bar_
    assert [a.text() for a in mb.trajectory_menu.actions()] == [
        "Phát hiện quỹ đạo trên ảnh UAV...", "Phát hiện quỹ đạo bằng ảnh vệ tinh..."]
    mb.satellite_trajectory_act.trigger()
    dialogs = window.findChildren(SatelliteTrajectoryDialog)
    assert dialogs and dialogs[-1].isVisible() and not dialogs[-1].isModal()
    dialogs[-1].close()


def test_scenes_and_validation(sat):
    sat.edits["input_dir"].setText(str(sat.scenes))
    assert "2 cảnh" in sat.count_label.text()  # the metadata.json is not a scene
    sat.run_btn.click()
    assert sat.errors[-1] == "Chưa chọn thư mục kết quả."
    sat.method_combo.setCurrentIndex(1)  # CFAR: no model needed
    assert not sat.edits["weights"].isEnabled() and sat.spins["k"].isEnabled() and not sat.spins["conf"].isEnabled()


@pytest.mark.parametrize("method", ["yolo", "cfar"])
def test_run_shows_results_and_adds_them_to_the_map(sat, qtbot, method):
    from qgis.core import QgsProject

    out = str(sat.scenes) + "_tau"
    sat.edits["input_dir"].setText(str(sat.scenes))
    sat.edits["output_dir"].setText(out)
    sat.method_combo.setCurrentIndex(0 if method == "yolo" else 1)
    sat.spins["gate_m"].setValue(1000)
    sat.run_btn.click()
    qtbot.waitUntil(lambda: sat.run_btn.isEnabled(), timeout=30000)

    args = sat.args()
    assert args[:6] == ["--input-dir", str(sat.scenes), "--output-dir", out, "--method", method]
    assert args[args.index("--gate-m") + 1] == "1000.0"
    if method == "yolo":
        assert args[args.index("--weights") + 1] == sat.edits["weights"].text() and "--k" not in args
    else:
        assert "--weights" not in args and args[args.index("--k") + 1] == "6.0"

    assert sat.status_label.text() == "Hoàn thành ✔" and sat.progress.value() == 100
    assert [sat.image_list.item(i).text() for i in range(sat.image_list.count())] == [
        "★ Bản đồ tổng quan quỹ đạo", "20260404_031749_59_251f", "20260415_032035_76_251f"]
    assert sat.track_table.rowCount() == 1 and sat.track_table.item(0, 3).text() == "140.2"

    group = QgsProject.instance().layerTreeRoot().findGroup("Quỹ đạo tàu - planet_tau")
    assert [n.name() for n in group.children()] == [
        "Quỹ đạo tàu (≥ 2 ngày)", "Vị trí tàu", "Khung thân tàu", "Ảnh vệ tinh"]
    points = QgsProject.instance().mapLayersByName("Vị trí tàu")[0]
    assert [c.label() for c in points.renderer().categories()] == ["#3", "#7"]  # one colour per ship
    assert "substr(\"date\", 9, 2)" in points.labeling().settings().fieldName
    scenes = group.findGroup("Ảnh vệ tinh").children()
    assert [n.itemVisibilityChecked() for n in scenes] == [True, False]
    assert scenes[0].layer().renderer().redBand() == 6  # true colour: red, green, blue of SuperDove


def test_copied_code_is_complete():
    """All the shiptrack scripts are there, unchanged except run_pipeline.py (added)."""
    names = {p.name for p in SCRIPTS.glob("*.py")}
    assert names == {"build_dataset.py", "detect_ships.py", "export_shapefile.py", "link_tracks.py",
                     "make_labels.py", "plot_tracks.py", "predict_scene.py", "review_predictions.py",
                     "train_obb.py", "run_pipeline.py"}


@pytest.mark.skipif(not AI_PYTHON.exists(), reason="ai environment not installed")
def test_real_pipeline_parses_its_options():
    import subprocess

    from vgeoint.ai.runner import activated_environment

    env = activated_environment(str(AI_PYTHON))
    env["PYTHONPATH"] = str(ROOT / "src")
    out = subprocess.run([str(AI_PYTHON), str(SCRIPTS / "run_pipeline.py"), "--help"], capture_output=True,
                         text=True, encoding="utf-8", timeout=300, env=env)
    assert out.returncode == 0, out.stderr
    for option in ("--method", "--weights", "--gate-m", "--moving-m"):
        assert option in out.stdout
