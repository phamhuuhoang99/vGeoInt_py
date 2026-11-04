"""Port of MainController.cpp.

Dialogs are looked up by module name under vgeoint.app.dialogs, so each later phase only has to add
the module; until then the action shows a "not ported yet" message instead of failing.
"""

import importlib

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt

from vgeoint.app.basemaps import BASEMAPS, add_basemap
from vgeoint.app.models.image_enhancement_model import ImageEnhancementModel
from vgeoint.app.models.layer_panel_model import LayerPanelModel
from vgeoint.app.models.project_model import ProjectModel
from vgeoint.app.models.raster_model import RasterModel
from vgeoint.app.models.vector_model import VectorModel
from vgeoint.app.plugins import RASTER
from vgeoint.common.utils import message_timeout

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")
VIET_NAM = QgsRectangle(102.1, 8.2, 109.5, 23.4)


class MainController:
    def __init__(self, main_window):
        self.main_window = main_window
        self.vector_model = VectorModel(main_window)
        self.raster_model = RasterModel(main_window)
        self.project_model = ProjectModel(main_window)
        self.layer_panel_model = LayerPanelModel(main_window)
        self.image_enhancement_model = ImageEnhancementModel(main_window)

    # ------------------------------------------------------------------ data
    def add_vector(self, file_name: str | None = None):
        if file_name:
            self.vector_model.add_vector(file_name)
        else:
            self.vector_model.add_vector_dialog()

    def add_raster(self, file_name: str | None = None):
        if file_name:
            self.raster_model.add_raster(file_name)
        else:
            self.raster_model.add_raster_dialog()

    def update_crs(self):
        self.project_model.update_crs()

    def remove_layer(self):
        self.layer_panel_model.remove_layer()

    def save_as(self):
        layer = self.main_window.active_layer()
        if isinstance(layer, QgsRasterLayer):
            self.raster_model.save_as(layer)
        elif isinstance(layer, QgsVectorLayer):
            self.vector_model.save_as(layer)

    # --------------------------------------------------------------- project
    def new_project(self):
        self.project_model.new_project()

    def open_project(self):
        self.project_model.open_project()

    def save_project(self) -> bool:
        return self.project_model.save_project()

    def save_project_as(self):
        self.project_model.save_project_as()

    def has_unsaved_changes(self) -> bool:
        return self.project_model.has_unsaved_changes()

    def get_project_file_path(self) -> str:
        return self.project_model.project_file_path

    def set_project_modified(self, modified: bool = True):
        self.project_model.set_project_modified(modified)

    # ----------------------------------------------------------- raster menu
    def local_cumulative_cut_stretch(self):
        self.image_enhancement_model.local_cumulative_cut_stretch()

    def full_cumulative_cut_stretch(self):
        self.image_enhancement_model.full_cumulative_cut_stretch()

    def local_std_dev_stretch(self):
        self.image_enhancement_model.local_std_dev_stretch()

    def full_std_dev_stretch(self):
        self.image_enhancement_model.full_std_dev_stretch()

    def local_histogram_stretch(self):
        self.image_enhancement_model.local_histogram_stretch()

    def full_histogram_stretch(self):
        self.image_enhancement_model.full_histogram_stretch()

    # --------------------------------------------------------------- dialogs
    def _exec_dialog(self, module: str, class_name: str, *args, modal_exec: bool = True, modal: bool = True):
        """Open vgeoint.app.dialogs.<module>.<class_name>(*args)."""
        try:
            mod = importlib.import_module(f"vgeoint.app.dialogs.{module}")
        except ModuleNotFoundError as e:
            if e.name != f"vgeoint.app.dialogs.{module}" and e.name != "vgeoint.app.dialogs":
                raise
            self.main_window.message_bar.pushMessage(
                class_name,
                "Chức năng đang được chuyển đổi sang phiên bản mới.",
                Qgis.MessageLevel.Info,
                message_timeout(),
            )
            return None
        dialog = getattr(mod, class_name)(*args)
        # The C++ app only wired `complete` for DLL plugins, so the dialogs' "auto add result"
        # checkbox never worked; connect it for every dialog that reports output files.
        if hasattr(dialog, "complete") and hasattr(dialog, "auto_add_output_files"):
            dialog.complete.connect(lambda d=dialog: self.add_output_files(d))
        dialog.setModal(modal)
        if modal_exec:
            dialog.exec()
            dialog.deleteLater()
        else:
            dialog.show()
        return dialog

    def add_output_files(self, source):
        """Add the results of a dialog/plugin to the map when its "auto add" option is on.

        `output_files` / `output_data_type` may be attributes or methods (BPluginInterface style).
        """
        if not source.auto_add_output_files():
            return
        files = source.output_files() if callable(source.output_files) else source.output_files
        data_type = getattr(source, "output_data_type", RASTER)
        data_type = data_type() if callable(data_type) else data_type
        add = self.add_raster if data_type == RASTER else self.add_vector
        for output in files:
            add(output)

    def _std_dialog(self, module: str, class_name: str):
        mw = self.main_window
        return self._exec_dialog(module, class_name, mw, mw.map_canvas, mw.layer_tree_view)

    def color_composite(self):
        self._std_dialog("color_composite", "ColorCompositeDialog")

    def band_math(self):
        self._std_dialog("band_math", "BandMathDialog")

    def brightness_contrast(self):
        self._std_dialog("brightness_contrast", "BrightnessContrastDialog")

    def image_filter(self):
        self._std_dialog("image_filter", "ImageFilterDialog")

    def image_split(self):
        self._std_dialog("image_split", "ImageSplitDialog")

    def image_enhancement(self):
        self._std_dialog("raster_analysis", "ImageEnhancementDialog")

    def pca(self):
        self._std_dialog("raster_analysis", "PcaDialog")

    def color_space_convertion(self):
        self._std_dialog("color_space_convertion", "ColorSpaceConvertionDialog")

    def change_detection(self):
        self._std_dialog("change_detection", "ChangeDetectionDialog")

    def motion_detection(self):
        self._std_dialog("motion_detection", "MotionDetectionDialog")

    def object_tracking(self):
        self._std_dialog("object_tracking", "ObjectTrackingDialog")

    def image_concatenating(self):
        self._std_dialog("image_concatenating", "ImageConcatenatingDialog")

    def view_metadata(self):
        self._std_dialog("metadata_viewer", "MetadataViewerDialog")

    def annotation_manager(self):
        self._std_dialog("annotation_manager", "AnnotationManagerDialog")

    def ship_detection(self):
        self._std_dialog("ship_detection", "ShipDetectionDialog")

    def ship_tracking(self):
        self._std_dialog("ship_tracking", "ShipTrackingDialog")

    def vehicle_tracking(self):
        self._std_dialog("vehicle_tracking", "VehicleTrackingDialog")

    def building_segmentation(self):
        self._std_dialog("building_segmentation", "BuildingSegmentationDialog")

    def tank_detection(self):
        self._std_dialog("tank_detection", "TankDetectionDialog")

    def image_blending(self):
        self._exec_dialog("image_blending", "ImageBlendingDialog", self.main_window)

    def auto_classification(self):
        self._std_dialog("auto_classification", "AutoClassificationDialog")

    def google_earth_engine(self):
        self._modeless_dialog("google_earth_engine", "GoogleEarthEngineDialog")

    def add_basemap(self, key: str):
        """Online basemap at the bottom of the layers; on an empty map, zoom to Viet Nam."""
        mw = self.main_window
        empty = not mw.map_canvas.layers()
        layer = add_basemap(key)
        if layer is None:
            mw.message_bar.pushMessage(
                "Ảnh nền", f"Không tải được {BASEMAPS[key].name}", Qgis.MessageLevel.Critical, message_timeout()
            )
            return
        if empty:
            # Let the bridge put the layer on the canvas first: on the first layer it zooms to the full
            # extent (the whole world for a tile layer), which would undo this zoom.
            mw.layer_tree_map_canvas_bridge.setCanvasLayers()
            transform = QgsCoordinateTransform(WGS84, mw.map_canvas.mapSettings().destinationCrs(), QgsProject.instance())
            mw.map_canvas.setExtent(transform.transformBoundingBox(VIET_NAM))
        mw.map_canvas.refresh()
        mw.message_bar.pushMessage(
            "Ảnh nền",
            f"Đã thêm {BASEMAPS[key].name} ({BASEMAPS[key].attribution}): chỉ để xem/số hoá, không lưu ảnh ra file.",
            Qgis.MessageLevel.Info,
            message_timeout(),
        )

    def free_imagery(self):
        self._modeless_dialog("free_imagery", "FreeImageryDialog")

    def uav_trajectory(self):
        self._modeless_dialog("uav_trajectory", "UavTrajectoryDialog")

    def satellite_trajectory(self):
        self._modeless_dialog("satellite_trajectory", "SatelliteTrajectoryDialog")

    def object_tank(self):
        self._modeless_dialog("object_detection", "TankObjectDialog")

    def object_aircraft(self):
        self._modeless_dialog("object_detection", "AircraftObjectDialog")

    def _modeless_dialog(self, module: str, class_name: str):
        # Not modal: the map stays usable (pan/zoom, draw the region of interest, look at results).
        mw = self.main_window
        dialog = self._exec_dialog(
            module, class_name, mw, mw.map_canvas, mw.layer_tree_view, modal_exec=False, modal=False
        )
        if dialog is not None:
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def vector_labeling(self, layer: QgsVectorLayer):
        mw = self.main_window
        self._exec_dialog("vector_labeling", "VectorLabelingDialog", layer, mw.map_canvas, mw)

    def settings_dialog(self):
        self._exec_dialog("settings", "SettingsDialog", self.main_window, modal_exec=False)

    def tag_annotation_setting(self):
        self._exec_dialog("tag_annotation_setting", "TagAnnotationSettingDialog", self.main_window, modal_exec=False)

    def save_map_as_pdf(self):
        from qgis.core import QgsProject

        mw = self.main_window
        annotations = QgsProject.instance().annotationManager().annotations()
        dialog = self._exec_dialog("map_save", "MapSaveDialog", mw, mw.map_canvas, [], annotations, modal_exec=False)
        if dialog is not None:
            dialog.setModal(False)
