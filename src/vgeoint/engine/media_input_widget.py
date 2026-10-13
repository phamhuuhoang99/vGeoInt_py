"""Port of MediaInputWidget.cpp."""

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QDir, QSize, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QCursor, QIcon, QImage, QPixmap
from qgis.PyQt.QtWidgets import (
    QApplication,
    QFileDialog,
    QListView,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QWidget,
)

from vgeoint.catalog.explorer import show_in_explorer
from vgeoint.common.ui import load_ui_class
from vgeoint.engine import context
from vgeoint.engine.defines import USER, green
from vgeoint.engine.drive_searching import DriveSearching
from vgeoint.engine.entities import (
    Aircraft,
    BObjectAbstract,
    Document,
    Image,
    Rocket,
    Ship,
    Tank,
    Video,
    exec_query,
)

Ui_MediaInputWidget = load_ui_class("engine", "MediaInputWidget")

USER_ROLE = Qt.ItemDataRole.UserRole
CHANGED_NOTICE = "Nhấn xác nhận để lưu thay đổi"


def _files_in(folder: str) -> list[str]:
    d = QDir(folder)
    d.setFilter(QDir.Filter.Files | QDir.Filter.NoDotAndDotDot | QDir.Filter.NoSymLinks)
    return d.entryList()


class MediaInputWidget(QWidget, Ui_MediaInputWidget):
    view_image = pyqtSignal(str)
    view_video = pyqtSignal(str)
    view_document = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.m_detail = True
        self.m_changed = False
        self.m_ido = ""
        self.m_name = ""
        self.m_note = ""
        self.m_code = ""
        self.m_images: list[Image] = []
        self.m_videos: list[Video] = []
        self.m_documents: list[Document] = []
        self.set_detail(True)
        self.m_attrib_tab = self.attribTab
        self.viewBtn.setVisible(False)
        self.imageLwg.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        for lwg in (self.videoLwg, self.docLwg):
            lwg.setIconSize(QSize(32, 32))
            lwg.setGridSize(QSize(40, 40))
        self.create_connections()
        DriveSearching.read_registered_disk_label()

    def clear(self):
        self.imageLwg.clear()
        self.videoLwg.clear()
        self.docLwg.clear()
        self.notePte.clear()

    def set_enabled_controls(self, value):
        for w in (self.mbaWidget, self.xetWidget, self.ttlWidget, self.tauWidget):
            w.setEnabled(bool(value))

    def set_view_btn_visible(self, value: bool):
        self.viewBtn.setVisible(value)

    def set_mode(self, mode: int):
        if mode != USER:
            return
        self.set_detail(False)
        for btn in (self.loadFromFolderBtn, self.addBtn, self.removeBtn, self.applyBtn, self.cancelBtn):
            btn.setVisible(False)
        for lwg, signal in ((self.imageLwg, self.view_image), (self.videoLwg, self.view_video), (self.docLwg, self.view_document)):
            lwg.itemDoubleClicked.connect(lambda item, s=signal: item and s.emit(item.toolTip()))

    def set_detail(self, detail: bool):
        self.m_detail = detail
        if self.m_detail:
            self.imageLwg.setViewMode(QListView.ViewMode.ListMode)
            self.imageLwg.setIconSize(QSize(32, 32))
            self.imageLwg.setGridSize(QSize(40, 40))
        else:
            self.imageLwg.setViewMode(QListView.ViewMode.IconMode)
            self.imageLwg.setIconSize(QSize(80, 80))
            self.imageLwg.setGridSize(QSize(100, 100))

    def _update_tab_star(self, tab, filled: bool, text: str):
        self.tabWidget.setTabText(self.tabWidget.indexOf(tab), ("*" if filled else "") + text)

    def _set_media(self, lwg, medias, icon_for):
        lwg.clear()
        label = DriveSearching.drive_label()
        for m in medias:
            path = label + m.path_without_label()
            item = QListWidgetItem(icon_for(m), path, lwg)
            item.setData(USER_ROLE, m.ido())
            item.setToolTip(path)

    def set_images(self, images: list[Image]):
        def icon(img):
            qimg = Image.image_from_base64(img.thumbnail())
            scaled = qimg.scaled(80, 80, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            return QIcon(QPixmap.fromImage(scaled))

        self._set_media(self.imageLwg, images, icon)
        self._update_tab_star(self.imageTab, self.imageLwg.count() > 0, "Hình ảnh")

    def set_videos(self, videos: list[Video]):
        self._set_media(self.videoLwg, videos, lambda _v: QIcon(":/myicon/Video.svg"))
        self._update_tab_star(self.videoTab, self.videoLwg.count() > 0, "Video")

    def set_documents(self, documents: list[Document]):
        self._set_media(self.docLwg, documents, lambda _d: QIcon(":/myicon/Document.svg"))
        self._update_tab_star(self.docTab, self.docLwg.count() > 0, "Tài liệu")

    def set_note(self, note: str):
        self.notePte.setPlainText(note)
        self._update_tab_star(self.noteTab, bool(note), "Ghi chú")

    def set_notice(self, notice: str):
        self.noticeLbl.setText(notice)

    def set_title(self, title: str):
        self.titleLbl.setText(title)

    def view_media(self, ido: str):
        self.m_changed = False
        self.set_notice("")

        self.m_ido = ido
        self.m_code = ido[:3]
        if self.m_code in ("GRP", "CLS", "TYP", "###"):
            self.tabWidget.removeTab(self.tabWidget.indexOf(self.m_attrib_tab))
            self.view_object(ido)
            return
        # C++ chèn lại tab mỗi lần gọi; chỉ chèn khi chưa có để không bị trùng tab
        if self.tabWidget.indexOf(self.m_attrib_tab) < 0:
            self.tabWidget.insertTab(0, self.m_attrib_tab, "Thuộc tính")
        if self.m_code == "MBA":
            self.view_aircraft(ido)
        elif self.m_code == "XET":
            self.view_tank(ido)
        elif self.m_code == "TTL":
            self.view_rocket(ido)
        elif self.m_code == "TAU":
            self.view_ship(ido)

    def images(self) -> list[Image]:
        imgs = []
        for i in range(self.imageLwg.count()):
            item = self.imageLwg.item(i)
            id_ = int(item.data(USER_ROLE) or 0)
            if id_ > 0:
                imgs.append(Image(id_, item.text()))
                continue
            img = QImage()
            if img.load(item.text()):
                imgs.append(Image(id_, item.text(), Image.base64_from_image(img)))
            else:
                QMessageBox.warning(None, "Lưu hình ảnh", f"Hình ảnh bị bỏ qua vì không thể đọc: {item.text()}")
        return imgs

    def videos(self) -> list[Video]:
        return [
            Video(int(self.videoLwg.item(i).data(USER_ROLE) or 0), self.videoLwg.item(i).text())
            for i in range(self.videoLwg.count())
        ]

    def documents(self) -> list[Document]:
        return [
            Document(int(self.docLwg.item(i).data(USER_ROLE) or 0), self.docLwg.item(i).text())
            for i in range(self.docLwg.count())
        ]

    def add(self):
        # Kiểm tra tab nào đang focus
        widget = self.tabWidget.currentWidget()
        if widget is self.imageTab:
            for file_name in QFileDialog.getOpenFileNames(self, "Chọn ảnh")[0]:
                self.add_image(file_name)
        elif widget is self.videoTab:
            for file_name in QFileDialog.getOpenFileNames(self, "Chọn video")[0]:
                self.add_video(file_name)
        elif widget is self.docTab:
            for file_name in QFileDialog.getOpenFileNames(self, "Chọn tài liệu")[0]:
                self.add_document(file_name)
        self.m_changed = True
        self.set_notice(CHANGED_NOTICE)

    def _current_list(self):
        widget = self.tabWidget.currentWidget()
        for tab, lwg in ((self.imageTab, self.imageLwg), (self.videoTab, self.videoLwg), (self.docTab, self.docLwg)):
            if widget is tab:
                return lwg
        return None

    def remove(self):
        lwg = self._current_list()
        if lwg is not None and lwg.currentItem() is not None:
            lwg.takeItem(lwg.row(lwg.currentItem()))
        self.m_changed = True
        self.set_notice(CHANGED_NOTICE)

    def apply(self):
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            self._apply()
        finally:
            QApplication.restoreOverrideCursor()
        self.m_changed = False
        QApplication.beep()
        self.set_notice(green("Cập nhật thành công."))
        QTimer.singleShot(2500, self._clear_notice)

    def _clear_notice(self):
        if not sip.isdeleted(self):
            self.set_notice("")

    def _apply(self):
        db = context.database()
        ido = self.m_ido
        if self.m_changed:
            added_image, removed_image = Image.get_changed(self.m_images, self.images())
            added_video, removed_video = Video.get_changed(self.m_videos, self.videos())
            added_doc, removed_doc = Document.get_changed(self.m_documents, self.documents())

            # Xóa các chi tiết Media
            for img in removed_image:
                exec_query(db, "select func_xoa_chitiet_hinhanh(?::varchar, ?::text)", ido, img.path_without_label())
            for v in removed_video:
                exec_query(db, "select func_xoa_chitiet_video(?::varchar, ?::text)", ido, v.path_without_label())
            for doc in removed_doc:
                exec_query(db, "select func_xoa_chitiet_tailieu(?::varchar, ?::text)", ido, doc.path_without_label())

            # Thêm vào bảng hình ảnh / video / tài liệu
            for img in added_image:
                exec_query(db, "select func_them_hinhanh(?::text, ?::text)", img.path_without_label(), img.thumbnail())
                img.set_ido(self._scalar_int(db, "select func_layid_hinhanh(?::text)", img.path_without_label()))
            for v in added_video:
                exec_query(db, "select func_them_video(?::text, ?::text)", v.path_without_label(), v.thumbnail())
                v.set_ido(self._scalar_int(db, "select func_layid_video(?::text)", v.path_without_label()))
            for doc in added_doc:
                exec_query(db, "select func_them_tailieu(?::text)", doc.path_without_label())
                doc.set_ido(self._scalar_int(db, "select func_layid_tailieu(?::text)", doc.path_without_label()))

            # Thêm vào bảng chi tiết hình ảnh / video / tài liệu
            for img in added_image:
                exec_query(db, "select func_them_chitiet_hinhanh(?::varchar, ?::int)", ido, img.ido())
            for v in added_video:
                exec_query(db, "select func_them_chitiet_video(?::varchar, ?::int)", ido, v.ido())
            for doc in added_doc:
                exec_query(db, "select func_them_chitiet_tailieu(?::varchar, ?::int)", ido, doc.ido())

        exec_query(db, "select func_sua_ghichu(?::varchar, ?::text)", ido, self.notePte.toPlainText())

        if self.tabWidget.indexOf(self.m_attrib_tab) >= 0:
            pair = {
                "MBA": (Aircraft, self.mbaWidget),
                "XET": (Tank, self.xetWidget),
                "TTL": (Rocket, self.ttlWidget),
                "TAU": (Ship, self.tauWidget),
            }.get(self.m_code)
            if pair is not None:
                obj = pair[0]()
                pair[1].get_attrib(obj)
                obj.set_ido(ido)
                obj.auto_insert(db)

    @staticmethod
    def _scalar_int(db, sql: str, value: str) -> int:
        query = exec_query(db, sql, value)
        if query is not None and query.next():
            return int(query.value(0))
        return 0

    def cancel(self):
        if self.m_changed:
            self.view_media(self.m_ido)
        self.m_changed = False
        self.set_notice("")

    def open_explorer(self, path: str | None = None):
        if path is None:
            lwg = self._current_list()
            if lwg is not None and lwg.currentItem() is not None:
                show_in_explorer(lwg.currentItem().toolTip())
            return
        show_in_explorer(path)

    def view(self):
        widget = self.tabWidget.currentWidget()
        for tab, lwg, signal in (
            (self.imageTab, self.imageLwg, self.view_image),
            (self.videoTab, self.videoLwg, self.view_video),
            (self.docTab, self.docLwg, self.view_document),
        ):
            if widget is tab:
                item = lwg.currentItem()
                if item is not None:
                    signal.emit(item.toolTip())

    def load_from_folder(self, path: str | None = None) -> bool:
        """C++ slot loadFromFolder() (asks for the folder) and loadFromFolder(path)."""
        if path is None:
            path = QFileDialog.getExistingDirectory(self, "Chọn folder")
        if not path:
            return False

        ok = False
        d = QDir(path)
        d.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.NoSymLinks)
        for sub in d.entryList():
            lower = sub.lower()
            if lower == "1_anh":
                self.add_image_from_folder(f"{path}/1_Anh")
                ok = True
            elif lower == "2_video":
                self.add_video_from_folder(f"{path}/2_Video")
                ok = True
            elif lower == "3_huongdan":
                self.add_document_from_folder(f"{path}/3_HuongDan")
                ok = True
            else:
                QMessageBox.warning(self, "Tải từ folder", f"Không nhận dạng được folder:\n{path}/{sub}")

        self._update_tab_star(self.imageTab, self.imageLwg.count() > 0, "Hình ảnh")
        self._update_tab_star(self.videoTab, self.videoLwg.count() > 0, "Video")
        self._update_tab_star(self.docTab, self.docLwg.count() > 0, "Tài liệu")
        self._update_tab_star(self.noteTab, bool(self.notePte.toPlainText()), "Ghi chú")

        if ok:
            self.m_changed = True
            self.set_notice(CHANGED_NOTICE)
        return ok

    def _show(self, obj: BObjectAbstract):
        self.m_ido = obj.ido()
        self.m_name = obj.name()
        self.m_note = obj.note()
        self.m_images = obj.images()
        self.m_videos = obj.videos()
        self.m_documents = obj.documents()

        self.set_title(self.m_name)
        self.set_note(self.m_note)
        self.set_images(self.m_images)
        self.set_videos(self.m_videos)
        self.set_documents(self.m_documents)

    def view_object(self, ido: str):
        o = BObjectAbstract()
        o.update_from_ido(context.database(), ido)
        self._show(o)

    def _view_attributed(self, cls, ido: str, page, widget):
        db = context.database()
        obj = cls()
        obj.update_from_ido(db, ido)
        obj.auto_update(db)
        self._show(obj)
        self.stackedWidget.setCurrentWidget(page)
        widget.view(obj)

    def view_aircraft(self, ido: str):
        self._view_attributed(Aircraft, ido, self.mbaPage, self.mbaWidget)

    def view_tank(self, ido: str):
        self._view_attributed(Tank, ido, self.xetPage, self.xetWidget)

    def view_rocket(self, ido: str):
        self._view_attributed(Rocket, ido, self.ttlPage, self.ttlWidget)

    def view_ship(self, ido: str):
        self._view_attributed(Ship, ido, self.tauPage, self.tauWidget)

    def show_context_menu(self, pos):
        menu = QMenu(self.imageLwg)
        menu.addAction("Làm mới", lambda: self.view_media(self.m_ido))
        menu.addAction("Đổi chế độ xem", lambda: self.set_detail(not self.m_detail))
        menu.exec(self.imageLwg.mapToGlobal(pos))

    def create_connections(self):
        self.addBtn.clicked.connect(self.add)
        self.removeBtn.clicked.connect(self.remove)
        self.applyBtn.clicked.connect(self.apply)
        self.cancelBtn.clicked.connect(self.cancel)
        self.gotoBtn.clicked.connect(lambda: self.open_explorer())
        self.viewBtn.clicked.connect(self.view)
        self.loadFromFolderBtn.clicked.connect(lambda: self.load_from_folder())
        self.imageLwg.customContextMenuRequested.connect(self.show_context_menu)

    def add_image_from_folder(self, folder: str):
        self.imageLwg.clear()
        for f in _files_in(folder):
            self.add_image(f"{folder}/{f}")

    def add_video_from_folder(self, folder: str):
        self.videoLwg.clear()
        for f in _files_in(folder):
            self.add_video(f"{folder}/{f}")

    def add_document_from_folder(self, folder: str):
        self.docLwg.clear()
        for f in _files_in(folder):
            self.add_document(f"{folder}/{f}")

    def add_image(self, file_name: str):
        img = QImage()
        if img.load(file_name):
            thumb = img.scaled(32, 32, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
            item = QListWidgetItem(QIcon(QPixmap.fromImage(thumb)), file_name, self.imageLwg)
            item.setData(USER_ROLE, 0)
        else:
            QMessageBox.warning(None, "Thêm hình ảnh", f"Hình ảnh bị bỏ qua vì không thể đọc: {file_name}")

    def add_video(self, file_name: str):
        item = QListWidgetItem(QIcon(":/myicon/Video.svg"), file_name, self.videoLwg)
        item.setData(USER_ROLE, 0)

    def add_document(self, file_name: str):
        item = QListWidgetItem(QIcon(":/myicon/Document.svg"), file_name, self.docLwg)
        item.setData(USER_ROLE, 0)
