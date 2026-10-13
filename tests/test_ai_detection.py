"""Ship/tank detection and building segmentation dialogs (fake scripts; real models with -m slow)."""

import sys
import textwrap
import time
from pathlib import Path

import pytest

from tests.conftest import make_raster

FAKE_DETECTION = textwrap.dedent(
    """
    import argparse, sys, time
    from osgeo import gdal, ogr, osr
    from vgeoint.ai.scripts._events import result
    p = argparse.ArgumentParser()
    for a in ("--input", "--model", "--output", "--confidence"):
        p.add_argument(a)
    args = p.parse_args()
    print("[OK] All Python dependencies loaded successfully")
    print(f"Loading model: {args.model}")
    print(f"Processing image: {args.input}")
    print(f"ARGS confidence={args.confidence}")
    if "{mode}" == "sleep":
        time.sleep(60)
    if "{mode}" == "fail":
        print("Error during detection: boom", file=sys.stderr)
        sys.exit(2)
    ds = gdal.Open(args.input)
    x0, dx, _, y0, _, dy = ds.GetGeoTransform()
    srs = osr.SpatialReference(wkt=ds.GetProjection())
    out = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(args.output)
    lyr = out.CreateLayer("det", srs, ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("confidence", ogr.OFTReal))
    for i in range({count}):
        x, y = x0 + (5 + 10 * i) * dx, y0 + 5 * dy
        ring = f"POLYGON(({x} {y},{x + 4 * dx} {y},{x + 4 * dx} {y + 4 * dy},{x} {y + 4 * dy},{x} {y}))"
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("confidence", 0.9)
        f.SetGeometry(ogr.CreateGeometryFromWkt(ring))
        lyr.CreateFeature(f)
    out = None
    print("[OK] Inference completed in 0.12 seconds")
    print("Total {what} detected: {count}")
    print(f"Shapefile created: {args.output}")
    result(output=args.output, count={count}, seconds=0.12, kind="shapefile")
    print("=== Process Finished ===")
    """
)

FAKE_SEGMENTATION = textwrap.dedent(
    """
    import argparse
    from osgeo import gdal
    from vgeoint.ai.scripts._events import result
    p = argparse.ArgumentParser()
    for a in ("--input", "--model", "--output"):
        p.add_argument(a)
    args = p.parse_args()
    print("Model loaded successfully on cpu")
    gdal.Translate(args.output, args.input)
    print("Building segmentation completed successfully!")
    result(output=args.output, seconds=0.34)
    """
)


def _install_fake(tmp_path, monkeypatch, name: str, code: str, models=("best.pt",)):
    from vgeoint.ai import runner

    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / name).write_text(code, encoding="utf-8")
    models_dir = tmp_path / "models"
    models_dir.mkdir(exist_ok=True)
    for m in models:
        (models_dir / m).write_bytes(b"fake")
    monkeypatch.setattr(runner, "SCRIPTS_DIR", scripts)
    monkeypatch.setattr(runner, "MODELS_DIR", models_dir)
    monkeypatch.setenv("VGEOINT_AI_PYTHON", sys.executable)


@pytest.fixture
def boxes(monkeypatch):
    """Record QMessageBox calls instead of showing them."""
    from qgis.PyQt.QtWidgets import QMessageBox

    calls = []
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, kind, lambda parent, title, text, *a, _k=kind: calls.append((_k, text)))
    return calls


def _add_raster(path, name="input"):
    from qgis.core import QgsProject, QgsRasterLayer

    layer = QgsRasterLayer(str(path), name, "gdal")
    assert layer.isValid()
    QgsProject.instance().addMapLayer(layer)
    return layer


def _layers_named(name):
    from qgis.core import QgsProject

    return QgsProject.instance().mapLayersByName(name)


def _log(dialog) -> str:
    return dialog.logTextEdit.toPlainText()


def _run(qtbot, dialog, timeout=30000):
    with qtbot.waitSignal(dialog.runner.finished, timeout=timeout) as blocker:
        dialog.okButton.click()
    return blocker.args


def _detection(kind, window):
    if kind == "ship":
        from vgeoint.app.dialogs.ship_detection import ShipDetectionDialog as cls
    else:
        from vgeoint.app.dialogs.tank_detection import TankDetectionDialog as cls
    return cls(window, window.map_canvas, window.layer_tree_view)


DETECTION_CASES = {
    #        script, model, word in fake output, output tag, Vietnamese object name
    "ship": ("ship_detection.py", "best.pt", "ships", "ships", "tàu thuyền"),
    "tank": ("tank_detection.py", "tank-detection-model.pt", "tanks", "tanks", "xe tăng"),
}


@pytest.mark.parametrize("kind", ["ship", "tank"])
def test_detection_success_loads_shapefile(qgis_app, qtbot, window, boxes, tmp_path, monkeypatch, kind):
    script, model, what, tag, vn = DETECTION_CASES[kind]
    _install_fake(tmp_path, monkeypatch, script, FAKE_DETECTION.replace("{mode}", "ok").replace("{what}", what).replace("{count}", "2"), (model,))
    raster = make_raster(tmp_path / "scene.tif", width=64, height=64)
    _add_raster(raster, "scene")

    dialog = _detection(kind, window)
    qtbot.addWidget(dialog)
    assert dialog.inputLayerComboBox.count() == 1
    assert dialog.outputPathLineEdit.text().endswith(f"/scene_{tag}.shp")
    assert dialog.outputTypeLabel.text() == "Đầu ra: Shapefile (.shp)"
    assert dialog.model_path.endswith(model)
    assert dialog.confidenceSpinBox.value() == 0.5
    dialog.confidenceSpinBox.setValue(0.35)
    completed = []
    dialog.complete.connect(lambda: completed.append(True))

    code, crashed = _run(qtbot, dialog)

    assert (code, crashed) == (0, False)
    log = _log(dialog)
    assert f"Phát hiện được 2 {vn}" in log  # count from the result event (C++ tank regex never matched)
    assert "Inference hoàn tất trong 0.12 giây" in log
    assert "Đã tạo Shapefile thành công" in log
    assert "Python: ARGS confidence=0.35" in log
    assert "🖼️ Đang xử lý ảnh đầu vào..." in log
    assert "✅ Đã tải tất cả thư viện Python" in log or "🔄 [OK] All Python dependencies" in log
    assert "Shapefile hợp lệ - 2 features" in log
    assert dialog.statusLabel.text() == "Hoàn thành thành công!"
    assert dialog.okButton.isEnabled() and dialog.browseOutputButton.isEnabled()
    assert dialog.progressBar.isHidden()
    assert completed == [True]
    assert dialog.output_files == [dialog.output_path]
    layers = _layers_named(f"scene_{tag}")
    assert len(layers) == 1 and layers[0].featureCount() == 2
    assert boxes and boxes[-1][0] == "information" and f"Phát hiện {vn} hoàn thành!" in boxes[-1][1]
    # MainController must not add a second copy through its auto-add hook.
    assert not hasattr(dialog, "auto_add_output_files")


def test_detection_auto_add_unchecked(qgis_app, qtbot, window, boxes, tmp_path, monkeypatch):
    _install_fake(tmp_path, monkeypatch, "ship_detection.py", FAKE_DETECTION.replace("{mode}", "ok").replace("{what}", "ships").replace("{count}", "1"))
    _add_raster(make_raster(tmp_path / "scene.tif"), "scene")
    dialog = _detection("ship", window)
    qtbot.addWidget(dialog)
    dialog.autoAddOutputCheckBox.setChecked(False)
    _run(qtbot, dialog)
    assert _layers_named("scene_ships") == []
    assert boxes[-1][0] == "information"


def test_tank_failure_and_error_text(qgis_app, qtbot, window, boxes, tmp_path, monkeypatch):
    _install_fake(tmp_path, monkeypatch, "tank_detection.py", FAKE_DETECTION.replace("{mode}", "fail").replace("{what}", "tanks").replace("{count}", "0"), ("tank-detection-model.pt",))
    _add_raster(make_raster(tmp_path / "scene.tif"), "scene")
    dialog = _detection("tank", window)
    qtbot.addWidget(dialog)

    code, _ = _run(qtbot, dialog)

    assert code == 2
    log = _log(dialog)
    assert "❌ Lỗi trong quá trình phát hiện: Error during detection: boom" in log
    assert "Mã thoát: 2" in log
    assert dialog.statusLabel.text() == "Xử lý thất bại!"
    assert boxes[-1][0] == "critical" and "Mã lỗi: 2" in boxes[-1][1]
    assert dialog.okButton.isEnabled()
    assert _layers_named("scene_tanks") == []


def test_tank_missing_script_mentions_tank_script(qgis_app, qtbot, window, boxes, tmp_path, monkeypatch):
    _install_fake(tmp_path, monkeypatch, "other.py", "", ("tank-detection-model.pt",))
    _add_raster(make_raster(tmp_path / "scene.tif"), "scene")
    dialog = _detection("tank", window)
    qtbot.addWidget(dialog)
    dialog.okButton.click()
    assert "Lỗi: Script Python không tồn tại!" in _log(dialog)
    assert boxes[-1][0] == "critical"
    assert "tank_detection.py" in boxes[-1][1] and "ship_detection.py" not in boxes[-1][1]
    assert dialog.okButton.isEnabled() and dialog.progressBar.isHidden()


def test_detection_validation(qgis_app, qtbot, window, boxes, tmp_path, monkeypatch):
    _install_fake(tmp_path, monkeypatch, "ship_detection.py", "", models=())
    dialog = _detection("ship", window)
    qtbot.addWidget(dialog)
    assert "Không tìm thấy layer raster nào" in _log(dialog)

    dialog.okButton.click()
    assert boxes[-1] == ("critical", "Vui lòng chọn layer đầu vào")
    dialog.browseOutputButton.click()
    assert boxes[-1] == ("warning", "Vui lòng chọn layer đầu vào trước")

    _add_raster(make_raster(tmp_path / "scene.tif"), "scene")
    dialog.update_layers_list()
    dialog.okButton.click()
    assert boxes[-1][0] == "critical" and boxes[-1][1].startswith("File mô hình không tồn tại: ")
    assert not dialog.runner.is_running()


def test_detection_cancel_kills_process(qgis_app, qtbot, window, boxes, tmp_path, monkeypatch):
    _install_fake(tmp_path, monkeypatch, "ship_detection.py", FAKE_DETECTION.replace("{mode}", "sleep").replace("{what}", "ships").replace("{count}", "0"))
    _add_raster(make_raster(tmp_path / "scene.tif"), "scene")
    dialog = _detection("ship", window)
    qtbot.addWidget(dialog)
    dialog.show()
    with qtbot.waitSignal(dialog.runner.started, timeout=20000):
        dialog.okButton.click()
    assert not dialog.okButton.isEnabled() and not dialog.progressBar.isHidden()
    qtbot.waitUntil(lambda: "Processing image" in _log(dialog) or "Đang xử lý ảnh" in _log(dialog), timeout=20000)

    dialog.cancelButton.click()

    assert not dialog.runner.is_running()
    assert "🛑 Đang dừng Python process..." in _log(dialog)
    assert boxes == []  # no crash/failure message for an abandoned run
    assert not dialog.isVisible()


def test_detection_regular_image_output(qgis_app, qtbot, window, tmp_path, monkeypatch):
    from qgis.PyQt.QtGui import QColor, QImage

    _install_fake(tmp_path, monkeypatch, "ship_detection.py", "")
    img = QImage(32, 32, QImage.Format.Format_RGB32)
    img.fill(QColor("blue"))
    img.save(str(tmp_path / "photo.png"))
    _add_raster(tmp_path / "photo.png", "photo")
    dialog = _detection("ship", window)
    qtbot.addWidget(dialog)
    assert dialog.outputPathLineEdit.text().endswith("/photo_ships_detected.jpg")
    assert dialog.outputTypeLabel.text() == "Đầu ra: Ảnh kết quả (.jpg)"


def test_detection_browse_and_save_log(qgis_app, qtbot, window, boxes, tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog

    from vgeoint.common.utils import settings

    _install_fake(tmp_path, monkeypatch, "tank_detection.py", "")
    _add_raster(make_raster(tmp_path / "scene.tif"), "scene")
    dialog = _detection("tank", window)
    qtbot.addWidget(dialog)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    requested = []

    def fake_save(parent, caption, directory, file_filter):
        requested.append((caption, directory, file_filter))
        return ((out_dir / ("res.shp" if file_filter.startswith("Shapefiles") else "log.txt")).as_posix(), "")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save)
    dialog.browseOutputButton.click()
    assert dialog.output_path.endswith("out/res.shp") and dialog.outputPathLineEdit.text() == dialog.output_path
    assert requested[-1][0] == "Lưu kết quả" and requested[-1][2] == "Shapefiles (*.shp)"
    assert settings().value("TankDetection/OutputDir") == out_dir.as_posix()

    dialog.saveLogButton.click()
    text = (out_dir / "log.txt").read_text(encoding="utf-8")
    assert text.startswith("=== vGeoInt_v2 Tank Detection Log ===\n")
    assert "Hệ thống phát hiện xe tăng đã sẵn sàng" in text
    assert "tank_detection_log_" in requested[-1][1]
    assert settings().value("TankDetection/LogDir") == out_dir.as_posix()
    settings().remove("TankDetection")

    dialog.clearLogButton.click()
    assert "Log đã được xóa" in _log(dialog) and "sẵn sàng" not in _log(dialog)


def _building(window):
    from vgeoint.app.dialogs.building_segmentation import BuildingSegmentationDialog

    return BuildingSegmentationDialog(window, window.map_canvas, window.layer_tree_view)


def test_building_segmentation_success(qgis_app, qtbot, window, boxes, tmp_path, monkeypatch):
    _install_fake(tmp_path, monkeypatch, "building_segmentation.py", FAKE_SEGMENTATION, ("building_unet.pth",))
    _add_raster(make_raster(tmp_path / "city.tif"), "city")
    dialog = _building(window)
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Phân đoạn tòa nhà từ ảnh vệ tinh"
    assert dialog.modelComboBox.currentText() == "UNet for Building Segmentation"
    expected = "_buildings.tif" if "geo" in str(tmp_path).lower() else "_buildings_mask.tif"
    assert dialog.outputLineEdit.text().endswith("/city" + expected)
    dialog.autoAddOutputCheckBox.setChecked(False)  # ignored, as in the C++ dialog

    code, _ = _run(qtbot, dialog)

    assert code == 0
    log = _log(dialog)
    assert "✅ Mô hình UNet đã được tải thành công" in log
    assert "✅ Phân đoạn tòa nhà hoàn tất!" in log
    assert "⚡ Inference hoàn tất trong 0.34 giây" in log
    assert "🎯 Đã tạo mặt nạ phân đoạn thành công" in log
    assert " MB)" in log and "%.2f" not in log
    assert "Mặt nạ phân đoạn hợp lệ - 64x48 pixels" in log
    assert dialog.statusLabel.text() == "Xử lý hoàn tất!"
    layer_name = "city" + expected[:-4]
    assert len(_layers_named(layer_name)) == 1
    assert boxes[-1][0] == "information" and "Phân đoạn tòa nhà hoàn thành!" in boxes[-1][1]


def test_building_missing_script(qgis_app, qtbot, window, boxes, tmp_path, monkeypatch):
    _install_fake(tmp_path, monkeypatch, "other.py", "", ("building_unet.pth",))
    _add_raster(make_raster(tmp_path / "city.tif"), "city")
    dialog = _building(window)
    qtbot.addWidget(dialog)
    dialog.okButton.click()
    assert dialog.statusLabel.text() == "Lỗi xử lý"
    assert "building_segmentation.py" in boxes[-1][1]


# --------------------------------------------------------------------------- real models
def _real_env(monkeypatch):
    from vgeoint.common.paths import MODELS_DIR, ROOT

    if not (ROOT / ".pixi" / "envs" / "ai").exists():
        pytest.skip("ai environment not installed")
    monkeypatch.delenv("VGEOINT_AI_PYTHON", raising=False)
    return MODELS_DIR


def _real_run(qtbot, dialog, model):
    if not (dialog.model_path and Path(dialog.model_path).exists()):
        pytest.skip(f"model {model} not available")
    events = []
    dialog.runner.event_received.connect(events.append)
    start = time.monotonic()
    code, crashed = _run(qtbot, dialog, timeout=900000)
    elapsed = time.monotonic() - start
    print(f"\n{type(dialog).__name__}: real run {elapsed:.1f}s, events={events}")
    assert (code, crashed) == (0, False), _log(dialog)
    assert any(e.get("type") == "result" for e in events), _log(dialog)
    return events


@pytest.mark.slow
@pytest.mark.parametrize("kind", ["ship", "tank"])
def test_real_detection(qgis_app, qtbot, window, no_modal, tmp_path, monkeypatch, kind):
    _real_env(monkeypatch)
    _, model, _, tag, _ = DETECTION_CASES[kind]
    _add_raster(make_raster(tmp_path / "crop.tif", width=256, height=256), "crop")
    dialog = _detection(kind, window)
    qtbot.addWidget(dialog)
    _real_run(qtbot, dialog, model)
    layers = _layers_named(f"crop_{tag}")
    assert len(layers) == 1 and layers[0].isValid(), _log(dialog)


@pytest.mark.slow
def test_real_building_segmentation(qgis_app, qtbot, window, no_modal, tmp_path, monkeypatch):
    _real_env(monkeypatch)
    _add_raster(make_raster(tmp_path / "crop.tif", width=256, height=256), "crop")
    dialog = _building(window)
    qtbot.addWidget(dialog)
    events = _real_run(qtbot, dialog, "building_unet.pth")
    assert events[-1]["output"] == dialog.output_path
    layers = _layers_named(Path(dialog.output_path).stem)
    assert len(layers) == 1 and layers[0].width() == 256, _log(dialog)
