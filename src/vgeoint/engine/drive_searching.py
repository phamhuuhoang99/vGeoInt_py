"""Port of DriveSearching.cpp — the drive letter prepended to media paths stored without label."""

from qgis.core import QgsSettings

# DriveSearching.cpp uses QSettings("vGeoInt", "vGeoEngine"), not the "DMA" organization of the other
# settings; keep that exact scope. Tests point this at a throwaway scope.
SETTINGS_SCOPE = ("vGeoInt", "vGeoEngine")
KEY = "DriveSearching"
DEFAULT = "C:/"


class DriveSearching:
    _disk_label = DEFAULT

    @staticmethod
    def set_disk_label(disk_label: str):
        QgsSettings(*SETTINGS_SCOPE).setValue(KEY, disk_label)
        DriveSearching._disk_label = disk_label

    @staticmethod
    def read_registered_disk_label():
        DriveSearching._disk_label = str(QgsSettings(*SETTINGS_SCOPE).value(KEY, DEFAULT))

    @staticmethod
    def drive_label() -> str:
        return DriveSearching._disk_label
