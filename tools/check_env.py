"""Phase-0 environment check: QGIS, GDAL, OpenCV, QPSQL driver, resources."""

import sys

ok = True


def check(name, fn):
    global ok
    try:
        print(f"[ OK ] {name}: {fn()}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"[FAIL] {name}: {e}")


def qgis_version():
    from qgis.core import Qgis
    return Qgis.version()


def qt_version():
    from qgis.PyQt.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
    return f"Qt {QT_VERSION_STR}, PyQt {PYQT_VERSION_STR}"


def gdal_version():
    from osgeo import gdal
    return gdal.__version__


def opencv_version():
    import cv2
    return cv2.__version__


def qpsql():
    from qgis.PyQt.QtWidgets import QApplication
    from qgis.PyQt.QtSql import QSqlDatabase
    _app = QApplication.instance() or QApplication(sys.argv)
    drivers = QSqlDatabase.drivers()
    if "QPSQL" not in drivers:
        raise RuntimeError(f"QPSQL missing, available: {drivers}")
    return "QPSQL available"


def psycopg_version():
    import psycopg
    return psycopg.__version__


def resources():
    from vgeoint.common.paths import RESOURCES_DIR
    rccs = sorted(p.name for p in RESOURCES_DIR.glob("*.rcc"))
    if not rccs:
        raise RuntimeError("no .rcc found - run `pixi run build-resources`")
    return ", ".join(rccs)


check("QGIS", qgis_version)
check("Qt", qt_version)
check("GDAL", gdal_version)
check("OpenCV", opencv_version)
check("QtSql", qpsql)
check("psycopg", psycopg_version)
check("Resources", resources)
sys.exit(0 if ok else 1)
