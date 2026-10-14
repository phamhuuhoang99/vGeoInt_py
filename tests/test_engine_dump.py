"""The vGeoEngine data dump of the old installer (sql/engine/init_vgeoengine.sql) works with the app.

The Docker server (docker/initdb/20_vgeoint.sh) builds vGeoEngine from it.
"""

import pytest

from tests.conftest import _docker

DB = "vGeoEngineDump"


@pytest.fixture(scope="module")
def dump_db(postgis_server):
    container, host, port, password = postgis_server
    _docker("exec", container, "psql", "-U", "postgres", "-c", f'drop database if exists "{DB}"')
    _docker("exec", container, "psql", "-U", "postgres", "-c", f'create database "{DB}"')
    # Same command as the Docker init script (pg_dump 17 output on a PostgreSQL 16 server).
    _docker(
        "exec", container, "bash", "-c",
        "grep -v '^SET transaction_timeout' /sql/engine/init_vgeoengine.sql"
        f" | PGCLIENTENCODING=utf-8 psql -v ON_ERROR_STOP=1 -q -U postgres -d {DB} > /dev/null",
        timeout=300,
    )
    return host, port, password


@pytest.fixture
def dump_engine(qgis_app, dump_db, monkeypatch):
    from vgeoint.engine import context

    host, port, password = dump_db
    monkeypatch.setenv("VGEOINT_DB_HOST", host)
    monkeypatch.setenv("VGEOINT_DB_PORT", str(port))
    monkeypatch.setenv("VGEOINT_DB_PASSWORD", password)
    monkeypatch.setenv("VGEOINT_DB_NAME", DB)
    context.reset()
    db = context.database()
    assert db.isOpen(), db.lastError().text()
    yield db
    context.reset()


def test_dump_has_data_the_app_can_read(dump_engine):
    from vgeoint.engine.entities import BGroup, BObjectAbstract, _scalar

    db = dump_engine
    counts = {t: _scalar(db, f"select count(*) from {t}") for t in ("tbl_hinhanh", "tbl_video", "tbl_tailieu", "tbl_taikhoan")}
    assert counts == {"tbl_hinhanh": 438, "tbl_video": 28, "tbl_tailieu": 164, "tbl_taikhoan": 2}
    assert _scalar(db, "select func_kiemtra_dangnhap('admin', matkhau) from tbl_taikhoan where tendangnhap = 'admin'") == 1

    groups = BGroup.get_all(db)
    assert groups
    obj = BObjectAbstract()
    obj.update_from_ido(db, _scalar(db, "select ido from tbl_chitiet_hinhanh limit 1"))
    assert obj.name() and obj.images()
    assert obj.images()[0].full_path().startswith("vGeoInt_DB/")
