"""Port of MapToolAnnotation / MapToolTextAnnotation / MapToolTagAnnotation / TagAnnotation.

Only the code paths the C++ tool actually uses are ported; its unused frame-corner cache and debug
helpers are dropped.
"""

import math
from enum import Enum

from qgis.core import (
    QgsCoordinateTransform,
    QgsCsException,
    QgsPointXY,
    QgsProject,
    QgsTextAnnotation,
)
from qgis.gui import QgsMapCanvas, QgsMapCanvasAnnotationItem, QgsMapTool
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QPointF, QRectF, QSizeF, Qt
from qgis.PyQt.QtGui import QCursor, QTextDocument, QTextOption
from qgis.PyQt.QtWidgets import QApplication, QMenu, QMessageBox

from vgeoint.common.utils import get_icon, settings

A = QgsMapCanvasAnnotationItem.MouseMoveAction
Btn = QMessageBox.StandardButton

RESIZE_RIGHT = {A.ResizeFrameRight, A.ResizeFrameRightDown, A.ResizeFrameRightUp}
RESIZE_LEFT = {A.ResizeFrameLeft, A.ResizeFrameLeftDown, A.ResizeFrameLeftUp}
RESIZE_UP = {A.ResizeFrameUp, A.ResizeFrameLeftUp, A.ResizeFrameRightUp}
RESIZE_DOWN = {A.ResizeFrameDown, A.ResizeFrameLeftDown, A.ResizeFrameRightDown}


class PinnedEdge(Enum):
    NONE = 0
    TOP = 1
    BOTTOM = 2
    LEFT = 3
    RIGHT = 4


def _key(annotation) -> int:
    """Stable key for an annotation: its C++ address (Python wrappers may be recreated)."""
    return sip.unwrapinstance(annotation)


def _annotations():
    return QgsProject.instance().annotationManager().annotations()


class MapToolAnnotation(QgsMapTool):
    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(canvas)
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.default_size = QSizeF(80, 30)
        self.default_offset = QPointF(-40, -60)
        self.current_move_action = A.NoAction
        self.last_mouse_position = QPointF(0, 0)
        self.item_visibilities = True
        # Original map positions before pinning (restored on unpin) and pinned edges, keyed by _key(annotation)
        self.original_map_positions: dict[int, QgsPointXY] = {}
        self.pinned_edges: dict[int, PinnedEdge] = {}

    # ---------------------------------------------------------------- hooks
    def create_item(self):
        return None

    def create_item_editor(self, item: QgsMapCanvasAnnotationItem):
        if item is None or item.annotation() is None:
            return None
        if isinstance(item.annotation(), QgsTextAnnotation):
            from vgeoint.app.dialogs.text_annotation import TextAnnotationDialog

            return TextAnnotationDialog(item)
        return None

    # --------------------------------------------------------------- events
    def canvasPressEvent(self, e):
        canvas = self.canvas()
        if e.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(e.pos())
            return

        self.last_mouse_position = QPointF(e.pos())
        items = self.selected_items()
        if items:
            self.current_move_action = self.get_smart_move_action(items[0], QPointF(e.pos()))
            if self.current_move_action != A.NoAction:
                return

        modifiers = QApplication.keyboardModifiers()
        if modifiers not in (Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier):
            canvas.scene().clearSelection()  # bỏ chọn tất cả anno đang chọn

        existing = self.item_at_pos(QPointF(e.pos()))
        if existing is not None:
            existing.setSelected(True)
            return

        # otherwise create new one
        annotation = self.create_item()
        if annotation is None:
            return
        map_pos = self.transform_canvas_to_annotation(self.toMapCoordinates(e.pos()), annotation)
        annotation.setMapPosition(map_pos)
        annotation.setMapPositionCrs(canvas.mapSettings().destinationCrs())
        annotation.setRelativePosition(QPointF(e.pos().x() / canvas.width(), e.pos().y() / canvas.height()))

        px_to_mm = self.pixel_to_mm()
        annotation.setFrameSizeMm(QSizeF(self.default_size.width() * px_to_mm, self.default_size.height() * px_to_mm))
        annotation.setFrameOffsetFromReferencePointMm(
            QPointF(self.default_offset.x() * px_to_mm, self.default_offset.y() * px_to_mm)
        )
        QgsProject.instance().annotationManager().addAnnotation(annotation)

        # select newly added item
        for item in canvas.items():
            if isinstance(item, QgsMapCanvasAnnotationItem) and item.annotation() is annotation:
                item.setSelected(True)
                break

    def _show_context_menu(self, pos):
        canvas = self.canvas()
        item_at_click = self.item_at_pos(QPointF(pos))
        menu = QMenu(canvas)
        annotations = self.selected_items()

        if len(annotations) == 1 or (not annotations and item_at_click is not None):
            if item_at_click is not None and annotations and item_at_click is not annotations[0]:
                annotations[0].setSelected(False)
                item_at_click.setSelected(True)
            if not annotations and item_at_click is not None:
                item_at_click.setSelected(True)

            pin_menu = menu.addMenu(get_icon("TextAnnotation/Pin.svg"), "Gắn vào")
            pin_menu.addAction(get_icon("TextAnnotation/PinTop.svg"), "Trên", lambda: self.pin(PinnedEdge.TOP))
            pin_menu.addAction(get_icon("TextAnnotation/PinBottom.svg"), "Dưới", lambda: self.pin(PinnedEdge.BOTTOM))
            pin_menu.addAction(get_icon("TextAnnotation/PinLeft.svg"), "Trái", lambda: self.pin(PinnedEdge.LEFT))
            pin_menu.addAction(get_icon("TextAnnotation/PinRight.svg"), "Phải", lambda: self.pin(PinnedEdge.RIGHT))
            pin_menu.addSeparator()
            menu.addAction(get_icon("TextAnnotation/Unpin.svg"), "Bỏ gắn", self.unpin)

            target = item_at_click if item_at_click is not None else annotations[0]
            menu.addAction(get_icon("TextAnnotation/Clear.svg"), "Bỏ chọn", lambda: target.setSelected(False))
            menu.addAction(get_icon("TextAnnotation/Remove.svg"), "Xóa", self.remove_selected_item)
        elif len(annotations) > 1:
            menu.addAction(
                get_icon("TextAnnotation/Clear.svg"), "Bỏ chọn tất cả nhãn", canvas.scene().clearSelection
            )
            menu.addAction(get_icon("TextAnnotation/Remove.svg"), "Xóa các nhãn đang chọn", self.remove_selected_item)
        elif _annotations():
            canvas.scene().clearSelection()
            # Create visibility toggle action based on current state
            if self.item_visibilities:
                act = menu.addAction(get_icon("TextAnnotation/Hide.svg"), "Ẩn tất cả nhãn")
            else:
                act = menu.addAction("Hiện tất cả nhãn")
            act.setCheckable(True)
            act.setChecked(False)
            act.triggered.connect(self.toggle_item_visibilities)
            menu.addAction("Xóa tất cả nhãn", self.remove_all_items)

        menu.exec(QCursor.pos())

    def canvasReleaseEvent(self, e):
        self.current_move_action = A.NoAction
        self.canvas().setCursor(self.cursor())

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_T and e.modifiers() == Qt.KeyboardModifier.ControlModifier:
            self.toggle_text_item_visibilities()
        items = self.selected_items()
        if not items:
            return
        item = items[0]
        if e.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            neutral = QCursor(item.cursorShapeForAction(A.NoAction))
            QgsProject.instance().annotationManager().removeAnnotation(item.annotation())
            self.canvas().setCursor(neutral)
            e.ignore()

    def canvasMoveEvent(self, e):
        items = self.selected_items()
        if not items or items[0].annotation() is None:
            return
        item = items[0]
        annotation = item.annotation()
        canvas = self.canvas()
        pos = QPointF(e.pos())

        if e.buttons() & Qt.MouseButton.LeftButton:
            delta = pos - self.last_mouse_position
            if self.current_move_action == A.MoveMapPosition:
                self._move_map_position(item, annotation, e, delta)
            elif self.current_move_action == A.MoveFramePosition:
                self.update_annotation_position(item, delta)
            elif self.current_move_action != A.NoAction:
                self._resize_frame(item, annotation, delta)
        else:
            # Update cursor based on smart hit detection for better visual feedback
            move_action = self.get_smart_move_action(item, pos)
            is_pinned = not annotation.hasFixedMapPosition()
            if not is_pinned and self.is_near_reference_point(item, pos, 10):
                new_cursor = QCursor(Qt.CursorShape.PointingHandCursor)
            elif is_pinned and move_action in (A.MoveMapPosition, A.MoveFramePosition):
                new_cursor = QCursor(item.cursorShapeForAction(A.MoveFramePosition))
            else:
                new_cursor = QCursor(item.cursorShapeForAction(move_action))
            if canvas.cursor().shape() != new_cursor.shape():
                canvas.setCursor(new_cursor)
        self.last_mouse_position = pos

    def _move_map_position(self, item, annotation, e, delta: QPointF):
        canvas = self.canvas()
        if not annotation.hasFixedMapPosition():
            rel = annotation.relativePosition()
            rel_dx = delta.x() / canvas.width()
            rel_dy = delta.y() / canvas.height()

            edge = self.pinned_edges.get(_key(annotation), PinnedEdge.NONE)
            if edge == PinnedEdge.NONE:
                # Fallback for legacy pinned annotations without cached edge.
                distances = {
                    PinnedEdge.TOP: abs(rel.y()),
                    PinnedEdge.BOTTOM: abs(1.0 - rel.y()),
                    PinnedEdge.LEFT: abs(rel.x()),
                    PinnedEdge.RIGHT: abs(1.0 - rel.x()),
                }
                edge = min(distances, key=distances.get)

            new_x, new_y = rel.x(), rel.y()
            if edge in (PinnedEdge.TOP, PinnedEdge.BOTTOM):
                new_x += rel_dx
            else:
                new_y += rel_dy
            annotation.setRelativePosition(QPointF(max(0.0, min(1.0, new_x)), max(0.0, min(1.0, new_y))))
        else:
            annotation.setMapPosition(self.transform_canvas_to_annotation(e.snapPoint(), annotation))
            annotation.setRelativePosition(QPointF(e.pos().x() / canvas.width(), e.pos().y() / canvas.height()))
        item.update()
        QgsProject.instance().setDirty(True)

    def _resize_frame(self, item, annotation, delta: QPointF):
        canvas = self.canvas()
        mm_to_px, px_to_mm = self.mm_to_pixel(), self.pixel_to_mm()
        size_mm = annotation.frameSizeMm()
        offset_mm = annotation.frameOffsetFromReferencePointMm()

        xmin = offset_mm.x() * mm_to_px
        ymin = offset_mm.y() * mm_to_px
        xmax = xmin + size_mm.width() * mm_to_px
        ymax = ymin + size_mm.height() * mm_to_px
        rel_x = annotation.relativePosition().x()
        rel_y = annotation.relativePosition().y()
        action = self.current_move_action
        fixed = annotation.hasFixedMapPosition()

        if action in RESIZE_RIGHT:
            xmax += delta.x()
        if action in RESIZE_LEFT:
            xmin += delta.x()
            if not fixed:
                rel_x = (rel_x * canvas.width() + delta.x()) / canvas.width()
        if action in RESIZE_UP:
            ymin += delta.y()
            if not fixed:
                rel_y = (rel_y * canvas.height() + delta.y()) / canvas.height()
        if action in RESIZE_DOWN:
            ymax += delta.y()

        min_size = 10.0  # Minimum 10 pixels
        xmin, xmax = min(xmin, xmax), max(xmin, xmax)
        ymin, ymax = min(ymin, ymax), max(ymin, ymax)
        if xmax - xmin < min_size:
            if action in RESIZE_LEFT:
                xmin = xmax - min_size
            else:
                xmax = xmin + min_size
        if ymax - ymin < min_size:
            if action in RESIZE_UP:
                ymin = ymax - min_size
            else:
                ymax = ymin + min_size

        annotation.setFrameOffsetFromReferencePointMm(QPointF(xmin * px_to_mm, ymin * px_to_mm))
        annotation.setFrameSizeMm(QSizeF((xmax - xmin) * px_to_mm, (ymax - ymin) * px_to_mm))
        annotation.setRelativePosition(QPointF(rel_x, rel_y))
        item.update()
        QgsProject.instance().setDirty(True)

    def canvasDoubleClickEvent(self, e):
        item = self.item_at_pos(QPointF(e.pos()))
        if item is None:
            return
        editor = self.create_item_editor(item)
        if editor is not None:
            if editor.exec():
                QgsProject.instance().setDirty(True)
            editor.deleteLater()

    # ------------------------------------------------------------- pinning
    def pin(self, edge: PinnedEdge):
        items = self.selected_items()
        if len(items) != 1:
            return
        annotation = items[0].annotation()
        if not isinstance(annotation, QgsTextAnnotation):
            return
        canvas = self.canvas()
        # Save original map position before pinning
        self.original_map_positions.setdefault(_key(annotation), annotation.mapPosition())

        size = items[0].boundingRect().size()
        w, h = canvas.width(), canvas.height()
        x, y = {
            PinnedEdge.TOP: ((w - size.width()) // 2, 0),
            PinnedEdge.BOTTOM: ((w - size.width()) // 2, h - size.height()),
            PinnedEdge.LEFT: (0, (h - size.height()) // 2),
            PinnedEdge.RIGHT: (w - size.width(), (h - size.height()) // 2),
        }[edge]
        annotation.setRelativePosition(QPointF(int(x) / w, int(y) / h))
        annotation.setHasFixedMapPosition(False)
        self.pinned_edges[_key(annotation)] = edge

    def unpin(self):
        items = self.selected_items()
        if len(items) != 1 or items[0].annotation() is None:
            return
        annotation = items[0].annotation()
        canvas = self.canvas()
        key = _key(annotation)
        if key in self.original_map_positions:
            annotation.setMapPosition(self.original_map_positions.pop(key))
            annotation.setMapPositionCrs(canvas.mapSettings().destinationCrs())
        elif not annotation.hasFixedMapPosition():
            # Fallback: Convert relative position back to fixed map position
            rel = annotation.relativePosition()
            canvas_pos = QPointF(rel.x() * canvas.width(), rel.y() * canvas.height()).toPoint()
            annotation.setMapPosition(self.toMapCoordinates(canvas_pos))
            annotation.setMapPositionCrs(canvas.mapSettings().destinationCrs())
        annotation.setHasFixedMapPosition(True)
        self.pinned_edges.pop(key, None)

    # -------------------------------------------------------- show/remove
    def toggle_item_visibilities(self):
        self.item_visibilities = not self.item_visibilities
        for ann in _annotations():
            ann.setVisible(self.item_visibilities)

    def remove_selected_item(self):
        items = self.selected_items()
        if not items:
            return
        result = QMessageBox.question(
            self.canvas(), "Xóa nhãn", "Bạn có chắc chắn muốn xóa nhãn này?", Btn.Yes | Btn.No
        )
        if result == Btn.Yes:
            for item in items:
                QgsProject.instance().annotationManager().removeAnnotation(item.annotation())
            self.canvas().setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def remove_all_items(self):
        if not _annotations():
            return
        result = QMessageBox.question(
            self.canvas(), "Xóa nhãn", "Bạn có chắc chắn muốn xóa tất cả các nhãn?", Btn.Yes | Btn.No
        )
        if result == Btn.Yes:
            QgsProject.instance().annotationManager().clear()

    def toggle_text_item_visibilities(self):
        for item in self.canvas().annotationItems():
            ann = item.annotation()
            if isinstance(ann, QgsTextAnnotation):
                ann.setVisible(not ann.isVisible())

    # ------------------------------------------------------------ queries
    def item_at_pos(self, pos: QPointF) -> QgsMapCanvasAnnotationItem | None:
        tolerance = 5
        search = QRectF(pos.x() - tolerance, pos.y() - tolerance, tolerance * 2, tolerance * 2)
        candidates = [
            i
            for i in self.canvas().scene().items(search)
            if isinstance(i, QgsMapCanvasAnnotationItem) and i.isVisible()
        ]
        # Topmost first
        candidates.sort(key=lambda i: i.zValue(), reverse=True)

        # Reference point hits have highest priority
        for item in candidates:
            if self.is_near_reference_point(item, pos, 10):
                return item
        for item in candidates:
            r = item.boundingRect().translated(item.pos())
            if r.adjusted(-tolerance, -tolerance, tolerance, tolerance).contains(pos):
                return item
        return None

    def selected_items(self) -> list[QgsMapCanvasAnnotationItem]:
        scene = self.canvas().scene() if self.canvas() else None
        if scene is None:
            return []
        return [i for i in scene.selectedItems() if isinstance(i, QgsMapCanvasAnnotationItem)]

    def transform_canvas_to_annotation(self, p: QgsPointXY, annotation) -> QgsPointXY:
        dest = self.canvas().mapSettings().destinationCrs()
        if annotation.mapPositionCrs() != dest:
            transform = QgsCoordinateTransform(dest, annotation.mapPositionCrs(), QgsProject.instance())
            try:
                p = transform.transform(p)
            except QgsCsException:
                pass
        return p

    def pixel_to_mm(self) -> float:
        return 25.4 / self.canvas().mapSettings().outputDpi()

    def mm_to_pixel(self) -> float:
        return self.canvas().mapSettings().outputDpi() / 25.4

    def update_annotation_position(self, item, delta: QPointF):
        annotation = item.annotation()
        if annotation is None:
            return
        px_to_mm = self.pixel_to_mm()
        if annotation.hasFixedMapPosition():
            offset = annotation.frameOffsetFromReferencePointMm()
            annotation.setFrameOffsetFromReferencePointMm(offset + QPointF(delta.x() * px_to_mm, delta.y() * px_to_mm))
        else:
            canvas = self.canvas()
            new_pos = item.pos() + delta
            map_pos = self.transform_canvas_to_annotation(self.toMapCoordinates(new_pos.toPoint()), annotation)
            annotation.setMapPosition(map_pos)
            annotation.setRelativePosition(QPointF(new_pos.x() / canvas.width(), new_pos.y() / canvas.height()))
        item.update()
        QgsProject.instance().setDirty(True)

    def reference_point_position(self, item) -> QPointF:
        annotation = item.annotation()
        if annotation.hasFixedMapPosition():
            return QPointF(self.toCanvasCoordinates(annotation.mapPosition()))
        rel = annotation.relativePosition()
        return QPointF(rel.x() * self.canvas().width(), rel.y() * self.canvas().height())

    def is_near_reference_point(self, item, pos: QPointF, tolerance: int = 8) -> bool:
        if item is None or item.annotation() is None:
            return False
        d = pos - self.reference_point_position(item)
        return math.hypot(d.x(), d.y()) <= tolerance

    def get_smart_move_action(self, item, pos: QPointF):
        if item is None or item.annotation() is None:
            return A.NoAction

        # 1. Reference point
        if self.is_near_reference_point(item, pos, 10):
            return A.MoveMapPosition

        # 2. QGIS hit test in scene coordinates
        scene_pos = self.canvas().mapToScene(pos.toPoint())
        action = item.moveActionForPosition(scene_pos)

        # 3. Expand resize area around the frame border
        if action in (A.NoAction, A.MoveFramePosition):
            tol = 10.0
            r = item.sceneBoundingRect()
            inside = (
                r.left() - tol <= scene_pos.x() <= r.right() + tol
                and r.top() - tol <= scene_pos.y() <= r.bottom() + tol
            )
            if inside:
                near_left = abs(scene_pos.x() - r.left()) <= tol
                near_right = abs(scene_pos.x() - r.right()) <= tol
                near_top = abs(scene_pos.y() - r.top()) <= tol
                near_bottom = abs(scene_pos.y() - r.bottom()) <= tol
                if near_left and near_top:
                    action = A.ResizeFrameLeftUp
                elif near_left and near_bottom:
                    action = A.ResizeFrameLeftDown
                elif near_right and near_top:
                    action = A.ResizeFrameRightUp
                elif near_right and near_bottom:
                    action = A.ResizeFrameRightDown
                elif near_left:
                    action = A.ResizeFrameLeft
                elif near_right:
                    action = A.ResizeFrameRight
                elif near_top:
                    action = A.ResizeFrameUp
                elif near_bottom:
                    action = A.ResizeFrameDown

        # 4. Pinned annotation: moving the frame moves the pinned position
        if action == A.MoveFramePosition and not item.annotation().hasFixedMapPosition():
            action = A.MoveMapPosition
        return action


class MapToolTextAnnotation(MapToolAnnotation):
    def create_item(self):
        return QgsTextAnnotation()


class TagAnnotation(QgsTextAnnotation):
    """Numbered tag used for counting objects on the map."""

    def __init__(self, text: str, align: int, size: int, red: int, green: int, blue: int):
        super().__init__()
        doc = QTextDocument()
        options = doc.defaultTextOption()
        options.setAlignment(
            {1: Qt.AlignmentFlag.AlignLeft, 2: Qt.AlignmentFlag.AlignRight}.get(align, Qt.AlignmentFlag.AlignCenter)
        )
        doc.setDefaultTextOption(options)

        font = doc.defaultFont()
        font.setBold(True)
        font.setPointSize(size)
        doc.setDefaultFont(font)

        doc.setDefaultStyleSheet(f"body {{color: rgb({red}, {green}, {blue});}}")
        doc.setHtml(f"<body>{text}</body>")
        self.setDocument(doc)


def tag_settings() -> dict[str, int]:
    s = settings()
    defaults = {
        "Red": 255, "Green": 0, "Blue": 0, "Size": 10, "Align": 0,
        "Width": 30, "Height": 25, "Dx": -15, "Dy": -35,
    }
    return {k: int(s.value(f"TagCounting/{k}", v)) for k, v in defaults.items()}


class MapToolTagAnnotation(MapToolAnnotation):
    counter = 1

    @classmethod
    def reset_counter(cls):
        cls.counter = 1

    @classmethod
    def set_counter(cls, value: int):
        cls.counter = value

    @classmethod
    def count(cls) -> int:
        return cls.counter

    def create_item(self):
        t = tag_settings()
        self.default_size = QSizeF(t["Width"], t["Height"])
        self.default_offset = QPointF(t["Dx"], t["Dy"])
        tag = TagAnnotation(str(MapToolTagAnnotation.counter), t["Align"], t["Size"], t["Red"], t["Green"], t["Blue"])
        MapToolTagAnnotation.counter += 1
        return tag
