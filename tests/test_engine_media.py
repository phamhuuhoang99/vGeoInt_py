"""vGeoEngine media input/viewer, attribute and searching widgets (real PostgreSQL via Docker for DB tests)."""

import itertools
from pathlib import Path

import pytest

_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    import uuid

    return f"{prefix}_{next(_counter)}_{uuid.uuid4().hex[:6]}"


def _write_image(path: Path, color: str = "red", size=(40, 30)) -> str:
    from qgis.PyQt.QtGui import QColor, QImage

    img = QImage(size[0], size[1], QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert img.save(str(path))
    return path.as_posix()


@pytest.fixture
def drive(tmp_path, monkeypatch, qgis_app):
    """Isolate DriveSearching settings and make its label the drive of tmp_path ("C:/")."""
    from vgeoint.engine import drive_searching
    from vgeoint.engine.drive_searching import DriveSearching

    monkeypatch.setattr(drive_searching, "SETTINGS_SCOPE", ("DMA_test", "vGeoEngine_drive_test"))
    label = tmp_path.drive + "/" if tmp_path.drive else "/"
    DriveSearching.set_disk_label(label)
    return label


def _seed_object(db, group: str, code: str, with_class: bool = True) -> tuple[str, str, str]:
    """Create class/type (if any) and an object under `group`; return (ido, name, ido of its classification)."""
    from vgeoint.engine.defines import make_ido
    from vgeoint.engine.entities import BClass, BObjectAbstract, BType, exec_query

    q = exec_query(db, "select func_layid_nhomdoituong(?::text)", group)
    assert q is not None and q.next()
    id_group = int(q.value(0))
    if with_class:
        class_name, type_name = _unique("Loai"), _unique("Kieu")
        BClass.add(db, class_name, id_group)
        cls = next(c for c in BClass.get_all(db, id_group) if c.name() == class_name)
        BType.add(db, type_name, int(cls.ido()[3:]))
        typ = next(t for t in BType.get_all(db, int(cls.ido()[3:])) if t.name() == type_name)
        ido_phl = typ.ido()
    else:
        ido_phl = make_ido("GRP", id_group)
    name = _unique("Obj")
    BObjectAbstract.add(db, name, ido_phl)
    q = exec_query(db, "select func_layid_doituong(?::text, ?::varchar)", name, ido_phl)
    assert q is not None and q.next()
    return make_ido(code, int(q.value(0))), name, ido_phl


# ------------------------------------------------------------------------------------------ viewers


def test_image_viewer_shows_and_zooms(qgis_app, qtbot):
    from qgis.PyQt.QtCore import QPoint, QPointF, Qt
    from qgis.PyQt.QtGui import QColor, QImage, QWheelEvent
    from qgis.PyQt.QtWidgets import QGraphicsPixmapItem

    from vgeoint.engine.image_viewer_widget import ImageViewerWidget

    w = ImageViewerWidget()
    qtbot.addWidget(w)
    w.resize(200, 200)
    img = QImage(100, 50, QImage.Format.Format_RGB32)
    img.fill(QColor("blue"))
    w.set_image(img)
    items = w.scene().items()
    assert len(items) == 1 and isinstance(items[0], QGraphicsPixmapItem)
    assert w.sceneRect().width() == 100 and w.sceneRect().height() == 50
    assert w.dragMode() == w.DragMode.ScrollHandDrag

    m11 = w.transform().m11()
    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    w.wheelEvent(ev)
    assert w.transform().m11() == pytest.approx(m11 * 1.25)

    w.set_image(img)  # setImage resets the zoom and replaces the pixmap
    assert len(w.scene().items()) == 1
    assert w.transform().m11() == pytest.approx(m11)


def test_media_viewer(qgis_app, qtbot, tmp_path, monkeypatch, no_modal):
    from qgis.PyQt.QtGui import QDesktopServices
    from qgis.PyQt.QtWidgets import QMessageBox

    from vgeoint.engine.media_viewer_widget import MediaViewerWidget

    w = MediaViewerWidget()
    qtbot.addWidget(w)
    w.view_image(_write_image(tmp_path / "a.png"))
    assert w.stackedWidget.currentWidget() is w.imageViewer
    assert w.imageViewer.sceneRect().width() == 40

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[1:]))
    w.view_image(str(tmp_path / "missing.png"))
    assert warnings == [("Lỗi xem ảnh", "Ảnh không tồn tại hoặc bị lỗi.")]

    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    w.view_video("C:/x/v.mp4")
    w.view_document("C:/x/d.pdf")
    assert opened == ["C:/x/v.mp4", "C:/x/d.pdf"]


def test_widgets_registry_resolves_my_classes(qgis_app):
    from vgeoint.common.ui import load_ui_class
    from vgeoint.engine import widgets

    for name in ("MediaViewerWidget", "SearchingWidget", "MediaInputWidget"):
        load_ui_class("engine", name)
    for name in ("ImageViewerWidget", "AircraftAttributeWidget", "RocketSearchingWidget", "MediaInputWidget"):
        assert getattr(widgets, name).__name__ == name


# ------------------------------------------------------------------------------ attribute widgets


def test_aircraft_attribute_widget_round_trip(qgis_app, qtbot):
    from vgeoint.engine.attribute_widgets import AircraftAttributeWidget
    from vgeoint.engine.entities import Aircraft

    w = AircraftAttributeWidget()
    qtbot.addWidget(w)
    a = Aircraft()
    a.set_name("Su-30")
    a.chieu_dai_than, a.sai_canh, a.chieu_cao, a.dong_co = 21.9, 14.7, 6.4, "AL-31F"
    a.vmax, a.hmax, a.tam_bay_max, a.ban_kinh_hd, a.nuoc_sx = 2120, 17300, 3000, 1500, "Nga"
    w.view(a)
    assert w.tenLed.text() == "Su-30"
    w.dongCoLed.setText("  AL-31FP  ")
    b = Aircraft()
    w.get_attrib(b)
    assert (b.chieu_dai_than, b.sai_canh, b.chieu_cao, b.dong_co) == (21.9, 14.7, 6.4, "AL-31FP")
    assert (b.vmax, b.hmax, b.tam_bay_max, b.ban_kinh_hd, b.nuoc_sx) == (2120, 17300, 3000, 1500, "Nga")

    w.setEnabled(False)
    assert not w.tenLed.isEnabled() and not w.nuocSxLed.isEnabled()
    w.setEnabled(True)
    assert w.vmaxDspb.isEnabled()


def test_ship_tank_rocket_attribute_widgets(qgis_app, qtbot):
    from vgeoint.engine.attribute_widgets import RocketAttributeWidget, ShipAttributeWidget, TankAttributeWidget
    from vgeoint.engine.entities import Rocket, Ship, Tank

    s = Ship()
    s.set_name("Tau")
    s.chieu_dai, s.chieu_rong, s.mom_nuoc, s.tai_trong, s.dong_co = 95.5, 15.25, 4.5, 30, "Diesel"  # .ui giữ phạm vi mặc định (<= 99.99)
    s.chan_vit, s.cong_suat, s.toc_do, s.tam_hoat_dong, s.thuy_thu_doan, s.nuoc_so_huu = 2, 80, 30.5, 40, 99, "VN"
    sw = ShipAttributeWidget()
    qtbot.addWidget(sw)
    sw.view(s)
    s2 = Ship()
    sw.get_attrib(s2)
    keys = ("chieu_dai", "chieu_rong", "mom_nuoc", "tai_trong", "dong_co", "chan_vit", "cong_suat", "toc_do",
            "tam_hoat_dong", "thuy_thu_doan", "nuoc_so_huu")
    assert all(getattr(s2, k) == getattr(s, k) for k in keys)
    sw.setEnabled(False)
    assert not sw.chanVitSpb.isEnabled()
    sw.setEnabled(True)
    assert sw.chanVitSpb.isEnabled() and not sw.tenLed.isEnabled()  # như C++: không đụng tới tenLed (tắt trong .ui)

    t = Tank()
    t.set_name("T-90")
    t.chieu_dai, t.chieu_rong, t.tai_trong, t.nuoc_so_huu = 9.6, 3.8, 46.5, "Nga"
    tw = TankAttributeWidget()
    qtbot.addWidget(tw)
    tw.view(t)
    assert tw.tenLed.text() == "T-90"
    t2 = Tank()
    tw.get_attrib(t2)
    assert (t2.chieu_dai, t2.chieu_rong, t2.tai_trong, t2.nuoc_so_huu) == (9.6, 3.8, 46.5, "Nga")

    r = Rocket()
    r.set_name("S-300")
    r.so_be, r.so_xe_rada, r.so_xe_chi_huy, r.duong_kinh, r.nuoc_so_huu = 4, 2, 1, 0.5, "Nga"
    rw = RocketAttributeWidget()
    qtbot.addWidget(rw)
    rw.view(r)
    r2 = Rocket()
    rw.get_attrib(r2)
    assert (r2.so_be, r2.so_xe_rada, r2.so_xe_chi_huy, r2.duong_kinh, r2.nuoc_so_huu) == (4, 2, 1, 0.5, "Nga")


# ------------------------------------------------------------------------------ searching widgets


def test_object_searching_where_str(qgis_app, qtbot):
    from vgeoint.engine.object_searching_widgets import (
        AircraftSearchingWidget,
        RocketSearchingWidget,
        ShipSearchingWidget,
        TankSearchingWidget,
    )

    a = AircraftSearchingWidget()
    qtbot.addWidget(a)
    assert a.tenChb.isChecked()  # mặc định trong .ui
    assert a.get_where_str() == (False, "(tbl_doituong.ten ilike '%%')")
    a.tenChb.setChecked(False)
    assert a.get_where_str() == (True, "")
    a.tenChb.setChecked(True)
    a.tenLed.setText(" Su'30 ")
    a.vmaxChb.setChecked(True)
    a.vmaxLed.setText("2000")
    a.vmaxDspb.setValue(100.5)
    a.nuocSanXuatChb.setChecked(True)
    a.nuocSxLed.setText("Nga")
    ok, where = a.get_where_str()
    assert ok
    assert where == (
        "(tbl_doituong.ten ilike '%Su''30%')"
        " and (1899.5 <= tbl_maybay.vmax and tbl_maybay.vmax <= 2100.5)"
        " and (tbl_maybay.nuoc_sanxuat ilike '%Nga%')"
    )
    a.vmaxLed.setText("20.5")  # QString::toInt fails on decimals
    assert a.get_where_str()[0] is False
    a.vmaxLed.setText("2000")
    a.tenLed.setText("  ")
    assert a.get_where_str()[0] is False

    s = ShipSearchingWidget()
    qtbot.addWidget(s)
    s.tenChb.setChecked(False)
    s.chanVitChb.setChecked(True)
    s.chanVitLed.setText("2")
    s.chanVitSpb.setValue(1)
    s.nuocSoHuuChb.setChecked(True)
    s.nuocSoHuuLed.setText("VN")
    assert s.get_where_str() == (
        True,
        "(1 <= tbl_tauthuyen.chanvit and tbl_tauthuyen.chanvit <= 3) and (tbl_tauthuyen.nuocsohuu ilike '%VN%')",
    )

    t = TankSearchingWidget()
    qtbot.addWidget(t)
    t.tenChb.setChecked(False)
    t.taiTrongChb.setChecked(True)
    t.taiTrongLed.setText("abc")
    ok, where = t.get_where_str()
    assert not ok and where == "(0 <= tbl_xetang.taitrong and tbl_xetang.taitrong <= 0)"

    r = RocketSearchingWidget()
    qtbot.addWidget(r)
    r.tenChb.setChecked(False)
    r.soBeChb.setChecked(True)
    r.soBeLed.setText("4")
    assert r.get_where_str() == (True, "(4 <= tbl_trandiatenlua.so_be and tbl_trandiatenlua.so_be <= 4)")


def _rows(query, n):
    rows = []
    while query.next():
        rows.append(tuple(query.value(i) for i in range(n)))
    return rows


def test_searching_widget_aircraft(engine, qtbot, monkeypatch):
    from vgeoint.engine.entities import Aircraft
    from vgeoint.engine.searching_widget import SearchingWidget

    ido, name, ido_type = _seed_object(engine, "Máy bay", "MBA")
    a = Aircraft()
    a.set_ido(ido)
    a.vmax, a.nuoc_sx = 2500, "Nga"
    a.auto_insert(engine)
    other_ido, other_name, _ = _seed_object(engine, "Máy bay", "MBA")
    b = Aircraft()
    b.set_ido(other_ido)
    b.vmax = 900
    b.auto_insert(engine)

    w = SearchingWidget()
    qtbot.addWidget(w)
    w.set_group_name("Máy bay")
    assert w.titleLbl.text() == "Máy bay"
    assert w.stackedWidget.currentWidget() is w.aircraftSearchingPage
    assert not w.classCbx.isHidden() and w.classCbx.count() >= 2
    assert w.m_ido_group.startswith("GRP")

    results = []
    w.searching_complete.connect(lambda q: results.append(_rows(q, 4)))
    page = w.aircraftSearchingPage
    page.tenChb.setChecked(False)
    page.vmaxChb.setChecked(True)
    page.vmaxLed.setText("2400")
    page.vmaxDspb.setValue(200)
    w.searchBtn.click()
    names = [r[1] for r in results[-1]]
    assert name in names and other_name not in names

    # Lọc theo loại/kiểu: chọn loại của đối tượng thứ nhất
    page.vmaxChb.setChecked(False)
    page.tenChb.setChecked(True)
    page.tenLed.setText("Obj_")
    from vgeoint.engine.entities import BType

    idx = next(i for i in range(w.classCbx.count())
               if any(t.ido() == ido_type for t in BType.get_all(engine, int(w.classCbx.itemData(i)[3:]))))
    w.classCbx.setCurrentIndex(idx)
    w.classChb.setChecked(True)
    w.typeChb.setChecked(True)
    w.typeCbx.setCurrentIndex(w.typeCbx.findData(ido_type))
    w.search()
    assert [r[1] for r in results[-1]] == [name]

    viewed = []
    w.view_ido.connect(viewed.append)
    w.viewGroupBtn.click()
    w.viewClassBtn.click()
    w.viewTypeBtn.click()
    assert viewed == [w.m_ido_group, w.classCbx.currentData(), ido_type]

    # Tham số không hợp lệ -> cảnh báo, không tìm
    from qgis.PyQt.QtWidgets import QMessageBox

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[1:]))
    page.tenLed.setText("")
    n = len(results)
    w.search()
    assert len(results) == n
    assert warned == [("Tìm kiếm đối tượng", "Chưa nhập hoặc nhập tham số không hợp lệ")]


def test_searching_widget_tank_and_rocket(engine, qtbot, no_modal):
    from vgeoint.engine.entities import Rocket, Tank
    from vgeoint.engine.searching_widget import SearchingWidget

    tank_ido, tank_name, _ = _seed_object(engine, "Xe tăng", "XET", with_class=False)
    t = Tank()
    t.set_ido(tank_ido)
    t.nuoc_so_huu = "Nước'X"
    t.auto_insert(engine)
    rocket_ido, rocket_name, _ = _seed_object(engine, "Trận địa tên lửa", "TTL", with_class=False)
    r = Rocket()
    r.set_ido(rocket_ido)
    r.so_be = 6
    r.auto_insert(engine)

    w = SearchingWidget()
    qtbot.addWidget(w)
    results = []
    w.searching_complete.connect(lambda q: results.append(_rows(q, 3)))

    w.set_group_name("Xe tăng")
    assert w.stackedWidget.currentWidget() is w.tankSearchingPage
    assert w.classCbx.isHidden() and w.typeChb.isHidden()
    w.tankSearchingPage.tenChb.setChecked(False)
    w.tankSearchingPage.nuocSoHuuChb.setChecked(True)
    w.tankSearchingPage.nuocSoHuuLed.setText("nước'x")
    w.search()
    assert [(r[1], r[2]) for r in results[-1]] == [(tank_name, "Nước'X")]

    w.set_group_name("Trận địa tên lửa")
    assert w.stackedWidget.currentWidget() is w.rocketSearchingPage
    page = w.rocketSearchingPage
    page.tenChb.setChecked(False)
    page.soBeChb.setChecked(True)
    page.soBeLed.setText("6")
    w.search()
    assert rocket_name in [r[1] for r in results[-1]]


# ------------------------------------------------------------------------------ media input widget


def _media_folder(root: Path) -> tuple[list[str], list[str], list[str]]:
    images = [_write_image(root / "1_Anh" / "a.png", "red"), _write_image(root / "1_Anh" / "b.jpg", "green")]
    (root / "2_Video").mkdir()
    (root / "2_Video" / "clip.mp4").write_bytes(b"\0" * 10)
    (root / "3_HuongDan").mkdir()
    (root / "3_HuongDan" / "doc.pdf").write_bytes(b"%PDF")
    return images, [(root / "2_Video" / "clip.mp4").as_posix()], [(root / "3_HuongDan" / "doc.pdf").as_posix()]


def _texts(lwg):
    return [lwg.item(i).text() for i in range(lwg.count())]


def test_media_input_round_trip(engine, qtbot, tmp_path, drive, no_modal):
    from vgeoint.engine.media_input_widget import MediaInputWidget

    ido, name, _ = _seed_object(engine, "Máy bay", "MBA")
    root = tmp_path / _unique("media")
    root.mkdir()
    images, videos, docs = _media_folder(root)

    w = MediaInputWidget()
    qtbot.addWidget(w)
    w.view_media(ido)
    assert w.titleLbl.text() == name
    assert w.tabWidget.indexOf(w.attribTab) == 0
    assert w.stackedWidget.currentWidget() is w.mbaPage
    assert w.imageLwg.count() == 0

    assert w.load_from_folder(root.as_posix())
    assert w.noticeLbl.text() == "Nhấn xác nhận để lưu thay đổi"
    assert _texts(w.imageLwg) == images and _texts(w.videoLwg) == videos and _texts(w.docLwg) == docs
    assert w.tabWidget.tabText(w.tabWidget.indexOf(w.imageTab)) == "*Hình ảnh"
    w.notePte.setPlainText("Ghi chú thử")
    w.mbaWidget.vmaxDspb.setValue(2120)
    w.mbaWidget.nuocSxLed.setText("Nga")
    w.apply()
    assert w.noticeLbl.text() == "<font color='green'>Cập nhật thành công.</font>"
    assert not w.m_changed

    w2 = MediaInputWidget()
    qtbot.addWidget(w2)
    w2.view_media(ido)
    assert sorted(_texts(w2.imageLwg)) == sorted(images)
    assert _texts(w2.videoLwg) == videos and _texts(w2.docLwg) == docs
    assert all(int(w2.imageLwg.item(i).data(256)) > 0 for i in range(w2.imageLwg.count()))
    assert w2.imageLwg.item(0).toolTip() == w2.imageLwg.item(0).text()
    assert w2.notePte.toPlainText() == "Ghi chú thử"
    assert w2.tabWidget.tabText(w2.tabWidget.indexOf(w2.noteTab)) == "*Ghi chú"
    assert w2.mbaWidget.vmaxDspb.value() == 2120 and w2.mbaWidget.nuocSxLed.text() == "Nga"
    assert w2.mbaWidget.tenLed.text() == name
    # thumbnails (base64 jpg) round-trip
    assert all(img.thumbnail() and not w2.imageLwg.item(0).icon().isNull() for img in w2.m_images)

    # Remove one image + the video, then apply
    w2.tabWidget.setCurrentWidget(w2.imageTab)
    w2.imageLwg.setCurrentRow(0)
    removed = w2.imageLwg.currentItem().text()
    w2.remove()
    w2.tabWidget.setCurrentWidget(w2.videoTab)
    w2.videoLwg.setCurrentRow(0)
    w2.removeBtn.click()
    w2.apply()

    w3 = MediaInputWidget()
    qtbot.addWidget(w3)
    w3.view_media(ido)
    assert _texts(w3.imageLwg) == [p for p in images if p != removed]
    assert w3.videoLwg.count() == 0
    assert w3.tabWidget.tabText(w3.tabWidget.indexOf(w3.videoTab)) == "Video"
    assert _texts(w3.docLwg) == docs


def test_media_input_group_view_and_cancel(engine, qtbot, tmp_path, drive, no_modal):
    from vgeoint.engine.defines import USER
    from vgeoint.engine.media_input_widget import MediaInputWidget

    ido, _name, _ = _seed_object(engine, "Xe tăng", "XET", with_class=False)
    w = MediaInputWidget()
    qtbot.addWidget(w)
    w.view_media(ido)
    assert w.stackedWidget.currentWidget() is w.xetPage
    w.view_media(ido)  # không chèn trùng tab thuộc tính
    assert [w.tabWidget.widget(i) for i in range(w.tabWidget.count())].count(w.attribTab) == 1

    w.view_media("GRP00001")
    assert w.tabWidget.indexOf(w.attribTab) == -1
    assert w.titleLbl.text() == "Máy bay"

    # Group objects keep notes/media too
    img = _write_image(tmp_path / _unique("grp") / "g.png")
    w.add_image(img)
    w.m_changed = True
    w.notePte.setPlainText("Nhóm máy bay")
    w.apply()
    w.view_media("GRP00001")
    assert img in _texts(w.imageLwg) and w.notePte.toPlainText() == "Nhóm máy bay"

    # cancel reloads from the DB
    w.add_video("C:/x/never.mp4")
    w.m_changed = True
    w.cancel()
    assert "C:/x/never.mp4" not in _texts(w.videoLwg) and w.noticeLbl.text() == ""

    # Unreadable image is skipped with a warning
    w.add_image(str(tmp_path / "nope.png"))
    assert str(tmp_path / "nope.png") not in _texts(w.imageLwg)

    # USER mode: editing buttons hidden, double click emits view signals
    w.set_mode(USER)
    assert w.addBtn.isHidden() and w.applyBtn.isHidden() and not w.m_detail
    seen = []
    w.view_image.connect(seen.append)
    w.imageLwg.itemDoubleClicked.emit(w.imageLwg.item(0))
    w.tabWidget.setCurrentWidget(w.imageTab)
    w.imageLwg.setCurrentRow(0)
    w.set_view_btn_visible(True)
    w.viewBtn.click()
    assert seen == [w.imageLwg.item(0).toolTip()] * 2

    w.set_enabled_controls(False)
    assert not w.xetWidget.chieuDaiDspb.isEnabled() and not w.mbaWidget.vmaxDspb.isEnabled()
    w.set_enabled_controls(True)
    assert w.tauWidget.chanVitSpb.isEnabled()


def test_load_from_folder_unknown_subfolder(qgis_app, qtbot, tmp_path, drive, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox

    from vgeoint.engine.media_input_widget import MediaInputWidget

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[1:]))
    (tmp_path / "Khac").mkdir()
    w = MediaInputWidget()
    qtbot.addWidget(w)
    assert not w.load_from_folder(tmp_path.as_posix())
    assert warned == [("Tải từ folder", f"Không nhận dạng được folder:\n{tmp_path.as_posix()}/Khac")]
    assert not w.load_from_folder("")
