"""Phase 2: measure, add feature, annotations, PDF export."""

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
