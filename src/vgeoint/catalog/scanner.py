"""Port of ScannerThread.cpp — walk the library folders and record geodata files.

Qt SQL connections may only be used from the thread that created them; the C++ thread reused the GUI
thread's connection. This thread opens its own connection by name.
"""

import threading

from qgis.PyQt.QtCore import QDir, QDirIterator, QThread, pyqtSignal
from qgis.PyQt.QtSql import QSqlDatabase

from vgeoint.catalog.geo_info_reader import GeoInfoReader
from vgeoint.catalog.models import DirectoryModel, GeoData, GeoDataModel, Library
from vgeoint.common.database import DbConfig, open_database

SCANNER_CONNECTION = "vgeocatalog_scanner"


class ScannerThread(QThread):
    report = pyqtSignal(str, bool)
    finished_scanning = pyqtSignal(str)

    def __init__(self, config: DbConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.library = Library()
        self._stop = threading.Event()

    def set_library(self, lib: Library):
        self.library = lib
        self._stop.clear()

    def stop(self):
        self._stop.set()

    def run(self):
        # A connection belongs to the thread that created it: use a fresh name for every run.
        connection = f"{SCANNER_CONNECTION}_{threading.get_ident()}"
        db = open_database(self.config, connection)
        directory_model = DirectoryModel(db)
        geo_data_model = GeoDataModel(db)
        reader = GeoInfoReader()

        lines = [f"* Lọc định dạng:\n    {self.library.filters_str()}\n", "* Đã quét folder:\n"]
        for directory in directory_model.get_dirs_from_lib(self.library):
            if self._stop.is_set():
                break
            if not directory.enabled:
                continue
            lines.append(f"    {directory.path}\n")
            it = QDirIterator(
                directory.path,
                self.library.star_filters(),
                QDir.Filter.Files,
                QDirIterator.IteratorFlag.Subdirectories,
            )
            while it.hasNext():
                if self._stop.is_set():
                    break
                file_name = it.next()
                reader.set_file_name(file_name)
                reader.exec()
                if reader.is_geo_data():
                    geo_data_model.add_or_update(
                        GeoData(
                            0,
                            file_name,
                            reader.date_time,
                            reader.extent_str,
                            reader.coordinate_system,
                            reader.srid,
                            reader.geom_wkt,
                            self.library.id,
                        )
                    )
                    self.report.emit(file_name, True)
                else:
                    self.report.emit(file_name, False)
        db.close()
        del db, directory_model, geo_data_model
        QSqlDatabase.removeDatabase(connection)
        self.finished_scanning.emit("".join(lines))
