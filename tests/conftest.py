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


@pytest.fixture
def no_modal(monkeypatch):
    """Make QMessageBox static helpers return immediately (Yes/Ok) so tests never block."""
    from qgis.PyQt.QtWidgets import QMessageBox

    Btn = QMessageBox.StandardButton
    for name, answer in (("question", Btn.Yes), ("warning", Btn.Ok), ("information", Btn.Ok), ("critical", Btn.Ok)):
        monkeypatch.setattr(QMessageBox, name, lambda *a, _r=answer, **k: _r)


def make_raster(path, bands: int = 3, width: int = 64, height: int = 48, dtype: str = "Byte", seed: int = 0):
    """Write a small georeferenced GeoTIFF (EPSG:32648) with deterministic random data; return its path."""
    import numpy as np
    from osgeo import gdal, osr

    gdal_type = {"Byte": gdal.GDT_Byte, "UInt16": gdal.GDT_UInt16, "Float32": gdal.GDT_Float32}[dtype]
    np_type = {"Byte": np.uint8, "UInt16": np.uint16, "Float32": np.float32}[dtype]
    ds = gdal.GetDriverByName("GTiff").Create(str(path), width, height, bands, gdal_type)
    ds.SetGeoTransform((500000, 10, 0, 2300000, 0, -10))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32648)
    ds.SetProjection(srs.ExportToWkt())
    rng = np.random.default_rng(seed)
    for b in range(1, bands + 1):
        ds.GetRasterBand(b).WriteArray(rng.integers(0, 200, size=(height, width)).astype(np_type))
    ds = None
    return str(path)


@pytest.fixture
def sample_raster(tmp_path):
    """A 3-band 64x48 Byte GeoTIFF."""
    return make_raster(tmp_path / "sample.tif")


def action_texts(menu) -> list[str]:
    return ["-" if a.isSeparator() else a.text() for a in menu.actions()]
