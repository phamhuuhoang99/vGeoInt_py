from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import QSplashScreen

from vgeoint.common.bootstrap import create_app, install_exception_hook, install_file_log
from vgeoint.common.defines import SOFT_NAME


def main() -> int:
    app = create_app(SOFT_NAME)
    install_file_log(SOFT_NAME)
    install_exception_hook(SOFT_NAME)

    splash = QSplashScreen(QPixmap(":/myicon/vietnam.jpg"))
    splash.show()
    QgsApplication.processEvents()

    from vgeoint.app.main_window import MainWindow

    window = MainWindow()
    window.show()
    splash.finish(window)

    result = app.exec()
    QgsApplication.exitQgis()
    return result
