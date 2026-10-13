"""QgsApplication startup shared by the three apps (port of main.cpp)."""

import os
import sys
from pathlib import Path

from osgeo import gdal
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QResource

from vgeoint.common.paths import RESOURCES_DIR


def _qgis_prefix() -> str:
    # Inside a pixi/conda env QGIS lives under <env>/Library; no hardcoded C:/OSGeo4W.
    env = os.environ.get("CONDA_PREFIX") or sys.prefix
    return str(Path(env) / "Library")


def register_resources() -> None:
    """Register compiled .rcc bundles so ':/myicon/...' paths from .ui files resolve."""
    for rcc in RESOURCES_DIR.glob("*.rcc"):
        QResource.registerResource(str(rcc))


def create_app(app_name: str, gui: bool = True) -> QgsApplication:
    # Ported code checks GDAL return values (None) like the C++ app; keep that mode explicitly.
    gdal.DontUseExceptions()
    QgsApplication.setPrefixPath(_qgis_prefix(), True)
    # QGIS 4 / PyQt6 bindings take argv as bytes.
    app = QgsApplication([a.encode() for a in sys.argv], gui)
    QgsApplication.setApplicationName(app_name)
    register_resources()
    QgsApplication.initQgis()
    return app


def install_file_log(app_name: str):
    """Write Qt and Python log messages to logs/<app>_log.txt (port of the C++ messageHandler)."""
    import logging

    from qgis.PyQt.QtCore import QtMsgType, qInstallMessageHandler

    from vgeoint.common.paths import LOGS_DIR

    LOGS_DIR.mkdir(exist_ok=True)
    handler = logging.FileHandler(LOGS_DIR / f"{app_name}_log.txt", mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s %(message)s", "%d-%m-%Y %H:%M:%S"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)

    qt_levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }
    qt_log = logging.getLogger("qt")
    qInstallMessageHandler(lambda msg_type, _ctx, msg: qt_log.log(qt_levels.get(msg_type, logging.INFO), msg))
