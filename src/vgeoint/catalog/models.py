"""Port of Library/Directory/GeoData and their *Model classes (vGeoCatalog).

The C++ models built SQL by string concatenation ("select insert_directory('%1', ...)"), so any path or
name containing an apostrophe broke the query. Here every call uses bound parameters.
"""

import logging
from dataclasses import dataclass, field

from qgis.PyQt.QtCore import QDateTime
from qgis.PyQt.QtSql import QSqlDatabase, QSqlQuery, QSqlQueryModel

log = logging.getLogger(__name__)


@dataclass
class Library:
    id: int = 0
    name: str = ""
    filters: list[str] = field(default_factory=list)

    @classmethod
    def from_filters_str(cls, id_: int, name: str, filters: str) -> "Library":
        return cls(id_, name, (filters or "").strip().split(" ") if (filters or "").strip() else [])

    def star_filters(self) -> list[str]:
        return [f"*.{f}" for f in self.filters]

    def filters_str(self) -> str:
        return " ".join(self.filters).strip()

    def set_filters(self, filters: str):
        self.filters = filters.strip().split(" ") if filters.strip() else []


@dataclass
class Directory:
    id: int = 0
    path: str = ""
    enabled: bool = True
    id_lib: int = 0


@dataclass
class GeoData:
    id: int = 0
    file_name: str = ""
    date_time: QDateTime = field(default_factory=QDateTime)
    extent: str = ""
    coordinate_system: str = ""
    srid: int = -1
    geom_wkt: str = ""  # POLYGON in the layer CRS
    id_lib: int = 0


def _exec(db: QSqlDatabase, sql: str, *values) -> QSqlQuery:
    query = QSqlQuery(db)
    query.prepare(sql)
    for v in values:
        query.addBindValue(v)
    if not query.exec():
        log.error("%s: %s", sql, query.lastError().text())
    return query


class LibraryModel:
    def __init__(self, db: QSqlDatabase):
        self.db = db

    def add_or_update(self, lib: Library):
        _exec(self.db, "select insert_library(?, ?)", lib.name, lib.filters_str())

    def remove(self, name: str):
        _exec(self.db, "select remove_library(?)", name)

    def get_all(self) -> list[Library]:
        query = _exec(self.db, "select id, name, filters from library order by name")
        libraries = []
        while query.next():
            libraries.append(Library.from_filters_str(int(query.value(0)), query.value(1), query.value(2) or ""))
        return libraries


class DirectoryModel:
    def __init__(self, db: QSqlDatabase):
        self.db = db

    def add_or_update(self, d: Directory):
        _exec(self.db, "select insert_directory(?, ?, ?)", d.path, d.enabled, d.id_lib)

    def remove(self, path: str, id_lib: int):
        _exec(self.db, "select remove_directory(?, ?)", path, id_lib)

    def get_dirs_from_lib(self, lib: Library) -> list[Directory]:
        query = _exec(self.db, "select id, path, enabled, idlib from directory where idlib = ? order by path", lib.id)
        dirs = []
        while query.next():
            dirs.append(Directory(int(query.value(0)), query.value(1), bool(query.value(2)), int(query.value(3))))
        return dirs


class GeoDataModel:
    def __init__(self, db: QSqlDatabase):
        self.db = db
        self.query_model = QSqlQueryModel()

    def add_or_update(self, g: GeoData):
        # insert_geodata() takes the geometry as text and casts it; build it server-side from WKT + SRID
        # (same ST_GeomFromText / ST_Transform(…, 4326) expression the C++ concatenated into the call).
        geom = "ST_GeomFromText(?, ?)" if g.srid == 4326 else "ST_Transform(ST_GeomFromText(?, ?), 4326)"
        _exec(
            self.db,
            f"select insert_geodata(?, ?, ?, ?, ?, {geom}::text, ?)",
            g.file_name,
            g.date_time.toString("yyyy-MM-dd hh:mm:ss"),
            g.extent,
            g.coordinate_system,
            g.srid,
            g.geom_wkt,
            g.srid,
            g.id_lib,
        )

    def remove(self, file_name: str, id_lib: int):
        _exec(self.db, "select remove_geodata(?, ?)", file_name, id_lib)

    def get_geo_data_from_lib(self, lib: Library) -> QSqlQueryModel:
        query = _exec(
            self.db,
            "select filename, datetime, extent, coordinatesystem, srid from geodata where idlib = ?",
            lib.id,
        )
        self.query_model.setQuery(query)
        return self.query_model
