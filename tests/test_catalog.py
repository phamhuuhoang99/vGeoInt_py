"""Phase 5: vGeoCatalog against a real PostGIS (Docker) with the original SQL scripts."""

import pytest
from osgeo import gdal

from tests.conftest import create_database, make_raster

DB = "vGeoCatalog"


@pytest.fixture(scope="module")
def catalog_db(postgis_server):
    container, host, port, password = postgis_server
    create_database(container, DB, "catalog/command.sql", "catalog/Countries.sql", "catalog/Regions.sql")
    return host, port, password


@pytest.fixture
def catalog(qgis_app, catalog_db, monkeypatch, tmp_path):
    """Point vGeoCatalog at the test database and return a fresh connection."""
    from qgis.PyQt.QtSql import QSqlQuery

    from vgeoint.catalog import context

    host, port, password = catalog_db
    monkeypatch.setenv("VGEOINT_DB_HOST", host)
    monkeypatch.setenv("VGEOINT_DB_PORT", str(port))
    monkeypatch.setenv("VGEOINT_DB_PASSWORD", password)
    context.reset()
    db = context.database()
    assert db.isOpen(), db.lastError().text()
    for table in ("geodata", "directory", "library"):
        QSqlQuery(db).exec(f"delete from {table}")
    yield db
    context.reset()


@pytest.fixture
def data_dir(tmp_path):
    """Two georeferenced rasters in Vietnam (UTM 48N), one non-georeferenced PNG, one nested folder."""
    d = tmp_path / "anh v'tinh"  # apostrophe: broke the C++ string-built SQL
    (d / "sub").mkdir(parents=True)
    make_raster(d / "a.tif", seed=1)
    make_raster(d / "sub" / "b.tif", seed=2)
    png = gdal.GetDriverByName("PNG").CreateCopy(str(d / "photo.png"), gdal.GetDriverByName("MEM").Create("", 8, 8, 1))
    png = None
    return d


def test_geo_info_reader(qgis_app, data_dir):
    from vgeoint.catalog.geo_info_reader import GeoInfoReader

    r = GeoInfoReader(str(data_dir / "a.tif"))
    r.exec()
    assert r.is_geo_data() and r.srid == 32648
    assert r.extent_str == "(500000, 2299520) (500640, 2300000)"
    assert r.geom_wkt.startswith("POLYGON((500000 2299520, 500000 2300000")

    r.set_file_name(str(data_dir / "photo.png"))
    r.exec()
    assert not r.is_geo_data()


def test_models_with_quotes(catalog):
    from vgeoint.catalog.models import Directory, DirectoryModel, Library, LibraryModel

    libs = LibraryModel(catalog)
    libs.add_or_update(Library(0, "Thư viện 'Ảnh'", ["TIF", "PNG"]))
    [lib] = libs.get_all()
    assert lib.name == "Thư viện 'Ảnh'" and lib.filters == ["TIF", "PNG"]

    dirs = DirectoryModel(catalog)
    dirs.add_or_update(Directory(0, r"D:\anh v'tinh", True, lib.id))
    dirs.add_or_update(Directory(0, r"D:\anh v'tinh", False, lib.id))  # update, not duplicate
    assert [(d.path, d.enabled) for d in dirs.get_dirs_from_lib(lib)] == [(r"D:\anh v'tinh", False)]

    libs.remove(lib.name)
    assert libs.get_all() == []
    assert dirs.get_dirs_from_lib(lib) == []  # on delete cascade


def _scan(qtbot, catalog, data_dir):
    from vgeoint.catalog import context
    from vgeoint.catalog.models import Directory, DirectoryModel, Library, LibraryModel
    from vgeoint.catalog.scanner import ScannerThread

    LibraryModel(catalog).add_or_update(Library(0, "Kho ảnh", ["TIF", "PNG"]))
    [lib] = LibraryModel(catalog).get_all()
    DirectoryModel(catalog).add_or_update(Directory(0, str(data_dir), True, lib.id))

    thread = ScannerThread(context.config())
    reports, summaries = [], []
    thread.report.connect(lambda f, geo: reports.append((f.replace("\\", "/").split("/")[-1], geo)))
    thread.finished_scanning.connect(summaries.append)
    thread.set_library(lib)
    with qtbot.waitSignal(thread.finished, timeout=60000):
        thread.start()
    return lib, sorted(reports), summaries


def test_scanner_records_geodata(qtbot, catalog, data_dir):
    from vgeoint.catalog.models import GeoDataModel

    lib, reports, summaries = _scan(qtbot, catalog, data_dir)
    assert reports == [("a.tif", True), ("b.tif", True), ("photo.png", False)]
    assert "TIF PNG" in summaries[0] and str(data_dir) in summaries[0]

    model = GeoDataModel(catalog).get_geo_data_from_lib(lib)
    assert model.rowCount() == 2
    assert {model.data(model.index(r, 4)) for r in range(2)} == {32648}

    from qgis.PyQt.QtSql import QSqlQuery

    q = QSqlQuery(catalog)
    assert q.exec("select ST_SRID(geom), ST_XMin(geom), ST_YMin(geom) from geodata limit 1") and q.next()
    # stored in WGS84, footprint near 105°E, 20.8°N
    assert q.value(0) == 4326 and abs(q.value(1) - 105.0) < 0.01 and abs(q.value(2) - 20.79) < 0.01


def test_main_widget_searches(qtbot, catalog, data_dir):
    from qgis.core import QgsRectangle

    from vgeoint.catalog.main_widget import MainWidget

    _scan(qtbot, catalog, data_dir)
    w = MainWidget()
    qtbot.addWidget(w)
    assert w.librariesCbx.count() == 1
    assert w.countryCbx.findText("Vietnam") >= 0

    w.set_area_searching(QgsRectangle(104, 20, 106, 22))
    w.search_by_area()
    assert w.result_layer is not None and w.result_layer.featureCount() == 2
    assert w.geoDataRecTbv.model().rowCount() == 2

    w.countrySearchingTypeCbx.setCurrentIndex(1)  # ST_Intersects
    w.countryCbx.setCurrentText("Vietnam")
    w.search_by_country()
    assert w.result_layer.featureCount() == 2

    w.countryCbx.setCurrentText("Brazil")
    w.search_by_country()
    assert w.result_layer.featureCount() == 0


def test_library_widget_flow(qtbot, catalog, data_dir, monkeypatch, no_modal):
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QFileDialog

    from vgeoint.catalog.library_widget import LibraryWidget
    from vgeoint.catalog.models import Library

    w = LibraryWidget()
    qtbot.addWidget(w)
    w.lib_model.add_or_update(Library(0, "Kho", []))
    w.load_lib()
    w.librariesLwg.setCurrentRow(0)

    # formats
    for i in range(w.formatsLwg.count()):
        item = w.formatsLwg.item(i)
        if item.text() == "TIF":
            item.setCheckState(Qt.CheckState.Checked)
    w.update_filters_from_gui()
    assert w.lib_model.get_all()[0].filters == ["TIF"]

    # directories
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(data_dir))
    w.add_dir()
    w.add_dir()  # duplicate -> warning, not added twice
    assert w.dirLwg.count() == 1
    w.update_directory_from_gui()

    # scan + view
    with qtbot.waitSignal(w.scanner_thread.finished, timeout=60000):
        w.scan_lib()
    assert w.report_dlg.geoDataCountLbl.text() == "2" and w.report_dlg.totalCountLbl.text() == "2"
    w.view_lib()
    assert w.geoDataTbv.model().rowCount() == 2
    assert "Kho" in w.geoDataTableLbl.text()


def test_main_window(qtbot, catalog, no_modal):
    from vgeoint.catalog.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.libraryPageBtn.click()
    assert win.stackedWidget.currentWidget() is win.libraryWidget
    win.mainPageBtn.click()
    assert win.stackedWidget.currentWidget() is win.mainWidget


def test_main_widget_record_actions(qtbot, catalog, data_dir):
    from qgis.core import QgsRectangle
    from qgis.PyQt.QtWidgets import QApplication

    from vgeoint.catalog.main_widget import MainWidget

    _scan(qtbot, catalog, data_dir)
    w = MainWidget()
    qtbot.addWidget(w)
    w.set_area_searching(QgsRectangle(104, 20, 106, 22))
    w.search_by_area()

    table = w.geoDataRecTbv
    table.setCurrentIndex(table.model().index(0, 1))
    w.view_rec_in_map_view()
    assert len(w.result_layer.selectedFeatureIds()) == 1
    assert w.map_canvas.extent().width() < 1  # zoomed to one footprint
    w.copy_rec_as_text()
    assert QApplication.clipboard().text().endswith(".tif")
    w.clear_rec_selection()
    assert not w.result_layer.selectedFeatureIds()
