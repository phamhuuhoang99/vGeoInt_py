"""Port of TagAnnotationSettingDialog.cpp."""

from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QColorDialog, QDialog

from vgeoint.app.maptools.annotation import MapToolTagAnnotation, tag_settings
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import settings

Ui_TagAnnotationSettingDialog = load_ui_class("app", "TagAnnotationSettingDialog")


class TagAnnotationSettingDialog(QDialog, Ui_TagAnnotationSettingDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        t = tag_settings()

        self.fromSbx.setValue(MapToolTagAnnotation.count())
        self.set_color(QColor(t["Red"], t["Green"], t["Blue"]))
        self.sizeSbx.setValue(t["Size"])
        self.alignCbx.setCurrentIndex(t["Align"])
        self.widthSbx.setValue(t["Width"])
        self.heightSbx.setValue(t["Height"])
        self.dxSbx.setValue(t["Dx"])
        self.dySbx.setValue(t["Dy"])

        self.resetBtn.clicked.connect(self._reset)
        self.colorPickerBtn.clicked.connect(self._pick_color)
        self.defaultBtn.clicked.connect(lambda: self.set_color(QColor(255, 0, 0)))
        self.okBtn.clicked.connect(self._ok)
        self.cancelBtn.clicked.connect(self.close)

    def set_color(self, color: QColor):
        self.color = QColor(color)
        self.colorLbl.setStyleSheet(f"background-color: rgb({color.red()}, {color.green()}, {color.blue()})")

    def _reset(self):
        MapToolTagAnnotation.reset_counter()
        self.fromSbx.setValue(MapToolTagAnnotation.count())

    def _pick_color(self):
        t = tag_settings()
        color = QColorDialog.getColor(QColor(t["Red"], t["Green"], t["Blue"]), self, "Chọn màu")
        if color.isValid():
            self.set_color(color)

    def _ok(self):
        MapToolTagAnnotation.set_counter(self.fromSbx.value())
        s = settings()
        for key, value in (
            ("Red", self.color.red()),
            ("Green", self.color.green()),
            ("Blue", self.color.blue()),
            ("Size", self.sizeSbx.value()),
            ("Align", self.alignCbx.currentIndex()),
            ("Width", self.widthSbx.value()),
            ("Height", self.heightSbx.value()),
            ("Dx", self.dxSbx.value()),
            ("Dy", self.dySbx.value()),
        ):
            s.setValue(f"TagCounting/{key}", value)
        self.close()
