"""Map tools ported from the C++ app (measure, add feature, annotations)."""

from qgis.gui import QgsMapToolCapture

from vgeoint.app.maptools.add_feature import AddFeatureTool
from vgeoint.app.maptools.annotation import MapToolTagAnnotation, MapToolTextAnnotation
from vgeoint.app.maptools.measure import MeasureTool

_CAPTURE_MODES = {
    "Point": QgsMapToolCapture.CaptureMode.CapturePoint,
    "Line": QgsMapToolCapture.CaptureMode.CaptureLine,
    "Polygon": QgsMapToolCapture.CaptureMode.CapturePolygon,
}


def create_add_feature_tool(canvas, cad_dock, geometry: str, message_bar):
    return AddFeatureTool(canvas, cad_dock, _CAPTURE_MODES[geometry], message_bar)


def create_measure_tool(canvas, measure_area: bool):
    return MeasureTool(canvas, measure_area)


def create_text_annotation_tool(canvas):
    return MapToolTextAnnotation(canvas)


def create_tag_annotation_tool(canvas):
    return MapToolTagAnnotation(canvas)
