"""Port of AveragingWidget, GaussianWidget, MedianWidget, SobelWidget, ScharrWidget, CannyWidget (.cpp)."""

from qgis.PyQt.QtWidgets import QSpinBox, QWidget

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


class CannyWidget(QWidget, Ui_CannyWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        _enable_with(self.averagingFilterChbx, self.rowSbx, self.colSbx)
        _keep_odd(self.rowSbx)
        _keep_odd(self.colSbx)
        _keep_odd(self.kernelSbx)
        self.lowThresholdSbx.valueChanged.connect(lambda value: self.highThresholdSbx.setValue(3 * value))
