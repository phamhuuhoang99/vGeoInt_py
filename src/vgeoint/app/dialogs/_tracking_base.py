"""Process handling shared by ShipTrackingDialog.cpp and VehicleTrackingDialog.cpp."""

import time

from qgis.PyQt.QtCore import QProcess, QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QMessageBox

from vgeoint.ai.runner import ScriptRunner, python_for, script_path


def qnum(value: float) -> str:
    """QString::number(double): %g with 6 significant digits."""
    return f"{value:g}"


class TrackingProcessMixin:
    """QProcess part of the C++ tracking dialogs, on top of ScriptRunner.

    Subclasses define SCRIPT, RUNNING_STATUS, add_log(message, type), _on_stdout, _on_stderr,
    _on_event and _on_process_finished(exit_code, crashed).
    """

    SCRIPT = ""
    RUNNING_STATUS = ""
    STARTED_LOG = ("", "INFO")

    def _init_process(self):
        self._runner = ScriptRunner(self)
        self._runner.output_line.connect(self._on_stdout)
        self._runner.error_line.connect(self._on_stderr)
        self._runner.event_received.connect(self._on_event)
        self._runner.started.connect(self._on_started)
        self._runner.finished.connect(self._on_runner_finished)
        self._closing = False
        self._start_time = time.monotonic()
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._update_process_progress)

    @property
    def runner(self) -> ScriptRunner:
        return self._runner

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start_time) * 1000)

    def _set_running(self, running: bool):
        self.okButton.setEnabled(not running)
        self.browseInputDirButton.setEnabled(not running)
        self.browseOutputDirButton.setEnabled(not running)

    def _run_python_script(self, arguments: list[str]):
        self.add_log("Khởi tạo Python process...")
        self._start_time = time.monotonic()

        self.progressBar.show()
        self.progressBar.setMaximum(0)  # Indeterminate
        self.statusLabel.setText(self.RUNNING_STATUS)
        self._progress_timer.start()
        self._set_running(True)

        script = script_path(self.SCRIPT)
        self.add_log(f"Script Python: {script}")
        if not script.exists():
            self.add_log("Lỗi: Script Python không tồn tại!", "ERROR")
            self._on_process_error(QProcess.ProcessError.FailedToStart)
            return

        self.add_log("Tham số dòng lệnh:")
        self.add_log("  python " + " ".join([str(script), *arguments]))
        self.add_log(f"Khởi động tiến trình Python ({python_for(self._runner.env)})...")
        self._runner.start_script(self.SCRIPT, arguments)

    def _on_started(self):
        message, log_type = self.STARTED_LOG
        self.add_log(message.format(pid=self._runner.process.processId()), log_type)

    def _update_process_progress(self):
        if not self._runner.is_running():
            return
        self.statusLabel.setText(self._progress_text(self.elapsed_ms() // 1000))

    def _progress_text(self, seconds: int) -> str:
        raise NotImplementedError

    def _on_runner_finished(self, exit_code: int, crashed: bool):
        if self._closing:
            return
        error = self._runner.process.error()
        if crashed and error == QProcess.ProcessError.FailedToStart:
            self.add_log("Lỗi: Không thể khởi động tiến trình Python", "ERROR")
            self._on_process_error(error)
            return
        if crashed:
            # QProcess reports errorOccurred(Crashed) before finished().
            self._on_process_error(QProcess.ProcessError.Crashed)
        self._on_process_finished(exit_code, crashed)

    def _on_process_error(self, error):
        self._progress_timer.stop()
        self.progressBar.hide()
        self._set_running(False)

        messages = {
            QProcess.ProcessError.FailedToStart: "Không thể khởi động Python. Vui lòng kiểm tra môi trường Python và "
            f"script {self.SCRIPT}.",
            QProcess.ProcessError.Crashed: "Tiến trình Python bị crash bất ngờ.",
            QProcess.ProcessError.Timedout: "Quá trình xử lý bị timeout.",
        }
        error_msg = messages.get(error, "Lỗi không xác định trong quá trình xử lý.")
        self.add_log(error_msg, "ERROR")
        self.statusLabel.setText("Xử lý thất bại!")
        QMessageBox.critical(self, "Lỗi", error_msg)

    def _show_failure(self, exit_code: int, time_str: str):
        self.statusLabel.setText("Xử lý thất bại!")
        self.add_log("❌ Quá trình xử lý thất bại! Vui lòng kiểm tra log.", "ERROR")
        QMessageBox.critical(
            self,
            "Lỗi",
            f"Xử lý thất bại!\nMã lỗi: {exit_code}\nThời gian xử lý: {time_str}\n"
            "Vui lòng kiểm tra log để biết chi tiết.",
        )

    def _show_success_box(self, title: str, text: str, informative: str, folder: str):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(text)
        if informative:
            box.setInformativeText(informative)
        open_btn = box.addButton("Mở thư mục kết quả", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() == open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def stop_process(self):
        """The C++ destructor terminated a running process when the dialog was deleted after exec()."""
        self._closing = True
        self._progress_timer.stop()
        self._runner.kill()

    def done(self, result: int):
        self.stop_process()
        super().done(result)
