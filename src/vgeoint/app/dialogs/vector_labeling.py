"""Port of VectorLabelingDialog.cpp."""

from qgis.core import QgsPalLayerSettings, QgsTextBufferSettings, QgsTextFormat, QgsVectorLayerSimpleLabeling
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QColorDialog, QDialog, QMessageBox

from vgeoint.common.ui import load_ui_class

Ui_VectorLabelingDialog = load_ui_class("app", "VectorLabelingDialog")


class VectorLabelingDialog(QDialog, Ui_VectorLabelingDialog):
    def __init__(self, layer=None, map_canvas=None, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.layer = layer
        self.map_canvas = map_canvas
        self.text_color = QColor(Qt.GlobalColor.black)
        self.buffer_color = QColor(Qt.GlobalColor.white)
        self.setWindowTitle("Hiển thị nhãn")
        self.setModal(True)

        self.okButton.clicked.connect(self.apply)
        self.cancelButton.clicked.connect(self.reject)
        self.textColorButton.clicked.connect(self.choose_text_color)
        self.bufferColorButton.clicked.connect(self.choose_buffer_color)
        self.enableLabelCheckBox.toggled.connect(self.on_enable_toggled)
        self.bufferCheckBox.toggled.connect(self.on_buffer_toggled)

        self.load_current_settings()

    @staticmethod
    def update_color_button(button, color: QColor):
        if button is None:
            return
        button.setStyleSheet(
            f"background-color: {color.name()}; color: {'black' if color.lightness() > 128 else 'white'}; "
            "border: 1px solid #888; border-radius: 3px; padding: 4px;"
        )
        button.setText(color.name().upper())

    def load_current_settings(self):
        if self.layer is None:
            return

        self.layerNameLabel.setText(self.layer.name())

        # Load fields
        self.fieldComboBox.clear()
        fields = self.layer.fields()
        for i in range(fields.count()):
            self.fieldComboBox.addItem(fields.at(i).name())

        self.enableLabelCheckBox.setChecked(self.layer.labelsEnabled() or fields.count() > 0)
        self.settingsGroupBox.setEnabled(self.enableLabelCheckBox.isChecked())

        # If existing labeling is present on the layer
        labeling = self.layer.labeling()
        if labeling is not None:
            pal = labeling.settings()
            idx = self.fieldComboBox.findText(pal.fieldName)
            if idx >= 0:
                self.fieldComboBox.setCurrentIndex(idx)

            fmt = pal.format()
            self.fontComboBox.setCurrentFont(fmt.font())
            self.fontSizeSpinBox.setValue(int(fmt.size() if fmt.size() > 0 else 10))
            self.boldCheckBox.setChecked(fmt.font().bold())
            self.italicCheckBox.setChecked(fmt.font().italic())

            self.text_color = fmt.color() if fmt.color().isValid() else QColor(Qt.GlobalColor.black)
            self.update_color_button(self.textColorButton, self.text_color)

            buffer = fmt.buffer()
            if buffer.enabled():
                self.bufferCheckBox.setChecked(True)
                self.buffer_color = buffer.color() if buffer.color().isValid() else QColor(Qt.GlobalColor.white)
                self.bufferSizeSpinBox.setValue(buffer.size() if buffer.size() > 0 else 1.0)
            else:
                self.bufferCheckBox.setChecked(False)
                self.buffer_color = QColor(Qt.GlobalColor.white)
                self.bufferSizeSpinBox.setValue(1.0)
            self.update_color_button(self.bufferColorButton, self.buffer_color)
        else:
            # Default settings
            self.text_color = QColor(Qt.GlobalColor.black)
            self.buffer_color = QColor(Qt.GlobalColor.white)
            self.update_color_button(self.textColorButton, self.text_color)
            self.update_color_button(self.bufferColorButton, self.buffer_color)
            self.fontSizeSpinBox.setValue(10)
            self.bufferCheckBox.setChecked(True)
            self.bufferSizeSpinBox.setValue(1.0)

        self.on_buffer_toggled(self.bufferCheckBox.isChecked())

    def on_enable_toggled(self, checked: bool):
        self.settingsGroupBox.setEnabled(checked)

    def on_buffer_toggled(self, checked: bool):
        self.bufferColorLabel.setEnabled(checked)
        self.bufferColorButton.setEnabled(checked)
        self.bufferSizeLabel.setEnabled(checked)
        self.bufferSizeSpinBox.setEnabled(checked)

    def choose_text_color(self):
        color = QColorDialog.getColor(self.text_color, self, "Chọn màu chữ")
        if color.isValid():
            self.text_color = color
            self.update_color_button(self.textColorButton, self.text_color)

    def choose_buffer_color(self):
        color = QColorDialog.getColor(self.buffer_color, self, "Chọn màu viền chữ")
        if color.isValid():
            self.buffer_color = color
            self.update_color_button(self.bufferColorButton, self.buffer_color)

    def apply(self):
        if self.layer is None:
            self.reject()
            return

        if self.enableLabelCheckBox.isChecked():
            if self.fieldComboBox.currentIndex() < 0:
                QMessageBox.warning(self, "Cảnh báo", "Vui lòng chọn trường thuộc tính để hiển thị nhãn.")
                return

            pal = QgsPalLayerSettings()
            pal.fieldName = self.fieldComboBox.currentText()
            pal.isExpression = False

            fmt = QgsTextFormat()
            font = self.fontComboBox.currentFont()
            font.setPointSize(self.fontSizeSpinBox.value())
            font.setBold(self.boldCheckBox.isChecked())
            font.setItalic(self.italicCheckBox.isChecked())
            fmt.setFont(font)
            fmt.setSize(self.fontSizeSpinBox.value())
            fmt.setColor(self.text_color)

            buffer = QgsTextBufferSettings()
            if self.bufferCheckBox.isChecked():
                buffer.setEnabled(True)
                buffer.setSize(self.bufferSizeSpinBox.value())
                buffer.setColor(self.buffer_color)
            else:
                buffer.setEnabled(False)
            fmt.setBuffer(buffer)

            pal.setFormat(fmt)
            self.layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
            self.layer.setLabelsEnabled(True)
        else:
            self.layer.setLabelsEnabled(False)

        self.layer.triggerRepaint()
        if self.map_canvas is not None:
            self.map_canvas.refresh()

        self.accept()
