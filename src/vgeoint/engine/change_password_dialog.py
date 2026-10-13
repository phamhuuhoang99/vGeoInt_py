"""Port of ChangePasswordDialog.cpp."""

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import QApplication, QDialog

from vgeoint.common.ui import load_ui_class
from vgeoint.engine import context
from vgeoint.engine.defines import green, md5_hex, red
from vgeoint.engine.entities import exec_query

Ui_ChangePasswordDialog = load_ui_class("engine", "ChangePasswordDialog")


class ChangePasswordDialog(QDialog, Ui_ChangePasswordDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.applyBtn.clicked.connect(self.apply)
        self.cancelBtn.clicked.connect(self.close)

    def set_account(self, account: str):
        self.accountLed.setText(account)

    def apply(self):
        account = self.accountLed.text()
        password = self.passwordLed.text()
        new_password = self.newPasswordLed.text()
        if len(new_password) < 6:
            self.userNoticeLbl.setText(red("Mật khẩu mới phải dài hơn 6 kí tự"))
            return
        if new_password != self.repasswordLed.text():
            self.userNoticeLbl.setText(red("Mật khẩu mới nhập không giống nhau"))
            return

        db = context.database()
        query = exec_query(db, "select func_kiemtra_dangnhap(?::varchar, ?::varchar)", account, md5_hex(password))
        if query is None or not query.next():
            self.userNoticeLbl.setText(red("Không làm việc được với CSDL"))
            return
        if int(query.value(0)) > 0:
            # C++ hashed the (already hashed) old password here instead of the new one.
            exec_query(db, "select func_doimatkhau_taikhoan(?::varchar, ?::varchar)", account, md5_hex(new_password))
            QApplication.beep()
            self.userNoticeLbl.setText(green("Đổi mật khẩu thành công"))
            QTimer.singleShot(1500, self.close)
        else:
            self.userNoticeLbl.setText(red("Mật khẩu cũ không đúng"))
