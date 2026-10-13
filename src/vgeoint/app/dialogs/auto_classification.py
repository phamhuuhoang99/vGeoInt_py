"""Port of AutoClassificationDialog.cpp."""

from qgis.core import QgsProject, QgsRasterLayer
from qgis.PyQt.QtCore import QDateTime, QDir, QFileInfo, QStandardPaths, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox

from vgeoint.ai.runner import ScriptRunner, model_path
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon

Ui_AutoClassificationDialog = load_ui_class("app", "AutoClassificationDialog")

_LOG_STYLES = {
    "ERROR": ("[LỖI]", QColor(255, 0, 0)),
    "WARNING": ("[CẢNH BÁO]", QColor(255, 165, 0)),
    "SUCCESS": ("[THÀNH CÔNG]", QColor(0, 128, 0)),
    "SYSTEM": ("[HỆ THỐNG]", QColor(128, 0, 128)),
    "PROCESS": ("[XỬ LÝ]", QColor(0, 0, 255)),
    "RESULT": ("[KẾT QUẢ]", QColor(0, 128, 128)),
}

# (substring or prefix, log text, log type) checked in order after the ERROR/WARNING tests
_KNOWN_LINES = (
    ("startswith", "Mô hình đã được tải", "✅ Đã tải mô hình Random Forest", "SUCCESS"),
    ("startswith", "Ảnh TIFF đã được tải", "✅ Đã tải ảnh đầu vào", "SUCCESS"),
    ("contains", "Phân loại ảnh hoàn tất", "✅ Phân loại ảnh hoàn tất", "SUCCESS"),
    ("contains", "Áp dụng mặt nạ", "🔄 Đang áp dụng mặt nạ cho kết quả", "PROCESS"),
    ("contains", "Kết quả phân loại đã được lưu", "💾 Đã lưu kết quả phân loại", "SUCCESS"),
    ("contains", "Ảnh phân loại với style unique values", "🎨 Đã tạo ảnh phân loại với màu sắc", "SUCCESS"),
)

MODEL = "models/random_forest_model_s2.joblib"


class AutoClassificationDialog(QDialog, Ui_AutoClassificationDialog):
    # No `complete` signal: like the C++ dialog, results are added to the map by the dialog itself.

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setModal(True)
        self.setWindowIcon(self.get_icon())
        self.setWindowTitle(self.vn_name())
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.model_path = ""
        self.output_path = ""
        self.output_files: list[str] = []
        self._raster_layers: list[QgsRasterLayer] = []
        self._process_start_time = QDateTime()
        self._runner: ScriptRunner | None = None
        self._started = False

        self.progressBar.hide()

        self.modelComboBox.clear()
        self.modelComboBox.addItem("Random Forest")
        if self.modelComboBox.currentIndex() == 0:
            self.model_path = str(model_path(MODEL))

        self.logTextEdit.setPlainText("")
        self.add_log("Hệ thống phân loại tự động đã sẵn sàng", "SYSTEM")

        self._progress_timer = QTimer(self)
        self._progress_timer.setSingleShot(False)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self.update_process_progress)

        self._setup_connections()
        self.update_layers_list()

    # BPluginInterface
    def name(self) -> str:
        return "AutoClassification"

    def vn_name(self) -> str:
        return "Phân loại tự động"

    def get_icon(self):
        return get_icon("AutoClassification.svg")

    def auto_add_output_files(self) -> bool:
        return self.autoAddOutputCheckBox.isChecked()

    def _setup_connections(self):
        self.okButton.clicked.connect(self.apply)
        self.cancelButton.clicked.connect(self.close)
        self.browseOutputButton.clicked.connect(self.browse_output)
        self.clearLogButton.clicked.connect(self.clear_log)
        self.saveLogButton.clicked.connect(self.save_log)
        self.inputLayerComboBox.currentIndexChanged.connect(self._layer_selected)

    def _layer_selected(self, index: int):
        if 0 <= index < len(self._raster_layers):
            layer = self._raster_layers[index]
            self.add_log(f"Đã chọn layer: {layer.name()}")
            info = QFileInfo(layer.source())
            self.output_path = QDir(info.absolutePath()).filePath(info.completeBaseName() + "_classified.tif")
            self.outputPathLineEdit.setText(self.output_path)

    def update_layers_list(self):
        self.inputLayerComboBox.clear()
        self._raster_layers.clear()

        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer) and layer.isValid():
                self._raster_layers.append(layer)
                self.inputLayerComboBox.addItem(layer.name())

        self.okButton.setEnabled(bool(self._raster_layers))
        if not self._raster_layers:
            self.add_log("Không tìm thấy layer ảnh nào trong dự án", "WARNING")
        else:
            self.add_log(f"Đã tìm thấy {len(self._raster_layers)} layer ảnh")
            self.inputLayerComboBox.setCurrentIndex(0)

    def apply(self):
        index = self.inputLayerComboBox.currentIndex()
        if index < 0 or index >= len(self._raster_layers):
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn một layer ảnh để phân loại")
            return
        if not self.model_path or not QFileInfo.exists(self.model_path):
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn một mô hình Random Forest hợp lệ")
            return
        if not self.output_path:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn đường dẫn lưu kết quả")
            return
        self.start_process()

    def browse_output(self):
        default_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if self.output_path:
            default_dir = QFileInfo(self.output_path).absolutePath()

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Chọn vị trí lưu kết quả", default_dir, "GeoTIFF (*.tif *.tiff)"
        )
        if file_path:
            self.output_path = file_path
            self.outputPathLineEdit.setText(self.output_path)
            self.add_log(f"Đã chọn đường dẫn lưu kết quả: {self.output_path}")

    def clear_log(self):
        self.logTextEdit.clear()
        self.add_log("Đã xóa log", "SYSTEM")

    def save_log(self):
        default_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_hhmmss")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu log",
            QDir(default_dir).filePath(f"auto_classification_log_{timestamp}.txt"),
            "Text Files (*.txt)",
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.logTextEdit.toPlainText())
                self.add_log(f"Đã lưu log vào: {file_path}", "SUCCESS")
            except OSError:
                self.add_log(f"Không thể lưu log vào: {file_path}", "ERROR")

    def add_log(self, message: str, log_type: str = "INFO"):
        prefix, color = _LOG_STYLES.get(log_type, ("[THÔNG TIN]", QColor(0, 0, 0)))
        self.logTextEdit.setTextColor(color)
        self.logTextEdit.append(f"{prefix} {message}")
        bar = self.logTextEdit.verticalScrollBar()
        bar.setValue(bar.maximum())

    def add_log_with_timestamp(self, message: str, log_type: str = "INFO"):
        timestamp = QDateTime.currentDateTime().toString("[hh:mm:ss]")
        self.add_log(f"{timestamp} {message}", log_type)

    # ---------------------------------------------------------------- process
    def start_process(self):
        if self._runner is not None and self._runner.is_running():
            QMessageBox.warning(
                self, "Cảnh báo", "Quá trình xử lý đang chạy. Vui lòng đợi hoặc hủy quá trình hiện tại."
            )
            return

        index = self.inputLayerComboBox.currentIndex()
        if index < 0 or index >= len(self._raster_layers):
            return
        input_path = self._raster_layers[index].source()

        self.output_files.clear()

        if self._runner is None:
            self._runner = ScriptRunner(self)
            self._runner.output_line.connect(self.read_process_output)
            self._runner.error_line.connect(lambda line: self.add_log(line.strip(), "ERROR"))
            self._runner.event_received.connect(self._on_event)
            self._runner.started.connect(self._on_started)
            self._runner.finished.connect(self._on_finished)

        self.okButton.setEnabled(False)
        self.progressBar.setValue(0)
        self.progressBar.setVisible(True)
        self.update_status("Đang xử lý...")
        self.add_log_with_timestamp("=== BẮT ĐẦU QUÁ TRÌNH PHÂN LOẠI ===", "SYSTEM")

        arguments = ["--input", input_path, "--model", self.model_path, "--output", self.output_path]
        want_colored = self.auto_add_output_files()
        if want_colored:
            arguments.append("--colored")

        self.output_files.append(self.output_path)
        info = QFileInfo(self.output_path)
        if want_colored:
            self.output_files.append(info.absolutePath() + "/" + info.completeBaseName() + "_unique_values.tif")

        self._process_start_time = QDateTime.currentDateTime()
        self._started = False
        self._runner.start_script("auto_classification.py", arguments)

    def _on_started(self):
        self._started = True
        self._progress_timer.start()
        self.add_log("Đã khởi động quá trình phân loại", "PROCESS")

    def stop_process(self):
        if self._runner is not None and self._runner.is_running():
            self._runner.kill()
            self.add_log("Đã dừng quá trình xử lý", "WARNING")
        self._progress_timer.stop()
        self.okButton.setEnabled(True)
        self.progressBar.setVisible(False)
        self.update_status("Đã dừng")

    def update_status(self, status: str):
        self.statusLabel.setText(status)

    def update_process_progress(self):
        if self._runner is None or not self._runner.is_running():
            return
        seconds = self._process_start_time.msecsTo(QDateTime.currentDateTime()) // 1000
        minutes, seconds = divmod(seconds, 60)
        self.progressBar.setMaximum(0)
        self.progressBar.setValue(0)
        self.update_status(f"Đang xử lý... ({minutes:02d}:{seconds:02d})")

    def _on_event(self, event: dict):
        # The script reports the files it actually wrote (C++ derived the colored name itself).
        if event.get("type") == "result" and event.get("output"):
            self.output_files = [event["output"]] + ([event["colored"]] if event.get("colored") else [])

    def _on_finished(self, exit_code: int, crashed: bool):
        self._progress_timer.stop()
        if crashed:
            self.okButton.setEnabled(True)
            self.progressBar.setVisible(False)
            self.handle_process_error(started=self._started)
            return

        if exit_code == 0:
            self.add_log_with_timestamp("=== QUÁ TRÌNH PHÂN LOẠI HOÀN TẤT ===", "SUCCESS")
            self.update_status("Hoàn tất")

            if self.auto_add_output_files():
                for output_file in self.output_files:
                    if QFileInfo.exists(output_file):
                        layer_name = QFileInfo(output_file).completeBaseName()
                        layer = QgsRasterLayer(output_file, layer_name)
                        if layer.isValid():
                            QgsProject.instance().addMapLayer(layer)
                            self.add_log(f"Đã thêm layer kết quả vào bản đồ: {layer_name}", "SUCCESS")
                        else:
                            self.add_log(f"Không thể thêm layer kết quả vào bản đồ: {layer_name}", "ERROR")

            QMessageBox.information(self, "Thành công", "Quá trình phân loại đã hoàn tất thành công!")
        else:
            self.add_log_with_timestamp("=== QUÁ TRÌNH PHÂN LOẠI THẤT BẠI ===", "ERROR")
            self.update_status("Lỗi")
            QMessageBox.critical(
                self, "Lỗi", "Quá trình phân loại gặp lỗi. Vui lòng kiểm tra log để biết thêm chi tiết."
            )

        self.okButton.setEnabled(True)
        self.progressBar.setVisible(False)

    def read_process_output(self, line: str):
        trimmed = line.strip()
        if not trimmed:
            return
        lower = trimmed.lower()
        if "error" in lower or "lỗi" in lower:
            self.add_log(trimmed, "ERROR")
            return
        if "warning" in lower or "cảnh báo" in lower:
            self.add_log(trimmed, "WARNING")
            return
        for mode, needle, text, log_type in _KNOWN_LINES:
            if (trimmed.startswith(needle) if mode == "startswith" else needle in trimmed):
                self.add_log(text, log_type)
                return
        if "Kích thước ảnh" in trimmed:
            self.add_log(f"ℹ️ {trimmed}", "INFO")
        elif "Bắt đầu xử lý ảnh" in trimmed:
            self.add_log("🔄 Bắt đầu xử lý ảnh đầu vào", "PROCESS")
        elif "Kết thúc xử lý ảnh" in trimmed:
            self.add_log("✅ Kết thúc xử lý ảnh", "SUCCESS")
        elif "Quy trình phân loại hoàn tất" in trimmed:
            self.add_log("✅ Quy trình phân loại hoàn tất thành công", "SUCCESS")
        elif "Đã tạo ảnh phân loại với style unique values" in trimmed:
            self.add_log("🎨 Đã tạo ảnh phân loại với màu sắc", "SUCCESS")
        elif any(c in trimmed for c in ("1: Dân cư", "2: Thực vật", "3: Giao thông", "4: Thủy hệ")):
            self.add_log(f"🏷️ {trimmed}", "RESULT")
        else:
            self.add_log(trimmed)

    def handle_process_error(self, started: bool):
        """QProcess::FailedToStart when the interpreter never started, otherwise QProcess::Crashed."""
        if not started:
            error_msg = (
                "Không thể khởi động quá trình Python. Vui lòng kiểm tra:\n"
                "- Python đã được cài đặt\n"
                "- Thư viện random_forest.py tồn tại"
            )
            self.add_log("❌ Lỗi khởi động Python process", "ERROR")
        else:
            error_msg = "Quá trình Python bị crash bất ngờ"
            self.add_log("💥 Python process bị crash", "ERROR")

        self.update_status("Xử lý thất bại!")
        self.add_log_with_timestamp("=== QUÁ TRÌNH XỬ LÝ BỊ GIÁN ĐOẠN ===", "SYSTEM")
        QMessageBox.critical(self, "Lỗi", error_msg)

    def get_output_path(self) -> str:
        return self.output_path

    def get_model_path(self) -> str:
        return self.model_path

    def done(self, result: int):
        # The C++ QProcess child was killed when the dialog was destroyed; stop it explicitly here.
        if self._runner is not None and self._runner.is_running():
            self._runner.finished.disconnect(self._on_finished)
            self._runner.kill()
            self._progress_timer.stop()
        super().done(result)
