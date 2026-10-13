"""Port of vGeoCatalog MainWindow.cpp."""

from qgis.PyQt.QtWidgets import QMainWindow, QMessageBox

from vgeoint.common.defines import CATALOG_NAME
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import app_settings

Ui_MainWindowClass = load_ui_class("catalog", "MainWindow")
VERSION = "1.0.2"


class MainWindow(QMainWindow, Ui_MainWindowClass):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.restore_settings()
        self.create_connections()

    def restore_settings(self):
        s = app_settings(CATALOG_NAME)
        for key, restore in (("Geometry", self.restoreGeometry), ("WindowState", self.restoreState)):
            value = s.value(key)
            if value is not None:
                restore(value)
        self.mainWidget.restore_settings()
        self.libraryWidget.restore_settings()

    def save_settings(self):
        s = app_settings(CATALOG_NAME)
        s.setValue("Geometry", self.saveGeometry())
        s.setValue("WindowState", self.saveState())
        self.mainWidget.save_settings()
        self.libraryWidget.save_settings()

    def closeEvent(self, event):
        if QMessageBox.question(self, "Thoát chương trình", "Bạn có chắc chắn muốn thoát?") == QMessageBox.StandardButton.Yes:
            self.libraryWidget.shutdown()
            self.save_settings()
            super().closeEvent(event)
        else:
            event.ignore()

    def create_connections(self):
        self.mainPageBtn.clicked.connect(lambda: self.stackedWidget.setCurrentWidget(self.mainWidget))
        self.libraryPageBtn.clicked.connect(lambda: self.stackedWidget.setCurrentWidget(self.libraryWidget))
        self.stackedWidget.currentChanged.connect(lambda idx: idx == 0 and self.mainWidget.refresh())
        self.infoBtn.clicked.connect(
            lambda: QMessageBox.information(
                self,
                "Thông tin phần mềm",
                f"Phần mềm vGeoCatalog phiên bản {VERSION} (2026)\n"
                "Bản quyền thuộc về Cục Tác chiến/Bộ Tổng Tham mưu\n"
                "\nNhóm tác giả:\n"
                "Phạm Xuân Hoàn, 0989.875.111, hoanpx@gmail.com\n"
                "Phạm Hữu Hoàng, 0941.688.367, phamhuuhoang99@gmail.com",
            )
        )
