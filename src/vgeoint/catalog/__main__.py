"""vGeoCatalog — ported in phase 5."""

import sys

from qgis.PyQt.QtWidgets import QMainWindow

from vgeoint.common.bootstrap import create_app
from vgeoint.common.defines import CATALOG_NAME

app = create_app(CATALOG_NAME)
window = QMainWindow()
window.setWindowTitle(CATALOG_NAME)
window.show()
sys.exit(app.exec())
