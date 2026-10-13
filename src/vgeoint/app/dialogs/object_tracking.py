"""Port of ObjectTrackingDialog.cpp."""

from datetime import datetime

from qgis.PyQt.QtCore import QDir, QFileInfo, QProcess, Qt, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from vgeoint.ai.runner import ScriptRunner, model_path, python_for, script_path
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon, settings

Ui_ObjectTrackingDialog = load_ui_class("app", "ObjectTrackingDialog")

SCRIPT = "detect_track_video_onnx.py"
MODEL = "models/onnx_output/model.onnx"

_PROCESS_ERRORS = {
    QProcess.ProcessError.FailedToStart: "Không thể khởi động tiến trình Python.",
    QProcess.ProcessError.Crashed: "Tiến trình Python bị crash.",
    QProcess.ProcessError.Timedout: "Tiến trình Python bị timeout.",
    QProcess.ProcessError.WriteError: "Lỗi ghi dữ liệu tới tiến trình Python.",
    QProcess.ProcessError.ReadError: "Lỗi đọc dữ liệu từ tiến trình Python.",
}


def build_output_file_path(video_path: str, output_dir: str) -> str:
    return QDir(output_dir).filePath(f"track_{QFileInfo(video_path).completeBaseName()}_onnx.mp4")


class ObjectTrackingDialog(QDialog, Ui_ObjectTrackingDialog):
    complete = pyqtSignal()

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.output_files: list[str] = []
        self.max_frames = 300
        self._output_video_path = ""
        self._last_log_video_path = ""
        self._last_log_output_dir = ""
        self._closing = False

        self.browseVideoBtn.clicked.connect(self.browse_video)
        self.browseOutputBtn.clicked.connect(self.browse_output_directory)
        self.startBtn.clicked.connect(self.apply)
        self.closeBtn.clicked.connect(self.reject)
        self.clearLogBtn.clicked.connect(self.logTextEdit.clear)

        self._runner = ScriptRunner(self)
        self._runner.output_line.connect(self._on_stdout)
        self._runner.error_line.connect(self._on_stderr)
        self._runner.event_received.connect(self._on_event)
        self._runner.finished.connect(self._on_runner_finished)

        self.outputDirLedr.setText(settings().value("ObjectTracking/OutputDir", QApplication.applicationDirPath()))
        self.progressBar.hide()
        self.progressBar.setValue(0)
        self.append_log("Sẵn sàng chọn video và thư mục lưu kết quả.")

    # BPluginInterface
    def name(self) -> str:
        return "T_ObjectTracking"

    def vn_name(self) -> str:
        return "Theo dõi đối tượng"

    def get_icon(self):
        return get_icon("tracking.svg")

    def auto_add_output_files(self) -> bool:
        return False

    @property
    def runner(self) -> ScriptRunner:
        return self._runner

    def apply(self):
        video_path = self.videoPathLedr.text().strip()
        output_dir = self.outputDirLedr.text().strip()
        s = settings()

        if self._runner.is_running():
            QMessageBox.warning(self, self.vn_name(), "Quá trình theo dõi đang chạy.")
            self.append_log("Quá trình đang chạy, không thể khởi động thêm.")
            return
        if not video_path:
            QMessageBox.warning(self, self.vn_name(), "Vui lòng chọn file video đầu vào.")
            self.append_log("Thiếu file video đầu vào.")
            return
        if not output_dir:
            QMessageBox.warning(self, self.vn_name(), "Vui lòng chọn thư mục lưu output.")
            self.append_log("Thiếu thư mục lưu output.")
            return

        script = script_path(SCRIPT)
        model = model_path(MODEL)
        if not script.exists():
            QMessageBox.critical(self, self.vn_name(), f"Không tìm thấy file detect_track_video_onnx.py tại: {script}")
            self.append_log(f"Không tìm thấy script: {script}")
            return
        if not model.exists():
            QMessageBox.critical(self, self.vn_name(), f"Không tìm thấy file model.onnx tại: {model}")
            self.append_log(f"Không tìm thấy model ONNX: {model}")
            return

        self._output_video_path = build_output_file_path(video_path, output_dir)
        s.setValue("ObjectTracking/VideoDir", QFileInfo(video_path).absolutePath())
        s.setValue("ObjectTracking/OutputDir", output_dir)
        self.output_files = [self._output_video_path]

        arguments = [
            "--video", video_path,
            "--model", str(model),
            "--out", self._output_video_path,
            "--score-thr", "0.05",
            "--max-frames", str(self.max_frames),
        ]  # fmt: skip

        self.append_log("Bắt đầu chạy theo dõi đối tượng (ONNX Runtime)...")
        self.append_log(f"Python: {python_for(self._runner.env)}")
        self.append_log(f"Script: {script}")
        self.append_log(f"ONNX Model: {model}")
        self.append_log(f"Output video: {self._output_video_path}")

        self.update_ui_state(True)
        self._runner.start_script(SCRIPT, arguments)

    def browse_video(self):
        s = settings()
        dir_ = s.value("ObjectTracking/VideoDir", QApplication.applicationDirPath())
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn video đầu vào", dir_, "Video (*.mp4 *.avi *.mov *.mkv *.wmv);;All Files (*.*)"
        )
        if not file_path:
            return
        self.videoPathLedr.setText(file_path)
        s.setValue("ObjectTracking/VideoDir", QFileInfo(file_path).absolutePath())
        if self._last_log_video_path != file_path:
            self.append_log(f"Đã chọn video: {file_path}")
            self._last_log_video_path = file_path

    def browse_output_directory(self):
        s = settings()
        dir_ = s.value("ObjectTracking/OutputDir", QApplication.applicationDirPath())
        selected = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục lưu output",
            dir_,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if not selected:
            return
        self.outputDirLedr.setText(selected)
        s.setValue("ObjectTracking/OutputDir", selected)
        if self._last_log_output_dir != selected:
            self.append_log(f"Đã chọn thư mục output: {selected}")
            self._last_log_output_dir = selected

    def append_log(self, message: str):
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.logTextEdit.appendPlainText(f"[{timestamp}] {message}")

    def update_ui_state(self, running: bool):
        for widget in (self.startBtn, self.browseVideoBtn, self.browseOutputBtn, self.videoPathLedr, self.outputDirLedr):
            widget.setEnabled(not running)
        if running:
            # Indeterminate (pulsing) while the model is loading
            self.progressBar.setMaximum(0)
            self.progressBar.setValue(0)
            self.progressBar.setFormat("Đang khởi động...")
            self.progressBar.show()
        else:
            self.progressBar.hide()

    # ------------------------------------------------------------- process
    def _on_runner_finished(self, exit_code: int, crashed: bool):
        if self._closing:
            return
        error = self._runner.process.error()
        if crashed and error == QProcess.ProcessError.FailedToStart:
            self._on_process_error(error)
            QMessageBox.critical(self, self.vn_name(), "Không thể khởi động tiến trình Python.")
            self.append_log("Không thể khởi động tiến trình Python.")
            return
        if crashed:
            self._on_process_error(QProcess.ProcessError.Crashed)
        self._on_process_finished(exit_code, crashed)

    def _on_process_finished(self, exit_code: int, crashed: bool):
        self.update_ui_state(False)
        self.append_log("Tiến trình Python đã kết thúc.")
        self.append_log(f"Exit code: {exit_code}")
        self.append_log("Trạng thái: " + ("Crashed" if crashed else "Normal"))

        if crashed or exit_code != 0:
            self.append_log("Theo dõi đối tượng thất bại. Kiểm tra log để biết chi tiết.")
            QMessageBox.critical(self, self.vn_name(), "Tiến trình theo dõi thất bại. Vui lòng kiểm tra log.")
            return

        self.append_log("Theo dõi đối tượng hoàn tất thành công.")
        self.complete.emit()

        box = QMessageBox(self)
        box.setWindowTitle(self.vn_name())
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("Theo dõi đối tượng hoàn tất.")
        box.setInformativeText(f"Kết quả được lưu tại:\n{self._output_video_path}")
        open_video = box.addButton("Mở video", QMessageBox.ButtonRole.ActionRole)
        open_folder = box.addButton("Mở thư mục", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() == open_video:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._output_video_path))
        elif box.clickedButton() == open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(QFileInfo(self._output_video_path).absolutePath()))

    def _on_process_error(self, error):
        self.update_ui_state(False)
        self.append_log(_PROCESS_ERRORS.get(error, "Lỗi không xác định khi chạy tiến trình Python."))

    def _on_stdout(self, line: str):
        self.append_log(line.strip())

    def _on_stderr(self, line: str):
        self.append_log(f"[stderr] {line.strip()}")

    def _on_event(self, event: dict):
        """Replaces the "processed N frames" / "Done." text matching of the C++ dialog."""
        if event.get("type") == "progress" and "frame" in event:
            if self.progressBar.maximum() == 0:
                # First report: switch from indeterminate to determinate mode
                self.progressBar.setMaximum(self.max_frames)
                self.progressBar.setFormat("%p% (%v / %m frames)")
            self.progressBar.setValue(min(int(event["frame"]), self.max_frames))
        elif event.get("type") == "result":
            self.progressBar.setMaximum(self.max_frames)
            self.progressBar.setValue(self.max_frames)

    def done(self, result: int):
        # The C++ QProcess child was killed when the dialog was deleted after exec().
        self._closing = True
        self._runner.kill()
        super().done(result)
