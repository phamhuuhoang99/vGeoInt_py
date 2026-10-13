"""Port of ShipDetectionDialog.cpp."""

from vgeoint.app.dialogs._yolo_detection_base import YoloDetectionDialog
from vgeoint.common.ui import load_ui_class

Ui_ShipDetectionDialog = load_ui_class("app", "ShipDetectionDialog")


class ShipDetectionDialog(YoloDetectionDialog, Ui_ShipDetectionDialog):
    NAME = "ShipDetection"
    VN_NAME = "Phát hiện tàu thuyền"
    ICON = "ship_detection.svg"  # C++ used "Ship.svg", which does not exist
    SCRIPT = "ship_detection.py"
    MODEL = "models/best.pt"
    READY_TEXT = "Hệ thống phát hiện tàu thuyền đã sẵn sàng"
    START_TEXT = "=== BẮT ĐẦU QUÁ TRÌNH PHÁT HIỆN TÀU THUYỀN ==="
    OBJECT_TEXT = "tàu thuyền"
    OUTPUT_TAG = "ships"
    LOG_TITLE = "Ship Detection"
    LOG_PREFIX = "ship_detection"
