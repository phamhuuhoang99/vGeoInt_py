"""Port of SettingDialog.cpp."""

from qgis.PyQt.QtCore import QDir
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QDialog

from vgeoint.common.ui import load_ui_class
from vgeoint.engine.drive_searching import DriveSearching

Ui_SettingDialog = load_ui_class("engine", "SettingDialog")


class SettingDialog(QDialog, Ui_SettingDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.okBtn.clicked.connect(self._ok)

    def _ok(self):
        DriveSearching.set_disk_label(self.driveCbx.currentText())
        self.close()

    def showEvent(self, event):
        self.driveCbx.clear()
        for info in QDir.drives():
            self.driveCbx.addItem(QIcon(":/myicon/Drive.svg"), info.path())
        idx = self.driveCbx.findText(DriveSearching.drive_label())
        if idx >= 0:
            self.driveCbx.setCurrentIndex(idx)
        super().showEvent(event)
