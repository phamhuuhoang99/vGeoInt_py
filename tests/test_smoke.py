"""Smoke tests: QGIS boots, every .ui loads, and the main window builds."""

import pytest

from vgeoint.common.paths import UI_DIR

# .ui files whose promoted custom widgets are not ported yet; shrink this set phase by phase.
PENDING = {
    "app/ImageFilterDialog",  # Averaging/Canny/Gaussian/Median/Scharr/Sobel widgets (phase 3)
    "catalog/MainWindow",  # LibraryWidget (phase 5)
    "engine/DatabaseWidget",  # phase 6
    "engine/MainWindow",
    "engine/MediaInputWidget",
    "engine/MediaViewerWidget",
    "engine/SearchingWidget",
}

UI_FILES = sorted(f"{p.parent.name}/{p.stem}" for p in UI_DIR.glob("*/*.ui"))


@pytest.fixture(scope="session")
def qgis_app():
    from vgeoint.common.bootstrap import create_app

    return create_app("vGeoInt_test")


def test_ui_count():
    assert len(UI_FILES) == 55


@pytest.mark.parametrize("ui", UI_FILES)
def test_ui_file_loads(qgis_app, ui):
    from vgeoint.common.ui import load_ui_class

    if ui in PENDING:
        pytest.xfail("custom widgets not ported yet")
    app, name = ui.split("/")
    load_ui_class(app, name)


def test_main_window(qgis_app, qtbot):
    from vgeoint.app.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "vGeoInt_v2"
    assert window.map_canvas is not None
