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


@pytest.mark.parametrize("fmt", ["geotiff", "png", "jpg", "geopdf", "pdf"])
def test_map_export_formats(window, tmp_path, qtbot, fmt):
    """GeoTIFF / PNG / JPG / GeoPDF carry the map extent and CRS (the C++ dialog only wrote a plain PDF)."""
    from osgeo import gdal
    from qgis.core import QgsRectangle

    from tests.conftest import make_raster
    from vgeoint.app.dialogs.map_save import FORMATS, MapSaveDialog

    window.main_controller.add_raster(make_raster(tmp_path / "anh.tif"))
    window.layer_tree_map_canvas_bridge.setCanvasLayers()
    canvas = window.map_canvas
    canvas.setExtent(QgsRectangle(500100, 2299600, 500500, 2299900))
    dlg = MapSaveDialog(window, canvas, [], [])
    assert [dlg.format_combo.itemData(i) for i in range(dlg.format_combo.count())] == list(FORMATS)
    dlg.format_combo.setCurrentIndex(dlg.format_combo.findData(fmt))
    out = tmp_path / ("ban_do" + FORMATS[fmt][2])
    task = dlg.export_map(str(out))
    assert task is not None
    qtbot.waitUntil(lambda: (item := window.message_bar.currentItem()) is not None
                    and "thành công" in item.text(), timeout=30000)
    assert out.exists() and out.stat().st_size > 0
    assert not list(tmp_path.glob("vgeoint_map_*.png"))  # no temporary file left
    if fmt == "pdf":
        return
    if fmt in ("png", "jpg"):
        assert (tmp_path / ("ban_do" + {"png": ".pgw", "jpg": ".jgw"}[fmt])).exists()
        assert (tmp_path / (out.name + ".aux.xml")).exists()
    if fmt == "geopdf" and gdal.GetDriverByName("PDF").GetMetadataItem("DMD_EXTENSIONS") is None:
        return
    ds = gdal.Open(str(out))
    if ds is None and fmt == "geopdf":
        pytest.skip("GDAL here cannot read PDF back (no PDF rendering library)")
    gt = ds.GetGeoTransform()
    x0, y0 = gt[0], gt[3]
    x1, y1 = x0 + gt[1] * ds.RasterXSize, y0 + gt[5] * ds.RasterYSize
    extent = canvas.mapSettings().visibleExtent()
    assert abs(x0 - extent.xMinimum()) < 50 and abs(y0 - extent.yMaximum()) < 50
    assert x0 <= 500100 < 500500 <= x1 and y1 <= 2299600 < 2299900 <= y0
    assert "32648" in ds.GetProjection() or "UTM zone 48N" in ds.GetProjection()


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
    layer = window.add_geometry_layer(getattr(Qgis.GeometryType, geom))
    window.start_creating(layer)  # Create Features -> pick the layer -> drawing tool
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


def test_cursor_tool_selects_moves_edits_and_deletes_annotations(window, monkeypatch):
    """The arrow tool picks annotations (select, drag, double-click edit, Delete) without creating any."""
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QEvent, QPoint, Qt
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QDialog

    from vgeoint.app.dialogs.text_annotation import TextAnnotationDialog

    canvas, vp = window.map_canvas, window.map_canvas.viewport()
    # create one text annotation with its frame around (300, 155) (ref point 300,200; offset -40,-60; 80x30)
    window.tool_add_text_annotation.canvasPressEvent(_mouse(canvas, QEvent.Type.MouseButtonPress, 300, 200, Qt.MouseButton.LeftButton))
    manager = QgsProject.instance().annotationManager()
    anno = manager.annotations()[0]
    canvas.scene().clearSelection()

    window.menu_bar_.cursor_click_act.trigger()
    assert canvas.mapTool() is window.tool_identify_feature
    L = Qt.MouseButton.LeftButton

    QTest.mouseClick(vp, L, Qt.KeyboardModifier.NoModifier, QPoint(5, 5))  # empty: no new annotation
    assert len(manager.annotations()) == 1

    QTest.mouseClick(vp, L, Qt.KeyboardModifier.NoModifier, QPoint(300, 155))  # click the frame: selected
    item = canvas.annotationItems()[0]
    assert item.isSelected()

    offset = anno.frameOffsetFromReferencePointMm()
    QTest.mousePress(vp, L, Qt.KeyboardModifier.NoModifier, QPoint(300, 155))
    for i in range(1, 6):
        QTest.mouseMove(vp, QPoint(300 + 8 * i, 155 + 6 * i))
    QTest.mouseRelease(vp, L, Qt.KeyboardModifier.NoModifier, QPoint(340, 185))
    assert anno.frameOffsetFromReferencePointMm() != offset  # frame dragged

    opened = []
    monkeypatch.setattr(QDialog, "exec", lambda self: opened.append(type(self)) or 0)
    window.tool_identify_feature.canvasDoubleClickEvent(
        _mouse(canvas, QEvent.Type.MouseButtonDblClick, 340, 185, Qt.MouseButton.LeftButton)
    )
    assert opened == [TextAnnotationDialog]

    QTest.mouseClick(vp, L, Qt.KeyboardModifier.NoModifier, QPoint(5, 5))  # click away: deselects
    assert not item.isSelected()
    QTest.mouseClick(vp, L, Qt.KeyboardModifier.NoModifier, QPoint(340, 185))
    QTest.keyClick(vp, Qt.Key.Key_Delete)
    assert manager.annotations() == []


def test_cursor_tool_still_identifies_vector_features(window, qtbot):
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsRectangle, QgsVectorLayer
    from qgis.PyQt.QtCore import QPoint, Qt
    from qgis.PyQt.QtTest import QTest

    layer = QgsVectorLayer("Point?crs=EPSG:3857", "pts", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(50, 50)))
    layer.dataProvider().addFeature(f)
    window.project.setCrs(layer.crs())
    window.main_controller.vector_model.add_vector_layer(layer)
    canvas = window.map_canvas
    canvas.setDestinationCrs(layer.crs())
    canvas.setExtent(QgsRectangle(0, 0, 100, 100))
    window.layer_tree_map_canvas_bridge.setCanvasLayers()
    window.menu_bar_.cursor_click_act.trigger()
    p = canvas.getCoordinateTransform().transform(QgsPointXY(50, 50))
    with qtbot.waitSignal(window.tool_identify_feature.featureIdentified, timeout=3000):
        QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(round(p.x()), round(p.y())))
    assert window.rubber_band is not None
