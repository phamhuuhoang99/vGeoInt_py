"""Port of ChangeDetectionDialog.cpp."""

import numpy as np
from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry
from qgis.core import (
    Qgis,
    QgsFeedback,
    QgsProject,
    QgsRasterBlock,
    QgsRasterBlockFeedback,
    QgsRasterFileWriter,
    QgsRasterLayer,
    QgsRectangle,
)
from qgis.PyQt.QtCore import QFile, QFileInfo, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication, QColorDialog, QDialog, QFileDialog

from vgeoint.app.dialogs.band_math import output_grid
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon, settings

Ui_ChangeDetectionDialog = load_ui_class("app", "ChangeDetectionDialog")


def _red(text: str) -> str:
    return f"<font color='red'>{text}</font>"


def _style(color: QColor) -> str:
    return f"background-color: rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


class ChangeDetectionDialog(QDialog, Ui_ChangeDetectionDialog):
    complete = pyqtSignal()

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.progressBar.hide()
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.output_files: list[str] = []

        s = settings()
        for prefix, default, sbx, setter in (
            ("Spread", (0, 200, 0, 255), self.spreadAlphaSbx, self.set_spread_color_label),
            ("NoChange", (200, 200, 200, 0), self.nochangeAlphaSbx, self.set_nochange_color_label),
            ("Loss", (200, 0, 0, 255), self.lossAlphaSbx, self.set_loss_color_label),
        ):
            red, green, blue, alpha = (
                int(s.value(f"ChangeDetection/{prefix}{key}", value))
                for key, value in zip(("Red", "Green", "Blue", "Alpha"), default)
            )
            sbx.setValue(alpha)
            setter(QColor(red, green, blue, alpha))

        for sbx, getter, setter in (
            (self.spreadAlphaSbx, self.spread_color_label, self.set_spread_color_label),
            (self.nochangeAlphaSbx, self.nochange_color_label, self.set_nochange_color_label),
            (self.lossAlphaSbx, self.loss_color_label, self.set_loss_color_label),
        ):
            sbx.valueChanged.connect(lambda value, g=getter, st=setter: self._set_alpha(value, g, st))

        self.browseBtn.clicked.connect(self._browse)
        self.spreadColorPickerBtn.clicked.connect(
            lambda: self._pick_color(self.spreadColorLbl, self.spreadAlphaSbx, self.set_spread_color_label)
        )
        self.nochangeColorPickerBtn.clicked.connect(
            lambda: self._pick_color(self.nochangeColorLbl, self.nochangeAlphaSbx, self.set_nochange_color_label)
        )
        self.lossColorPickerBtn.clicked.connect(
            lambda: self._pick_color(self.lossColorLbl, self.lossAlphaSbx, self.set_loss_color_label)
        )
        self.defaultBtn.clicked.connect(self._default)
        self.okBtn.clicked.connect(self.apply)
        self.cancelBtn.clicked.connect(self.close)

        self.populate()

    # BPluginInterface
    def name(self) -> str:
        return "T_ChangeDetection"

    def vn_name(self) -> str:
        return "Phát hiện thay đổi"

    def get_icon(self):
        return get_icon("ChangeDetection.svg")

    def auto_add_output_files(self) -> bool:
        return self.autoAddOutputChbx.isChecked()

    def populate(self):
        """ChangeDetectionDialog::show(): list the canvas raster layers."""
        self.beforeRasterLayerCbx.clear()
        self.afterRasterLayerCbx.clear()
        for layer in self.map_canvas.layers():
            if layer.type() == Qgis.LayerType.Raster:
                self.beforeRasterLayerCbx.addItem(get_icon("Raster.svg"), layer.name(), layer)
                self.afterRasterLayerCbx.addItem(get_icon("Raster.svg"), layer.name(), layer)

    # ---------------------------------------------------------------- colors
    def _default(self):
        # Như bản C++: chỉ đổi màu nhãn, không lưu cài đặt / không đổi ô alpha
        self.spreadColorLbl.setStyleSheet("background-color: rgba(0, 200, 0, 255)")
        self.nochangeColorLbl.setStyleSheet("background-color: rgba(200, 200, 200, 0)")
        self.lossColorLbl.setStyleSheet("background-color: rgba(200, 0, 0, 255)")

    def _set_alpha(self, value: int, getter, setter):
        color = getter()
        color.setAlpha(value)
        setter(color)

    def _pick_color(self, label, alpha_sbx, setter):
        init_color = self._label_color(label)
        new_color = QColorDialog.getColor(init_color, self, "Chọn màu nền")
        if new_color.isValid():
            new_color.setAlpha(alpha_sbx.value())
            setter(new_color)

    def _set_color_label(self, label, prefix: str, color: QColor):
        label.setStyleSheet(_style(color))
        s = settings()
        s.setValue(f"ChangeDetection/{prefix}Red", color.red())
        s.setValue(f"ChangeDetection/{prefix}Green", color.green())
        s.setValue(f"ChangeDetection/{prefix}Blue", color.blue())
        s.setValue(f"ChangeDetection/{prefix}Alpha", color.alpha())

    def set_spread_color_label(self, color: QColor):
        self._set_color_label(self.spreadColorLbl, "Spread", color)

    def set_nochange_color_label(self, color: QColor):
        self._set_color_label(self.nochangeColorLbl, "NoChange", color)

    def set_loss_color_label(self, color: QColor):
        self._set_color_label(self.lossColorLbl, "Loss", color)

    @staticmethod
    def _label_color(label) -> QColor:
        # The style sheet colour reaches the palette once the label is polished (always true once shown).
        label.ensurePolished()
        return QColor(label.palette().color(QPalette.ColorRole.Window))

    def spread_color_label(self) -> QColor:
        return self._label_color(self.spreadColorLbl)

    def nochange_color_label(self) -> QColor:
        return self._label_color(self.nochangeColorLbl)

    def loss_color_label(self) -> QColor:
        return self._label_color(self.lossColorLbl)

    # ------------------------------------------------------------------ run
    def _browse(self):
        s = settings()
        default_dir = QApplication.applicationDirPath()
        dir_ = s.value("SaveImage/Dir", default_dir)

        store_dir = ""
        file_name, _ = QFileDialog.getSaveFileName(self, "Lưu ảnh kết quả", dir_, "Rasters (*.tif *.tiff *.png *.jpg)")
        if file_name:
            store_dir = QFileInfo(file_name).dir().path()
            self.outputLedr.setText(file_name)

        if store_dir and store_dir != dir_:
            s.setValue("SaveImage/Dir", store_dir)

    def _on_progress(self, value: float):
        ivalue = int(value)
        if ivalue != self.progressBar.value():
            self.progressBar.setValue(ivalue)
        if ivalue == 100:
            self.progressBar.hide()

    def _start_progress(self, feedback: QgsFeedback):
        feedback.progressChanged.connect(self._on_progress)
        if self.progressBar.isHidden():
            self.progressBar.show()
        self.progressBar.setValue(0)

    def apply(self):
        before = self.beforeRasterLayerCbx.currentData()
        after = self.afterRasterLayerCbx.currentData()
        if not (before and before.isValid() and after and after.isValid()):
            return
        if before.id() == after.id():
            self.noticeLbl.setText(_red("Ảnh trước và sau phải khác nhau"))
            return

        output = self.outputLedr.text().strip()
        if not output:
            self.noticeLbl.setText(_red("Chưa chọn lưu ảnh kết quả"))
            return

        idx = output.rfind(".")
        if idx < 0:
            # C++ QString::insert(-1, ...) is a no-op, so every temp file would be the output itself
            idx = len(output)
        output_math = output[:idx] + "_math" + output[idx:]
        output_segmentation = output[:idx] + "_segm" + output[idx:]

        if not self.subtract_layer(output_math, before, after):
            self.noticeLbl.setText(_red("Xảy ra lỗi trong quá trình tính toán"))
            return

        result = self.segment(output_segmentation, output_math)
        QFile.remove(output_math)
        QFile.remove(output_math + ".aux.xml")
        if not result:
            self.noticeLbl.setText(_red("Xảy ra lỗi trong quá trình phân đoạn"))
            return

        result = self.fill_color(
            output, output_segmentation, self.spread_color_label(), self.nochange_color_label(), self.loss_color_label()
        )
        QFile.remove(output_segmentation)
        QFile.remove(output_segmentation + ".aux.xml")
        if not result:
            self.noticeLbl.setText(_red("Xảy ra lỗi trong quá trình đổ màu"))
            return

        self.output_files = [output]
        self.complete.emit()
        self.close()

    def subtract_layer(self, output: str, before: QgsRasterLayer, after: QgsRasterLayer) -> bool:
        extent = before.extent()
        xmin, ymin, xmax, ymax = extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()
        extent = after.extent()
        xmin = min(xmin, extent.xMinimum())
        ymin = min(ymin, extent.yMinimum())
        xmax = max(xmax, extent.xMaximum())
        ymax = max(ymax, extent.yMaximum())
        extent = QgsRectangle(xmin, ymin, xmax, ymax)

        feedback = QgsFeedback(self)
        self._start_progress(feedback)

        entry1 = QgsRasterCalculatorEntry()
        entry1.raster = before
        entry1.bandNumber = 1
        entry1.ref = "Before"
        entry2 = QgsRasterCalculatorEntry()
        entry2.raster = after
        entry2.bandNumber = 1
        entry2.ref = "After"

        calculator = QgsRasterCalculator(
            '"After" - "Before"',
            output,
            "GTiff",
            extent,
            *output_grid(extent, [before, after]),
            [entry1, entry2],
            QgsProject.instance().transformContext(),
        )
        return calculator.processCalculation(feedback) == QgsRasterCalculator.Result.Success

    def segment(self, output: str, input_: str) -> bool:
        input_lyr = QgsRasterLayer(input_, "input")
        if not input_lyr.isValid():
            return False

        extent = input_lyr.extent()
        stats = input_lyr.dataProvider().bandStatistics(1, extent=extent)  # stats = All (default)
        step = (stats.maximumValue - stats.minimumValue) / 3.0
        thresh1 = stats.minimumValue + step
        thresh2 = stats.minimumValue + 2 * step

        feedback = QgsFeedback(self)
        self._start_progress(feedback)

        entry = QgsRasterCalculatorEntry()
        entry.raster = input_lyr
        entry.bandNumber = 1
        entry.ref = "B"

        # QString::arg(double) dùng định dạng %g (6 chữ số có nghĩa)
        t1, t2 = f"{thresh1:g}", f"{thresh2:g}"
        expression = f'("B" <= {t1})*0 + ({t1} < "B" AND "B" < {t2})*127 + ({t2} <= "B")*255'

        calculator = QgsRasterCalculator(
            expression,
            output,
            "GTiff",
            extent,
            input_lyr.width(),
            input_lyr.height(),
            [entry],
            QgsProject.instance().transformContext(),
        )
        result = calculator.processCalculation(feedback)
        # Giải phóng layer để có thể xóa file tạm
        del calculator, entry, input_lyr
        return result == QgsRasterCalculator.Result.Success

    def fill_color(self, output: str, input_: str, spread: QColor, nochange: QColor, loss: QColor) -> bool:
        raster_lyr = QgsRasterLayer(input_)
        if not raster_lyr.isValid():
            return False

        feedback = QgsRasterBlockFeedback(self)
        self._start_progress(feedback)

        extent = raster_lyr.extent()
        width = raster_lyr.width()
        height = raster_lyr.height()
        input_block = raster_lyr.dataProvider().block(1, extent, width, height, feedback)
        if not input_block.convert(Qgis.DataType.Byte):
            return False

        file_writer = QgsRasterFileWriter(output)
        output_prov = file_writer.createMultiBandRaster(Qgis.DataType.Byte, width, height, extent, raster_lyr.crs(), 4)
        if output_prov is None:
            return False

        input_data = np.frombuffer(input_block.data(), dtype=np.uint8, count=width * height)
        is_loss = input_data == 0
        is_nochange = input_data == 127
        for band, (sp, nc, ls) in enumerate(
            (
                (spread.red(), nochange.red(), loss.red()),
                (spread.green(), nochange.green(), loss.green()),
                (spread.blue(), nochange.blue(), loss.blue()),
                (spread.alpha(), nochange.alpha(), loss.alpha()),
            ),
            start=1,
        ):
            data = np.where(is_loss, ls, np.where(is_nochange, nc, sp)).astype(np.uint8)
            block = QgsRasterBlock(Qgis.DataType.Byte, width, height)
            block.setData(data.tobytes())
            output_prov.writeBlock(block, band)

        del output_prov, input_block, raster_lyr
        return True
