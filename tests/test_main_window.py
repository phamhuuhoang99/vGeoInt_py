"""Phase 1: the main window has the same menus, toolbars and docks as the C++ app."""

import pytest
from qgis.core import QgsVectorLayer
from qgis.PyQt.QtWidgets import QToolBar

from tests.conftest import action_texts


def test_menus(window):
    titles = [a.text() for a in window.mainMenuBar.actions()]
    assert titles == ["File", "Xem", "Layer", "Vector", "Raster", "Công cụ", "Trợ giúp"]


def test_file_menu(window):
    assert action_texts(window.menu_bar_.file_menu) == [
        "Dự án mới",
        "Mở dự án...",
        "Lưu dự án",
        "Lưu dự án với tên...",
        "-",
        "Mở file vector...",
        "Mở file raster...",
        "-",
        "vGeoCatalog",
        "vGeoEngine",
        "-",
        "Cài đặt chung",
        "Xuất ra với tên...",
        "Xuất Pdf",
        "-",
        "Thoát",
    ]


def test_toolbars(window):
    names = [tb.objectName() for tb in window.findChildren(QToolBar) if tb.objectName()]
    for expected in (
        "mainToolBar",
        "ViewToolBar",
        "DataToolBar",
        "VectorToolBar",
        "RasterToolBar",
        "VectorBPluginToolBar",
        "RasterBPluginToolBar",
        "AnnotationBPluginToolBar",
        "MeasureBPluginToolBar",
        "HelpToolBar",
    ):
        assert expected in names


def test_raster_plugin_toolbar(window):
    tb = window.findChild(QToolBar, "RasterBPluginToolBar")
    assert len(tb.actions()) == 9


def test_all_actions_have_icons(window):
    # Every icon the C++ app used must resolve from the compiled .rcc bundles.
    missing = [
        a.text()
        for menu in (window.menu_bar_.file_menu, window.menu_bar_.raster_menu, window.menu_bar_.tool_menu)
        for a in menu.actions()
        if not a.isSeparator() and a.icon().isNull()
    ]
    assert not missing


def test_add_vector_and_stretch_warning(window, tmp_path):
    layer = QgsVectorLayer("Point?crs=EPSG:4326", "pts", "memory")
    assert window.main_controller.vector_model.add_vector_layer(layer)
    assert window.active_layer() is layer
    # Histogram stretch on a vector layer only pushes a warning, no exception.
    window.main_controller.local_histogram_stretch()


def test_unported_dialog_shows_message(window):
    # A dialog module that does not exist (yet) shows a notice instead of failing.
    window.main_controller._std_dialog("does_not_exist", "MissingDialog")
    assert window.message_bar.currentItem() is not None


def test_coordinate_widget_shows_dms(window):
    """xyCoordinates fires on every mouse move; the DMS formatting used Qt5-era enum names."""
    from qgis.core import QgsPointXY, QgsProject, QgsVectorLayer

    QgsProject.instance().addMapLayer(QgsVectorLayer("Point?crs=EPSG:4326", "pts", "memory"))
    window.layer_tree_map_canvas_bridge.setCanvasLayers()
    window.map_canvas.xyCoordinates.emit(QgsPointXY(105.85, 21.03))
    assert "105" in window.coordinate_widget.coord_ledr.text()
    assert "21°" in window.coordinate_widget.geo_ledr.text()


def test_layer_context_menu(window):
    from qgis.core import QgsVectorLayer

    vl = QgsVectorLayer("Point?crs=EPSG:4326", "pts", "memory")
    window.main_controller.vector_model.add_vector_layer(vl)
    menu = window.layer_panel_menu.createContextMenu()
    texts = [a.text() for a in menu.actions()]
    assert "Đi tới layer này" in texts and "Hiển thị nhãn..." in texts and "Xem siêu dữ liệu" in texts


def test_no_missing_qt_qgis_attributes():
    """tools/check_attributes.py: no Qt5/QGIS3-era enum or class attribute names left in src/."""
    import subprocess
    import sys

    from vgeoint.common.paths import ROOT

    out = subprocess.run([sys.executable, str(ROOT / "tools" / "check_attributes.py")], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout


def _edit_layer(window, name="roads"):
    from qgis.core import QgsVectorLayer

    layer = QgsVectorLayer("LineString?crs=EPSG:4326", name, "memory")
    window.main_controller.vector_model.add_vector_layer(layer)
    return layer


def test_toggle_editing_on_off(window):
    act = window.toggle_editing_act
    layer = _edit_layer(window)
    assert act.isCheckable() and not act.isChecked()

    act.trigger()  # on
    assert layer.isEditable() and act.isChecked()
    assert "Đang chỉnh sửa: roads" in act.toolTip()

    act.trigger()  # off, nothing modified -> no question
    assert not layer.isEditable() and not act.isChecked()


@pytest.mark.parametrize("answer, saved, still_editing", [("Yes", 1, False), ("No", 0, False), ("Cancel", 0, True)])
def test_toggle_off_with_changes(window, monkeypatch, answer, saved, still_editing):
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY
    from qgis.PyQt.QtWidgets import QMessageBox

    asked = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or getattr(QMessageBox.StandardButton, answer)
    )
    act = window.toggle_editing_act
    layer = _edit_layer(window)
    act.trigger()
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(0, 0), QgsPointXY(1, 1)]))
    layer.addFeature(f)

    act.trigger()
    assert asked and "roads" in asked[0]
    assert layer.dataProvider().featureCount() == saved
    assert layer.isEditable() is still_editing
    assert act.isChecked() is still_editing


def test_toggle_follows_save_button_and_auto_layer(window, monkeypatch):
    from qgis.core import Qgis
    from qgis.PyQt.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    act = window.toggle_editing_act
    point_act = [a for a in window.menu_bar_.vector_menu.actions() if a.text() == "Thêm đối tượng điểm"][0]

    window.add_feature(point_act, Qgis.GeometryType.Point)  # auto-creates the "Điểm" memory layer
    assert act.isChecked() and "Điểm" in act.toolTip()

    save_act = [a for a in window.menu_bar_.vector_menu.actions() if a.text() == "Lưu thay đổi"][0]
    save_act.trigger()  # "No" -> roll back, leaves edit mode
    assert not act.isChecked()


def test_toggle_unchecks_when_edited_layer_removed(window, qtbot):
    from qgis.core import QgsProject

    act = window.toggle_editing_act
    layer = _edit_layer(window)
    act.trigger()
    assert act.isChecked()
    QgsProject.instance().removeMapLayer(layer.id())
    qtbot.waitUntil(lambda: not act.isChecked(), timeout=2000)
