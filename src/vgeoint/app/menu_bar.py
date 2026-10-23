"""Port of MenuBar.cpp — same menus, actions, icons and order."""

from qgis.PyQt.QtGui import QAction, QKeySequence
from qgis.PyQt.QtWidgets import QMenu, QMenuBar

from vgeoint.app.basemaps import BASEMAPS
from vgeoint.common.utils import get_icon


def _action(icon: str, text: str, parent) -> QAction:
    return QAction(get_icon(icon), text, parent)


class MenuBar:
    def __init__(self, menu_bar: QMenuBar):
        self.menu_bar = menu_bar
        self.create_file_menu()
        self.create_view_menu()
        self.create_layer_menu()
        self.create_vector_menu()
        self.create_raster_menu()
        self.create_tool_menu()
        self.create_trajectory_menu()
        self.create_satellite_menu()
        self.create_help_menu()

    def add_view_action(self, act: QAction):
        self.view_menu.addAction(act)

    def create_file_menu(self):
        self.file_menu = QMenu("File", self.menu_bar)
        self.menu_bar.addMenu(self.file_menu)

        # Project management actions
        self.new_project_act = _action("NewProject.svg", "Dự án mới", self.file_menu)
        self.new_project_act.setShortcut(QKeySequence.StandardKey.New)
        self.open_project_act = _action("OpenProject.svg", "Mở dự án...", self.file_menu)
        self.open_project_act.setShortcut(QKeySequence.StandardKey.Open)
        self.save_project_act = _action("SaveProject.svg", "Lưu dự án", self.file_menu)
        self.save_project_act.setShortcut(QKeySequence.StandardKey.Save)
        self.save_project_as_act = _action("SaveProjectAs.svg", "Lưu dự án với tên...", self.file_menu)
        self.save_project_as_act.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.open_vector_file_act = _action("Vector.svg", "Mở file vector...", self.file_menu)
        self.open_raster_file_act = _action("Raster.svg", "Mở file raster...", self.file_menu)

        self.file_menu.addAction(self.new_project_act)
        self.file_menu.addAction(self.open_project_act)
        self.file_menu.addAction(self.save_project_act)
        self.file_menu.addAction(self.save_project_as_act)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.open_vector_file_act)
        self.file_menu.addAction(self.open_raster_file_act)
        self.file_menu.addSeparator()

    def create_view_menu(self):
        self.view_menu = QMenu("Xem", self.menu_bar)
        self.menu_bar.addMenu(self.view_menu)

        self.fit_view_act = _action("Home.svg", "Xem toàn bộ", self.view_menu)
        self.zoom_in_act = _action("ZoomIn.svg", "Phóng to", self.view_menu)
        self.zoom_out_act = _action("ZoomOut.svg", "Thu nhỏ", self.view_menu)
        self.pan_map_act = _action("PanMap.svg", "Kéo / Dịch", self.view_menu)
        self.cursor_click_act = _action("CursorClick.svg", "Chọn đối tượng", self.view_menu)

        self.view_menu.addAction(self.cursor_click_act)
        self.view_menu.addAction(self.pan_map_act)
        self.view_menu.addAction(self.zoom_in_act)
        self.view_menu.addAction(self.zoom_out_act)
        self.view_menu.addAction(self.fit_view_act)

    def create_layer_menu(self):
        self.layer_menu = QMenu("Layer", self.menu_bar)
        self.menu_bar.addMenu(self.layer_menu)

        self.add_vector_lyr_act = _action("AddVector.svg", "Thêm vector", self.layer_menu)
        self.add_raster_lyr_act = _action("AddRaster.svg", "Thêm raster", self.layer_menu)
        self.remove_lyr_act = _action("mActionRemoveLayer.svg", "Gỡ bỏ layer", self.layer_menu)

        self.layer_menu.addAction(self.add_vector_lyr_act)
        self.layer_menu.addAction(self.add_raster_lyr_act)
        self.layer_menu.addSeparator()
        self.layer_menu.addAction(self.remove_lyr_act)

    def create_vector_menu(self):
        self.vector_menu = QMenu("Vector", self.menu_bar)
        self.menu_bar.addMenu(self.vector_menu)

    def create_raster_menu(self):
        self.raster_menu = QMenu("Raster", self.menu_bar)
        self.menu_bar.addMenu(self.raster_menu)
        m = self.raster_menu

        self.local_cumulative_cut_stretch_act = _action("LocalCumulativeCutStretch.svg", "Lũy tích cục bộ", m)
        self.full_cumulative_cut_stretch_act = _action("FullCumulativeCutStretch.svg", "Lũy tích toàn bộ", m)
        self.local_std_dev_stretch_act = _action("LocalStdDevStretch.svg", "Độ lệch chuẩn cục bộ", m)
        self.full_std_dev_stretch_act = _action("FullStdDevStretch.svg", "Độ lệch chuẩn toàn bộ", m)
        self.local_histogram_stretch_act = _action("LocalHistogramStretch.svg", "Lược đồ mức xám cục bộ", m)
        self.full_histogram_stretch_act = _action("FullHistogramStretch.svg", "Lược đồ mức xám toàn bộ", m)
        self.band_math_act = _action("BandMath.svg", "Tính toán trên ảnh", m)
        self.color_composite_act = _action("ColorComposite.svg", "Tổ hợp màu", m)
        self.brightness_contrast_act = _action("BrightnessContrast.svg", "Độ sáng/ Độ tương phản", m)

        for act in (
            self.local_cumulative_cut_stretch_act,
            self.full_cumulative_cut_stretch_act,
            self.local_std_dev_stretch_act,
            self.full_std_dev_stretch_act,
            self.local_histogram_stretch_act,
            self.full_histogram_stretch_act,
            self.band_math_act,
            self.color_composite_act,
            self.brightness_contrast_act,
        ):
            m.addAction(act)

    def create_tool_menu(self):
        self.tool_menu = QMenu("Công cụ", self.menu_bar)
        m = self.tool_menu

        self.image_filter_act = _action("ImageFilter.svg", "Lọc ảnh", m)
        self.image_split_act = _action("SplitImage.svg", "Tách kênh ảnh", m)
        self.image_concatenating_act = _action("ConcatenateImages.svg", "Gộp kênh ảnh", m)
        self.color_space_convertion_act = _action("ColorSpace.svg", "Chuyển đổi không gian màu", m)
        self.change_detection_act = _action("ChangeDetection.svg", "Phát hiện thay đổi", m)
        # Temporary use change detection icon
        self.motion_detection_act = _action("ChangeDetection.svg", "Phát hiện biến động", m)
        self.object_tracking_act = _action("tracking.svg", "Theo dõi đối tượng", m)
        self.ship_detection_act = _action("ship_detection.svg", "Phát hiện tàu thuyền", m)
        self.ship_tracking_act = _action("Engine/Warship.svg", "Theo dõi tàu thuyền", m)
        self.vehicle_tracking_act = _action("DetectVehicles.svg", "Theo dõi phương tiện", m)
        self.building_segmentation_act = _action("BuildingSegmentation.svg", "Phân đoạn tòa nhà", m)
        self.tank_detection_act = _action("tank_detection.svg", "Phát hiện xe tăng", m)
        self.image_blending_act = _action("ImageBlending.svg", "Trộn ảnh", m)
        self.view_metadata_act = _action("Metadata.svg", "Xem metadata", m)
        self.auto_classification_act = _action("Classification.svg", "Phân loại tự động", m)
        # Not in the menu itself (same as C++), only connected.
        self.annotation_manager_act = _action("TextAnnotation/Manager.svg", "Quản lý ghi chú", m)

        for act in (
            self.image_filter_act,
            self.image_split_act,
            self.image_concatenating_act,
            self.color_space_convertion_act,
            self.change_detection_act,
            self.motion_detection_act,
            self.object_tracking_act,
            self.ship_detection_act,
            self.ship_tracking_act,
            self.vehicle_tracking_act,
            self.building_segmentation_act,
            self.tank_detection_act,
            self.image_blending_act,
            self.view_metadata_act,
            self.auto_classification_act,
        ):
            m.addAction(act)

        self.menu_bar.addMenu(m)

    def create_trajectory_menu(self):
        """Not in the C++ app: trajectories of moving objects (the Detect & Draw tool, ported)."""
        self.trajectory_menu = QMenu("Phát hiện quỹ đạo", self.menu_bar)
        self.uav_trajectory_act = _action("tracking.svg", "Phát hiện quỹ đạo trên ảnh UAV...", self.trajectory_menu)
        self.trajectory_menu.addAction(self.uav_trajectory_act)
        self.menu_bar.addMenu(self.trajectory_menu)

    def create_satellite_menu(self):
        """Own menu for downloading imagery (the C++ app had it at the end of "Công cụ")."""
        self.satellite_menu = QMenu("Tải ảnh vệ tinh", self.menu_bar)
        self.google_earth_engine_act = _action(
            "GoogleEarthEngine.svg", "Tải ảnh từ Google Earth Engine...", self.satellite_menu
        )
        self.free_imagery_act = _action("Earth.svg", "Tải ảnh miễn phí (không cần tài khoản)...", self.satellite_menu)
        self.satellite_menu.addAction(self.free_imagery_act)
        self.satellite_menu.addAction(self.google_earth_engine_act)
        self.satellite_menu.addSeparator()
        # Online basemaps: viewed on the map only (their terms do not allow saving the imagery).
        self.basemap_menu = self.satellite_menu.addMenu(get_icon("Earth.svg"), "Ảnh nền trực tuyến (chỉ xem)")
        self.basemap_acts = {}
        for key, basemap in BASEMAPS.items():
            act = _action("Earth.svg", basemap.name, self.basemap_menu)
            self.basemap_menu.addAction(act)
            self.basemap_acts[key] = act
        self.menu_bar.addMenu(self.satellite_menu)

    def create_help_menu(self):
        self.help_menu = QMenu("Trợ giúp", self.menu_bar)
        self.menu_bar.addMenu(self.help_menu)

        self.information_act = _action("Information.svg", "Thông tin chương trình", self.help_menu)
        self.contact_act = _action("Contact.svg", "Liên hệ", self.help_menu)
        self.help_act = _action("Help.svg", "Trợ giúp", self.help_menu)

        self.help_menu.addAction(self.information_act)
        self.help_menu.addAction(self.contact_act)
        self.help_menu.addAction(self.help_act)
