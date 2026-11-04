"""Port of AveragingWidget, GaussianWidget, MedianWidget, SobelWidget, ScharrWidget, CannyWidget (.cpp);
PrewittWidget and LaplacianWidget are new (not in the C++ app)."""

from qgis.PyQt.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QRadioButton, QSpinBox, QWidget

from vgeoint.common.ui import load_ui_class

Ui_AveragingWidget = load_ui_class("app", "AveragingWidget")
Ui_GaussianWidget = load_ui_class("app", "GaussianWidget")
Ui_MedianWidget = load_ui_class("app", "MedianWidget")
Ui_SobelWidget = load_ui_class("app", "SobelWidget")
Ui_ScharrWidget = load_ui_class("app", "ScharrWidget")
Ui_CannyWidget = load_ui_class("app", "CannyWidget")


def _keep_odd(spin_box: QSpinBox):
    """Kích thước kernel luôn là số lẻ: giá trị chẵn bị giảm đi 1."""

    def on_value_changed(value: int):
        if value % 2 == 0:
            spin_box.setValue(value - 1)

    spin_box.valueChanged.connect(on_value_changed)


def _enable_with(check_box, *widgets):
    def on_toggled(checked: bool):
        for w in widgets:
            w.setEnabled(checked)

    check_box.toggled.connect(on_toggled)


class AveragingWidget(QWidget, Ui_AveragingWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        _keep_odd(self.rowSbx)
        _keep_odd(self.colSbx)


class GaussianWidget(QWidget, Ui_GaussianWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        _keep_odd(self.rowSbx)
        _keep_odd(self.colSbx)


class MedianWidget(QWidget, Ui_MedianWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        _keep_odd(self.kernelSbx)


class SobelWidget(QWidget, Ui_SobelWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        _enable_with(self.gaussFilterChbx, self.rowSbx, self.colSbx)
        _keep_odd(self.rowSbx)
        _keep_odd(self.colSbx)
        _keep_odd(self.kernelSbx)


class ScharrWidget(QWidget, Ui_ScharrWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        _enable_with(self.gaussFilterChbx, self.rowSbx, self.colSbx)
        _keep_odd(self.rowSbx)
        _keep_odd(self.colSbx)


class PrewittWidget(ScharrWidget):
    """Scharr's options (Gaussian pre-filter, X / Y direction) plus both directions (gradient magnitude)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bothAxesRbtn = QRadioButton("Cả hai hướng (độ lớn gradient)", self)
        self.gridLayout.addWidget(self.bothAxesRbtn, 4, 0)


class LaplacianWidget(QWidget):
    """Kernel size (1, 3, 5, 7) and an optional Gaussian pre-filter (Laplacian of Gaussian, less noise)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        self.gaussFilterChbx = QCheckBox("Lọc trước qua phép lọc Gaussian (LoG):", self)
        self.rowSbx = QSpinBox(self)
        self.colSbx = QSpinBox(self)
        for box in (self.rowSbx, self.colSbx):
            box.setRange(1, 31)
            box.setValue(3)
            box.setEnabled(False)
            _keep_odd(box)
        size = QHBoxLayout()
        size.addWidget(QLabel("Rộng", self))
        size.addWidget(self.rowSbx)
        size.addWidget(QLabel("Cao", self))
        size.addWidget(self.colSbx)
        form.addRow(self.gaussFilterChbx)
        form.addRow(size)
        _enable_with(self.gaussFilterChbx, self.rowSbx, self.colSbx)
        self.kernelCbx = QComboBox(self)
        for k in (1, 3, 5, 7):
            self.kernelCbx.addItem(str(k), k)
        self.kernelCbx.setCurrentIndex(1)
        form.addRow("Kích thước nhân:", self.kernelCbx)


class CannyWidget(QWidget, Ui_CannyWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        _enable_with(self.averagingFilterChbx, self.rowSbx, self.colSbx)
        _keep_odd(self.rowSbx)
        _keep_odd(self.colSbx)
        _keep_odd(self.kernelSbx)
        self.lowThresholdSbx.valueChanged.connect(lambda value: self.highThresholdSbx.setValue(3 * value))
