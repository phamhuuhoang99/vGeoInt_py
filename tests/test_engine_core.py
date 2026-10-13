"""Tests for the vGeoEngine core: defines, entities, dialogs, account/database/object-table widgets, main window."""

import pytest

from vgeoint.engine.defines import ADMIN, USER, blue, green, ido2id, make_ido, md5_hex, red


# ------------------------------------------------------------------------------------------- defines
def test_defines():
    assert make_ido("GRP", 1) == "GRP00001"
    assert make_ido("MBA", 123456) == "MBA123456"
    assert ido2id("TYP00042") == 42
    assert ido2id("") == 0
    assert (ADMIN, USER) == (1, 2)
    assert green("a") == "<font color='green'>a</font>"
    assert blue("a") == "<font color='blue'>a</font>"
    assert red("a") == "<font color='red'>a</font>"
    assert md5_hex("abc") == "900150983cd24fb0d6963f7d28e17f72"


# ------------------------------------------------------------------------------------------ entities
def _group_id(db, name):
    from vgeoint.engine.entities import BGroup

    return next(ido2id(g.ido()) for g in BGroup.get_all(db) if g.name() == name)


def test_group_class_type_crud(engine):
    from vgeoint.engine.entities import BClass, BGroup, BType

    name = "Nhóm d'Test"
    BGroup.add(engine, name)
    gid = _group_id(engine, name)
    BGroup.update(engine, gid, "Nhóm d'Test 2")
    assert any(g.name() == "Nhóm d'Test 2" for g in BGroup.get_all(engine))

    BClass.add(engine, "Loại 'A'", gid)
    classes = BClass.get_all(engine, gid)
    assert [c.name() for c in classes] == ["Loại 'A'"]
    cid = ido2id(classes[0].ido())
    assert classes[0].ido().startswith("CLS") and classes[0].id_group() == gid
    BClass.update(engine, cid, "Loại 'B'")
    assert BClass.get_all(engine, gid)[0].name() == "Loại 'B'"

    BType.add(engine, "Kiểu 'X'", cid)
    types = BType.get_all(engine, cid)
    assert [t.name() for t in types] == ["Kiểu 'X'"] and types[0].id_class() == cid
    tid = ido2id(types[0].ido())
    assert BType.get_id_class_group(engine, tid) == (cid, gid)
    assert BType.get_id_class_group(engine, 999999) is None
    BType.update(engine, tid, "Kiểu 'Y'")
    assert BType.get_all(engine, cid)[0].name() == "Kiểu 'Y'"

    BType.remove(engine, tid)
    assert BType.get_all(engine, cid) == []
    BClass.remove(engine, cid)
    assert BClass.get_all(engine, gid) == []
    BGroup.remove(engine, gid)
    assert all(g.name() != "Nhóm d'Test 2" for g in BGroup.get_all(engine))


def test_object_crud_and_attributes(engine):
    from vgeoint.engine.entities import Aircraft, BClass, BObjectAbstract, BType, Rocket, Ship, Tank

    gid = _group_id(engine, "Máy bay")
    BClass.add(engine, "Tiêm kích'", gid)
    cid = next(ido2id(c.ido()) for c in BClass.get_all(engine, gid) if c.name() == "Tiêm kích'")
    BType.add(engine, "Su-30'", cid)
    typ = next(t for t in BType.get_all(engine, cid) if t.name() == "Su-30'")

    BObjectAbstract.add(engine, "Su-30MK2 'V'", typ.ido())
    objs = BObjectAbstract.get_all(engine, typ.ido())
    assert [o.name() for o in objs] == ["Su-30MK2 'V'"]
    obj = objs[0]
    assert obj.ido().startswith("MBA")
    oid = ido2id(obj.ido())

    loaded = BObjectAbstract()
    loaded.update_from_ido(engine, obj.ido())
    assert loaded.name() == "Su-30MK2 'V'"
    assert loaded.note() == "" and loaded.images() == [] and loaded.videos() == [] and loaded.documents() == []

    a = Aircraft()
    a.set_ido(obj.ido())
    a.auto_update(engine)
    assert a.chieu_dai_than == 0 and a.nuoc_sx == ""
    a.chieu_dai_than, a.sai_canh, a.chieu_cao, a.dong_co = 21.9, 14.7, 6.4, "AL-31F 'x'"
    a.vmax, a.hmax, a.tam_bay_max, a.ban_kinh_hd, a.nuoc_sx = 2120, 17300, 3000, 1500, "Nga"
    a.auto_insert(engine)
    b = Aircraft()
    b.set_ido(obj.ido())
    b.auto_update(engine)
    assert b.chieu_dai_than == pytest.approx(21.9, rel=1e-5) and b.dong_co == "AL-31F 'x'" and b.nuoc_sx == "Nga"

    BObjectAbstract.update(engine, oid, "Su-30MK2 'W'")
    assert BObjectAbstract.get_all(engine, typ.ido())[0].name() == "Su-30MK2 'W'"
    BObjectAbstract.remove(engine, oid)
    assert BObjectAbstract.get_all(engine, typ.ido()) == []
    BType.remove(engine, ido2id(typ.ido()))
    BClass.remove(engine, cid)

    # Xe tăng / Trận địa tên lửa: objects directly under the group
    for group, cls, code in (("Xe tăng", Tank, "XET"), ("Trận địa tên lửa", Rocket, "TTL")):
        gido = make_ido("GRP", _group_id(engine, group))
        BObjectAbstract.add(engine, f"{code} 'o'", gido)
        o = next(o for o in BObjectAbstract.get_all(engine, gido) if o.name() == f"{code} 'o'")
        assert o.ido().startswith(code)
        x = cls()
        x.set_ido(o.ido())
        x.nuoc_so_huu = "Việt Nam'"
        x.auto_insert(engine)
        y = cls()
        y.set_ido(o.ido())
        y.auto_update(engine)
        assert y.nuoc_so_huu == "Việt Nam'"
        BObjectAbstract.remove(engine, ido2id(o.ido()))

    s = Ship()
    s.set_ido("TAU99999")
    s.auto_update(engine)
    assert s.chan_vit == 0 and s.dong_co == ""


def test_code_from_vn_and_media():
    from qgis.PyQt.QtGui import QColor, QImage

    from vgeoint.engine.entities import BObjectAbstract, Document, Image, Media, Video

    assert BObjectAbstract.code_from_vn("Máy bay") == "MBA"
    assert BObjectAbstract.code_from_vn("Tàu thuyền") == "TAU"
    assert BObjectAbstract.code_from_vn("abc") == "###"

    m = Media(3, "D:/data/a.jpg")
    assert m.path_without_label() == "data/a.jpg" and m.full_path() == "D:/data/a.jpg" and m.ido() == 3
    assert Media(1, "data/a.jpg").path_without_label() == "data/a.jpg"

    old = [Image(1, "C:/x/A.jpg"), Image(2, "C:/x/b.jpg")]
    now = [Image(-1, "D:/x/a.jpg"), Image(-1, "D:/x/c.jpg")]
    added, removed = Image.get_changed(old, now)
    assert [i.full_path() for i in added] == ["D:/x/c.jpg"]
    assert [i.full_path() for i in removed] == ["C:/x/b.jpg"]
    added, removed = Video.get_changed([Video(1, "C:/v.mp4")], [])
    assert added == [] and len(removed) == 1
    added, removed = Document.get_changed([], [Document(-1, "C:/d.pdf")])
    assert len(added) == 1 and removed == []

    img = QImage(100, 50, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    b64 = Image.base64_from_image(img)
    assert isinstance(b64, str) and b64
    back = Image.image_from_base64(b64)
    assert back.width() == 64 and back.height() == 64


# -------------------------------------------------------------------------------- settings / drives
@pytest.fixture(autouse=True)
def _drive_scope(monkeypatch):
    from vgeoint.engine import drive_searching

    scope = ("DMA_test", "vGeoEngine_drive_test")
    monkeypatch.setattr(drive_searching, "SETTINGS_SCOPE", scope)
    monkeypatch.setattr(drive_searching.DriveSearching, "_disk_label", "C:/")
    yield
    from qgis.core import QgsSettings

    QgsSettings(*scope).clear()


def test_drive_searching(qgis_app):
    from qgis.core import QgsSettings

    from vgeoint.engine import drive_searching
    from vgeoint.engine.drive_searching import DriveSearching

    DriveSearching.read_registered_disk_label()
    assert DriveSearching.drive_label() == "C:/"
    DriveSearching.set_disk_label("E:/")
    assert DriveSearching.drive_label() == "E:/"
    assert QgsSettings(*drive_searching.SETTINGS_SCOPE).value("DriveSearching") == "E:/"
    DriveSearching._disk_label = "C:/"
    DriveSearching.read_registered_disk_label()
    assert DriveSearching.drive_label() == "E:/"


def test_setting_dialog(qgis_app, qtbot):
    from qgis.PyQt.QtCore import QDir

    from vgeoint.engine.drive_searching import DriveSearching
    from vgeoint.engine.setting_dialog import SettingDialog

    drives = [d.path() for d in QDir.drives()]
    DriveSearching._disk_label = drives[-1]
    dlg = SettingDialog()
    qtbot.addWidget(dlg)
    dlg.show()
    assert [dlg.driveCbx.itemText(i) for i in range(dlg.driveCbx.count())] == drives
    assert dlg.driveCbx.currentText() == drives[-1]
    dlg.driveCbx.setCurrentIndex(0)
    dlg.okBtn.click()
    assert not dlg.isVisible()
    assert DriveSearching.drive_label() == drives[0]
    DriveSearching._disk_label = "X:/"
    DriveSearching.read_registered_disk_label()
    assert DriveSearching.drive_label() == drives[0]


# ------------------------------------------------------------------------------------------ accounts
def _add_account(db, name, password, permission):
    from vgeoint.engine.entities import exec_query

    query = exec_query(db, "select func_them_taikhoan(?::varchar, ?::varchar, ?::int)", name, md5_hex(password), permission)
    assert query is not None and query.next()


def _check_login(db, name, password) -> int:
    from vgeoint.engine.entities import exec_query

    query = exec_query(db, "select func_kiemtra_dangnhap(?::varchar, ?::varchar)", name, md5_hex(password))
    query.next()
    return int(query.value(0))


def _remove_account(db, name):
    from vgeoint.engine.entities import exec_query

    exec_query(db, "select func_xoa_taikhoan(?::varchar)", name)


def test_login_dialog(qgis_app, qtbot):
    from vgeoint.engine.login_dialog import LoginDialog

    dlg = LoginDialog()
    qtbot.addWidget(dlg)
    dlg.accountLed.setText("admin")
    dlg.passwordLed.setText("secret'")
    with qtbot.waitSignal(dlg.login) as blocker:
        dlg.loginBtn.click()
    assert blocker.args == ["admin", "secret'"]
    dlg.set_notice(red("x"))
    assert dlg.noticeLbl.text() == red("x")
    dlg.show()
    with qtbot.waitSignal(dlg.rejected):
        dlg.cancelBtn.click()


def test_change_password_dialog(engine, qtbot):
    from vgeoint.engine.change_password_dialog import ChangePasswordDialog

    _add_account(engine, "o'brien", "oldpass1", USER)
    try:
        dlg = ChangePasswordDialog()
        qtbot.addWidget(dlg)
        dlg.set_account("o'brien")
        dlg.passwordLed.setText("oldpass1")
        dlg.newPasswordLed.setText("short")
        dlg.repasswordLed.setText("short")
        dlg.applyBtn.click()
        assert dlg.userNoticeLbl.text() == red("Mật khẩu mới phải dài hơn 6 kí tự")
        dlg.newPasswordLed.setText("newpass1")
        dlg.repasswordLed.setText("newpass2")
        dlg.applyBtn.click()
        assert dlg.userNoticeLbl.text() == red("Mật khẩu mới nhập không giống nhau")
        dlg.repasswordLed.setText("newpass1")
        dlg.passwordLed.setText("wrong")
        dlg.applyBtn.click()
        assert dlg.userNoticeLbl.text() == red("Mật khẩu cũ không đúng")
        assert _check_login(engine, "o'brien", "oldpass1") == USER

        dlg.passwordLed.setText("oldpass1")
        dlg.applyBtn.click()
        assert dlg.userNoticeLbl.text() == green("Đổi mật khẩu thành công")
        assert _check_login(engine, "o'brien", "newpass1") == USER
        assert _check_login(engine, "o'brien", "oldpass1") == -1
    finally:
        _remove_account(engine, "o'brien")


def _rows(table):
    return [(table.item(r, 0).text(), table.item(r, 1).text()) for r in range(table.rowCount())]


def _names(table):
    return [r[0] for r in _rows(table)]


def test_account_widget(engine, qtbot, no_modal):
    from vgeoint.engine.account_widget import AccountWidget

    w = AccountWidget()
    qtbot.addWidget(w)
    assert ("admin", "Quản trị") in _rows(w.tableWidget)
    assert ("user", "Người dùng") in _rows(w.tableWidget)
    assert not w.adminAccountLed.isEnabled()

    # add
    w.addBtn.click()
    assert w.adminAccountLed.isEnabled() and not w.adminPasswordLed.isHidden()
    w.adminAccountLed.setText("abc")
    w.adminApplyBtn.click()
    assert w.adminNoticeLbl.text() == red("Tên tài khoản phải lớn hơn 4 kí tự")
    w.adminAccountLed.setText("d'artagnan")
    w.adminPasswordLed.setText("12345")
    w.adminApplyBtn.click()
    assert w.adminNoticeLbl.text() == red("Mật khẩu phải dài hơn 6 kí tự")
    w.adminPasswordLed.setText("musket1")
    w.adminRepasswordLed.setText("musket2")
    w.adminApplyBtn.click()
    assert w.adminNoticeLbl.text() == red("Mật khẩu nhập không giống nhau")
    w.adminRepasswordLed.setText("musket1")
    w.adminPermissionCbx.setCurrentIndex(1)
    w.adminApplyBtn.click()
    try:
        assert w.adminNoticeLbl.text() == green("Thêm tài khoản thành công")
        assert ("d'artagnan", "Quản trị") in _rows(w.tableWidget)
        assert _check_login(engine, "d'artagnan", "musket1") == ADMIN
        assert w.action == w.NONE and not w.adminAccountLed.isEnabled()

        # duplicate
        w.addBtn.click()
        w.adminAccountLed.setText("admin")
        w.adminPasswordLed.setText("whatever")
        w.adminRepasswordLed.setText("whatever")
        w.adminApplyBtn.click()
        assert w.adminNoticeLbl.text() == red("Tài khoản đã bị trùng")
        w.adminCancelBtn.click()
        assert w.adminNoticeLbl.text() == "" and w.action == w.NONE

        # edit: permission only, then permission + password
        w.tableWidget.setCurrentCell(_names(w.tableWidget).index("d'artagnan"), 0)
        w.editBtn.click()
        assert w.adminAccountLed.text() == "d'artagnan" and w.adminPermissionCbx.currentIndex() == 1
        assert not w.adminPasswordChbx.isHidden() and w.adminPasswordLed.isHidden()
        w.adminPermissionCbx.setCurrentIndex(0)
        w.adminApplyBtn.click()
        assert w.adminNoticeLbl.text() == green("Cập nhật tài khoản thành công")
        assert _check_login(engine, "d'artagnan", "musket1") == USER

        w.tableWidget.setCurrentCell(_names(w.tableWidget).index("d'artagnan"), 0)
        w.editBtn.click()
        w.adminPasswordChbx.setChecked(True)
        assert not w.adminPasswordLed.isHidden()
        w.adminPasswordLed.setText("athos12")
        w.adminRepasswordLed.setText("athos13")
        w.adminApplyBtn.click()
        assert w.adminNoticeLbl.text() == red("Mật khẩu mới nhập không giống nhau")
        w.adminRepasswordLed.setText("athos12")
        w.adminApplyBtn.click()
        assert _check_login(engine, "d'artagnan", "athos12") == USER

        # double click fills the form
        w.tableWidget.cellDoubleClicked.emit(_names(w.tableWidget).index("admin"), 0)
        assert w.adminAccountLed.text() == "admin" and w.adminPermissionCbx.currentIndex() == 1

        # remove
        w.tableWidget.setCurrentCell(_names(w.tableWidget).index("d'artagnan"), 0)
        w.removeBtn.click()
        assert "d'artagnan" not in _names(w.tableWidget)
        assert _check_login(engine, "d'artagnan", "athos12") == -1
    finally:
        _remove_account(engine, "d'artagnan")


# -------------------------------------------------------------------------------------- object table
def test_object_table_widget(engine, qtbot):
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtSql import QSqlQuery

    from vgeoint.engine.object_table_widget import ObjectTableWidget

    w = ObjectTableWidget()
    qtbot.addWidget(w)
    w.set_code("XET")
    assert w.table.columnCount() == 2
    assert w.table.horizontalHeaderItem(1).text() == "Nước sở hữu"
    assert w.table.horizontalHeaderItem(0).font().bold()
    w.set_code("MBA")
    assert [w.table.horizontalHeaderItem(i).text() for i in range(3)] == ["Tên", "Kiểu đối tượng", "Loại đối tượng"]

    query = QSqlQuery(engine)
    assert query.exec("select 5, 'Su-30', 'Su', 'Tiêm kích' union all select 7, 'MiG', null, 'X' order by 1")
    w.set_query_result(query)
    assert w.table.rowCount() == 2
    assert [w.table.item(0, c).text() for c in range(3)] == ["Su-30", "Su", "Tiêm kích"]
    assert w.table.item(1, 1).text() == ""

    w.table.setCurrentCell(1, 0)
    with qtbot.waitSignal(w.show_detail_object_id) as blocker:
        w.viewBtn.click()
    assert blocker.args == ["MBA00007"]
    with qtbot.waitSignal(w.show_detail_object_id) as blocker:
        w.table.cellDoubleClicked.emit(0, 1)
    assert blocker.args == ["MBA00005"]

    w.set_code("XET")
    query = QSqlQuery(engine)
    assert query.exec("select 3, 'T-90', 'Nga'")
    w.set_query_result(query)
    assert w.table.rowCount() == 1 and w.table.item(0, 1).text() == "Nga"
    assert w.table.item(0, 0).data(Qt.ItemDataRole.UserRole) == "XET00003"


# ----------------------------------------------------------------------------------------- database
USER_ROLE = 256  # Qt.ItemDataRole.UserRole


def _texts(widget):
    if hasattr(widget, "itemText"):
        return [widget.itemText(i) for i in range(widget.count())]
    return [widget.item(i).text() for i in range(widget.count())]


def _select(lwg, text):
    lwg.setCurrentRow(_texts(lwg).index(text))


def test_database_widget(engine, qtbot, no_modal, monkeypatch):
    from vgeoint.engine.database_widget import DatabaseWidget
    from vgeoint.engine.entities import BClass, BGroup

    w = DatabaseWidget()
    qtbot.addWidget(w)
    viewed = []
    monkeypatch.setattr(w.mediaInput, "view_media", viewed.append)
    monkeypatch.setattr(w.mediaInput, "clear", lambda: None)

    groups = [g.name() for g in BGroup.get_all(engine)]
    assert _texts(w.gLwg) == groups
    assert _texts(w.oGroupCbx) == groups
    assert "Xe tăng" not in _texts(w.cGroupCbx) and "Trận địa tên lửa" not in _texts(w.tGroupCbx)
    assert _texts(w.cLwg) == [c.name() for c in BClass.get_all(engine, ido2id(w.cGroupCbx.itemData(0)))]

    # groups
    w.gNameLed.setText("  Nhóm 'mới'  ")
    w.gAddBtn.click()
    assert w.gNameLed.text() == "" and "Nhóm 'mới'" in _texts(w.gLwg)
    assert "Nhóm 'mới'" in _texts(w.cGroupCbx)
    _select(w.gLwg, "Nhóm 'mới'")
    w.gEditBtn.click()
    assert w.gEditBtn.text() == "Lưu"
    w.gLwg.currentItem().setText("Nhóm 'sửa'")
    w.gEditBtn.click()
    assert w.gEditBtn.text() == "Sửa"
    assert "Nhóm 'sửa'" in [g.name() for g in BGroup.get_all(engine)]
    w.tabWidget.setCurrentWidget(w.groupTab)
    w.gViewBtn.click()
    assert viewed[-1] == w.gLwg.currentItem().data(USER_ROLE)

    # classes in the new group
    w.load_groups()
    w.cGroupCbx.setCurrentIndex(_texts(w.cGroupCbx).index("Nhóm 'sửa'"))
    assert _texts(w.cLwg) == []
    w.cNameLed.setText("Loại 'A'")
    w.cAddBtn.click()
    assert _texts(w.cLwg) == ["Loại 'A'"]
    _select(w.cLwg, "Loại 'A'")
    w.cEditBtn.click()
    w.cLwg.currentItem().setText("Loại 'B'")
    w.cEditBtn.click()
    w.c_group_cbx_changed(w.cGroupCbx.currentIndex())
    assert _texts(w.cLwg) == ["Loại 'B'"]

    # types
    w.tGroupCbx.setCurrentIndex(_texts(w.tGroupCbx).index("Nhóm 'sửa'"))
    assert _texts(w.tClassCbx) == ["Loại 'B'"] and _texts(w.tLwg) == []
    w.tNameLed.setText("Kiểu 'X'")
    w.tAddBtn.click()
    assert _texts(w.tLwg) == ["Kiểu 'X'"]
    _select(w.tLwg, "Kiểu 'X'")
    w.tEditBtn.click()
    w.tLwg.currentItem().setText("Kiểu 'W'")
    w.tEditBtn.click()
    w.t_class_cbx_changed(0)
    assert _texts(w.tLwg) == ["Kiểu 'W'"]

    # objects under a type
    w.oGroupCbx.setCurrentIndex(_texts(w.oGroupCbx).index("Nhóm 'sửa'"))
    assert not w.oTypeCbx.isHidden()
    assert _texts(w.oClassCbx) == ["Loại 'B'"] and _texts(w.oTypeCbx) == ["Kiểu 'W'"]
    w.oNameLed.setText("Đối tượng 'Z'")
    w.oAddBtn.click()
    assert _texts(w.oLwg) == ["Đối tượng 'Z'"]
    _select(w.oLwg, "Đối tượng 'Z'")
    w.oEditBtn.click()
    w.oLwg.currentItem().setText("Đối tượng 'Y'")
    w.oEditBtn.click()
    w.o_type_cbx_changed(0)
    assert _texts(w.oLwg) == ["Đối tượng 'Y'"]
    assert w.oLwg.item(0).data(USER_ROLE).startswith("###")  # code_from_vn of an unknown group name
    w.tabWidget.setCurrentWidget(w.objectTab)
    _select(w.oLwg, "Đối tượng 'Y'")
    w.oViewBtn.click()
    assert viewed[-1] == w.oLwg.item(0).data(USER_ROLE)
    w.oRemoveBtn.click()
    assert _texts(w.oLwg) == []

    # objects directly under "Xe tăng"
    w.oGroupCbx.setCurrentIndex(_texts(w.oGroupCbx).index("Xe tăng"))
    assert w.oTypeCbx.isHidden() and w.oClassCbx.isHidden()
    w.oNameLed.setText("T-90 'S'")
    w.oAddBtn.click()
    assert "T-90 'S'" in _texts(w.oLwg)
    assert w.oLwg.item(_texts(w.oLwg).index("T-90 'S'")).data(USER_ROLE).startswith("XET")
    _select(w.oLwg, "T-90 'S'")
    w.oRemoveBtn.click()
    assert "T-90 'S'" not in _texts(w.oLwg)

    # remove type, class, group
    _select(w.tLwg, "Kiểu 'W'")
    w.tRemoveBtn.click()
    assert _texts(w.tLwg) == []
    _select(w.cLwg, "Loại 'B'")
    w.cRemoveBtn.click()
    assert _texts(w.cLwg) == []
    _select(w.gLwg, "Nhóm 'sửa'")
    w.gRemoveBtn.click()
    assert "Nhóm 'sửa'" not in _texts(w.gLwg)

    w.set_mode(USER)
    assert w.gAddBtn.isHidden() and w.oRemoveBtn.isHidden() and w.tLoadFromFolderBtn.isHidden()


def test_database_widget_load_from_folder(engine, qtbot, monkeypatch, tmp_path):
    from qgis.PyQt.QtWidgets import QFileDialog

    from vgeoint.engine.database_widget import DatabaseWidget
    from vgeoint.engine.entities import BGroup

    w = DatabaseWidget()
    qtbot.addWidget(w)
    calls = []
    monkeypatch.setattr(w.mediaInput, "view_media", lambda ido: calls.append(("view", ido)))
    monkeypatch.setattr(w.mediaInput, "load_from_folder", lambda path: calls.append(("load", path)))
    folder = tmp_path / "Nhóm thư mục"
    folder.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: folder.as_posix())
    w.gLoadFromFolderBtn.click()
    assert "Nhóm thư mục" in _texts(w.gLwg)
    ido = w.gLwg.item(_texts(w.gLwg).index("Nhóm thư mục")).data(USER_ROLE)
    BGroup.remove(engine, ido2id(ido))
    assert calls == [("view", ido), ("load", folder.as_posix())]


# -------------------------------------------------------------------------------------- main window
@pytest.fixture
def main_window(engine, qtbot, no_modal):
    from vgeoint.engine.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    yield w
    w.login_dlg.close()


def test_main_window_login(main_window, engine):
    from vgeoint.engine.change_password_dialog import ChangePasswordDialog

    w = main_window
    w.show()
    assert w.login_dlg.isVisible()
    assert w.stackedWidget.currentWidget() is w.searchingPage
    w.login("admin", "wrong")
    assert w.login_dlg.noticeLbl.text() == red("Sai tên đăng nhập hoặc mật khẩu")
    assert w.login_dlg.isVisible() and w.permission == -1

    _add_account(engine, "tester'", "tester1", USER)
    try:
        w.login_dlg.accountLed.setText("tester'")
        w.login_dlg.passwordLed.setText("tester1")
        w.login_dlg.loginBtn.click()
        assert w.permission == USER and w.account == "tester'"
        assert not w.login_dlg.isVisible() and w.isVisible()  # rejected no longer closes the window
        assert w.databaseBtn.isHidden()

        w.accountBtn.click()  # a user can only change the password
        dlg = w.findChild(ChangePasswordDialog)
        assert dlg is not None and dlg.accountLed.text() == "tester'"
        dlg.close()
    finally:
        _remove_account(engine, "tester'")


def test_main_window_cancel_login_closes(main_window, qtbot):
    w = main_window
    w.show()
    w.login_dlg.cancelBtn.click()
    assert not w.isVisible()


def test_main_window_admin_pages(main_window, engine):
    w = main_window
    _add_account(engine, "boss'", "boss123", ADMIN)
    try:
        w.login("boss'", "boss123")
        assert w.permission == ADMIN and not w.databaseBtn.isHidden()
        w.accountBtn.click()
        assert w.stackedWidget.currentWidget() is w.accountPage
        w.databaseBtn.click()
        assert w.stackedWidget.currentWidget() is w.databasePage
        for btn, code in ((w.tankBtn, "XET"), (w.rocketBtn, "TTL"), (w.shipBtn, "TAU"), (w.aircraftBtn, "MBA")):
            btn.click()
            assert w.stackedWidget.currentWidget() is w.searchingPage
            assert w.objectTable._code == code
        w.infoBtn.click()
    finally:
        _remove_account(engine, "boss'")


def test_main_window_settings(main_window, qtbot):
    from vgeoint.common.defines import ENGINE_NAME
    from vgeoint.common.utils import app_settings
    from vgeoint.engine.main_window import MainWindow

    w = main_window
    w.resize(900, 650)
    w.mainSplitter.setSizes([100, 300])
    w.close()
    s = app_settings(ENGINE_NAME)
    for key in ("MainWindow/Geometry", "MainWindow/WindowState", "MediaSplitter/Geometry", "MediaSplitter/State",
                "SearchingSplitter/Geometry", "SearchingSplitter/State", "MainSplitter/Geometry", "MainSplitter/State"):
        assert s.value(key) is not None, key
    assert s.value("MainWindow/Geometry") == w.saveGeometry()
    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.mainSplitter.saveState() == s.value("MainSplitter/State") == w.mainSplitter.saveState()
    w2.login_dlg.close()
