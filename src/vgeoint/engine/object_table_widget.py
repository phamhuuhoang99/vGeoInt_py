"""Port of ObjectTableWidget.cpp — table of searching results."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtSql import QSqlQuery
from qgis.PyQt.QtWidgets import QAbstractItemView, QTableWidgetItem, QWidget

from vgeoint.common.ui import load_ui_class
from vgeoint.engine.defines import make_ido

Ui_ObjectTableWidget = load_ui_class("engine", "ObjectTableWidget")


def _text(value) -> str:
    return "" if value is None else str(value)


class ObjectTableWidget(QWidget, Ui_ObjectTableWidget):
    show_detail_object_id = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self._code = ""
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.viewBtn.clicked.connect(lambda: self._show_detail(self.table.currentRow()))
        self.table.cellDoubleClicked.connect(lambda row, _col: self._show_detail(row))

    def _show_detail(self, row: int):
        if row >= 0:
            self.show_detail_object_id.emit(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))

    def set_code(self, code: str):
        self._code = code
        if code in ("XET", "TTL"):
            headers = ["Tên", "Nước sở hữu"]
        else:
            headers = ["Tên", "Kiểu đối tượng", "Loại đối tượng"]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        for i in range(self.table.columnCount()):
            item = self.table.horizontalHeaderItem(i)
            font = item.font()
            font.setBold(True)
            item.setFont(font)

    def set_query_result(self, query: QSqlQuery):
        """Fill the table from rows (id, name, text2[, text3 for MBA])."""
        # xóa tất cả các row
        self.table.setRowCount(0)
        row = 0
        while query.next():
            item1 = QTableWidgetItem(_text(query.value(1)))
            # Đưa id vào trong data của cột đầu tiên là item1.
            item1.setData(Qt.ItemDataRole.UserRole, make_ido(self._code, int(query.value(0))))
            self.table.insertRow(row)
            self.table.setItem(row, 0, item1)
            self.table.setItem(row, 1, QTableWidgetItem(_text(query.value(2))))
            if self._code == "MBA":
                self.table.setItem(row, 2, QTableWidgetItem(_text(query.value(3))))
            row += 1
        self.table.horizontalHeader().setStretchLastSection(True)
