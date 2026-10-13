"""Port of ColorCompositeDialog.cpp."""

from qgis.core import Qgis, QgsContrastEnhancement, QgsMultiBandColorRenderer, QgsRasterLayer
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QDialog

from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon, settings

Ui_ColorCompositeDialogClass = load_ui_class("app", "ColorCompositeDialog")
RangeLimit = Qgis.RasterRangeLimit


def fill_raster_layer_combo(combo, map_canvas, layer_tree_view) -> list[QgsRasterLayer]:
    """Fill combo with the canvas raster layers and select the first selected layer (shared show() logic).

    Returns the raster layer list (m_rasterLayers in the C++ dialogs).
    """
    raster_layers = [lyr for lyr in map_canvas.layers() if lyr.type() == Qgis.LayerType.Raster]
    combo.clear()
    for layer in raster_layers:
        combo.addItem(get_icon("Raster.svg"), layer.name(), layer)

    selected = layer_tree_view.selectedLayers() if layer_tree_view else []
    if selected and selected[0].type() == Qgis.LayerType.Raster:
        combo.setCurrentIndex(raster_layers.index(selected[0]) if selected[0] in raster_layers else -1)
    else:
        combo.setCurrentIndex(0)
    return raster_layers


class ColorCompositeDialog(QDialog, Ui_ColorCompositeDialogClass):
    complete = pyqtSignal()

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.raster_layers: list[QgsRasterLayer] = []
        self.output_files: list[str] = []

        self.rasterLayerCbx.currentIndexChanged.connect(self.raster_layer_changed)
        self.applyBtn.clicked.connect(self.apply)
        self.okBtn.clicked.connect(self._ok)
        self.cancelBtn.clicked.connect(self.close)
        self.defaultBtn.clicked.connect(self._default)

        # Initialize with current raster layers
        self.populate_raster_layers()

    # BPluginInterface
    def name(self) -> str:
        return "Color Composite"

    def vn_name(self) -> str:
        return "Tổng hợp màu"

    def get_icon(self):
        return get_icon("ColorComposite.svg")

    def auto_add_output_files(self) -> bool:
        return False

    def _ok(self):
        self.apply()
        self.close()

    def _set_limit(self, limit):
        if limit == RangeLimit.CumulativeCut:
            self.cumulativeCutRbtn.setChecked(True)
        elif limit == RangeLimit.MinimumMaximum:
            self.minMaxRbtn.setChecked(True)
        elif limit == RangeLimit.StdDev:
            self.stdDevRbtn.setChecked(True)
        else:
            self.noneRbtn.setChecked(True)

    def _default(self):
        s = settings()
        band_red = int(s.value("ColorComposite/BandRed", 1))
        band_green = int(s.value("ColorComposite/BandGreen", 2))
        band_blue = int(s.value("ColorComposite/BandBlue", 3))
        limit = RangeLimit(int(s.value("ColorComposite/Limit", RangeLimit.CumulativeCut.value)))

        self.redBandCbx.setCurrentIndex(band_red - 1)
        self.greenBandCbx.setCurrentIndex(band_green - 1)
        self.blueBandCbx.setCurrentIndex(band_blue - 1)
        self._set_limit(limit)

    def populate_raster_layers(self):
        if self.map_canvas is None:
            return
        self.raster_layers = fill_raster_layer_combo(self.rasterLayerCbx, self.map_canvas, self.layer_tree_view)

    def raster_layer_changed(self, idx: int):
        if idx < 0 or idx >= self.rasterLayerCbx.count():
            return
        raster_layer = self.rasterLayerCbx.itemData(idx)
        if not (raster_layer and raster_layer.isValid()):
            return

        band_cbxs = (self.redBandCbx, self.greenBandCbx, self.blueBandCbx)
        for cbx in band_cbxs:
            cbx.clear()
            cbx.addItem("Không", -1)

        band_count = raster_layer.bandCount()
        for i in range(1, band_count + 1):
            for cbx in band_cbxs:
                cbx.addItem(get_icon("Band.svg"), f"Kênh {i}", i)

        renderer = raster_layer.renderer()
        if isinstance(renderer, QgsMultiBandColorRenderer):
            bands = (renderer.redBand(), renderer.greenBand(), renderer.blueBand())
        else:
            # C++ ép kiểu mọi renderer sang QgsMultiBandColorRenderer (sai với ảnh 1 kênh)
            bands = (-1, -1, -1)
        for cbx, band in zip(band_cbxs, bands):
            cbx.setCurrentIndex(band if 0 < band <= band_count else 0)

        self._set_limit(renderer.minMaxOrigin().limits() if renderer else RangeLimit.NotSet)
        self.saveBandIndexesChbx.setEnabled(band_count >= 3)

    def apply(self):
        raster_layer = self.rasterLayerCbx.currentData()
        if not (raster_layer and raster_layer.isValid()):
            return

        band_red = int(self.redBandCbx.currentData())
        band_green = int(self.greenBandCbx.currentData())
        band_blue = int(self.blueBandCbx.currentData())

        limit = RangeLimit.NotSet
        if self.cumulativeCutRbtn.isChecked():
            limit = RangeLimit.CumulativeCut
        elif self.minMaxRbtn.isChecked():
            limit = RangeLimit.MinimumMaximum
        elif self.stdDevRbtn.isChecked():
            limit = RangeLimit.StdDev

        if raster_layer.bandCount() >= 2:
            renderer = raster_layer.renderer()
            if isinstance(renderer, QgsMultiBandColorRenderer):
                renderer.setRedBand(band_red)
                renderer.setGreenBand(band_green)
                renderer.setBlueBand(band_blue)

        raster_layer.setContrastEnhancement(
            QgsContrastEnhancement.ContrastEnhancementAlgorithm.StretchToMinimumMaximum, limit
        )
        raster_layer.triggerRepaint()

        if self.saveBandIndexesChbx.isChecked():
            s = settings()
            s.setValue("ColorComposite/BandRed", band_red)
            s.setValue("ColorComposite/BandGreen", band_green)
            s.setValue("ColorComposite/BandBlue", band_blue)
            s.setValue("ColorComposite/Limit", limit.value)
        # Thông báo hoàn thành
        self.complete.emit()
