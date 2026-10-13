"""Port of MetadataViewerDialog.cpp."""

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QDialog

from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon

Ui_MetadataViewerDialog = load_ui_class("app", "MetadataViewerDialog")


class MetadataViewerDialog(QDialog, Ui_MetadataViewerDialog):
    complete = pyqtSignal()

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.output_files: list[str] = []
        self.populate()

    # BPluginInterface
    def name(self) -> str:
        return "T_MetadataViewer"

    def vn_name(self) -> str:
        return "Xem metadata"

    def get_icon(self):
        return get_icon("Metadata.svg")

    def auto_add_output_files(self) -> bool:
        return False

    def populate(self):
        """BPluginInterface::show() of the C++ dialog: show the current layer's metadata."""
        layer = self.layer_tree_view.currentLayer() if self.layer_tree_view else None
        if layer is not None and layer.isValid():
            self.textBrowser.setHtml(layer.htmlMetadata())
