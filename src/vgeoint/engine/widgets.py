"""Custom widgets promoted in the vGeoEngine .ui files, resolved lazily for uic.

uic-generated code does `from vgeoint.engine.widgets import X`; each name is imported from its module
on first use so a .ui only needs the widgets it actually contains.
"""

import importlib

_MODULES = {
    "AccountWidget": "account_widget",
    "DatabaseWidget": "database_widget",
    "ObjectTableWidget": "object_table_widget",
    "MediaInputWidget": "media_input_widget",
    "MediaViewerWidget": "media_viewer_widget",
    "ImageViewerWidget": "image_viewer_widget",
    "SearchingWidget": "searching_widget",
    "AircraftAttributeWidget": "attribute_widgets",
    "ShipAttributeWidget": "attribute_widgets",
    "TankAttributeWidget": "attribute_widgets",
    "RocketAttributeWidget": "attribute_widgets",
    "AircraftSearchingWidget": "object_searching_widgets",
    "ShipSearchingWidget": "object_searching_widgets",
    "TankSearchingWidget": "object_searching_widgets",
    "RocketSearchingWidget": "object_searching_widgets",
}


def __getattr__(name: str):
    module = _MODULES.get(name)
    if module is None:
        raise AttributeError(name)
    return getattr(importlib.import_module(f"vgeoint.engine.{module}"), name)
