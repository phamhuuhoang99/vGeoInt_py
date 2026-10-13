"""Port of AccountWidget.cpp — account management (admin page)."""

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QTableWidgetItem, QWidget

from vgeoint.common.ui import load_ui_class
from vgeoint.engine import context
from vgeoint.engine.defines import ADMIN, USER, green, md5_hex, red
from vgeoint.engine.entities import exec_query

Ui_AccountWidget = load_ui_class("engine", "AccountWidget")

USER_NAME = "Người dùng"
ADMIN_NAME = "Quản trị"


class AccountWidget(QWidget, Ui_AccountWidget):
    # enum Action
    NONE, ADD, EDIT = range(3)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.action = self.NONE
        self.set_password_visible(False)
        self.load_accounts()
        self.adminPermissionCbx.addItem(USER_NAME)
        self.adminPermissionCbx.addItem(ADMIN_NAME)
        self.adminAccountLed.setEnabled(False)
        self.adminPasswordChbx.setVisible(False)

        self.adminPasswordChbx.toggled.connect(self.set_password_visible)
        self.tableWidget.cellDoubleClicked.connect(self._cell_double_clicked)
        self.addBtn.clicked.connect(self.add)
        self.editBtn.clicked.connect(self.edit)
        self.removeBtn.clicked.connect(self.remove)
        self.adminApplyBtn.clicked.connect(self.admin_apply)
        self.adminCancelBtn.clicked.connect(self.admin_cancel)

    def _cell_double_clicked(self, row: int, _col: int):
        self.adminAccountLed.setText(self.tableWidget.item(row, 0).text())
        permission_name = self.tableWidget.item(row, 1).text()
        self.adminPermissionCbx.setCurrentIndex(0 if permission_name == USER_NAME else 1)

    def add(self):
        self.action = self.ADD
        self.adminNoticeLbl.setText(green("Nhập thông tin tài khoản mới"))
        self.adminAccountLed.clear()
        self.adminAccountLed.setEnabled(True)
        self.adminPermissionCbx.setCurrentIndex(0)
        self.adminPasswordChbx.setVisible(False)
        self.set_password_visible(True)

    def edit(self):
        row = self.tableWidget.currentRow()
        if row < 0:
            return
        self.action = self.EDIT
        self.adminNoticeLbl.setText(green("Thay đổi thông tin tài khoản"))
        self.adminAccountLed.setText(self.tableWidget.item(row, 0).text())
        self.adminAccountLed.setEnabled(False)
        permission_name = self.tableWidget.item(row, 1).text()
        self.adminPermissionCbx.setCurrentIndex(0 if permission_name == USER_NAME else 1)
        self.adminPasswordChbx.setVisible(True)
        self.adminPasswordChbx.setChecked(False)
        self.set_password_visible(False)

    def remove(self):
        row = self.tableWidget.currentRow()
        if row < 0:
            return
        account = self.tableWidget.item(row, 0).text()
        answer = QMessageBox.question(self, "Xóa tài khoản", f"Bạn chắc chắn muốn xóa {account}")
        if answer == QMessageBox.StandardButton.Yes:
            exec_query(context.database(), "select * from func_xoa_taikhoan(?::varchar)", account)
            self.tableWidget.removeRow(row)

    def admin_apply(self):
        account = self.adminAccountLed.text().strip()
        permission = ADMIN if self.adminPermissionCbx.currentText() == ADMIN_NAME else USER
        password = self.adminPasswordLed.text()
        db = context.database()
        if self.action == self.ADD:
            if len(account) < 4:
                self.adminNoticeLbl.setText(red("Tên tài khoản phải lớn hơn 4 kí tự"))
                return
            if len(password) < 6:
                self.adminNoticeLbl.setText(red("Mật khẩu phải dài hơn 6 kí tự"))
                return
            if password != self.adminRepasswordLed.text():
                self.adminNoticeLbl.setText(red("Mật khẩu nhập không giống nhau"))
                return
            query = exec_query(
                db, "select func_them_taikhoan(?::varchar, ?::varchar, ?::int)", account, md5_hex(password), permission
            )
            if query is None or not query.next():
                self.adminNoticeLbl.setText(red("Không làm việc được với CSDL"))
                return
            if not query.value(0):
                self.adminNoticeLbl.setText(red("Tài khoản đã bị trùng"))
                return
            self._applied("Thêm tài khoản thành công")
        elif self.action == self.EDIT:
            change_password = self.adminPasswordChbx.isChecked()
            if change_password:
                if len(password) < 6:
                    self.adminNoticeLbl.setText(red("Mật khẩu phải dài hơn 6 kí tự"))
                    return
                if password != self.adminRepasswordLed.text():
                    self.adminNoticeLbl.setText(red("Mật khẩu mới nhập không giống nhau"))
                    return
            exec_query(db, "select func_doiquyen_taikhoan(?::varchar, ?::int)", account, permission)
            if change_password:
                exec_query(db, "select func_doimatkhau_taikhoan(?::varchar, ?::varchar)", account, md5_hex(password))
            self._applied("Cập nhật tài khoản thành công")

    def _applied(self, notice: str):
        QApplication.beep()
        self.action = self.NONE
        self.adminNoticeLbl.setText(green(notice))
        self.load_accounts()
        self.adminAccountLed.clear()
        self.adminAccountLed.setEnabled(False)
        self.adminPermissionCbx.setCurrentIndex(0)
        self.adminPasswordChbx.setVisible(False)
        self.set_password_visible(False)
        QTimer.singleShot(3000, self.adminNoticeLbl.clear)

    def admin_cancel(self):
        self.action = self.NONE
        self.adminNoticeLbl.setText("")
        self.adminAccountLed.clear()
        self.adminAccountLed.setEnabled(False)
        self.adminPermissionCbx.setCurrentIndex(0)
        self.adminPasswordChbx.setVisible(False)
        self.set_password_visible(False)

    def set_password_visible(self, enable: bool):
        self.adminPasswordLed.clear()
        self.adminRepasswordLed.clear()
        self.adminPasswordLbl.setVisible(enable)
        self.adminRepasswordLbl.setVisible(enable)
        self.adminPasswordLed.setVisible(enable)
        self.adminRepasswordLed.setVisible(enable)

    def load_accounts(self):
        # xóa tất cả các row
        self.tableWidget.setRowCount(0)
        query = exec_query(context.database(), "select * from func_laytatca_taikhoan()")
        row = 0
        while query is not None and query.next():
            permission = int(query.value(1))
            self.tableWidget.insertRow(row)
            self.tableWidget.setItem(row, 0, QTableWidgetItem(str(query.value(0))))
            self.tableWidget.setItem(row, 1, QTableWidgetItem(ADMIN_NAME if permission == ADMIN else USER_NAME))
            row += 1
        self.tableWidget.horizontalHeader().setStretchLastSection(True)
