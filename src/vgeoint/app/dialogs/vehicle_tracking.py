"""Port of VehicleTrackingDialog.cpp."""

import os
from datetime import datetime

from qgis.core import (
    QgsPalLayerSettings,
    QgsProject,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QDir, QFileInfo, Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox

from vgeoint.ai.runner import model_path
from vgeoint.app.dialogs._tracking_base import TrackingProcessMixin, qnum
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon

Ui_VehicleTrackingDialog = load_ui_class("app", "VehicleTrackingDialog")

_LOG_COLORS = {
    "ERROR": "#e74c3c",
    "WARNING": "#f39c12",
    "SUCCESS": "#27ae60",
    "RESULT": "#2980b9; font-weight: bold;",
    "SYSTEM": "#8e44ad; font-weight: bold;",
}


def resolve_model(selected: str) -> str:
    """Model path from the combo text, as VehicleTrackingDialog::validateInputs().

    The combo items are "YOLOv8x (yolov8x.pt)", "Mô hình tùy chọn (models/best.pt)" or
    "<name> (<absolute path>)" for a browsed file. Relative names were resolved against the working
    directory ("python_env" layout); they now point to the models folder when the file is there,
    otherwise the bare name is passed on (Ultralytics then downloads the standard weights).
    """
    for known in ("models/yolov8x.pt", "models/yolov8m.pt", "models/yolov8n.pt", "models/best.pt"):
        if known in selected:
            path = known
            break
    else:
        if "(" in selected and ")" in selected:
            path = selected[selected.index("(") + 1 : selected.rindex(")")]
        else:
            path = selected
    if path and not os.path.isabs(path):
        candidate = model_path(path)
        if candidate.is_file():
            return str(candidate)
    return path


class VehicleTrackingDialog(TrackingProcessMixin, QDialog, Ui_VehicleTrackingDialog):
    SCRIPT = "vehicles_track_detection.py"
    RUNNING_STATUS = "Đang xử lý theo dõi phương tiện..."
    STARTED_LOG = ("Tiến trình Python đã khởi động thành công (PID: {pid})", "SUCCESS")

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle("Theo dõi phương tiện")
        self.setWindowIcon(get_icon("DetectVehicles.svg"))
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.output_files: list[str] = []
        self._input_dir = ""
        self._model_path = ""
        self.avg_speed = 0.0
        self.total_tracks = 0
        self.total_points = 0

        self.confidenceSpinBox.setValue(0.10)
        self.maxSpeedSpinBox.setValue(90.0)
        self.progressBar.hide()
        self.progressBar.setValue(0)
        self.statusLabel.setText("Sẵn sàng")

        self._init_process()
        self._setup_connections()

        default_output = QDir.currentPath() + "/tracking_vehicle_output"
        self.outputDirLineEdit.setText(default_output)
        self._output_dir = default_output

    # BPluginInterface
    def name(self) -> str:
        return "T_VehicleTracking"

    def vn_name(self) -> str:
        return "Theo dõi phương tiện"

    def get_icon(self):
        return get_icon("DetectVehicles.svg")

    def auto_add_output_files(self) -> bool:
        return self.autoAddOutputCheckBox.isChecked()

    def _setup_connections(self):
        self.browseInputDirButton.clicked.connect(self.browse_input_dir)
        self.browseModelButton.clicked.connect(self.browse_model)
        self.browseOutputDirButton.clicked.connect(self.browse_output_dir)
        self.okButton.clicked.connect(self.apply)
        self.cancelButton.clicked.connect(self.reject)
        self.clearLogButton.clicked.connect(self.clear_log)
        self.saveLogButton.clicked.connect(self.save_log)

    def browse_input_dir(self):
        start = self.inputDirLineEdit.text() or QDir.currentPath()
        dir_ = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục chứa ảnh/GeoTIFF theo dõi phương tiện",
            start,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if dir_:
            self.inputDirLineEdit.setText(dir_)
            self._input_dir = dir_
            self.add_log(f"Đã chọn thư mục đầu vào: {dir_}")
            out = self.outputDirLineEdit.text()
            if not out or out.endswith("/tracking_vehicle_output"):
                self._output_dir = dir_ + "/tracking_output"
                self.outputDirLineEdit.setText(self._output_dir)

    def browse_model(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "Chọn tệp mô hình YOLO (.pt)", QDir.currentPath(), "Mô hình YOLO (*.pt);;Tất cả tệp (*.*)"
        )
        if file:
            self.modelComboBox.insertItem(0, f"{QFileInfo(file).fileName()} ({file})")
            self.modelComboBox.setCurrentIndex(0)
            self._model_path = file
            self.add_log(f"Đã chọn mô hình: {file}")

    def browse_output_dir(self):
        start = self.outputDirLineEdit.text() or QDir.currentPath()
        dir_ = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục lưu kết quả",
            start,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if dir_:
            self.outputDirLineEdit.setText(dir_)
            self._output_dir = dir_
            self.add_log(f"Đã chọn thư mục lưu kết quả: {dir_}")

    def validate_inputs(self):
        """Raise ValueError with the user message when an input is invalid."""
        self._input_dir = self.inputDirLineEdit.text().strip()
        if not self._input_dir:
            raise ValueError("Vui lòng chọn thư mục chứa dữ liệu ảnh/GeoTIFF!")
        if not QDir(self._input_dir).exists():
            raise ValueError("Thư mục đầu vào không tồn tại!")

        self._model_path = resolve_model(self.modelComboBox.currentText())

        self._output_dir = self.outputDirLineEdit.text().strip()
        if not self._output_dir:
            raise ValueError("Vui lòng chọn thư mục lưu kết quả!")
        out_dir = QDir(self._output_dir)
        if not out_dir.exists() and not out_dir.mkpath("."):
            raise ValueError("Không thể tạo thư mục lưu kết quả!")

        self.add_log("✓ Tất cả tham số đầu vào hợp lệ")

    def apply(self):
        try:
            self.add_log("=== BẮT ĐẦU QUÁ TRÌNH THEO DÕI PHƯƠNG TIỆN ===", "SYSTEM")
            self.validate_inputs()

            confidence = self.confidenceSpinBox.value()
            max_speed = self.maxSpeedSpinBox.value()

            self.avg_speed = 0.0
            self.total_tracks = 0
            self.total_points = 0
            self.avgSpeedValueLabel.setText("-- km/h")
            self.trackCountValueLabel.setText("--")
            self.pointCountValueLabel.setText("--")
            self.directionValueLabel.setText("--")

            self.add_log("Tham số xử lý:")
            self.add_log(f"  - Thư mục đầu vào: {self._input_dir}")
            self.add_log(f"  - Mô hình: {self._model_path}")
            self.add_log(f"  - Ngưỡng tin cậy: {qnum(confidence)}")
            self.add_log(f"  - Ràng buộc vận tốc tối đa: {qnum(max_speed)} km/h")
            self.add_log(f"  - Thư mục đầu ra: {self._output_dir}")

            self._run_python_script(
                [
                    "--input-dir", self._input_dir,
                    "--model", self._model_path,
                    "--output-dir", self._output_dir,
                    "--confidence", qnum(confidence),
                    "--max-speed", qnum(max_speed),
                ]
            )  # fmt: skip
        except ValueError as e:
            self.add_log(f"Lỗi: {e}", "ERROR")
            QMessageBox.critical(self, "Lỗi", str(e))

    # ------------------------------------------------------------- process
    def _on_event(self, event: dict):
        """Replaces parseResultMetrics() (QRegExp on "km/h", "Total Tracks:", ...)."""
        if event.get("type") != "result":
            return
        if "avg_speed_kmh" in event:
            self.avg_speed = float(event["avg_speed_kmh"])
            self.avgSpeedValueLabel.setText(f"{self.avg_speed:.2f} km/h")
        if "tracks" in event:
            self.total_tracks = int(event["tracks"])
            self.trackCountValueLabel.setText(str(self.total_tracks))
        if "points" in event:
            self.total_points = int(event["points"])
            self.pointCountValueLabel.setText(str(self.total_points))
        direction = str(event.get("direction", "")).strip()
        if direction:
            self.directionValueLabel.setText(direction)

    def _on_stdout(self, line: str):
        line = line.strip()
        if not line:
            return
        if "[OK]" in line:
            self.add_log(line, "SUCCESS")
        elif "[WARN]" in line:
            self.add_log(line, "WARNING")
        elif "[RESULT]" in line:
            self.add_log(line, "RESULT")
        else:
            self.add_log(line, "INFO")

    def _on_stderr(self, line: str):
        line = line.strip()
        if not line:
            return
        if "UserWarning" in line or "FutureWarning" in line or "WARNING" in line:
            self.add_log(line, "WARNING")
        else:
            self.add_log(line, "ERROR")

    def _progress_text(self, seconds: int) -> str:
        return f"Đang xử lý theo dõi phương tiện... ({seconds}s)"

    def _on_process_finished(self, exit_code: int, crashed: bool):
        self._progress_timer.stop()
        self.progressBar.hide()
        self._set_running(False)

        total = self.elapsed_ms() // 1000
        time_str = f"{total // 60}m {total % 60}s"

        if crashed or exit_code != 0:
            self._show_failure(exit_code, time_str)
            return

        self.statusLabel.setText("Xử lý hoàn thành!")
        self.add_log(f"✓ Quá trình theo dõi phương tiện hoàn tất trong {time_str}", "SUCCESS")

        if self.autoAddOutputCheckBox.isChecked():
            self.add_outputs_to_map()

        points_file = self._output_dir + "/vehicle_points.geojson"
        tracks_file = self._output_dir + "/vehicle_tracks.geojson"
        segs_file = self._output_dir + "/vehicle_segments.geojson"
        self._show_success_box(
            "Hoàn thành",
            "Quá trình theo dõi phương tiện đã hoàn thành!\n\n"
            f"• Vận tốc trung bình các đoạn: {self.avg_speed:.2f} km/h\n"
            f"• Số lượng phương tiện: {self.total_tracks}\n"
            f"• Tổng điểm phát hiện: {self.total_points}\n"
            f"• Thời gian xử lý: {time_str}\n\n"
            f"Kết quả đã được lưu tại:\n- {points_file}\n- {tracks_file}\n- {segs_file}",
            "",
            self._output_dir,
        )

    def add_outputs_to_map(self) -> bool:
        any_success = False
        self.output_files = []
        tracks_geojson = self._output_dir + "/vehicle_tracks.geojson"
        segs_geojson = self._output_dir + "/vehicle_segments.geojson"
        points_geojson = self._output_dir + "/vehicle_points.geojson"

        if os.path.exists(tracks_geojson):
            self.output_files.append(tracks_geojson)
            layer = QgsVectorLayer(tracks_geojson, "Đường đi phương tiện", "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self.add_log(f"✓ Đã thêm lớp 'Đường đi phương tiện' ({layer.featureCount()} đối tượng)", "SUCCESS")
                any_success = True

        if os.path.exists(segs_geojson):
            self.output_files.append(segs_geojson)
            layer = QgsVectorLayer(segs_geojson, "Từng đoạn phương tiện (vận tốc)", "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self.add_log(f"✓ Đã thêm lớp 'Từng đoạn phương tiện' ({layer.featureCount()} đoạn)", "SUCCESS")
                any_success = True

        if os.path.exists(points_geojson):
            self.output_files.append(points_geojson)
            layer = QgsVectorLayer(points_geojson, "Điểm phương tiện", "ogr")
            if layer.isValid():
                layer.setLabeling(QgsVectorLayerSimpleLabeling(_time_label_settings()))
                layer.setLabelsEnabled(True)
                layer.triggerRepaint()
                QgsProject.instance().addMapLayer(layer)
                self.add_log(
                    f"✓ Đã thêm lớp 'Điểm phương tiện' ({layer.featureCount()} điểm) kèm nhãn ngày giờ chụp",
                    "SUCCESS",
                )
                any_success = True

        if self.map_canvas is not None:
            self.map_canvas.refresh()
        return any_success

    # ----------------------------------------------------------------- log
    @staticmethod
    def format_log_message(message: str, log_type: str) -> str:
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = _LOG_COLORS.get(log_type, "#2c3e50")
        return f"<span style='color: #7f8c8d;'>[{timestamp}]</span> <span style='color: {color};'>{message}</span>"

    def add_log(self, message: str, log_type: str = "INFO"):
        self.logTextEdit.append(self.format_log_message(message, log_type))

    def clear_log(self):
        self.logTextEdit.clear()
        self.add_log("Đã xóa log", "INFO")

    def save_log(self):
        default_name = f"VehicleTracking_Log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu log ra file",
            QDir.currentPath() + "/" + default_name,
            "Text files (*.txt);;All files (*.*)",
        )
        if not file_name:
            return
        try:
            with open(file_name, "w", encoding="utf-8") as f:
                f.write(self.logTextEdit.toPlainText())
        except OSError:
            self.add_log("Lỗi: Không thể lưu file log!", "ERROR")
            QMessageBox.warning(self, "Lỗi", "Không thể lưu file log!")
            return
        self.add_log(f"✓ Đã lưu log vào file: {file_name}", "SUCCESS")


def _time_label_settings() -> QgsPalLayerSettings:
    """"label" field (e.g. 16:21:46.477 28/03/2026) in bold yellow with a black halo."""
    pal = QgsPalLayerSettings()
    pal.fieldName = "label"
    pal.isExpression = False

    text_format = QgsTextFormat()
    font = QFont("Segoe UI", 9)
    font.setBold(True)
    text_format.setFont(font)
    text_format.setColor(QColor(255, 235, 59))

    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.0)
    buffer.setColor(QColor(Qt.GlobalColor.black))
    text_format.setBuffer(buffer)

    pal.setFormat(text_format)
    return pal
