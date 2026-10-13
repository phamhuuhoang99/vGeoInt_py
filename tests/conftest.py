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


# ------------------------------------------------------------------ PostGIS (Docker)
POSTGIS_IMAGE = "postgis/postgis:16-3.4"
TEST_DB_PASSWORD = "vgeoint_test"


def _docker(*args, check=True, timeout=120):
    import subprocess

    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=timeout)


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def postgis_server():
    """A throwaway PostGIS container; yields (host, port, password). Skips when Docker is unavailable."""
    import shutil
    import time

    if shutil.which("docker") is None or _docker("info", check=False, timeout=30).returncode != 0:
        pytest.skip("Docker is not running")
    from vgeoint.common.paths import SQL_DIR

    port = _free_port()
    container = _docker(
        "run", "-d", "--rm",
        "-p", f"127.0.0.1:{port}:5432",
        "-e", f"POSTGRES_PASSWORD={TEST_DB_PASSWORD}",
        "-v", f"{SQL_DIR}:/sql:ro",
        POSTGIS_IMAGE,
        timeout=600,
    ).stdout.strip()
    try:
        deadline = time.time() + 120
        # The image restarts postgres once after initdb; wait for a real query to succeed.
        while _docker("exec", container, "psql", "-U", "postgres", "-c", "select 1", check=False).returncode != 0:
            if time.time() > deadline:
                raise RuntimeError("PostGIS container did not start")
            time.sleep(1)
        time.sleep(2)
        while _docker("exec", container, "psql", "-U", "postgres", "-c", "select 1", check=False).returncode != 0:
            time.sleep(1)
        yield container, "127.0.0.1", port, TEST_DB_PASSWORD
    finally:
        _docker("rm", "-f", container, check=False)


def create_database(container: str, name: str, *sql_files: str):
    """Create a database in the test container and run SQL files from sql/ (e.g. "catalog/command.sql")."""
    _docker("exec", container, "psql", "-U", "postgres", "-c", f'drop database if exists "{name}"')
    _docker("exec", container, "psql", "-U", "postgres", "-c", f'create database "{name}"')
    for f in sql_files:
        _docker("exec", container, "psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", "postgres", "-d", name, "-f", f"/sql/{f}", timeout=300)


ENGINE_SQL = [
    f"engine/{name}.sql"
    for name in (
        "Group", "Class", "Type", "Object", "Note", "Image", "ImageDetail", "Video", "VideoDetail",
        "Document", "DocumentDetail", "Account", "Aircraft", "Ship", "Tank", "Rocket",
    )
]  # same order as vGeoEngine/SQL/init-db.bat


@pytest.fixture(scope="module")
def engine_db(postgis_server):
    """A fresh vGeoEngine database built from the original SQL scripts; yields (container, host, port, password)."""
    container, host, port, password = postgis_server
    create_database(container, "vGeoEngine", *ENGINE_SQL)
    return container, host, port, password


@pytest.fixture
def engine(qgis_app, engine_db, monkeypatch):
    """Point vGeoEngine at the test database; returns the open QSqlDatabase."""
    from vgeoint.engine import context

    _container, host, port, password = engine_db
    monkeypatch.setenv("VGEOINT_DB_HOST", host)
    monkeypatch.setenv("VGEOINT_DB_PORT", str(port))
    monkeypatch.setenv("VGEOINT_DB_PASSWORD", password)
    context.reset()
    db = context.database()
    assert db.isOpen(), db.lastError().text()
    yield db
    context.reset()
