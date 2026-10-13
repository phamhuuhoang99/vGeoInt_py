"""Port of ImageSplitDialog.cpp (C++ class ImageSplit)."""

import logging

from qgis.core import QgsRasterFileWriter, QgsRasterLayer
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog, QListWidgetItem

from vgeoint.app.dialogs.color_composite import fill_raster_layer_combo
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon, settings

Ui_ImageSplitDialog = load_ui_class("app", "ImageSplitDialog")
log = logging.getLogger(__name__)


def green(text: str) -> str:
    return f"<font color='green'>{text}</font>"


def red(text: str) -> str:
    return f"<font color='red'>{text}</font>"


class ImageSplitDialog(QDialog, Ui_ImageSplitDialog):
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

        self.progressBar.hide()

        self.rasterLayerCbx.currentIndexChanged.connect(self.raster_layer_changed)
        self.okBtn.clicked.connect(self._ok)
        self.cancelBtn.clicked.connect(self.close)
        self.selectFolderBtn.clicked.connect(self._select_folder)
        self.editBandNameBtn.clicked.connect(self._edit_band_name)
        self.defaultBandNameBtn.clicked.connect(self._default_band_names)
        self.populate()

    # BPluginInterface
    def name(self) -> str:
        return "T_ImageSplit"

    def vn_name(self) -> str:
        return "Tách kênh ảnh"

    def get_icon(self):
        return get_icon("SplitImage.svg")

    def auto_add_output_files(self) -> bool:
        return self.autoAddOutputChbx.isChecked()

    def populate(self):
        """BPluginInterface::show() of the C++ dialog: list the canvas raster layers."""
        self.raster_layers = fill_raster_layer_combo(self.rasterLayerCbx, self.map_canvas, self.layer_tree_view)

    def _ok(self):
        self.apply()
        self.close()

    def _select_folder(self):
        s = settings()
        directory = s.value("SaveImage/Dir", QApplication.applicationDirPath())
        folder = QFileDialog.getExistingDirectory(self, "Folder chứa ảnh kết quả", directory)
        if folder:
            self.outputFolderLedr.setText(folder)
            if folder != directory:
                s.setValue("SaveImage/Dir", folder)

    def _edit_band_name(self):
        item = self.bandLswg.currentItem()
        if item:
            self.bandLswg.editItem(item)

    def _default_band_names(self):
        for i in range(self.bandLswg.count()):
            self.bandLswg.item(i).setText(f"{self.rasterLayerCbx.currentText()}-band{i + 1}")

    def raster_layer_changed(self, idx: int):
        if idx < 0 or idx >= self.rasterLayerCbx.count():
            return
        raster_layer = self.rasterLayerCbx.itemData(idx)
        if not (raster_layer and raster_layer.isValid()):
            return
        band_count = raster_layer.bandCount()
        pixel_type = raster_layer.dataProvider().dataTypeSize(1)
        self.bandCountLedr.setText(str(band_count))
        self.pixelTypeLedr.setText(f"{pixel_type * 8} bit")
        self.bandLswg.clear()
        for i in range(band_count):
            item = QListWidgetItem(
                get_icon("Band.svg"), f"{self.rasterLayerCbx.currentText()}-band{i + 1}", self.bandLswg
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)

    def apply(self):
        raster_layer = self.rasterLayerCbx.currentData()
        if raster_layer and raster_layer.isValid():
            folder = self.outputFolderLedr.text()
            file_names = [f"{folder}/{self.bandLswg.item(i).text()}.tif" for i in range(self.bandLswg.count())]
            if self.split_image(raster_layer, file_names):
                self.noticeLbl.setText(green("Tách kênh ảnh đã hoàn thành"))
                self.output_files = file_names
                self.complete.emit()
            else:
                self.noticeLbl.setText(red("Không thể tách kênh ảnh"))
        QApplication.beep()

    def split_image(self, raster_layer: QgsRasterLayer, file_names: list[str]) -> bool:
        if not raster_layer or not raster_layer.isValid():
            log.critical("Raster layer isn't valid")
            return False

        self.progressBar.show()
        self.progressBar.setValue(0)

        provider = raster_layer.dataProvider()
        band_count = provider.bandCount()
        if band_count < 2:
            log.critical("BandCount < 2")
            self.progressBar.hide()
            return False
        if band_count != len(file_names):
            log.critical("BandCount != number of output files")
            self.progressBar.hide()
            return False

        extent = raster_layer.extent()
        width = raster_layer.width()
        height = raster_layer.height()
        crs = raster_layer.crs()
        for i in range(band_count):
            writer = QgsRasterFileWriter(file_names[i])
            out_provider = writer.createOneBandRaster(provider.dataType(i + 1), width, height, extent, crs)
            if out_provider is None:
                # C++ không kiểm tra nullptr (crash); ở đây báo lỗi
                log.critical("Cannot create %s", file_names[i])
                self.progressBar.hide()
                return False
            block = provider.block(i + 1, extent, width, height)
            out_provider.writeBlock(block, 1)
            del block
            del out_provider  # đóng file (delete outputDataProv)
            self.progressBar.setValue((i + 1) * 100 // band_count)
        self.progressBar.hide()
        return True
