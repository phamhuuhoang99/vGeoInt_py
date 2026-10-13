"""Port of DatabaseWidget.cpp — manage groups, classes, types and objects with their media."""

from qgis.PyQt.QtCore import QSignalBlocker, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QApplication, QComboBox, QFileDialog, QListWidget, QListWidgetItem, QMessageBox, QWidget

from vgeoint.common.ui import load_ui_class
from vgeoint.engine import context
from vgeoint.engine.defines import USER, ido2id
from vgeoint.engine.entities import BClass, BGroup, BObjectAbstract, BType

Ui_DatabaseWidget = load_ui_class("engine", "DatabaseWidget")

USER_ROLE = Qt.ItemDataRole.UserRole
EDITABLE = Qt.ItemFlag.ItemIsEditable
# Các nhóm không có loại/kiểu: đối tượng gắn trực tiếp vào nhóm
GROUPS_WITHOUT_CLASS = ("Xe tăng", "Trận địa tên lửa")


def _attachment_icon() -> QIcon:
    return QIcon(":/myicon/Attachment.svg")


def _fill_list(lwg: QListWidget, entities, icon: str = ":/myicon/Attachment.svg"):
    lwg.clear()
    for e in entities:
        item = QListWidgetItem(e.name())
        item.setIcon(QIcon(icon))
        item.setData(USER_ROLE, e.ido())
        lwg.addItem(item)


def _fill_combo(cbx: QComboBox, entities):
    cbx.clear()
    for e in entities:
        cbx.addItem(_attachment_icon(), e.name(), e.ido())


def _find_ido(lwg: QListWidget, name: str) -> str:
    for i in range(lwg.count()):
        item = lwg.item(i)
        if item.text() == name:
            return item.data(USER_ROLE)
    return ""


class DatabaseWidget(QWidget, Ui_DatabaseWidget):
    EDIT, SAVE = range(2)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.create_connections()
        self.load_groups()
        self.c_group_cbx_changed(0)
        self.t_group_cbx_changed(0)
        self.o_group_cbx_changed(0)

    def create_connections(self):
        for prefix, kind in (("g", "group"), ("c", "class"), ("t", "type"), ("o", "object")):
            getattr(self, f"{prefix}EditBtn").clicked.connect(getattr(self, f"edit_{kind}"))
            getattr(self, f"{prefix}Lwg").currentRowChanged.connect(getattr(self, f"{prefix}_current_row_changed"))
            getattr(self, f"{prefix}LoadFromFolderBtn").clicked.connect(getattr(self, f"{prefix}_load_from_folder"))
            getattr(self, f"{prefix}AddBtn").clicked.connect(lambda _=False, k=kind: getattr(self, f"add_{k}")())
            getattr(self, f"{prefix}RemoveBtn").clicked.connect(getattr(self, f"remove_{kind}"))
            getattr(self, f"{prefix}ViewBtn").clicked.connect(self.view)
            getattr(self, f"{prefix}Lwg").itemDoubleClicked.connect(self.item_double_clicked)
        self.cGroupCbx.currentIndexChanged.connect(self.c_group_cbx_changed)
        self.tGroupCbx.currentIndexChanged.connect(self.t_group_cbx_changed)
        self.tClassCbx.currentIndexChanged.connect(self.t_class_cbx_changed)
        self.oGroupCbx.currentIndexChanged.connect(self.o_group_cbx_changed)
        self.oClassCbx.currentIndexChanged.connect(self.o_class_cbx_changed)
        self.oTypeCbx.currentIndexChanged.connect(self.o_type_cbx_changed)

    # ---------------------------------------------------------------------------------------- helpers
    def _set_edit_btn(self, btn, value: int):
        if value == self.EDIT:
            btn.setText("Sửa")
            btn.setIcon(QIcon(":/myicon/Edit.svg"))
        else:
            btn.setText("Lưu")
            btn.setIcon(QIcon(":/myicon/SaveEditing.svg"))

    def set_group_edit_btn(self, value: int):
        self._set_edit_btn(self.gEditBtn, value)

    def set_class_edit_btn(self, value: int):
        self._set_edit_btn(self.cEditBtn, value)

    def set_type_edit_btn(self, value: int):
        self._set_edit_btn(self.tEditBtn, value)

    def set_object_edit_btn(self, value: int):
        self._set_edit_btn(self.oEditBtn, value)

    def _current_row_changed(self, lwg: QListWidget, btn, row: int):
        if row >= 0:
            self._set_edit_btn(btn, self.SAVE if lwg.item(row).flags() & EDITABLE else self.EDIT)

    def _edit(self, lwg: QListWidget, btn, update):
        """First click makes the current item editable ("Lưu"); second click saves the new name."""
        item = lwg.currentItem()
        if item is None:
            return
        if item.flags() & EDITABLE:
            name = item.text().strip()
            if name:
                update(context.database(), ido2id(item.data(USER_ROLE)), name)
            item.setFlags(item.flags() & ~EDITABLE)
            self._set_edit_btn(btn, self.EDIT)
            QApplication.beep()
        else:
            item.setFlags(item.flags() | EDITABLE)
            lwg.editItem(item)
            self._set_edit_btn(btn, self.SAVE)

    def _remove(self, lwg: QListWidget, title: str, remove, refresh):
        item = lwg.currentItem()
        if item is None:
            return
        if QMessageBox.question(self, title, "Bạn chắc chắn muốn xóa?") == QMessageBox.StandardButton.Yes:
            remove(context.database(), ido2id(item.data(USER_ROLE)))
            refresh()
            QApplication.beep()
            self.mediaInput.clear()

    def _load_from_folder(self, add, lwg: QListWidget):
        path = QFileDialog.getExistingDirectory(self, "Chọn folder")
        if not path:
            return
        name = path[path.rfind("/") + 1:]
        add(name)
        ido = _find_ido(lwg, name)
        if ido:
            self.mediaInput.view_media(ido)
            self.mediaInput.load_from_folder(path)

    def _objects_by_group(self) -> bool:
        """Xe tăng / Trận địa tên lửa: objects belong directly to the group (class/type combos hidden)."""
        return self.oTypeCbx.isHidden()

    def _refresh_objects(self):
        if self._objects_by_group():
            self.o_group_cbx_changed(self.oGroupCbx.currentIndex())
        else:
            self.o_type_cbx_changed(self.oTypeCbx.currentIndex())

    # ----------------------------------------------------------------------------------------- groups
    def load_groups(self):
        self.set_groups(BGroup.get_all(context.database()))

    def set_groups(self, groups: list[BGroup]):
        combos = (self.cGroupCbx, self.tGroupCbx, self.oGroupCbx)
        for c in combos:
            c.blockSignals(True)
        self.gLwg.clear()
        self.cGroupCbx.clear()
        self.tGroupCbx.clear()
        self.oGroupCbx.clear()
        for g in groups:
            item = QListWidgetItem(g.name())
            item.setIcon(_attachment_icon())
            item.setData(USER_ROLE, g.ido())
            self.gLwg.addItem(item)
            if g.name() not in GROUPS_WITHOUT_CLASS:
                self.cGroupCbx.addItem(_attachment_icon(), g.name(), g.ido())
                self.tGroupCbx.addItem(_attachment_icon(), g.name(), g.ido())
            self.oGroupCbx.addItem(_attachment_icon(), g.name(), g.ido())
        for c in combos:
            c.blockSignals(False)

    def add_group(self, name: str | None = None):
        if name is None:
            name = self.gNameLed.text().strip()
            self.gNameLed.clear()
        if not name:
            return
        BGroup.add(context.database(), name)
        self.load_groups()

    def edit_group(self):
        self._edit(self.gLwg, self.gEditBtn, BGroup.update)

    def remove_group(self):
        self._remove(self.gLwg, "Xóa nhóm đối tượng", BGroup.remove, self.load_groups)

    def g_current_row_changed(self, row: int):
        self._current_row_changed(self.gLwg, self.gEditBtn, row)

    def g_load_from_folder(self):
        self._load_from_folder(self.add_group, self.gLwg)

    # ---------------------------------------------------------------------------------------- classes
    def c_group_cbx_changed(self, idx: int):
        if idx < 0:
            return
        ido = self.cGroupCbx.itemData(idx)
        if ido:
            _fill_list(self.cLwg, BClass.get_all(context.database(), ido2id(ido)))

    def add_class(self, name: str | None = None):
        if name is None:
            name = self.cNameLed.text().strip()
            self.cNameLed.clear()
        ido = self.cGroupCbx.currentData()
        if not name or not ido:
            return
        BClass.add(context.database(), name, ido2id(ido))
        self.c_group_cbx_changed(self.cGroupCbx.currentIndex())

    def edit_class(self):
        self._edit(self.cLwg, self.cEditBtn, BClass.update)

    def remove_class(self):
        self._remove(
            self.cLwg, "Xóa loại đối tượng", BClass.remove,
            lambda: self.c_group_cbx_changed(self.cGroupCbx.currentIndex()),
        )

    def c_current_row_changed(self, row: int):
        self._current_row_changed(self.cLwg, self.cEditBtn, row)

    def c_load_from_folder(self):
        self._load_from_folder(self.add_class, self.cLwg)

    # ------------------------------------------------------------------------------------------ types
    def t_group_cbx_changed(self, idx: int):
        with QSignalBlocker(self.tClassCbx):
            if idx >= 0:
                ido = self.tGroupCbx.itemData(idx)
                if ido:
                    _fill_combo(self.tClassCbx, BClass.get_all(context.database(), ido2id(ido)))
        if self.tClassCbx.count():
            self.t_class_cbx_changed(0)
        else:
            self.tLwg.clear()

    def t_class_cbx_changed(self, idx: int):
        if idx < 0:
            return
        ido = self.tClassCbx.itemData(idx)
        if ido:
            _fill_list(self.tLwg, BType.get_all(context.database(), ido2id(ido)))

    def add_type(self, name: str | None = None):
        if name is None:
            name = self.tNameLed.text().strip()
            self.tNameLed.clear()
        ido = self.tClassCbx.currentData()
        if not name or not ido:
            return
        BType.add(context.database(), name, ido2id(ido))
        self.t_class_cbx_changed(self.tClassCbx.currentIndex())

    def edit_type(self):
        self._edit(self.tLwg, self.tEditBtn, BType.update)

    def remove_type(self):
        self._remove(
            self.tLwg, "Xóa kiểu đối tượng", BType.remove,
            lambda: self.t_class_cbx_changed(self.tClassCbx.currentIndex()),
        )

    def t_current_row_changed(self, row: int):
        self._current_row_changed(self.tLwg, self.tEditBtn, row)

    def t_load_from_folder(self):
        self._load_from_folder(self.add_type, self.tLwg)

    # ---------------------------------------------------------------------------------------- objects
    def o_group_cbx_changed(self, idx: int):
        if idx < 0:
            return
        ido = self.oGroupCbx.itemData(idx)
        by_group = self.oGroupCbx.currentText() in GROUPS_WITHOUT_CLASS
        for w in (self.oClassCbx, self.oClassLbl, self.oTypeCbx, self.oTypeLbl):
            w.setVisible(not by_group)
        if by_group:
            if ido:
                _fill_list(self.oLwg, BObjectAbstract.get_all(context.database(), ido), ":/myicon/Item.svg")
            return
        with QSignalBlocker(self.oClassCbx):
            if ido:
                _fill_combo(self.oClassCbx, BClass.get_all(context.database(), ido2id(ido)))
        if self.oClassCbx.count():
            self.o_class_cbx_changed(0)
        else:
            self.oTypeCbx.clear()
            self.oLwg.clear()

    def o_class_cbx_changed(self, idx: int):
        with QSignalBlocker(self.oTypeCbx):
            if idx >= 0:
                ido = self.oClassCbx.itemData(idx)
                if ido:
                    _fill_combo(self.oTypeCbx, BType.get_all(context.database(), ido2id(ido)))
        if self.oTypeCbx.count():
            self.o_type_cbx_changed(0)
        else:
            self.oLwg.clear()

    def o_type_cbx_changed(self, idx: int):
        if idx < 0:
            return
        ido = self.oTypeCbx.itemData(idx)
        if ido:
            _fill_list(self.oLwg, BObjectAbstract.get_all(context.database(), ido), ":/myicon/Item.svg")

    def add_object(self, name: str | None = None):
        if name is None:
            name = self.oNameLed.text().strip()
            self.oNameLed.clear()
        ido = self.oGroupCbx.currentData() if self._objects_by_group() else self.oTypeCbx.currentData()
        if not name or not ido:
            return
        BObjectAbstract.add(context.database(), name, ido)
        self._refresh_objects()

    def edit_object(self):
        self._edit(self.oLwg, self.oEditBtn, BObjectAbstract.update)

    def remove_object(self):
        self._remove(self.oLwg, "Xóa đối tượng", BObjectAbstract.remove, self._refresh_objects)

    def o_current_row_changed(self, row: int):
        self._current_row_changed(self.oLwg, self.oEditBtn, row)

    def o_load_from_folder(self):
        self._load_from_folder(self.add_object, self.oLwg)

    # ------------------------------------------------------------------------------------------- view
    def item_double_clicked(self, item: QListWidgetItem | None):
        """g/c/t/oItemDoubleClicked: show the media of the item."""
        if item is None:
            return
        self.mediaInput.view_media(item.data(USER_ROLE))

    def view(self):
        lwg = {self.groupTab: self.gLwg, self.classTab: self.cLwg, self.typeTab: self.tLwg, self.objectTab: self.oLwg}
        current = self.tabWidget.currentWidget()
        for tab, widget in lwg.items():
            if tab is current:
                self.item_double_clicked(widget.currentItem())

    def set_mode(self, mode: int):
        self.mediaInput.set_mode(mode)
        if mode == USER:
            for prefix in "gcto":
                for suffix in ("LoadFromFolderBtn", "Lbl", "NameLed", "AddBtn", "EditBtn", "RemoveBtn"):
                    getattr(self, f"{prefix}{suffix}").setVisible(False)
