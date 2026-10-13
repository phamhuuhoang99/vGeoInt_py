"""Open Windows Explorer with a file selected (or a folder)."""

import subprocess
import sys

from qgis.PyQt.QtCore import QDir, QFileInfo, QUrl
from qgis.PyQt.QtGui import QDesktopServices


def show_in_explorer(path: str):
    info = QFileInfo(path)
    if sys.platform == "win32":
        args = [] if info.isDir() else ["/select,"]
        subprocess.Popen(["explorer.exe", *args, QDir.toNativeSeparators(info.canonicalFilePath())])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(info.absolutePath() if not info.isDir() else path))
