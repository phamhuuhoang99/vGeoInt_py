"""Port of qgsmeasuretool.cpp + qgsmeasuredialog.cpp (QGIS app sources customised in the C++ app)."""

import math

from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsCsException,
    QgsDistanceArea,
    QgsMessageLog,
    QgsPointLocator,
    QgsPointXY,
    QgsProject,
    QgsUnitTypes,
)
from qgis.gui import QgsMapCanvas, QgsMapTool, QgsRubberBand, QgsSnapIndicator
from qgis.PyQt.QtCore import QLocale, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QColorDialog, QDialog, QMessageBox, QTreeWidgetItem

from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import settings

Ui_QgsMeasureBase = load_ui_class("app", "qgsmeasurebase")

AU = Qgis.AreaUnit
DU = Qgis.DistanceUnit
STANDARD = Qgis.DistanceUnitType.Standard
GEOGRAPHIC = Qgis.DistanceUnitType.Geographic

AREA_UNITS = [
    AU.SquareMeters, AU.SquareKilometers, AU.SquareFeet, AU.SquareYards, AU.SquareMiles, AU.Hectares,
    AU.Acres, AU.SquareCentimeters, AU.SquareMillimeters, AU.SquareNauticalMiles, AU.SquareDegrees,
]
DISTANCE_UNITS = [
    DU.Meters, DU.Kilometers, DU.Feet, DU.Yards, DU.Miles, DU.NauticalMiles, DU.Centimeters,
    DU.Millimeters, DU.Degrees,
]


def measure_color() -> QColor:
    s = settings()
    return QColor(
        int(s.value("MeasureColor/Red", 0)), int(s.value("MeasureColor/Green", 255)), int(s.value("MeasureColor/Blue", 255))
    )


class MeasureDialog(QDialog, Ui_QgsMeasureBase):
    def __init__(self, tool: "MeasureTool"):
        super().__init__(tool.canvas().window())
        self.setupUi(self)
        self.measure_area = tool.measure_area
        self.tool = tool
        self.canvas: QgsMapCanvas = tool.canvas()
        self.da = QgsDistanceArea()
        self.total = 0.0
        self.last_mouse_point = QgsPointXY()
        self.decimal_places = 3
        self.distance_units = DU.Meters
        self.area_units = AU.SquareMeters

        self.repopulate_combo_box_units(self.measure_area)
        project = QgsProject.instance()
        self._select_unit(project.areaUnits() if self.measure_area else project.distanceUnits())
        if not self.canvas.mapSettings().destinationCrs().isValid():
            self.mUnitsCombo.setEnabled(False)
            self._select_unit(AU.Unknown if self.measure_area else DU.Unknown)

        self.update_settings()

        self.mUnitsCombo.currentIndexChanged.connect(self.units_changed)
        self.canvas.destinationCrsChanged.connect(self.crs_changed)
        self.newBtn.clicked.connect(self.restart)
        self.cancelBtn.clicked.connect(self.reject)
        self.colorPickerBtn.clicked.connect(self._pick_color)
        self.groupBox.setCollapsed(True)

    def _select_unit(self, unit):
        self.mUnitsCombo.setCurrentIndex(self.mUnitsCombo.findData(unit))

    def _pick_color(self):
        color = QColorDialog.getColor(measure_color(), self, "Chọn màu cho thước")
        if color.isValid():
            s = settings()
            s.setValue("MeasureColor/Red", color.red())
            s.setValue("MeasureColor/Green", color.green())
            s.setValue("MeasureColor/Blue", color.blue())
            self.tool.update_settings()

    def crs_changed(self):
        if not self.canvas.mapSettings().destinationCrs().isValid():
            self.mUnitsCombo.setEnabled(False)
            self._select_unit(AU.Unknown if self.measure_area else DU.Unknown)
        else:
            self.mUnitsCombo.setEnabled(True)
        self.update_ui()

    def update_settings(self):
        s = settings()
        self.decimal_places = int(s.value("Measure/Decimalplaces", 3))
        project = QgsProject.instance()
        self.distance_units = project.distanceUnits()
        self.area_units = project.areaUnits()
        self.da.setSourceCrs(self.canvas.mapSettings().destinationCrs(), project.transformContext())
        self.da.setEllipsoid(project.ellipsoid())
        self.mTable.clear()
        self.total = 0.0
        self.update_ui()

    def units_changed(self, index: int):
        data = self.mUnitsCombo.itemData(index)
        if data is None:
            return
        if self.measure_area:
            self.area_units = data
        else:
            self.distance_units = data
        self.mTable.clear()
        self.total = 0.0
        self.update_ui()
        if not self.tool.done:
            self.add_point()
            self.mouse_move(self.last_mouse_point)

    def restart(self):
        self.tool.restart()
        self.mTable.clear()
        self.total = 0.0
        self.update_ui()

    def _fmt(self, value: float) -> str:
        return QLocale().toString(value, "f", self.decimal_places)

    def _add_row(self, value: float):
        item = QTreeWidgetItem([self._fmt(value)])
        item.setTextAlignment(0, Qt.AlignmentFlag.AlignRight)
        self.mTable.addTopLevelItem(item)
        self.mTable.scrollToItem(item)

    def mouse_move(self, point: QgsPointXY):
        self.last_mouse_point = point
        points = self.tool.points
        if self.measure_area and len(points) >= 2:
            self.editTotal.setText(self.format_area(self.da.measurePolygon(points + [point])))
        elif not self.measure_area and points:
            d = self.da.measureLine(points[-1], point)
            self.editTotal.setText(self.format_distance(self.total + d))
            item = self.mTable.topLevelItem(self.mTable.topLevelItemCount() - 1)
            if item is not None:
                item.setText(0, self._fmt(self.convert_length(d, self.distance_units)))

    def add_point(self):
        points = self.tool.points
        if self.measure_area and len(points) > 2:
            self.editTotal.setText(self.format_area(self.da.measurePolygon(points)))
        elif not self.measure_area and len(points) >= 1:
            if not self.tool.done:
                self._add_row(0.0)
            if len(points) > 1:
                self.total = self.da.measureLine(points)
                self.editTotal.setText(self.format_distance(self.total))

    def remove_last_point(self):
        points = self.tool.points
        if self.measure_area:
            if len(points) > 1:
                self.editTotal.setText(self.format_area(self.da.measurePolygon(points + [self.last_mouse_point])))
            else:
                self.editTotal.setText(self.format_area(0))
        elif len(points) >= 1:
            self.mTable.takeTopLevelItem(self.mTable.topLevelItemCount() - 1)
            self.total = self.da.measureLine(points)
            if not self.tool.done:
                d = self.da.measureLine(points[-1], self.last_mouse_point)
                item = self.mTable.topLevelItem(self.mTable.topLevelItemCount() - 1)
                if item is not None:
                    item.setText(0, self._fmt(self.convert_length(d, self.distance_units)))
                self.editTotal.setText(self.format_distance(self.total + d))
            else:
                self.editTotal.setText(self.format_distance(self.total))

    def closeEvent(self, e):
        self.reject()
        e.accept()

    def restore_position(self):
        s = settings()
        geometry = s.value("Measure/Geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        key, default = ("Measure/HNoTable", 70) if self.measure_area else ("Measure/H", 200)
        self.resize(self.width(), int(s.value(key, default)))
        self.update_ui()

    def save_window_location(self):
        s = settings()
        s.setValue("Measure/Geometry", self.saveGeometry())
        s.setValue("Measure/HNoTable" if self.measure_area else "Measure/H", self.height())

    def format_distance(self, distance: float, convert_units: bool = True) -> str:
        base_unit = str(settings().value("Measure/KeepBaseUnit", True)).lower() in ("true", "1")
        if convert_units:
            distance = self.convert_length(distance, self.distance_units)
        decimals = self.decimal_places
        if self.distance_units == DU.Degrees and 0 < distance < 1:
            decimals = max(decimals, round(math.log10(1.0 / distance)) + 1)
        return QgsDistanceArea.formatDistance(distance, decimals, self.distance_units, base_unit)

    def format_area(self, area: float, convert_units: bool = True) -> str:
        if convert_units:
            area = self.convert_area(area, self.area_units)
        return QgsDistanceArea.formatArea(area, self.decimal_places, self.area_units, True)

    def update_ui(self):
        tool_tip = "Kết quả được tính bởi:"
        force_cartesian = False
        convert_to_display_units = True
        crs = self.canvas.mapSettings().destinationCrs()
        tr = QgsUnitTypes.toString

        if self.measure_area:
            if not crs.isValid():
                tool_tip += "<br> * Không có hệ tọa độ, do vậy diện tích được tính theo hệ tọa độ Đề-các."
                tool_tip += "<br> * Đơn vị không xác định."
                force_cartesian, convert_to_display_units = True, False
            elif crs.mapUnits() == DU.Degrees and self.area_units in (AU.SquareDegrees, AU.Unknown):
                tool_tip += (
                    "<br> * Hệ tọa độ đo và ảnh (%s) cùng đơn vị là độ, do vậy diện tích sẽ là độ vuông "
                    "tính theo hệ tọa độ Đề-các" % crs.description()
                )
                force_cartesian, convert_to_display_units = True, False
            else:
                if self.da.willUseEllipsoid():
                    result_unit = AU.SquareMeters
                    tool_tip += "<br> * Hệ tọa độ vuông góc đang hiện hành "
                    tool_tip += "<br> * Tọa độ sẽ được chuyển về theo ellipsoid (%s), diện tích được tính theo đơn vị %s." % (
                        self.da.ellipsoid(), tr(result_unit)
                    )
                else:
                    result_unit = QgsUnitTypes.distanceToAreaUnit(crs.mapUnits())
                    tool_tip += "<br> * Hệ tọa độ vuông góc không hiện hành "
                    tool_tip += "Diện tích được tính theo đơn vị %s, trên cơ sở hệ tọa độ (%s)." % (
                        tr(result_unit), crs.description()
                    )
                self.setWindowTitle("Đo diện tích")
                if QgsUnitTypes.unitType(result_unit) == GEOGRAPHIC and QgsUnitTypes.unitType(self.area_units) == STANDARD:
                    tool_tip += "<br> * Diện tích được chuyển thành mét vuông (1 degree = 111319.49 meters)."
                    result_unit = AU.SquareMeters
                elif QgsUnitTypes.unitType(result_unit) == STANDARD and QgsUnitTypes.unitType(self.area_units) == GEOGRAPHIC:
                    tool_tip += "<br> * Diện tích được chuyển thành độ vuông (1 degree = 111319.49 meters)."
                    result_unit = AU.SquareDegrees
                if (
                    result_unit != self.area_units
                    and QgsUnitTypes.unitType(result_unit) == STANDARD
                    and QgsUnitTypes.unitType(self.area_units) == STANDARD
                ):
                    tool_tip += "<br> * Giá trị được chuyển từ %s sang %s." % (tr(result_unit), tr(self.area_units))
        else:
            if not crs.isValid():
                tool_tip += "<br> * Không có hệ tọa độ, do vậy độ dài được tính theo hệ tọa độ Đề-các."
                tool_tip += "<br> * Đơn vị không xác định."
                force_cartesian, convert_to_display_units = True, False
            elif crs.mapUnits() == DU.Degrees and self.distance_units == DU.Degrees:
                tool_tip += (
                    "<br> * Hệ tọa độ đo và ảnh (%s) cùng đơn vị là độ, do vậy độ dài sẽ là độ "
                    "tính theo hệ tọa độ Đề-các" % crs.description()
                )
                force_cartesian, convert_to_display_units = True, False
            else:
                if self.da.willUseEllipsoid():
                    result_unit = DU.Meters
                    tool_tip += "<br> * Hệ tọa độ vuông góc đang hiện hành "
                    tool_tip += "<br> * Tọa độ sẽ được chuyển về theo ellipsoid (%s), độ dài được tính theo đơn vị %s." % (
                        self.da.ellipsoid(), tr(result_unit)
                    )
                else:
                    result_unit = crs.mapUnits()
                    tool_tip += "<br> * Hệ tọa độ vuông góc không hiện hành "
                    tool_tip += "Độ dài được tính theo đơn vị %s, trên cơ sở hệ tọa độ (%s)." % (
                        tr(result_unit), crs.description()
                    )
                self.setWindowTitle("Đo độ dài")
                if QgsUnitTypes.unitType(result_unit) == GEOGRAPHIC and QgsUnitTypes.unitType(self.distance_units) == STANDARD:
                    tool_tip += "<br> * Độ dài được chuyển thành mét (1 degree = 111319.49 meters)."
                    result_unit = DU.Meters
                elif QgsUnitTypes.unitType(result_unit) == STANDARD and QgsUnitTypes.unitType(self.distance_units) == GEOGRAPHIC:
                    tool_tip += "<br> * Độ dài được chuyển thành độ (1 degree = 111319.49 meters)."
                    result_unit = DU.Degrees
                if (
                    result_unit != self.distance_units
                    and QgsUnitTypes.unitType(result_unit) == STANDARD
                    and QgsUnitTypes.unitType(self.distance_units) == STANDARD
                ):
                    tool_tip += "<br> * Giá trị được chuyển từ %s sang %s." % (tr(result_unit), tr(self.distance_units))

        self.editTotal.setToolTip(tool_tip)
        self.mTable.setToolTip(tool_tip)
        self.mNotesLabel.setText(tool_tip)

        self.mUnitsCombo.blockSignals(True)
        if self.measure_area:
            self._select_unit(self.area_units)
        else:
            self._select_unit(self.distance_units)
            if self.distance_units != DU.Unknown:
                self.mTable.setHeaderLabels([f"Độ dài các đoạn con [{tr(self.distance_units)}]"])
            else:
                self.mTable.setHeaderLabels(["Độ dài các đoạn con"])
        self.mUnitsCombo.blockSignals(False)

        points = self.tool.points
        if self.measure_area:
            area = self.da.measurePolygon(points) if len(points) > 1 else 0.0
            self.mTable.hide()  # Hide the table, only show summary.
            self.editTotal.setText(self.format_area(area))
        else:
            self.total = 0.0
            for p1, p2 in zip(points, points[1:]):
                if force_cartesian:
                    d = math.sqrt(p2.sqrDist(p1))
                    self.total += d
                else:
                    d = self.convert_length(self.da.measureLine(p1, p2), self.distance_units)
                self._add_row(d)
            if not force_cartesian:
                self.total = self.da.measureLine(points)
            self.mTable.show()  # Show the table with items
            self.editTotal.setText(self.format_distance(self.total, convert_to_display_units))

    def repopulate_combo_box_units(self, is_area: bool):
        self.mUnitsCombo.clear()
        for unit in AREA_UNITS if is_area else DISTANCE_UNITS:
            self.mUnitsCombo.addItem(QgsUnitTypes.toString(unit), unit)
        self.mUnitsCombo.addItem(self.tr("map units"), AU.Unknown if is_area else DU.Unknown)

    def convert_length(self, length: float, to_unit) -> float:
        return self.da.convertLengthMeasurement(length, to_unit)

    def convert_area(self, area: float, to_unit) -> float:
        return self.da.convertAreaMeasurement(area, to_unit)

    def reject(self):
        self.save_window_location()
        self.restart()
        self.close()


class MeasureTool(QgsMapTool):
    def __init__(self, canvas: QgsMapCanvas, measure_area: bool):
        super().__init__(canvas)
        self.measure_area = measure_area
        self.snap_indicator = QgsSnapIndicator(canvas)
        self.rubber_band = QgsRubberBand(canvas, Qgis.GeometryType.Polygon if measure_area else Qgis.GeometryType.Line)
        self.rubber_band_points = QgsRubberBand(canvas, Qgis.GeometryType.Point)
        self.points: list[QgsPointXY] = [QgsPointXY(0, 0)]
        self.done = True
        self.wrong_project_projection = False
        self.destination_crs = canvas.mapSettings().destinationCrs()
        self.dialog = MeasureDialog(self)
        self.dialog.setWindowFlags(self.dialog.windowFlags() | Qt.WindowType.Tool)
        self.dialog.restore_position()
        canvas.destinationCrsChanged.connect(self.update_settings)

    def activate(self):
        self.dialog.show()
        super().activate()
        self.update_settings()

        canvas = self.canvas()
        crs = canvas.mapSettings().destinationCrs()
        if crs.isValid() and crs.isGeographic() and (canvas.extent().height() > 360 or canvas.extent().width() > 720):
            QMessageBox.warning(
                None,
                self.tr("Incorrect Measure Results"),
                self.tr(
                    "<p>This map is defined with a geographic coordinate system (latitude/longitude) but the map "
                    "extents suggests that it is actually a projected coordinate system (e.g., Mercator). If so, the "
                    "results from line or area measurements will be incorrect.</p><p>To fix this, explicitly set an "
                    "appropriate map coordinate system using the <tt>Settings:Project Properties</tt> menu."
                ),
            )
            self.wrong_project_projection = True

    def deactivate(self):
        self.snap_indicator.setMatch(QgsPointLocator.Match())
        self.dialog.hide()
        super().deactivate()

    def restart(self):
        self.points = []
        self.rubber_band.reset(Qgis.GeometryType.Polygon if self.measure_area else Qgis.GeometryType.Line)
        self.rubber_band_points.reset(Qgis.GeometryType.Point)
        self.done = True
        self.wrong_project_projection = False

    def update_settings(self):
        color = measure_color()
        self.rubber_band.setColor(QColor(color.red(), color.green(), color.blue(), 100))
        self.rubber_band.setWidth(3)
        self.rubber_band_points.setIcon(QgsRubberBand.IconType.ICON_CROSS)
        self.rubber_band_points.setIconSize(15)
        self.rubber_band_points.setColor(QColor(color.red(), color.green(), color.blue(), 150))

        canvas_crs = self.canvas().mapSettings().destinationCrs()
        if self.rubber_band.size() > 0 and self.destination_crs != canvas_crs and canvas_crs.isValid():
            points = list(self.points)
            last_done = self.done
            self.dialog.restart()
            self.done = last_done
            ct = QgsCoordinateTransform(self.destination_crs, canvas_crs, QgsProject.instance())
            for previous in points:
                try:
                    point = ct.transform(previous)
                except QgsCsException as cse:
                    QgsMessageLog.logMessage(f"Transform error caught at the MeasureTool: {cse}")
                    continue
                self.points.append(point)
                self.rubber_band.addPoint(point, False)
                self.rubber_band_points.addPoint(point, False)
            for rb in (self.rubber_band, self.rubber_band_points):
                rb.updatePosition()
                rb.update()

        self.destination_crs = canvas_crs
        self.dialog.update_settings()

        if not self.done and self.rubber_band.size() > 0:
            self.rubber_band.addPoint(self.points[-1])
            self.dialog.add_point()
        if self.rubber_band.size() > 0:
            self.rubber_band.setVisible(True)
            self.rubber_band_points.setVisible(True)

    def canvasPressEvent(self, e):
        pass

    def canvasMoveEvent(self, e):
        point = e.snapPoint()
        self.snap_indicator.setMatch(e.mapPointMatch())
        if not self.done:
            self.rubber_band.movePoint(point)
            self.dialog.mouse_move(point)

    def canvasReleaseEvent(self, e):
        point = e.snapPoint()
        if self.done:  # if we have stopped measuring any mouse click restart measuring
            self.dialog.restart()

        if e.button() == Qt.MouseButton.RightButton:  # if we clicked the right button we stop measuring
            self.done = True
            self.rubber_band.removeLastPoint()
            self.dialog.remove_last_point()
        elif e.button() == Qt.MouseButton.LeftButton:
            self.done = False
            self.add_point(point)
        self.dialog.show()

    def undo(self):
        if not self.points:
            return
        if len(self.points) == 1:
            self.restart()
            self.dialog.restart()
        else:
            self.rubber_band.removePoint(-2, True)
            self.rubber_band_points.removePoint(-1, True)
            self.points.pop()
            self.dialog.remove_last_point()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            if not self.done:
                self.undo()
            e.ignore()

    def add_point(self, point: QgsPointXY):
        if self.points and self.points[-1] == point:
            return
        self.points.append(QgsPointXY(point))
        self.rubber_band.addPoint(point)
        self.rubber_band_points.addPoint(point)
        if not self.done:  # Prevent the insertion of a new item in segments measure table
            self.dialog.add_point()
