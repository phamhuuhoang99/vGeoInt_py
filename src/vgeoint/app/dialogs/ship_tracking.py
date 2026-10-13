"""Port of ShipTrackingDialog.cpp."""

import os
from datetime import datetime

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QDir, QFileInfo, QStandardPaths
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from vgeoint.ai.runner import model_path
from vgeoint.app.dialogs._tracking_base import TrackingProcessMixin, qnum
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon, settings

Ui_ShipTrackingDialog = load_ui_class("app", "ShipTrackingDialog")

_LOG_ICONS = {"ERROR": "❌", "WARNING": "⚠️", "SUCCESS": "✅", "PROCESS": "🔄", "RESULT": "📊", "SYSTEM": "🔧"}


class ShipTrackingDialog(TrackingProcessMixin, QDialog, Ui_ShipTrackingDialog):
    SCRIPT = "ship_track_detection.py"
    RUNNING_STATUS = "Đang xử lý theo dõi tàu thuyền..."
    STARTED_LOG = ("✓ Tiến trình Python đã khởi động thành công (PID: {pid})", "INFO")

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setModal(True)
        self.setWindowIcon(self.get_icon())
        self.setWindowTitle(self.vn_name())
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.output_files: list[str] = []
        self._input_dir = ""
        self._output_dir = ""
        self._init_process()

        self.progressBar.hide()

        self._model_path = str(model_path("models/Ship_Detection_RGB.pth"))
        self.modelComboBox.clear()
        self.modelComboBox.addItem("Mask R-CNN ResNet50 (Ship_Detection_RGB.pth)", self._model_path)
        self.modelComboBox.setCurrentIndex(0)

        self.confidenceSpinBox.setValue(0.60)
        self.maxDistanceSpinBox.setValue(30000.0)

        self.logTextEdit.setPlainText("")
        self.add_log("Hệ thống theo dõi quỹ đạo tàu thuyền đã sẵn sàng", "SYSTEM")

        s = settings()
        last_input = s.value("ShipTracking/InputDir", "")
        if last_input and QDir(last_input).exists():
            self._input_dir = last_input
            self.inputDirLineEdit.setText(last_input)
        last_output = s.value("ShipTracking/OutputDir", "")
        if last_output:
            self._output_dir = last_output
            self.outputDirLineEdit.setText(last_output)

        self._setup_connections()

    # BPluginInterface
    def name(self) -> str:
        return "T_ShipTracking"

    def vn_name(self) -> str:
        return "Theo dõi tàu thuyền"

    def get_icon(self):
        return get_icon("Engine/Warship.svg")

    def auto_add_output_files(self) -> bool:
        return self.autoAddOutputCheckBox.isChecked()

    def _setup_connections(self):
        self.okButton.clicked.connect(self.apply)
        self.cancelButton.clicked.connect(self.close)
        self.browseInputDirButton.clicked.connect(self.browse_input_dir)
        self.browseOutputDirButton.clicked.connect(self.browse_output_dir)
        self.clearLogButton.clicked.connect(self.clear_log)
        self.saveLogButton.clicked.connect(self.save_log)
        self.modelComboBox.currentIndexChanged.connect(self._model_changed)
        self.inputDirLineEdit.textChanged.connect(self._input_dir_changed)
        self.outputDirLineEdit.textChanged.connect(lambda text: setattr(self, "_output_dir", text.strip()))

    def _model_changed(self, index: int):
        if index >= 0:
            self._model_path = self.modelComboBox.itemData(index)
            self.add_log(f"Đã chọn mô hình: {self.modelComboBox.currentText()}")
            self.add_log(f"Đường dẫn: {self._model_path}")

    def _input_dir_changed(self, text: str):
        self._input_dir = text.strip()
        if not self.outputDirLineEdit.text().strip() and self._input_dir:
            self._output_dir = self._input_dir + "/output"
            self.outputDirLineEdit.setText(self._output_dir)

    def browse_input_dir(self):
        s = settings()
        default_dir = s.value("ShipTracking/InputDir", QApplication.applicationDirPath())
        dir_ = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục chứa ảnh/video theo ngày",
            default_dir,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if dir_:
            self._input_dir = dir_
            self.inputDirLineEdit.setText(dir_)
            s.setValue("ShipTracking/InputDir", dir_)
            self.add_log(f"Đã chọn thư mục đầu vào: {dir_}")
            if not self.outputDirLineEdit.text().strip():
                self._output_dir = dir_ + "/output"
                self.outputDirLineEdit.setText(self._output_dir)
                self.add_log(f"Tự động đặt thư mục đầu ra: {self._output_dir}")

    def browse_output_dir(self):
        s = settings()
        default_dir = s.value(
            "ShipTracking/OutputDir", self._input_dir if self._input_dir else QApplication.applicationDirPath()
        )
        dir_ = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục lưu kết quả",
            default_dir,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if dir_:
            self._output_dir = dir_
            self.outputDirLineEdit.setText(dir_)
            s.setValue("ShipTracking/OutputDir", dir_)
            self.add_log(f"Đã chọn thư mục đầu ra: {dir_}")

    def validate_inputs(self):
        """Raise ValueError with the user message when an input is invalid."""
        self.add_log("Đang kiểm tra các tham số đầu vào...")

        self._input_dir = self.inputDirLineEdit.text().strip()
        if not self._input_dir or not QDir(self._input_dir).exists():
            self.add_log("Lỗi: Thư mục dữ liệu đầu vào không tồn tại!", "ERROR")
            raise ValueError("Vui lòng chọn thư mục dữ liệu đầu vào hợp lệ")
        self.add_log("✓ Thư mục đầu vào hợp lệ")

        if not os.path.isfile(self._model_path):
            self.add_log(f"Lỗi: File mô hình không tồn tại: {self._model_path}", "ERROR")
            raise ValueError(f"File mô hình không tồn tại: {self._model_path}")
        self.add_log("✓ File mô hình hợp lệ")

        self._output_dir = self.outputDirLineEdit.text().strip()
        if not self._output_dir:
            self.add_log("Lỗi: Chưa chọn thư mục lưu kết quả", "ERROR")
            raise ValueError("Vui lòng chọn thư mục lưu kết quả")

        out_dir = QDir(self._output_dir)
        if not out_dir.exists():
            self.add_log("Thư mục đầu ra chưa tồn tại, đang tạo mới...")
            if not out_dir.mkpath("."):
                self.add_log(f"Lỗi: Không thể tạo thư mục đầu ra: {self._output_dir}", "ERROR")
                raise ValueError("Không thể tạo thư mục đầu ra")
            self.add_log("✓ Đã tạo thư mục đầu ra")

        self.add_log("✓ Tất cả tham số đầu vào hợp lệ")

    def apply(self):
        try:
            self.add_log_with_timestamp("=== BẮT ĐẦU QUÁ TRÌNH THEO DÕI TÀU THUYỀN ===", "SYSTEM")
            self.validate_inputs()

            confidence = self.confidenceSpinBox.value()
            max_distance = self.maxDistanceSpinBox.value()

            self.add_log("Tham số xử lý:")
            self.add_log(f"  - Thư mục đầu vào: {self._input_dir}")
            self.add_log(f"  - Mô hình: {self._model_path}")
            self.add_log(f"  - Ngưỡng tin cậy: {qnum(confidence)}")
            self.add_log(f"  - Khoảng cách ghép tối đa: {qnum(max_distance)} m")
            self.add_log(f"  - Thư mục đầu ra: {self._output_dir}")

            self._run_python_script(
                [
                    "--input-dir", self._input_dir,
                    "--model", self._model_path,
                    "--output-dir", self._output_dir,
                    "--confidence", qnum(confidence),
                    "--max-distance", qnum(max_distance),
                ]
            )  # fmt: skip
        except ValueError as e:
            self.add_log(f"Lỗi: {e}", "ERROR")
            QMessageBox.critical(self, "Lỗi", str(e))

    # ------------------------------------------------------------- process
    def _on_stdout(self, line: str):
        line = line.strip()
        if not line:
            return
        if "[OK]" in line or line.startswith("Loading weights"):
            self.add_log(f"🔄 {line}", "PROCESS")
        elif line.startswith("Found ") and "sequential data files" in line:
            self.add_log(f"📁 {line}", "PROCESS")
        elif line.startswith("Detecting ships for date"):
            self.add_log(f"🔍 {line}", "PROCESS")
        elif "Detected" in line and "ship centroids" in line:
            self.add_log(f"🚢 {line}", "RESULT")
        elif "Built" in line and "ship trajectories" in line:
            self.add_log(f"📈 {line}", "RESULT")
        elif "File duong di" in line or "File tam thuyen" in line:
            self.add_log(f"💾 {line}", "RESULT")
        elif "completed successfully" in line or "Process Finished" in line:
            self.add_log("✅ Xử lý hoàn tất thành công!", "SUCCESS")
        else:
            clean = line.replace("[OK]", "✓").replace("[ERROR]", "❌").replace("[WARN]", "⚠️")
            self.add_log(f"Python: {clean}", "PROCESS")

    def _on_stderr(self, line: str):
        line = line.strip()
        if not line:
            return
        if "Missing dependencies:" in line:
            self.add_log(f"❌ Thiếu thư viện Python: {line}", "ERROR")
        elif "Error" in line or "ERROR" in line:
            self.add_log(f"❌ Lỗi: {line}", "ERROR")
        elif "Warning" in line or "WARNING" in line:
            self.add_log(f"⚠️ Cảnh báo: {line}", "WARNING")
        else:
            self.add_log(f"Python stderr: {line}", "ERROR")

    def _on_event(self, event: dict):
        # The dialog reads the output files from the output folder; the result event is informative only.
        pass

    def _progress_text(self, seconds: int) -> str:
        return f"Đang xử lý theo dõi tàu thuyền... ({seconds}s)"

    def _on_process_finished(self, exit_code: int, crashed: bool):
        self._progress_timer.stop()
        ms = self.elapsed_ms()
        time_str = f"{ms // 1000}.{(ms % 1000) // 100}s"

        self.add_log_with_timestamp("=== KẾT THÚC TIẾN TRÌNH XỬ LÝ ===", "SYSTEM")
        self.add_log(f"Thời gian thực hiện: {time_str}")
        self.add_log(f"Mã thoát (Exit code): {exit_code}")
        self.add_log(f"Trạng thái: {'Crashed' if crashed else 'Normal'}")

        self.progressBar.hide()
        self._set_running(False)

        if crashed or exit_code != 0:
            self._show_failure(exit_code, time_str)
            return

        self.statusLabel.setText("Hoàn thành thành công!")
        self.add_log("✅ Quá trình theo dõi tàu thuyền đã hoàn tất thành công!", "SUCCESS")

        if self.auto_add_output_files():
            self.add_log("🗺️ Đang thêm các lớp kết quả vào bản đồ...", "SYSTEM")
            if self.add_outputs_to_map():
                self.add_log("✅ Đã thêm các lớp kết quả vào bản đồ thành công", "SUCCESS")
            else:
                self.add_log("⚠️ Không thể nạp một số lớp kết quả vào bản đồ", "WARNING")
            QApplication.beep()
            # C++ emitted complete() here; MainController would add the files a second time, so the
            # layers are only added by add_outputs_to_map() as in the C++ app.

        lines_file = self._output_dir + "/ship_trajectories_lines.geojson"
        points_file = self._output_dir + "/ship_centroids_points.geojson"
        self._show_success_box(
            self.vn_name(),
            "Theo dõi tàu thuyền hoàn tất thành công!",
            f"Kết quả được lưu tại:\n- {lines_file}\n- {points_file}\nThời gian xử lý: {time_str}",
            self._output_dir,
        )

    def add_outputs_to_map(self) -> bool:
        any_success = False
        self.output_files = []
        lines_geojson = self._output_dir + "/ship_trajectories_lines.geojson"
        points_geojson = self._output_dir + "/ship_centroids_points.geojson"

        if os.path.exists(lines_geojson):
            self.output_files.append(lines_geojson)
            layer = QgsVectorLayer(lines_geojson, "Đường đi tàu thuyền", "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self.add_log(f"✓ Đã thêm lớp 'Đường đi tàu thuyền' ({layer.featureCount()} đối tượng)", "SUCCESS")
                any_success = True

        if os.path.exists(points_geojson):
            self.output_files.append(points_geojson)
            layer = QgsVectorLayer(points_geojson, "Tâm vị trí tàu thuyền", "ogr")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self.add_log(f"✓ Đã thêm lớp 'Tâm vị trí tàu thuyền' ({layer.featureCount()} điểm)", "SUCCESS")
                any_success = True

        if self.map_canvas is not None:
            self.map_canvas.refresh()
        return any_success

    # ----------------------------------------------------------------- log
    @staticmethod
    def format_log_message(message: str, log_type: str) -> str:
        timestamp = datetime.now().strftime("%H:%M:%S")
        return f"[{timestamp}] {_LOG_ICONS.get(log_type, 'ℹ️')} {message}"

    def add_log(self, message: str, log_type: str = "INFO"):
        self.logTextEdit.append(self.format_log_message(message, log_type))
        bar = self.logTextEdit.verticalScrollBar()
        bar.setValue(bar.maximum())

    def add_log_with_timestamp(self, message: str, log_type: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.add_log(f"[{timestamp}] {message}", log_type)

    def clear_log(self):
        self.logTextEdit.clear()
        self.add_log("Log đã được xóa", "SYSTEM")

    def save_log(self):
        s = settings()
        default_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        dir_ = s.value("ShipTracking/LogDir", default_dir)
        default_name = f"ship_tracking_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Lưu log", QDir(dir_).filePath(default_name), "Text files (*.txt);;All files (*)"
        )
        if not file_name:
            return
        try:
            with open(file_name, "w", encoding="utf-8") as f:
                f.write("=== vGeoInt_v2 Ship Tracking Log ===\n")
                f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Version: {QApplication.applicationVersion()}\n")
                f.write("========================================\n\n")
                f.write(self.logTextEdit.toPlainText())
        except OSError:
            self.add_log("❌ Lỗi: Không thể ghi file log", "ERROR")
            return
        self.add_log(f"✅ Log đã được lưu: {QFileInfo(file_name).fileName()}", "SUCCESS")
        s.setValue("ShipTracking/LogDir", QFileInfo(file_name).dir().path())
