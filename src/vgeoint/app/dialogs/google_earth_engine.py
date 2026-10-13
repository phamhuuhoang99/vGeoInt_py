"""Port of GoogleEarthEngineDialog.cpp.

Login: the C++ dialog ran scripts/gee_authentication.bat, i.e. `earthengine authenticate --force` with
whatever `earthengine` was on PATH. The same Earth Engine CLI command now runs with the ai environment
interpreter (AUTH_ARGUMENTS), so the credentials are stored for the earthengine-api used by
gee_download.py (in the user's ~/.config/earthengine as before).
"""

import os

from qgis.core import QgsProject, QgsRasterLayer
from qgis.PyQt.QtCore import QDateTime, QDir, QFileInfo, QStandardPaths, QTimer
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from vgeoint.ai.runner import ScriptRunner, python_for, script_path
from vgeoint.common.utils import get_icon, settings

SCRIPT = "gee_download.py"
# `earthengine authenticate --force` run through the ai interpreter (python -c sets sys.argv[1:]).
AUTH_ARGUMENTS = ["-c", "from ee.cli.eecli import main; main()", "authenticate", "--force"]

_LOG_ICONS = {"SUCCESS": "✓", "ERROR": "❌", "WARNING": "⚠️", "SYSTEM": "🔧", "INFO": "ℹ️"}


class GoogleEarthEngineDialog(QDialog):
    # The C++ dialog emitted complete() after adding the layer itself; MainController never connected it
    # for dialogs, so there is no `complete` signal here (it would add the image twice).

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.is_logged_in = False
        self.auth_token = ""
        self.output_path = "downloads"
        self.output_files: list[str] = []
        self._process: ScriptRunner | None = None
        self._process_start_time = QDateTime()
        self._downloaded_file = ""
        self._started = False

        self._setup_ui()
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view

        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._on_progress_timer)

        self.login_btn.clicked.connect(self.on_login_clicked)
        self.download_btn.clicked.connect(self.on_download_clicked)
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        self.clear_log_btn.clicked.connect(self.clear_log)
        self.save_log_btn.clicked.connect(self.save_log)
        self.browse_output_btn.clicked.connect(self.browse_output)

        self.add_log("Giao diện Google Earth Engine đã sẵn sàng", "SYSTEM")

    # BPluginInterface
    def name(self) -> str:
        return "GoogleEarthEngine"

    def vn_name(self) -> str:
        return "Tải ảnh từ Google Earth Engine"

    def get_icon(self):
        return get_icon("GoogleEarthEngine.svg")

    def auto_add_output_files(self) -> bool:
        return self.auto_add_check_box.isChecked()

    # ---------------------------------------------------------------- UI
    def _setup_ui(self):
        self.setWindowTitle("Tải ảnh từ Google Earth Engine")
        self.setFixedSize(600, 700)
        main_layout = QVBoxLayout(self)
        self._create_login_group()
        self._create_data_group()
        self._create_button_group()
        self._create_log_group()
        main_layout.addWidget(self.login_group)
        main_layout.addWidget(self.data_group)
        main_layout.addWidget(self.button_group)
        main_layout.addWidget(self.log_group)

    def _create_login_group(self):
        self.login_group = QGroupBox("Đăng nhập", self)
        layout = QVBoxLayout(self.login_group)
        self.login_btn = QPushButton("Đăng nhập", self)
        self.login_btn.setFixedHeight(40)
        layout.addWidget(self.login_btn)

    def _create_data_group(self):
        self.data_group = QGroupBox("Dữ liệu", self)
        layout = QVBoxLayout(self.data_group)

        project_id_label = QLabel("Project ID:", self)
        self.project_id_edit = QLineEdit(self)
        self.project_id_edit.setPlaceholderText("Nhập Project ID...")
        self.project_id_edit.setText("root-clover-471000-e0")

        data_id_label = QLabel("ID dữ liệu:", self)
        self.data_id_edit = QLineEdit(self)
        self.data_id_edit.setPlaceholderText("Nhập ID dữ liệu...")

        region_label = QLabel("Vùng quan tâm (minLon,minLat,maxLon,maxLat):", self)
        self.region_edit = QLineEdit(self)
        self.region_edit.setPlaceholderText("Ví dụ: 105.7,20.9,106.0,21.1")
        self.region_edit.setText("105.7,20.9,106.0,21.1")

        output_path_label = QLabel("Thư mục đầu ra:", self)
        output_path_layout = QHBoxLayout()
        self.output_path_edit = QLineEdit(self)
        self.output_path_edit.setText("downloads")
        self.browse_output_btn = QPushButton("Duyệt...", self)
        self.browse_output_btn.setMaximumWidth(80)
        output_path_layout.addWidget(self.output_path_edit)
        output_path_layout.addWidget(self.browse_output_btn)

        self.auto_add_check_box = QCheckBox("Tự động thêm vào bản đồ", self)
        self.auto_add_check_box.setChecked(True)

        layout.addWidget(project_id_label)
        layout.addWidget(self.project_id_edit)
        layout.addWidget(data_id_label)
        layout.addWidget(self.data_id_edit)
        layout.addWidget(region_label)
        layout.addWidget(self.region_edit)
        layout.addWidget(output_path_label)
        layout.addLayout(output_path_layout)
        layout.addWidget(self.auto_add_check_box)

    def _create_button_group(self):
        self.button_group = QGroupBox(self)
        layout = QHBoxLayout(self.button_group)
        self.download_btn = QPushButton("Tải", self)
        self.cancel_btn = QPushButton("Hủy", self)
        layout.addWidget(self.download_btn)
        layout.addWidget(self.cancel_btn)

    def _create_log_group(self):
        self.log_group = QGroupBox("Log tiến trình", self)
        layout = QVBoxLayout(self.log_group)

        self.log_text_edit = QTextEdit(self)
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setMaximumHeight(200)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setVisible(False)
        self.status_label = QLabel("Sẵn sàng", self)

        log_button_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("Xóa log", self)
        self.save_log_btn = QPushButton("Lưu log", self)
        log_button_layout.addWidget(self.clear_log_btn)
        log_button_layout.addWidget(self.save_log_btn)
        log_button_layout.addStretch()

        layout.addWidget(self.log_text_edit)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addLayout(log_button_layout)

    # ---------------------------------------------------------------- login
    def on_login_clicked(self):
        self.add_log("Bắt đầu quá trình đăng nhập Google Earth Engine...", "INFO")

        process = ScriptRunner(self)
        state = {"started": False}
        process.started.connect(lambda: state.update(started=True))
        process.output_line.connect(lambda line: self.add_log(line.strip(), "INFO"))
        process.error_line.connect(lambda line: self.add_log(line.strip(), "INFO"))
        process.finished.connect(lambda code, crashed: self._login_finished(process, state["started"], code))

        self.add_log("Khởi động script xác thực...", "INFO")
        process.start_script("", AUTH_ARGUMENTS, program=python_for(process.env))

    def _login_finished(self, process: ScriptRunner, started: bool, exit_code: int):
        process.deleteLater()
        if not started:
            self.add_log("Không thể khởi động script!", "ERROR")
            QMessageBox.critical(self, "Lỗi", "Không thể khởi động script!")
            return
        if exit_code == 0:
            self.is_logged_in = True
            self.login_btn.setText("Đã đăng nhập")
            self.login_btn.setEnabled(False)
            self.add_log("Đăng nhập thành công!", "SUCCESS")
            QMessageBox.information(self, "Thành công", "Đăng nhập thành công!")
        else:
            self.add_log("Đăng nhập thất bại!", "ERROR")
            QMessageBox.warning(self, "Lỗi", "Đăng nhập thất bại!")

    # ---------------------------------------------------------------- download
    def on_download_clicked(self):
        if not self.is_logged_in:
            self.add_log("Vui lòng đăng nhập trước!", "WARNING")
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng đăng nhập trước!")
            return

        project_id = self.project_id_edit.text().strip()
        if not project_id:
            self.add_log("Vui lòng nhập Project ID!", "WARNING")
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng nhập Project ID!")
            return

        data_id = self.data_id_edit.text().strip()
        if not data_id:
            self.add_log("Vui lòng nhập ID dữ liệu!", "WARNING")
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng nhập ID dữ liệu!")
            return

        region = self.region_edit.text().strip()
        if not region:
            self.add_log("Vui lòng nhập vùng quan tâm!", "WARNING")
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng nhập vùng quan tâm!")
            return

        output_path = self.output_path_edit.text().strip() or "downloads"

        self.add_log("Bắt đầu tải dữ liệu...", "INFO")
        self.add_log(f"Project ID: {project_id}", "INFO")
        self.add_log(f"ID dữ liệu: {data_id}", "INFO")
        self.add_log(f"Vùng quan tâm: {region}", "INFO")
        self.add_log(f"Thư mục đầu ra: {output_path}", "INFO")

        self.run_python_script(data_id, region, output_path, project_id)

    def on_cancel_clicked(self):
        self.close()

    @staticmethod
    def _absolute_output_dir(output_path: str) -> str:
        # The C++ app resolved a relative folder ("downloads") against its working directory; the
        # script now runs in the repository root, so pass the folder as an absolute path.
        return os.path.abspath(output_path)

    def run_python_script(self, data_id: str, region: str, output_path: str, project_id: str):
        self.add_log("Khởi tạo Python process...", "INFO")
        self._process_start_time = QDateTime.currentDateTime()

        self.progress_bar.show()
        self.progress_bar.setMaximum(0)
        self.status_label.setText("Đang xử lý...")
        self._progress_timer.start(100)

        self.download_btn.setEnabled(False)
        self.login_btn.setEnabled(False)

        if self._process is not None:
            self._process.deleteLater()
        self._process = ScriptRunner(self)
        self._process.started.connect(self._on_process_started)
        self._process.finished.connect(self.on_process_finished)
        self._process.output_line.connect(self.on_process_ready_read_standard_output)
        self._process.error_line.connect(self.on_process_ready_read_standard_error)
        self._process.event_received.connect(self._on_event)
        self._downloaded_file = ""

        script = script_path(SCRIPT)
        self.add_log(f"Script Python: {script}", "INFO")
        if not script.exists():
            self.add_log("Lỗi: Script Python không tồn tại!", "ERROR")
            self.on_process_error("Không thể khởi động process")
            return

        arguments = [
            "--data_id",
            data_id,
            "--region",
            region,
            "--output",
            self._absolute_output_dir(output_path),
            "--project_id",
            project_id,
        ]
        self.add_log("Tham số dòng lệnh:", "INFO")
        self.add_log(f"  python {' '.join([str(script), *arguments])}", "INFO")

        self.add_log("Khởi động Python process...", "INFO")
        self._started = False
        self._process.start_script(SCRIPT, arguments)

    def _on_process_started(self):
        self._started = True
        self.add_log("✓ Python process đã khởi động thành công", "SUCCESS")
        self.add_log(f"Process ID: {self._process.process.processId()}", "INFO")

    def _on_progress_timer(self):
        if self._process is not None and self._process.is_running():
            self.status_label.setText("Đang xử lý...")

    def _on_event(self, event: dict):
        if event.get("type") == "result" and event.get("output"):
            self._downloaded_file = event["output"]

    def on_process_finished(self, exit_code: int, crashed: bool):
        if not self._started:
            self.add_log("Lỗi: Không thể khởi động Python process", "ERROR")
            self.on_process_error("Không thể khởi động process")
            return

        self._progress_timer.stop()
        ms = self._process_start_time.msecsTo(QDateTime.currentDateTime())
        time_str = f"{ms // 1000}.{(ms % 1000) // 100}s"

        self.add_log_with_timestamp("=== KẾT THÚC QUÁ TRÌNH TẢI DỮ LIỆU ===", "SYSTEM")
        self.add_log(f"Thời gian xử lý: {time_str}")
        self.add_log(f"Mã thoát: {exit_code}")
        self.add_log(f"Trạng thái: {'Crashed' if crashed else 'Normal'}")

        self.progress_bar.hide()
        self.download_btn.setEnabled(True)
        self.login_btn.setEnabled(True)

        if not crashed and exit_code == 0:
            self.status_label.setText("Hoàn thành thành công!")
            self.add_log("✅ Quá trình tải dữ liệu hoàn tất thành công!", "SUCCESS")

            output_path = self.output_path_edit.text().strip() or "downloads"
            full_path = self._downloaded_file
            if not full_path or not QFileInfo.exists(full_path):
                # C++ fallback: last *.tif / *.tiff / *.geotiff of the output folder (by name)
                out_dir = QDir(self._absolute_output_dir(output_path))
                files = out_dir.entryList(["*.tif", "*.tiff", "*.geotiff"], QDir.Filter.Files)
                full_path = out_dir.filePath(files[-1]) if files else ""

            if full_path:
                info = QFileInfo(full_path)
                self.add_log(f"📄 File đã tải: {info.fileName()}")
                self.add_log(f"📊 Kích thước: {info.size() / 1024.0:.1f} KB")

                if self.auto_add_output_files():
                    self.output_files = [full_path]
                    self.add_log("🗺️ Đang thêm kết quả vào bản đồ...", "SYSTEM")
                    if self.add_output_to_map():
                        self.add_log("✅ Đã thêm kết quả vào bản đồ thành công", "SUCCESS")
                    else:
                        self.add_log("⚠️ Không thể thêm kết quả vào bản đồ", "WARNING")
                    QApplication.beep()

                QMessageBox.information(
                    self,
                    "Thành công",
                    f"Tải dữ liệu hoàn thành!\n\nFile: {info.fileName()}\nThời gian xử lý: {time_str}",
                )
            else:
                self.add_log("⚠️ Cảnh báo: Không tìm thấy file đã tải", "WARNING")
                QMessageBox.warning(
                    self,
                    "Cảnh báo",
                    f"Tải dữ liệu hoàn tất nhưng không tìm thấy file trong thư mục:\n{output_path}",
                )
        else:
            self.status_label.setText("Tải dữ liệu thất bại!")
            self.add_log("❌ Quá trình tải dữ liệu thất bại!", "ERROR")
            # stderr was already streamed to the log (C++ re-read nothing here: it was consumed live).
            QMessageBox.critical(
                self,
                "Lỗi",
                f"Tải dữ liệu thất bại!\n\nMã lỗi: {exit_code}\nThời gian xử lý: {time_str}"
                "\n\nVui lòng kiểm tra log để biết chi tiết.",
            )

    def on_process_error(self, error_msg: str):
        self._progress_timer.stop()
        self.progress_bar.hide()
        self.status_label.setText("Lỗi")
        self.add_log(f"❌ Lỗi process: {error_msg}", "ERROR")
        self.download_btn.setEnabled(True)
        self.login_btn.setEnabled(True)

    def on_process_ready_read_standard_output(self, line: str):
        trimmed = line.strip()
        if not trimmed:
            return
        if "[OK]" in trimmed:
            self.add_log(trimmed, "SUCCESS")
        elif "[ERROR]" in trimmed:
            self.add_log(trimmed, "ERROR")
        elif "[INFO]" in trimmed:
            self.add_log(trimmed, "INFO")
        elif "[WARN]" in trimmed:
            self.add_log(trimmed, "WARNING")
        else:
            self.add_log(trimmed, "INFO")

    def on_process_ready_read_standard_error(self, line: str):
        if line.strip():
            self.add_log(line.strip(), "ERROR")

    # ---------------------------------------------------------------- log
    def add_log(self, message: str, log_type: str = "INFO"):
        self.log_text_edit.append(self.format_log_message(message, log_type))
        bar = self.log_text_edit.verticalScrollBar()
        bar.setValue(bar.maximum())
        # C++ called QApplication::processEvents() here; output now arrives asynchronously line by line,
        # and re-entering the event loop from a ScriptRunner signal could deliver `finished` mid-read.

    def add_log_with_timestamp(self, message: str, log_type: str = "INFO"):
        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
        self.add_log(f"[{timestamp}] {message}", log_type)

    def clear_log(self):
        self.clear_log_display()
        self.add_log("Log đã được xóa", "SYSTEM")

    def save_log(self):
        self.add_log("Mở dialog lưu log...", "INFO")
        s = settings()
        default_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        dir_ = s.value("GoogleEarthEngine/LogDir", default_dir)
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_hhmmss")
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu log",
            QDir(dir_).filePath(f"gee_download_log_{timestamp}.txt"),
            "Text files (*.txt);;All files (*)",
        )
        if not file_name:
            self.add_log("Hủy lưu log", "INFO")
            return
        try:
            with open(file_name, "w", encoding="utf-8") as f:
                f.write("=== vGeoInt_v2 Google Earth Engine Download Log ===\n")
                f.write(f"Timestamp: {QDateTime.currentDateTime().toString('yyyy-MM-dd hh:mm:ss')}\n")
                f.write(f"Version: {QApplication.applicationVersion()}\n")
                f.write("==================================================\n\n")
                f.write(self.log_text_edit.toPlainText())
        except OSError:
            self.add_log("❌ Lỗi lưu log: Không thể ghi file", "ERROR")
            QMessageBox.critical(self, "Lỗi", f"Không thể lưu log vào file:\n{file_name}")
            return
        self.add_log(f"✅ Log đã được lưu: {QFileInfo(file_name).fileName()}", "SUCCESS")
        store_dir = QFileInfo(file_name).dir().path()
        if store_dir != dir_:
            s.setValue("GoogleEarthEngine/LogDir", store_dir)

    def clear_log_display(self):
        self.log_text_edit.clear()

    def format_log_message(self, message: str, log_type: str) -> str:
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        return f"[{timestamp}] {_LOG_ICONS.get(log_type, '•')} {message}"

    def browse_output(self):
        self.add_log("Mở dialog chọn thư mục đầu ra...", "INFO")
        s = settings()
        default_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        dir_ = s.value("GoogleEarthEngine/OutputDir", default_dir)
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục đầu ra",
            dir_,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if folder_path:
            self.output_path_edit.setText(folder_path)
            self.add_log(f"Đã chọn thư mục đầu ra: {folder_path}", "SUCCESS")
            # As in C++: remembers the parent of the chosen folder.
            store_dir = QFileInfo(folder_path).dir().path()
            if store_dir != dir_:
                s.setValue("GoogleEarthEngine/OutputDir", store_dir)
        else:
            self.add_log("Hủy chọn thư mục đầu ra", "INFO")

    def add_output_to_map(self) -> bool:
        if not self.output_files:
            self.add_log("❌ Không có file đầu ra để thêm vào bản đồ", "ERROR")
            return False
        output_path = self.output_files[0]
        if not QFileInfo.exists(output_path):
            self.add_log(f"❌ File đầu ra không tồn tại: {output_path}", "ERROR")
            return False

        info = QFileInfo(output_path)
        layer_name = info.completeBaseName()
        extension = info.suffix().lower()
        if extension not in ("tif", "tiff", "geotiff"):
            self.add_log(f"❌ Định dạng file không được hỗ trợ: {extension}", "ERROR")
            return False

        self.add_log("🖼️ Đang thêm ảnh vệ tinh vào bản đồ...", "SYSTEM")
        layer = QgsRasterLayer(output_path, layer_name, "gdal")
        if not layer.isValid():
            self.add_log("❌ Ảnh vệ tinh không hợp lệ", "ERROR")
            return False
        self.add_log(f"✅ Ảnh vệ tinh hợp lệ - {layer.width()}x{layer.height()} pixels", "SUCCESS")

        QgsProject.instance().addMapLayer(layer)
        self.add_log(f"🗺️ Đã thêm layer '{layer_name}' vào project", "SUCCESS")
        if self.map_canvas is not None:
            self.map_canvas.refresh()
            self.add_log("🔄 Đã làm mới bản đồ", "SUCCESS")
        return True

    def done(self, result: int):
        # C++ deleteLater'd the QProcess in the destructor (killing the script); do it explicitly.
        for runner in self.findChildren(ScriptRunner):
            if runner.is_running():
                runner.finished.disconnect()
                runner.kill()
        self._progress_timer.stop()
        super().done(result)
