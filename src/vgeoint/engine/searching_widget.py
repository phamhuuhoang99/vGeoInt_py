"""Port of SearchingWidget.cpp."""

import logging

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtSql import QSqlQuery
from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from vgeoint.common.ui import load_ui_class
from vgeoint.engine import context
from vgeoint.engine.defines import ido2id, make_ido

log = logging.getLogger(__name__)
Ui_SearchingWidget = load_ui_class("engine", "SearchingWidget")

_AIRCRAFT_SQL = (
    " select tbl_doituong.id, tbl_doituong.ten, tbl_kieudoituong.ten, tbl_loaidoituong.ten"
    " from tbl_doituong, tbl_kieudoituong, tbl_loaidoituong, tbl_maybay"
    " where tbl_doituong.id = substring(tbl_maybay.ido, 4)::int"
    " and substring(tbl_doituong.ido_phanloai,4)::int = tbl_kieudoituong.id"
    " and tbl_loaidoituong.id = tbl_kieudoituong.id_loai"
)
_SHIP_SQL = (
    " select tbl_doituong.id, tbl_doituong.ten, tbl_kieudoituong.ten, tbl_loaidoituong.ten"
    " from tbl_doituong, tbl_kieudoituong, tbl_loaidoituong, tbl_tauthuyen"
    " where tbl_doituong.id = substring(tbl_tauthuyen.ido, 4)::int"
    " and substring(tbl_doituong.ido_phanloai,4)::int = tbl_kieudoituong.id"
    " and tbl_loaidoituong.id = tbl_kieudoituong.id_loai"
)
_TANK_SQL = (
    " select id, ten, nuoc_sohuu"
    " from tbl_doituong, tbl_xetang"
    " where substring(tbl_xetang.ido, 4)::int = tbl_doituong.id"
)
_ROCKET_SQL = (
    " select id, ten, nuoc_sohuu"
    " from tbl_doituong, tbl_trandiatenlua"
    " where substring(tbl_trandiatenlua.ido, 4)::int = tbl_doituong.id"
)


class SearchingWidget(QWidget, Ui_SearchingWidget):
    view_ido = pyqtSignal(str)
    searching_complete = pyqtSignal(object)  # QSqlQuery positioned before the first row

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.m_ido_group = ""
        self.create_connections()

    def set_group_name(self, name: str):
        self.titleLbl.setText(name)
        simple = name in ("Xe tăng", "Trận địa tên lửa")
        for w in (self.classChb, self.classCbx, self.viewClassBtn, self.typeChb, self.typeCbx, self.viewTypeBtn):
            w.setVisible(not simple)
        if simple:
            page = self.tankSearchingPage if name == "Xe tăng" else self.rocketSearchingPage
        else:
            page = self.aircraftSearchingPage if name == "Máy bay" else self.shipSearchingPage
        self.stackedWidget.setCurrentWidget(page)

        db = context.database()
        query = QSqlQuery(db)
        query.prepare("select func_layid_nhomdoituong(?)")
        query.addBindValue(name)
        if not (query.exec() and query.next()):
            log.debug(query.lastError().text())
            return
        id_group = int(query.value(0))
        self.m_ido_group = make_ido("GRP", id_group)
        if simple:
            return

        from vgeoint.engine.entities import BClass

        classes = BClass.get_all(db, id_group)
        self.class_cbx_connect(False)
        self.classCbx.clear()
        for c in classes:
            self.classCbx.addItem(QIcon(":/myicon/Attachment.svg"), c.name(), c.ido())
        self.class_cbx_connect(True)
        if self.classCbx.count():
            self.class_cbx_changed(0)

    def class_cbx_changed(self, idx: int):
        if idx < 0:
            return
        ido = self.classCbx.itemData(idx) or ""
        if ido:
            from vgeoint.engine.entities import BType

            types = BType.get_all(context.database(), ido2id(ido))
            self.typeCbx.clear()
            for t in types:
                self.typeCbx.addItem(QIcon(":/myicon/Attachment.svg"), t.name(), t.ido())

    def search(self):
        widget = self.stackedWidget.currentWidget()
        if widget is self.aircraftSearchingPage:
            self.search_aircraft()
        elif widget is self.tankSearchingPage:
            self.search_tank()
        elif widget is self.rocketSearchingPage:
            self.search_rocket()
        elif widget is self.shipSearchingPage:
            self.search_ship()

    def view_group(self):
        if self.m_ido_group:
            self.view_ido.emit(self.m_ido_group)

    def view_class(self):
        ido = self.classCbx.currentData() or ""
        if ido:
            self.view_ido.emit(ido)

    def view_type(self):
        ido = self.typeCbx.currentData() or ""
        if ido:
            self.view_ido.emit(ido)

    def search_aircraft(self):
        self._search(self.aircraftSearchingPage, _AIRCRAFT_SQL, with_class_type=True)

    def search_tank(self):
        self._search(self.tankSearchingPage, _TANK_SQL)

    def search_rocket(self):
        self._search(self.rocketSearchingPage, _ROCKET_SQL)

    def search_ship(self):
        self._search(self.shipSearchingPage, _SHIP_SQL, with_class_type=True)

    def _search(self, page, cmd: str, with_class_type: bool = False):
        result, where_str = page.get_where_str()
        if not result:
            QMessageBox.warning(self, "Tìm kiếm đối tượng", "Chưa nhập hoặc nhập tham số không hợp lệ")
            log.debug(where_str)
            return
        if where_str:
            cmd += " and " + where_str
        if with_class_type:
            id_type = ido2id(self.typeCbx.currentData() or "")
            if self.typeChb.isChecked() and id_type > 0:
                cmd += f" and tbl_kieudoituong.id = {id_type}"
            id_class = ido2id(self.classCbx.currentData() or "")
            if self.classChb.isChecked() and id_class > 0:
                cmd += f" and tbl_loaidoituong.id = {id_class}"

        query = QSqlQuery(context.database())
        if query.exec(cmd):
            self.searching_complete.emit(query)
        else:
            log.debug(query.lastError().text())

    def class_cbx_connect(self, value: bool):
        if value:
            self.classCbx.currentIndexChanged.connect(self.class_cbx_changed)
        else:
            try:
                self.classCbx.currentIndexChanged.disconnect(self.class_cbx_changed)
            except TypeError:
                pass  # chưa kết nối (lần gọi đầu tiên)

    def create_connections(self):
        self.searchBtn.clicked.connect(self.search)
        self.viewGroupBtn.clicked.connect(self.view_group)
        self.viewClassBtn.clicked.connect(self.view_class)
        self.viewTypeBtn.clicked.connect(self.view_type)
