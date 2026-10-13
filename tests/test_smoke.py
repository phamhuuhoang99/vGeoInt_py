"""Smoke tests: QGIS boots and every .ui file loads."""

import pytest

from vgeoint.common.paths import UI_DIR

# .ui files whose promoted custom widgets are not ported yet; shrink this set phase by phase.
PENDING = {
    "catalog/MainWindow",  # LibraryWidget (phase 5)
    "engine/DatabaseWidget",  # phase 6
    "engine/MainWindow",
    "engine/MediaInputWidget",
    "engine/MediaViewerWidget",
    "engine/SearchingWidget",
}

UI_FILES = sorted(f"{p.parent.name}/{p.stem}" for p in UI_DIR.glob("*/*.ui"))




def test_ui_count():
    assert len(UI_FILES) == 55


@pytest.mark.parametrize("ui", UI_FILES)
def test_ui_file_loads(qgis_app, ui):
    from vgeoint.common.ui import load_ui_class

    if ui in PENDING:
        pytest.xfail("custom widgets not ported yet")
    app, name = ui.split("/")
    load_ui_class(app, name)


