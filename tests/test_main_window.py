"""Phase 1: the main window has the same menus, toolbars and docks as the C++ app."""

from pathlib import Path

import pytest
from qgis.core import QgsVectorLayer
from qgis.PyQt.QtWidgets import QToolBar

from tests.conftest import action_texts


def test_menus(window):
    titles = [a.text() for a in window.mainMenuBar.actions()]
    assert titles == [
        "File", "Xem", "Layer", "Vector", "Raster", "Công cụ", "Phát hiện quỹ đạo", "Tải ảnh vệ tinh", "Trợ giúp",
    ]


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
    layer = window.add_geometry_layer(Qgis.GeometryType.Point)
    window.start_creating(layer)  # Create Features -> pick the new "Điểm" layer
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


def _layers(window):
    from qgis.core import QgsVectorLayer

    made = {}
    for name, geom in (("roads", "LineString"), ("wells", "Point"), ("lakes", "Polygon")):
        layer = QgsVectorLayer(f"{geom}?crs=EPSG:4326", name, "memory")
        window.main_controller.vector_model.add_vector_layer(layer)
        made[name] = layer
    return made


def _start_editing(window, layer):
    window.layer_tree_view.setCurrentLayer(layer)
    window.toggle_editing_act.trigger()
    assert layer.isEditable()


def test_create_features_needs_edit_session_then_picks_layer(window):
    """Pencil first; then picking a layer in the panel edits (switches to) that layer."""
    layers = _layers(window)
    panel = window.create_features_panel
    assert not window.create_features_act.isEnabled() and not window.toggle_editing_act.isChecked()
    window.create_features_act.trigger()  # disabled: nothing happens
    assert not panel.isVisibleTo(window)
    _start_editing(window, layers["lakes"])
    assert window.create_features_act.isEnabled()
    window.create_features_act.trigger()
    assert panel.isVisibleTo(window)
    names = [panel.layer_list.item(i).text() for i in range(panel.layer_list.count())]
    assert names == ["lakes (đang sửa)", "roads", "wells"]
    panel.filter_edit.setText("wel")
    assert [panel.layer_list.item(i).isHidden() for i in range(3)] == [True, True, False]
    panel.filter_edit.clear()

    panel.layer_list.itemClicked.emit(panel.item_for(layers["roads"]))
    assert layers["roads"].isEditable() and window.toggle_editing_act.isChecked()
    assert window.map_canvas.mapTool() is window.tool_add_line_feature
    assert panel.item_for(layers["roads"]).text() == "roads (đang sửa)"
    # Picking another layer switches the edit session; "Tạo đối tượng" stays open
    panel.layer_list.itemClicked.emit(panel.item_for(layers["wells"]))
    assert layers["wells"].isEditable() and not layers["roads"].isEditable()
    assert window.map_canvas.mapTool() is window.tool_add_point_feature
    assert panel.isVisibleTo(window) and window.create_features_act.isChecked()

    window.toggle_editing_act.trigger()  # the pencil stops editing -> creating ends too
    assert not layers["wells"].isEditable()
    assert window.map_canvas.mapTool() is window.tool_identify_feature
    assert not panel.isVisibleTo(window) and not window.create_features_act.isChecked()
    assert not any(a.isEnabled() for a in window.edit_actions.values())
    assert not window.edit_actions["draw"].isChecked() and not window.create_features_act.isEnabled()

    # Pencil again, reopen the panel and pick a layer
    _start_editing(window, layers["lakes"])
    window.create_features_act.trigger()
    panel.layer_list.itemClicked.emit(panel.item_for(layers["roads"]))
    assert layers["roads"].isEditable() and window.map_canvas.mapTool() is window.tool_add_line_feature


def test_save_and_stop_ends_creating(window):
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

    layers = _layers(window)
    panel = window.create_features_panel
    _start_editing(window, layers["wells"])
    window.create_features_act.trigger()
    panel.layer_list.itemClicked.emit(panel.item_for(layers["wells"]))
    f = QgsFeature(layers["wells"].fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(105, 21)))
    window.tool_add_point_feature.digitized(f)
    window.toggle_editing_act.trigger()  # fixture answers Yes: save and stop
    assert layers["wells"].featureCount() == 1 and not layers["wells"].isEditable()
    assert window.map_canvas.mapTool() is window.tool_identify_feature
    assert not panel.isVisibleTo(window)


@pytest.mark.parametrize("name, tool_attr", [
    ("wells", "tool_add_point_feature"), ("roads", "tool_add_line_feature"), ("lakes", "tool_add_polygon_feature"),
])
def test_choose_layer_starts_matching_tool(window, name, tool_attr):
    layers = _layers(window)
    window.create_features_panel.layer_chosen.emit(layers[name])
    assert layers[name].isEditable()
    assert window.map_canvas.mapTool() is getattr(window, tool_attr)
    assert window.map_canvas.currentLayer() is layers[name]
    assert window.toggle_editing_act.isChecked()


@pytest.mark.parametrize("answer, switched", [("Yes", True), ("No", True), ("Cancel", False)])
def test_choose_other_layer_switches_edit_session(window, monkeypatch, answer, switched):
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY
    from qgis.PyQt.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: getattr(QMessageBox.StandardButton, answer))
    layers = _layers(window)
    window.start_creating(layers["wells"])
    f = QgsFeature(layers["wells"].fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1, 1)))
    layers["wells"].addFeature(f)

    window.start_creating(layers["roads"])
    assert layers["roads"].isEditable() is switched
    assert layers["wells"].isEditable() is (not switched)
    assert layers["wells"].dataProvider().featureCount() == (1 if answer == "Yes" else 0)
    expected_tool = window.tool_add_line_feature if switched else window.tool_add_point_feature
    assert window.map_canvas.mapTool() is expected_tool


def test_create_features_list_vietnamese_order(window):
    from qgis.core import QgsVectorLayer

    for name in ("Hồ chứa", "Đường giao thông", "Giếng khoan", "Data", "bản đồ"):
        window.main_controller.vector_model.add_vector_layer(QgsVectorLayer("Point?crs=EPSG:4326", name, "memory"))
    panel = window.create_features_panel
    panel.refresh()
    names = [panel.layer_list.item(i).text() for i in range(panel.layer_list.count())]
    assert names == ["bản đồ", "Data", "Đường giao thông", "Giếng khoan", "Hồ chứa"]


@pytest.mark.parametrize("geom_type, name, wkb", [("Point", "Điểm", 1), ("Line", "Đường", 2), ("Polygon", "Vùng", 3)])
def test_add_layer_button_only_adds_layer(window, geom_type, name, wkb):
    """"Thêm đối tượng điểm/đường/vùng" only adds an empty layer: no question, no editing, no tool."""
    from qgis.core import Qgis, QgsWkbTypes

    tool_before = window.map_canvas.mapTool()
    window.add_feature_acts[getattr(Qgis.GeometryType, geom_type)].trigger()
    layer = window.layer_tree_view.currentLayer()
    assert layer.name() == name and layer.featureCount() == 0
    assert QgsWkbTypes.flatType(layer.wkbType()).value == wkb
    assert not layer.isEditable() and not window.toggle_editing_act.isChecked()
    assert window.map_canvas.mapTool() is tool_before
    # a second one gets a distinct name
    window.add_feature_acts[getattr(Qgis.GeometryType, geom_type)].trigger()
    assert window.layer_tree_view.currentLayer().name() == f"{name} 2"


def test_arcgis_workflow_add_layer_edit_create_draw(window):
    """Add layer -> Bật chỉnh sửa -> Tạo đối tượng -> pick layer -> draw."""
    from qgis.core import Qgis, QgsFeature, QgsGeometry, QgsPointXY

    window.add_feature_acts[Qgis.GeometryType.Point].trigger()
    layer = window.layer_tree_view.currentLayer()
    window.toggle_editing_act.trigger()
    assert layer.isEditable() and window.create_features_act.isEnabled()
    window.create_features_act.trigger()
    panel = window.create_features_panel
    panel.layer_list.itemClicked.emit(panel.item_for(layer))
    assert window.map_canvas.mapTool() is window.tool_add_point_feature
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(105, 21)))
    window.tool_add_point_feature.digitized(f)
    assert layer.featureCount() == 1



def test_vector_toolbar_without_identify_and_delete_buttons(window):
    """Selecting / deleting is done from the "Tạo đối tượng" panel; the C++ buttons were removed."""
    tb = window.findChild(QToolBar, "VectorToolBar")
    texts = [a.text() for a in tb.actions()] + [a.text() for a in window.menu_bar_.vector_menu.actions()]
    assert "Chọn đối tượng" not in texts and "Xóa đối tượng" not in texts


def test_panel_buttons_disabled_without_edit_session(window):
    _layers(window)
    window.create_features_panel.show()
    window.edit_actions["draw"].trigger()
    assert window.vector_layer_editing() is None
    assert not window.edit_actions["draw"].isEnabled() and not window.edit_actions["draw"].isChecked()


def test_create_features_icon(window):
    from qgis.PyQt.QtCore import QFile

    assert QFile.exists(":/myicon/CreateFeatures.png")
    assert not window.create_features_act.icon().isNull()


def test_start_editing_with_raster_selected_opens_session(window, tmp_path):
    """The pencil does not need a vector layer selected: the layer is picked in "Tạo đối tượng"."""
    from tests.conftest import make_raster

    window.main_controller.add_raster(make_raster(tmp_path / "anh.tif"))
    layers = _layers(window)
    window.layer_tree_view.setCurrentLayer(window.project.mapLayersByName("anh")[0])
    window.toggle_editing_act.trigger()
    panel = window.create_features_panel
    assert window.toggle_editing_act.isChecked() and window.vector_layer_editing() is None
    assert window.create_features_act.isEnabled() and panel.isVisibleTo(window)
    assert not any(a.isEnabled() for a in window.edit_actions.values())

    panel.layer_list.itemClicked.emit(panel.item_for(layers["roads"]))
    assert layers["roads"].isEditable() and window.map_canvas.mapTool() is window.tool_add_line_feature
    assert all(a.isEnabled() for a in window.edit_actions.values())

    window.toggle_editing_act.trigger()
    assert not window.toggle_editing_act.isChecked() and not layers["roads"].isEditable()
    assert not window.create_features_act.isEnabled() and not panel.isVisibleTo(window)


def test_session_without_layer_toggles_off(window):
    _layers(window)
    window.layer_tree_view.setCurrentLayer(None)
    window.toggle_editing_act.trigger()
    assert window.toggle_editing_act.isChecked() and window.create_features_panel.isVisibleTo(window)
    window.toggle_editing_act.trigger()
    assert not window.toggle_editing_act.isChecked() and not window.create_features_act.isEnabled()
    assert not window.create_features_panel.isVisibleTo(window)


def test_start_editing_without_vector_layers_warns(window):
    window.toggle_editing_act.trigger()
    assert not window.toggle_editing_act.isChecked() and not window.create_features_act.isEnabled()
    assert "Chưa có lớp vector" in window.message_bar.currentItem().text()


def test_active_map_tool_button_is_checked(window):
    assert window.tool_identify_feature.action().isChecked()
    window.map_canvas.setMapTool(window.tool_pan_map)
    assert window.tool_pan_map.action().isChecked() and not window.tool_identify_feature.action().isChecked()
    assert "QToolButton:checked" in window.styleSheet()


def test_selected_layer_is_highlighted(window):
    assert "item:selected" in window.layer_tree_view.styleSheet()


def test_satellite_menu_opens_gee_dialog(window, monkeypatch):
    from vgeoint.app.dialogs import google_earth_engine
    from vgeoint.app.dialogs.google_earth_engine import GoogleEarthEngineDialog

    mb = window.menu_bar_
    assert [a.text() for a in mb.satellite_menu.actions() if not a.isSeparator()] == [
        "Tải ảnh miễn phí (không cần tài khoản)...", "Tải ảnh từ Google Earth Engine...",
        "Ảnh nền trực tuyến (chỉ xem)",
    ]
    assert mb.google_earth_engine_act not in mb.tool_menu.actions()
    monkeypatch.setattr(google_earth_engine, "credentials_path", lambda: Path("missing"))
    mb.google_earth_engine_act.trigger()
    dialogs = window.findChildren(GoogleEarthEngineDialog)
    assert dialogs and dialogs[-1].isVisible() and not dialogs[-1].isModal()
    dialogs[-1].close()


def test_tool_bars_on_one_row_without_gaps(window):
    from vgeoint.common.utils import settings

    # A saved state with a toolbar on a second row (as on the user's machine) is flattened again.
    anno = window.findChild(QToolBar, "AnnotationBPluginToolBar")
    window.insertToolBarBreak(anno)
    settings().setValue("WindowState", window.saveState())
    window.load_settings()
    window.resize(1920, 900)
    window.show()
    bars = [t for t in window.findChildren(QToolBar) if t.parent() is window and t.isVisible()]
    assert len({t.y() for t in bars}) == 1 and not any(window.toolBarBreak(t) for t in bars)
    ordered = sorted(bars, key=lambda t: t.x())
    assert all(b.x() - (a.x() + a.width()) <= 1 for a, b in zip(ordered, ordered[1:]))
    assert window.findChild(QToolBar, "VectorBPluginToolBar").isHidden()  # no plugin actions
    settings().remove("WindowState")


def test_basemaps_menu_adds_xyz_layers_at_the_bottom(window):
    from qgis.core import QgsProject

    from vgeoint.app.basemaps import BASEMAPS, xyz_uri

    assert "lyrs%3Ds%26x%3D{x}%26y%3D{y}%26z%3D{z}" in xyz_uri(BASEMAPS["google_satellite"])
    mb = window.menu_bar_
    assert [a.text() for a in mb.basemap_menu.actions()] == [b.name for b in BASEMAPS.values()]

    data = QgsVectorLayer("Point?crs=EPSG:4326", "diem", "memory")
    QgsProject.instance().addMapLayer(data)
    mb.basemap_acts["google_satellite"].trigger()
    mb.basemap_acts["google_satellite"].trigger()  # not added twice
    mb.basemap_acts["osm"].trigger()
    root = QgsProject.instance().layerTreeRoot()
    names = [n.name() for n in root.children()]
    assert names == ["diem", "Google Satellite", "OpenStreetMap"]  # basemaps under the data
    layer = QgsProject.instance().mapLayersByName("Google Satellite")[0]
    assert layer.isValid() and layer.providerType() == "wms"
    assert "Google" in window.message_bar.currentItem().text() or "OpenStreetMap" in window.message_bar.currentItem().text()


def test_basemap_on_empty_map_zooms_to_viet_nam(window):
    """Not to the whole world (the first layer's full extent, applied by the canvas bridge)."""
    from qgis.core import QgsCoordinateTransform, QgsProject

    from vgeoint.app.main_controller import VIET_NAM, WGS84

    window.menu_bar_.basemap_acts["esri_imagery"].trigger()
    window.layer_tree_map_canvas_bridge.setCanvasLayers()
    canvas = window.map_canvas
    to_wgs84 = QgsCoordinateTransform(canvas.mapSettings().destinationCrs(), WGS84, QgsProject.instance())
    extent = to_wgs84.transformBoundingBox(canvas.extent())
    assert extent.contains(VIET_NAM) and extent.height() < 30
