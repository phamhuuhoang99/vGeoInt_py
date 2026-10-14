"""Port of ColorSpaceConvertionDialog.cpp (C++ class ColorSpaceConvertion)."""

import logging
import os

import cv2
import numpy as np
from osgeo import gdal
from qgis.core import QgsRasterLayer
from qgis.PyQt.QtCore import QCoreApplication, QFileInfo, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog

from vgeoint.app.dialogs.image_filter import (
    canvas_raster_layers,
    populate_raster_combo,
    read_band_u8,
    write_geotiff_u8,
)
from vgeoint.app.dialogs._feedback import notify_failure, notify_success
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

    def convert_color(self, layer: QgsRasterLayer, code: int, output: str) -> str | None:
        """Convert the first 3 bands of `layer` into `output`. Return why it failed, None on success."""
        if layer is None or not layer.isValid():
            return "Ảnh đầu vào không hợp lệ"
        prov = layer.dataProvider()
        if prov.bandCount() < 3:
            return f"Ảnh {layer.name()} chỉ có {prov.bandCount()} kênh, cần ít nhất 3 kênh"
        # Một byte
        if prov.dataTypeSize(1) != 1:
            return (
                f"Ảnh {layer.name()} có kiểu điểm ảnh {prov.dataType(1).name} "
                f"({prov.dataTypeSize(1) * 8}-bit), chỉ hỗ trợ ảnh 8-bit (Byte)"
            )
        folder = os.path.dirname(os.path.abspath(output))
        if not os.path.isdir(folder):
            return f"Thư mục lưu kết quả không tồn tại: {folder}"

        self.progressBar.show()
        self.progressBar.setValue(25)
        try:
            b1, b2, b3 = (read_band_u8(layer, b) for b in (1, 2, 3))
            if any(b is None for b in (b1, b2, b3)):
                return f"Không đọc được dữ liệu ảnh {layer.name()}"
            self.progressBar.setValue(50)
            # C++: merge(band3, band2, band1) -> cvtColor -> split ghi đè lại vào block3, block2, block1
            dst = cv2.cvtColor(np.dstack((b3, b2, b1)), code)
            bands = [dst[:, :, 2], dst[:, :, 1], dst[:, :, 0]]
            self.progressBar.setValue(75)
            gdal.ErrorReset()
            if not write_geotiff_u8(output, bands, layer.extent(), layer.crs()) or not os.path.exists(output):
                detail = gdal.GetLastErrorMsg()
                return f"Không ghi được file {output}" + (f": {detail}" if detail else " (file đang mở hoặc không có quyền ghi?)")
        except (cv2.error, MemoryError, OSError, RuntimeError) as e:
            log.exception("Color space conversion failed")
            return f"Lỗi khi xử lý ảnh: {e}"
        finally:
            self.progressBar.setValue(100)
            self.progressBar.hide()
        return None

    def apply(self):
        from_text = self.fromColorCbx.currentText()
        to_text = self.toColorCbx.currentText()
        output = self.outputLedr.text().strip()
        layer = self.rasterLayerCbx.currentData()
        code = CONVERSIONS.get((from_text, to_text))

        if not output:
            reason = "Chưa chọn file lưu kết quả"
        elif layer is None:
            reason = "Chưa chọn ảnh đầu vào"
        elif from_text == to_text:
            reason = f"Không gian màu nguồn và đích giống nhau ({from_text})"
        elif code is None:
            reason = f"Không hỗ trợ chuyển {from_text} sang {to_text} (chỉ hỗ trợ RGB ↔ HSV, RGB ↔ HLS)"
        else:
            reason = self.convert_color(layer, code, output)

        if reason is None:
            log.info("Convert %s to %s succeeded", from_text, to_text)
            self.noticeLbl.setText(_green("Chuyển đổi thành công"))
            notify_success(self.vn_name(), f"Chuyển {from_text} sang {to_text} thành công", output)
            # Lưu đường dẫn kết quả và thông báo hoàn thành
            self._output_files = [output]
            self.complete.emit()
        else:
            log.critical("Convert %s to %s failed: %s", from_text, to_text, reason)
            self.noticeLbl.setText(_red(f"Chuyển đổi thất bại: {reason}"))
            notify_failure(self.vn_name(), f"Chuyển đổi thất bại: {reason}")
        QApplication.beep()
