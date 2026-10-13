import pytest

TEST_SETTINGS_SCOPE = ("DMA_test", "vGeoInt_test")


@pytest.fixture(scope="session")
def qgis_app():
    from qgis.core import QgsSettings

    from vgeoint.common import utils
    from vgeoint.common.bootstrap import create_app

    # Never read or write the user's real settings (shared with the C++ app).
    utils.SETTINGS_SCOPE = TEST_SETTINGS_SCOPE
    app = create_app("vGeoInt_test")
    yield app
    QgsSettings(*TEST_SETTINGS_SCOPE).clear()


@pytest.fixture
def window(qgis_app, qtbot, monkeypatch):
    from qgis.core import QgsProject
    from qgis.PyQt.QtWidgets import QMessageBox

    from vgeoint.app.main_window import MainWindow

    # Answer every modal question (e.g. the exit confirmation on close) without blocking.
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    MainWindow._instance = None
    w = MainWindow()
    w.resize(1000, 700)
    qtbot.addWidget(w)
    yield w
    QgsProject.instance().clear()
    MainWindow._instance = None


def action_texts(menu) -> list[str]:
    return ["-" if a.isSeparator() else a.text() for a in menu.actions()]
