"""vGeoCatalog entry point (port of vGeoCatalog/main.cpp)."""

import sys

from qgis.core import QgsApplication

from vgeoint.common.bootstrap import create_app, install_file_log
from vgeoint.common.defines import CATALOG_NAME


def main() -> int:
    app = create_app(CATALOG_NAME)
    install_file_log(CATALOG_NAME)

    from vgeoint.catalog.main_window import MainWindow

    window = MainWindow()
    window.show()
    result = app.exec()
    QgsApplication.exitQgis()
    return result


if __name__ == "__main__":
    sys.exit(main())
