"""Port of ImageConcatenatingDialog.cpp."""

import logging

from qgis.core import QgsRasterFileWriter, QgsRasterLayer
from qgis.PyQt.QtCore import QFileInfo, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog, QListWidgetItem

from vgeoint.app.dialogs.color_composite import fill_raster_layer_combo
from vgeoint.app.dialogs.image_split import green, red
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon, settings

Ui_ImageConcatenatingDialog = load_ui_class("app", "ImageConcatenatingDialog")
log = logging.getLogger(__name__)
USER_ROLE = Qt.ItemDataRole.UserRole


class ImageConcatenatingDialog(QDialog, Ui_ImageConcatenatingDialog):
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

        self.addBtn.clicked.connect(self._add)
        self.removeBtn.clicked.connect(self._remove)
        self.upBtn.clicked.connect(self._up)
        self.downBtn.clicked.connect(self._down)
        self.selectFileNameBtn.clicked.connect(self._select_file_name)
        self.okBtn.clicked.connect(self._ok)
        self.cancelBtn.clicked.connect(self.close)
        self.populate()

    # BPluginInterface
    def name(self) -> str:
        return "T_ImageConcatenating"

    def vn_name(self) -> str:
        return "Gộp kênh ảnh"

    def get_icon(self):
        return get_icon("ConcatenateImages.svg")

    def auto_add_output_files(self) -> bool:
        return self.autoAddOutputChbx.isChecked()

    def populate(self):
        """BPluginInterface::show() of the C++ dialog: list the canvas raster layers."""
        self.raster_layers = fill_raster_layer_combo(self.rasterLayerCbx, self.map_canvas, self.layer_tree_view)

    def _ok(self):
        self.apply()
        self.close()

    def _add(self):
        raster_layer = self.rasterLayerCbx.currentData()
        if raster_layer and raster_layer.isValid():
            item = QListWidgetItem(get_icon("Raster.svg"), raster_layer.name(), self.bandLswg)
            item.setData(USER_ROLE, self.raster_layers.index(raster_layer))

    def _remove(self):
        item = self.bandLswg.currentItem()
        if item:
            self.bandLswg.takeItem(self.bandLswg.row(item))

    def _up(self):
        idx = self.bandLswg.currentRow()
        if 0 < idx < self.bandLswg.count():
            item = self.bandLswg.takeItem(idx)
            self.bandLswg.insertItem(idx - 1, item)
            self.bandLswg.setCurrentRow(idx - 1)

    def _down(self):
        idx = self.bandLswg.currentRow()
        if 0 <= idx < self.bandLswg.count() - 1:
            item = self.bandLswg.takeItem(idx)
            self.bandLswg.insertItem(idx + 1, item)
            self.bandLswg.setCurrentRow(idx + 1)

    def _select_file_name(self):
        s = settings()
        directory = s.value("AddRasterLayer/Dir", QApplication.applicationDirPath())
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Đặt ảnh kết quả", directory, "Rasters (*.tif *.tiff *.png *.jpg)"
        )
        if file_name:
            self.outputFileNameLedr.setText(file_name)
            s.setValue("AddRasterLayer/Dir", QFileInfo(file_name).dir().path())

    def _selected_layers(self) -> list[QgsRasterLayer]:
        return [self.raster_layers[int(self.bandLswg.item(i).data(USER_ROLE))] for i in range(self.bandLswg.count())]

    def apply(self):
        if self.bandLswg.count() == 0:
            log.critical("Concatenate images failed")
            self.noticeLbl.setText(red("Chưa có ảnh nào được chọn"))
            return

        if not self.outputFileNameLedr.text().strip():
            log.critical("Concatenate images failed")
            self.noticeLbl.setText(red("Chưa đặt ảnh kết quả"))
            return

        raster_layers = self._selected_layers()
        extent = raster_layers[0].extent()
        crs = raster_layers[0].crs()
        same = all(lyr.extent() == extent and lyr.crs() == crs for lyr in raster_layers[1:])

        if same:
            if self.concatenate_images(raster_layers, self.outputFileNameLedr.text()):
                log.info("Concatenate images succeeded")
                self.noticeLbl.setText(green("Gộp kênh ảnh đã hoàn thành"))
                # Lưu đường dẫn kết quả và thông báo hoàn thành
                self.output_files = [self.outputFileNameLedr.text()]
                self.complete.emit()
            else:
                log.critical("Concatenate images failed")
                self.noticeLbl.setText(red("Gộp kênh ảnh thất bại"))
        else:
            log.critical("Concatenate images failed")
            self.noticeLbl.setText(red("Các ảnh không cùng khu vực hoặc hệ tọa độ"))
        QApplication.beep()

    def concatenate_images(self, raster_layers: list[QgsRasterLayer], output: str) -> bool:
        self.progressBar.show()
        self.progressBar.setValue(0)

        providers = [lyr.dataProvider() for lyr in raster_layers]
        band_count = sum(p.bandCount() for p in providers)

        width = raster_layers[0].width()
        height = raster_layers[0].height()
        crs = raster_layers[0].crs()
        data_type = providers[0].dataType(1)
        extent = raster_layers[0].extent()

        writer = QgsRasterFileWriter(output)
        out_provider = writer.createMultiBandRaster(data_type, width, height, extent, crs, band_count)
        if out_provider is None:
            log.critical("Output QgsRasterDataProvider is nullptr")
            self.progressBar.hide()
            return False

        band_idx = 1
        for provider in providers:
            for i in range(provider.bandCount()):
                block = provider.block(i + 1, extent, width, height)
                out_provider.writeBlock(block, band_idx)
                band_idx += 1
                self.progressBar.setValue((band_idx - 1) * 100 // band_count)
        del out_provider  # đóng file (delete outputDataProv)

        self.progressBar.hide()
        return True
