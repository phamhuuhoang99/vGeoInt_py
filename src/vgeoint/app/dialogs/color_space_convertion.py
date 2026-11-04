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

SQ2 = np.sqrt(2.0)
# Linear IHS model of remote sensing (ERDAS / ENVI, pan-sharpening): I = mean of R, G, B; (v1, v2) the
# chromatic plane; H = angle, S = length of (v1, v2). Rows: I, v1, v2 = RGB_TO_IHS @ (R, G, B).
RGB_TO_IHS = np.array([[1 / 3, 1 / 3, 1 / 3],
                       [-SQ2 / 6, -SQ2 / 6, 2 * SQ2 / 6],
                       [1 / SQ2, -1 / SQ2, 0.0]])
IHS_TO_RGB = np.linalg.inv(RGB_TO_IHS)


def bgr_to_ihs(bgr: np.ndarray) -> np.ndarray:
    """8-bit BGR -> 8-bit channels (H, S, I), like OpenCV's (H, S, V): H in 0-255 for 0-360°, S = |(v1, v2)|
    (at most 208 for 8-bit RGB, so not rescaled), I = (R + G + B) / 3."""
    rgb = bgr[..., ::-1].astype(np.float64)
    i, v1, v2 = np.moveaxis(rgb @ RGB_TO_IHS.T, -1, 0)
    h = (np.degrees(np.arctan2(v2, v1)) % 360.0) * 255.0 / 360.0
    sat = np.hypot(v1, v2)
    return np.clip(np.round(np.dstack((h, sat, i))), 0, 255).astype(np.uint8)


def ihs_to_bgr(hsi: np.ndarray) -> np.ndarray:
    """Inverse of bgr_to_ihs (exact up to the 8-bit rounding of H: steps of 1.4°)."""
    h = np.radians(hsi[..., 0].astype(np.float64) * 360.0 / 255.0)
    sat, i = hsi[..., 1].astype(np.float64), hsi[..., 2].astype(np.float64)
    rgb = np.dstack((i, sat * np.cos(h), sat * np.sin(h))) @ IHS_TO_RGB.T
    return np.clip(np.round(rgb[..., ::-1]), 0, 255).astype(np.uint8)


class BandConversion:
    """A conversion between band lists (natural order: band 1, 2, ...), for spaces without 3 channels.

    The OpenCV ones keep the C++ band order (bands 1-3 = R, G, B in; channels written in reverse out).
    """

    def __init__(self, n_in: int, func):
        self.n_in = n_in
        self.func = func


def rgb_to_cmyk(bands: list[np.ndarray]) -> list[np.ndarray]:
    """R, G, B (8-bit) -> C, M, Y, K (8-bit, 255 = 100 % ink): K = 1 - max(R, G, B), C = (1 - R - K) / (1 - K)..."""
    rgb = np.stack(bands[:3]).astype(np.float64) / 255.0
    k = 1.0 - rgb.max(axis=0)
    denom = np.where(k < 1.0, 1.0 - k, 1.0)
    cmy = (1.0 - rgb - k) / denom
    cmy[:, k >= 1.0] = 0.0  # black: no colour ink
    return [np.clip(np.round(c * 255), 0, 255).astype(np.uint8) for c in (*cmy, k)]


def cmyk_to_rgb(bands: list[np.ndarray]) -> list[np.ndarray]:
    """C, M, Y, K (8-bit) -> R, G, B: R = 255 (1 - C)(1 - K)..."""
    c, m, y, k = (b.astype(np.float64) / 255.0 for b in bands[:4])
    return [np.clip(np.round(255 * (1 - x) * (1 - k)), 0, 255).astype(np.uint8) for x in (c, m, y)]


# (from, to) -> OpenCV conversion code, a function of an 8-bit BGR image (IHS: not in OpenCV), or a
# BandConversion (CMYK: 4 bands). IHS, Lab and CMYK are not in the C++ app.
CONVERSIONS = {
    ("RGB", "HSV"): cv2.COLOR_BGR2HSV,
    ("RGB", "HLS"): cv2.COLOR_BGR2HLS,
    ("HSV", "RGB"): cv2.COLOR_HSV2BGR,
    ("HLS", "RGB"): cv2.COLOR_HLS2BGR,
    ("RGB", "Lab"): cv2.COLOR_BGR2Lab,  # 8-bit Lab: L*255/100, a+128, b+128
    ("Lab", "RGB"): cv2.COLOR_Lab2BGR,
    ("RGB", "IHS"): bgr_to_ihs,
    ("IHS", "RGB"): ihs_to_bgr,
    ("RGB", "CMYK"): BandConversion(3, rgb_to_cmyk),
    ("CMYK", "RGB"): BandConversion(4, cmyk_to_rgb),
}
COLOR_SPACES = ("RGB", "HSV", "HLS", "IHS", "Lab", "CMYK")


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

        for text in COLOR_SPACES:
            self.fromColorCbx.addItem(get_icon("Rgb.svg"), text)
        self.fromColorCbx.setCurrentIndex(0)
        for text in COLOR_SPACES:
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

    def convert_color(self, layer: QgsRasterLayer, code, output: str) -> str | None:
        """Convert the first 3 (CMYK: 4) bands of `layer` into `output`. Return why it failed, None on success."""
        if layer is None or not layer.isValid():
            return "Ảnh đầu vào không hợp lệ"
        prov = layer.dataProvider()
        n_in = code.n_in if isinstance(code, BandConversion) else 3
        if prov.bandCount() < n_in:
            return f"Ảnh {layer.name()} chỉ có {prov.bandCount()} kênh, cần ít nhất {n_in} kênh"
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
            inputs = [read_band_u8(layer, b) for b in range(1, n_in + 1)]
            if any(b is None for b in inputs):
                return f"Không đọc được dữ liệu ảnh {layer.name()}"
            self.progressBar.setValue(50)
            if isinstance(code, BandConversion):
                bands = code.func(inputs)
            else:
                # C++: merge(band3, band2, band1) -> cvtColor -> split ghi đè lại vào block3, block2, block1
                b1, b2, b3 = inputs
                src = np.dstack((b3, b2, b1))
                dst = code(src) if callable(code) else cv2.cvtColor(src, code)
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
            reason = f"Không hỗ trợ chuyển {from_text} sang {to_text} (chỉ hỗ trợ RGB ↔ HSV, HLS, IHS, Lab, CMYK)"
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
