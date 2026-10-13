"""Port of qgsmaptooladdfeature.cpp + EditAttributeDialog.cpp.

The C++ app carried a copy of QGIS' QgsMapToolDigitizeFeature; PyQGIS exposes the same class, so only
the add-feature behaviour (attribute dialog + topological points) is ported here.
"""

from qgis.core import Qgis, QgsFeature, QgsProject, QgsVectorLayer
from qgis.gui import (
    QgsAdvancedDigitizingDockWidget,
    QgsMapCanvas,
    QgsMapMouseEvent,
    QgsMapToolCapture,
    QgsMapToolDigitizeFeature,
)
from qgis.PyQt.QtCore import QEvent, QPointF, Qt
from qgis.PyQt.QtGui import QMouseEvent
from qgis.PyQt.QtWidgets import QDialog, QGridLayout, QLabel, QLineEdit, QPushButton

from vgeoint.common.utils import message_timeout

Mode = QgsMapToolCapture.CaptureMode


class EditAttributeDialog(QDialog):
    def __init__(self, parent, feature: QgsFeature):
        super().__init__(parent)
        self.feature = feature
        self.setWindowTitle("Nhập thuộc tính")
        self.setModal(True)

        grid = QGridLayout(self)
        fields = feature.fields()
        self.line_edits = []
        for i, field in enumerate(fields):
            grid.addWidget(QLabel(field.name(), self), i, 0, 1, 1)
            edit = QLineEdit(self)
            grid.addWidget(edit, i, 1, 1, 4)
            self.line_edits.append(edit)

        ok_btn = QPushButton("Đồng ý", self)
        ok_btn.setDefault(True)
        cancel_btn = QPushButton("Thoát", self)
        cancel_btn.setDefault(False)
        grid.addWidget(ok_btn, fields.count(), 3, 1, 1)
        grid.addWidget(cancel_btn, fields.count(), 4, 1, 1)

        ok_btn.clicked.connect(self._accept)
        cancel_btn.clicked.connect(self.close)
        self.adjustSize()

    def _accept(self):
        for i, edit in enumerate(self.line_edits):
            self.feature.setAttribute(i, edit.text())
        self.close()


class AddFeatureTool(QgsMapToolDigitizeFeature):
    def __init__(self, canvas: QgsMapCanvas, cad_dock: QgsAdvancedDigitizingDockWidget, mode: Mode, message_bar=None):
        super().__init__(canvas, cad_dock, mode)
        self.digitizingCompleted.connect(self.digitized)
        if message_bar is not None:
            self.messageEmitted.connect(
                lambda msg, level=Qgis.MessageLevel.Info: message_bar.pushMessage(msg, level, message_timeout())
            )
        self._swallow_release = False

    # ------------------------------------------------- double-click to finish
    # Not in the C++ app (right-click only): a double-click also finishes a line/polygon. Qt delivers
    # press, release (adds the last vertex), double-click (finish), release (must not start a new one).
    def canvasDoubleClickEvent(self, e):
        if self.mode() not in (Mode.CaptureLine, Mode.CapturePolygon) or e.button() != Qt.MouseButton.LeftButton:
            super().canvasDoubleClickEvent(e)
            return
        finish = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(e.pos()),
            e.globalPosition(),
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
            e.modifiers(),
        )
        self._swallow_release = True
        self.cadCanvasReleaseEvent(QgsMapMouseEvent(self.canvas(), finish))

    def cadCanvasReleaseEvent(self, e):
        if self._swallow_release and e.button() == Qt.MouseButton.LeftButton:
            self._swallow_release = False
            return
        super().cadCanvasReleaseEvent(e)

    def current_layer(self) -> QgsVectorLayer | None:
        layer = self.canvas().currentLayer()
        return layer if isinstance(layer, QgsVectorLayer) else None

    def add_feature(self, layer: QgsVectorLayer, feature: QgsFeature) -> bool:
        if layer is None or not layer.isEditable():
            return False
        if feature.fields().count():
            EditAttributeDialog(self.canvas(), feature).exec()
        result = layer.addFeature(feature)
        layer.triggerRepaint()
        return result

    def digitized(self, feature: QgsFeature):
        layer = self.current_layer()
        f = QgsFeature(feature)
        if layer is not None and not f.fields().count():
            f.setFields(layer.fields(), True)
        if not self.add_feature(layer, f) or self.mode() not in (Mode.CaptureLine, Mode.CapturePolygon):
            return

        project = QgsProject.instance()
        intersection_layers = project.avoidIntersectionsLayers()
        if intersection_layers:  # try to add topological points also to background layers
            for vl in intersection_layers:
                if vl.geometryType() == Qgis.GeometryType.Polygon and vl.isEditable():
                    vl.addTopologicalPoints(f.geometry())
        elif project.topologicalEditing():
            layer.addTopologicalPoints(f.geometry())
