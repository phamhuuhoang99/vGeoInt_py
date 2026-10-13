"""ShipTrackingDialog, VehicleTrackingDialog and ObjectTrackingDialog.

Fast tests run fake scripts (same CLI, outputs and events as the real ones) with the test interpreter.
`pixi run pytest -m slow tests/test_ai_tracking.py` runs the real models in the ai environment.
"""

import json
import shutil
import subprocess
import sys
import textwrap
import time

import pytest

from vgeoint.common.paths import ROOT

AI_PYTHON = ROOT / ".pixi" / "envs" / "ai" / "python.exe"

FAKE_VEHICLES = textwrap.dedent(
    """
    import argparse, json, os, sys
    from vgeoint.ai.scripts._events import result
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir"); p.add_argument("--model"); p.add_argument("--output-dir")
    p.add_argument("--confidence", type=float); p.add_argument("--max-speed", type=float)
    a = p.parse_args()
    with open(os.path.join(a.output_dir, "args.json"), "w") as f:
        json.dump(sys.argv[1:], f)
    print("[OK] Ultralytics YOLO loaded successfully")
    print("FutureWarning: something", file=sys.stderr)
    print("[WARN] SAHI not available")
    def fc(features):
        return {"type": "FeatureCollection", "features": features}
    def feat(geom, **props):
        return {"type": "Feature", "properties": props, "geometry": geom}
    pts = [feat({"type": "Point", "coordinates": [105.0 + i * 0.001, 21.0]}, track_id=1, label=f"16:21:4{i}.000 28/03/2026")
           for i in range(3)]
    line = {"type": "LineString", "coordinates": [[105.0, 21.0], [105.002, 21.0]]}
    seg = {"type": "LineString", "coordinates": [[105.0, 21.0], [105.001, 21.0]]}
    for name, feats in (("vehicle_points", pts), ("vehicle_tracks", [feat(line, track_id=1)]),
                        ("vehicle_segments", [feat(seg, track_id=1), feat(seg, track_id=1)])):
        with open(os.path.join(a.output_dir, name + ".geojson"), "w", encoding="utf-8") as f:
            json.dump(fc(feats), f)
    print(" [RESULT] Total Tracks: 1")
    result(avg_speed_kmh=12.35, tracks=1, points=3, segments=2, direction="Đông (E) - 90.0°")
    print("=== Process Finished ===")
    sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
    """
)

FAKE_SHIP = textwrap.dedent(
    """
    import argparse, json, os, sys
    from vgeoint.ai.scripts._events import result
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir"); p.add_argument("--model"); p.add_argument("--output-dir")
    p.add_argument("--confidence"); p.add_argument("--max-distance")
    a = p.parse_args()
    with open(os.path.join(a.output_dir, "args.json"), "w") as f:
        json.dump(sys.argv[1:], f)
    print("[OK] PyTorch and TorchVision loaded successfully")
    print("Found 2 sequential data files in x:")
    print("Detecting ships for date [04-04-2026]: a.tif...")
    print("[OK] Date [04-04-2026]: Detected 2 ship centroids")
    print("Missing dependencies: foo", file=sys.stderr)
    print("[OK] Built 1 multi-date ship trajectories")
    lines = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"ship_id": "Ship_001"},
             "geometry": {"type": "LineString", "coordinates": [[105, 21], [105.1, 21.1]]}}]}
    points = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"ship_id": "Ship_001"},
              "geometry": {"type": "Point", "coordinates": [105 + i * 0.1, 21 + i * 0.1]}} for i in range(2)]}
    for name, data in (("ship_trajectories_lines", lines), ("ship_centroids_points", points)):
        with open(os.path.join(a.output_dir, name + ".geojson"), "w") as f:
            json.dump(data, f)
    print("  1. File duong di (Lines): x")
    result(lines="x", points="y", tracks=1, ship_points=2)
    print("Ship tracking completed successfully!")
    sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
    """
)

FAKE_ONNX = textwrap.dedent(
    """
    import argparse, os, sys, time
    from vgeoint.ai.scripts._events import emit, result
    p = argparse.ArgumentParser()
    p.add_argument("--video"); p.add_argument("--model"); p.add_argument("--out")
    p.add_argument("--score-thr"); p.add_argument("--max-frames", type=int)
    a = p.parse_args()
    if os.environ.get("FAKE_SLEEP"):
        time.sleep(float(os.environ["FAKE_SLEEP"]))
    print("Registering custom operators library from: x.dll")
    print("processed 50 frames")
    emit("progress", value=50.0, message="processed 50 frames", frame=50)
    print("onnx warning", file=sys.stderr)
    with open(a.out, "wb") as f:
        f.write(b"video")
    print(f"Done. Output: {a.out}")
    result(output=a.out, frames=a.max_frames)
    sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
    """
)


@pytest.fixture
def boxes(monkeypatch):
    """Record QMessageBox calls (static helpers and exec of custom boxes) without blocking."""
    from qgis.PyQt.QtWidgets import QMessageBox

    calls = []
    Btn = QMessageBox.StandardButton
    for name, answer in (("warning", Btn.Ok), ("information", Btn.Ok), ("critical", Btn.Ok)):
        monkeypatch.setattr(
            QMessageBox, name, lambda *a, _n=name, _r=answer, **k: calls.append((_n, a[1], a[2])) or _r
        )
    monkeypatch.setattr(QMessageBox, "exec", lambda self: calls.append(("exec", self.text(), self.informativeText())) or 0)
    return calls


@pytest.fixture
def fake_scripts(tmp_path, monkeypatch):
    from vgeoint.ai import runner

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "vehicles_track_detection.py").write_text(FAKE_VEHICLES, encoding="utf-8")
    (scripts / "ship_track_detection.py").write_text(FAKE_SHIP, encoding="utf-8")
    (scripts / "detect_track_video_onnx.py").write_text(FAKE_ONNX, encoding="utf-8")
    models = tmp_path / "models"
    (models / "onnx_output").mkdir(parents=True)
    for name in ("Ship_Detection_RGB.pth", "yolov8m.pt", "onnx_output/model.onnx"):
        (models / name).write_bytes(b"x")
    monkeypatch.setattr(runner, "SCRIPTS_DIR", scripts)
    monkeypatch.setattr(runner, "MODELS_DIR", models)
    monkeypatch.setenv("VGEOINT_AI_PYTHON", sys.executable)
    monkeypatch.delenv("FAKE_EXIT", raising=False)
    monkeypatch.delenv("FAKE_SLEEP", raising=False)
    return scripts


def _log(dlg) -> str:
    return dlg.logTextEdit.toPlainText()


def _layers_by_name():
    from qgis.core import QgsProject

    return {layer.name(): layer for layer in QgsProject.instance().mapLayers().values()}


# ------------------------------------------------------------------ vehicle
def _vehicle(window):
    from vgeoint.app.dialogs.vehicle_tracking import VehicleTrackingDialog

    return VehicleTrackingDialog(window, window.map_canvas, window.layer_tree_view)


def test_vehicle_initial_state(window):
    dlg = _vehicle(window)
    assert dlg.windowTitle() == "Theo dõi phương tiện"
    assert dlg.confidenceSpinBox.value() == pytest.approx(0.10)
    assert dlg.maxSpeedSpinBox.value() == 90.0
    assert dlg.progressBar.isHidden()
    assert dlg.statusLabel.text() == "Sẵn sàng"
    assert dlg.outputDirLineEdit.text().endswith("/tracking_vehicle_output")
    assert dlg.name() == "T_VehicleTracking"


def test_vehicle_resolve_model(tmp_path, monkeypatch):
    from vgeoint.ai import runner
    from vgeoint.app.dialogs.vehicle_tracking import resolve_model

    (tmp_path / "yolov8x.pt").write_bytes(b"x")
    (tmp_path / "best.pt").write_bytes(b"x")
    monkeypatch.setattr(runner, "MODELS_DIR", tmp_path)
    assert resolve_model("YOLOv8x (yolov8x.pt)") == str(tmp_path / "yolov8x.pt")
    assert resolve_model("Mô hình tùy chọn (models/best.pt)") == str(tmp_path / "best.pt")
    # Missing standard weights: the bare name is passed on (Ultralytics downloads it), as in C++.
    assert resolve_model("YOLOv8n (yolov8n.pt)") == "yolov8n.pt"
    assert resolve_model("my.pt (D:/w/my.pt)") == "D:/w/my.pt"


def test_vehicle_validation(window, boxes, tmp_path):
    dlg = _vehicle(window)
    dlg.okButton.click()
    assert boxes[-1] == ("critical", "Lỗi", "Vui lòng chọn thư mục chứa dữ liệu ảnh/GeoTIFF!")
    dlg.inputDirLineEdit.setText(str(tmp_path / "missing"))
    dlg.okButton.click()
    assert boxes[-1][2] == "Thư mục đầu vào không tồn tại!"
    dlg.inputDirLineEdit.setText(str(tmp_path))
    dlg.outputDirLineEdit.setText("  ")
    dlg.okButton.click()
    assert boxes[-1][2] == "Vui lòng chọn thư mục lưu kết quả!"
    assert "Lỗi: Vui lòng chọn thư mục lưu kết quả!" in _log(dlg)
    assert not dlg.runner.is_running()


def test_vehicle_browse_input_sets_output(window, tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog

    dlg = _vehicle(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: "D:/data/uav")
    dlg.browseInputDirButton.click()
    assert dlg.inputDirLineEdit.text() == "D:/data/uav"
    assert dlg.outputDirLineEdit.text() == "D:/data/uav/tracking_output"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("D:/w/custom.pt", ""))
    dlg.browseModelButton.click()
    assert dlg.modelComboBox.currentText() == "custom.pt (D:/w/custom.pt)"


def test_vehicle_run_success(window, qtbot, boxes, fake_scripts, tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    out = tmp_path / "out"
    dlg = _vehicle(window)
    dlg.inputDirLineEdit.setText(str(images))
    dlg.outputDirLineEdit.setText(str(out))
    dlg.modelComboBox.setCurrentIndex(1)  # YOLOv8m (yolov8m.pt)
    dlg.autoAddOutputCheckBox.setChecked(True)
    with qtbot.waitSignal(dlg.runner.finished, timeout=30000):
        dlg.okButton.click()
        assert not dlg.okButton.isEnabled() and not dlg.progressBar.isHidden()
        assert dlg.progressBar.maximum() == 0

    args = json.loads((out / "args.json").read_text())
    assert args == [
        "--input-dir", str(images), "--model", str(fake_scripts.parent / "models" / "yolov8m.pt"),
        "--output-dir", str(out), "--confidence", "0.1", "--max-speed", "90",
    ]  # fmt: skip
    assert dlg.okButton.isEnabled() and dlg.progressBar.isHidden()
    assert dlg.statusLabel.text() == "Xử lý hoàn thành!"
    assert dlg.avgSpeedValueLabel.text() == "12.35 km/h"
    assert dlg.trackCountValueLabel.text() == "1"
    assert dlg.pointCountValueLabel.text() == "3"
    assert dlg.directionValueLabel.text() == "Đông (E) - 90.0°"

    html = dlg.logTextEdit.toHtml()
    log = _log(dlg)
    assert "Tiến trình Python đã khởi động thành công (PID:" in log
    assert "FutureWarning: something" in log and "#f39c12" in html
    assert "[RESULT] Total Tracks: 1" in log
    assert "Đã thêm lớp 'Điểm phương tiện' (3 điểm) kèm nhãn ngày giờ chụp" in log

    layers = _layers_by_name()
    assert layers["Đường đi phương tiện"].featureCount() == 1
    assert layers["Từng đoạn phương tiện (vận tốc)"].featureCount() == 2
    points = layers["Điểm phương tiện"]
    assert points.labelsEnabled()
    pal = points.labeling().settings()
    assert pal.fieldName == "label"
    assert pal.format().color().name() == "#ffeb3b" and pal.format().buffer().enabled()
    assert dlg.output_files == [f"{out}/vehicle_{n}.geojson" for n in ("tracks", "segments", "points")]

    kind, text, _ = boxes[-1]
    assert kind == "exec" and "• Vận tốc trung bình các đoạn: 12.35 km/h" in text and "• Số lượng phương tiện: 1" in text


def test_vehicle_run_failure_no_layers(window, qtbot, boxes, fake_scripts, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "1")
    dlg = _vehicle(window)
    dlg.inputDirLineEdit.setText(str(tmp_path))
    dlg.outputDirLineEdit.setText(str(tmp_path / "out"))
    with qtbot.waitSignal(dlg.runner.finished, timeout=30000):
        dlg.okButton.click()
    assert dlg.statusLabel.text() == "Xử lý thất bại!"
    kind, title, text = boxes[-1]
    assert kind == "critical" and title == "Lỗi" and text.startswith("Xử lý thất bại!\nMã lỗi: 1\n")
    assert "Điểm phương tiện" not in _layers_by_name()


def test_vehicle_cancel_kills_process(window, qtbot, boxes, fake_scripts, tmp_path):
    (fake_scripts / "vehicles_track_detection.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    dlg = _vehicle(window)
    dlg.inputDirLineEdit.setText(str(tmp_path))
    dlg.outputDirLineEdit.setText(str(tmp_path / "out"))
    with qtbot.waitSignal(dlg.runner.started, timeout=30000):
        dlg.okButton.click()
    t0 = time.monotonic()
    dlg.cancelButton.click()
    assert not dlg.runner.is_running()
    assert time.monotonic() - t0 < 5
    assert boxes == []


# --------------------------------------------------------------------- ship
def _ship(window):
    from vgeoint.app.dialogs.ship_tracking import ShipTrackingDialog

    return ShipTrackingDialog(window, window.map_canvas, window.layer_tree_view)


def test_ship_initial_state_and_settings(window, tmp_path):
    from vgeoint.common.utils import settings

    s = settings()
    s.setValue("ShipTracking/InputDir", str(tmp_path))
    s.setValue("ShipTracking/OutputDir", "")
    try:
        dlg = _ship(window)
    finally:
        s.remove("ShipTracking")
    assert dlg.windowTitle() == "Theo dõi tàu thuyền"
    assert dlg.inputDirLineEdit.text() == str(tmp_path)
    assert dlg.outputDirLineEdit.text() == ""  # restored before the auto-output connection, as in C++
    assert dlg.modelComboBox.count() == 1
    assert dlg.modelComboBox.currentData().endswith("Ship_Detection_RGB.pth")
    assert dlg.confidenceSpinBox.value() == pytest.approx(0.6)
    assert dlg.maxDistanceSpinBox.value() == 30000.0
    assert "Hệ thống theo dõi quỹ đạo tàu thuyền đã sẵn sàng" in _log(dlg)

    dlg.inputDirLineEdit.setText("D:/ships")
    assert dlg.outputDirLineEdit.text() == "D:/ships/output"


def test_ship_missing_model_message(window, boxes, tmp_path, monkeypatch):
    """Ship_Detection_RGB.pth is not shipped: the C++ validation message is shown."""
    from vgeoint.ai import runner

    monkeypatch.setattr(runner, "MODELS_DIR", tmp_path / "no_models")
    dlg = _ship(window)
    dlg.inputDirLineEdit.setText(str(tmp_path))
    dlg.okButton.click()
    kind, title, text = boxes[-1]
    expected = f"File mô hình không tồn tại: {tmp_path / 'no_models' / 'Ship_Detection_RGB.pth'}"
    assert (kind, title, text) == ("critical", "Lỗi", expected)
    assert "Lỗi: File mô hình không tồn tại" in _log(dlg)
    assert not dlg.runner.is_running() and dlg.okButton.isEnabled()


def test_ship_invalid_input_dir(window, boxes, tmp_path):
    dlg = _ship(window)
    dlg.inputDirLineEdit.setText(str(tmp_path / "missing"))
    dlg.okButton.click()
    assert boxes[-1] == ("critical", "Lỗi", "Vui lòng chọn thư mục dữ liệu đầu vào hợp lệ")


def test_ship_run_success(window, qtbot, boxes, fake_scripts, tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    out = tmp_path / "new" / "out"
    dlg = _ship(window)
    dlg.inputDirLineEdit.setText(str(images))
    dlg.outputDirLineEdit.setText(str(out))
    dlg.autoAddOutputCheckBox.setChecked(True)
    with qtbot.waitSignal(dlg.runner.finished, timeout=30000):
        dlg.okButton.click()
    assert out.is_dir()
    args = json.loads((out / "args.json").read_text())
    assert args[args.index("--confidence") + 1] == "0.6"
    assert args[args.index("--max-distance") + 1] == "30000"
    assert args[args.index("--model") + 1] == str(fake_scripts.parent / "models" / "Ship_Detection_RGB.pth")

    log = _log(dlg)
    assert "✓ Đã tạo thư mục đầu ra" in log
    assert "📁 Found 2 sequential data files" in log
    assert "🚢 [OK] Date [04-04-2026]: Detected 2 ship centroids" not in log  # "[OK]" rule wins, as in C++
    assert "🔄 [OK] Date [04-04-2026]: Detected 2 ship centroids" in log
    assert "🔍 Detecting ships for date" in log
    assert "❌ Thiếu thư viện Python: Missing dependencies: foo" in log
    assert "💾 1. File duong di (Lines): x" in log
    assert "✅ Xử lý hoàn tất thành công!" in log
    assert "Mã thoát (Exit code): 0" in log and "Trạng thái: Normal" in log
    assert "✓ Đã thêm lớp 'Tâm vị trí tàu thuyền' (2 điểm)" in log
    assert dlg.statusLabel.text() == "Hoàn thành thành công!"

    layers = _layers_by_name()
    assert layers["Đường đi tàu thuyền"].featureCount() == 1
    assert layers["Tâm vị trí tàu thuyền"].featureCount() == 2
    kind, text, informative = boxes[-1]
    assert kind == "exec" and text == "Theo dõi tàu thuyền hoàn tất thành công!"
    assert f"- {out}/ship_trajectories_lines.geojson" in informative


def test_ship_no_auto_add(window, qtbot, boxes, fake_scripts, tmp_path):
    dlg = _ship(window)
    dlg.inputDirLineEdit.setText(str(tmp_path))
    dlg.outputDirLineEdit.setText(str(tmp_path / "out"))
    dlg.autoAddOutputCheckBox.setChecked(False)
    with qtbot.waitSignal(dlg.runner.finished, timeout=30000):
        dlg.okButton.click()
    assert "Đường đi tàu thuyền" not in _layers_by_name()
    assert boxes[-1][0] == "exec"


def test_ship_save_and_clear_log(window, tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog

    dlg = _ship(window)
    target = tmp_path / "log.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    dlg.saveLogButton.click()
    content = target.read_text(encoding="utf-8")
    assert content.startswith("=== vGeoInt_v2 Ship Tracking Log ===")
    assert "Hệ thống theo dõi quỹ đạo tàu thuyền đã sẵn sàng" in content
    dlg.clearLogButton.click()
    assert "Log đã được xóa" in _log(dlg) and "đã sẵn sàng" not in _log(dlg)


# ------------------------------------------------------------------- object
def _object(window):
    from vgeoint.app.dialogs.object_tracking import ObjectTrackingDialog

    return ObjectTrackingDialog(window, window.map_canvas, window.layer_tree_view)


def test_object_validation(window, boxes, tmp_path):
    dlg = _object(window)
    assert dlg.windowTitle() == "Theo dõi đối tượng"
    assert dlg.progressBar.isHidden()
    dlg.outputDirLedr.setText("")
    dlg.startBtn.click()
    assert boxes[-1] == ("warning", "Theo dõi đối tượng", "Vui lòng chọn file video đầu vào.")
    dlg.videoPathLedr.setText(str(tmp_path / "v.mp4"))
    dlg.startBtn.click()
    assert boxes[-1] == ("warning", "Theo dõi đối tượng", "Vui lòng chọn thư mục lưu output.")
    assert "Thiếu thư mục lưu output." in _log(dlg)


def test_object_missing_model(window, boxes, tmp_path, monkeypatch):
    from vgeoint.ai import runner

    monkeypatch.setattr(runner, "MODELS_DIR", tmp_path / "none")
    dlg = _object(window)
    dlg.videoPathLedr.setText(str(tmp_path / "v.mp4"))
    dlg.outputDirLedr.setText(str(tmp_path))
    dlg.startBtn.click()
    kind, _, text = boxes[-1]
    assert kind == "critical" and text.startswith("Không tìm thấy file model.onnx tại:")


def test_object_run_success(window, qtbot, boxes, fake_scripts, tmp_path):
    dlg = _object(window)
    dlg.videoPathLedr.setText(str(tmp_path / "clip.avi"))
    dlg.outputDirLedr.setText(str(tmp_path))
    completed = []
    dlg.complete.connect(lambda: completed.append(True))
    with qtbot.waitSignal(dlg.runner.finished, timeout=30000):
        dlg.startBtn.click()
        assert not dlg.startBtn.isEnabled() and not dlg.videoPathLedr.isEnabled()
        assert dlg.progressBar.format() == "Đang khởi động..."

    out = tmp_path / "track_clip_onnx.mp4"
    assert out.read_bytes() == b"video"
    assert dlg.output_files == [str(out).replace("\\", "/")]
    assert dlg.progressBar.maximum() == 300 and dlg.progressBar.value() == 300
    assert dlg.progressBar.format() == "%p% (%v / %m frames)"
    assert dlg.startBtn.isEnabled() and dlg.progressBar.isHidden()
    log = _log(dlg)
    assert "processed 50 frames" in log and "[stderr] onnx warning" in log
    assert "--max-frames" not in log and "Exit code: 0" in log
    assert "Theo dõi đối tượng hoàn tất thành công." in log
    assert completed == [True]
    assert boxes[-1][0] == "exec" and boxes[-1][2].endswith("track_clip_onnx.mp4")
    assert not dlg.auto_add_output_files()

    from vgeoint.common.utils import settings

    assert settings().value("ObjectTracking/OutputDir") == str(tmp_path)


def test_object_progress_from_event(window, qtbot):
    dlg = _object(window)
    dlg.update_ui_state(True)
    dlg._on_event({"type": "progress", "value": 16.7, "frame": 50})
    assert (dlg.progressBar.maximum(), dlg.progressBar.value()) == (300, 50)


def test_object_failure_and_running_guard(window, qtbot, boxes, fake_scripts, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "4")
    monkeypatch.setenv("FAKE_SLEEP", "1.5")
    dlg = _object(window)
    dlg.videoPathLedr.setText(str(tmp_path / "clip.mp4"))
    dlg.outputDirLedr.setText(str(tmp_path))
    with qtbot.waitSignal(dlg.runner.finished, timeout=30000):
        dlg.startBtn.click()
        dlg.apply()  # second start while running
        assert boxes[-1] == ("warning", "Theo dõi đối tượng", "Quá trình theo dõi đang chạy.")
    assert boxes[-1] == ("critical", "Theo dõi đối tượng", "Tiến trình theo dõi thất bại. Vui lòng kiểm tra log.")
    assert "Exit code: 4" in _log(dlg)


def test_object_close_kills_process(window, qtbot, boxes, fake_scripts, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "60")
    dlg = _object(window)
    dlg.videoPathLedr.setText(str(tmp_path / "clip.mp4"))
    dlg.outputDirLedr.setText(str(tmp_path))
    with qtbot.waitSignal(dlg.runner.started, timeout=30000):
        dlg.startBtn.click()
    dlg.closeBtn.click()
    assert not dlg.runner.is_running()
    assert boxes == []


# --------------------------------------------------------------------- slow
@pytest.mark.slow
@pytest.mark.skipif(not AI_PYTHON.exists(), reason="ai environment not installed")
def test_vehicle_real_yolov8m(window, qtbot, boxes, tmp_path, monkeypatch):
    from vgeoint.ai.runner import model_path

    assert model_path("models/yolov8m.pt").exists()
    monkeypatch.delenv("VGEOINT_AI_PYTHON", raising=False)
    bus = ROOT / ".pixi" / "envs" / "ai" / "Lib" / "site-packages" / "ultralytics" / "assets" / "bus.jpg"
    images = tmp_path / "images"
    images.mkdir()
    shutil.copy(bus, images / "20260328_162146_477_DJI_0260_V.jpg")
    shutil.copy(bus, images / "20260328_162147_477_DJI_0261_V.jpg")

    dlg = _vehicle(window)
    dlg.inputDirLineEdit.setText(str(images))
    dlg.outputDirLineEdit.setText(str(tmp_path / "out"))
    dlg.modelComboBox.setCurrentIndex(1)
    dlg.confidenceSpinBox.setValue(0.25)
    dlg.autoAddOutputCheckBox.setChecked(True)
    t0 = time.monotonic()
    with qtbot.waitSignal(dlg.runner.finished, timeout=600000) as blocker:
        dlg.okButton.click()
    print(f"\nvehicle tracking real run: {time.monotonic() - t0:.1f}s")
    assert blocker.args[0] == 0, _log(dlg)
    assert int(dlg.trackCountValueLabel.text()) >= 1
    assert int(dlg.pointCountValueLabel.text()) >= 2
    assert dlg.avgSpeedValueLabel.text() == "0.00 km/h"  # identical frames: nothing moved
    assert _layers_by_name()["Điểm phương tiện"].featureCount() == int(dlg.pointCountValueLabel.text())


@pytest.mark.slow
@pytest.mark.skipif(not AI_PYTHON.exists(), reason="ai environment not installed")
def test_object_tracking_real_onnx(window, qtbot, boxes, tmp_path, monkeypatch):
    from vgeoint.ai.runner import model_path

    assert model_path("models/onnx_output/model.onnx").exists()
    monkeypatch.delenv("VGEOINT_AI_PYTHON", raising=False)
    video = tmp_path / "synthetic.mp4"
    writer = textwrap.dedent(
        """
        import sys, cv2, numpy as np
        w = cv2.VideoWriter(sys.argv[1], cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 240))
        for i in range(10):
            f = np.full((240, 320, 3), 90, np.uint8)
            cv2.rectangle(f, (20 + 10 * i, 100), (50 + 10 * i, 115), (230, 230, 230), -1)
            w.write(f)
        w.release()
        """
    )
    subprocess.run([str(AI_PYTHON), "-c", writer, str(video)], check=True)

    dlg = _object(window)
    dlg.max_frames = 8
    dlg.videoPathLedr.setText(str(video))
    dlg.outputDirLedr.setText(str(tmp_path / "out"))
    t0 = time.monotonic()
    with qtbot.waitSignal(dlg.runner.finished, timeout=600000) as blocker:
        dlg.startBtn.click()
    print(f"\nobject tracking real run: {time.monotonic() - t0:.1f}s")
    log = _log(dlg)
    assert blocker.args[0] == 0, log
    assert "Registering custom operators library from:" in log
    assert "[ERROR]" not in log, log
    out = tmp_path / "out" / "track_synthetic_onnx.mp4"
    assert out.stat().st_size > 0
    assert dlg.progressBar.value() == 8
