"""Port of AircraftSearchingWidget.cpp, ShipSearchingWidget.cpp, TankSearchingWidget.cpp and RocketSearchingWidget.cpp."""

import re

from qgis.PyQt.QtWidgets import QWidget

from vgeoint.common.ui import load_ui_class

_INT = re.compile(r"\s*[+-]?\d+\s*")

# Field kinds: TEXT -> "<column> ilike '%text%'"; NUM -> "min <= <column> and <column> <= max"
TEXT, NUM = "text", "num"


def _quote(text: str) -> str:
    """Escape a value placed inside a single-quoted SQL literal (the C++ concatenated it raw)."""
    return text.replace("'", "''")


def _to_int(text: str) -> int | None:
    """QString::toInt(&ok): None when not ok."""
    return int(text) if _INT.fullmatch(text) else None


def make_where_str(where_str: str, cond: str) -> str:
    return f"({cond})" if not where_str else f"{where_str} and ({cond})"


class _ObjectSearchingWidget(QWidget):
    # (prefix, kind, column, tolerance widget suffix); widgets are <prefix>Chb, <prefix>Led, <prefix><suffix>
    FIELDS: tuple = ()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

    def get_where_str(self) -> tuple[bool, str]:
        """bool getWhereStr(QString& whereStr) -> (pass, whereStr)."""
        where_str = ""
        passed = True
        for chb, led, tolerance, kind, column in self.FIELDS:
            if not getattr(self, chb).isChecked():
                continue
            text = getattr(self, led).text().strip()
            if kind == TEXT:
                passed &= bool(text)
                where_str = make_where_str(where_str, f"{column} ilike '%{_quote(text)}%'")
            else:
                value = _to_int(text)
                passed &= value is not None
                tol = getattr(self, tolerance).value()
                v = value or 0
                where_str = make_where_str(where_str, f"{v - tol:.15g} <= {column} and {column} <= {v + tol:.15g}")
        return passed, where_str


def _field(prefix: str, kind: str, column: str, tolerance: str = "Dspb", led: str = "", chb: str = ""):
    return (chb or f"{prefix}Chb", led or f"{prefix}Led", f"{prefix}{tolerance}", kind, column)


class AircraftSearchingWidget(_ObjectSearchingWidget, load_ui_class("engine", "AircraftSearchingWidget")):
    FIELDS = (
        _field("ten", TEXT, "tbl_doituong.ten"),
        _field("chieuDai", NUM, "tbl_maybay.chieudaithan"),
        _field("saiCanh", NUM, "tbl_maybay.saicanh"),
        _field("chieuCao", NUM, "tbl_maybay.chieucao"),
        _field("dongCo", TEXT, "tbl_maybay.dongco"),
        _field("vmax", NUM, "tbl_maybay.vmax"),
        _field("hmax", NUM, "tbl_maybay.hmax"),
        _field("tamBayMax", NUM, "tbl_maybay.tambay_max"),
        _field("banKinhHd", NUM, "tbl_maybay.bankinh_hoatdong"),
        _field("nuocSanXuat", TEXT, "tbl_maybay.nuoc_sanxuat", led="nuocSxLed"),
    )


class ShipSearchingWidget(_ObjectSearchingWidget, load_ui_class("engine", "ShipSearchingWidget")):
    FIELDS = (
        _field("ten", TEXT, "tbl_doituong.ten"),
        _field("chieuDai", NUM, "tbl_tauthuyen.chieudai"),
        _field("chieuRong", NUM, "tbl_tauthuyen.chieurong"),
        _field("momNuoc", NUM, "tbl_tauthuyen.momnuoc"),
        _field("taiTrong", NUM, "tbl_tauthuyen.taitrong"),
        _field("dongCo", TEXT, "tbl_tauthuyen.dongco"),
        _field("chanVit", NUM, "tbl_tauthuyen.chanvit", "Spb"),
        _field("congSuat", NUM, "tbl_tauthuyen.congsuat", "Spb"),
        _field("tocDo", NUM, "tbl_tauthuyen.tocdo"),
        _field("tamHoatDong", NUM, "tbl_tauthuyen.tamhoatdong"),
        _field("thuyThuDoan", NUM, "tbl_tauthuyen.thuythudoan", "Spb"),
        _field("nuocSoHuu", TEXT, "tbl_tauthuyen.nuocsohuu"),
    )


class TankSearchingWidget(_ObjectSearchingWidget, load_ui_class("engine", "TankSearchingWidget")):
    FIELDS = (
        _field("ten", TEXT, "tbl_doituong.ten"),
        _field("chieuDai", NUM, "tbl_xetang.chieudai"),
        _field("chieuRong", NUM, "tbl_xetang.chieurong"),
        _field("taiTrong", NUM, "tbl_xetang.taitrong"),
        _field("nuocSoHuu", TEXT, "tbl_xetang.nuoc_sohuu"),
    )


class RocketSearchingWidget(_ObjectSearchingWidget, load_ui_class("engine", "RocketSearchingWidget")):
    FIELDS = (
        _field("ten", TEXT, "tbl_doituong.ten"),
        _field("soBe", NUM, "tbl_trandiatenlua.so_be", "Spb"),
        _field("soXeRada", NUM, "tbl_trandiatenlua.so_xerada", "Spb"),
        _field("soXeChiHuy", NUM, "tbl_trandiatenlua.so_xechihuy", "Spb"),
        _field("duongKinh", NUM, "tbl_trandiatenlua.duongkinh"),
        _field("nuocSoHuu", TEXT, "tbl_trandiatenlua.nuoc_sohuu"),
    )
