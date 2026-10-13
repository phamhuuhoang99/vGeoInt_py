"""Port of ImageBlendingDialog.cpp.

The C++ dialog builds its widgets in code (ImageBlendingDialog.ui only holds the window title), so the
widgets are created here in the same order. Pansharpening runs Orfeo Toolbox through
scripts/pansharpening_script.py, which locates otbcli_Pansharpening (see that script).
"""

from enum import IntEnum

from qgis.core import QgsRasterLayer
from qgis.PyQt.QtCore import QDateTime, QFileInfo, QStandardPaths, Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from vgeoint.ai.runner import ScriptRunner, script_path

SCRIPT = "pansharpening_script.py"


class BlendingMethod(IntEnum):
    RCS = 0
    LMVM = 1
    Bayesian = 2


DEFAULT_RADIUS_X_RCS = 9
DEFAULT_RADIUS_Y_RCS = 9
DEFAULT_RADIUS_X_LMVM = 3
DEFAULT_RADIUS_Y_LMVM = 3
DEFAULT_LAMBDA = 0.9999
DEFAULT_S = 1.0


def _default_output() -> str:
    return (
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        + "/pansharpening_output.tif"
    )


class ImageBlendingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_method = BlendingMethod.RCS
        self._stderr: list[str] = []
        self._started = False

        self.runner = ScriptRunner(self)

        self.setWindowTitle("Trộn ảnh - Pansharpening")
        self.setModal(True)
        self.setMinimumSize(800, 600)

        self._setup_ui()
        self._setup_connections()

        self.update_parameters_ui()

    # ---------------------------------------------------------------- UI
    def _setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Vertical, self)

        self._setup_input_group()
        self._setup_method_group()
        self._setup_parameters_group()
        self._setup_output_group()
        self._setup_controls_group()

        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.addWidget(self.input_group)
        top_layout.addWidget(self.method_group)
        top_layout.addWidget(self.parameters_group)
        top_layout.addWidget(self.output_group)
        top_layout.addWidget(self.controls_group)
        top_layout.setSpacing(10)
        splitter.addWidget(top_widget)

        self.log_output = QTextEdit(self)
        self.log_output.setMaximumHeight(150)
        self.log_output.setFont(QFont("Consolas", 9))
        self.log_output.setPlaceholderText("Nhật ký xử lý sẽ hiển thị ở đây...")
        splitter.addWidget(self.log_output)
        splitter.setSizes([400, 150])

        self.main_layout.addWidget(splitter)

    def _setup_input_group(self):
        self.input_group = QGroupBox("Dữ liệu đầu vào", self)
        layout = QGridLayout(self.input_group)

        self.use_layer_input = QCheckBox("Sử dụng layer đã mở", self.input_group)
        self.use_layer_input.setChecked(True)
        layout.addWidget(self.use_layer_input, 0, 0, 1, 3)

        pan_label = QLabel("Ảnh toàn sắc (PAN):", self.input_group)
        self.pan_layer_combo = QComboBox(self.input_group)
        self.pan_image_edit = QLineEdit(self.input_group)
        self.pan_browse_btn = QPushButton("Duyệt...", self.input_group)
        layout.addWidget(pan_label, 1, 0)
        layout.addWidget(self.pan_layer_combo, 1, 1)
        layout.addWidget(self.pan_image_edit, 1, 2)
        layout.addWidget(self.pan_browse_btn, 1, 3)

        ms_label = QLabel("Ảnh đa phổ (MS):", self.input_group)
        self.multispectral_layer_combo = QComboBox(self.input_group)
        self.multispectral_image_edit = QLineEdit(self.input_group)
        self.multispectral_browse_btn = QPushButton("Duyệt...", self.input_group)
        layout.addWidget(ms_label, 2, 0)
        layout.addWidget(self.multispectral_layer_combo, 2, 1)
        layout.addWidget(self.multispectral_image_edit, 2, 2)
        layout.addWidget(self.multispectral_browse_btn, 2, 3)

        from vgeoint.app.main_window import MainWindow

        main_window = MainWindow.instance()
        if main_window is not None:
            for layer in main_window.raster_layers():
                if layer is not None and layer.isValid():
                    self.pan_layer_combo.addItem(layer.name(), layer)
                    self.multispectral_layer_combo.addItem(layer.name(), layer)

        self.use_layer_input.toggled.connect(self._toggle_layer_input)

        self.pan_image_edit.setVisible(False)
        self.multispectral_image_edit.setVisible(False)
        self.pan_browse_btn.setVisible(False)
        self.multispectral_browse_btn.setVisible(False)

    def _toggle_layer_input(self, checked: bool):
        self.pan_layer_combo.setVisible(checked)
        self.multispectral_layer_combo.setVisible(checked)
        self.pan_image_edit.setVisible(not checked)
        self.multispectral_image_edit.setVisible(not checked)
        self.pan_browse_btn.setVisible(not checked)
        self.multispectral_browse_btn.setVisible(not checked)

    def _setup_method_group(self):
        self.method_group = QGroupBox("Phương pháp trộn ảnh", self)
        layout = QHBoxLayout(self.method_group)

        self.method_button_group = QButtonGroup(self)
        self.rcs_radio = QRadioButton("RCS (Resolution-Preserving Color-Sharpening)", self.method_group)
        self.lmvm_radio = QRadioButton("LMVM (Local Mean and Variance Matching)", self.method_group)
        self.bayes_radio = QRadioButton("Bayesian (Bayesian Data Fusion)", self.method_group)
        self.method_button_group.addButton(self.rcs_radio, 0)
        self.method_button_group.addButton(self.lmvm_radio, 1)
        self.method_button_group.addButton(self.bayes_radio, 2)
        self.rcs_radio.setChecked(True)

        layout.addWidget(self.rcs_radio)
        layout.addWidget(self.lmvm_radio)
        layout.addWidget(self.bayes_radio)

    def _setup_parameters_group(self):
        self.parameters_group = QGroupBox("Tham số", self)
        self.parameters_layout = QGridLayout(self.parameters_group)
        g = self.parameters_group

        self.radius_x_label = QLabel("Bán kính X:", g)
        self.radius_x_spin = QSpinBox(g)
        self.radius_x_spin.setRange(1, 50)
        self.radius_x_spin.setValue(DEFAULT_RADIUS_X_RCS)

        self.radius_y_label = QLabel("Bán kính Y:", g)
        self.radius_y_spin = QSpinBox(g)
        self.radius_y_spin.setRange(1, 50)
        self.radius_y_spin.setValue(DEFAULT_RADIUS_Y_RCS)

        self.lambda_label = QLabel("Lambda (λ):", g)
        self.lambda_spin = QDoubleSpinBox(g)
        self.lambda_spin.setRange(0.0001, 0.9999)
        self.lambda_spin.setDecimals(4)
        self.lambda_spin.setSingleStep(0.0001)
        self.lambda_spin.setValue(DEFAULT_LAMBDA)

        self.s_label = QLabel("Hệ số S:", g)
        self.s_spin = QDoubleSpinBox(g)
        self.s_spin.setRange(0.1, 10.0)
        self.s_spin.setDecimals(2)
        self.s_spin.setSingleStep(0.1)
        self.s_spin.setValue(DEFAULT_S)

        self.parameters_layout.addWidget(self.radius_x_label, 0, 0)
        self.parameters_layout.addWidget(self.radius_x_spin, 0, 1)
        self.parameters_layout.addWidget(self.radius_y_label, 0, 2)
        self.parameters_layout.addWidget(self.radius_y_spin, 0, 3)
        self.parameters_layout.addWidget(self.lambda_label, 1, 0)
        self.parameters_layout.addWidget(self.lambda_spin, 1, 1)
        self.parameters_layout.addWidget(self.s_label, 1, 2)
        self.parameters_layout.addWidget(self.s_spin, 1, 3)

    def _setup_output_group(self):
        self.output_group = QGroupBox("Đầu ra", self)
        layout = QGridLayout(self.output_group)

        output_label = QLabel("Tệp đầu ra:", self.output_group)
        self.output_path_edit = QLineEdit(self.output_group)
        self.output_browse_btn = QPushButton("Duyệt...", self.output_group)
        self.output_path_edit.setText(_default_output())

        self.add_to_map_check_box = QCheckBox("Thêm vào bản đồ sau khi xử lý", self.output_group)
        self.add_to_map_check_box.setChecked(True)

        layout.addWidget(output_label, 0, 0)
        layout.addWidget(self.output_path_edit, 0, 1)
        layout.addWidget(self.output_browse_btn, 0, 2)
        layout.addWidget(self.add_to_map_check_box, 1, 0, 1, 3)

    def _setup_controls_group(self):
        self.controls_group = QGroupBox("Điều khiển", self)
        layout = QHBoxLayout(self.controls_group)

        self.process_btn = QPushButton("Xử lý", self.controls_group)
        self.reset_btn = QPushButton("Đặt lại", self.controls_group)
        self.close_btn = QPushButton("Đóng", self.controls_group)
        self.progress_bar = QProgressBar(self.controls_group)
        self.progress_bar.setVisible(False)
        self.process_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")

        layout.addWidget(self.process_btn)
        layout.addWidget(self.reset_btn)
        layout.addStretch()
        layout.addWidget(self.progress_bar)
        layout.addStretch()
        layout.addWidget(self.close_btn)

    def _setup_connections(self):
        self.method_button_group.idClicked.connect(self.on_method_changed)
        self.pan_browse_btn.clicked.connect(self.on_input_pan_browse)
        self.multispectral_browse_btn.clicked.connect(self.on_input_multispectral_browse)
        self.output_browse_btn.clicked.connect(self.on_output_browse)
        self.process_btn.clicked.connect(self.on_process_clicked)
        self.reset_btn.clicked.connect(self.on_reset_clicked)
        self.close_btn.clicked.connect(self.close)

        self.runner.started.connect(self._on_started)
        # The C++ timer read stdout once a second; the runner delivers each line as it arrives.
        self.runner.output_line.connect(self.log_message)
        self.runner.error_line.connect(self._stderr.append)
        self.runner.finished.connect(self._on_runner_finished)

    # ---------------------------------------------------------------- slots
    def on_method_changed(self, _id: int = -1):
        self.current_method = BlendingMethod(self.method_button_group.checkedId())
        self.update_parameters_ui()

    def update_parameters_ui(self):
        for w in (
            self.radius_x_label,
            self.radius_x_spin,
            self.radius_y_label,
            self.radius_y_spin,
            self.lambda_label,
            self.lambda_spin,
            self.s_label,
            self.s_spin,
        ):
            w.setVisible(False)

        if self.current_method in (BlendingMethod.RCS, BlendingMethod.LMVM):
            for w in (self.radius_x_label, self.radius_x_spin, self.radius_y_label, self.radius_y_spin):
                w.setVisible(True)
            if self.current_method == BlendingMethod.RCS:
                self.radius_x_spin.setValue(DEFAULT_RADIUS_X_RCS)
                self.radius_y_spin.setValue(DEFAULT_RADIUS_Y_RCS)
            else:
                self.radius_x_spin.setValue(DEFAULT_RADIUS_X_LMVM)
                self.radius_y_spin.setValue(DEFAULT_RADIUS_Y_LMVM)
        else:
            for w in (self.lambda_label, self.lambda_spin, self.s_label, self.s_spin):
                w.setVisible(True)

    _IMAGE_FILTER = "Tệp ảnh (*.tif *.tiff *.jp2 *.jpg *.png *.img *.hdr)"

    def on_input_pan_browse(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh toàn sắc", "", self._IMAGE_FILTER)
        if file_name:
            self.pan_image_edit.setText(file_name)

    def on_input_multispectral_browse(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh đa phổ", "", self._IMAGE_FILTER)
        if file_name:
            self.multispectral_image_edit.setText(file_name)

    def on_output_browse(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Chọn tệp đầu ra", self.output_path_edit.text(), "Tệp ảnh (*.tif *.tiff)"
        )
        if file_name:
            self.output_path_edit.setText(file_name)

    def _input_paths(self) -> tuple[str, str]:
        if self.use_layer_input.isChecked():
            pan = self.pan_layer_combo.currentData()
            ms = self.multispectral_layer_combo.currentData()
            return pan.source(), ms.source()
        return self.pan_image_edit.text(), self.multispectral_image_edit.text()

    def validate_inputs(self) -> bool:
        if self.use_layer_input.isChecked():
            if self.pan_layer_combo.currentIndex() < 0 or self.multispectral_layer_combo.currentIndex() < 0:
                QMessageBox.warning(self, "Lỗi", "Vui lòng chọn layer cho ảnh toàn sắc và ảnh đa phổ.")
                return False
            pan = self.pan_layer_combo.currentData()
            ms = self.multispectral_layer_combo.currentData()
            if not isinstance(pan, QgsRasterLayer) or not isinstance(ms, QgsRasterLayer):
                QMessageBox.warning(self, "Lỗi", "Không thể lấy thông tin layer.")
                return False
        pan_input, ms_input = self._input_paths()

        if not pan_input or not ms_input:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn ảnh toàn sắc và ảnh đa phổ.")
            return False
        if not QFileInfo.exists(pan_input) or not QFileInfo.exists(ms_input):
            QMessageBox.warning(self, "Lỗi", "Tệp đầu vào không tồn tại.")
            return False
        if not self.output_path_edit.text():
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn tệp đầu ra.")
            return False
        return True

    def on_process_clicked(self):
        if not self.validate_inputs():
            return
        self.process_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.log_message("Bắt đầu quá trình trộn ảnh...")
        self.run_pansharpening_process()

    def on_reset_clicked(self):
        self.reset_parameters()
        self.log_output.clear()
        self.log_message("Đã đặt lại tham số về giá trị mặc định.")

    def reset_parameters(self):
        self.rcs_radio.setChecked(True)
        self.current_method = BlendingMethod.RCS
        self.update_parameters_ui()
        self.output_path_edit.setText(_default_output())
        self.add_to_map_check_box.setChecked(True)

    # ---------------------------------------------------------------- process
    def run_pansharpening_process(self):
        script = script_path(SCRIPT)
        if not script.exists():
            self.log_message("Lỗi: Không tìm thấy file script: " + str(script))
            QMessageBox.critical(self, "Lỗi", "Không tìm thấy file pansharpening_script.py trong thư mục scripts/")
            self.on_process_error()
            return

        args = self.build_command_arguments()
        self.log_message("Python script: " + str(script))
        self.log_message("Arguments: " + " ".join([str(script), *args]))

        self._stderr.clear()
        self._started = False
        self.runner.start_script(SCRIPT, args)

    def _on_started(self):
        self._started = True
        self.log_message("Đang chạy OTB Pansharpening...")

    def build_command_arguments(self) -> list[str]:
        args = list(self._input_paths())
        args.append(self.output_path_edit.text())
        if self.current_method == BlendingMethod.RCS:
            args += ["rcs", "radiusx", str(self.radius_x_spin.value()), "radiusy", str(self.radius_y_spin.value())]
        elif self.current_method == BlendingMethod.LMVM:
            args += ["lmvm", "radiusx", str(self.radius_x_spin.value()), "radiusy", str(self.radius_y_spin.value())]
        else:
            args += ["bayes", "lambda_weight", f"{self.lambda_spin.value():.4f}", "s", f"{self.s_spin.value():.2f}"]
        return args

    def _on_runner_finished(self, exit_code: int, crashed: bool):
        if not self._started:
            self.log_message("Lỗi: Không thể khởi động quá trình Python.")
            self.on_process_error()
        elif crashed:
            self.on_process_error()
        else:
            self.on_process_finished(exit_code)

    def on_process_finished(self, exit_code: int):
        self.progress_bar.setVisible(False)
        self.process_btn.setEnabled(True)

        if exit_code == 0:
            self.log_message("✓ Quá trình trộn ảnh hoàn thành thành công!")
            if self.add_to_map_check_box.isChecked():
                from vgeoint.app.main_window import MainWindow

                output_path = self.output_path_edit.text()
                main_window = MainWindow.instance()
                if QFileInfo.exists(output_path) and main_window is not None:
                    layer = QgsRasterLayer(output_path, "Pansharpened Image")
                    if layer.isValid():
                        main_window.project.addMapLayer(layer)
                        self.log_message("✓ Đã thêm layer vào bản đồ.")
                    else:
                        self.log_message("⚠ Không thể thêm layer vào bản đồ.")
            QMessageBox.information(self, "Thành công", "Quá trình trộn ảnh đã hoàn thành thành công!")
        else:
            self.log_message("✗ Quá trình thất bại: " + "\n".join(self._stderr))
            QMessageBox.critical(self, "Lỗi", "Quá trình trộn ảnh thất bại. Xem nhật ký để biết chi tiết.")

    def on_process_error(self):
        self.progress_bar.setVisible(False)
        self.process_btn.setEnabled(True)
        self.log_message("✗ Lỗi trong quá trình xử lý.")
        QMessageBox.critical(self, "Lỗi", "Đã xảy ra lỗi trong quá trình xử lý.")

    def log_message(self, message: str):
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        self.log_output.append(f"[{timestamp}] {message}")
        bar = self.log_output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def done(self, result: int):
        # The C++ std::unique_ptr<QProcess> killed the script when the dialog was destroyed.
        if self.runner.is_running():
            self.runner.finished.disconnect(self._on_runner_finished)
            self.runner.kill()
        super().done(result)
