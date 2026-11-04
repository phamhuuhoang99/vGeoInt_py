"""Port of qgsmapsavedialog.cpp — export the current map view.

The C++ dialog only wrote a plain PDF. Georeferenced outputs are added (not in the C++ app): GeoTIFF,
PNG / JPG with a world file and the CRS (.aux.xml), and a georeferenced PDF. The map is rendered by
QgsMapRendererTask (background); raster formats get their georeferencing with GDAL from the rendered
extent (rotation forced to 0 so that the image stays north-up).
"""

import os
import tempfile
from pathlib import Path

from osgeo import gdal

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsMapRendererTask,
    QgsMapSettings,
    QgsProject,
    QgsRectangle,
    QgsSettings,
)
from qgis.gui import QgsExtentGroupBox
from qgis.PyQt.QtCore import QDir, QSize, QUrl
from qgis.PyQt.QtWidgets import QComboBox, QDialog, QFileDialog, QLabel, QWidget

from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import settings

Ui_QgsMapSaveDialog = load_ui_class("app", "qgsmapsavedialog")

# key -> (label, file filter, extension)
FORMATS = {
    "pdf": ("PDF (bản in vector, không toạ độ)", "PDF (*.pdf *.PDF)", ".pdf"),
    "geotiff": ("GeoTIFF (ảnh có toạ độ)", "GeoTIFF (*.tif *.tiff)", ".tif"),
    "geopdf": ("PDF có toạ độ (GeoPDF, dạng ảnh)", "PDF (*.pdf *.PDF)", ".pdf"),
    "png": ("PNG + world file (.pgw) + hệ toạ độ", "PNG (*.png)", ".png"),
    "jpg": ("JPG + world file (.jgw) + hệ toạ độ", "JPEG (*.jpg *.jpeg)", ".jpg"),
}


def georeference(src: str, dst: str, driver: str, extent: QgsRectangle, wkt: str, dpi: int):
    """Copy the rendered image `src` to `dst` (GTiff / PDF) with the map extent and CRS."""
    options = ["COMPRESS=DEFLATE", "TILED=YES"] if driver == "GTiff" else [f"DPI={dpi}"]
    out = gdal.Translate(dst, src, format=driver, outputSRS=wkt or None, creationOptions=options,
                         outputBounds=[extent.xMinimum(), extent.yMaximum(), extent.xMaximum(), extent.yMinimum()])
    if out is None:
        raise RuntimeError(gdal.GetLastErrorMsg() or f"Không ghi được {dst}")
    out = None


def write_crs_sidecar(path: str, extent: QgsRectangle, wkt: str):
    """CRS (and extent) of a PNG / JPG in GDAL's <file>.aux.xml, read by QGIS, ArcGIS, GDAL."""
    ds = gdal.Open(path)
    width, height = ds.RasterXSize, ds.RasterYSize
    ds.SetGeoTransform((extent.xMinimum(), extent.width() / width, 0, extent.yMaximum(), 0, -extent.height() / height))
    if wkt:
        ds.SetProjection(wkt)
    ds = None


class MapSaveDialog(QDialog, Ui_QgsMapSaveDialog):
    def __init__(self, parent, map_canvas, decorations, annotations):
        super().__init__(parent)
        self.setupUi(self)
        self.main_window = parent
        self.map_canvas = map_canvas
        self.annotations = annotations
        self.decorations = list(decorations)

        ms = QgsMapSettings(map_canvas.mapSettings())
        ms.setRotation(0)
        self.extent = ms.visibleExtent()
        self.dpi = ms.outputDpi()
        self.size = QSize(ms.outputSize())

        self.mResolutionSpinBox.setValue(int(self.dpi))
        self.mExtentGroupBox.setOutputCrs(ms.destinationCrs())
        self.mExtentGroupBox.setCurrentExtent(self.extent, ms.destinationCrs())
        self.mExtentGroupBox.setOutputExtentFromCurrent()
        self.mExtentGroupBox.setMapCanvas(map_canvas)

        active = ", ".join(d.name().lower() for d in self.decorations)
        self.mDrawDecorations.setText(f"Xuất các đối tượng đồ họa: {active or 'Không có'}")

        self.mResolutionSpinBox.valueChanged.connect(self.update_dpi)
        self.mOutputWidthSpinBox.valueChanged.connect(self.update_output_width)
        self.mOutputHeightSpinBox.valueChanged.connect(self.update_output_height)
        self.mExtentGroupBox.extentChanged.connect(self.update_extent)
        self.mLockAspectRatio.lockChanged.connect(self.lock_changed)
        self.update_output_size()

        self.setWindowTitle("Xuất bản đồ")
        # Vietnamese labels of the QGIS extent widget, as in the imagery download dialogs
        from vgeoint.app.dialogs.google_earth_engine import EXTENT_WIDGET_TEXTS

        self.mExtentGroupBox.setTitleBase("Phạm vi xuất")
        for name, text in EXTENT_WIDGET_TEXTS.items():
            child = self.mExtentGroupBox.findChild(QWidget, name)
            if child is not None:
                child.setVisible(text is not None)
                if text is not None:
                    child.setText(text)
        self.format_combo = QComboBox(self)
        for key, (label, _filter, _ext) in FORMATS.items():
            self.format_combo.addItem(label, key)
        self.gridLayout.addWidget(QLabel("Định dạng", self), 6, 0)
        self.gridLayout.addWidget(self.format_combo, 6, 1)
        self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(
            settings().value("MapExport/Format", "pdf"))))
        self.okBtn.clicked.connect(self.export_map)
        self.cancelBtn.clicked.connect(self.close)

    def update_dpi(self, dpi: int):
        self.size = QSize(int(self.size.width() * dpi / self.dpi), int(self.size.height() * dpi / self.dpi))
        self.dpi = dpi
        self.update_output_size()

    def _set_extent_from_user(self):
        self.mExtentGroupBox.blockSignals(True)
        self.mExtentGroupBox.setOutputExtentFromUser(self.extent, self.mExtentGroupBox.currentCrs())
        self.mExtentGroupBox.blockSignals(False)

    def _grow_x(self, width: int):
        adjustment = (self.extent.width() * width / self.size.width() - self.extent.width()) / 2
        self.size.setWidth(width)
        self.extent.setXMinimum(self.extent.xMinimum() - adjustment)
        self.extent.setXMaximum(self.extent.xMaximum() + adjustment)

    def _grow_y(self, height: int):
        adjustment = (self.extent.height() * height / self.size.height() - self.extent.height()) / 2
        self.size.setHeight(height)
        self.extent.setYMinimum(self.extent.yMinimum() - adjustment)
        self.extent.setYMaximum(self.extent.yMaximum() + adjustment)

    def update_output_width(self, width: int):
        self._grow_x(width)
        if self.mLockAspectRatio.locked():
            ratio = self.mExtentGroupBox.ratio()
            height = int(width * ratio.height() / ratio.width())
            self.mOutputHeightSpinBox.blockSignals(True)
            self.mOutputHeightSpinBox.setValue(height)
            self.mOutputHeightSpinBox.blockSignals(False)
            self._grow_y(height)
        self._set_extent_from_user()

    def update_output_height(self, height: int):
        self._grow_y(height)
        if self.mLockAspectRatio.locked():
            ratio = self.mExtentGroupBox.ratio()
            width = int(height * ratio.width() / ratio.height())
            self.mOutputWidthSpinBox.blockSignals(True)
            self.mOutputWidthSpinBox.setValue(width)
            self.mOutputWidthSpinBox.blockSignals(False)
            self._grow_x(width)
        self._set_extent_from_user()

    def update_extent(self, extent: QgsRectangle):
        if self.mExtentGroupBox.extentState() != QgsExtentGroupBox.ExtentState.UserExtent:
            current_dpi = self.dpi
            ms = QgsMapSettings(self.map_canvas.mapSettings())
            ms.setRotation(0)
            self.dpi = ms.outputDpi()
            self.size.setWidth(int(ms.outputSize().width() * extent.width() / ms.visibleExtent().width()))
            self.size.setHeight(int(ms.outputSize().height() * extent.height() / ms.visibleExtent().height()))
            if current_dpi != self.dpi:
                self.update_dpi(int(current_dpi))
        else:
            self.size.setWidth(int(self.size.width() * extent.width() / self.extent.width()))
            self.size.setHeight(int(self.size.height() * extent.height() / self.extent.height()))
        self.update_output_size()
        self.extent = QgsRectangle(extent)
        if self.mLockAspectRatio.locked():
            self.mExtentGroupBox.setRatio(QSize(self.size.width(), self.size.height()))

    def update_output_size(self):
        for spin, value in ((self.mOutputWidthSpinBox, self.size.width()), (self.mOutputHeightSpinBox, self.size.height())):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def lock_changed(self, locked: bool):
        if locked:
            self.mExtentGroupBox.setRatio(QSize(self.mOutputWidthSpinBox.value(), self.mOutputHeightSpinBox.value()))
        else:
            self.mExtentGroupBox.setRatio(QSize(0, 0))

    def apply_map_settings(self, ms: QgsMapSettings):
        canvas = self.map_canvas
        project = QgsProject.instance()
        ms.setFlag(Qgis.MapSettingsFlag.Antialiasing, True)
        # force vector output (no caching of marker images etc.)
        ms.setFlag(Qgis.MapSettingsFlag.ForceVectorOutput, True)
        ms.setFlag(Qgis.MapSettingsFlag.DrawEditingInfo, False)
        ms.setFlag(Qgis.MapSettingsFlag.DrawSelection, True)
        ms.setDestinationCrs(canvas.mapSettings().destinationCrs())
        ms.setExtent(self.mExtentGroupBox.outputExtent())
        ms.setOutputSize(self.size)
        ms.setOutputDpi(self.mResolutionSpinBox.value())
        ms.setBackgroundColor(canvas.canvasColor())
        ms.setRotation(canvas.rotation())
        ms.setLayers(canvas.layers())
        ms.setLabelingEngineSettings(canvas.mapSettings().labelingEngineSettings())
        ms.setTransformContext(project.transformContext())
        ms.setPathResolver(project.pathResolver())

        context = QgsExpressionContext()
        context.appendScope(QgsExpressionContextUtils.globalScope())
        context.appendScope(QgsExpressionContextUtils.projectScope(project))
        context.appendScope(QgsExpressionContextUtils.mapSettingsScope(ms))
        ms.setExpressionContext(context)

    def export_pdf(self):
        """Kept for callers of the C++ name: plain PDF."""
        self.format_combo.setCurrentIndex(self.format_combo.findData("pdf"))
        self.export_map()

    def export_map(self, file_name: str | None = None) -> QgsMapRendererTask | None:
        fmt = self.format_combo.currentData()
        label, file_filter, ext = FORMATS[fmt]
        s = QgsSettings()
        if file_name is None:
            last_dir = s.value("UI/lastSaveAsImageDir", QDir.homePath())
            file_name, _ = QFileDialog.getSaveFileName(self.main_window, "Xuất bản đồ", last_dir, file_filter)
        if not file_name:
            return None
        if not Path(file_name).suffix:
            file_name += ext
        s.setValue("UI/lastSaveAsImageDir", str(Path(file_name).parent))
        settings().setValue("MapExport/Format", fmt)

        ms = QgsMapSettings()
        self.apply_map_settings(ms)
        bar = self.main_window.message_bar
        title = "Xuất bản đồ"
        if not ms.layers():
            bar.pushWarning(title, "Không thể xuất: chưa có layer nào. Vui lòng thêm ít nhất một layer.")
            return None
        if fmt != "pdf":
            ms.setRotation(0)  # georeferenced images are north-up
            if ms.flags() & Qgis.MapSettingsFlag.ForceVectorOutput:
                ms.setFlag(Qgis.MapSettingsFlag.ForceVectorOutput, False)
        extent = QgsRectangle(ms.visibleExtent())
        wkt = ms.destinationCrs().toWkt(Qgis.CrsWktVariant.PreferredGdal) if ms.destinationCrs().isValid() else ""
        dpi = int(ms.outputDpi())

        # the image QGIS renders: the final file for PDF / PNG / JPG, a temporary PNG for GeoTIFF / GeoPDF
        if fmt in ("geotiff", "geopdf"):
            handle, render_path = tempfile.mkstemp(suffix=".png", prefix="vgeoint_map_")
            os.close(handle)
            render_format = "PNG"
        else:
            render_path = file_name
            render_format = {"pdf": "PDF", "png": "PNG", "jpg": "JPG"}[fmt]
        task = QgsMapRendererTask(ms, render_path, render_format, False)
        if fmt in ("png", "jpg"):
            task.setSaveWorldFile(True)
        if self.mDrawAnnotations.isChecked():
            task.addAnnotations(QgsProject.instance().annotationManager().annotations())
        if self.mDrawDecorations.isChecked() and self.decorations:
            task.addDecorations(self.decorations)

        folder_url = QUrl.fromLocalFile(str(Path(file_name).parent)).toString()

        def finished():
            try:
                if fmt == "geotiff":
                    georeference(render_path, file_name, "GTiff", extent, wkt, dpi)
                elif fmt == "geopdf":
                    georeference(render_path, file_name, "PDF", extent, wkt, dpi)
                elif fmt in ("png", "jpg"):
                    write_crs_sidecar(file_name, extent, wkt)
            except RuntimeError as e:
                bar.pushWarning(title, f"Xuất thất bại: {e}")
                return
            finally:
                if render_path != file_name and os.path.exists(render_path):
                    os.remove(render_path)
            georef = "" if fmt == "pdf" else " (có toạ độ)"
            bar.pushSuccess(title, f'Xuất {label.split(" (")[0]}{georef} thành công tại '
                                   f'<a href="{folder_url}">{QDir.toNativeSeparators(file_name)}</a>')

        task.renderingComplete.connect(finished)
        task.errorOccurred.connect(lambda _code: bar.pushWarning(title, "Xảy ra lỗi trong quá trình xuất"))
        QgsApplication.taskManager().addTask(task)
        return task
