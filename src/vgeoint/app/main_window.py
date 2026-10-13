"""Port of MainWindow.cpp — phase 0 skeleton (map canvas only).

Remaining create*() steps are ported in phase 1, keeping the same order as the C++ constructor.
"""

from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsSettings
from qgis.gui import QgsMapCanvas, QgsMessageBar
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QMainWindow, QVBoxLayout

from vgeoint.common.defines import ORG_NAME, SOFT_NAME
from vgeoint.common.paths import RESOURCES_DIR
from vgeoint.common.ui import load_ui_class

Ui_MainWindowClass = load_ui_class("app", "MainWindow")


class MainWindow(QMainWindow, Ui_MainWindowClass):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle(SOFT_NAME)
        self.setWindowIcon(QIcon(str(RESOURCES_DIR / "vGeoInt.ico")))
        self.setAcceptDrops(True)
        self.project = QgsProject.instance()

        self.create_map_canvas()

        # Hệ tọa độ mặc định ban đầu
        settings = QgsSettings(ORG_NAME, SOFT_NAME)
        epsg_id = int(settings.value("MapCanvas/EPSG", 4326))
        srs = QgsCoordinateReferenceSystem.fromEpsgId(epsg_id)
        self.project.setCrs(srs)
        self.project.setEllipsoid(srs.ellipsoidAcronym())

    def create_map_canvas(self):
        self.map_canvas = QgsMapCanvas(self.centralWidget)
        self.message_bar = QgsMessageBar(self.centralWidget)
        layout = QVBoxLayout(self.centralWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.message_bar)
        layout.addWidget(self.map_canvas)
