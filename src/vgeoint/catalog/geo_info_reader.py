"""Port of GeoInfoReader.cpp — read extent, CRS and date of a raster/vector file."""

import logging
from pathlib import Path

from qgis.core import QgsFileUtils, QgsProviderRegistry, QgsRasterLayer, QgsRectangle, QgsVectorLayer
from qgis.PyQt.QtCore import QDateTime, QFile, QFileInfo

log = logging.getLogger(__name__)


def _extensions(filters: str) -> list[str]:
    return sorted({e.upper() for e in QgsFileUtils.extensionsFromFilter(filters)})


def supported_raster_formats() -> list[str]:
    return _extensions(QgsProviderRegistry.instance().fileRasterFilters())


def supported_vector_formats() -> list[str]:
    return _extensions(QgsProviderRegistry.instance().fileVectorFilters())


def _g10(value: float) -> str:
    """QString::number(v, 'g', 10)."""
    return f"{value:.10g}"


class GeoInfoReader:
    def __init__(self, file_name: str = ""):
        self.file_name = file_name
        self.raster_formats = supported_raster_formats()
        self.vector_formats = supported_vector_formats()
        self.reset()

    def reset(self):
        self.srid = -1
        self.date_time = QDateTime()
        self.coordinate_system = ""
        self.extent = QgsRectangle()
        self.extent_str = ""
        self.geom_wkt = ""

    def set_file_name(self, file_name: str):
        self.file_name = file_name

    def is_geo_data(self) -> bool:
        return self.srid != -1

    def exec(self):
        self.reset()
        if not self.file_name:
            log.error("ERROR: FileName is empty")
            return

        suffix = Path(self.file_name).suffix.lstrip(".").upper()
        if suffix in self.raster_formats:
            layer = QgsRasterLayer(self.file_name)
            if layer.isValid():
                extent = layer.extent()
                # Ảnh không có tọa độ (extent từ 0) không được coi là dữ liệu địa lý
                if extent.xMinimum() > 0.0 or extent.yMinimum() > 0.0:
                    self._read_layer(layer)
            del layer
            QFile.remove(self.file_name + ".aux.xml")
        elif suffix in self.vector_formats:
            layer = QgsVectorLayer(self.file_name)
            if layer.isValid():
                self._read_layer(layer)
            del layer
            QFile.remove(self.file_name + ".aux.xml")
        else:
            log.error("Cannot read file: %s", self.file_name)

    def _read_layer(self, layer):
        self.extent = layer.extent()
        self.date_time = QFileInfo(self.file_name).lastModified()
        crs = layer.crs()
        self.coordinate_system = crs.description()
        raw_srid = crs.postgisSrid()
        if raw_srid <= 0 or not crs.isValid():
            # Fallback to WGS84 (EPSG:4326) for invalid or missing CRS
            self.srid = 4326
            self.coordinate_system = "WGS 84 (assumed - original CRS invalid)"
            log.warning("File %s has invalid CRS, using WGS84 (EPSG:4326) as fallback", self.file_name)
        else:
            self.srid = raw_srid
        self._update_extent_str()
        self._update_geom()

    def _update_extent_str(self):
        e = self.extent
        self.extent_str = (
            f"({_g10(e.xMinimum())}, {_g10(e.yMinimum())}) ({_g10(e.xMaximum())}, {_g10(e.yMaximum())})"
        )

    def _update_geom(self):
        e = self.extent
        # The C++ used QString::arg(double) (6 significant digits): UTM coordinates were rounded by metres.
        x1, y1, x2, y2 = _g10(e.xMinimum()), _g10(e.yMinimum()), _g10(e.xMaximum()), _g10(e.yMaximum())
        self.geom_wkt = f"POLYGON(({x1} {y1}, {x1} {y2}, {x2} {y2}, {x2} {y1}, {x1} {y1}))"
