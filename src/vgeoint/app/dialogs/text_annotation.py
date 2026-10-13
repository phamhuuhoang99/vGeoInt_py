"""Port of TextAnnotationDialog.cpp."""

from qgis.core import QgsFillSymbol, QgsProject, QgsTextAnnotation
from qgis.gui import QgsGui, QgsMapCanvasAnnotationItem
from qgis.PyQt.QtCore import QSize, QSizeF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPen, QPixmap
from qgis.PyQt.QtWidgets import QColorDialog, QDialog

from vgeoint.common.ui import load_ui_class

Ui_TextAnnotationDialog = load_ui_class("app", "TextAnnotationDialog")
AF = Qt.AlignmentFlag


def create_style_icon(text: str, bold: bool, italic: bool) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    font = QFont("Arial", 10)
    font.setBold(bold)
    font.setItalic(italic)
    painter.setFont(font)
    painter.setPen(QColor(40, 40, 40))
    painter.drawText(pixmap.rect(), AF.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


def create_alignment_icon(alignment: Qt.AlignmentFlag) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    pen = QPen(QColor(40, 40, 40))
    pen.setWidth(2)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    for y, length in zip((3, 6, 10, 13), (10, 7, 10, 7)):
        if alignment == AF.AlignHCenter:
            x1 = 8 - length // 2
        elif alignment == AF.AlignRight:
            x1 = 14 - length
        else:
            x1 = 2
        painter.drawLine(x1, y, x1 + length, y)
    painter.end()
    return QIcon(pixmap)


def _color_style(color: QColor) -> str:
    return f"background-color: rgb({color.red()}, {color.green()}, {color.blue()})"


class TextAnnotationDialog(QDialog, Ui_TextAnnotationDialog):
    def __init__(self, item: QgsMapCanvasAnnotationItem, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.item = item
        self.text_document = None
        self.text_color = QColor(Qt.GlobalColor.black)
        self.bg_color = QColor(Qt.GlobalColor.white)

        self.mBoldPushButton.setText("")
        self.mBoldPushButton.setIcon(create_style_icon("B", True, False))
        self.mBoldPushButton.setIconSize(QSize(16, 16))
        self.mBoldPushButton.setToolTip("In đậm")
        self.mItalicsPushButton.setText("")
        self.mItalicsPushButton.setIcon(create_style_icon("I", False, True))
        self.mItalicsPushButton.setIconSize(QSize(16, 16))
        self.mItalicsPushButton.setToolTip("In nghiêng")
        for btn, align, tip in (
            (self.mAlignLeftPushButton, AF.AlignLeft, "Căn lề trái"),
            (self.mAlignCenterPushButton, AF.AlignHCenter, "Căn giữa"),
            (self.mAlignRightPushButton, AF.AlignRight, "Căn lề phải"),
        ):
            btn.setText("")
            btn.setIcon(create_alignment_icon(align))
            btn.setToolTip(tip)
        self.backgroundTranspSbx.setValue(100)

        self.fill_symbol = QgsFillSymbol()
        self.mLayerComboBox.setAllowEmptyLayer(True)
        self.mTextEdit.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        annotation = item.annotation() if item is not None else None
        if isinstance(annotation, QgsTextAnnotation):
            doc = annotation.document()
            self.text_document = doc.clone(self) if doc is not None else None
            if self.text_document is not None:
                self.mTextEdit.setDocument(self.text_document)
            self.set_bg_color_label(annotation.fillSymbol().color())
            self.backgroundTranspSbx.setValue(int(annotation.fillSymbol().opacity() * 100))
            self.enableFloatAnnotation.setChecked(not annotation.hasFixedMapPosition())

        QgsGui.enableAutoGeometryRestore(self)

        self.set_current_font_properties_to_gui()
        self.set_current_alignment_to_gui()
        self.mFontComboBox.currentFontChanged.connect(self.change_current_format)
        self.mFontSizeSpinBox.valueChanged.connect(self.change_current_format)
        self.mBoldPushButton.toggled.connect(self.change_current_format)
        self.mItalicsPushButton.toggled.connect(self.change_current_format)
        self.mAlignLeftPushButton.clicked.connect(lambda: self._align(AF.AlignLeft))
        self.mAlignCenterPushButton.clicked.connect(lambda: self._align(AF.AlignHCenter))
        self.mAlignRightPushButton.clicked.connect(lambda: self._align(AF.AlignRight))
        self.mTextEdit.cursorPositionChanged.connect(self._cursor_moved)

        self.textColorBtn.clicked.connect(self._pick_text_color)
        self.backgroundColorBtn.clicked.connect(self._pick_bg_color)
        self.enableFloatAnnotation.toggled.connect(self.annotationDockAreaCbx.setEnabled)
        self.removeBtn.clicked.connect(self.remove_item)
        self.applyBtn.clicked.connect(self.apply_text_to_item)
        self.okBtn.clicked.connect(self._ok)
        self.cancelBtn.clicked.connect(self.close)

    def _ok(self):
        self.apply_text_to_item()
        self.accept()

    def _align(self, alignment):
        self.mTextEdit.setAlignment(alignment)
        self.set_current_alignment_to_gui()

    def _cursor_moved(self):
        self.set_current_font_properties_to_gui()
        self.set_current_alignment_to_gui()

    def _pick_text_color(self):
        color = QColorDialog.getColor(self.text_color, self, "Chọn màu chữ")
        if color.isValid():
            self.set_text_color_label(color)
            self.change_current_format()

    def _pick_bg_color(self):
        color = QColorDialog.getColor(self.bg_color, self, "Chọn màu nền")
        if color.isValid():
            self.set_bg_color_label(color)

    def apply_text_to_item(self):
        if self.item is None or self.text_document is None or self.item.annotation() is None:
            return
        annotation = self.item.annotation()
        if not isinstance(annotation, QgsTextAnnotation):
            return
        self.fill_symbol.setColor(self.bg_color)
        self.fill_symbol.setOpacity(self.backgroundTranspSbx.value() * 0.01)
        annotation.setFillSymbol(self.fill_symbol.clone())
        annotation.setMapLayer(self.mLayerComboBox.currentLayer())
        annotation.setHasFixedMapPosition(not self.enableFloatAnnotation.isChecked())

        # Auto-fit frame size to full text content after applying edits.
        self.text_document.setTextWidth(-1)
        self.text_document.adjustSize()
        doc_size = self.text_document.size()
        padding, min_w, min_h = 12.0, 24.0, 20.0
        width_px = max(min_w, doc_size.width() + padding)
        height_px = max(min_h, doc_size.height() + padding)
        screen = QGuiApplication.primaryScreen()
        dpi = screen.logicalDotsPerInch() if screen else 96.0
        px_to_mm = 25.4 / dpi
        annotation.setFrameSizeMm(QSizeF(width_px * px_to_mm, height_px * px_to_mm))

        # Pass a clone so the annotation owns its document independently of this dialog.
        annotation.setDocument(self.text_document.clone())
        self.item.update()

    def set_text_color_label(self, color: QColor):
        self.text_color = QColor(color)
        self.textColorLbl.setStyleSheet(_color_style(color))

    def set_bg_color_label(self, color: QColor):
        self.bg_color = QColor(color)
        self.backgroundColorLbl.setStyleSheet(_color_style(color))

    def change_current_format(self, *_):
        font = QFont()
        font.setFamily(self.mFontComboBox.currentFont().family())
        font.setBold(self.mBoldPushButton.isChecked())
        font.setItalic(self.mItalicsPushButton.isChecked())
        font.setPointSize(self.mFontSizeSpinBox.value())
        self.mTextEdit.setCurrentFont(font)
        self.mTextEdit.setTextColor(self.text_color)

    def _gui_widgets(self):
        return (
            self.mFontComboBox, self.mFontSizeSpinBox, self.mBoldPushButton, self.mItalicsPushButton,
            self.mAlignLeftPushButton, self.mAlignCenterPushButton, self.mAlignRightPushButton,
        )

    def block_all_signals(self, block: bool):
        for w in self._gui_widgets():
            w.blockSignals(block)

    def set_current_font_properties_to_gui(self):
        self.block_all_signals(True)
        font = self.mTextEdit.currentFont()
        self.mFontComboBox.setCurrentFont(font)
        self.mFontSizeSpinBox.setValue(max(1, font.pointSize()))
        self.mBoldPushButton.setChecked(font.bold())
        self.mItalicsPushButton.setChecked(font.italic())
        self.set_text_color_label(self.mTextEdit.textColor())
        self.block_all_signals(False)

    def set_current_alignment_to_gui(self):
        self.block_all_signals(True)
        alignment = self.mTextEdit.alignment()
        self.mAlignLeftPushButton.setChecked(bool(alignment & AF.AlignLeft))
        self.mAlignCenterPushButton.setChecked(bool(alignment & AF.AlignHCenter))
        self.mAlignRightPushButton.setChecked(bool(alignment & AF.AlignRight))
        if not any(b.isChecked() for b in self._gui_widgets()[4:]):
            self.mAlignLeftPushButton.setChecked(True)
        self.block_all_signals(False)

    def remove_item(self):
        if self.item is not None and self.item.annotation() is not None:
            QgsProject.instance().annotationManager().removeAnnotation(self.item.annotation())
            self.item = None
