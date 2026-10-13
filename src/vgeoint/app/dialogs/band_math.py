"""Port of BandMathDialog.cpp."""

from qgis.analysis import QgsRasterCalcNode, QgsRasterCalculator, QgsRasterCalculatorEntry
from qgis.core import QgsFeedback, QgsProject, QgsRasterLayer, QgsRectangle
from qgis.PyQt.QtCore import QFileInfo, pyqtSignal
from qgis.PyQt.QtWidgets import QApplication, QDialog, QFileDialog

from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon, settings

Ui_BandMathDialog = load_ui_class("app", "BandMathDialog")


def _green(text: str) -> str:
    return f"<font color='green'>{text}</font>"


def _red(text: str) -> str:
    return f"<font color='red'>{text}</font>"


# Button -> text inserted into the expression editor
_OPERATOR_BUTTONS = {
    "mPlusPushButton": " + ",
    "mMinusPushButton": " - ",
    "mMultiplyPushButton": " * ",
    "mDividePushButton": " / ",
    "mSqrtButton": " sqrt ( ",
    "mCosButton": " cos ( ",
    "mSinButton": " sin ( ",
    "mASinButton": " asin ( ",
    "mExpButton": " ^ ",
    "mLnButton": " ln ( ",
    "mLogButton": " log10 ( ",
    "mNotEqualButton": " != ",
    "mTanButton": " tan ( ",
    "mACosButton": " acos ( ",
    "mATanButton": " atan ( ",
    "mOpenBracketPushButton": " ( ",
    "mCloseBracketPushButton": " ) ",
    "mLessButton": " < ",
    "mGreaterButton": " > ",
    "mEqualButton": " = ",
    "mLesserEqualButton": " <= ",
    "mGreaterEqualButton": " >= ",
    "mAndButton": " AND ",
    "mOrButton": " OR ",
}


class BandMathDialog(QDialog, Ui_BandMathDialog):
    complete = pyqtSignal()

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.setupUi(self)
        self.progressBar.hide()
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.output_files: list[str] = []
        self._entries: list[QgsRasterCalculatorEntry] = []
        self._raster_layers: list[QgsRasterLayer] = []

        self.okBtn.clicked.connect(self.apply)
        self.cancelBtn.clicked.connect(self.close)
        self.clearExpressionBtn.clicked.connect(self.expressionTder.clear)
        self.checkExpressionBtn.clicked.connect(self._check_expression_clicked)
        self.bandLswg.itemDoubleClicked.connect(
            lambda item: self.expressionTder.insertPlainText(self.quote_band_entry(item.text()))
        )
        self.browseBtn.clicked.connect(self._browse)
        for button_name, text in _OPERATOR_BUTTONS.items():
            getattr(self, button_name).clicked.connect(lambda _=False, t=text: self.expressionTder.insertPlainText(t))

        self.populate()

    # BPluginInterface
    def name(self) -> str:
        return "R_BandMathPlugin"

    def vn_name(self) -> str:
        return "Tính toán trên ảnh"

    def get_icon(self):
        return get_icon("BandMath.svg")

    def auto_add_output_files(self) -> bool:
        return self.autoAddOutputChbx.isChecked()

    def populate(self):
        """BandMathDialog::show(): list every band of the project's GDAL raster layers."""
        self._entries.clear()
        self.bandLswg.clear()
        self._raster_layers.clear()
        layers = QgsProject.instance().mapLayers()
        for layer_id in sorted(layers):  # QMap iterates in key order
            rlayer = layers[layer_id]
            if isinstance(rlayer, QgsRasterLayer) and rlayer.dataProvider() and rlayer.dataProvider().name() == "gdal":
                for i in range(rlayer.bandCount()):
                    entry = QgsRasterCalculatorEntry()
                    entry.raster = rlayer
                    entry.bandNumber = i + 1
                    entry.ref = f"{rlayer.name()}@k{i + 1}"
                    self._entries.append(entry)
                    self.bandLswg.addItem(entry.ref)
                    self._raster_layers.append(rlayer)

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

    def _check_expression_clicked(self):
        if self.check_expression():
            self.noticeLbl.setText(_green("Biểu thức hợp lệ"))
        else:
            self.noticeLbl.setText(_red("Biểu thức không hợp lệ"))

    def _on_progress(self, value: float):
        ivalue = int(value)
        if ivalue != self.progressBar.value():
            self.progressBar.setValue(ivalue)
        if ivalue == 100:
            self.progressBar.hide()

    def apply(self):
        output = self.outputLedr.text().strip()
        if output == "":
            return

        expression = self.expressionTder.toPlainText()
        if not self.check_expression():
            self.noticeLbl.setText(_red("Biểu thức không hợp lệ"))
            return

        entries = []
        # C++ left ymin/ymax uninitialised when no band is referenced; start at 0 instead.
        xmin, ymin, xmax, ymax = 1.0, 0.0, 0.0, 0.0
        for entry, layer in zip(self._entries, self._raster_layers):
            if entry.ref in expression:
                entries.append(entry)
                extent = layer.extent()
                if xmin > xmax:
                    xmin, ymin = extent.xMinimum(), extent.yMinimum()
                    xmax, ymax = extent.xMaximum(), extent.yMaximum()
                else:
                    xmin = min(xmin, extent.xMinimum())
                    ymin = min(ymin, extent.yMinimum())
                    xmax = max(xmax, extent.xMaximum())
                    ymax = max(ymax, extent.yMaximum())
        extent = QgsRectangle(xmin, ymin, xmax, ymax)

        feedback = QgsFeedback(self)
        feedback.progressChanged.connect(self._on_progress)
        self.progressBar.show()
        self.progressBar.setValue(0)

        # Số cột/hàng = độ rộng/cao của extent (đơn vị bản đồ), giữ nguyên như bản C++
        calculator = QgsRasterCalculator(
            expression,
            output,
            "GTiff",
            extent,
            int(extent.width()),
            int(extent.height()),
            entries,
            QgsProject.instance().transformContext(),
        )
        result = calculator.processCalculation(feedback)
        if result == QgsRasterCalculator.Result.Success:
            self.output_files = [output]
            if self.auto_add_output_files():
                new_layer = QgsRasterLayer(output, QFileInfo(output).baseName())
                if new_layer.isValid():
                    QgsProject.instance().addMapLayer(new_layer)
            QApplication.beep()
            self.complete.emit()
            self.close()
        else:
            self.noticeLbl.setText(_red(f"Xảy ra lỗi: Code = {int(result.value)}"))
            QApplication.beep()

    @staticmethod
    def quote_band_entry(layer_name: str) -> str:
        return '"' + layer_name.replace('"', '\\"') + '"'

    def check_expression(self) -> bool:
        return QgsRasterCalcNode.parseRasterCalcString(self.expressionTder.toPlainText(), "") is not None
