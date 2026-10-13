"""AutoClassification, MotionDetection, ImageBlending and GoogleEarthEngine dialogs.

Fast tests run fake scripts with the test interpreter; `pytest -m slow` runs the real scripts in the ai
environment (Random Forest model, Orfeo Toolbox).
"""

import json
import os
import sys
import textwrap
import time
from pathlib import Path

import numpy as np
import pytest
from osgeo import gdal

from tests.conftest import make_raster

AI_PYTHON = Path(__file__).resolve().parents[1] / ".pixi" / "envs" / "ai" / "python.exe"
OTB_LAUNCHER = Path(r"C:\OTB-9.1.0-Win64\bin\otbcli_Pansharpening.bat")

# Shared helpers available to every fake script.
FAKE_HEADER = textwrap.dedent(
    """
    import argparse, json, os, sys, time
    import numpy as np
    from osgeo import gdal
    from vgeoint.ai.scripts._events import progress, result

    def read(path, band=1):
        ds = gdal.Open(path)
        return ds.GetRasterBand(band).ReadAsArray()

    def write(path, arrays, gdal_type=gdal.GDT_Byte, colors=None):
        h, w = arrays[0].shape
        ds = gdal.GetDriverByName("GTiff").Create(path, w, h, len(arrays), gdal_type)
        ds.SetGeoTransform((500000, 10, 0, 2300000, 0, -10))
        for i, a in enumerate(arrays, 1):
            ds.GetRasterBand(i).WriteArray(a)
        if colors:
            ct = gdal.ColorTable()
            for value, rgba in colors.items():
                ct.SetColorEntry(value, rgba)
            ds.GetRasterBand(1).SetRasterColorTable(ct)
        ds = None
    """
)


@pytest.fixture
def fake_scripts(tmp_path, monkeypatch):
    """Return write(name, body): installs a fake script run by the test interpreter."""
    from vgeoint.ai import runner

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    monkeypatch.setattr(runner, "SCRIPTS_DIR", scripts)
    monkeypatch.setenv("VGEOINT_AI_PYTHON", sys.executable)

    def write(name: str, body: str):
        (scripts / name).write_text(FAKE_HEADER + textwrap.dedent(body), encoding="utf-8")

    return write


@pytest.fixture
def boxes(monkeypatch):
    """Record QMessageBox static calls and QMessageBox.exec() instead of blocking."""
    from qgis.PyQt.QtWidgets import QMessageBox

    calls = []
    Btn = QMessageBox.StandardButton
    for name in ("question", "warning", "information", "critical"):
        monkeypatch.setattr(
            QMessageBox, name, lambda *a, _n=name, **k: (calls.append((_n, a[1], a[2])), Btn.Ok)[1]
        )
    monkeypatch.setattr(QMessageBox, "exec", lambda self: calls.append(("exec", self.text(), self.detailedText())))
    return calls


def add_raster(window, path):
    """Add a raster and let the layer tree bridge update the canvas layers (deferred)."""
    from qgis.PyQt.QtWidgets import QApplication

    window.main_controller.add_raster(path)
    QApplication.processEvents()


def layer_names():
    from qgis.core import QgsProject

    return sorted(l.name() for l in QgsProject.instance().mapLayers().values())


def s2_raster(path, seed=0, width=48, height=32):
    """10-band UInt16 raster with Sentinel-2 like reflectances (the Random Forest expects 10 features)."""
    ds = gdal.GetDriverByName("GTiff").Create(str(path), width, height, 10, gdal.GDT_UInt16)
    ds.SetGeoTransform((500000, 10, 0, 2300000, 0, -10))
    from osgeo import osr

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32648)
    ds.SetProjection(srs.ExportToWkt())
    rng = np.random.default_rng(seed)
    for b in range(1, 11):
        ds.GetRasterBand(b).WriteArray(rng.integers(100, 4000, size=(height, width)).astype(np.uint16))
    ds = None
    return str(path)


# ======================================================================= AutoClassification
FAKE_AUTO_CLASSIFICATION = """
p = argparse.ArgumentParser()
p.add_argument("--input"); p.add_argument("--model"); p.add_argument("--output")
p.add_argument("--colored", action="store_true")
a = p.parse_args()
if open(a.model).read() == "fail":
    print("Lỗi: mô hình hỏng", file=sys.stderr)
    sys.exit(1)
if open(a.model).read() == "slow":
    time.sleep(30)
print("[OK] Mô hình đã được tải thành công từ: " + a.model)
print("Kích thước ảnh: 48x64 với 3 kênh.")
print("WARNING: giả lập")
src = read(a.input)
classes = (src % 4 + 1).astype(np.float32)
write(a.output, [classes], gdal.GDT_Float32)
print("[OK] Kết quả phân loại đã được lưu tại: " + a.output)
colored = None
if a.colored:
    colored = a.output.replace(".tif", "_unique_values.tif")
    write(colored, [classes.astype(np.uint8)], colors={1: (180, 0, 0, 255), 2: (0, 180, 0, 255)})
    print("1: Dân cư (Đỏ nhạt)")
result(output=os.path.abspath(a.output), colored=os.path.abspath(colored) if colored else None)
"""


def _auto_classification(window):
    from vgeoint.app.dialogs.auto_classification import AutoClassificationDialog

    return AutoClassificationDialog(window, window.map_canvas, window.layer_tree_view)


def _log(dlg_text_edit):
    return dlg_text_edit.toPlainText()


def test_auto_classification_ui(window, tmp_path, boxes):
    dlg = _auto_classification(window)
    assert dlg.windowTitle() == "Phân loại tự động"
    assert dlg.modelComboBox.currentText() == "Random Forest"
    assert dlg.get_model_path().endswith("random_forest_model_s2.joblib")
    assert not dlg.okButton.isEnabled()
    assert "[CẢNH BÁO] Không tìm thấy layer ảnh nào trong dự án" in _log(dlg.logTextEdit)
    assert not hasattr(dlg, "complete")  # results are added by the dialog itself

    add_raster(window, make_raster(tmp_path / "scene.tif"))
    dlg = _auto_classification(window)
    log = _log(dlg.logTextEdit)
    assert "[HỆ THỐNG] Hệ thống phân loại tự động đã sẵn sàng" in log
    assert "Đã chọn layer: scene" in log and "Đã tìm thấy 1 layer ảnh" in log
    assert dlg.okButton.isEnabled()
    assert Path(dlg.outputPathLineEdit.text()) == tmp_path / "scene_classified.tif"

    dlg.model_path = str(tmp_path / "missing.joblib")
    dlg.apply()
    assert boxes[-1] == ("warning", "Cảnh báo", "Vui lòng chọn một mô hình Random Forest hợp lệ")

    dlg.clearLogButton.click()
    assert _log(dlg.logTextEdit) == "[HỆ THỐNG] Đã xóa log"


def _run_auto(dlg, qtbot, timeout=20000):
    dlg.apply()
    qtbot.waitUntil(lambda: dlg._runner is not None and not dlg._runner.is_running() and dlg.okButton.isEnabled(),
                    timeout=timeout)


def test_auto_classification_run(window, tmp_path, fake_scripts, boxes, qtbot):
    fake_scripts("auto_classification.py", FAKE_AUTO_CLASSIFICATION)
    add_raster(window, make_raster(tmp_path / "scene.tif"))
    dlg = _auto_classification(window)
    model = tmp_path / "m.joblib"
    model.write_text("ok")
    dlg.model_path = str(model)

    _run_auto(dlg, qtbot)

    log = _log(dlg.logTextEdit)
    assert "=== BẮT ĐẦU QUÁ TRÌNH PHÂN LOẠI ===" in log
    assert "[XỬ LÝ] Đã khởi động quá trình phân loại" in log
    assert "[THÀNH CÔNG] ✅ Đã tải mô hình Random Forest" not in log  # "[OK] ..." does not start with it
    assert "[THÔNG TIN] ℹ️ Kích thước ảnh: 48x64 với 3 kênh." in log
    assert "[CẢNH BÁO] WARNING: giả lập" in log
    assert "[THÀNH CÔNG] 💾 Đã lưu kết quả phân loại" in log
    assert "[KẾT QUẢ] 🏷️ 1: Dân cư (Đỏ nhạt)" in log
    assert "=== QUÁ TRÌNH PHÂN LOẠI HOÀN TẤT ===" in log
    assert dlg.statusLabel.text() == "Hoàn tất"
    assert dlg.progressBar.isHidden()
    assert boxes[-1] == ("information", "Thành công", "Quá trình phân loại đã hoàn tất thành công!")
    assert "scene_classified" in layer_names() and "scene_classified_unique_values" in layer_names()
    assert dlg.output_files == [
        str(tmp_path / "scene_classified.tif"),
        str(tmp_path / "scene_classified_unique_values.tif"),
    ]


def test_auto_classification_without_auto_add(window, tmp_path, fake_scripts, boxes, qtbot):
    fake_scripts("auto_classification.py", FAKE_AUTO_CLASSIFICATION)
    add_raster(window, make_raster(tmp_path / "scene.tif"))
    dlg = _auto_classification(window)
    (tmp_path / "m.joblib").write_text("ok")
    dlg.model_path = str(tmp_path / "m.joblib")
    dlg.autoAddOutputCheckBox.setChecked(False)
    _run_auto(dlg, qtbot)
    assert (tmp_path / "scene_classified.tif").exists()
    assert not (tmp_path / "scene_classified_unique_values.tif").exists()  # no --colored
    assert layer_names() == ["scene"]


def test_auto_classification_failure_and_cancel(window, tmp_path, fake_scripts, boxes, qtbot):
    fake_scripts("auto_classification.py", FAKE_AUTO_CLASSIFICATION)
    add_raster(window, make_raster(tmp_path / "scene.tif"))
    dlg = _auto_classification(window)
    model = tmp_path / "m.joblib"
    model.write_text("fail")
    dlg.model_path = str(model)
    _run_auto(dlg, qtbot)
    log = _log(dlg.logTextEdit)
    assert "[LỖI] Lỗi: mô hình hỏng" in log  # stderr is shown (the C++ dialog dropped it)
    assert "=== QUÁ TRÌNH PHÂN LOẠI THẤT BẠI ===" in log
    assert dlg.statusLabel.text() == "Lỗi"
    assert boxes[-1][0] == "critical"

    model.write_text("slow")
    dlg.apply()
    qtbot.waitUntil(lambda: dlg._started, timeout=20000)
    assert not dlg.okButton.isEnabled()
    dlg.apply()  # still running
    assert boxes[-1] == ("warning", "Cảnh báo", "Quá trình xử lý đang chạy. Vui lòng đợi hoặc hủy quá trình hiện tại.")
    dlg.reject()
    assert not dlg._runner.is_running()


def test_auto_classification_python_missing(window, tmp_path, fake_scripts, boxes, qtbot, monkeypatch):
    monkeypatch.setenv("VGEOINT_AI_PYTHON", str(tmp_path / "nope" / "python.exe"))
    add_raster(window, make_raster(tmp_path / "scene.tif"))
    dlg = _auto_classification(window)
    (tmp_path / "m.joblib").write_text("ok")
    dlg.model_path = str(tmp_path / "m.joblib")
    _run_auto(dlg, qtbot)
    assert "❌ Lỗi khởi động Python process" in _log(dlg.logTextEdit)
    assert dlg.statusLabel.text() == "Xử lý thất bại!"
    assert boxes[-1][0] == "critical" and boxes[-1][2].startswith("Không thể khởi động quá trình Python")


# ======================================================================= MotionDetection
FAKE_MOTION = """
p = argparse.ArgumentParser()
for k in ("--before", "--after", "--output", "--model"):
    p.add_argument(k)
for k in ("--stats", "--summary", "--visualize"):
    p.add_argument(k, action="store_true")
a = p.parse_args()
json.dump(sys.argv[1:], open(a.output + ".args.json", "w"))
if "fail" in a.output:
    print("*** LOI: hỏng")
    print("Traceback: boom", file=sys.stderr)
    sys.exit(1)
before = read(a.before) % 4 + 1
after = read(a.after) % 4 + 1
change = (before * 10 + after).astype(np.uint8)
colored = a.output.replace(".tif", "_colored_unique_values.tif")
write(colored, [change], colors={11: (128, 128, 128, 255), 12: (144, 238, 144, 255)})
combined = colored.replace(".tif", "_with_legend.tif")
write(combined, [change, change, change])
stats = a.output.replace(".tif", "_statistics.csv")
open(stats, "w", encoding="utf-8-sig").write("Mã thay đổi,Số pixel\\n11,5\\n")
print(f"COLORED_OUTPUT_PATH: {colored}")
result(output=a.output, colored=colored, combined=combined, statistics=stats)
"""


@pytest.fixture
def motion_inputs(window, tmp_path):
    a = make_raster(tmp_path / "before.tif", seed=1)
    b = make_raster(tmp_path / "after.tif", seed=2)
    add_raster(window, a)
    add_raster(window, b)
    return a, b


def _motion(window):
    from vgeoint.app.dialogs.motion_detection import MotionDetectionDialog

    return MotionDetectionDialog(window, window.map_canvas, window.layer_tree_view)


def test_motion_detection_validation(window, motion_inputs, tmp_path, boxes, monkeypatch):
    from vgeoint.app.dialogs import motion_detection

    dlg = _motion(window)
    assert dlg.windowTitle().startswith("Phát hiện thay đổi lớp phủ mặt đất AI/ML")
    assert sorted(dlg.beforeRasterLayerCbx.itemText(i) for i in range(2)) == ["after", "before"]
    assert not hasattr(dlg, "complete")

    dlg.beforeRasterLayerCbx.setCurrentIndex(0)
    dlg.afterRasterLayerCbx.setCurrentIndex(0)
    dlg.aiProcessBtn.click()
    assert "Ảnh trước và sau phải khác nhau" in dlg.noticeLbl.text()

    dlg.afterRasterLayerCbx.setCurrentIndex(1)
    dlg.aiProcessBtn.click()
    assert "Chưa chọn đường dẫn lưu kết quả" in dlg.noticeLbl.text()

    dlg.outputLedr.setText(str(tmp_path / "out.tif"))
    monkeypatch.setattr(motion_detection, "model_path", lambda rel: tmp_path / "missing.joblib")
    dlg.aiProcessBtn.click()
    assert "KHÔNG TÌM THẤY MÔ HÌNH! models/random_forest_model_s2.joblib" in dlg.noticeLbl.text()
    assert boxes[-1][0] == "warning" and boxes[-1][1] == "Mô hình không tồn tại"
    assert str(tmp_path / "missing.joblib") in boxes[-1][2]


def _run_motion(dlg, qtbot, output, timeout=20000):
    dlg.beforeRasterLayerCbx.setCurrentIndex(dlg.beforeRasterLayerCbx.findText("before"))
    dlg.afterRasterLayerCbx.setCurrentIndex(dlg.afterRasterLayerCbx.findText("after"))
    dlg.outputLedr.setText(str(output))
    dlg.aiProcessBtn.click()  # a missing interpreter fails synchronously, otherwise the notice says "running"
    qtbot.waitUntil(lambda: dlg.noticeLbl.text() != "Đang chạy ML phát hiện thay đổi lớp phủ...", timeout=timeout)


def test_motion_detection_run(window, motion_inputs, tmp_path, fake_scripts, boxes, qtbot, monkeypatch):
    from vgeoint.app.dialogs import motion_detection

    fake_scripts("ai_motion_detection.py", FAKE_MOTION)
    model = tmp_path / "rf.joblib"
    model.write_text("x")
    monkeypatch.setattr(motion_detection, "model_path", lambda rel: model)
    dlg = _motion(window)
    out = tmp_path / "out.tif"
    noticed = []
    orig = dlg.noticeLbl.setText
    monkeypatch.setattr(dlg.noticeLbl, "setText", lambda t: (noticed.append(t), orig(t)))
    _run_motion(dlg, qtbot, out)
    assert noticed[0] == "Đang chạy ML phát hiện thay đổi lớp phủ..."

    assert "AI phát hiện thay đổi hoàn tất thành công!" in dlg.noticeLbl.text()
    args = json.loads(Path(str(out) + ".args.json").read_text())
    assert args == [
        "--before", motion_inputs[0], "--after", motion_inputs[1], "--output", str(out), "--model", str(model),
        "--stats", "--summary", "--visualize",
    ]
    assert dlg.colored_output_path == str(tmp_path / "out_colored_unique_values.tif")
    assert dlg.output_files == [
        str(out), str(tmp_path / "out_statistics.csv"), str(tmp_path / "out_colored_unique_values.tif")
    ]
    assert ("exec", "Thống kê thay đổi lớp phủ mặt đất (AI):", "Mã thay đổi,Số pixel\n11,5\n") in boxes
    names = layer_names()
    assert "Change Detection (Colored) - out_colored_unique_values" in names
    assert "out_colored_unique_values_with_legend (With Legend)" in names
    assert not any(n.startswith("Change Detection - ") for n in names)  # main output is never written


def test_motion_detection_failure(window, motion_inputs, tmp_path, fake_scripts, boxes, qtbot, monkeypatch):
    from vgeoint.app.dialogs import motion_detection

    fake_scripts("ai_motion_detection.py", FAKE_MOTION)
    (tmp_path / "rf.joblib").write_text("x")
    monkeypatch.setattr(motion_detection, "model_path", lambda rel: tmp_path / "rf.joblib")
    dlg = _motion(window)
    _run_motion(dlg, qtbot, tmp_path / "fail.tif")
    assert dlg.noticeLbl.text() == "<font color='red'>Lỗi Python: Traceback: boom</font>"
    assert layer_names() == ["after", "before"]

    monkeypatch.setenv("VGEOINT_AI_PYTHON", str(tmp_path / "nope.exe"))
    _run_motion(dlg, qtbot, tmp_path / "out.tif")
    assert "Không thể khởi động Python" in dlg.noticeLbl.text()


# ======================================================================= ImageBlending
FAKE_PANSHARPENING = """
pan, ms, out, method = sys.argv[1:5]
print("=== Starting Pansharpening ===")
print(f"Method: {method}")
json.dump(sys.argv[1:], open(out + ".args.json", "w"))
if "fail" in out:
    print("OTB error", file=sys.stderr)
    sys.exit(1)
src = gdal.Open(ms)
write(out, [src.GetRasterBand(i).ReadAsArray() for i in range(1, src.RasterCount + 1)])
print("✓ Pansharpening completed successfully!")
result(output=os.path.abspath(out))
"""


def _blending(window):
    from vgeoint.app.dialogs.image_blending import ImageBlendingDialog

    return ImageBlendingDialog(window)


def test_image_blending_ui(window, tmp_path, boxes):
    add_raster(window, make_raster(tmp_path / "pan.tif", bands=1))
    add_raster(window, make_raster(tmp_path / "ms.tif", bands=4))
    dlg = _blending(window)
    assert dlg.windowTitle() == "Trộn ảnh - Pansharpening"
    assert dlg.minimumSize().width() == 800
    assert sorted(dlg.pan_layer_combo.itemText(i) for i in range(dlg.pan_layer_combo.count())) == ["ms", "pan"]
    assert dlg.output_path_edit.text().endswith("/pansharpening_output.tif")
    assert dlg.pan_image_edit.isHidden() and not dlg.pan_layer_combo.isHidden()
    assert not dlg.radius_x_spin.isHidden() and dlg.lambda_spin.isHidden()
    assert dlg.radius_x_spin.value() == 9

    dlg.lmvm_radio.click()
    assert dlg.radius_x_spin.value() == 3 and dlg.radius_y_spin.value() == 3
    dlg.bayes_radio.click()
    assert dlg.radius_x_spin.isHidden() and not dlg.lambda_spin.isHidden() and not dlg.s_spin.isHidden()
    dlg.output_path_edit.setText(str(tmp_path / "o.tif"))
    args = dlg.build_command_arguments()
    assert args[2:] == [str(tmp_path / "o.tif"), "bayes", "lambda_weight", "0.9999", "s", "1.00"]

    dlg.reset_btn.click()
    assert dlg.rcs_radio.isChecked() and dlg.radius_x_spin.value() == 9
    assert dlg.output_path_edit.text().endswith("/pansharpening_output.tif")
    assert dlg.log_output.toPlainText().endswith("Đã đặt lại tham số về giá trị mặc định.")

    dlg.use_layer_input.setChecked(False)
    assert not dlg.pan_image_edit.isHidden() and dlg.pan_layer_combo.isHidden()
    dlg.process_btn.click()
    assert boxes[-1] == ("warning", "Lỗi", "Vui lòng chọn ảnh toàn sắc và ảnh đa phổ.")
    dlg.pan_image_edit.setText(str(tmp_path / "x.tif"))
    dlg.multispectral_image_edit.setText(str(tmp_path / "y.tif"))
    dlg.process_btn.click()
    assert boxes[-1] == ("warning", "Lỗi", "Tệp đầu vào không tồn tại.")


def _run_blending(dlg, qtbot, timeout=20000):
    dlg.process_btn.click()
    assert not dlg.process_btn.isEnabled()
    qtbot.waitUntil(lambda: dlg.process_btn.isEnabled(), timeout=timeout)


def test_image_blending_run(window, tmp_path, fake_scripts, boxes, qtbot):
    fake_scripts("pansharpening_script.py", FAKE_PANSHARPENING)
    pan = make_raster(tmp_path / "pan.tif", bands=1)
    ms = make_raster(tmp_path / "ms.tif", bands=4)
    add_raster(window, pan)
    add_raster(window, ms)
    dlg = _blending(window)
    dlg.pan_layer_combo.setCurrentIndex(dlg.pan_layer_combo.findText("pan"))
    dlg.multispectral_layer_combo.setCurrentIndex(dlg.multispectral_layer_combo.findText("ms"))
    out = tmp_path / "sharp.tif"
    dlg.output_path_edit.setText(str(out))
    _run_blending(dlg, qtbot)

    assert json.loads(Path(str(out) + ".args.json").read_text()) == [pan, ms, str(out), "rcs", "radiusx", "9", "radiusy", "9"]
    log = dlg.log_output.toPlainText()
    for text in ("Bắt đầu quá trình trộn ảnh...", "Đang chạy OTB Pansharpening...", "Method: rcs",
                 "✓ Quá trình trộn ảnh hoàn thành thành công!", "✓ Đã thêm layer vào bản đồ."):
        assert text in log
    assert boxes[-1] == ("information", "Thành công", "Quá trình trộn ảnh đã hoàn thành thành công!")
    assert "Pansharpened Image" in layer_names()
    assert dlg.progress_bar.isHidden()

    dlg.output_path_edit.setText(str(tmp_path / "fail.tif"))
    _run_blending(dlg, qtbot)
    assert "✗ Quá trình thất bại: OTB error" in dlg.log_output.toPlainText()
    assert boxes[-1] == ("critical", "Lỗi", "Quá trình trộn ảnh thất bại. Xem nhật ký để biết chi tiết.")


def test_pansharpening_finds_otb(tmp_path):
    """OTB lookup of pansharpening_script.py (run in a subprocess: importing it rewraps sys.stdout)."""
    import subprocess

    from vgeoint.common.paths import CONFIG_DIR, SCRIPTS_DIR

    code = (
        "import json, os, sys; sys.path.insert(0, sys.argv[1]); import pansharpening_script as ps; "
        "print(json.dumps([ps.OTB_LAUNCHER, ps.find_otb_executable(), 'PROJ_DATA' in ps.otb_environment()]))"
    )

    def run(**env):
        out = subprocess.run([sys.executable, "-c", code, str(SCRIPTS_DIR)], capture_output=True, text=True,
                             env={**os.environ, "PROJ_DATA": "x", **env}, timeout=60)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout.strip().splitlines()[-1])

    launcher, found, has_proj = run()
    assert not has_proj
    configured = json.loads((CONFIG_DIR / "image_blending_config.json").read_text(encoding="utf-8"))["otb_path"]
    if os.path.exists(configured):
        assert found == configured

    fake = tmp_path / "otb" / "bin"
    fake.mkdir(parents=True)
    (fake / launcher).write_text("")
    assert run(VGEOINT_OTB_DIR=str(tmp_path / "otb"))[1] == str(fake / launcher)


# ======================================================================= GoogleEarthEngine
FAKE_GEE = """
p = argparse.ArgumentParser()
for k in ("--data_id", "--region", "--output", "--project_id"):
    p.add_argument(k)
a = p.parse_args()
print(f"[12:00:00] [INFO] Data ID: {a.data_id}")
os.makedirs(a.output, exist_ok=True)
json.dump(sys.argv[1:], open(os.path.join(a.output, "args.json"), "w"))
if a.data_id == "bad":
    print("[12:00:01] [ERROR] Image not found")
    print("ee.EEException: not found", file=sys.stderr)
    sys.exit(1)
path = os.path.join(a.output, "COPERNICUS_S2_20250101.tif")
write(path, [np.full((20, 30), 7, np.uint8)] * 3)
print(f"[12:00:02] [OK] Completed! File downloaded successfully to: {path}")
if a.data_id != "noevent":
    result(output=path)
"""


def _gee(window):
    from vgeoint.app.dialogs.google_earth_engine import GoogleEarthEngineDialog

    return GoogleEarthEngineDialog(window, window.map_canvas, window.layer_tree_view)


def test_gee_ui_and_validation(window, boxes):
    dlg = _gee(window)
    assert dlg.windowTitle() == "Tải ảnh từ Google Earth Engine"
    assert (dlg.width(), dlg.height()) == (600, 700)
    assert dlg.project_id_edit.text() == "root-clover-471000-e0"
    assert dlg.region_edit.text() == "105.7,20.9,106.0,21.1"
    assert dlg.output_path_edit.text() == "downloads"
    assert dlg.auto_add_output_files()
    assert "🔧 Giao diện Google Earth Engine đã sẵn sàng" in dlg.log_text_edit.toPlainText()
    assert not hasattr(dlg, "complete")

    dlg.download_btn.click()
    assert boxes[-1] == ("warning", "Cảnh báo", "Vui lòng đăng nhập trước!")
    dlg.is_logged_in = True
    dlg.download_btn.click()
    assert boxes[-1] == ("warning", "Cảnh báo", "Vui lòng nhập ID dữ liệu!")
    dlg.data_id_edit.setText("x")
    dlg.region_edit.clear()
    dlg.download_btn.click()
    assert boxes[-1] == ("warning", "Cảnh báo", "Vui lòng nhập vùng quan tâm!")

    dlg.clear_log_btn.click()
    assert dlg.log_text_edit.toPlainText().endswith("🔧 Log đã được xóa")


@pytest.mark.parametrize("code, ok", [("print('ok')", True), ("import sys; sys.exit(1)", False)])
def test_gee_login(window, boxes, qtbot, monkeypatch, code, ok):
    from vgeoint.app.dialogs import google_earth_engine

    monkeypatch.setenv("VGEOINT_AI_PYTHON", sys.executable)
    monkeypatch.setattr(google_earth_engine, "AUTH_ARGUMENTS", ["-c", code])
    dlg = _gee(window)
    dlg.login_btn.click()
    qtbot.waitUntil(lambda: len(boxes) > 0, timeout=20000)
    if ok:
        assert boxes == [("information", "Thành công", "Đăng nhập thành công!")]
        assert dlg.is_logged_in and dlg.login_btn.text() == "Đã đăng nhập" and not dlg.login_btn.isEnabled()
    else:
        assert boxes == [("warning", "Lỗi", "Đăng nhập thất bại!")]
        assert not dlg.is_logged_in and dlg.login_btn.isEnabled()


@pytest.mark.skipif(not AI_PYTHON.exists(), reason="ai environment not installed")
def test_gee_auth_command_is_the_earthengine_cli(qgis_app):
    """AUTH_ARGUMENTS reaches `earthengine authenticate` in the ai env (checked with --help, no network)."""
    import subprocess

    from vgeoint.app.dialogs.google_earth_engine import AUTH_ARGUMENTS

    assert AUTH_ARGUMENTS[-2:] == ["authenticate", "--force"]
    out = subprocess.run([str(AI_PYTHON), *AUTH_ARGUMENTS[:-1], "--help"], capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stderr
    assert "usage: earthengine authenticate" in out.stdout and "--force" in out.stdout


@pytest.mark.parametrize("data_id", ["COPERNICUS/S2/20250101", "noevent"])
def test_gee_download(window, tmp_path, fake_scripts, boxes, qtbot, data_id):
    fake_scripts("gee_download.py", FAKE_GEE)
    dlg = _gee(window)
    dlg.is_logged_in = True
    dlg.data_id_edit.setText(data_id)
    out_dir = tmp_path / "dl"
    dlg.output_path_edit.setText(str(out_dir))
    dlg.download_btn.click()
    assert not dlg.download_btn.isEnabled() and not dlg.progress_bar.isHidden()
    qtbot.waitUntil(lambda: dlg.download_btn.isEnabled(), timeout=20000)

    assert json.loads((out_dir / "args.json").read_text()) == [
        "--data_id", data_id, "--region", "105.7,20.9,106.0,21.1", "--output", str(out_dir),
        "--project_id", "root-clover-471000-e0",
    ]
    log = dlg.log_text_edit.toPlainText()
    assert "✓ [12:00:02] [OK] Completed!" in log
    assert "ℹ️ [12:00:00] [INFO] Data ID:" in log
    assert "📄 File đã tải: COPERNICUS_S2_20250101.tif" in log
    assert "✅ Ảnh vệ tinh hợp lệ - 30x20 pixels" in log
    assert "Mã thoát: 0" in log and "Trạng thái: Normal" in log
    assert dlg.status_label.text() == "Hoàn thành thành công!"
    assert boxes[-1][0] == "information" and "File: COPERNICUS_S2_20250101.tif" in boxes[-1][2]
    assert layer_names() == ["COPERNICUS_S2_20250101"]
    assert [Path(p) for p in dlg.output_files] == [out_dir / "COPERNICUS_S2_20250101.tif"]


def test_gee_download_failure(window, tmp_path, fake_scripts, boxes, qtbot):
    fake_scripts("gee_download.py", FAKE_GEE)
    dlg = _gee(window)
    dlg.is_logged_in = True
    dlg.data_id_edit.setText("bad")
    dlg.output_path_edit.setText(str(tmp_path / "dl"))
    dlg.download_btn.click()
    qtbot.waitUntil(lambda: dlg.download_btn.isEnabled(), timeout=20000)
    log = dlg.log_text_edit.toPlainText()
    assert "❌ [12:00:01] [ERROR] Image not found" in log
    assert "❌ ee.EEException: not found" in log
    assert dlg.status_label.text() == "Tải dữ liệu thất bại!"
    assert boxes[-1][0] == "critical" and "Mã lỗi: 1" in boxes[-1][2]
    assert layer_names() == []


# ======================================================================= real runs (slow)
def _real_ai(monkeypatch):
    if not AI_PYTHON.exists():
        pytest.skip("ai environment not installed")
    monkeypatch.delenv("VGEOINT_AI_PYTHON", raising=False)


@pytest.mark.slow
@pytest.mark.timeout(900)
def test_auto_classification_real(window, tmp_path, boxes, qtbot, monkeypatch):
    _real_ai(monkeypatch)
    add_raster(window, s2_raster(tmp_path / "s2.tif"))
    dlg = _auto_classification(window)
    if not Path(dlg.model_path).exists():
        pytest.skip("models/random_forest_model_s2.joblib missing")
    t0 = time.perf_counter()
    _run_auto(dlg, qtbot, timeout=600000)
    print(f"\nAutoClassification real run: {time.perf_counter() - t0:.1f}s")
    log = _log(dlg.logTextEdit)
    assert dlg.statusLabel.text() == "Hoàn tất", log
    assert "✅ Phân loại ảnh hoàn tất" in log and "🎨 Đã tạo ảnh phân loại với màu sắc" in log
    classified = gdal.Open(str(tmp_path / "s2_classified.tif")).ReadAsArray()
    assert classified.shape == (32, 48)
    assert set(np.unique(classified[~np.isnan(classified)])) <= {1.0, 2.0, 3.0, 4.0}
    colored = gdal.Open(str(tmp_path / "s2_classified_unique_values.tif"))
    assert colored.GetRasterBand(1).GetColorTable() is not None
    assert {"s2_classified", "s2_classified_unique_values"} <= set(layer_names())


@pytest.mark.slow
@pytest.mark.timeout(900)
def test_motion_detection_real(window, tmp_path, boxes, qtbot, monkeypatch):
    _real_ai(monkeypatch)
    add_raster(window, s2_raster(tmp_path / "before.tif", seed=1))
    add_raster(window, s2_raster(tmp_path / "after.tif", seed=2))
    from vgeoint.ai.runner import model_path

    if not model_path("models/random_forest_model_s2.joblib").exists():
        pytest.skip("models/random_forest_model_s2.joblib missing")
    dlg = _motion(window)
    t0 = time.perf_counter()
    _run_motion(dlg, qtbot, tmp_path / "change.tif", timeout=600000)
    print(f"\nMotionDetection real run: {time.perf_counter() - t0:.1f}s")
    assert "hoàn tất thành công" in dlg.noticeLbl.text(), dlg.noticeLbl.text()
    assert (tmp_path / "change_colored_unique_values.tif").exists()
    assert (tmp_path / "change_statistics.csv").exists()
    codes = set(np.unique(gdal.Open(str(tmp_path / "change_colored_unique_values.tif")).ReadAsArray()))
    assert codes <= {b * 10 + a for b in range(1, 5) for a in range(1, 5)}
    assert any(b[0] == "exec" for b in boxes)
    names = layer_names()
    assert "Change Detection (Colored) - change_colored_unique_values" in names
    assert "change_colored_unique_values_with_legend (With Legend)" in names


@pytest.mark.slow
@pytest.mark.timeout(900)
def test_image_blending_real_otb(window, tmp_path, boxes, qtbot, monkeypatch):
    _real_ai(monkeypatch)
    if not OTB_LAUNCHER.exists():
        pytest.skip("Orfeo Toolbox not installed at C:\\OTB-9.1.0-Win64")
    # OTB Pansharpening (like the C++ dialog, which did not run Superimpose first) needs the MS image
    # already resampled onto the PAN grid ("Inputs do not occupy the same physical space" otherwise).
    pan = make_raster(tmp_path / "pan.tif", bands=1, width=96, height=64, dtype="UInt16", seed=3)
    ms = make_raster(tmp_path / "ms.tif", bands=4, width=96, height=64, dtype="UInt16", seed=4)
    add_raster(window, str(pan))
    add_raster(window, ms)
    dlg = _blending(window)
    dlg.pan_layer_combo.setCurrentIndex(dlg.pan_layer_combo.findText("pan"))
    dlg.multispectral_layer_combo.setCurrentIndex(dlg.multispectral_layer_combo.findText("ms"))
    out = tmp_path / "sharp.tif"
    dlg.output_path_edit.setText(str(out))
    t0 = time.perf_counter()
    _run_blending(dlg, qtbot, timeout=600000)
    print(f"\nImageBlending (OTB rcs) real run: {time.perf_counter() - t0:.1f}s")
    log = dlg.log_output.toPlainText()
    assert boxes[-1][0] == "information", log
    result = gdal.Open(str(out))
    assert (result.RasterCount, result.RasterXSize, result.RasterYSize) == (4, 96, 64)
    assert "Pansharpened Image" in layer_names()
