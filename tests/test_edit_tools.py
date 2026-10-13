"""Select / vertex / move / attributes / delete in the "Tạo đối tượng" panel, driven by real mouse events."""

import pytest
from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsRectangle, QgsVectorLayer
from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtTest import QTest

L, R = Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton
NONE, CTRL = Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier


def px(canvas, x, y) -> QPoint:
    p = canvas.getCoordinateTransform().transform(QgsPointXY(x, y))
    return QPoint(round(p.x()), round(p.y()))


def drag(widget, a: QPoint, b: QPoint, modifier=NONE):
    QTest.mousePress(widget, L, modifier, a)
    for i in range(1, 6):
        QTest.mouseMove(widget, a + (b - a) * i / 5)
    QTest.mouseRelease(widget, L, modifier, b)


def real_double_click(widget, pos):
    from tests.test_map_tools import _real_double_click

    _real_double_click(widget, pos)


@pytest.fixture
def editing(window):
    """An edited layer per geometry type, canvas showing (0,0)-(100,100)."""

    def make(wkb, geometries, fields=""):
        layer = QgsVectorLayer(f"{wkb}?crs=EPSG:3857{fields}", "test", "memory")
        feats = []
        for g in geometries:
            f = QgsFeature(layer.fields())
            f.setGeometry(QgsGeometry.fromWkt(g))
            feats.append(f)
        layer.dataProvider().addFeatures(feats)
        window.project.setCrs(layer.crs())
        window.main_controller.vector_model.add_vector_layer(layer)
        window.map_canvas.setDestinationCrs(layer.crs())
        window.map_canvas.setExtent(QgsRectangle(0, 0, 100, 100))
        window.toggle_editing_act.trigger()
        assert layer.isEditable()
        return layer

    return make


def test_edit_actions_enabled_only_while_editing(window, editing):
    assert not any(a.isEnabled() for a in window.edit_actions.values())
    layer = editing("Point", ["Point (50 50)"])
    assert all(a.isEnabled() for a in window.edit_actions.values())
    window.edit_actions["select"].trigger()
    assert window.map_canvas.mapTool() is window.tool_select_features
    window.toggle_editing_act.trigger()  # stop editing
    assert not any(a.isEnabled() for a in window.edit_actions.values())
    assert window.map_canvas.mapTool() is window.tool_identify_feature
    assert not layer.isEditable()


def test_select_click_ctrl_rect_and_delete_key(window, editing):
    layer = editing("Point", ["Point (20 20)", "Point (50 50)", "Point (80 80)"])
    ids = sorted(f.id() for f in layer.getFeatures())
    canvas, vp = window.map_canvas, window.map_canvas.viewport()
    window.edit_actions["select"].trigger()

    QTest.mouseClick(vp, L, NONE, px(canvas, 20, 20))
    assert layer.selectedFeatureIds() == [ids[0]]
    QTest.mouseClick(vp, L, CTRL, px(canvas, 50, 50))
    assert sorted(layer.selectedFeatureIds()) == ids[:2]
    QTest.mouseClick(vp, L, CTRL, px(canvas, 20, 20))  # ctrl-click again removes
    assert layer.selectedFeatureIds() == [ids[1]]
    QTest.mouseClick(vp, L, NONE, px(canvas, 5, 95))  # empty spot clears
    assert layer.selectedFeatureIds() == []
    drag(vp, px(canvas, 40, 95), px(canvas, 95, 40))  # rectangle over the last two
    assert sorted(layer.selectedFeatureIds()) == ids[1:]

    QTest.keyClick(vp, Qt.Key.Key_Delete)
    assert sorted(f.id() for f in layer.getFeatures()) == ids[:1]


def test_vertex_move_insert_delete(window, editing):
    layer = editing("LineString", ["LineString (10 10, 50 10, 90 10)"])
    canvas, vp = window.map_canvas, window.map_canvas.viewport()
    window.edit_actions["vertex"].trigger()

    drag(vp, px(canvas, 50, 10), px(canvas, 50, 60))  # drag the middle vertex up
    pts = [(round(v.x()), round(v.y())) for v in next(layer.getFeatures()).geometry().vertices()]
    assert pts[0] == (10, 10) and pts[2] == (90, 10) and abs(pts[1][0] - 50) <= 1 and abs(pts[1][1] - 60) <= 1

    real_double_click(vp, px(canvas, 70, 35))  # on the segment (50,60)-(90,10): insert a vertex
    assert len(list(next(layer.getFeatures()).geometry().vertices())) == 4

    QTest.mouseClick(vp, R, NONE, px(canvas, 10, 10))  # right-click the first vertex: delete it
    pts = [(round(v.x()), round(v.y())) for v in next(layer.getFeatures()).geometry().vertices()]
    assert len(pts) == 3 and (10, 10) not in pts


def test_move_feature_and_undo(window, editing):
    layer = editing("Polygon", ["Polygon ((10 10, 30 10, 30 30, 10 30, 10 10))"])
    canvas, vp = window.map_canvas, window.map_canvas.viewport()
    window.edit_actions["move"].trigger()
    drag(vp, px(canvas, 20, 20), px(canvas, 60, 50))
    box = next(layer.getFeatures()).geometry().boundingBox()
    tol = 2 * canvas.mapUnitsPerPixel()  # mouse positions are whole pixels
    assert abs(box.xMinimum() - 50) <= tol and abs(box.yMinimum() - 40) <= tol

    layer.undoStack().undo()  # edits are undoable edit commands
    box = next(layer.getFeatures()).geometry().boundingBox()
    assert abs(box.xMinimum() - 10) < 1e-6


def test_edit_attributes(window, editing, monkeypatch):
    from vgeoint.app.maptools.add_feature import EditAttributeDialog

    layer = editing("Point", ["Point (50 50)"], "&field=name:string(20)&field=code:integer")
    fid = next(layer.getFeatures()).id()
    layer.changeAttributeValues(fid, {0: "cũ", 1: 1})

    window.edit_actions["attributes"].trigger()  # nothing selected -> warning only
    layer.selectByIds([fid])

    seen = []

    def fake_exec(dialog, name="Giếng 'A'", code="42"):
        seen.append([e.text() for e in dialog.line_edits])  # pre-filled with current values
        dialog.line_edits[0].setText(name)
        dialog.line_edits[1].setText(code)
        dialog._accept()
        return 1

    monkeypatch.setattr(EditAttributeDialog, "exec", fake_exec)
    window.edit_actions["attributes"].trigger()
    f = layer.getFeature(fid)
    assert seen == [["cũ", "1"]] and f["name"] == "Giếng 'A'" and f["code"] == 42

    monkeypatch.setattr(EditAttributeDialog, "exec", lambda d: fake_exec(d, code="không phải số"))
    window.edit_actions["attributes"].trigger()
    assert layer.getFeature(fid)["code"] == 42  # invalid value rejected


def test_delete_requires_selection(window, editing):
    layer = editing("Point", ["Point (50 50)"])
    window.edit_actions["delete"].trigger()
    assert layer.featureCount() == 1
    assert "Chưa chọn" in window.message_bar.currentItem().text()


def test_switch_between_draw_and_select(window, editing):
    editing("Point", ["Point (50 50)"])
    window.edit_actions["select"].trigger()
    window.edit_actions["draw"].trigger()
    assert window.map_canvas.mapTool() is window.tool_add_point_feature
    assert window.edit_actions["draw"].isChecked() and not window.edit_actions["select"].isChecked()
