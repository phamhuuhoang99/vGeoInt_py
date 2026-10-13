"""Port of SettingsDialog.cpp."""

from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QColorDialog, QDialog

from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import settings

Ui_SettingsDialog = load_ui_class("app", "SettingsDialog")

CRS_ITEMS = (
    ("GEO: WGS 84", 4326),
    ("PROJ: WGS 84 / UTM zone 48N", 32648),
    ("PROJ: WGS 84 / UTM zone 49N", 32649),
    ("GEO: VN2000", 4756),
    ("PROJ: VN2000 / UTM zone 48N", 3405),
    ("PROJ: VN2000 / UTM zone 49N", 3406),
)


def _main_window():
    from vgeoint.app.main_window import MainWindow

    return MainWindow.instance()


class SettingsDialog(QDialog, Ui_SettingsDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        for text, epsg in CRS_ITEMS:
            self.crsCbx.addItem(text, epsg)

        s = settings()
        epsg_id = int(s.value("MapCanvas/EPSG", 4326))
        self.crsCbx.setCurrentIndex(self.crsCbx.findData(epsg_id))
        self.set_color(
            QColor(int(s.value("MapCanvas/Red", 255)), int(s.value("MapCanvas/Green", 255)), int(s.value("MapCanvas/Blue", 255)))
        )

        self.defaultBtn.clicked.connect(self._default)
        self.colorPickerBtn.clicked.connect(self._pick_color)
        self.okBtn.clicked.connect(self._ok)
        self.cancelBtn.clicked.connect(self.close)

    def set_color(self, color: QColor):
        # C++ đọc lại màu từ palette của colorLbl; ở đây giữ trong self.color
        self.color = QColor(color)
        self.colorLbl.setStyleSheet(f"background-color: rgb({color.red()}, {color.green()}, {color.blue()})")

    def _default(self):
        self.crsCbx.setCurrentIndex(0)
        self.set_color(QColor(255, 255, 255))

    def _pick_color(self):
        init_color = _main_window().map_canvas.canvasColor()
        color = QColorDialog.getColor(init_color, self, "Chọn màu nền")
        if color.isValid():
            self.set_color(color)

    def _ok(self):
        epsg_id = int(self.crsCbx.currentData())
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem.fromEpsgId(epsg_id))
        _main_window().map_canvas.setCanvasColor(self.color)

        s = settings()
        s.setValue("MapCanvas/EPSG", epsg_id)
        s.setValue("MapCanvas/Red", self.color.red())
        s.setValue("MapCanvas/Green", self.color.green())
        s.setValue("MapCanvas/Blue", self.color.blue())
        self.close()
