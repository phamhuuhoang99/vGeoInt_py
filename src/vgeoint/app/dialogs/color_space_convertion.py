"""Port of ColorSpaceConvertionDialog.cpp (C++ class ColorSpaceConvertion)."""

import logging
import os

import cv2
import numpy as np
from qgis.core import QgsRasterLayer
from qgis.PyQt.QtCore import QCoreApplication, QFileInfo, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog

from vgeoint.app.dialogs.image_filter import (
    canvas_raster_layers,
    populate_raster_combo,
    read_band_u8,
    write_geotiff_u8,
)
from vgeoint.app.plugins import RASTER
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon, settings

log = logging.getLogger(__name__)

Ui_ColorSpaceConvertionDialog = load_ui_class("app", "ColorSpaceConvertionDialog")

T_COLOR_SPACE_CONVERTION = "T_ColorSpaceConvertionPlugin"

# (from, to) -> OpenCV conversion code
CONVERSIONS = {
    ("RGB", "HSV"): cv2.COLOR_BGR2HSV,
    ("RGB", "HLS"): cv2.COLOR_BGR2HLS,
    ("HSV", "RGB"): cv2.COLOR_HSV2BGR,
    ("HLS", "RGB"): cv2.COLOR_HLS2BGR,
}


def _red(text: str) -> str:
    return f"<font color='red'>{text}</font>"


def _green(text: str) -> str:
    return f"<font color='green'>{text}</font>"


class ColorSpaceConvertionDialog(QDialog, Ui_ColorSpaceConvertionDialog):
    complete = pyqtSignal()

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setModal(True)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self._output_files: list[str] = []
        self._raster_layers: list[QgsRasterLayer] = []
        self.setWindowIcon(self.get_icon())
        self.setWindowTitle(self.vn_name())
        self.progressBar.hide()

        for text in ("RGB", "HSV", "HLS"):
            self.fromColorCbx.addItem(get_icon("Rgb.svg"), text)
        self.fromColorCbx.setCurrentIndex(0)
        for text in ("RGB", "HSV", "HLS"):
            self.toColorCbx.addItem(get_icon("Rgb.svg"), text)
        self.toColorCbx.setCurrentIndex(1)

        self.browseBtn.clicked.connect(self._browse)
        self.cancelBtn.clicked.connect(self.close)
        self.okBtn.clicked.connect(self.apply)
        # C++ gọi show() (bị override) trong constructor: chỉ nạp danh sách raster layer
        self.populate_raster_layers()

    # BPluginInterface contract
    def name(self) -> str:
        return T_COLOR_SPACE_CONVERTION

    def vn_name(self) -> str:
        return "Chuyển đổi không gian màu"

    def get_icon(self):
        return get_icon("ColorSpace.svg")

    def auto_add_output_files(self) -> bool:
        return self.autoAddOutputChbx.isChecked()

    def output_files(self) -> list[str]:
        return list(self._output_files)

    def output_data_type(self) -> int:
        return RASTER

    def populate_raster_layers(self):
        self._raster_layers = canvas_raster_layers(self.map_canvas)
        populate_raster_combo(self.rasterLayerCbx, self._raster_layers, self.layer_tree_view)

    def _browse(self):
        s = settings()
        directory = s.value("SaveImage/Dir", QCoreApplication.applicationDirPath())
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Lưu ảnh kết quả", directory, "Rasters (*.tif *.tiff *.png *.jpg)"
        )
        store_dir = ""
        if file_name:
            store_dir = QFileInfo(file_name).dir().path()
            self.outputLedr.setText(file_name)
        if store_dir and store_dir != directory:
            s.setValue("SaveImage/Dir", store_dir)

    def convert_color(self, layer: QgsRasterLayer, code: int, output: str) -> bool:
        if layer is None or not layer.isValid():
            log.critical("Raster is not valid")
            return False
        prov = layer.dataProvider()
        if prov.bandCount() < 3:
            log.critical("BandCount < 3")
            return False

        self.progressBar.show()
        self.progressBar.setValue(0)
        self.progressBar.setValue(25)

        # Một byte
        if prov.dataTypeSize(1) != 1:
            log.critical("PixelType is unsupported")
            self.progressBar.hide()
            return False

        self.progressBar.setValue(50)
        b1, b2, b3 = (read_band_u8(layer, b) for b in (1, 2, 3))
        # C++: merge(band3, band2, band1) -> cvtColor -> split ghi đè lại vào block3, block2, block1
        dst = cv2.cvtColor(np.dstack((b3, b2, b1)), code)
        bands = [dst[:, :, 2], dst[:, :, 1], dst[:, :, 0]]
        self.progressBar.setValue(75)

        ok = write_geotiff_u8(output, bands, layer.extent(), layer.crs())
        self.progressBar.setValue(100)
        self.progressBar.hide()
        return ok and os.path.exists(output)

    def apply(self):
        from_text = self.fromColorCbx.currentText()
        to_text = self.toColorCbx.currentText()
        output = self.outputLedr.text()
        if not output.strip():
            log.critical("Convert %s to %s failed", from_text, to_text)
            self.noticeLbl.setText(_red("Chưa chọn thư mục lưu kết quả"))
            return

        layer = self.rasterLayerCbx.currentData()
        if layer is None or not layer.isValid():
            log.critical("Raster is not valid")
            return

        code = CONVERSIONS.get((from_text, to_text))
        result = code is not None and self.convert_color(layer, code, output)
        if result:
            log.info("Convert %s to %s succeeded", from_text, to_text)
            self.noticeLbl.setText(_green("Chuyển đổi thành công"))
            # Lưu đường dẫn kết quả và thông báo hoàn thành
            self._output_files = [output]
            self.complete.emit()
        else:
            log.critical("Convert %s to %s failed", from_text, to_text)
            self.noticeLbl.setText(_red("Chuyển đổi thất bại"))
        QApplication.beep()
