"""Port of BuildingSegmentationDialog.cpp."""

from qgis.core import QgsRasterLayer
from qgis.PyQt.QtCore import QFileInfo
from qgis.PyQt.QtWidgets import QApplication, QFileDialog, QMessageBox

from vgeoint.app.dialogs._yolo_detection_base import AiScriptDialog
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import settings

Ui_BuildingSegmentationDialog = load_ui_class("app", "BuildingSegmentationDialog")


class BuildingSegmentationDialog(AiScriptDialog, Ui_BuildingSegmentationDialog):
    NAME = "BuildingSegmentation"
    VN_NAME = "Phân đoạn tòa nhà từ ảnh vệ tinh"
    ICON = "BuildingSegmentation.svg"
    SCRIPT = "building_segmentation.py"
    MODEL = "models/building_unet.pth"
    MODEL_TEXT = "UNet for Building Segmentation"
    MODEL_KIND = "UNet"
    READY_TEXT = "Hệ thống phân đoạn tòa nhà đã sẵn sàng"
    START_TEXT = "=== BẮT ĐẦU QUÁ TRÌNH PHÂN ĐOẠN TÒA NHÀ ==="
    ERROR_STATUS_TEXT = "Lỗi xử lý"
    LOG_INTERRUPTED = False

    @staticmethod
    def is_geotiff(file_path: str) -> bool:
        return QFileInfo(file_path).suffix().lower() in ("tif", "tiff") and "geo" in file_path.lower()

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
            self.output_path = f"{directory}/{base}_buildings.tif"
            self.outputLineEdit.setText(self.output_path)
            self.add_log("Phát hiện GeoTIFF - sẽ tạo mặt nạ phân đoạn", "INFO")
        else:
            self.output_path = f"{directory}/{base}_buildings_mask.tif"
            self.outputLineEdit.setText(self.output_path)
            self.add_log("Phát hiện ảnh thường - sẽ tạo mặt nạ phân đoạn", "INFO")
        self.add_log(f"Đường dẫn đầu ra được tạo: {self.output_path}")

    def browse_output(self):
        layer = self.current_layer()
        if layer is None:
            self.add_log("Vui lòng chọn layer đầu vào trước khi chọn đầu ra", "WARNING")
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn layer đầu vào trước")
            return

        self.add_log("Mở dialog chọn đường dẫn đầu ra...")
        s = settings()
        directory = s.value("BuildingSegmentation/OutputDir", QFileInfo(layer.source()).dir().path())
        file_name, _ = QFileDialog.getSaveFileName(self, "Chọn file đầu ra", directory, "GeoTIFF Files (*.tif *.tiff)")
        if file_name:
            self.output_path = file_name
            self.outputLineEdit.setText(file_name)
            self.add_log(f"Đã chọn đường dẫn đầu ra: {QFileInfo(file_name).fileName()}")
            store_dir = QFileInfo(file_name).dir().path()
            if store_dir != directory:
                s.setValue("BuildingSegmentation/OutputDir", store_dir)

    def on_stdout_line(self, line: str):
        line = line.strip()
        if not line:
            return
        if "[OK]" in line or line.startswith("Loading model:"):
            self.add_log(f"🔄 {line}", "PROCESS")
        elif line.startswith("Processing image:"):
            self.add_log("🖼️ Đang xử lý ảnh đầu vào...", "PROCESS")
        elif "Building segmentation completed" in line:
            self.add_log("✅ Phân đoạn tòa nhà hoàn tất!", "SUCCESS")
        elif "GeoTIFF" in line and "Confirmed" in line:
            self.add_log("🗺️ Xác nhận đầu vào là GeoTIFF", "PROCESS")
        elif "All Python dependencies loaded" in line:
            self.add_log("✅ Đã tải tất cả thư viện Python", "SUCCESS")
        elif "Model loaded successfully" in line:
            self.add_log("✅ Mô hình UNet đã được tải thành công", "SUCCESS")
        else:
            clean = line.replace("[OK]", "✓").replace("[ERROR]", "❌").replace("[WARN]", "⚠️")
            self.add_log(f"Python: {clean}", "PROCESS")

    def on_event(self, event: dict):
        if event.get("type") != "result":
            return
        if event.get("seconds") is not None:
            self.add_log(f"⚡ Inference hoàn tất trong {event['seconds']:.2f} giây", "RESULT")
        if event.get("output"):
            self.add_log("🎯 Đã tạo mặt nạ phân đoạn thành công", "RESULT")

    def on_stderr_line(self, line: str):
        line = line.strip()
        if not line:
            return
        if "Missing dependencies:" in line:
            self.add_log(f"❌ Thiếu thư viện Python: {line}", "ERROR")
        elif "Error loading model:" in line:
            self.add_log(f"❌ Lỗi tải mô hình: {line}", "ERROR")
        elif "Error during segmentation:" in line:
            self.add_log(f"❌ Lỗi trong quá trình phân đoạn: {line}", "ERROR")
        elif "Error creating mask:" in line:
            self.add_log(f"❌ Lỗi tạo mặt nạ: {line}", "ERROR")
        elif "Warning" in line or "WARNING" in line:
            self.add_log(f"⚠️ Cảnh báo: {line}", "WARNING")
        else:
            self.add_log(f"Python Error: {line}", "ERROR")

    def on_process_finished(self, exit_code: int, crashed: bool):
        time_str = self.log_finished_header(exit_code, crashed)
        if crashed or exit_code != 0:
            self.failure_details(exit_code, time_str)
            return

        self.statusLabel.setText("Xử lý hoàn tất!")
        self.add_log("✅ Quá trình phân đoạn hoàn tất thành công!", "SUCCESS")

        info = QFileInfo(self.output_path)
        if info.exists():
            self.add_log(f"📁 File đầu ra: {info.fileName()} ({info.size() / (1024.0 * 1024.0):.2f} MB)", "RESULT")
            # The C++ autoAddOutputFiles() returned true: the result is always added (checkbox ignored).
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
            f"Phân đoạn tòa nhà hoàn thành!\n\nKết quả: {self.output_path}\nThời gian xử lý: {time_str}",
        )

    def add_output_to_map(self) -> bool:
        info = QFileInfo(self.output_path)
        if not self.output_path or not info.exists():
            self.add_log(f"❌ File đầu ra không tồn tại: {self.output_path}", "ERROR")
            return False

        layer_name = info.completeBaseName()
        extension = info.suffix().lower()
        if extension not in ("tif", "tiff"):
            self.add_log(f"❌ Định dạng file không được hỗ trợ: {extension}", "ERROR")
            return False

        self.add_log("🖼️ Đang thêm mặt nạ phân đoạn vào bản đồ...", "SYSTEM")
        layer = QgsRasterLayer(self.output_path, layer_name, "gdal")
        if not layer.isValid():
            self.add_log("❌ Mặt nạ phân đoạn không hợp lệ", "ERROR")
            return False
        self.add_log(f"✅ Mặt nạ phân đoạn hợp lệ - {layer.width()}x{layer.height()} pixels", "SUCCESS")
        self.add_layer_to_project(layer, layer_name)
        return True

    def save_log(self):
        s = settings()
        directory = s.value("BuildingSegmentation/LogDir", self.documents_dir())
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Lưu log", f"{directory}/building_segmentation_log.txt", "Text Files (*.txt)"
        )
        if not file_name:
            return
        header = "Building Segmentation Log\n=========================\n"
        if self.write_log_file(file_name, header):
            self.add_log(f"✅ Log đã được lưu: {QFileInfo(file_name).fileName()}", "SUCCESS")
            store_dir = QFileInfo(file_name).dir().path()
            if store_dir != directory:
                s.setValue("BuildingSegmentation/LogDir", store_dir)
        else:
            self.add_log("❌ Lỗi lưu log: Không thể ghi file", "ERROR")
            QMessageBox.critical(self, "Lỗi", f"Không thể lưu file log:\n{file_name}")
