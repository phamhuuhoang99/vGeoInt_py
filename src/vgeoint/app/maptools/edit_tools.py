"""Select / edit vertices / move features of the layer being edited (not in the C++ app).

QGIS' own vertex and move-feature tools live in the QGIS desktop application and are not exposed in
PyQGIS, so small equivalents are implemented here. All edits go through the layer edit buffer inside an
edit command, so they are undoable and saved/discarded with the edit session.
"""

from qgis.core import (
    Qgis,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapCanvas, QgsMapTool, QgsRubberBand, QgsVertexMarker
from qgis.PyQt.QtCore import QPoint, QRect, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QCursor

PIXEL_TOLERANCE = 6  # px around the cursor when picking features / vertices
DRAG_THRESHOLD = 4  # px before a press turns into a drag


class _LayerTool(QgsMapTool):
    """Base: works on one vector layer, converting canvas <-> layer coordinates."""

    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(canvas)
        self.layer: QgsVectorLayer | None = None
        self.tool_cursor = QCursor(Qt.CursorShape.ArrowCursor)
        self.setCursor(self.tool_cursor)

    def set_layer(self, layer: QgsVectorLayer | None):
        self.layer = layer

    def map_tolerance(self) -> float:
        return PIXEL_TOLERANCE * self.canvas().mapUnitsPerPixel()

    def layer_point(self, pos: QPoint) -> QgsPointXY:
        return self.toLayerCoordinates(self.layer, pos)

    def layer_rect(self, map_rect: QgsRectangle) -> QgsRectangle:
        return self.toLayerCoordinates(self.layer, map_rect)

    def search_rect(self, pos: QPoint) -> QgsRectangle:
        """Small rectangle around `pos`, in layer coordinates."""
        p = self.toMapCoordinates(pos)
        t = self.map_tolerance()
        return self.layer_rect(QgsRectangle(p.x() - t, p.y() - t, p.x() + t, p.y() + t))

    def feature_at(self, pos: QPoint):
        """Topmost feature under the cursor (closest geometry), or None."""
        if self.layer is None:
            return None
        rect = self.search_rect(pos)
        probe = QgsGeometry.fromRect(rect)
        center = QgsGeometry.fromPointXY(rect.center())
        hits = [f for f in self.layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)) if f.geometry().intersects(probe)]
        if not hits:
            return None
        return min(hits, key=lambda f: f.geometry().distance(center))


class SelectFeatureTool(_LayerTool):
    """Click: select the feature under the cursor (Ctrl: add/remove). Drag: select by rectangle.

    Uses the layer selection, so selected features are drawn highlighted by QGIS. Delete key asks the
    window to delete the selection.
    """

    delete_requested = pyqtSignal()

    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(canvas)
        self.press_pos: QPoint | None = None
        self.band = QgsRubberBand(canvas, Qgis.GeometryType.Polygon)
        self.band.setColor(QColor(0, 120, 215, 60))
        self.band.setStrokeColor(QColor(0, 120, 215))
        self.band.setWidth(1)

    def canvasPressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.press_pos = e.pos()

    def canvasMoveEvent(self, e):
        if self.press_pos is None or (e.pos() - self.press_pos).manhattanLength() < DRAG_THRESHOLD:
            return
        r = QRect(self.press_pos, e.pos()).normalized()
        a, b = self.toMapCoordinates(r.topLeft()), self.toMapCoordinates(r.bottomRight())
        self.band.setToGeometry(QgsGeometry.fromRect(QgsRectangle(a, b)), None)

    def canvasReleaseEvent(self, e):
        if self.press_pos is None or self.layer is None:
            self.press_pos = None
            return
        add = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        behavior = Qgis.SelectBehavior.AddToSelection if add else Qgis.SelectBehavior.SetSelection
        if (e.pos() - self.press_pos).manhattanLength() >= DRAG_THRESHOLD:
            r = QRect(self.press_pos, e.pos()).normalized()
            a, b = self.toMapCoordinates(r.topLeft()), self.toMapCoordinates(r.bottomRight())
            self.layer.selectByRect(self.layer_rect(QgsRectangle(a, b)), behavior)
        else:
            f = self.feature_at(e.pos())
            if f is None:
                if not add:
                    self.layer.removeSelection()
            elif add and f.id() in self.layer.selectedFeatureIds():
                self.layer.deselect(f.id())
            else:
                self.layer.selectByIds([f.id()], behavior)
        self.band.reset(Qgis.GeometryType.Polygon)
        self.press_pos = None

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_requested.emit()
            e.accept()

    def deactivate(self):
        self.band.reset(Qgis.GeometryType.Polygon)
        super().deactivate()


class VertexEditTool(_LayerTool):
    """Edit vertices of the selected features (or the feature clicked, which becomes selected).

    Drag a vertex to move it; double-click a segment to insert a vertex; right-click a vertex to delete it.
    """

    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(canvas)
        self.markers: list[QgsVertexMarker] = []
        self.drag: tuple[int, int] | None = None  # (feature id, vertex index)
        self.preview = QgsRubberBand(canvas, Qgis.GeometryType.Line)
        self.preview.setColor(QColor(255, 0, 0, 180))
        self.preview.setWidth(2)

    def set_layer(self, layer):
        if self.layer is not None:
            try:
                self.layer.selectionChanged.disconnect(self.refresh_markers)
                self.layer.geometryChanged.disconnect(self.refresh_markers)
            except (TypeError, RuntimeError):  # not connected / layer already deleted
                pass
        super().set_layer(layer)
        if layer is not None:
            layer.selectionChanged.connect(self.refresh_markers)
            layer.geometryChanged.connect(self.refresh_markers)
        self.refresh_markers()

    def activate(self):
        super().activate()
        self.refresh_markers()

    def deactivate(self):
        self.clear_markers()
        self.preview.reset(Qgis.GeometryType.Line)
        super().deactivate()

    def clear_markers(self):
        for m in self.markers:
            self.canvas().scene().removeItem(m)
        self.markers = []

    def refresh_markers(self, *_):
        self.clear_markers()
        if self.layer is None or not self.isActive():
            return
        for f in self.layer.getSelectedFeatures():
            for v in f.geometry().vertices():
                m = QgsVertexMarker(self.canvas())
                m.setIconType(QgsVertexMarker.IconType.ICON_BOX)
                m.setColor(QColor(255, 0, 0))
                m.setIconSize(9)
                m.setPenWidth(2)
                m.setCenter(self.toMapCoordinates(self.layer, QgsPointXY(v.x(), v.y())))
                self.markers.append(m)

    def _candidates(self, pos):
        if self.layer is None:
            return []
        if self.layer.selectedFeatureCount():
            return list(self.layer.getSelectedFeatures())
        f = self.feature_at(pos)
        return [f] if f is not None else []

    def vertex_at(self, pos):
        """(feature id, vertex index) of the vertex under the cursor among the candidates."""
        p = self.layer_point(pos)
        tolerance = self.search_rect(pos).width() / 2
        best = None
        for f in self._candidates(pos):
            _pt, idx, _before, _after, sqr_dist = f.geometry().closestVertex(p)
            if idx >= 0 and sqr_dist <= tolerance**2 and (best is None or sqr_dist < best[2]):
                best = (f.id(), idx, sqr_dist)
        return best[:2] if best else None

    def canvasPressEvent(self, e):
        if self.layer is None:
            return
        hit = self.vertex_at(e.pos())
        if e.button() == Qt.MouseButton.RightButton:
            if hit is not None:
                fid, idx = hit
                self.layer.beginEditCommand("Xóa đỉnh")
                result = self.layer.deleteVertex(fid, idx)
                self.layer.endEditCommand()
                if result != Qgis.VectorEditResult.Success:
                    self.layer.undoStack().undo()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if hit is None:
            f = self.feature_at(e.pos())
            if f is not None and f.id() not in self.layer.selectedFeatureIds():
                self.layer.selectByIds([f.id()])
            return
        self.drag = hit

    def canvasMoveEvent(self, e):
        if self.drag is None:
            return
        fid, idx = self.drag
        geom = QgsGeometry(self.layer.getFeature(fid).geometry())
        p = self.layer_point(e.pos())
        geom.moveVertex(p.x(), p.y(), idx)
        self.preview.setToGeometry(geom, self.layer)

    def canvasReleaseEvent(self, e):
        if self.drag is None:
            return
        fid, idx = self.drag
        self.drag = None
        self.preview.reset(Qgis.GeometryType.Line)
        p = self.layer_point(e.pos())
        self.layer.beginEditCommand("Di chuyển đỉnh")
        self.layer.moveVertex(p.x(), p.y(), fid, idx)
        self.layer.endEditCommand()
        self.layer.triggerRepaint()

    def canvasDoubleClickEvent(self, e):
        """Insert a vertex on the segment under the cursor."""
        if self.layer is None or QgsWkbTypes.geometryType(self.layer.wkbType()) == Qgis.GeometryType.Point:
            return
        p = self.layer_point(e.pos())
        tolerance = self.search_rect(e.pos()).width() / 2
        for f in self._candidates(e.pos()):
            sqr_dist, closest, after_vertex, _left = f.geometry().closestSegmentWithContext(p)
            if after_vertex > 0 and sqr_dist <= tolerance**2:
                self.layer.beginEditCommand("Thêm đỉnh")
                self.layer.insertVertex(closest.x(), closest.y(), f.id(), after_vertex)
                self.layer.endEditCommand()
                self.layer.triggerRepaint()
                return


class MoveFeatureTool(_LayerTool):
    """Drag the selected features (or the feature under the cursor) to a new position."""

    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(canvas)
        self.start: QgsPointXY | None = None
        self.moving: list = []
        self.tool_cursor = QCursor(Qt.CursorShape.SizeAllCursor)
        self.setCursor(self.tool_cursor)
        self.preview = QgsRubberBand(canvas, Qgis.GeometryType.Polygon)
        self.preview.setColor(QColor(255, 0, 0, 60))
        self.preview.setStrokeColor(QColor(255, 0, 0))
        self.preview.setWidth(2)

    def canvasPressEvent(self, e):
        if self.layer is None or e.button() != Qt.MouseButton.LeftButton:
            return
        f = self.feature_at(e.pos())
        if f is None:
            return
        if f.id() not in self.layer.selectedFeatureIds():
            self.layer.selectByIds([f.id()])
        self.moving = list(self.layer.getSelectedFeatures())
        self.start = self.layer_point(e.pos())

    def _moved(self, p: QgsPointXY):
        dx, dy = p.x() - self.start.x(), p.y() - self.start.y()
        return dx, dy

    def canvasMoveEvent(self, e):
        if self.start is None:
            return
        dx, dy = self._moved(self.layer_point(e.pos()))
        self.preview.reset(self.layer.geometryType())
        for f in self.moving:
            g = QgsGeometry(f.geometry())
            g.translate(dx, dy)
            self.preview.addGeometry(g, self.layer)

    def canvasReleaseEvent(self, e):
        if self.start is None:
            return
        dx, dy = self._moved(self.layer_point(e.pos()))
        self.preview.reset(Qgis.GeometryType.Polygon)
        if dx or dy:
            self.layer.beginEditCommand("Di chuyển đối tượng")
            for f in self.moving:
                self.layer.translateFeature(f.id(), dx, dy)
            self.layer.endEditCommand()
            self.layer.triggerRepaint()
        self.start = None
        self.moving = []
