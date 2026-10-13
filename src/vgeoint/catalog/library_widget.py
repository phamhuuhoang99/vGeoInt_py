"""Port of LibraryWidget.cpp — manage libraries, watched folders, formats and scan results."""

import logging

from qgis.PyQt.QtCore import QFile, QSize, Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QListWidgetItem,
    QMessageBox,
    QWidget,
)

from vgeoint.catalog import context
from vgeoint.catalog.explorer import show_in_explorer
from vgeoint.catalog.geo_info_reader import supported_raster_formats, supported_vector_formats
from vgeoint.catalog.models import Directory, DirectoryModel, GeoDataModel, Library, LibraryModel
from vgeoint.catalog.report_dialog import ReportDialog
from vgeoint.catalog.scanner import ScannerThread
from vgeoint.common.defines import CATALOG_NAME
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import app_settings

log = logging.getLogger(__name__)
Ui_LibraryWidget = load_ui_class("catalog", "LibraryWidget")
Btn = QMessageBox.StandardButton
CHECKED, UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.Unchecked


def _green(text: str) -> str:
    return f"<font color='green'>{text}</font>"


def _toggle(item: QListWidgetItem):
    item.setCheckState(UNCHECKED if item.checkState() == CHECKED else CHECKED)


class LibraryWidget(QWidget, Ui_LibraryWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.load_supported_formats()

        db = context.database(self)
        if not db.isOpen():
            QMessageBox.warning(self, "Lỗi khởi động", "Không thể kết nối đến Cơ sở dữ liệu.")
            log.error("Connect to database failed. %s", db.lastError().text())

        self.lib_model = LibraryModel(db)
        self.dir_model = DirectoryModel(db)
        self.geo_data_model = GeoDataModel(db)
        self.scanner_thread = ScannerThread(context.config(), self)
        self.report_dlg = ReportDialog(self)
        self.libraries: list[Library] = []
        self.current_lib_in_rec_table = Library()  # library đang hiển thị trên bảng GeoData

        self.geoDataTbv.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.create_connections()
        self.load_lib()

    # ------------------------------------------------------------ settings
    _SPLITTERS = (("hSplitter1", "LibraryWidgetHSplitter1"), ("hSplitter2", "LibraryWidgetHSplitter2"), ("vSplitter", "LibraryWidgetVSplitter"))

    def restore_settings(self):
        s = app_settings(CATALOG_NAME)
        for attr, key in self._SPLITTERS:
            splitter = getattr(self, attr)
            for suffix, restore in (("Geometry", splitter.restoreGeometry), ("State", splitter.restoreState)):
                value = s.value(f"{key}/{suffix}")
                if value is not None:
                    restore(value)

    def save_settings(self):
        s = app_settings(CATALOG_NAME)
        for attr, key in self._SPLITTERS:
            splitter = getattr(self, attr)
            s.setValue(f"{key}/Geometry", splitter.saveGeometry())
            s.setValue(f"{key}/State", splitter.saveState())

    # --------------------------------------------------------- connections
    def create_connections(self):
        self.scanLibBtn.clicked.connect(self.scan_lib)
        self.addLibBtn.clicked.connect(self.add_lib)
        self.removeLibBtn.clicked.connect(self.remove_lib)
        self.viewLibBtn.clicked.connect(self.view_lib)
        self.formatsLwg.itemDoubleClicked.connect(_toggle)
        self.selectAllFormatsBtn.clicked.connect(self.select_all_formats)
        self.clearFormatsBtn.clicked.connect(self.clear_selected_formats)
        self.saveFormatsBtn.clicked.connect(self.update_filters_from_gui)
        # Kết nối này để bắt signal hoàn thành chỉnh sửa tên item
        self.librariesLwg.itemDelegate().commitData.connect(self.commit_lib)
        self.librariesLwg.currentRowChanged.connect(self._library_selected)
        self.addDirBtn.clicked.connect(self.add_dir)
        self.removeDirBtn.clicked.connect(self.remove_dir)
        self.showDirInExplorerBtn.clicked.connect(self.show_dir_in_explorer)
        self.dirLwg.itemDoubleClicked.connect(_toggle)
        self.selectAllEnabledDirBtn.clicked.connect(lambda: self._set_all_dirs(CHECKED))
        self.clearEnabledDirBtn.clicked.connect(lambda: self._set_all_dirs(UNCHECKED))
        self.saveDirBtn.clicked.connect(self.update_directory_from_gui)
        self.showRecInExplorerBtn.clicked.connect(self.show_rec_in_explorer)
        self.copyRecContentBtn.clicked.connect(self.copy_rec_content)
        self.removeRecNotExistsBtn.clicked.connect(self.remove_rec_not_exists)

        self.report_dlg.stop.connect(self.scanner_thread.stop)
        self.report_dlg.stop.connect(lambda: self.load_geo_data_from_lib(self.scanner_thread.library))
        self.scanner_thread.finished.connect(lambda: self.scanLibBtn.setEnabled(True))
        self.scanner_thread.report.connect(self.report_dlg.report)
        self.scanner_thread.finished_scanning.connect(self.report_dlg.finished)

    def _library_selected(self, idx: int):
        if 0 <= idx < len(self.libraries):
            lib = self.libraries[idx]
            self.set_formats_from_filters(lib.filters)
            self.load_directories(lib)

    # ----------------------------------------------------------- libraries
    def _library_item(self, name: str) -> QListWidgetItem:
        item = QListWidgetItem(name, self.librariesLwg)
        item.setIcon(QIcon(":/myicon/Library.svg"))
        return item

    def load_lib(self):
        self.librariesLwg.clear()
        self.dirLwg.clear()
        self.clear_selected_formats()
        self.libraries = self.lib_model.get_all()
        for lib in self.libraries:
            self._library_item(lib.name)

    def scan_lib(self):
        idx = self.librariesLwg.currentRow()
        if idx < 0:
            return
        self.scanLibBtn.setEnabled(False)
        self.report_dlg.show()
        self.report_dlg.clear()
        self.scanner_thread.set_library(self.libraries[idx])
        self.scanner_thread.start()

    def add_lib(self):
        count = 1
        name = f"Thư viện {count}"
        while self.is_exists_lib(name):
            count += 1
            name = f"Thư viện {count}"
        item = self._library_item(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.librariesLwg.setCurrentItem(item)
        self.librariesLwg.editItem(item)

    def remove_lib(self):
        item = self.librariesLwg.currentItem()
        if item is not None and QMessageBox.question(self, CATALOG_NAME, "Bạn muốn xóa thư viện này?") == Btn.Yes:
            self.lib_model.remove(item.text())
            self.load_lib()

    def view_lib(self):
        idx = self.librariesLwg.currentRow()
        if idx < 0:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.load_geo_data_from_lib(self.libraries[idx])
        finally:
            QApplication.restoreOverrideCursor()

    def commit_lib(self, editor: QWidget):
        lib_name = editor.text().strip() or "Thư viện"
        last = self.librariesLwg.count() - 1
        if any(self.librariesLwg.item(i).text() == lib_name for i in range(last)):
            count = 1
            new_name = f"{lib_name}{count}"
            while self.is_exists_lib(new_name):
                count += 1
                new_name = f"{lib_name}{count}"
            lib_name = new_name
            self.librariesLwg.item(last).setText(lib_name)

        # Thêm mới library vào CSDL rồi load lại lên GUI
        self.lib_model.add_or_update(Library(0, lib_name, []))
        self.load_lib()
        # Đặt current index là library vừa tạo
        for i in range(self.librariesLwg.count()):
            if self.librariesLwg.item(i).text() == lib_name:
                self.librariesLwg.setCurrentRow(i)
                break

    def load_geo_data_from_lib(self, lib: Library):
        self.current_lib_in_rec_table = lib
        model = self.geo_data_model.get_geo_data_from_lib(lib)
        for col, title in enumerate(("Đường Dẫn", "Thời Gian Tạo", "Tọa Độ Khung", "Hệ Tọa Độ", "SRID")):
            model.setHeaderData(col, Qt.Orientation.Horizontal, title)
        self.geoDataTableLbl.setText(f"Dữ liệu đã thu thập: [{lib.name}]")
        self.geoDataTbv.setModel(model)
        self.geoDataTbv.resizeColumnsToContents()
        self.geoDataTbv.horizontalHeader().setStretchLastSection(True)

    # ------------------------------------------------------------- formats
    def load_supported_formats(self):
        for f in sorted(set(supported_raster_formats() + supported_vector_formats())):
            item = QListWidgetItem(f, self.formatsLwg)
            item.setSizeHint(QSize(80, 30))
            item.setToolTip(f)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(UNCHECKED)

    def _format_items(self):
        return (self.formatsLwg.item(i) for i in range(self.formatsLwg.count()))

    def set_formats_from_filters(self, filters: list[str]):
        self.clear_selected_formats()
        wanted = set(filters)
        for item in self._format_items():
            if item.text() in wanted:
                item.setCheckState(CHECKED)

    def clear_selected_formats(self):
        for item in self._format_items():
            item.setCheckState(UNCHECKED)

    def select_all_formats(self):
        for item in self._format_items():
            item.setCheckState(CHECKED)

    def _notice(self, label):
        label.setText(_green("Lưu xong!"))
        QTimer.singleShot(2000, label.clear)
        QApplication.beep()

    def update_filters_from_gui(self):
        idx = self.librariesLwg.currentRow()
        if idx < 0:
            return
        lib = self.libraries[idx]
        lib.set_filters(" ".join(i.text() for i in self._format_items() if i.checkState() == CHECKED))
        self.lib_model.add_or_update(lib)
        self._notice(self.formatsNoticeLbl)

    # --------------------------------------------------------- directories
    def _dir_item(self, path: str, enabled: bool) -> QListWidgetItem:
        item = QListWidgetItem(QIcon(":/myicon/Folder.svg"), path, self.dirLwg)
        item.setToolTip(path)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(CHECKED if enabled else UNCHECKED)
        return item

    def add_dir(self):
        if self.librariesLwg.currentRow() < 0:
            return
        directory = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục giám sát",
            "",
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if not directory:
            return
        if self.is_exists_dir(directory):
            QMessageBox.warning(self, CATALOG_NAME, "Thư mục này đã thêm rồi")
            return
        self.dirLwg.setCurrentItem(self._dir_item(directory, True))

    def remove_dir(self):
        item = self.dirLwg.currentItem()
        if item is not None and QMessageBox.question(self, CATALOG_NAME, "Bạn muốn xóa thư mục này?") == Btn.Yes:
            self.dirLwg.takeItem(self.dirLwg.row(item))

    def show_dir_in_explorer(self):
        item = self.dirLwg.currentItem()
        if item is not None:
            show_in_explorer(item.text())

    def load_directories(self, lib: Library):
        self.dirLwg.clear()
        for d in self.dir_model.get_dirs_from_lib(lib):
            self._dir_item(d.path, d.enabled)
        if self.dirLwg.count():
            self.dirLwg.setCurrentRow(0)

    def _set_all_dirs(self, state):
        for i in range(self.dirLwg.count()):
            self.dirLwg.item(i).setCheckState(state)

    def update_directory_from_gui(self):
        idx = self.librariesLwg.currentRow()
        if idx < 0:
            return
        lib = self.libraries[idx]
        for d in self.dir_model.get_dirs_from_lib(lib):
            if not self.is_exists_dir(d.path):
                self.dir_model.remove(d.path, lib.id)
        for i in range(self.dirLwg.count()):
            item = self.dirLwg.item(i)
            self.dir_model.add_or_update(Directory(0, item.text(), item.checkState() == CHECKED, lib.id))
        self._notice(self.dirNoticeLbl)

    # ------------------------------------------------------------- records
    def _current_record(self):
        index = self.geoDataTbv.currentIndex()
        model = self.geoDataTbv.model()
        return (index, model) if index.isValid() and model is not None else (None, None)

    def show_rec_in_explorer(self):
        index, model = self._current_record()
        if index is None:
            return
        file_name = model.data(index.siblingAtColumn(0))
        if QFile.exists(file_name):
            show_in_explorer(file_name)
        else:
            QMessageBox.warning(self, CATALOG_NAME, "File không tồn tại")

    def copy_rec_content(self):
        index, model = self._current_record()
        if index is None:
            return
        cell = lambda col: model.data(index.siblingAtColumn(col))  # noqa: E731
        date = cell(1)
        date_text = date.toString("M/d/yyyy h:mm AP") if hasattr(date, "toString") else str(date)
        QApplication.clipboard().setText(f"{cell(0)}\n{date_text}\n{cell(2)}\n{cell(3)}\n{int(cell(4) or 0)}")
        QApplication.beep()

    def remove_rec_not_exists(self):
        model = self.geoDataTbv.model()
        if model is None:
            return
        if QMessageBox.question(self, CATALOG_NAME, "Bạn muốn xóa các file không còn tồn tại?") != Btn.Yes:
            return
        missing = [
            model.data(model.index(i, 0))
            for i in range(model.rowCount())
            if not QFile.exists(model.data(model.index(i, 0)))
        ]
        for file_name in missing:
            self.geo_data_model.remove(file_name, self.current_lib_in_rec_table.id)
        self.load_geo_data_from_lib(self.current_lib_in_rec_table)

    # -------------------------------------------------------------- lookups
    def is_exists_lib(self, name: str) -> bool:
        return any(self.librariesLwg.item(i).text() == name for i in range(self.librariesLwg.count()))

    def is_exists_dir(self, path: str) -> bool:
        return any(self.dirLwg.item(i).text() == path for i in range(self.dirLwg.count()))

    def shutdown(self):
        """Stop a running scan before the window closes."""
        if self.scanner_thread.isRunning():
            self.scanner_thread.stop()
            self.scanner_thread.wait(10000)
