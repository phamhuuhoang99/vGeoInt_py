"""Port of ReportDialog.cpp — live scan report."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QDialog

from vgeoint.common.ui import load_ui_class

Ui_ReportDialog = load_ui_class("catalog", "ReportDialog")


class ReportDialog(QDialog, Ui_ReportDialog):
    stop = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.total_count = 0
        self.geo_data_count = 0
        self.closeBtn.clicked.connect(self.close)

    def clear(self):
        self.textEdit.clear()
        self.total_count = 0
        self.geo_data_count = 0

    def closeEvent(self, event):
        self.stop.emit()
        super().closeEvent(event)

    def report(self, file_name: str, is_geo_data: bool):
        self.total_count += 1
        if is_geo_data:
            self.geo_data_count += 1
            self.textEdit.append("<font color='green'>[GeoData] </font>" + file_name)
        else:
            # The C++ also appended the bare file name first, printing every non-geo file twice.
            self.textEdit.append("<font color='red'>[Non-Geo] </font>" + file_name)
        self.geoDataCountLbl.setText(str(self.geo_data_count))
        self.totalCountLbl.setText(str(self.total_count))

    def finished(self, message: str):
        self.textEdit.append("\n---------- Quét xong! ----------")
        self.textEdit.append(message.strip())
        self.textEdit.append("----------------------------------\n")
        if self.autoCloseChbx.isChecked():
            self.close()
