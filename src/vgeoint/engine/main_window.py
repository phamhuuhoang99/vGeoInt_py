"""Port of vGeoEngine MainWindow.cpp."""

import logging

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import QMainWindow, QMessageBox

from vgeoint.common.defines import ENGINE_NAME
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import app_settings
from vgeoint.engine import context
from vgeoint.engine.change_password_dialog import ChangePasswordDialog
from vgeoint.engine.defines import ADMIN, USER, md5_hex, red
from vgeoint.engine.entities import exec_query
from vgeoint.engine.login_dialog import LoginDialog
from vgeoint.engine.setting_dialog import SettingDialog

log = logging.getLogger(__name__)
Ui_MainWindowClass = load_ui_class("engine", "MainWindow")

INFO_TEXT = (
    "Phần mềm vGeoEngine phiên bản 1.0.2 (2026)\n(C) Bản quyền thuộc về Cục Tác chiến/Bộ Tổng Tham mưu.\n"
    "\nNhóm tác giả:\n"
    "Phạm Xuân Hoàn, 0989.875.111, hoanpx@gmail.com\n"
    "Phạm Hữu Hoàng, 0941.688.367, phamhuuhoang99@gmail.com\n"
)


class MainWindow(QMainWindow, Ui_MainWindowClass):
    # (attribute, settings key) of the splitters whose geometry/state are saved
    _SPLITTERS = (("mediaSplitter", "MediaSplitter"), ("searchingSplitter", "SearchingSplitter"), ("mainSplitter", "MainSplitter"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.open_db_connection()
        self.setupUi(self)
        self.login_dlg = LoginDialog(self)
        self.setting_dlg = SettingDialog(self)
        self.mediaDetail.set_mode(2)
        self.mediaDetail.set_view_btn_visible(True)
        self.mediaDetail.set_enabled_controls(False)
        self.account = ""
        self.permission = 0
        self.restore_settings()
        self.create_connections()
        self.open_aircraft_searching_page()

    def open_db_connection(self):
        db = context.database(self)
        if not db.isOpen():
            log.error("Cannot open database: %s", db.lastError().text())
            QMessageBox.warning(self, "Lỗi khởi động", "Không thể kết nối đến Cơ sở dữ liệu.")
            # C++ called close() from the constructor, which had no effect; close once the loop runs.
            QTimer.singleShot(0, self.close)

    @staticmethod
    def database():
        return context.database()

    def showEvent(self, event):
        super().showEvent(event)
        if self.permission == 0:
            self.login_dlg.show()

    def closeEvent(self, event):
        self.save_settings()
        super().closeEvent(event)

    # ------------------------------------------------------------------------------------------ pages
    def open_database_page(self):
        self.stackedWidget.setCurrentWidget(self.databasePage)

    def open_account_page(self):
        if self.permission == ADMIN:
            self.stackedWidget.setCurrentWidget(self.accountPage)
        else:
            dlg = ChangePasswordDialog(self)
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dlg.set_account(self.account)
            dlg.show()

    def _open_searching_page(self, group_name: str, code: str):
        self.stackedWidget.setCurrentWidget(self.searchingPage)
        self.searchingWidget.set_group_name(group_name)
        self.objectTable.set_code(code)

    def open_aircraft_searching_page(self):
        self._open_searching_page("Máy bay", "MBA")

    def open_tank_searching_page(self):
        self._open_searching_page("Xe tăng", "XET")

    def open_rocket_searching_page(self):
        self._open_searching_page("Trận địa tên lửa", "TTL")

    def open_ship_searching_page(self):
        self._open_searching_page("Tàu thuyền", "TAU")

    def show_info(self):
        QMessageBox.information(self, "Thông tin", INFO_TEXT)

    # --------------------------------------------------------------------------------------- settings
    def restore_settings(self):
        s = app_settings(ENGINE_NAME)
        for key, restore in (("MainWindow/Geometry", self.restoreGeometry), ("MainWindow/WindowState", self.restoreState)):
            value = s.value(key)
            if value is not None:
                restore(value)
        for attr, key in self._SPLITTERS:
            splitter = getattr(self, attr)
            for suffix, restore in (("Geometry", splitter.restoreGeometry), ("State", splitter.restoreState)):
                value = s.value(f"{key}/{suffix}")
                if value is not None:
                    restore(value)

    def save_settings(self):
        s = app_settings(ENGINE_NAME)
        s.setValue("MainWindow/Geometry", self.saveGeometry())
        s.setValue("MainWindow/WindowState", self.saveState())
        for attr, key in self._SPLITTERS:
            splitter = getattr(self, attr)
            s.setValue(f"{key}/Geometry", splitter.saveGeometry())
            s.setValue(f"{key}/State", splitter.saveState())

    # ---------------------------------------------------------------------------------------- account
    def set_permission(self, permission: int):
        if permission == USER:
            # self.databaseWidget.set_mode(USER)
            self.databaseBtn.setVisible(False)

    def login(self, account: str, password: str):
        query = exec_query(context.database(), "select func_kiemtra_dangnhap(?::varchar, ?::varchar)", account, md5_hex(password))
        if query is None:
            return
        query.next()
        self.permission = int(query.value(0) or 0)
        if self.permission > 0:
            self.set_permission(self.permission)
            self.account = account
            self.login_dlg.rejected.disconnect(self.close)
            self.login_dlg.close()
        else:
            self.login_dlg.set_notice(red("Sai tên đăng nhập hoặc mật khẩu"))

    def create_connections(self):
        self.aircraftBtn.clicked.connect(self.open_aircraft_searching_page)
        self.tankBtn.clicked.connect(self.open_tank_searching_page)
        self.rocketBtn.clicked.connect(self.open_rocket_searching_page)
        self.shipBtn.clicked.connect(self.open_ship_searching_page)
        self.infoBtn.clicked.connect(self.show_info)
        self.databaseBtn.clicked.connect(self.open_database_page)
        self.accountBtn.clicked.connect(self.open_account_page)
        self.settingBtn.clicked.connect(self.setting_dlg.show)
        self.login_dlg.rejected.connect(self.close)
        self.login_dlg.login.connect(self.login)
        self.searchingWidget.searching_complete.connect(self.objectTable.set_query_result)
        self.searchingWidget.view_ido.connect(self.mediaDetail.view_media)
        self.objectTable.show_detail_object_id.connect(self.mediaDetail.view_media)
        self.mediaDetail.view_image.connect(self.mediaViewer.view_image)
        self.mediaDetail.view_video.connect(self.mediaViewer.view_video)
        self.mediaDetail.view_document.connect(self.mediaViewer.view_document)
