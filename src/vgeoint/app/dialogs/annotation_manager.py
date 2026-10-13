"""Port of AnnotationManagerDialog.cpp — lists text and tag annotations, go to / clear them."""

from qgis.core import QgsProject, QgsTextAnnotation
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QListWidgetItem, QMessageBox

from vgeoint.app.maptools.annotation import TagAnnotation
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon

Ui_AnnotationManagerDialog = load_ui_class("app", "AnnotationManagerDialog")
Btn = QMessageBox.StandardButton
USER_ROLE = Qt.ItemDataRole.UserRole


def _split_annotations():
    """Return (text annotations, tag annotations)."""
    texts, tags = [], []
    for anno in QgsProject.instance().annotationManager().annotations():
        if isinstance(anno, TagAnnotation):
            tags.append(anno)
        elif isinstance(anno, QgsTextAnnotation):
            texts.append(anno)
    return texts, tags


class AnnotationManagerDialog(QDialog, Ui_AnnotationManagerDialog):
    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.setWindowIcon(get_icon("TextAnnotation/Manager.svg"))

        self.tagAnnoLswg.itemDoubleClicked.connect(self._go_to)
        self.textAnnoLswg.itemDoubleClicked.connect(self._go_to)
        self.gotoBtn.clicked.connect(self._go_to_current)
        self.clearBtn.clicked.connect(self._clear)
        self.populate()

    def populate(self):
        self.textAnnoLswg.clear()
        self.tagAnnoLswg.clear()
        texts, tags = _split_annotations()
        for annos, widget in ((tags, self.tagAnnoLswg), (texts, self.textAnnoLswg)):
            for anno in annos:
                text = anno.document().toPlainText()
                item = QListWidgetItem(text if text.strip() else "<trống>", widget)
                item.setData(USER_ROLE, anno.mapPosition())

    def _go_to(self, item: QListWidgetItem):
        self.map_canvas.setCenter(item.data(USER_ROLE))

    def _go_to_current(self):
        widget = self.textAnnoLswg if self.tabWidget.currentIndex() == 0 else self.tagAnnoLswg
        item = widget.currentItem()
        if item is not None:
            self._go_to(item)

    def _clear(self):
        texts, tags = _split_annotations()
        manager = QgsProject.instance().annotationManager()
        if self.tabWidget.currentIndex() == 0 and texts:
            question, annos, widget = "Bạn chắc chắn muốn xóa tất cả ghi chú văn bản", texts, self.textAnnoLswg
        elif tags:
            question, annos, widget = "Bạn chắc chắn muốn xóa tất cả ghi chú Tag", tags, self.tagAnnoLswg
        else:
            return
        if QMessageBox.question(self, "Xóa tất cả", question) == Btn.Yes:
            for anno in annos:
                manager.removeAnnotation(anno)
            widget.clear()
