"""Port of CoordinateWidget.cpp and ScaleWidget.cpp."""

from qgis.core import QgsPointXY, QgsProject
from qgis.gui import QgsMapCanvas, QgsScaleComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from vgeoint.common.utils import format_coordinate_for_project, get_size_text


class CoordinateWidget(QWidget):
    def __init__(self, parent: QWidget, map_canvas: QgsMapCanvas):
        super().__init__(parent)
        self.map_canvas = map_canvas
        self.precision = 8

        self.label = QLabel("GEO (WGS 84)", self)
        self.label.setMargin(3)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setFrameStyle(QFrame.Shape.NoFrame.value)

        self.coord_ledr = QLineEdit(self)
        self.coord_ledr.setFixedWidth(120)
        self.coord_ledr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.coord_ledr.setContentsMargins(0, 0, 0, 0)

        self.geo_ledr = QLineEdit(self)
        self.geo_ledr.setFixedWidth(120)
        self.geo_ledr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.geo_ledr.setContentsMargins(0, 0, 0, 0)

        self.button = QPushButton(">", self)
        self.button.setToolTip("Đi tới tọa độ")
        self.button.setFixedSize(self.button.height(), self.button.height())
        self.button.setContentsMargins(0, 0, 0, 0)

        layout = QHBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.setSpacing(5)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        layout.addWidget(self.coord_ledr)
        layout.addWidget(self.geo_ledr)
        layout.addWidget(self.button)
        self.map_canvas.xyCoordinates.connect(self.show_mouse_coordinates)

    def set_text(self, text: str):
        self.label.setText(text)

    def set_precision(self, precision: int):
        self.precision = precision

    def show_mouse_coordinates(self, p: QgsPointXY):
        if not self.map_canvas.layers():
            self.coord_ledr.setText("")
            self.geo_ledr.setText("")
            return

        coord_text, geo_text = format_coordinate_for_project(
            QgsProject.instance(), p, self.map_canvas.mapSettings().destinationCrs(), self.precision
        )
        for edit, text in ((self.coord_ledr, coord_text), (self.geo_ledr, geo_text)):
            edit.setText(text)
            width, _height = get_size_text(edit.text(), edit.font())
            edit.setFixedWidth(width + 10)


class ScaleWidget(QWidget):
    def __init__(self, parent: QWidget, map_canvas: QgsMapCanvas):
        super().__init__(parent)
        self.map_canvas = map_canvas

        self.label = QLabel("Tỉ lệ", self)
        self.label.setFrameStyle(QFrame.Shape.NoFrame.value)
        self.label.setMargin(3)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.scale = QgsScaleComboBox(self)
        self.scale.setContentsMargins(0, 0, 0, 0)

        layout = QHBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.scale)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.scale.scaleChanged.connect(lambda _s: self.map_canvas.zoomScale(self.scale.scale()))

    def set_scale(self, scale: float):
        self.scale.blockSignals(True)
        self.scale.setScale(scale)
        self.scale.blockSignals(False)
        if self.scale.width() > self.scale.minimumWidth():
            self.scale.setMinimumWidth(self.scale.width())
