"""The arrow ("Chọn đối tượng") tool: identify vector features and also pick annotations.

Not in the C++ app, where annotations could only be selected with the annotation tools. Events that
hit an annotation (or the frame handles of the selected one) are handled by the annotation tool logic
- select, move, resize, double-click to edit, right-click menu, Delete - without ever creating a new
annotation; everything else goes to QgsMapToolIdentifyFeature as before.
"""

from qgis.gui import QgsMapCanvas, QgsMapCanvasAnnotationItem, QgsMapToolIdentifyFeature
from qgis.PyQt.QtCore import QPointF, Qt

from vgeoint.app.maptools.annotation import MapToolAnnotation

A = QgsMapCanvasAnnotationItem.MouseMoveAction


class _AnnotationPicker(MapToolAnnotation):
    """Annotation tool that never creates annotations (create_item returns None)."""


class CursorTool(QgsMapToolIdentifyFeature):
    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(canvas)
        self.annotations = _AnnotationPicker(canvas)
        self._on_annotation = False

    def _hits_annotation(self, pos) -> bool:
        p = QPointF(pos)
        if self.annotations.item_at_pos(p) is not None:
            return True
        selected = self.annotations.selected_items()
        return bool(selected) and self.annotations.get_smart_move_action(selected[0], p) != A.NoAction

    def canvasPressEvent(self, e):
        if self._hits_annotation(e.pos()):
            self._on_annotation = True
            self.annotations.canvasPressEvent(e)
            return
        self._on_annotation = False
        for item in self.annotations.selected_items():
            item.setSelected(False)
        super().canvasPressEvent(e)

    def canvasMoveEvent(self, e):
        if self._on_annotation or (self.annotations.selected_items() and not e.buttons()):
            self.annotations.canvasMoveEvent(e)  # drag, or resize/move cursor feedback
            if self._on_annotation:
                return
        super().canvasMoveEvent(e)

    def canvasReleaseEvent(self, e):
        if self._on_annotation:
            self._on_annotation = False
            self.annotations.canvasReleaseEvent(e)
            return
        super().canvasReleaseEvent(e)

    def canvasDoubleClickEvent(self, e):
        if self.annotations.item_at_pos(QPointF(e.pos())) is not None:
            self.annotations.canvasDoubleClickEvent(e)
            return
        super().canvasDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if self.annotations.selected_items() and e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.annotations.keyPressEvent(e)
            return
        super().keyPressEvent(e)
