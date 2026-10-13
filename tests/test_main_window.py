"""Phase 1: the main window has the same menus, toolbars and docks as the C++ app."""

import pytest
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtWidgets import QToolBar

from tests.conftest import action_texts


@pytest.fixture
def window(qgis_app, qtbot, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox

    from vgeoint.app.main_window import MainWindow

    # Answer every modal question (e.g. the exit confirmation on close) without blocking.
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(MainWindow, "save_settings", lambda self: None)
    MainWindow._instance = None
    w = MainWindow()
    qtbot.addWidget(w)
    yield w
    QgsProject.instance().clear()
    MainWindow._instance = None


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
    window.main_controller.ship_detection()
    assert window.message_bar.currentItem() is not None
