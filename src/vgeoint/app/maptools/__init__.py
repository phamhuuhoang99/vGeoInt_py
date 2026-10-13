"""Map tools. Tools ported from the QGIS app sources (measure, add feature, annotations) land in phase 2."""

from qgis.core import Qgis
from qgis.gui import QgsMapCanvas, QgsMapTool

from vgeoint.common.utils import message_timeout


class PendingMapTool(QgsMapTool):
    """Placeholder that keeps the toolbar/menu wiring of a tool not ported yet."""

    def __init__(self, canvas: QgsMapCanvas, name: str, message_bar=None):
        super().__init__(canvas)
        self.name = name
        self.message_bar = message_bar

    def activate(self):
        super().activate()
        if self.message_bar is not None:
            self.message_bar.pushMessage(
                self.name, "Công cụ đang được chuyển đổi sang phiên bản mới.", Qgis.MessageLevel.Info, message_timeout()
            )


def create_add_feature_tool(canvas, geometry: str, message_bar):
    return PendingMapTool(canvas, f"Thêm đối tượng ({geometry})", message_bar)


def create_measure_tool(canvas, measure_area: bool, message_bar):
    return PendingMapTool(canvas, "Đo diện tích" if measure_area else "Đo độ dài", message_bar)


def create_text_annotation_tool(canvas, message_bar):
    return PendingMapTool(canvas, "Chèn ghi chú văn bản", message_bar)


def create_tag_annotation_tool(canvas, message_bar):
    return PendingMapTool(canvas, "Chèn Tag đếm đối tượng", message_bar)
