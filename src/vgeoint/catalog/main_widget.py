"""Port of MainWidget.cpp — search the catalog by area, country or region and show results on a map."""

import logging

from qgis.core import (
    Qgis,
    QgsFillSymbol,
    QgsPalLayerSettings,
    QgsRasterLayer,
    QgsRectangle,
    QgsSimpleFillSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsVectorLayerCache,
    QgsVectorLayerSimpleLabeling,
)
from qgis.gui import (
    QgsAttributeTableFilterModel,
    QgsAttributeTableModel,
    QgsMapCanvas,
    QgsMapToolExtent,
    QgsMapToolPan,
    QgsMapToolZoom,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QCursor, QIcon, QPixmap
from qgis.PyQt.QtSql import QSqlQuery
from qgis.PyQt.QtWidgets import QApplication, QGridLayout, QWidget

from vgeoint.catalog import context
from vgeoint.catalog.explorer import show_in_explorer
from vgeoint.catalog.models import LibraryModel
from vgeoint.common.database import postgis_uri
from vgeoint.common.defines import CATALOG_NAME
from vgeoint.common.paths import CATALOG_DATA_DIR
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import app_settings

log = logging.getLogger(__name__)
Ui_MainWidget = load_ui_class("catalog", "MainWidget")

RASTER_BG = CATALOG_DATA_DIR / "Data.ras"
VECTOR_BG = CATALOG_DATA_DIR / "Data.shp"
# The C++ called the createview_searcharea/country/region() SQL functions, which build the view by
# string concatenation: searcharea emits "idlib = 5and ..." (rejected since PostgreSQL 15) and names
# with an apostrophe broke the other two. The same views are created here directly, with the
# predicate whitelisted, numbers formatted from floats/ints and text escaped, so existing databases
# work without migrating their functions.
PREDICATES = ("ST_Contains", "ST_Intersects")


def _g10(value: float) -> str:
    return f"{value:.10g}"


def _sql_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _boundary_view_sql(view: str, table: str, column: str, value: str, predicate: str) -> str:
    return (
        f"create or replace view {view} as "
        "select geodata.id, filename, datetime, extent, coordinatesystem, geodata.geom, library.name "
        f"from geodata, {table}, library "
        f"where {column} = {_sql_literal(value)} and idlib = library.id "
        f"and {predicate}({table}.geom, geodata.geom)"
    )


def _fill_symbol(stroke_width: float, stroke_color: QColor) -> QgsFillSymbol:
    layer = QgsSimpleFillSymbolLayer()
    layer.setBrushStyle(Qt.BrushStyle.NoBrush)
    layer.setStrokeWidth(stroke_width)
    layer.setStrokeColor(stroke_color)
    return QgsFillSymbol([layer])


class MainWidget(QWidget, Ui_MainWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        db = context.database(self)
        if not db.isOpen():
            log.error("Connect to database failed. %s", db.lastError().text())
        self.db = db
        self.lib_model = LibraryModel(db)
        self.libraries = []
        self.background_raster: QgsRasterLayer | None = None
        self.background_vector: QgsVectorLayer | None = None
        self.result_layer: QgsVectorLayer | None = None
        self.layer_cache = self.attribute_table_model = self.table_filter_model = None

        self.refresh()
        self.create_map_canvas()
        self.init_controls()
        self.load_map_background()
        self.create_connections()

    # ------------------------------------------------------------ settings
    _SPLITTERS = (("hSplitter", "MainWidgetHSplitter"), ("vSplitter", "MainWidgetVSplitter"))

    def restore_settings(self):
        s = app_settings(CATALOG_NAME)
        for attr, key in self._SPLITTERS:
            splitter = getattr(self, attr)
            for suffix, restore in (("Geometry", splitter.restoreGeometry), ("State", splitter.restoreState)):
                value = s.value(f"{key}/{suffix}")
                if value is not None:
                    restore(value)

    def save_settings(self):
        s = app_settings(CATALOG_NAME)
        for attr, key in self._SPLITTERS:
            splitter = getattr(self, attr)
            s.setValue(f"{key}/Geometry", splitter.saveGeometry())
            s.setValue(f"{key}/State", splitter.saveState())

    def refresh(self):
        """Cập nhật các thư viện hiện hành."""
        self.libraries = self.lib_model.get_all()
        self.librariesCbx.clear()
        for lib in self.libraries:
            self.librariesCbx.addItem(QIcon(":/myicon/Library.svg"), lib.name, lib.id)

    # -------------------------------------------------------------- canvas
    def create_map_canvas(self):
        self.map_canvas = QgsMapCanvas(self.mapViewWidget)
        self.map_canvas.setCanvasColor(QColor(Qt.GlobalColor.black))
        layout = QGridLayout(self.mapViewWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.map_canvas)

    def init_controls(self):
        for cbx, inside, intersects in (
            (self.mainSearchingTypeCbx, "Bên trong vùng tìm kiếm", "Giao với vùng tìm kiếm"),
            (self.countrySearchingTypeCbx, "Bên trong ranh giới quốc gia", "Giao với ranh giới quốc gia"),
            (self.regionSearchingTypeCbx, "Bên trong ranh giới khuc vực", "Giao với ranh giới khuc vực"),
        ):
            cbx.addItem(inside, "ST_Contains")
            cbx.addItem(intersects, "ST_Intersects")
            cbx.setCurrentIndex(0)

    def create_connections(self):
        self.map_tool_extent = QgsMapToolExtent(self.map_canvas)
        self.map_tool_extent.extentChanged.connect(self.set_area_searching)
        self.drawOnCanvasBtn.clicked.connect(self._draw_on_canvas)
        self.currentViewBtn.clicked.connect(lambda: self.set_area_searching(self.map_canvas.extent()))
        self.clearExtentBtn.clicked.connect(self._clear_extent)

        self.zoom_in_tool = QgsMapToolZoom(self.map_canvas, False)
        self.zoom_out_tool = QgsMapToolZoom(self.map_canvas, True)
        self.pan_tool = QgsMapToolPan(self.map_canvas)
        self.zoomInBtn.clicked.connect(lambda: self._set_tool(self.zoom_in_tool, ":/myicon/ZoomIn.svg"))
        self.zoomOutBtn.clicked.connect(lambda: self._set_tool(self.zoom_out_tool, ":/myicon/ZoomOut.svg"))
        self.panMapBtn.clicked.connect(lambda: self.map_canvas.setMapTool(self.pan_tool))
        self.zoomFullExtentBtn.clicked.connect(self.map_canvas.zoomToFullExtent)
        self.rasterTypeRbx.toggled.connect(self._background_toggled)

        self.searchBtn.clicked.connect(lambda: self._busy(self.search_by_area))
        self.countrySearchBtn.clicked.connect(lambda: self._busy(self.search_by_country))
        self.regionSearchBtn.clicked.connect(lambda: self._busy(self.search_by_region))
        self.gotoRecInMapViewBtn.clicked.connect(self.view_rec_in_map_view)
        self.showRecInExplorerBtn.clicked.connect(self.show_rec_in_explorer)
        self.copyRecAsTextBtn.clicked.connect(self.copy_rec_as_text)
        self.clearRecSelectionBtn.clicked.connect(self.clear_rec_selection)

    def _set_tool(self, tool, cursor_icon: str):
        self.map_canvas.setMapTool(tool)
        self.map_canvas.setCursor(QCursor(QPixmap(cursor_icon)))

    def _draw_on_canvas(self):
        self._clear_extent_edits()
        self.map_canvas.setMapTool(self.map_tool_extent)

    def _clear_extent_edits(self):
        for edit in (self.topValueLedr, self.bottomValueLedr, self.leftValueLedr, self.rightValueLedr):
            edit.clear()

    def _clear_extent(self):
        self._clear_extent_edits()
        tool = self.map_canvas.mapTool()
        if tool is not None:
            self.map_canvas.setMapTool(tool, True)

    def _busy(self, fn):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            fn()
        finally:
            QApplication.restoreOverrideCursor()

    def set_area_searching(self, extent: QgsRectangle):
        self.topValueLedr.setText(_g10(extent.yMaximum()))
        self.bottomValueLedr.setText(_g10(extent.yMinimum()))
        self.rightValueLedr.setText(_g10(extent.xMaximum()))
        self.leftValueLedr.setText(_g10(extent.xMinimum()))

    # ---------------------------------------------------------- background
    def _background_toggled(self):
        if self.rasterTypeRbx.isChecked():
            self.view_raster_map_background()
        else:
            self.view_vector_map_background()

    def _set_background(self, layer, color):
        layers = self.map_canvas.layers()
        if layers:
            layers.pop()
        if layer is not None:
            layers.append(layer)
        self.map_canvas.setCanvasColor(QColor(color))
        self.map_canvas.setLayers(layers)

    def view_raster_map_background(self):
        self._set_background(self.background_raster, Qt.GlobalColor.black)

    def view_vector_map_background(self):
        self._set_background(self.background_vector, Qt.GlobalColor.white)

    def load_map_background(self):
        self.background_raster = QgsRasterLayer(str(RASTER_BG))
        if not self.background_raster.isValid():
            log.error("Cannot load raster background %s", RASTER_BG)
            self.background_raster = None

        self.background_vector = QgsVectorLayer(str(VECTOR_BG))
        if self.background_vector.isValid():
            # Set style cho nền bản đồ
            self.background_vector.setRenderer(QgsSingleSymbolRenderer(_fill_symbol(0.4, QColor(32, 166, 179))))
            # Set label hiển thị
            pal = QgsPalLayerSettings()
            pal.fieldName = "NAME"
            self.background_vector.setLabeling(QgsVectorLayerSimpleLabeling(pal))
            self.background_vector.setLabelsEnabled(True)
            # Lấy dữ liệu quốc gia và khu vực
            for cbx, field in ((self.countryCbx, 0), (self.regionCbx, 2)):
                for value in sorted(str(v) for v in self.background_vector.uniqueValues(field)):
                    cbx.addItem(value)
        else:
            log.error("Cannot load vector background %s", VECTOR_BG)
            self.background_vector = None

        if int(app_settings(CATALOG_NAME).value("MapBackgroundType", 1)) == 1:
            self.view_raster_map_background()
        else:
            self.view_vector_map_background()
        self.map_canvas.zoomToFullExtent()

    # -------------------------------------------------------------- search
    def _exec(self, sql: str, *values) -> bool:
        query = QSqlQuery(self.db)
        query.prepare(sql)
        for v in values:
            query.addBindValue(v)
        if not query.exec():
            log.warning(query.lastError().text())
            return False
        return True

    @staticmethod
    def _predicate(cbx) -> str:
        predicate = cbx.currentData()
        return predicate if predicate in PREDICATES else PREDICATES[0]

    def search_by_area(self):
        idx = self.librariesCbx.currentIndex()
        if idx < 0:
            return
        id_lib = self.librariesCbx.itemData(idx)
        edits = (self.leftValueLedr, self.topValueLedr, self.rightValueLedr, self.bottomValueLedr)
        if any(not e.text() for e in edits):
            return
        try:
            left, top, right, bottom = (float(e.text()) for e in edits)
        except ValueError:
            return
        predicate = self._predicate(self.mainSearchingTypeCbx)
        if self._exec(
            "create or replace view searcharea as "
            "select geodata.id, filename, datetime, extent, coordinatesystem, library.name, geom "
            "from geodata, library "
            f"where library.id = idlib and idlib = {int(id_lib)} "
            f"and {predicate}(ST_MakeEnvelope({left!r}, {top!r}, {right!r}, {bottom!r}, 4326), geom)"
        ):
            self.view_postgis_query("searcharea")

    def search_by_country(self):
        if self._exec(
            _boundary_view_sql(
                "searchcountry", "countryshp", "countryshp.name",
                self.countryCbx.currentText(), self._predicate(self.countrySearchingTypeCbx),
            )
        ):
            self.view_postgis_query("searchcountry")

    def search_by_region(self):
        if self._exec(
            _boundary_view_sql(
                "searchregion", "regionshp", "region",
                self.regionCbx.currentText(), self._predicate(self.regionSearchingTypeCbx),
            )
        ):
            self.view_postgis_query("searchregion")

    def view_postgis_query(self, view: str):
        uri = postgis_uri(context.config())
        uri.setSrid("4326")
        uri.setWkbType(Qgis.WkbType.MultiPolygon)
        uri.setDataSource("public", view, "geom", "", "id")
        result = QgsVectorLayer(uri.uri(False), "result", "postgres")
        if not result.isValid():
            log.error("Cannot open postgis layer")
            return
        self.set_default_style(result)
        self.set_rec_table(result)
        # Hiển thị trên map canvas: kết quả luôn ở trên cùng, nền ở dưới
        layers = self.map_canvas.layers()
        if len(layers) > 1:
            layers.pop(0)
        layers.insert(0, result)
        self.result_layer = result
        self.map_canvas.setLayers(layers)

    def set_default_style(self, layer: QgsVectorLayer):
        layer.setRenderer(QgsSingleSymbolRenderer(_fill_symbol(0.2, QColor(Qt.GlobalColor.red))))
        pal = QgsPalLayerSettings()
        pal.fieldName = "ID"
        fmt = pal.format()
        fmt.setColor(QColor(Qt.GlobalColor.green))
        pal.setFormat(fmt)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        layer.setLabelsEnabled(True)

    def set_rec_table(self, layer: QgsVectorLayer):
        for i, alias in enumerate(("ID", "Đường Dẫn", "Ngày Tạo", "Tạo Độ Khung", "Hệ Tọa Độ", "Thư Viện")):
            layer.setFieldAlias(i, alias)
        # Hiển thị lên bảng kết quả
        table = self.geoDataRecTbv
        self.layer_cache = QgsVectorLayerCache(layer, 2000, table)
        self.attribute_table_model = QgsAttributeTableModel(self.layer_cache, table)
        self.attribute_table_model.loadLayer()
        self.table_filter_model = QgsAttributeTableFilterModel(self.map_canvas, self.attribute_table_model, table)
        # The view keeps its own selection manager bound to the layer selection (the C++ created one
        # explicitly; that class is not exposed in PyQGIS 4).
        table.setModel(self.table_filter_model)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)

    # ------------------------------------------------------------- records
    def view_rec_in_map_view(self):
        layer = self.result_layer
        if layer is None or layer not in self.map_canvas.layers():
            return
        index = self.geoDataRecTbv.currentIndex()
        if not index.isValid():
            return
        self.geoDataRecTbv.selectRow(index.row())
        self.geoDataRecTbv.setCurrentIndex(index)
        extent = QgsRectangle()
        extent.setNull()
        for fid in layer.selectedFeatureIds():
            extent.combineExtentWith(layer.getFeature(fid).geometry().boundingBox())
        if not extent.isNull():
            self.map_canvas.setExtent(extent)
            self.map_canvas.refresh()
        self.geoDataRecTbv.setFocus()

    def show_rec_in_explorer(self):
        index = self.geoDataRecTbv.currentIndex()
        if not index.isValid():
            return
        self.geoDataRecTbv.selectRow(index.row())
        self.geoDataRecTbv.setCurrentIndex(index)
        self.geoDataRecTbv.setFocus()
        show_in_explorer(str(self.geoDataRecTbv.model().data(index.siblingAtColumn(1), Qt.ItemDataRole.DisplayRole)))

    def copy_rec_as_text(self):
        index = self.geoDataRecTbv.currentIndex()
        if not index.isValid():
            return
        self.geoDataRecTbv.setFocus()
        QApplication.clipboard().setText(str(self.geoDataRecTbv.model().data(index, Qt.ItemDataRole.DisplayRole)))
        QApplication.beep()

    def clear_rec_selection(self):
        if self.result_layer is not None:
            self.result_layer.removeSelection()
