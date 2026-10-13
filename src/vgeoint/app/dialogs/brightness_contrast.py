"""Port of BrightnessContrastDialog.cpp."""

from qgis.core import QgsRasterLayer
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QDialog

from vgeoint.app.dialogs.color_composite import fill_raster_layer_combo
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon

Ui_BrightnessContrastDialog = load_ui_class("app", "BrightnessContrastDialog")


class BrightnessContrastDialog(QDialog, Ui_BrightnessContrastDialog):
    complete = pyqtSignal()

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setModal(True)
        self.setWindowIcon(self.get_icon())
        self.setWindowTitle(self.vn_name())
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.raster_layers: list[QgsRasterLayer] = []
        self.output_files: list[str] = []

        self.rasterLayerCbx.currentIndexChanged.connect(self.raster_layer_changed)
        self.applyBtn.clicked.connect(self.apply)
        self.okBtn.clicked.connect(self._ok)
        self.cancelBtn.clicked.connect(self.close)
        self.brightnessDefaultBtn.clicked.connect(lambda: self.brightnessSdr.setValue(0))
        self.contrastDefaultBtn.clicked.connect(lambda: self.contrastSdr.setValue(0))
        self.populate()

    # BPluginInterface
    def name(self) -> str:
        return "R_BrightnessContrast"

    def vn_name(self) -> str:
        return "Độ sáng / Độ tương phản"

    def get_icon(self):
        return get_icon("BrightnessContrast.svg")

    def auto_add_output_files(self) -> bool:
        return False

    def populate(self):
        """BPluginInterface::show() of the C++ dialog: list the canvas raster layers."""
        self.raster_layers = fill_raster_layer_combo(self.rasterLayerCbx, self.map_canvas, self.layer_tree_view)

    def _ok(self):
        self.apply()
        self.close()

    @staticmethod
    def set_brightness(raster_layer: QgsRasterLayer, brightness: int):
        f = raster_layer.brightnessFilter()
        if f.brightness() != brightness:
            f.setBrightness(brightness)
            raster_layer.triggerRepaint()

    @staticmethod
    def set_contrast(raster_layer: QgsRasterLayer, contrast: int):
        f = raster_layer.brightnessFilter()
        if f.contrast() != contrast:
            f.setContrast(contrast)
            raster_layer.triggerRepaint()

    def raster_layer_changed(self, idx: int):
        if idx < 0 or idx >= self.rasterLayerCbx.count():
            return
        raster_layer = self.rasterLayerCbx.itemData(idx)
        if raster_layer and raster_layer.isValid():
            f = raster_layer.brightnessFilter()
            self.brightnessSdr.setValue(f.brightness())
            self.contrastSdr.setValue(f.contrast())

    def apply(self):
        raster_layer = self.rasterLayerCbx.currentData()
        if raster_layer and raster_layer.isValid():
            self.set_brightness(raster_layer, self.brightnessSdr.value())
            self.set_contrast(raster_layer, self.contrastSdr.value())
            self.complete.emit()
