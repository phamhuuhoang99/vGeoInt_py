"""Port of Utils.cpp."""

from qgis.core import (
    QgsCoordinateFormatter,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsPointXY,
    QgsProject,
    QgsSettings,
)
from qgis.PyQt.QtCore import QFile
from qgis.PyQt.QtGui import QFont, QFontMetrics, QIcon

from vgeoint.common.defines import ORG_NAME, SOFT_NAME

# (organization, application) used for QgsSettings; tests point this at a throwaway scope.
SETTINGS_SCOPE = (ORG_NAME, SOFT_NAME)


def settings() -> QgsSettings:
    return QgsSettings(*SETTINGS_SCOPE)


def app_settings(app_name: str) -> QgsSettings:
    """Settings of a sibling app (vGeoCatalog, vGeoEngine) under the same organization."""
    return QgsSettings(SETTINGS_SCOPE[0], app_name)


def message_timeout() -> int:
    return int(settings().value("MessageTimeout", 4))


def mouse_precision_decimal_places(is_geographic: bool = True) -> int:
    if is_geographic:
        return int(settings().value("MousePrecisionDecimalPlaces/Geographic", 5))
    return int(settings().value("MousePrecisionDecimalPlaces/Projected", 1))


def get_icon(name: str) -> QIcon:
    """Icon lookup order from the C++ app: :/myicon/<name>, then the QGIS default theme."""
    for path in (f":/myicon/{name}", f":/images/themes/default/{name}"):
        if QFile.exists(path):
            return QIcon(path)
    return QIcon()


def get_size_text(text: str, font: QFont) -> tuple[int, int]:
    fm = QFontMetrics(font)
    return fm.horizontalAdvance(text), fm.height()


def format_coordinate_for_project(
    project: QgsProject, point: QgsPointXY, dest_crs: QgsCoordinateReferenceSystem, precision: int
) -> tuple[str, str]:
    """Return (coordinate text in canvas CRS, WGS84 text in degrees/minutes/seconds)."""
    if project is None:
        return "", ""

    coord_str = QgsCoordinateFormatter.asPair(point.x(), point.y(), precision)
    geo = point
    if dest_crs.isValid() and not dest_crs.isGeographic():
        # need to transform to geographic coordinates
        ct = QgsCoordinateTransform(dest_crs, QgsCoordinateReferenceSystem.fromEpsgId(4326), project)
        try:
            geo = ct.transform(point)
        except QgsCsException:
            return coord_str, coord_str

    geo_str = QgsCoordinateFormatter.format(
        geo,
        QgsCoordinateFormatter.Format.FormatDegreesMinutesSeconds,
        3,
        QgsCoordinateFormatter.FormatFlag.FlagDegreesPadMinutesSeconds
        | QgsCoordinateFormatter.FormatFlag.FlagDegreesUseStringSuffix,
    )
    return coord_str, geo_str
