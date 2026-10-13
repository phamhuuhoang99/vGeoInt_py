"""Port of TankDetectionDialog.cpp."""

from vgeoint.app.dialogs._yolo_detection_base import YoloDetectionDialog
from vgeoint.common.ui import load_ui_class

Ui_TankDetectionDialog = load_ui_class("app", "TankDetectionDialog")


class TankDetectionDialog(YoloDetectionDialog, Ui_TankDetectionDialog):
    NAME = "TankDetection"
    VN_NAME = "Phát hiện xe tăng"
    ICON = "tank_detection.svg"
    SCRIPT = "tank_detection.py"
    MODEL = "models/tank-detection-model.pt"
    READY_TEXT = "Hệ thống phát hiện xe tăng đã sẵn sàng"
    START_TEXT = "=== BẮT ĐẦU QUÁ TRÌNH PHÁT HIỆN XE TĂNG ==="
    OBJECT_TEXT = "xe tăng"
    OUTPUT_TAG = "tanks"
    LOG_TITLE = "Tank Detection"
    LOG_PREFIX = "tank_detection"
