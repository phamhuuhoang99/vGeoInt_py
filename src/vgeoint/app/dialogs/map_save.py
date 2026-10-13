"""Port of qgsmapsavedialog.cpp — export the current map view to PDF."""

from pathlib import Path

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
from qgis.PyQt.QtWidgets import QDialog, QFileDialog

from vgeoint.common.ui import load_ui_class

Ui_QgsMapSaveDialog = load_ui_class("app", "qgsmapsavedialog")


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

        self.okBtn.clicked.connect(self.export_pdf)
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
        s = QgsSettings()
        last_dir = s.value("UI/lastSaveAsImageDir", QDir.homePath())
        file_name, _ = QFileDialog.getSaveFileName(
            self.main_window, self.tr("Save Map As"), last_dir, self.tr("PDF Format") + " (*.pdf *.PDF)"
        )
        if not file_name:
            return
        s.setValue("UI/lastSaveAsImageDir", str(Path(file_name).parent))

        ms = QgsMapSettings()
        self.apply_map_settings(ms)
        bar = self.main_window.message_bar
        if not ms.layers():
            bar.pushWarning("Xuất PDF", "Không thể xuất PDF: chưa có layer nào. Vui lòng thêm ít nhất một layer.")
            return

        task = QgsMapRendererTask(ms, file_name, "PDF", False)
        if self.mDrawAnnotations.isChecked():
            task.addAnnotations(QgsProject.instance().annotationManager().annotations())
        if self.mDrawDecorations.isChecked() and self.decorations:
            task.addDecorations(self.decorations)

        folder_url = QUrl.fromLocalFile(str(Path(file_name).parent)).toString()
        task.renderingComplete.connect(
            lambda: bar.pushSuccess(
                "Xuất PDF", f'Xuất thành công tại <a href="{folder_url}">{QDir.toNativeSeparators(file_name)}</a>'
            )
        )
        task.errorOccurred.connect(lambda _code: bar.pushWarning("Xuất PDF", "Xảy ra lỗi trong quá trình xuất"))
        QgsApplication.taskManager().addTask(task)
