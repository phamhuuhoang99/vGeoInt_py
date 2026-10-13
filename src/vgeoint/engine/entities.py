"""Port of BObjectAbstract, Aircraft, Ship, Tank, Rocket, BGroup, BClass, BType, Media, Image, Video, Document (.cpp).

The C++ classes built SQL by string concatenation; here every call uses bound parameters (with explicit
casts, since several SQL functions are overloaded) against the same SQL functions.
"""

from __future__ import annotations

import logging

from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice, Qt
from qgis.PyQt.QtGui import QImage
from qgis.PyQt.QtSql import QSqlDatabase, QSqlQuery

from vgeoint.engine.defines import make_ido

log = logging.getLogger(__name__)


def exec_query(db: QSqlDatabase, sql: str, *values) -> QSqlQuery | None:
    """Prepare `sql` (with ? placeholders), bind `values` in order and execute; None (logged) on failure."""
    query = QSqlQuery(db)
    if not query.prepare(sql):
        log.warning("%s: %s", sql, query.lastError().text())
        return None
    for v in values:
        query.addBindValue(v)
    if not query.exec():
        log.warning("%s: %s", sql, query.lastError().text())
        return None
    return query


def _scalar(db: QSqlDatabase, sql: str, *values):
    query = exec_query(db, sql, *values)
    if query is not None and query.next():
        return query.value(0)
    return None


def _str(value) -> str:
    return "" if value is None else str(value)


# ---------------------------------------------------------------------------------------------- Media


class Media:
    def __init__(self, ido: int, path: str):
        self._ido = ido
        self._path = ""
        self.set_path(path)

    def ido(self) -> int:
        return self._ido

    def path_without_label(self) -> str:
        """Path without the drive label ("C:/a/b.jpg" -> "a/b.jpg")."""
        idx = self._path.find(":")
        if idx > 0:
            return self._path[idx + 2:]
        return self._path

    def full_path(self) -> str:
        return self._path

    def set_ido(self, ido: int):
        self._ido = ido

    def set_path(self, path: str):
        self._path = path

    @staticmethod
    def _get_changed(old: list, now: list) -> tuple[list, list]:
        old_keys = {m.path_without_label().lower() for m in old}
        now_keys = {m.path_without_label().lower() for m in now}
        removed = [m for m in old if m.path_without_label().lower() not in now_keys]
        added = [m for m in now if m.path_without_label().lower() not in old_keys]
        return added, removed


class Image(Media):
    def __init__(self, ido: int = -1, path: str = "", thumbnail: str = ""):
        super().__init__(ido, path)
        self._thumbnail = thumbnail

    def thumbnail(self) -> str:
        return self._thumbnail

    @staticmethod
    def base64_from_image(image: QImage) -> str:
        thumb = image.scaled(64, 64, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        ba = QByteArray()
        bf = QBuffer(ba)
        bf.open(QIODevice.OpenModeFlag.WriteOnly)
        thumb.save(bf, "jpg")
        bf.close()
        return bytes(ba.toBase64()).decode("ascii")

    @staticmethod
    def image_from_base64(text: str) -> QImage:
        ba = QByteArray.fromBase64(QByteArray(text.encode("latin-1", "ignore")))
        image = QImage()
        image.loadFromData(ba, "jpg")
        return image

    @staticmethod
    def get_changed(old: list[Image], now: list[Image]) -> tuple[list[Image], list[Image]]:
        """Return (added, removed), comparing paths without drive label, case-insensitively."""
        return Media._get_changed(old, now)


class Video(Media):
    def __init__(self, ido: int = -1, path: str = "", thumbnail: str = ""):
        super().__init__(ido, path)
        self._thumbnail = thumbnail

    def set_thumbnail(self, thumbnail: str):
        self._thumbnail = thumbnail

    def thumbnail(self) -> str:
        return self._thumbnail

    @staticmethod
    def get_changed(old: list[Video], now: list[Video]) -> tuple[list[Video], list[Video]]:
        """Return (added, removed)."""
        return Media._get_changed(old, now)


class Document(Media):
    def __init__(self, ido: int = -1, path: str = ""):
        super().__init__(ido, path)

    @staticmethod
    def get_changed(old: list[Document], now: list[Document]) -> tuple[list[Document], list[Document]]:
        """Return (added, removed)."""
        return Media._get_changed(old, now)


# ------------------------------------------------------------------------------------- BObjectAbstract

_GROUP_CODES = {
    "Máy bay": "MBA",
    "Sân bay": "SBA",
    "Xe tăng": "XET",
    "Trận địa tên lửa": "TTL",
    "Tàu thuyền": "TAU",
    "Căn cứ": "CCU",
    "Cảng quân sự": "CQS",
    "Kho quân sự": "KQS",
}


class BObjectAbstract:
    def __init__(self, ido: str = "", name: str = "", note: str = ""):
        self._ido = ido
        self._name = name
        self._note = note
        self._images: list[Image] = []
        self._videos: list[Video] = []
        self._documents: list[Document] = []

    def ido(self) -> str:
        return self._ido

    def name(self) -> str:
        return self._name

    def note(self) -> str:
        return self._note

    def images(self) -> list[Image]:
        return self._images

    def videos(self) -> list[Video]:
        return self._videos

    def documents(self) -> list[Document]:
        return self._documents

    def set_ido(self, ido: str):
        self._ido = ido

    def set_name(self, name: str):
        self._name = name

    def set_note(self, note: str):
        self._note = note

    def set_images(self, images: list[Image]):
        self._images = images

    def set_videos(self, videos: list[Video]):
        self._videos = videos

    def set_documents(self, documents: list[Document]):
        self._documents = documents

    def _get_images(self, db: QSqlDatabase, ido: str) -> list[Image]:
        query = exec_query(db, "select * from func_lay_dshinhanh(?::varchar)", ido)
        images = []
        while query is not None and query.next():
            images.append(Image(int(query.value(0)), _str(query.value(1)), _str(query.value(2))))
        return images

    def _get_videos(self, db: QSqlDatabase, ido: str) -> list[Video]:
        query = exec_query(db, "select * from func_lay_dsvideo(?::varchar)", ido)
        videos = []
        while query is not None and query.next():
            videos.append(Video(int(query.value(0)), _str(query.value(1)), _str(query.value(2))))
        return videos

    def _get_documents(self, db: QSqlDatabase, ido: str) -> list[Document]:
        query = exec_query(db, "select * from func_lay_dstailieu(?::varchar)", ido)
        documents = []
        while query is not None and query.next():
            documents.append(Document(int(query.value(0)), _str(query.value(1))))
        return documents

    def _get_note(self, db: QSqlDatabase, ido: str) -> str:
        return _str(_scalar(db, "select func_lay_ghichu(?::varchar)", ido))

    def _get_name(self, db: QSqlDatabase, ido: str) -> str:
        return _str(_scalar(db, "select func_lay_ten(?::varchar)", ido))

    def update_from_ido(self, db: QSqlDatabase, ido: str):
        self.set_ido(ido)
        self.set_name(self._get_name(db, ido))
        self.set_note(self._get_note(db, ido))
        self.set_images(self._get_images(db, ido))
        self.set_videos(self._get_videos(db, ido))
        self.set_documents(self._get_documents(db, ido))

    @staticmethod
    def add(db: QSqlDatabase, name: str, ido_phl: str):
        exec_query(db, "select func_them_doituong(?::text, ?::varchar)", name, ido_phl)

    @staticmethod
    def update(db: QSqlDatabase, id_: int, name: str):
        exec_query(db, "select func_sua_doituong(?::int, ?::text)", id_, name)

    @staticmethod
    def remove(db: QSqlDatabase, id_: int):
        exec_query(db, "select func_xoa_doituong(?::int)", id_)

    @staticmethod
    def get_all(db: QSqlDatabase, ido_phl: str) -> list[BObjectAbstract]:
        """All objects classified under `ido_phl` (a TYPxxxxx, or a GRPxxxxx for groups without classes)."""
        query = exec_query(db, "select func_lay_tennhom_idt(?::varchar)", ido_phl)
        if query is None:
            return []
        query.next()
        code = BObjectAbstract.code_from_vn(_str(query.value(0)))

        query = exec_query(db, "select * from func_laytatca_doituong(?::varchar)", ido_phl)
        objs = []
        while query is not None and query.next():
            objs.append(BObjectAbstract(make_ido(code, int(query.value(0))), _str(query.value(1))))
        return objs

    @staticmethod
    def code_from_vn(text: str) -> str:
        return _GROUP_CODES.get(text, "###")


# ------------------------------------------------------------------------------- Group / Class / Type


class BGroup(BObjectAbstract):
    def __init__(self, ido: str, name: str):
        super().__init__(ido, name)

    @staticmethod
    def add(db: QSqlDatabase, name: str):
        exec_query(db, "select func_them_nhomdoituong(?::text)", name)

    @staticmethod
    def update(db: QSqlDatabase, id_: int, name: str):
        exec_query(db, "select func_sua_nhomdoituong(?::int, ?::text)", id_, name)

    @staticmethod
    def remove(db: QSqlDatabase, id_: int):
        exec_query(db, "select func_xoa_nhomdoituong(?::int)", id_)

    @staticmethod
    def get_all(db: QSqlDatabase) -> list[BGroup]:
        query = exec_query(db, "select * from func_laytatca_nhomdoituong()")
        groups = []
        while query is not None and query.next():
            groups.append(BGroup(make_ido("GRP", int(query.value(0))), _str(query.value(1))))
        return groups


class BClass(BObjectAbstract):
    def __init__(self, ido: str, name: str, id_group: int):
        super().__init__(ido, name)
        self._id_group = id_group

    def id_group(self) -> int:
        return self._id_group

    @staticmethod
    def add(db: QSqlDatabase, name: str, id_group: int):
        exec_query(db, "select func_them_loaidoituong(?::text, ?::int)", name, id_group)

    @staticmethod
    def update(db: QSqlDatabase, id_: int, name: str):
        exec_query(db, "select func_sua_loaidoituong(?::int, ?::text)", id_, name)

    @staticmethod
    def remove(db: QSqlDatabase, id_: int):
        exec_query(db, "select func_xoa_loaidoituong(?::int)", id_)

    @staticmethod
    def get_all(db: QSqlDatabase, id_group: int) -> list[BClass]:
        query = exec_query(db, "select * from func_laytatca_loaidoituong(?::int)", id_group)
        classes = []
        while query is not None and query.next():
            classes.append(BClass(make_ido("CLS", int(query.value(0))), _str(query.value(1)), id_group))
        return classes


class BType(BObjectAbstract):
    def __init__(self, ido: str, name: str, id_class: int):
        super().__init__(ido, name)
        self._id_class = id_class

    def id_class(self) -> int:
        return self._id_class

    @staticmethod
    def add(db: QSqlDatabase, name: str, id_class: int):
        exec_query(db, "select func_them_kieudoituong(?::text, ?::int)", name, id_class)

    @staticmethod
    def update(db: QSqlDatabase, id_: int, name: str):
        exec_query(db, "select func_sua_kieudoituong(?::int, ?::text)", id_, name)

    @staticmethod
    def remove(db: QSqlDatabase, id_: int):
        exec_query(db, "select func_xoa_kieudoituong(?::int)", id_)

    @staticmethod
    def get_id_class_group(db: QSqlDatabase, id_type: int) -> tuple[int, int] | None:
        """Return (id_class, id_group) of a type, None when not found (C++ out-params left unchanged)."""
        query = exec_query(db, "select * from func_layid_loainhom(?::int)", id_type)
        if query is not None and query.next():
            return int(query.value(0)), int(query.value(1))
        return None

    @staticmethod
    def get_all(db: QSqlDatabase, id_class: int) -> list[BType]:
        query = exec_query(db, "select * from func_laytatca_kieudoituong(?::int)", id_class)
        types = []
        while query is not None and query.next():
            types.append(BType(make_ido("TYP", int(query.value(0))), _str(query.value(1)), id_class))
        return types


# ------------------------------------------------------------------------------ Object attribute sets


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class Aircraft(BObjectAbstract):
    def __init__(self):
        super().__init__()
        self.chieu_dai_than = 0.0
        self.sai_canh = 0.0
        self.chieu_cao = 0.0
        self.dong_co = ""
        self.vmax = 0.0
        self.hmax = 0.0
        self.tam_bay_max = 0.0
        self.ban_kinh_hd = 0.0
        self.nuoc_sx = ""

    def auto_update(self, db: QSqlDatabase):
        """Load the attributes of ido() (all zero / empty when there is no row)."""
        query = exec_query(db, "select * from func_lay_maybay(?::varchar)", self.ido())
        ok = query is not None and query.next()
        v = (lambda i: query.value(i)) if ok else (lambda i: None)
        self.chieu_dai_than = _float(v(0))
        self.sai_canh = _float(v(1))
        self.chieu_cao = _float(v(2))
        self.dong_co = _str(v(3))
        self.vmax = _float(v(4))
        self.hmax = _float(v(5))
        self.tam_bay_max = _float(v(6))
        self.ban_kinh_hd = _float(v(7))
        self.nuoc_sx = _str(v(8))

    def auto_insert(self, db: QSqlDatabase):
        exec_query(
            db,
            "select func_them_maybay(?::varchar, ?::real, ?::real, ?::real, ?::text, ?::real, ?::real, ?::real, ?::real, ?::text)",
            self.ido(), float(self.chieu_dai_than), float(self.sai_canh), float(self.chieu_cao), self.dong_co,
            float(self.vmax), float(self.hmax), float(self.tam_bay_max), float(self.ban_kinh_hd), self.nuoc_sx,
        )


class Ship(BObjectAbstract):
    def __init__(self):
        super().__init__()
        self.chieu_dai = 0.0
        self.chieu_rong = 0.0
        self.mom_nuoc = 0.0
        self.tai_trong = 0.0
        self.dong_co = ""
        self.chan_vit = 0
        self.cong_suat = 0
        self.toc_do = 0.0
        self.tam_hoat_dong = 0.0
        self.thuy_thu_doan = 0
        self.nuoc_so_huu = ""

    def auto_update(self, db: QSqlDatabase):
        query = exec_query(db, "select * from func_lay_tauthuyen(?::varchar)", self.ido())
        ok = query is not None and query.next()
        v = (lambda i: query.value(i)) if ok else (lambda i: None)
        self.chieu_dai = _float(v(0))
        self.chieu_rong = _float(v(1))
        self.mom_nuoc = _float(v(2))
        self.tai_trong = _float(v(3))
        self.dong_co = _str(v(4))
        self.chan_vit = _int(v(5))
        self.cong_suat = _int(v(6))
        self.toc_do = _float(v(7))
        self.tam_hoat_dong = _float(v(8))
        self.thuy_thu_doan = _int(v(9))
        self.nuoc_so_huu = _str(v(10))

    def auto_insert(self, db: QSqlDatabase):
        exec_query(
            db,
            "select func_them_tauthuyen(?::varchar, ?::real, ?::real, ?::real, ?::real, ?::text, ?::int, ?::int,"
            " ?::real, ?::real, ?::int, ?::text)",
            self.ido(), float(self.chieu_dai), float(self.chieu_rong), float(self.mom_nuoc), float(self.tai_trong),
            self.dong_co, int(self.chan_vit), int(self.cong_suat), float(self.toc_do), float(self.tam_hoat_dong),
            int(self.thuy_thu_doan), self.nuoc_so_huu,
        )


class Tank(BObjectAbstract):
    def __init__(self):
        super().__init__()
        self.chieu_dai = 0.0
        self.chieu_rong = 0.0
        self.tai_trong = 0.0
        self.nuoc_so_huu = ""

    def auto_update(self, db: QSqlDatabase):
        query = exec_query(db, "select * from func_lay_xetang(?::varchar)", self.ido())
        ok = query is not None and query.next()
        v = (lambda i: query.value(i)) if ok else (lambda i: None)
        self.chieu_dai = _float(v(0))
        self.chieu_rong = _float(v(1))
        self.tai_trong = _float(v(2))
        self.nuoc_so_huu = _str(v(3))

    def auto_insert(self, db: QSqlDatabase):
        exec_query(
            db,
            "select func_them_xetang(?::varchar, ?::real, ?::real, ?::real, ?::text)",
            self.ido(), float(self.chieu_dai), float(self.chieu_rong), float(self.tai_trong), self.nuoc_so_huu,
        )


class Rocket(BObjectAbstract):
    def __init__(self):
        super().__init__()
        self.so_be = 0
        self.so_xe_rada = 0
        self.so_xe_chi_huy = 0
        self.duong_kinh = 0.0
        self.nuoc_so_huu = ""

    def auto_update(self, db: QSqlDatabase):
        query = exec_query(db, "select * from func_lay_trandiatenlua(?::varchar)", self.ido())
        ok = query is not None and query.next()
        v = (lambda i: query.value(i)) if ok else (lambda i: None)
        self.so_be = _int(v(0))
        self.so_xe_rada = _int(v(1))
        self.so_xe_chi_huy = _int(v(2))
        self.duong_kinh = _float(v(3))
        self.nuoc_so_huu = _str(v(4))

    def auto_insert(self, db: QSqlDatabase):
        exec_query(
            db,
            "select func_them_trandiatenlua(?::varchar, ?::int, ?::int, ?::int, ?::real, ?::text)",
            self.ido(), int(self.so_be), int(self.so_xe_rada), int(self.so_xe_chi_huy), float(self.duong_kinh),
            self.nuoc_so_huu,
        )
