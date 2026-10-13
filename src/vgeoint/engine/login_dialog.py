"""Port of LoginDialog.cpp."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QDialog

from vgeoint.common.ui import load_ui_class

Ui_LoginDialog = load_ui_class("engine", "LoginDialog")


class LoginDialog(QDialog, Ui_LoginDialog):
    login = pyqtSignal(str, str)  # (account, password)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.cancelBtn.clicked.connect(self.close)
        self.loginBtn.clicked.connect(lambda: self.login.emit(self.accountLed.text(), self.passwordLed.text()))

    def set_notice(self, notice: str):
        self.noticeLbl.setText(notice)
