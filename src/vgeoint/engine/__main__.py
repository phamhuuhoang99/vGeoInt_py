"""vGeoEngine entry point (port of vGeoEngine/main.cpp)."""

import sys

from qgis.core import QgsApplication

from vgeoint.common.bootstrap import create_app, install_exception_hook, install_file_log
from vgeoint.common.defines import ENGINE_NAME


def main() -> int:
    app = create_app(ENGINE_NAME)
    install_file_log(ENGINE_NAME)
    install_exception_hook(ENGINE_NAME)

    from vgeoint.engine.main_window import MainWindow

    window = MainWindow()
    window.show()
    result = app.exec()
    QgsApplication.exitQgis()
    return result


if __name__ == "__main__":
    sys.exit(main())
