"""Port of MotionDetectionDialog.cpp."""

from qgis.core import Qgis, QgsProject, QgsRasterLayer
from qgis.PyQt.QtCore import QDir, QFile, QFileInfo
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from vgeoint.ai.runner import ScriptRunner, model_path, script_path
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon, settings

Ui_MotionDetectionDialog = load_ui_class("app", "MotionDetectionDialog")

MODEL = "models/random_forest_model_s2.joblib"
SCRIPT = "ai_motion_detection.py"


def _red(text: str) -> str:
    return f"<font color='red'>{text}</font>"


def _green(text: str) -> str:
    return f"<font color='green'>{text}</font>"


class MotionDetectionDialog(QDialog, Ui_MotionDetectionDialog):
    # The C++ dialog emitted complete() but always added its layers itself (and MainController never
    # connected it), so no `complete` signal here: connecting it would add the outputs twice.

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.progressBar.hide()
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.output_files: list[str] = []
        self.colored_output_path = ""
        self.combined_tiff_path = ""
        self._stderr: list[str] = []
        self._started = False
        self._runner: ScriptRunner | None = None

        self.browseBtn.clicked.connect(self._browse)
        self.cancelBtn.clicked.connect(self.close)
        self.aiProcessBtn.clicked.connect(self.run_python_script)

        self.populate()

    # BPluginInterface
    def name(self) -> str:
        return "T_MotionDetection"

    def vn_name(self) -> str:
        return "Phát hiện biến động"

    def get_icon(self):
        return get_icon("ChangeDetection.svg")

    def auto_add_output_files(self) -> bool:
        return self.autoAddOutputChbx.isChecked()

    def populate(self):
        """MotionDetectionDialog::show(): list the valid canvas raster layers."""
        self.beforeRasterLayerCbx.clear()
        self.afterRasterLayerCbx.clear()
        for layer in self.map_canvas.layers():
            if layer.type() == Qgis.LayerType.Raster and layer.isValid():
                self.beforeRasterLayerCbx.addItem(get_icon("Raster.svg"), layer.name(), layer)
                self.afterRasterLayerCbx.addItem(get_icon("Raster.svg"), layer.name(), layer)

    def _browse(self):
        s = settings()
        default_dir = QApplication.applicationDirPath()
        dir_ = s.value("SaveImage/Dir", default_dir)

        store_dir = ""
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Lưu kết quả phát hiện biến động", dir_, "Rasters (*.tif *.tiff)"
        )
        if file_name:
            store_dir = QFileInfo(file_name).dir().path()
            self.outputLedr.setText(file_name)

        if store_dir and store_dir != dir_:
            s.setValue("SaveImage/Dir", store_dir)

    def apply(self):
        self.run_python_script()

    def run_python_script(self):
        before = self.beforeRasterLayerCbx.currentData()
        after = self.afterRasterLayerCbx.currentData()

        if not before or not before.isValid() or not after or not after.isValid():
            self.noticeLbl.setText(_red("Vui lòng chọn các layer raster hợp lệ"))
            return
        if before.id() == after.id():
            self.noticeLbl.setText(_red("Ảnh trước và sau phải khác nhau"))
            return

        output = self.outputLedr.text().strip()
        if not output:
            self.noticeLbl.setText(_red("Chưa chọn đường dẫn lưu kết quả"))
            return

        generate_stats = show_summary = enable_visualization = True

        model = str(model_path(MODEL))
        if not QFile.exists(model):
            self.noticeLbl.setText(_red("⚠️ KHÔNG TÌM THẤY MÔ HÌNH! models/random_forest_model_s2.joblib"))
            QMessageBox.warning(
                self,
                "Mô hình không tồn tại",
                "Không tìm thấy file mô hình tại:\n"
                + model
                + "\n\nVui lòng đảm bảo file models/random_forest_model_s2.joblib tồn tại.",
            )
            return

        self.noticeLbl.setText("Đang chạy ML phát hiện thay đổi lớp phủ...")

        if not script_path(SCRIPT).exists():
            self.noticeLbl.setText(_red("Không tìm thấy script AI: ai_motion_detection.py"))
            return

        self.run_python_process(
            before.source(), after.source(), output, model, generate_stats, show_summary, enable_visualization
        )

    def run_python_process(
        self,
        before_path: str,
        after_path: str,
        output_path: str,
        model: str,
        generate_stats: bool = True,
        show_summary: bool = True,
        enable_visualization: bool = True,
    ):
        # C++ passed "--model" twice (before and after the flags); argparse keeps the last, same value.
        arguments = ["--before", before_path, "--after", after_path, "--output", output_path, "--model", model]
        if generate_stats:
            arguments.append("--stats")
        if show_summary:
            arguments.append("--summary")
        if enable_visualization:
            arguments.append("--visualize")
        if not model or not QFile.exists(model):
            self.noticeLbl.setText(_red("Lỗi hệ thống: Mô hình ML bị thiếu"))
            return

        self._stderr = []
        self._started = False
        runner = ScriptRunner(self)
        runner.started.connect(lambda: setattr(self, "_started", True))
        runner.error_line.connect(self._stderr.append)
        runner.event_received.connect(self._on_event)
        runner.finished.connect(lambda code, crashed, r=runner: self._on_finished(r, output_path, code, crashed))
        self._runner = runner
        runner.start_script(SCRIPT, arguments)

    def _on_event(self, event: dict):
        if event.get("type") == "result":
            self.colored_output_path = event.get("colored") or ""
            self.combined_tiff_path = event.get("combined") or ""

    def _on_finished(self, runner: ScriptRunner, output_path: str, exit_code: int, crashed: bool):
        runner.deleteLater()
        if not self._started:
            self.noticeLbl.setText(_red("Không thể khởi động Python"))
            return

        if exit_code == 0 and not crashed:
            self.noticeLbl.setText(_green("AI phát hiện thay đổi hoàn tất thành công!"))

            self.output_files = [output_path]
            stats_path = output_path.replace(".tif", "_statistics.csv")
            if QFile.exists(stats_path):
                self.output_files.append(stats_path)
            viz_path = output_path.replace(".tif", "_visualization.png")
            if QFile.exists(viz_path):
                self.output_files.append(viz_path)
            if self.colored_output_path and QFile.exists(self.colored_output_path):
                self.output_files.append(self.colored_output_path)

            self.show_result_summary(output_path)
            self.add_output_layer_to_map_canvas(output_path, QFileInfo(output_path).baseName())
            self.add_colored_output_to_map_canvas()
            self.add_combined_tiff_to_map_canvas()
        else:
            error = "\n".join(self._stderr)
            self.noticeLbl.setText(f"<font color='red'>Lỗi Python: {error}</font>")

    def show_result_summary(self, output_path: str):
        stats_path = output_path.replace(".tif", "_statistics.csv")
        if not QFile.exists(stats_path):
            return
        try:
            with open(stats_path, encoding="utf-8-sig") as f:
                content = f.read()
        except OSError:
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Kết quả phát hiện thay đổi AI")
        msg_box.setText("Thống kê thay đổi lớp phủ mặt đất (AI):")
        msg_box.setDetailedText(content)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def add_output_layer_to_map_canvas(self, output_path: str, base_name: str):
        # ai_motion_detection.py only writes the *_colored_unique_values.tif / *_with_legend.tif files, so
        # this returns early as it did in the C++ app.
        if not output_path or not QFile.exists(output_path):
            return
        layer = QgsRasterLayer(output_path, f"Change Detection - {base_name}")
        if not layer.isValid():
            return
        QgsProject.instance().addMapLayer(layer)

        qml_path = output_path.replace(".tif", ".qml")
        if QFile.exists(qml_path):
            _msg, ok = layer.loadNamedStyle(qml_path)
            if not ok:
                self.create_fallback_style(layer)
        else:
            self.create_fallback_style(layer)
        layer.triggerRepaint()

    def create_fallback_style(self, layer: QgsRasterLayer):
        if layer is None or not layer.isValid():
            return
        layer.triggerRepaint()

    def add_colored_output_to_map_canvas(self):
        colored_path = self.colored_output_path
        if not colored_path:
            filename = self.outputLedr.text().strip()
            if not filename:
                return
            info = QFileInfo(filename)
            colored_path = QDir(info.absolutePath()).filePath(info.baseName() + "_colored_unique_values.tif")

        if not QFile.exists(colored_path):
            return

        base_name = QFileInfo(colored_path).baseName()
        layer = QgsRasterLayer(colored_path, f"Change Detection (Colored) - {base_name}")
        if not layer.isValid():
            return
        QgsProject.instance().addMapLayer(layer)
        layer.triggerRepaint()
        # C++ then zoomed to the layer when parent() was a QgsMapCanvas; the parent is the main window,
        # so that never happened.

    def add_combined_tiff_to_map_canvas(self):
        if not self.combined_tiff_path or not QFile.exists(self.combined_tiff_path):
            return
        layer_name = QFileInfo(self.combined_tiff_path).baseName()
        layer = QgsRasterLayer(self.combined_tiff_path, layer_name + " (With Legend)")
        if not layer.isValid():
            return
        QgsProject.instance().addMapLayer(layer)
        layer.triggerRepaint()

    def done(self, result: int):
        # The C++ QProcess children died with the dialog; kill a still running script explicitly.
        for runner in self.findChildren(ScriptRunner):
            if runner.is_running():
                runner.finished.disconnect()
                runner.kill()
        super().done(result)
