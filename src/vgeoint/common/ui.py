"""Helpers to reuse the original Qt Designer .ui files unchanged."""

import io
import xml.etree.ElementTree as ET
from functools import cache

from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon

from vgeoint.common.paths import resource, ui_file


def _python_module(app: str, header: str) -> str:
    """Map a C++ custom-widget header to the Python module that provides the class.

    qgs*.h -> qgis.gui; project widgets (AccountWidget.h, cannywidget.h...) -> vgeoint.<app>.widgets
    """
    if header.lower().startswith("qgs"):
        return "qgis.gui"
    return f"vgeoint.{app}.widgets"


@cache
def load_ui_class(app: str, name: str):
    """Return the generated Ui_* form class for ui/<app>/<name>.ui."""
    tree = ET.parse(ui_file(app, name))
    for header in tree.getroot().iter("header"):
        header.text = _python_module(app, header.text)
        header.attrib.pop("location", None)
    source = io.StringIO(ET.tostring(tree.getroot(), encoding="unicode"))
    # compileUi + exec instead of loadUiType: the latter fails when the top-level
    # widget is a QGIS class (e.g. QgsDockWidget), and only the form class is needed.
    code = io.StringIO()
    uic.compileUi(source, code)
    scope = {}
    exec(code.getvalue(), scope)
    return scope[f"Ui_{tree.getroot().findtext("class")}"]


def icon(qrc_path: str) -> QIcon:
    return QIcon(resource(qrc_path))
