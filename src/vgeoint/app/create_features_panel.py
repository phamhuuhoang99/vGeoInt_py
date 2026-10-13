"""'Tạo đối tượng' panel (ArcGIS-style Create Features): pick the target layer, get the matching tool.

Not in the C++ app. Lists every vector layer of the project with an icon for its geometry type; the layer
being edited is shown in bold. Clicking a layer asks the main window to start creating features in it
(switching the edit session if another layer is being edited).
"""

from functools import cmp_to_key

from qgis.core import Qgis, QgsProject, QgsVectorLayer
from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import QCollator, QLocale, QSize, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QToolBar, QVBoxLayout, QWidget

from vgeoint.common.utils import get_icon

GEOMETRY_ICONS = {
    Qgis.GeometryType.Point: "AddPoint.svg",
    Qgis.GeometryType.Line: "AddLine.svg",
    Qgis.GeometryType.Polygon: "AddPolygon.svg",
}
LAYER_ID = Qt.ItemDataRole.UserRole


class CreateFeaturesPanel(QgsDockWidget):
    layer_chosen = pyqtSignal(QgsVectorLayer)

    def __init__(self, parent=None):
        super().__init__("Tạo đối tượng", parent)
        self.setObjectName("CreateFeaturesPanel")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        # Vẽ | Chọn | Sửa đỉnh | Di chuyển | Thuộc tính | Xóa — actions are added by the main window.
        self.toolbar = QToolBar()
        self.toolbar.setIconSize(QSize(22, 22))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Tìm lớp...")
        self.filter_edit.setClearButtonEnabled(True)
        self.layer_list = QListWidget()
        hint = QLabel(
            "Nhấp vào lớp để bắt đầu vẽ. Điểm: nhấp một lần. Đường / vùng: nhấp từng đỉnh, "
            "nhấp đúp hoặc chuột phải để kết thúc.\n"
            "Chọn: nhấp hoặc kéo khung (Ctrl: thêm/bớt). Sửa đỉnh: kéo đỉnh, nhấp đúp lên cạnh để thêm "
            "đỉnh, chuột phải lên đỉnh để xóa đỉnh. Phím Delete: xóa đối tượng đang chọn."
        )
        hint.setWordWrap(True)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.layer_list)
        layout.addWidget(hint)
        self.setWidget(body)

        self.filter_edit.textChanged.connect(self.apply_filter)
        self.layer_list.itemClicked.connect(self._item_clicked)

    def refresh(self, editing_layer: QgsVectorLayer | None = None):
        current_id = self.layer_list.currentItem().data(LAYER_ID) if self.layer_list.currentItem() else None
        self.layer_list.clear()
        layers = [
            l for l in QgsProject.instance().mapLayers().values()
            if isinstance(l, QgsVectorLayer) and l.geometryType() in GEOMETRY_ICONS
        ]
        # Vietnamese collation: "Đường" sorts with D, not after Z.
        collator = QCollator(QLocale(QLocale.Language.Vietnamese))
        collator.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        for layer in sorted(layers, key=cmp_to_key(lambda a, b: collator.compare(a.name(), b.name()))):
            editing = editing_layer is not None and layer.id() == editing_layer.id()
            item = QListWidgetItem(get_icon(GEOMETRY_ICONS[layer.geometryType()]), layer.name(), self.layer_list)
            item.setData(LAYER_ID, layer.id())
            if editing:
                item.setText(f"{layer.name()} (đang sửa)")
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            if layer.id() == current_id:
                self.layer_list.setCurrentItem(item)
        self.apply_filter(self.filter_edit.text())

    def apply_filter(self, text: str):
        needle = text.strip().lower()
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def item_for(self, layer: QgsVectorLayer) -> QListWidgetItem | None:
        for i in range(self.layer_list.count()):
            if self.layer_list.item(i).data(LAYER_ID) == layer.id():
                return self.layer_list.item(i)
        return None

    def _item_clicked(self, item: QListWidgetItem):
        layer = QgsProject.instance().mapLayer(item.data(LAYER_ID))
        if isinstance(layer, QgsVectorLayer):
            self.layer_chosen.emit(layer)
