"""The data dumps of the old installer (sql/*/init_*.sql) load and work with the apps.

The Docker server (docker/initdb/20_vgeoint.sh) builds vGeoCatalog / vGeoEngine from them.
"""

import pytest

from tests.conftest import _docker


def _load_dump(container: str, db: str, dump: str):
    _docker("exec", container, "psql", "-U", "postgres", "-c", f'drop database if exists "{db}"')
    _docker("exec", container, "psql", "-U", "postgres", "-c", f'create database "{db}"')
    # Same command as the Docker init script (pg_dump 17 output on a PostgreSQL 16 server).
    _docker(
        "exec", container, "bash", "-c",
        f"set -o pipefail; grep -v '^SET transaction_timeout' /sql/{dump}"
        f" | PGCLIENTENCODING=utf-8 psql -v ON_ERROR_STOP=1 -q -U postgres -d {db} > /dev/null",
        timeout=300,
    )


@pytest.fixture(scope="module")
def dumps(postgis_server):
    container, host, port, password = postgis_server
    _load_dump(container, "vGeoCatalogDump", "catalog/init_vgeocatalog.sql")
    _load_dump(container, "vGeoEngineDump", "engine/init_vgeoengine.sql")
    return host, port, password


def _connect(monkeypatch, dumps, context, name):
    host, port, password = dumps
    monkeypatch.setenv("VGEOINT_DB_HOST", host)
    monkeypatch.setenv("VGEOINT_DB_PORT", str(port))
    monkeypatch.setenv("VGEOINT_DB_PASSWORD", password)
    monkeypatch.setenv("VGEOINT_DB_NAME", name)
    context.reset()
    db = context.database()
    assert db.isOpen(), db.lastError().text()
    return db


def test_engine_dump(qgis_app, dumps, monkeypatch):
    from vgeoint.engine import context
    from vgeoint.engine.entities import BGroup, BObjectAbstract, _scalar

    db = _connect(monkeypatch, dumps, context, "vGeoEngineDump")
    try:
        tables = ("tbl_hinhanh", "tbl_video", "tbl_tailieu", "tbl_taikhoan")
        counts = {t: _scalar(db, f"select count(*) from {t}") for t in tables}
        assert counts == {"tbl_hinhanh": 438, "tbl_video": 28, "tbl_tailieu": 164, "tbl_taikhoan": 2}
        login = "select func_kiemtra_dangnhap('admin', matkhau) from tbl_taikhoan where tendangnhap = 'admin'"
        assert _scalar(db, login) == 1
        assert BGroup.get_all(db)
        obj = BObjectAbstract()
        obj.update_from_ido(db, _scalar(db, "select ido from tbl_chitiet_hinhanh limit 1"))
        assert obj.name() and obj.images()
        assert obj.images()[0].full_path().startswith("vGeoInt_DB/")
    finally:
        context.reset()


def test_catalog_dump(qgis_app, dumps, monkeypatch):
    from vgeoint.catalog import context
    from vgeoint.catalog.models import DirectoryModel, LibraryModel

    db = _connect(monkeypatch, dumps, context, "vGeoCatalogDump")
    try:
        libraries = LibraryModel(db).get_all()
        assert [lib.name for lib in libraries] == ["Thư viện 1", "Thư viện 2"]
        assert all(DirectoryModel(db).get_dirs_from_lib(lib) for lib in libraries)
        from qgis.PyQt.QtSql import QSqlQuery

        query = QSqlQuery(db)
        assert query.exec("select count(*), count(geom) from geodata") and query.next()
        assert (query.value(0), query.value(1)) == (13, 13)
    finally:
        context.reset()
