"""vGeoEngine — ported in phase 6."""

import sys

from qgis.PyQt.QtWidgets import QMainWindow

from vgeoint.common.bootstrap import create_app
from vgeoint.common.defines import ENGINE_NAME

app = create_app(ENGINE_NAME)
window = QMainWindow()
window.setWindowTitle(ENGINE_NAME)
window.show()
sys.exit(app.exec())
