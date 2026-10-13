"""Port of ImageViewerWidget.cpp."""

from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import QImage, QPixmap
from qgis.PyQt.QtWidgets import QGraphicsScene, QGraphicsView


class ImageViewerWidget(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.m_scene = QGraphicsScene(self)
        self.m_scene.setBackgroundBrush(Qt.GlobalColor.black)
        self.setScene(self.m_scene)

    def set_image(self, image: QImage):
        self.resetTransform()
        self.m_scene.clear()
        self.m_scene.addPixmap(QPixmap.fromImage(image))
        self.setSceneRect(QRectF(0, 0, image.width(), image.height()))
        self.fitInView(self.m_scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.scale(1.25, 1.25)
        else:
            self.scale(0.8, 0.8)
