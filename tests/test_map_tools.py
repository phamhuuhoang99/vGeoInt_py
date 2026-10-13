"""Phase 2: measure, add feature, annotations, PDF export."""

import pytest
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsTextAnnotation,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType


def _utm_window(window):
    crs = QgsCoordinateReferenceSystem.fromEpsgId(32648)  # UTM 48N
    QgsProject.instance().setCrs(crs)
    window.map_canvas.setDestinationCrs(crs)
    window.map_canvas.setExtent(QgsRectangle(500000, 2300000, 510000, 2310000))


def test_measure_distance(window):
    _utm_window(window)
    tool = window.tool_measure_dist
    window.map_canvas.setMapTool(tool)
    tool.restart()
    tool.done = False
    tool.add_point(QgsPointXY(500000, 2300000))
    tool.add_point(QgsPointXY(503000, 2304000))  # 5 km
    assert len(tool.points) == 2
    assert tool.dialog.mTable.topLevelItemCount() == 2
    assert tool.dialog.editTotal.text()  # e.g. "5000.000 m" (ellipsoidal)
    assert tool.dialog.windowTitle() == "Đo độ dài"


def test_measure_area(window):
    _utm_window(window)
    tool = window.tool_measure_area
    window.map_canvas.setMapTool(tool)
    tool.restart()
    tool.done = False
    for x, y in ((500000, 2300000), (501000, 2300000), (501000, 2301000)):
        tool.add_point(QgsPointXY(x, y))
    assert tool.dialog.editTotal.text()
    assert tool.dialog.windowTitle() == "Đo diện tích"


def test_add_feature_with_attributes(window, monkeypatch):
    from vgeoint.app.maptools.add_feature import EditAttributeDialog

    layer = QgsVectorLayer("Point?crs=EPSG:4326", "pts", "memory")
    layer.dataProvider().addAttributes([QgsField("name", QMetaType.Type.QString)])
    layer.updateFields()
    QgsProject.instance().addMapLayer(layer)
    layer.startEditing()
    window.map_canvas.setCurrentLayer(layer)

    def fake_exec(dialog):
        dialog.line_edits[0].setText("Điểm A")
        dialog._accept()
        return 1

    monkeypatch.setattr(EditAttributeDialog, "exec", fake_exec)
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(105.8, 21.0)))
    window.tool_add_point_feature.digitized(f)

    assert layer.featureCount() == 1
    assert next(layer.getFeatures())["name"] == "Điểm A"


def test_tag_annotation_counter_and_manager(window):
    from vgeoint.app.dialogs.annotation_manager import AnnotationManagerDialog
    from vgeoint.app.maptools.annotation import MapToolTagAnnotation, TagAnnotation

    MapToolTagAnnotation.reset_counter()
    tool = window.tool_tag_counting
    manager = QgsProject.instance().annotationManager()
    for _ in range(2):
        anno = tool.create_item()
        anno.setMapPosition(QgsPointXY(1, 1))
        manager.addAnnotation(anno)
    text = QgsTextAnnotation()
    manager.addAnnotation(text)

    assert MapToolTagAnnotation.count() == 3
    assert all(isinstance(a, TagAnnotation) for a in manager.annotations()[:2])
    # Each annotation gets a canvas item (MainWindow.annotation_created)
    assert len(window.map_canvas.annotationItems()) == 3

    dlg = AnnotationManagerDialog(window, window.map_canvas, window.layer_tree_view)
    assert [dlg.tagAnnoLswg.item(i).text() for i in range(dlg.tagAnnoLswg.count())] == ["1", "2"]
    assert dlg.textAnnoLswg.count() == 1


def test_text_annotation_dialog_apply(window):
    from vgeoint.app.dialogs.text_annotation import TextAnnotationDialog

    anno = QgsTextAnnotation()
    QgsProject.instance().annotationManager().addAnnotation(anno)
    item = window.map_canvas.annotationItems()[0]
    dlg = TextAnnotationDialog(item)
    dlg.mTextEdit.setPlainText("Ghi chú thử")
    dlg.apply_text_to_item()
    assert anno.document().toPlainText() == "Ghi chú thử"
    assert anno.frameSizeMm().width() > 0


def test_tag_setting_dialog_saves(window):
    from vgeoint.app.dialogs.tag_annotation_setting import TagAnnotationSettingDialog
    from vgeoint.app.maptools.annotation import MapToolTagAnnotation, tag_settings

    dlg = TagAnnotationSettingDialog(window)
    dlg.fromSbx.setValue(7)
    dlg.sizeSbx.setValue(14)
    dlg._ok()
    assert MapToolTagAnnotation.count() == 7
    assert tag_settings()["Size"] == 14


def test_map_save_dialog_settings(window):
    from qgis.core import QgsMapSettings

    from vgeoint.app.dialogs.map_save import MapSaveDialog

    layer = QgsVectorLayer("Point?crs=EPSG:4326", "pts", "memory")
    QgsProject.instance().addMapLayer(layer)
    dlg = MapSaveDialog(window, window.map_canvas, [], [])
    ms = QgsMapSettings()
    dlg.apply_map_settings(ms)
    assert ms.outputDpi() == dlg.mResolutionSpinBox.value()
    assert dlg.mDrawDecorations.text() == "Xuất các đối tượng đồ họa: Không có"


def _mouse(canvas, kind, x, y, button, buttons=None):
    from qgis.gui import QgsMapMouseEvent
    from qgis.PyQt.QtCore import QPoint, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent

    me = QMouseEvent(
        kind, QPointF(x, y), QPointF(canvas.mapToGlobal(QPoint(x, y))), button,
        button if buttons is None else buttons, Qt.KeyboardModifier.NoModifier,
    )
    return QgsMapMouseEvent(canvas, me)




@pytest.mark.parametrize("tool_attr", ["tool_add_text_annotation", "tool_tag_counting"])
def test_annotation_tool_full_mouse_sequence(window, monkeypatch, tool_attr):
    """Press, release, hover, drag, double-click: release used to crash (no QgsMapTool.cursor() in PyQGIS)
    and the double-click must open the text editor dialog."""
    from qgis.PyQt.QtCore import QEvent, Qt
    from qgis.PyQt.QtWidgets import QDialog

    from vgeoint.app.dialogs.text_annotation import TextAnnotationDialog

    opened = []
    monkeypatch.setattr(QDialog, "exec", lambda self: opened.append(type(self)) or 0)
    canvas = window.map_canvas
    tool = getattr(window, tool_attr)
    canvas.setMapTool(tool)
    T, B = QEvent.Type, Qt.MouseButton

    tool.canvasPressEvent(_mouse(canvas, T.MouseButtonPress, 300, 200, B.LeftButton))
    tool.canvasReleaseEvent(_mouse(canvas, T.MouseButtonRelease, 300, 200, B.LeftButton))
    tool.canvasMoveEvent(_mouse(canvas, T.MouseMove, 305, 205, B.NoButton, B.NoButton))
    tool.canvasMoveEvent(_mouse(canvas, T.MouseMove, 320, 220, B.NoButton, B.LeftButton))
    tool.canvasReleaseEvent(_mouse(canvas, T.MouseButtonRelease, 320, 220, B.LeftButton))
    assert len(canvas.annotationItems()) == 1

    tool.canvasDoubleClickEvent(_mouse(canvas, T.MouseButtonDblClick, 300, 200, B.LeftButton))
    assert opened == [TextAnnotationDialog]


def _real_double_click(widget, pos):
    """What a real double-click delivers: press, release, double-click, release.

    (QTest.mouseDClick in Qt 6 only sends the double-click event.)
    """
    from qgis.PyQt.QtCore import QEvent, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QApplication

    L, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    QTest.mousePress(widget, L, none, pos)
    QTest.mouseRelease(widget, L, none, pos)
    dbl = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(pos), QPointF(widget.mapToGlobal(pos)), L, L, none)
    QApplication.sendEvent(widget, dbl)
    QTest.mouseRelease(widget, L, none, pos)


@pytest.mark.parametrize("geom, pts, wkb", [
    ("Line", [(300, 300), (500, 250)], "LineString"),
    ("Polygon", [(300, 300), (500, 250), (600, 400)], "Polygon"),
])
def test_double_click_finishes_line_and_polygon(window, monkeypatch, geom, pts, wkb):
    """Double-click finishes the shape (right-click still works); the trailing release is swallowed."""
    from qgis.core import Qgis, QgsRectangle
    from qgis.PyQt.QtCore import QPoint, Qt
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    canvas = window.map_canvas
    canvas.setExtent(QgsRectangle(100, 10, 110, 20))
    act = [a for a in window.menu_bar_.vector_menu.actions() if a.text() == f"Thêm đối tượng {'đường' if geom == 'Line' else 'vùng'}"][0]
    act.trigger()  # answers "Yes" -> creates an editable memory layer
    layer = canvas.currentLayer()
    tool = canvas.mapTool()
    vp = canvas.viewport()
    L = Qt.MouseButton.LeftButton
    for x, y in pts:
        QTest.mouseClick(vp, L, Qt.KeyboardModifier.NoModifier, QPoint(x, y))
    _real_double_click(vp, QPoint(700, 350))

    feats = list(layer.getFeatures())
    assert len(feats) == 1
    geom_obj = feats[0].geometry()
    assert geom_obj.asWkt().startswith(wkb)
    vertices = list(geom_obj.vertices())
    expected = len(pts) + 1 + (1 if geom == "Polygon" else 0)  # polygon ring repeats its first vertex
    assert len(vertices) == expected
    assert not tool.isCapturing()  # the release after the double-click did not start a new shape

    # a normal right-click finish still works afterwards
    for x, y in pts:
        QTest.mouseClick(vp, L, Qt.KeyboardModifier.NoModifier, QPoint(x + 10, y + 10))
    QTest.mouseClick(vp, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, QPoint(x + 10, y + 10))
    assert layer.featureCount() == (2 if geom == "Line" or len(pts) >= 3 else 1)
    assert layer.geometryType() == (Qgis.GeometryType.Line if geom == "Line" else Qgis.GeometryType.Polygon)
