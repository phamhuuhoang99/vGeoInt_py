"""Port of ImageFilterDialog.cpp."""

import logging

import cv2
import numpy as np
from osgeo import gdal
from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsRasterLayer, QgsRectangle
from qgis.PyQt.QtCore import QCoreApplication, QFileInfo, pyqtSignal
from qgis.PyQt.QtGui import QImage, QPixmap
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox

from vgeoint.app.dialogs._feedback import notify_failure, notify_success
from vgeoint.app.plugins import RASTER
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon, settings

log = logging.getLogger(__name__)

Ui_ImageFilterDialog = load_ui_class("app", "ImageFilterDialog")

T_IMAGE_FILTER = "T_ImageFilterPlugin"

LOC_TB = "LOC_TB"
LOC_TV = "LOC_TV"
LOC_GAUSS = "LOC_GAUSS"
LOC_SOBEL = "LOC_SOBEL"
LOC_SCHARR = "LOC_SCHARR"
LOC_CANNY = "LOC_CANNY"


# ----------------------------------------------------------------- raster helpers (shared with color_space_convertion)
def canvas_raster_layers(map_canvas) -> list[QgsRasterLayer]:
    return [lyr for lyr in map_canvas.layers() if lyr.type() == Qgis.LayerType.Raster]


def populate_raster_combo(combo, raster_layers, layer_tree_view):
    """Fill the combo with raster layers and select the layer selected in the layer tree (C++ populateRasterLayers)."""
    combo.clear()
    for layer in raster_layers:
        combo.addItem(get_icon("Raster.svg"), layer.name(), layer)

    selected = layer_tree_view.selectedLayers() if layer_tree_view is not None else []
    if selected and selected[0].type() == Qgis.LayerType.Raster:
        ids = [lyr.id() for lyr in raster_layers]
        combo.setCurrentIndex(ids.index(selected[0].id()) if selected[0].id() in ids else -1)
    else:
        combo.setCurrentIndex(0)


def read_band_u8(layer: QgsRasterLayer, band: int) -> np.ndarray | None:
    """Read a whole band through the data provider as uint8 (C++: cv::Mat CV_8U on block->bits()).

    Return None when the band is not 1 byte per pixel.
    """
    width, height = layer.width(), layer.height()
    block = layer.dataProvider().block(band, layer.extent(), width, height)
    if block is None or block.dataTypeSize() != 1:
        return None
    return np.frombuffer(bytes(block.data()), dtype=np.uint8, count=width * height).reshape(height, width).copy()


def write_geotiff_u8(path: str, bands: list[np.ndarray], extent: QgsRectangle, crs: QgsCoordinateReferenceSystem):
    """Write Byte bands like QgsRasterFileWriter(path) (GTiff driver, whatever the file extension)."""
    height, width = bands[0].shape
    ds = gdal.GetDriverByName("GTiff").Create(path, width, height, len(bands), gdal.GDT_Byte)
    if ds is None:
        return False
    ds.SetGeoTransform(
        (extent.xMinimum(), extent.width() / width, 0.0, extent.yMaximum(), 0.0, -extent.height() / height)
    )
    if crs.isValid():
        ds.SetProjection(crs.toWkt(Qgis.CrsWktVariant.PreferredGdal))
    for i, data in enumerate(bands, start=1):
        ds.GetRasterBand(i).WriteArray(data)
    ds.FlushCache()
    ds = None
    return True


def gray_pixmap(img: np.ndarray | None) -> QPixmap:
    if img is None or img.size == 0:
        return QPixmap()
    img = np.ascontiguousarray(img, dtype=np.uint8)
    h, w = img.shape
    qimage = QImage(img.data, w, h, int(img.strides[0]), QImage.Format.Format_Grayscale8)
    return QPixmap.fromImage(qimage.copy())


# ----------------------------------------------------------------- dialog
class ImageFilterDialog(QDialog, Ui_ImageFilterDialog):
    complete = pyqtSignal()

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setModal(True)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self._output_files: list[str] = []
        self._raster_layers: list[QgsRasterLayer] = []
        self._src_image: np.ndarray | None = None
        self.setWindowTitle(self.vn_name())
        self.setWindowIcon(self.get_icon())
        self._init_filters()

        self.filterTypeCbx.currentIndexChanged.connect(self._filter_type_changed)
        self.viewBtn.clicked.connect(self.view)
        self.browseBtn.clicked.connect(self._browse)
        self.rasterLayerCbx.currentIndexChanged.connect(self.raster_layer_changed)
        self.bandCbx.currentIndexChanged.connect(self.raster_band_changed)
        self.okBtn.clicked.connect(self._ok)
        self.cancelBtn.clicked.connect(self.close)

        self._show_widget(self.averagingWidget)
        self.populate_raster_layers()

    # BPluginInterface contract
    def name(self) -> str:
        return T_IMAGE_FILTER

    def vn_name(self) -> str:
        return "Lọc ảnh"

    def get_icon(self):
        return get_icon("ImageFilter.svg")

    def auto_add_output_files(self) -> bool:
        return self.autoAddOutputChbx.isChecked()

    def output_files(self) -> list[str]:
        return list(self._output_files)

    def output_data_type(self) -> int:
        return RASTER

    def _init_filters(self):
        self.filterTypeCbx.addItem(get_icon("SmoothFilter.svg"), "Trung bình", LOC_TB)
        self.filterTypeCbx.addItem(get_icon("SmoothFilter.svg"), "Trung vị", LOC_TV)
        self.filterTypeCbx.addItem(get_icon("SmoothFilter.svg"), "Gaussian", LOC_GAUSS)
        self.filterTypeCbx.addItem(get_icon("EdgeFilter.svg"), "Sobel", LOC_SOBEL)
        self.filterTypeCbx.addItem(get_icon("EdgeFilter.svg"), "Scharr", LOC_SCHARR)
        self.filterTypeCbx.addItem(get_icon("EdgeFilter.svg"), "Canny", LOC_CANNY)

    def _show_widget(self, widget):
        self.stackedWidget.setCurrentWidget(widget)
        self.stackedWidget.setFixedSize(widget.sizeHint())
        self.adjustSize()

    def _filter_type_changed(self, _idx: int):
        widget = {
            LOC_TB: self.averagingWidget,
            LOC_TV: self.medianWidget,
            LOC_GAUSS: self.gaussianWidget,
            LOC_SOBEL: self.sobelWidget,
            LOC_SCHARR: self.scharrWidget,
            LOC_CANNY: self.cannyWidget,
        }.get(self.filterTypeCbx.currentData())
        if widget is not None:
            self.stackedWidget.setCurrentWidget(widget)
            self.stackedWidget.setFixedSize(widget.sizeHint())
        self.adjustSize()

    def _browse(self):
        s = settings()
        directory = s.value("AddRasterLayer/Dir", QCoreApplication.applicationDirPath())
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Đặt ảnh kết quả", directory, "Rasters (*.tif *.tiff *.png *.jpg)"
        )
        if file_name:
            self.outputFileLedr.setText(file_name)
            s.setValue("AddRasterLayer/Dir", QFileInfo(file_name).dir().path())

    def populate_raster_layers(self):
        if self.map_canvas is None:
            return
        self._raster_layers = canvas_raster_layers(self.map_canvas)
        populate_raster_combo(self.rasterLayerCbx, self._raster_layers, self.layer_tree_view)

    def raster_layer_changed(self, idx: int):
        if idx < 0 or idx >= self.rasterLayerCbx.count():
            return
        layer = self.rasterLayerCbx.itemData(idx)
        if layer is not None and layer.isValid():
            self.bandCbx.clear()
            for i in range(1, layer.bandCount() + 1):
                self.bandCbx.addItem(get_icon("Band.svg"), f"Kênh {i}", i)
            self.bandCbx.setCurrentIndex(0)

            img = read_band_u8(layer, 1)
            if img is not None:
                self._src_image = img
                self.srcImageLbl.setPixmap(gray_pixmap(img))

    def raster_band_changed(self, idx: int):
        if idx < 0 or idx >= self.bandCbx.count():
            return
        band = int(self.bandCbx.currentData())
        layer = self.rasterLayerCbx.currentData()
        if layer is not None and layer.isValid():
            img = read_band_u8(layer, band)
            if img is not None:
                self._src_image = img
                self.srcImageLbl.setPixmap(gray_pixmap(img))

    def filter(self, src: np.ndarray) -> np.ndarray | None:
        """Apply the selected filter; None when no result (invalid Canny thresholds or OpenCV error)."""
        filter_type = self.filterTypeCbx.currentData()
        try:
            if filter_type == LOC_TB:
                w = self.averagingWidget
                return cv2.blur(src, (w.colSbx.value(), w.rowSbx.value()))
            if filter_type == LOC_TV:
                return cv2.medianBlur(src, self.medianWidget.kernelSbx.value())
            if filter_type == LOC_GAUSS:
                w = self.gaussianWidget
                return cv2.GaussianBlur(
                    src, (w.colSbx.value(), w.rowSbx.value()), w.sigmaXSbx.value(), sigmaY=w.sigmaYSbx.value()
                )
            if filter_type == LOC_SOBEL:
                w = self.sobelWidget
                img = src.copy()
                if w.gaussFilterChbx.isChecked():
                    img = cv2.GaussianBlur(img, (w.colSbx.value(), w.rowSbx.value()), 0)
                dx, dy = (1, 0) if w.xAxisRbtn.isChecked() else (0, 1)
                img_16s = cv2.Sobel(img, cv2.CV_16S, dx, dy, ksize=w.kernelSbx.value())
                return cv2.convertScaleAbs(img_16s)
            if filter_type == LOC_SCHARR:
                w = self.scharrWidget
                img = src.copy()
                if w.gaussFilterChbx.isChecked():
                    img = cv2.GaussianBlur(img, (w.colSbx.value(), w.rowSbx.value()), 0)
                dx, dy = (1, 0) if w.xAxisRbtn.isChecked() else (0, 1)
                return cv2.convertScaleAbs(cv2.Scharr(img, cv2.CV_16S, dx, dy))
            if filter_type == LOC_CANNY:
                w = self.cannyWidget
                low = float(w.lowThresholdSbx.value())
                high = float(w.highThresholdSbx.value())
                if high <= low:
                    QMessageBox.warning(self, "Lỗi nhập liệu", "Ngưỡng cận trên phải lớn hơn cận dưới")
                    return None
                img = src.copy()
                if w.averagingFilterChbx.isChecked():
                    img = cv2.blur(img, (w.colSbx.value(), w.rowSbx.value()))
                return cv2.Canny(img, low, high, apertureSize=w.kernelSbx.value())
        except cv2.error:
            # C++: cv::Exception không được bắt (vd. Canny kernel > 7) -> crash
            log.exception("Image filter failed")
        return None

    def view(self):
        if self._src_image is not None:
            result = self.filter(self._src_image.copy())
            self.dstImageLbl.setPixmap(gray_pixmap(result))

    def _ok(self):
        # The C++ closed the dialog whatever happened, hiding the result; keep it open on failure.
        if self.apply():
            self.close()

    def _fail(self, text: str) -> bool:
        log.critical(text)
        notify_failure(self.vn_name(), text)
        return False

    def apply(self) -> bool:
        layer = self.rasterLayerCbx.currentData()
        if layer is None or not layer.isValid():
            return self._fail("Chưa chọn raster layer")
        band = int(self.bandCbx.currentData())
        if layer.dataProvider().dataTypeSize(band) != 1:
            return self._fail("Chỉ hỗ trợ ảnh 8 bit")
        output = self.outputFileLedr.text()
        if not output:
            # C++: QgsRasterFileWriter("") -> null provider -> crash
            return self._fail("Chưa chọn ảnh kết quả")

        src = read_band_u8(layer, band)
        self._src_image = src
        result = self.filter(src)
        # C++: kết quả rỗng (Canny sai ngưỡng) -> ghi lại kênh gốc
        out = src if result is None else result
        if not write_geotiff_u8(output, [out], layer.extent(), layer.crs()):
            return self._fail(f"Không thể ghi {output}")

        self._output_files = [output]
        notify_success(self.vn_name(), "Lọc ảnh đã hoàn thành", output)
        self.complete.emit()
        return True
