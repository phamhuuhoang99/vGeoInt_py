"""Shared code of ShipDetectionDialog.cpp / TankDetectionDialog.cpp (and BuildingSegmentationDialog.cpp).

The C++ ship and tank dialogs were line-for-line copies; the building segmentation dialog reuses the
same log, layer-list and process handling. `AiScriptDialog` holds the common part, `YoloDetectionDialog`
the ship/tank dialog, parametrized by class attributes.
"""

import time
from datetime import datetime

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtCore import QDir, QFileInfo, QProcess, QStandardPaths, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from vgeoint.ai.runner import ScriptRunner, model_path, script_path
from vgeoint.common.utils import get_icon, settings

_LOG_ICONS = {"ERROR": "❌", "WARNING": "⚠️", "SUCCESS": "✅", "PROCESS": "🔄", "RESULT": "📊", "SYSTEM": "🔧"}


class InputError(Exception):
    """Invalid dialog input (std::runtime_error in the C++ dialogs)."""


class AiScriptDialog(QDialog):
    """Log area, raster layer list, Python process lifecycle. Subclasses also inherit their Ui_ class."""

    complete = pyqtSignal()

    NAME = ""  # settings group / plugin name
    VN_NAME = ""
    ICON = ""
    SCRIPT = ""
    MODEL = ""  # model path as written in the C++ code ("models/...")
    MODEL_TEXT = ""
    MODEL_KIND = ""  # "YOLO" / "UNet" in the validation log
    READY_TEXT = ""
    START_TEXT = ""
    ERROR_STATUS_TEXT = "Xử lý thất bại!"
    LOG_INTERRUPTED = True  # log "=== QUÁ TRÌNH XỬ LÝ BỊ GIÁN ĐOẠN ===" on process errors

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setModal(True)
        self.setWindowIcon(get_icon(self.ICON))
        self.setWindowTitle(self.VN_NAME)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.raster_layers: list[QgsRasterLayer] = []
        self.output_path = ""
        self.output_files: list[str] = []
        self._start_time = time.monotonic()
        self._process_started = False

        self.progressBar.hide()

        self.model_path = str(model_path(self.MODEL))
        self.modelComboBox.clear()
        self.modelComboBox.addItem(self.MODEL_TEXT, self.model_path)
        self.modelComboBox.setCurrentIndex(0)
        self.init_parameters()

        self.logTextEdit.setPlainText("")
        self.add_log(self.READY_TEXT, "SYSTEM")

        self.progress_timer = QTimer(self)
        self.progress_timer.setSingleShot(False)
        self.progress_timer.setInterval(1000)
        self.progress_timer.timeout.connect(self.update_process_progress)

        self.runner = ScriptRunner(self)
        self.runner.output_line.connect(self.on_stdout_line)
        self.runner.error_line.connect(self.on_stderr_line)
        self.runner.event_received.connect(self.on_event)
        self.runner.started.connect(self._on_started)
        self.runner.finished.connect(self._on_finished)
        self.runner.process.errorOccurred.connect(self._on_error_occurred)

        self.setup_connections()
        self.update_layers_list()

    # ------------------------------------------------------------- hooks
    def init_parameters(self):
        pass

    def on_input_layer_changed(self, index: int):
        raise NotImplementedError

    def on_stdout_line(self, line: str):
        raise NotImplementedError

    def on_stderr_line(self, line: str):
        raise NotImplementedError

    def on_event(self, event: dict):
        pass

    def on_process_finished(self, exit_code: int, crashed: bool):
        raise NotImplementedError

    # ------------------------------------------------------------- setup
    def setup_connections(self):
        self.okButton.clicked.connect(self.apply)
        self.cancelButton.clicked.connect(self.close)
        self.browseOutputButton.clicked.connect(self.browse_output)
        self.clearLogButton.clicked.connect(self.clear_log)
        self.saveLogButton.clicked.connect(self.save_log)
        self.modelComboBox.currentIndexChanged.connect(self._on_model_changed)
        self.inputLayerComboBox.currentIndexChanged.connect(self.on_input_layer_changed)

    def _on_model_changed(self, index: int):
        if index >= 0:
            self.model_path = self.modelComboBox.itemData(index)
            self.add_log(f"Đã chọn mô hình: {self.modelComboBox.currentText()}")
            self.add_log(f"Đường dẫn: {self.model_path}")

    def update_layers_list(self):
        self.raster_layers.clear()
        self.inputLayerComboBox.clear()
        self.add_log("Đang quét các layer raster có sẵn...")

        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer) and layer.dataProvider() and layer.dataProvider().name() == "gdal":
                self.raster_layers.append(layer)
                self.inputLayerComboBox.addItem(get_icon("Raster.svg"), layer.name())

        self.add_log(f"Tìm thấy {len(self.raster_layers)} layer raster hợp lệ")

        selected = self.layer_tree_view.selectedLayers() if self.layer_tree_view else []
        if selected and isinstance(selected[0], QgsRasterLayer) and selected[0] in self.raster_layers:
            self.inputLayerComboBox.setCurrentIndex(self.raster_layers.index(selected[0]))
            self.add_log(f"Tự động chọn layer hiện tại: {selected[0].name()}")

        if not self.raster_layers:
            self.add_log("Không tìm thấy layer raster nào. Vui lòng thêm ảnh vào project.", "WARNING")

    def current_layer(self) -> QgsRasterLayer | None:
        index = self.inputLayerComboBox.currentIndex()
        return self.raster_layers[index] if 0 <= index < len(self.raster_layers) else None

    # ------------------------------------------------------------- log
    @staticmethod
    def format_log_message(message: str, type_: str) -> str:
        timestamp = datetime.now().strftime("%H:%M:%S")
        return f"[{timestamp}] {_LOG_ICONS.get(type_, 'ℹ️')} {message}"

    def add_log(self, message: str, type_: str = "INFO"):
        self.logTextEdit.append(self.format_log_message(message, type_))
        bar = self.logTextEdit.verticalScrollBar()
        bar.setValue(bar.maximum())
        # The C++ called QApplication::processEvents() here; log lines now arrive from ScriptRunner
        # signals, and re-entering the event loop while it reads output can corrupt its state.

    def add_log_with_timestamp(self, message: str, type_: str = "INFO"):
        self.add_log(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", type_)

    def clear_log(self):
        self.logTextEdit.clear()
        self.add_log("Log đã được xóa", "SYSTEM")

    @staticmethod
    def documents_dir() -> str:
        return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)

    def write_log_file(self, file_name: str, header: str) -> bool:
        try:
            with open(file_name, "w", encoding="utf-8") as f:
                f.write(header)
                f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Version: {QApplication.applicationVersion()}\n")
                f.write("========================================\n\n")
                f.write(self.logTextEdit.toPlainText())
            return True
        except OSError:
            return False

    # ------------------------------------------------------------- run
    def validate_inputs(self):
        self.add_log("Đang kiểm tra các tham số đầu vào...")

        if self.inputLayerComboBox.currentIndex() < 0:
            self.add_log("Lỗi: Chưa chọn layer đầu vào", "ERROR")
            raise InputError("Vui lòng chọn layer đầu vào")
        self.add_log("✓ Layer đầu vào hợp lệ")

        if not QFileInfo(self.model_path).exists():
            self.add_log(f"Lỗi: File mô hình không tồn tại: {self.model_path}", "ERROR")
            raise InputError(f"File mô hình không tồn tại: {self.model_path}")
        self.add_log(f"✓ Mô hình {self.MODEL_KIND} hợp lệ")

        if not self.output_path:
            self.add_log("Lỗi: Chưa chọn đường dẫn đầu ra", "ERROR")
            raise InputError("Vui lòng chọn đường dẫn đầu ra")
        self.add_log("✓ Đường dẫn đầu ra hợp lệ")

        output_dir = QFileInfo(self.output_path).dir()
        if not output_dir.exists():
            self.add_log("Thư mục đầu ra không tồn tại, đang tạo...")
            if not output_dir.mkpath("."):
                self.add_log("Lỗi: Không thể tạo thư mục đầu ra", "ERROR")
                raise InputError("Không thể tạo thư mục đầu ra")
            self.add_log("✓ Đã tạo thư mục đầu ra")

        self.add_log("✓ Tất cả tham số đầu vào hợp lệ")

    def processing_parameters(self, layer: QgsRasterLayer) -> list[str]:
        return [
            f"  - Layer: {layer.name()}",
            f"  - Đường dẫn ảnh: {layer.source()}",
            f"  - Mô hình: {QFileInfo(self.model_path).fileName()}",
        ]

    def script_arguments(self, input_path: str) -> list[str]:
        return ["--input", input_path, "--model", self.model_path, "--output", self.output_path]

    def apply(self):
        try:
            self.add_log_with_timestamp(self.START_TEXT, "SYSTEM")
            self.validate_inputs()
            layer = self.current_layer()
            self.add_log("Tham số xử lý:")
            for line in self.processing_parameters(layer):
                self.add_log(line)
            self.add_log(f"  - Đầu ra: {self.output_path}")
            self.run_python_script(self.script_arguments(layer.source()))
        except InputError as e:
            self.add_log(f"Lỗi: {e}", "ERROR")
            QMessageBox.critical(self, "Lỗi", str(e))

    def run_python_script(self, arguments: list[str]):
        self.add_log("Khởi tạo Python process...")
        self._start_time = time.monotonic()
        self.progressBar.show()
        self.progressBar.setMaximum(0)
        self.statusLabel.setText("Đang xử lý...")
        self.progress_timer.start()
        self.okButton.setEnabled(False)
        self.browseOutputButton.setEnabled(False)

        script = script_path(self.SCRIPT)
        self.add_log(f"Script Python: {script}")
        if not script.exists():
            self.add_log("Lỗi: Script Python không tồn tại!", "ERROR")
            self.on_process_error(QProcess.ProcessError.FailedToStart)
            return

        self.add_log("Tham số dòng lệnh:")
        self.add_log(f"  python {' '.join([str(script), *arguments])}")
        self.add_log("Khởi động Python process...")
        self._process_started = False
        self.runner.start_script(self.SCRIPT, arguments)

    def _on_started(self):
        self._process_started = True
        self.add_log("✓ Python process đã khởi động thành công")
        self.add_log(f"Process ID: {self.runner.process.processId()}")

    def _on_error_occurred(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.add_log("Lỗi: Không thể khởi động Python process", "ERROR")
        self.on_process_error(error)

    def _on_finished(self, exit_code: int, crashed: bool):
        if self._process_started:  # FailedToStart is reported by _on_error_occurred
            self.on_process_finished(exit_code, crashed)

    def elapsed_text(self) -> str:
        ms = int((time.monotonic() - self._start_time) * 1000)
        return f"{ms // 1000}.{(ms % 1000) // 100}s"

    def on_process_error(self, error):
        self.progress_timer.stop()
        self.progressBar.hide()
        self.okButton.setEnabled(True)
        self.browseOutputButton.setEnabled(True)

        Err = QProcess.ProcessError
        if error == Err.FailedToStart:
            message = (
                "Không thể khởi động Python. Vui lòng kiểm tra:\n"
                "- Python đã được cài đặt\n"
                "- Python có trong PATH\n"
                f"- Script {self.SCRIPT} tồn tại"
            )
            self.add_log("❌ Lỗi khởi động Python process", "ERROR")
        elif error == Err.Crashed:
            message = "Quá trình Python bị crash bất ngờ"
            self.add_log("💥 Python process bị crash", "ERROR")
        elif error == Err.Timedout:
            message = "Quá trình xử lý bị timeout"
            self.add_log("⏰ Timeout trong quá trình xử lý", "ERROR")
        elif error == Err.ReadError:
            message = "Lỗi đọc dữ liệu từ process"
            self.add_log("📖 Lỗi đọc output từ Python process", "ERROR")
        elif error == Err.WriteError:
            message = "Lỗi ghi dữ liệu vào process"
            self.add_log("✍️ Lỗi ghi input vào Python process", "ERROR")
        else:
            message = "Lỗi không xác định trong quá trình xử lý"
            self.add_log("❓ Lỗi không xác định", "ERROR")

        self.statusLabel.setText(self.ERROR_STATUS_TEXT)
        if self.LOG_INTERRUPTED:
            self.add_log_with_timestamp("=== QUÁ TRÌNH XỬ LÝ BỊ GIÁN ĐOẠN ===", "SYSTEM")
        QMessageBox.critical(self, "Lỗi", message)

    def update_process_progress(self):
        if not self.runner.is_running():
            return
        self.statusLabel.setText(f"Đang xử lý... ({int(time.monotonic() - self._start_time)}s)")
        info = QFileInfo(self.output_path) if self.output_path else None
        if info and info.exists() and info.size() > 0:
            self.add_log(f"📈 File đầu ra đang được tạo... ({info.size() / 1024.0:.1f} KB)", "PROGRESS")

    def failure_details(self, exit_code: int, time_str: str):
        self.statusLabel.setText("Xử lý thất bại!")
        self.add_log("❌ Quá trình xử lý thất bại!", "ERROR")
        # stderr was already streamed to the log line by line (C++ re-read the leftover here).
        QMessageBox.critical(
            self,
            "Lỗi",
            f"Xử lý thất bại!\n\nMã lỗi: {exit_code}\nThời gian xử lý: {time_str}\n\n"
            "Vui lòng kiểm tra log để biết chi tiết.",
        )

    def log_finished_header(self, exit_code: int, crashed: bool) -> str:
        self.progress_timer.stop()
        time_str = self.elapsed_text()
        self.add_log_with_timestamp("=== KẾT THÚC QUÁ TRÌNH XỬ LÝ ===", "SYSTEM")
        self.add_log(f"Thời gian xử lý: {time_str}")
        self.add_log(f"Mã thoát: {exit_code}")
        self.add_log(f"Trạng thái: {'Crashed' if crashed else 'Normal'}")
        self.progressBar.hide()
        self.okButton.setEnabled(True)
        self.browseOutputButton.setEnabled(True)
        return time_str

    def add_layer_to_project(self, layer, layer_name: str):
        QgsProject.instance().addMapLayer(layer)
        self.add_log(f"🗺️ Đã thêm layer '{layer_name}' vào project", "SUCCESS")
        if self.map_canvas:
            self.map_canvas.refresh()
            self.add_log("🔄 Đã làm mới bản đồ", "SUCCESS")

    # ------------------------------------------------------------- close
    def stop_process(self):
        """The C++ destructor killed a running process; do it when the dialog closes."""
        self.progress_timer.stop()
        if self.runner.is_running():
            self.add_log("🛑 Đang dừng Python process...", "SYSTEM")
            # No finished/crash message boxes for a process the user abandoned.
            self.runner.blockSignals(True)
            self.runner.process.blockSignals(True)
            self.runner.kill()
            self.runner.process.blockSignals(False)
            self.runner.blockSignals(False)
            self.progressBar.hide()
            self.okButton.setEnabled(True)
            self.browseOutputButton.setEnabled(True)

    def done(self, result):
        self.stop_process()
        super().done(result)

    def closeEvent(self, event):
        self.stop_process()
        super().closeEvent(event)


class YoloDetectionDialog(AiScriptDialog):
    """ShipDetectionDialog / TankDetectionDialog."""

    MODEL_TEXT = "YOLOv8"
    MODEL_KIND = "YOLO"
    OBJECT_TEXT = ""  # "tàu thuyền" / "xe tăng"
    OUTPUT_TAG = ""  # "ships" / "tanks"
    LOG_TITLE = ""  # "Ship Detection" / "Tank Detection"
    LOG_PREFIX = ""  # "ship_detection" / "tank_detection"

    def init_parameters(self):
        self.confidenceSpinBox.setValue(0.5)

    def auto_add_enabled(self) -> bool:
        # Not named auto_add_output_files: the dialog adds its output itself (as in C++, where
        # MainController never connected `complete`), so MainController must not add it again.
        return self.autoAddOutputCheckBox.isChecked()

    def is_geotiff(self, file_path: str) -> bool:
        if QFileInfo(file_path).suffix().lower() not in ("tif", "tiff"):
            return False
        layer = self.current_layer()
        return layer.crs().isValid() if layer else True

    def on_input_layer_changed(self, index: int):
        if not 0 <= index < len(self.raster_layers):
            return
        layer = self.raster_layers[index]
        path = layer.source()
        self.add_log(f"Đã chọn layer: {layer.name()}")
        self.add_log(f"Đường dẫn: {path}")

        info = QFileInfo(path)
        base, directory = info.completeBaseName(), info.dir().path()
        if self.is_geotiff(path):
            self.output_path = f"{directory}/{base}_{self.OUTPUT_TAG}.shp"
            self.outputPathLineEdit.setText(self.output_path)
            self.outputTypeLabel.setText("Đầu ra: Shapefile (.shp)")
            self.add_log("Phát hiện GeoTIFF - sẽ tạo Shapefile", "INFO")
        else:
            self.output_path = f"{directory}/{base}_{self.OUTPUT_TAG}_detected.jpg"
            self.outputPathLineEdit.setText(self.output_path)
            self.outputTypeLabel.setText("Đầu ra: Ảnh kết quả (.jpg)")
            self.add_log("Phát hiện ảnh thường - sẽ tạo ảnh có chú thích", "INFO")
        self.add_log(f"Đường dẫn đầu ra được tạo: {self.output_path}")

    def browse_output(self):
        layer = self.current_layer()
        if layer is None:
            self.add_log("Vui lòng chọn layer đầu vào trước khi chọn đầu ra", "WARNING")
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn layer đầu vào trước")
            return

        self.add_log("Mở dialog chọn đường dẫn đầu ra...")
        input_path = layer.source()
        s = settings()
        directory = s.value(f"{self.NAME}/OutputDir", QFileInfo(input_path).dir().path())
        file_filter = "Shapefiles (*.shp)" if self.is_geotiff(input_path) else "Images (*.jpg *.png *.tiff)"
        file_name, _ = QFileDialog.getSaveFileName(self, "Lưu kết quả", directory, file_filter)
        if file_name:
            self.output_path = file_name
            self.outputPathLineEdit.setText(file_name)
            self.add_log(f"Đã chọn đường dẫn đầu ra: {file_name}")
            store_dir = QFileInfo(file_name).dir().path()
            if store_dir != directory:
                s.setValue(f"{self.NAME}/OutputDir", store_dir)
        else:
            self.add_log("Hủy chọn đường dẫn đầu ra")

    def processing_parameters(self, layer):
        return [*super().processing_parameters(layer), f"  - Ngưỡng tin cậy: {self.confidenceSpinBox.value():g}"]

    def script_arguments(self, input_path):
        return [*super().script_arguments(input_path), "--confidence", f"{self.confidenceSpinBox.value():g}"]

    def on_stdout_line(self, line: str):
        line = line.strip()
        if not line:
            return
        if "[OK]" in line or line.startswith("Loading model:"):
            self.add_log(f"🔄 {line}", "PROCESS")
        elif line.startswith("Processing image:"):
            self.add_log("🖼️ Đang xử lý ảnh đầu vào...", "PROCESS")
        elif "GeoTIFF" in line and "Confirmed" in line:
            self.add_log("🗺️ Xác nhận đầu vào là GeoTIFF", "PROCESS")
        elif "Regular image file detected" in line:
            self.add_log("🖼️ Xác nhận đầu vào là ảnh thường", "PROCESS")
        elif "completed successfully" in line or "Process Finished" in line:
            self.add_log("✅ Xử lý hoàn tất thành công!", "SUCCESS")
        elif "All Python dependencies loaded" in line:
            self.add_log("✅ Đã tải tất cả thư viện Python", "SUCCESS")
        elif "Model loaded successfully" in line:
            self.add_log("✅ Mô hình YOLO đã được tải thành công", "SUCCESS")
        else:
            clean = line.replace("[OK]", "✓").replace("[ERROR]", "❌").replace("[WARN]", "⚠️")
            self.add_log(f"Python: {clean}", "PROCESS")

    def on_event(self, event: dict):
        if event.get("type") != "result":
            return
        if event.get("seconds") is not None:
            self.add_log(f"⚡ Inference hoàn tất trong {event['seconds']:.2f} giây", "RESULT")
        if event.get("count") is not None:
            self.add_log(f"🚢 Phát hiện được {event['count']} {self.OBJECT_TEXT}", "RESULT")
        if event.get("kind") == "shapefile":
            self.add_log("📁 Đã tạo Shapefile thành công", "RESULT")
        elif event.get("kind") == "image":
            self.add_log("🖼️ Đã tạo ảnh có chú thích thành công", "RESULT")

    def on_stderr_line(self, line: str):
        line = line.strip()
        if not line:
            return
        if "Missing dependencies:" in line:
            self.add_log(f"❌ Thiếu thư viện Python: {line}", "ERROR")
        elif "Error loading model:" in line:
            self.add_log(f"❌ Lỗi tải mô hình: {line}", "ERROR")
        elif "Error during detection:" in line:
            self.add_log(f"❌ Lỗi trong quá trình phát hiện: {line}", "ERROR")
        elif "Error creating shapefile:" in line:
            self.add_log(f"❌ Lỗi tạo Shapefile: {line}", "ERROR")
        elif "Error creating annotated image:" in line:
            self.add_log(f"❌ Lỗi tạo ảnh chú thích: {line}", "ERROR")
        elif "Warning" in line or "WARNING" in line:
            self.add_log(f"⚠️ Cảnh báo: {line}", "WARNING")
        else:
            self.add_log(f"Python Error: {line}", "ERROR")

    def on_process_finished(self, exit_code: int, crashed: bool):
        time_str = self.log_finished_header(exit_code, crashed)
        if crashed or exit_code != 0:
            self.failure_details(exit_code, time_str)
            return

        self.statusLabel.setText("Hoàn thành thành công!")
        self.add_log(f"✅ Quá trình phát hiện {self.OBJECT_TEXT} hoàn tất thành công!", "SUCCESS")

        info = QFileInfo(self.output_path)
        if not info.exists():
            self.add_log("⚠️ Cảnh báo: File đầu ra không được tạo", "WARNING")
            QMessageBox.warning(
                self, "Cảnh báo", f"Xử lý hoàn tất nhưng file đầu ra không được tìm thấy:\n{self.output_path}"
            )
            return

        self.add_log(f"📄 File đầu ra: {info.fileName()}")
        self.add_log(f"📊 Kích thước: {info.size() / 1024.0:.1f} KB")
        if self.auto_add_enabled():
            self.output_files = [self.output_path]
            self.add_log("🗺️ Đang thêm kết quả vào bản đồ...", "SYSTEM")
            if self.add_output_to_map():
                self.add_log("✅ Đã thêm kết quả vào bản đồ thành công", "SUCCESS")
            else:
                self.add_log("⚠️ Không thể thêm kết quả vào bản đồ", "WARNING")
            QApplication.beep()
            self.complete.emit()

        QMessageBox.information(
            self,
            "Thành công",
            f"Phát hiện {self.OBJECT_TEXT} hoàn thành!\n\nKết quả: {self.output_path}\nThời gian xử lý: {time_str}",
        )

    def add_output_to_map(self) -> bool:
        info = QFileInfo(self.output_path)
        if not self.output_path or not info.exists():
            self.add_log(f"❌ File đầu ra không tồn tại: {self.output_path}", "ERROR")
            return False

        layer_name = info.completeBaseName()
        extension = info.suffix().lower()
        if extension == "shp":
            self.add_log("📁 Đang thêm Shapefile vào bản đồ...", "SYSTEM")
            layer = QgsVectorLayer(self.output_path, layer_name, "ogr")
            if not layer.isValid():
                self.add_log("❌ Shapefile không hợp lệ", "ERROR")
                return False
            self.add_log(f"✅ Shapefile hợp lệ - {layer.featureCount()} features", "SUCCESS")
        elif extension in ("jpg", "jpeg", "png", "tif", "tiff"):
            self.add_log("🖼️ Đang thêm ảnh kết quả vào bản đồ...", "SYSTEM")
            layer = QgsRasterLayer(self.output_path, layer_name, "gdal")
            if not layer.isValid():
                self.add_log("❌ Ảnh không hợp lệ", "ERROR")
                return False
            self.add_log(f"✅ Ảnh hợp lệ - {layer.width()}x{layer.height()} pixels", "SUCCESS")
        else:
            self.add_log(f"❌ Định dạng file không được hỗ trợ: {extension}", "ERROR")
            return False

        self.add_layer_to_project(layer, layer_name)
        if extension == "shp" and layer.featureCount() > 0 and self.map_canvas:
            extent = layer.extent()
            if not extent.isEmpty():
                self.map_canvas.setExtent(extent)
                self.map_canvas.refresh()
                self.add_log("🔍 Đã zoom đến vùng chứa kết quả", "SUCCESS")
        return True

    def save_log(self):
        self.add_log("Mở dialog lưu log...")
        s = settings()
        directory = s.value(f"{self.NAME}/LogDir", self.documents_dir())
        default_name = f"{self.LOG_PREFIX}_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Lưu log", QDir(directory).filePath(default_name), "Text files (*.txt);;All files (*)"
        )
        if not file_name:
            self.add_log("Hủy lưu log")
            return
        if self.write_log_file(file_name, f"=== vGeoInt_v2 {self.LOG_TITLE} Log ===\n"):
            self.add_log(f"✅ Log đã được lưu: {QFileInfo(file_name).fileName()}", "SUCCESS")
            store_dir = QFileInfo(file_name).dir().path()
            if store_dir != directory:
                s.setValue(f"{self.NAME}/LogDir", store_dir)
        else:
            self.add_log("❌ Lỗi lưu log: Không thể ghi file", "ERROR")
            QMessageBox.critical(self, "Lỗi", f"Không thể lưu log vào file:\n{file_name}")
