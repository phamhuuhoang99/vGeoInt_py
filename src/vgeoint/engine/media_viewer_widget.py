"""Port of MediaViewerWidget.cpp."""

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QImage
from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from vgeoint.common.ui import load_ui_class

Ui_MediaViewerWidget = load_ui_class("engine", "MediaViewerWidget")


class MediaViewerWidget(QWidget, Ui_MediaViewerWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

    def view_image(self, file_name: str):
        self.stackedWidget.setCurrentWidget(self.imageViewer)
        img = QImage()
        if img.load(file_name):
            self.imageViewer.set_image(img)
        else:
            QMessageBox.warning(self, "Lỗi xem ảnh", "Ảnh không tồn tại hoặc bị lỗi.")

    def view_video(self, file_name: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(file_name))

    def view_document(self, file_name: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(file_name))
