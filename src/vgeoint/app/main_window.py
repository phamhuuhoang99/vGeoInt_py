"""Port of MainWindow.cpp — same docks, toolbars, menus, order, icons and texts as the C++ app."""

import subprocess
import sys
from pathlib import Path

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFileUtils,
    QgsLayerTreeModel,
    QgsMapLayer,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.gui import (
    QgsAdvancedDigitizingDockWidget,
    QgsDockWidget,
    QgsLayerTreeMapCanvasBridge,
    QgsLayerTreeView,
    QgsMapCanvas,
    QgsMapCanvasAnnotationItem,
    QgsMapOverviewCanvas,
    QgsMapToolIdentifyFeature,
    QgsMapToolPan,
    QgsMapToolZoom,
    QgsMessageBar,
    QgsRubberBand,
    QgsStatusBar,
)
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QAction, QColor, QCursor, QIcon
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QGridLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QSlider,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from vgeoint.app import maptools
from vgeoint.app.layer_panel_menu import LayerPanelMenu
from vgeoint.app.main_controller import MainController
from vgeoint.app.menu_bar import MenuBar
from vgeoint.app.plugins import RASTER, load_plugins
from vgeoint.app.status_widgets import CoordinateWidget, ScaleWidget
from vgeoint.common.defines import CATALOG_NAME, ENGINE_NAME, SOFT_NAME, VERSION
from vgeoint.common.paths import RESOURCES_DIR
from vgeoint.common.ui import load_ui_class
from vgeoint.common.utils import get_icon, message_timeout, settings

Ui_MainWindowClass = load_ui_class("app", "MainWindow")

Btn = QMessageBox.StandardButton
Fixed = QSizePolicy.Policy.Fixed
LEFT = Qt.DockWidgetArea.LeftDockWidgetArea
LEFT_RIGHT = Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea

T_METADATA_VIEWER = "T_MetadataViewer"
T_ANNOTATION_MANAGER = "T_AnnotationManager"
V_SHAPE_FILE_CREATING = "V_ShapeFileCreating"
V_VECTOR_RENDER = "V_VectorRenderPlugin"
V_VECTOR_LABELING = "V_VectorLabelingPlugin"

SLIDER_STYLE = (
    "QSlider::groove:horizontal { border: 1px solid #bbb; background: white; height: 12px; border-radius: 4px; }"
    "QSlider::sub-page:horizontal{ background: %1; border: 1px solid #777; height: 12px; border-radius: 4px; }"
    "QSlider::add-page:horizontal{ background: #fff; border: 1px solid #777; height: 12px; border-radius: 4px; }"
    "QSlider::handle:horizontal{ background: qlineargradient(x1 : 0, y1 : 0, x2 : 1, y2 : 1, stop : 0 #eee, stop:1 #ccc); border: 1px solid #777; width: 13px; margin-top: -2px; margin-bottom: -2px; border-radius: 4px; }"
    "QSlider::handle:horizontal:hover{ background: qlineargradient(x1 : 0, y1 : 0, x2 : 1, y2 : 1, stop : 0 #fff, stop:1 #ddd); border: 1px solid #444; border-radius: 4px; }"
    "QSlider::sub-page:horizontal:disabled{ background: #bbb; border-color: #999; }"
    "QSlider::add-page : horizontal : disabled{ background: #eee; border-color: #999; }"
    "QSlider::handle : horizontal : disabled{ background: #eee; border: 1px solid #aaa; border-radius: 4px; }"
)
LINE_EDIT_STYLE = "QLineEdit { border: 1px solid #777; border-radius: 4px; margin-left: 4px; margin-right: 4px;}"


def _slider_style(color: str) -> str:
    return SLIDER_STYLE.replace("%1", color)


def _value_edit(text: str, tooltip: str, size: QSize, parent) -> QLineEdit:
    edit = QLineEdit(text, parent)
    edit.setToolTip(tooltip)
    edit.setStyleSheet(LINE_EDIT_STYLE)
    edit.setSizePolicy(Fixed, Fixed)
    edit.setFixedSize(size)
    edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return edit


def _launch_module(module: str):
    """Start a sibling app (vGeoCatalog / vGeoEngine) detached, like QProcess::startDetached."""
    flags = subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0
    subprocess.Popen([sys.executable, "-m", module], creationflags=flags)


class MainWindow(QMainWindow, Ui_MainWindowClass):
    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        if MainWindow._instance is not None:
            QMessageBox.critical(self, SOFT_NAME, "Phần mềm đang hoạt động!")
            return

        self.setupUi(self)
        self.setWindowTitle(SOFT_NAME)
        self.setWindowIcon(QIcon(str(RESOURCES_DIR / "vGeoInt.ico")))
        self.setAcceptDrops(True)
        MainWindow._instance = self
        self.project = QgsProject.instance()

        self.plugins: dict[str, list] = {}  # name -> [action, plugin]
        self.feature_selection_layer: QgsVectorLayer | None = None
        self.feature_selection_id = -1
        self.rubber_band: QgsRubberBand | None = None

        self.main_controller = MainController(self)

        self.create_menu_bar()
        self.create_map_canvas()
        self.create_layer_panel()
        self.create_overview()
        self.create_status_bar()

        self.load_supported_raster_formats()
        self.load_supported_vector_formats()
        self.load_plugins()
        self.create_plugin_actions()

        self.create_cad_widget()
        self.create_canvas_tools()

        self.create_view_tool_bar()
        self.create_data_tool_bar()
        self.create_vector_tool_bar()
        self.create_raster_tool_bar()
        self.create_module_tool_bar()
        self.create_connections()
        self.load_settings()

        # Thiết lập map tool mặc định
        self.map_canvas.setMapTool(self.tool_identify_feature)

        # Hệ tọa độ mặc định ban đầu
        epsg_id = int(settings().value("MapCanvas/EPSG", 4326))
        srs = QgsCoordinateReferenceSystem.fromEpsgId(epsg_id)
        self.project.setCrs(srs)
        self.project.setEllipsoid(srs.ellipsoidAcronym())

    # ------------------------------------------------------------- accessors
    @classmethod
    def instance(cls) -> "MainWindow | None":
        return cls._instance

    def active_layer(self) -> QgsMapLayer | None:
        return self.layer_tree_view.currentLayer() if self.layer_tree_view else None

    def cad_dock_widget(self) -> QgsAdvancedDigitizingDockWidget:
        return self.advanced_digitizing_dock_widget

    def raster_layers(self) -> list[QgsRasterLayer]:
        return [l for l in self.map_canvas.layers() if l.type() == Qgis.LayerType.Raster]

    def vector_layers(self) -> list[QgsVectorLayer]:
        return [l for l in self.map_canvas.layers() if l.type() == Qgis.LayerType.Vector]

    def selected_layers(self) -> list[QgsMapLayer]:
        return self.layer_tree_view.selectedLayers()

    def freeze_canvases(self, frozen: bool = True):
        self.map_canvas.freeze(frozen)

    def get_plugin_action_by_code(self, code: str) -> QAction | None:
        entry = self.plugins.get(code)
        return entry[0] if entry else None

    # ---------------------------------------------------------------- events
    def closeEvent(self, event):
        # Check for unsaved project changes
        if self.main_controller.has_unsaved_changes():
            result = QMessageBox.question(
                self,
                "Thoát chương trình",
                "Dự án có thay đổi chưa lưu. Bạn có muốn lưu trước khi thoát không?",
                Btn.Save | Btn.Discard | Btn.Cancel,
            )
            if result == Btn.Save and not self.main_controller.save_project():
                event.ignore()  # User cancelled save
                return
            if result == Btn.Cancel:
                event.ignore()  # User cancelled close
                return
        elif QMessageBox.question(self, "Thoát chương trình", "Bạn có chắc chắn muốn thoát?") != Btn.Yes:
            event.ignore()
            return

        self.save_settings()
        super().closeEvent(event)

    def _supported(self, file_name: str) -> str | None:
        ext = Path(file_name).suffix.lstrip(".").upper()
        if ext in self.supported_raster_formats:
            return "raster"
        if ext in self.supported_vector_formats:
            return "vector"
        return None

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() and any(self._supported(u.toLocalFile()) for u in mime.urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_name = url.toLocalFile()
            kind = self._supported(file_name)
            if kind == "raster":
                self.main_controller.add_raster(file_name)
            elif kind == "vector":
                self.main_controller.add_vector(file_name)

    # --------------------------------------------------------------- plugins
    def load_plugins(self):
        for name, plugin in load_plugins(self).items():
            plugin.setWindowFlags(plugin.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
            self.plugins[name] = [None, plugin]

    def load_supported_raster_formats(self):
        filters = QgsProviderRegistry.instance().fileRasterFilters()
        self.supported_raster_formats = sorted({e.upper() for e in QgsFileUtils.extensionsFromFilter(filters)})

    def load_supported_vector_formats(self):
        filters = QgsProviderRegistry.instance().fileVectorFilters()
        self.supported_vector_formats = sorted({e.upper() for e in QgsFileUtils.extensionsFromFilter(filters)})

    def create_plugin_actions(self):
        # Thêm menu từ plugins
        mb = self.menu_bar_
        insert_raster_separator = len(mb.raster_menu.actions()) > 0
        for key, entry in self.plugins.items():
            plugin = entry[1]
            if key.startswith("V_"):
                menu = mb.vector_menu
            elif key.startswith("R_"):
                menu = mb.raster_menu
                if insert_raster_separator:
                    menu.addSeparator()
                    insert_raster_separator = False
            elif key.startswith("T_"):
                menu = mb.tool_menu
            else:
                continue
            entry[0] = QAction(plugin.get_icon(), plugin.vn_name(), menu)
            menu.addAction(entry[0])

    # --------------------------------------------------------------- widgets
    def create_menu_bar(self):
        # Named menu_bar_ to avoid shadowing QMainWindow.menuBar().
        self.menu_bar_ = MenuBar(self.mainMenuBar)

    def create_map_canvas(self):
        s = settings()
        color = QColor(
            int(s.value("MapCanvas/Red", 255)),
            int(s.value("MapCanvas/Green", 255)),
            int(s.value("MapCanvas/Blue", 255)),
        )

        central = self.centralWidget
        self.map_canvas = QgsMapCanvas(central)
        self.map_canvas.freeze(False)
        self.map_canvas.setVisible(True)
        self.map_canvas.setCanvasColor(color)
        self.map_canvas.enableAntiAliasing(True)
        layout = QGridLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.message_bar = QgsMessageBar(central)
        self.message_bar.setSizePolicy(QSizePolicy.Policy.Minimum, Fixed)

        layout.addWidget(self.map_canvas, 0, 0, 2, 1)
        layout.addWidget(self.message_bar, 0, 0, 1, 1)

    def create_layer_panel(self):
        self.layer_panel_widget = QgsDockWidget("Layers", self)
        self.layer_panel_widget.setObjectName("LayerPanelWidget")
        self.layer_panel_widget.setAllowedAreas(LEFT_RIGHT)

        layer_tree = self.project.layerTreeRoot()
        model = QgsLayerTreeModel(layer_tree, self)
        for flag in (
            QgsLayerTreeModel.Flag.AllowNodeReorder,
            QgsLayerTreeModel.Flag.AllowNodeRename,
            QgsLayerTreeModel.Flag.AllowNodeChangeVisibility,
            QgsLayerTreeModel.Flag.ShowLegendAsTree,
            QgsLayerTreeModel.Flag.UseEmbeddedWidgets,
        ):
            model.setFlag(flag)
        model.setAutoCollapseLegendNodes(10)

        self.layer_tree_view = QgsLayerTreeView(self)
        self.layer_tree_view.setModel(model)
        self.layer_panel_menu = LayerPanelMenu(self.layer_tree_view, self.map_canvas, self.main_controller)
        self.layer_tree_view.setMenuProvider(self.layer_panel_menu)

        # add group action
        action_add_group = QAction(self.tr("Add Group"), self)
        action_add_group.setIcon(get_icon("mActionAddGroup.svg"))
        action_add_group.setToolTip("Thêm nhóm")
        action_add_group.triggered.connect(self.layer_tree_view.defaultActions().addGroup)

        # expand / collapse tool buttons
        action_expand_all = QAction(self.tr("Expand All"), self)
        action_expand_all.setIcon(get_icon("mActionExpandTree.svg"))
        action_expand_all.setToolTip("Mở rộng tất cả")
        action_expand_all.triggered.connect(self.layer_tree_view.expandAllNodes)

        action_collapse_all = QAction(self.tr("Collapse All"), self)
        action_collapse_all.setIcon(get_icon("mActionCollapseTree.svg"))
        action_collapse_all.setToolTip("Thu gọn tất cả")
        action_collapse_all.triggered.connect(self.layer_tree_view.collapseAllNodes)

        toolbar = QToolBar()
        toolbar.setIconSize(QSize(24, 24))
        toolbar.addAction(action_add_group)
        toolbar.addAction(action_expand_all)
        toolbar.addAction(action_collapse_all)
        toolbar.addAction(self.menu_bar_.remove_lyr_act)

        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(toolbar)
        vbox.addWidget(self.layer_tree_view)

        w = QWidget()
        w.setLayout(vbox)
        self.layer_panel_widget.setWidget(w)
        self.addDockWidget(LEFT, self.layer_panel_widget)
        self.layer_tree_map_canvas_bridge = QgsLayerTreeMapCanvasBridge(layer_tree, self.map_canvas, self)

        # Tạo action cho phép đóng mở widget này
        self.menu_bar_.view_menu.addSeparator()
        show_layer_panel_action = self.layer_panel_widget.toggleViewAction()
        show_layer_panel_action.setText("Bảng điều khiển layer")
        self.menu_bar_.add_view_action(show_layer_panel_action)

    def create_overview(self):
        self.overview_widget = QgsDockWidget("Tổng quan", self)
        self.overview_widget.setObjectName("OverviewWidget")
        self.overview_widget.setAllowedAreas(LEFT_RIGHT)

        overview = QgsMapOverviewCanvas(self.overview_widget, self.map_canvas)
        overview.setBackgroundColor(QColor(Qt.GlobalColor.white))
        overview.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.overview_widget.setWidget(overview)
        self.overview_canvas = overview

        self.addDockWidget(LEFT, self.overview_widget)
        self.layer_tree_map_canvas_bridge.setOverviewCanvas(overview)
        # Tạo Action cho phép đóng mở widget này
        show_overview_action = self.overview_widget.toggleViewAction()
        show_overview_action.setText("Cửa sổ tổng quan")
        self.menu_bar_.add_view_action(show_overview_action)

    def create_status_bar(self):
        self.qgs_status_bar = QgsStatusBar(self.mainStatusBar)
        self.mainStatusBar.addPermanentWidget(self.qgs_status_bar)

        progress_bar = QProgressBar(self.qgs_status_bar)
        progress_bar.setObjectName("ProgressBar")
        progress_bar.setMinimumWidth(200)
        progress_bar.setMaximumHeight(18)
        progress_bar.hide()
        self.qgs_status_bar.addPermanentWidget(progress_bar)

        def render_starting():
            if not progress_bar.isVisible():
                progress_bar.show()
            progress_bar.setMaximum(0)
            progress_bar.setValue(-1)

        def canvas_refreshed():
            progress_bar.reset()
            progress_bar.hide()

        self.map_canvas.renderStarting.connect(render_starting)
        self.map_canvas.mapCanvasRefreshed.connect(canvas_refreshed)

        self.scale_widget = ScaleWidget(self.qgs_status_bar, self.map_canvas)
        self.map_canvas.scaleChanged.connect(self.scale_widget.set_scale)
        self.qgs_status_bar.addPermanentWidget(self.scale_widget)

        self.coordinate_widget = CoordinateWidget(self.qgs_status_bar, self.map_canvas)
        self.qgs_status_bar.addPermanentWidget(self.coordinate_widget)

    def create_cad_widget(self):
        self.advanced_digitizing_dock_widget = QgsAdvancedDigitizingDockWidget(self.map_canvas, self)

        cad_dock_widget = QDockWidget("Công cụ vẽ đối tượng", self)
        cad_dock_widget.setObjectName("AdvancedDigitizingTools")
        cad_dock_widget.setWidget(self.advanced_digitizing_dock_widget)
        cad_dock_widget.setAllowedAreas(LEFT_RIGHT)

        self.addDockWidget(LEFT, cad_dock_widget)
        cad_dock_widget.hide()

        # Tạo action cho phép đóng mở widget này
        show_advanced_digitizing_act = cad_dock_widget.toggleViewAction()
        show_advanced_digitizing_act.setText("Công cụ vẽ đối tượng")
        self.menu_bar_.add_view_action(show_advanced_digitizing_act)

    def create_canvas_tools(self):
        canvas, mb, bar = self.map_canvas, self.menu_bar_, self.message_bar
        self.tool_zoom_in = QgsMapToolZoom(canvas, False)
        self.tool_zoom_in.setAction(mb.zoom_in_act)
        self.tool_zoom_out = QgsMapToolZoom(canvas, True)
        self.tool_zoom_out.setAction(mb.zoom_out_act)
        self.tool_pan_map = QgsMapToolPan(canvas)
        self.tool_pan_map.setAction(mb.pan_map_act)
        self.tool_add_point_feature = maptools.create_add_feature_tool(canvas, "Point", bar)
        self.tool_add_line_feature = maptools.create_add_feature_tool(canvas, "Line", bar)
        self.tool_add_polygon_feature = maptools.create_add_feature_tool(canvas, "Polygon", bar)
        self.tool_identify_feature = QgsMapToolIdentifyFeature(canvas)
        # Set cursor to default pointer instead of cross cursor
        self.tool_identify_feature.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.tool_identify_feature.setAction(mb.cursor_click_act)
        self.tool_measure_dist = maptools.create_measure_tool(canvas, False, bar)
        self.tool_measure_area = maptools.create_measure_tool(canvas, True, bar)
        self.tool_add_text_annotation = maptools.create_text_annotation_tool(canvas, bar)
        self.tool_tag_counting = maptools.create_tag_annotation_tool(canvas, bar)

    # -------------------------------------------------------------- toolbars
    def create_view_tool_bar(self):
        view_tool_bar = QToolBar("Điều khiển nhìn", self)
        view_tool_bar.setObjectName("ViewToolBar")
        self.addToolBar(view_tool_bar)

        self.transparent_sdr = QSlider(Qt.Orientation.Horizontal, view_tool_bar)
        self.transparent_sdr.setToolTip("Điều chỉnh độ trong suốt")
        self.transparent_sdr.setSizePolicy(Fixed, Fixed)
        self.transparent_sdr.setRange(0, 100)
        self.transparent_sdr.setValue(100)

        mb = self.menu_bar_
        view_tool_bar.addAction(mb.cursor_click_act)
        view_tool_bar.addAction(mb.pan_map_act)
        view_tool_bar.addAction(mb.zoom_in_act)
        view_tool_bar.addAction(mb.zoom_out_act)
        view_tool_bar.addAction(mb.fit_view_act)
        view_tool_bar.addWidget(self.transparent_sdr)

        transparent_ledr = _value_edit("100%", "Độ trong suốt", QSize(48, 18), view_tool_bar)
        view_tool_bar.addWidget(transparent_ledr)

        def on_transparency(value: int):
            transparent_ledr.setText(f"{value}%")
            layer = self.active_layer()
            if isinstance(layer, QgsVectorLayer):
                layer.setOpacity(value * 0.01)
                layer.triggerRepaint()
            elif isinstance(layer, QgsRasterLayer):
                layer.renderer().setOpacity(value * 0.01)
                layer.triggerRepaint()

        self.transparent_sdr.valueChanged.connect(on_transparency)

    def create_data_tool_bar(self):
        data_tool_bar = QToolBar("Dữ liệu", self)
        data_tool_bar.setObjectName("DataToolBar")
        self.addToolBar(data_tool_bar)
        data_tool_bar.addAction(self.menu_bar_.add_vector_lyr_act)
        data_tool_bar.addAction(self.menu_bar_.add_raster_lyr_act)

    def create_vector_tool_bar(self):
        tb = QToolBar("Vector", self)
        tb.setObjectName("VectorToolBar")
        self.addToolBar(tb)
        vector_menu = self.menu_bar_.vector_menu

        start_editing_act = QAction(get_icon("StartEditing.svg"), "Thêm, sửa, xóa", tb)
        tb.addAction(start_editing_act)
        vector_menu.addSeparator()
        vector_menu.addAction(start_editing_act)

        save_editing_act = QAction(get_icon("SaveEditing.svg"), "Lưu thay đổi", tb)
        tb.addAction(save_editing_act)
        vector_menu.addAction(save_editing_act)

        for icon, text, tool, geom in (
            ("AddPoint.svg", "Thêm đối tượng điểm", self.tool_add_point_feature, Qgis.GeometryType.Point),
            ("AddLine.svg", "Thêm đối tượng đường", self.tool_add_line_feature, Qgis.GeometryType.Line),
            ("AddPolygon.svg", "Thêm đối tượng vùng", self.tool_add_polygon_feature, Qgis.GeometryType.Polygon),
        ):
            act = QAction(get_icon(icon), text, tb)
            act.setCheckable(True)
            tb.addAction(act)
            vector_menu.addAction(act)
            tool.setAction(act)
            act.triggered.connect(lambda _c=False, a=act, g=geom: self.add_feature(a, g))
            tool.deactivated.connect(lambda a=act: a.setChecked(False))

        start_editing_act.triggered.connect(self._start_editing)
        save_editing_act.triggered.connect(self._save_editing)

        identify_act = QAction(get_icon("Identify.svg"), "Chọn đối tượng", tb)
        tb.addAction(identify_act)
        vector_menu.addAction(identify_act)
        identify_act.triggered.connect(lambda: self.map_canvas.setMapTool(self.tool_identify_feature))

        remove_fea_act = QAction(get_icon("RemoveFeature.svg"), "Xóa đối tượng", tb)
        tb.addAction(remove_fea_act)
        vector_menu.addAction(remove_fea_act)
        remove_fea_act.triggered.connect(self._remove_selected_feature)

    def _push(self, title: str, text: str, level: Qgis.MessageLevel):
        self.message_bar.pushMessage(title, text, level, message_timeout())

    def _start_editing(self):
        title = "Mở chỉnh sửa"
        if self.vector_layer_editing() is not None:
            self._push(
                title, "Tồn tại một vector layer đang sửa. Đóng chỉnh sửa trước khi tiếp tục", Qgis.MessageLevel.Warning
            )
            return
        vlayer = self.active_layer()
        if not isinstance(vlayer, QgsVectorLayer):
            self._push(title, "Công cụ chỉ hoạt động trên vector layer", Qgis.MessageLevel.Warning)
            return
        if not vlayer.startEditing():
            self._push(title, "Thất bại", Qgis.MessageLevel.Critical)

    def _save_editing(self):
        title = "Lưu thay đổi"
        vlayer = self.vector_layer_editing()
        if vlayer is None:
            self._push(title, "Không có vector layer nào đang chỉnh sửa", Qgis.MessageLevel.Warning)
            return

        result = QMessageBox.question(
            self, title, "Bạn có muốn lưu lại các thay đổi không?", Btn.Yes | Btn.No | Btn.Cancel
        )
        if result == Btn.Yes:
            if not vlayer.isModified():
                self._push(title, "Không có thay đổi nào để lưu", Qgis.MessageLevel.Info)
            elif vlayer.commitChanges():
                self._push(title, "Thành công", Qgis.MessageLevel.Info)
            else:
                self._push(title, "Thất bại", Qgis.MessageLevel.Critical)
        elif result == Btn.No:
            vlayer.rollBack()

    def _remove_selected_feature(self):
        layer = self.feature_selection_layer
        if layer is not None and layer.isEditable() and self.feature_selection_id >= 0:
            layer.deleteFeature(self.feature_selection_id)
            self.rubber_band.reset(Qgis.GeometryType.Polygon)
            layer.triggerRepaint()

    def create_raster_tool_bar(self):
        tb = QToolBar("Raster", self)
        tb.setObjectName("RasterToolBar")
        self.addToolBar(tb)
        size = QSize(40, 18)

        self.brightness_sdr = QSlider(Qt.Orientation.Horizontal, tb)
        self.brightness_sdr.setToolTip("Điều chỉnh độ sáng")
        self.brightness_sdr.setStyleSheet(_slider_style("#FBD362"))
        self.brightness_sdr.setSizePolicy(Fixed, Fixed)
        self.brightness_sdr.setRange(-255, 255)
        self.brightness_sdr.setValue(0)
        self.brightness_ledr = _value_edit("0", "Độ sáng", size, tb)

        self.contrast_sdr = QSlider(Qt.Orientation.Horizontal, tb)
        self.contrast_sdr.setToolTip("Điều chỉnh độ tương phản")
        # The C++ code sets #54BCE9 then overrides it with #86BF65; keep the effective color.
        self.contrast_sdr.setStyleSheet(_slider_style("#86BF65"))
        self.contrast_sdr.setSizePolicy(Fixed, Fixed)
        self.contrast_sdr.setRange(-255, 255)
        self.contrast_sdr.setValue(0)
        self.contrast_ledr = _value_edit("0", "Độ tương phản", size, tb)

        self.transparent_sdr.setStyleSheet(_slider_style("#54BCE9"))

        def on_brightness(value: int):
            self.brightness_ledr.setText(str(value))
            layer = self.active_layer()
            if isinstance(layer, QgsRasterLayer):
                layer.brightnessFilter().setBrightness(value)
                layer.triggerRepaint()

        def on_contrast(value: int):
            self.contrast_ledr.setText(str(value))
            layer = self.active_layer()
            if isinstance(layer, QgsRasterLayer):
                layer.brightnessFilter().setContrast(value)
                layer.triggerRepaint()

        self.brightness_sdr.valueChanged.connect(on_brightness)
        self.contrast_sdr.valueChanged.connect(on_contrast)

        tb.addWidget(self.brightness_sdr)
        tb.addWidget(self.brightness_ledr)
        tb.addWidget(self.contrast_sdr)
        tb.addWidget(self.contrast_ledr)

        mb = self.menu_bar_
        for act in (
            mb.local_cumulative_cut_stretch_act,
            mb.full_cumulative_cut_stretch_act,
            mb.local_std_dev_stretch_act,
            mb.full_std_dev_stretch_act,
            mb.local_histogram_stretch_act,
            mb.full_histogram_stretch_act,
        ):
            tb.addAction(act)

    def set_brightness_contrast_enabled(self, enabled: bool):
        for w in (self.brightness_sdr, self.brightness_ledr, self.contrast_sdr, self.contrast_ledr):
            w.setEnabled(enabled)

    def create_module_tool_bar(self):
        mb, mc = self.menu_bar_, self.main_controller
        file_menu, tool_menu = mb.file_menu, mb.tool_menu

        def file_action(icon: str, text: str, slot) -> QAction:
            act = QAction(get_icon(icon), text, file_menu)
            file_menu.addAction(act)
            self.mainToolBar.addAction(act)
            act.triggered.connect(lambda _c=False: slot())
            return act

        file_action("vGeoCatalog.svg", CATALOG_NAME, lambda: _launch_module("vgeoint.catalog"))
        file_action("vGeoEngine.svg", ENGINE_NAME, lambda: _launch_module("vgeoint.engine"))
        file_menu.addSeparator()
        self.mainToolBar.addSeparator()

        file_action("Settings.svg", "Cài đặt chung", mc.settings_dialog)
        metadata_act = self.get_plugin_action_by_code(T_METADATA_VIEWER)
        if metadata_act is not None:
            file_menu.addAction(metadata_act)
            self.mainToolBar.addAction(metadata_act)
        file_action("SaveAs.svg", "Xuất ra với tên...", mc.save_as)
        file_action("ExportPdf.svg", "Xuất Pdf", mc.save_map_as_pdf)

        file_menu.addSeparator()
        exit_act = QAction(get_icon("Exit.svg"), "Thoát", file_menu)
        file_menu.addAction(exit_act)
        exit_act.triggered.connect(self.close)

        # Vector BPlugin
        vector_bplugin_tool_bar = QToolBar("Vector bổ sung", self)
        vector_bplugin_tool_bar.setObjectName("VectorBPluginToolBar")
        self.addToolBar(vector_bplugin_tool_bar)
        for code in (V_SHAPE_FILE_CREATING, V_VECTOR_RENDER, V_VECTOR_LABELING):
            act = self.get_plugin_action_by_code(code)
            if act is not None:
                vector_bplugin_tool_bar.addAction(act)

        # Raster BPlugin
        raster_bplugin_tool_bar = QToolBar("Raster bổ sung", self)
        raster_bplugin_tool_bar.setObjectName("RasterBPluginToolBar")
        self.addToolBar(raster_bplugin_tool_bar)
        for icon, text, slot in (
            ("BrightnessContrast.svg", "Độ sáng/ Độ tương phản", mc.brightness_contrast),
            ("ColorComposite.svg", "Tổ hợp màu", mc.color_composite),
            ("ColorSpace.svg", "Chuyển đổi không gian màu", mc.color_space_convertion),
            ("ImageFilter.svg", "Lọc ảnh", mc.image_filter),
            ("SplitImage.svg", "Tách kênh ảnh", mc.image_split),
            ("ConcatenateImages.svg", "Gộp kênh ảnh", mc.image_concatenating),
            ("BandMath.svg", "Tính toán trên ảnh", mc.band_math),
            ("ChangeDetection.svg", "Phát hiện thay đổi", mc.change_detection),
            # Temporary use change detection icon
            ("ChangeDetection.svg", "Phát hiện biến động", mc.motion_detection),
        ):
            act = QAction(get_icon(icon), text, tool_menu)
            act.triggered.connect(lambda _c=False, s=slot: s())
            raster_bplugin_tool_bar.addAction(act)

        # Annotation BPlugin
        anno_tb = QToolBar("Ghi chú", self)
        anno_tb.setObjectName("AnnotationBPluginToolBar")
        self.addToolBar(anno_tb)

        def anno_action(icon: str, text: str, slot, tool=None) -> QAction:
            act = QAction(get_icon(icon), text, anno_tb)
            tool_menu.addAction(act)
            anno_tb.addAction(act)
            if tool is not None:
                tool.setAction(act)
            act.triggered.connect(lambda _c=False: slot())
            return act

        anno_action(
            "TextAnnotation/Insert.svg",
            "Chèn ghi chú văn bản",
            lambda: self.map_canvas.setMapTool(self.tool_add_text_annotation),
            self.tool_add_text_annotation,
        )
        anno_action(
            "TextAnnotation/TagCounting.svg",
            "Chèn Tag đếm đối tượng",
            lambda: self.map_canvas.setMapTool(self.tool_tag_counting),
            self.tool_tag_counting,
        )
        anno_action("TextAnnotation/TagCountingSetting.svg", "Cấu hình Tag đếm đối tượng", mc.tag_annotation_setting)
        anno_action("TextAnnotation/Remove.svg", "Xóa ghi chú", self._remove_selected_annotations)
        anno_action("TextAnnotation/Manager.svg", "Quản lý ghi chú", mc.annotation_manager)
        act = self.get_plugin_action_by_code(T_ANNOTATION_MANAGER)
        if act is not None:
            anno_tb.addAction(act)

        # Measure BPlugin
        measure_tb = QToolBar("Đo đạc", self)
        measure_tb.setObjectName("MeasureBPluginToolBar")
        self.addToolBar(measure_tb)

        measure_distance_act = QAction(get_icon("MeasureDistance.svg"), "Đo độ dài", measure_tb)
        measure_distance_act.triggered.connect(lambda: self.map_canvas.setMapTool(self.tool_measure_dist))
        measure_area_act = QAction(get_icon("MeasureArea.svg"), "Đo diện tích", measure_tb)
        measure_area_act.triggered.connect(lambda: self.map_canvas.setMapTool(self.tool_measure_area))
        tool_menu.addSeparator()
        tool_menu.addAction(measure_distance_act)
        tool_menu.addAction(measure_area_act)
        measure_tb.addAction(measure_distance_act)
        measure_tb.addAction(measure_area_act)
        self.tool_measure_dist.setAction(measure_distance_act)
        self.tool_measure_area.setAction(measure_area_act)

        # Help Toolbar
        help_tb = QToolBar("Trợ giúp", self)
        help_tb.setObjectName("HelpToolBar")
        self.addToolBar(help_tb)
        help_tb.addAction(mb.information_act)
        help_tb.addAction(mb.contact_act)
        help_tb.addAction(mb.help_act)

    def _remove_selected_annotations(self):
        for item in self.map_canvas.scene().selectedItems():
            if isinstance(item, QgsMapCanvasAnnotationItem):
                self.project.annotationManager().removeAnnotation(item.annotation())

    # ----------------------------------------------------------- connections
    def create_connections(self):
        mb, mc = self.menu_bar_, self.main_controller

        # Kết nối này để cập nhật tỉ lệ và hệ tọa độ khi có sự thay đổi
        self.project.crsChanged.connect(mc.update_crs)

        connections = {
            # Project management
            mb.new_project_act: mc.new_project,
            mb.open_project_act: mc.open_project,
            mb.save_project_act: mc.save_project,
            mb.save_project_as_act: mc.save_project_as,
            mb.open_vector_file_act: mc.add_vector,
            mb.open_raster_file_act: mc.add_raster,
            # View menu
            mb.fit_view_act: self.map_canvas.zoomToFullExtent,
            mb.zoom_in_act: lambda: self.map_canvas.setMapTool(self.tool_zoom_in),
            mb.zoom_out_act: lambda: self.map_canvas.setMapTool(self.tool_zoom_out),
            mb.pan_map_act: lambda: self.map_canvas.setMapTool(self.tool_pan_map),
            mb.cursor_click_act: lambda: self.map_canvas.setMapTool(self.tool_identify_feature),
            # Layer menu
            mb.add_vector_lyr_act: mc.add_vector,
            mb.add_raster_lyr_act: mc.add_raster,
            mb.remove_lyr_act: mc.remove_layer,
            # Raster menu
            mb.local_cumulative_cut_stretch_act: mc.local_cumulative_cut_stretch,
            mb.full_cumulative_cut_stretch_act: mc.full_cumulative_cut_stretch,
            mb.local_std_dev_stretch_act: mc.local_std_dev_stretch,
            mb.full_std_dev_stretch_act: mc.full_std_dev_stretch,
            mb.local_histogram_stretch_act: mc.local_histogram_stretch,
            mb.full_histogram_stretch_act: mc.full_histogram_stretch,
            mb.color_composite_act: mc.color_composite,
            mb.band_math_act: mc.band_math,
            mb.brightness_contrast_act: mc.brightness_contrast,
            # Tool menu
            mb.image_filter_act: mc.image_filter,
            mb.image_split_act: mc.image_split,
            mb.color_space_convertion_act: mc.color_space_convertion,
            mb.change_detection_act: mc.change_detection,
            mb.motion_detection_act: mc.motion_detection,
            mb.object_tracking_act: mc.object_tracking,
            mb.image_concatenating_act: mc.image_concatenating,
            mb.view_metadata_act: mc.view_metadata,
            mb.ship_detection_act: mc.ship_detection,
            mb.ship_tracking_act: mc.ship_tracking,
            mb.vehicle_tracking_act: mc.vehicle_tracking,
            mb.building_segmentation_act: mc.building_segmentation,
            mb.tank_detection_act: mc.tank_detection,
            mb.image_blending_act: mc.image_blending,
            mb.auto_classification_act: mc.auto_classification,
            mb.google_earth_engine_act: mc.google_earth_engine,
            mb.annotation_manager_act: mc.annotation_manager,
            # Help menu
            mb.information_act: self._show_information,
            mb.contact_act: self._show_contact,
            mb.help_act: lambda: None,  # Chưa xây dựng
        }
        for action, slot in connections.items():
            # Drop the `checked` argument so slots with optional parameters are called with defaults.
            action.triggered.connect(lambda _checked=False, s=slot: s())

        # Vector menu: highlight the identified feature
        self.tool_identify_feature.featureIdentified[QgsFeature].connect(self._feature_identified)

        # Plugins
        for action, plugin in self.plugins.values():
            plugin.complete.connect(lambda p=plugin: self._plugin_complete(p))
            if action is not None:
                action.triggered.connect(lambda _c=False, p=plugin: self._show_plugin(p))

        # Kết nối này đảm bảo khi thêm anno Project nó sẽ xuất hiện trên MapCanvas
        self.project.annotationManager().annotationAdded.connect(self.annotation_created)

        # Kết nối sự thay đổi current layer trên LayerTreeView (Layer Panel)
        self.layer_tree_view.currentLayerChanged.connect(self._current_layer_changed)

    def _feature_identified(self, f: QgsFeature):
        if self.rubber_band is None:
            s = settings()
            self.rubber_band = QgsRubberBand(self.map_canvas, Qgis.GeometryType.Polygon)
            self.rubber_band.setWidth(int(s.value("RubberBand/Width", 6)))
            fill = QColor(
                int(s.value("RubberBand/FillRed", 0)),
                int(s.value("RubberBand/FillGreen", 255)),
                int(s.value("RubberBand/FillBlue", 255)),
                50,
            )
            stroke = QColor(
                int(s.value("RubberBand/StrokeRed", 0)),
                int(s.value("RubberBand/StrokeGreen", 255)),
                int(s.value("RubberBand/StrokeBlue", 255)),
                200,
            )
            self.rubber_band.setFillColor(fill)
            self.rubber_band.setStrokeColor(stroke)

        vl = self.active_layer()
        vl = vl if isinstance(vl, QgsVectorLayer) else None
        self.rubber_band.setToGeometry(f.geometry(), vl)
        self.feature_selection_layer = vl
        self.feature_selection_id = f.id()

    def _plugin_complete(self, plugin):
        if not plugin.auto_add_output_files():
            return
        add = self.main_controller.add_raster if plugin.output_data_type() == RASTER else self.main_controller.add_vector
        for output in plugin.output_files():
            add(output)

    def _show_plugin(self, plugin):
        plugin.set_map_canvas(self.map_canvas)
        plugin.set_layer_tree_view(self.layer_tree_view)
        plugin.show()

    def _show_information(self):
        QMessageBox.information(
            self,
            "Thông tin phần mềm",
            f"Phần mềm vGeoInt phiên bản {VERSION} (2025)\nBản quyền thuộc về Cục Tác chiến/Bộ Tổng Tham mưu",
        )

    def _show_contact(self):
        QMessageBox.information(
            self,
            "Liên hệ",
            "Nhóm tác giả:\n"
            "Phạm Xuân Hoàn, 0989.875.111, hoanpx@gmail.com\n"
            "Phạm Hữu Hoàng, 0941.688.367, phamhuuhoang99@gmail.com\n",
        )

    def _current_layer_changed(self, layer: QgsMapLayer):
        if isinstance(layer, QgsVectorLayer):
            self.tool_identify_feature.setLayer(layer)
            self.set_brightness_contrast_enabled(False)
            self.transparent_sdr.setValue(int(layer.opacity() * 100))
        elif isinstance(layer, QgsRasterLayer):
            self.set_brightness_contrast_enabled(True)
            f = layer.brightnessFilter()
            self.brightness_sdr.setValue(f.brightness())
            self.contrast_sdr.setValue(f.contrast())
            self.transparent_sdr.setValue(int(layer.renderer().opacity() * 100))

    def annotation_created(self, anno):
        # Lệnh này tự động chèn annotation vào map canvas
        QgsMapCanvasAnnotationItem(anno, self.map_canvas)

    # ----------------------------------------------------------- vector edit
    def vector_layer_editing(self) -> QgsVectorLayer | None:
        for layer in self.map_canvas.layers():
            if isinstance(layer, QgsVectorLayer) and layer.isEditable():
                return layer
        return None

    def add_feature(self, act: QAction, geometry_type: Qgis.GeometryType):
        vn_name, name, tool = {
            Qgis.GeometryType.Point: ("Điểm", "Point", self.tool_add_point_feature),
            Qgis.GeometryType.Line: ("Đường", "LineString", self.tool_add_line_feature),
            Qgis.GeometryType.Polygon: ("Vùng", "Polygon", self.tool_add_polygon_feature),
        }[geometry_type]

        vlayer = self.vector_layer_editing()
        if vlayer is not None and vlayer.geometryType() == geometry_type:
            self.map_canvas.setCurrentLayer(vlayer)
            self.map_canvas.setMapTool(tool)
            act.setChecked(True)
            return
        if vlayer is not None:
            self._push(
                f"Thêm {vn_name}",
                "Khác kiểu so với vector layer đang sửa. Hãy lưu layer hiện tại và thử lại.",
                Qgis.MessageLevel.Warning,
            )
            act.setChecked(False)
            return

        question = QMessageBox(
            QMessageBox.Icon.Question,
            f"Thêm {vn_name}",
            f"Không có vector layer dạng {vn_name} nào đang mở số hóa.\n"
            "Bạn có muốn tự động tạo một vector layer mới không?",
            Btn.Yes | Btn.No,
            self,
        )
        question.button(Btn.Yes).setText("Có")
        question.button(Btn.No).setText("Không")
        if question.exec() != Btn.Yes:
            act.setChecked(False)
            return

        url = f"{name}?crs={self.project.crs().authid()}&index=yes"
        new_layer = QgsVectorLayer(url, vn_name, "memory")
        if new_layer.isValid():
            self.project.addMapLayer(new_layer)
            new_layer.startEditing()
            self.map_canvas.setCurrentLayer(new_layer)
            self.map_canvas.setMapTool(tool)
            act.setChecked(True)

    def get_raster_layer_argv(self) -> str:
        return "|".join(f"{lyr.name()}|{lyr.source()}" for lyr in self.raster_layers())

    # -------------------------------------------------------------- settings
    def load_settings(self):
        s = settings()
        for key, restore in (
            ("Geometry", self.restoreGeometry),
            ("WindowState", self.restoreState),
            ("LayerPanelWidget/geometry", self.layer_panel_widget.restoreGeometry),
            ("OverviewWidget/geometry", self.overview_widget.restoreGeometry),
        ):
            value = s.value(key)
            if value is not None:
                restore(value)

    def save_settings(self):
        s = settings()
        s.setValue("Geometry", self.saveGeometry())
        s.setValue("WindowState", self.saveState())
        s.setValue("LayerPanelWidget/geometry", self.layer_panel_widget.saveGeometry())
        s.setValue("OverviewWidget/geometry", self.overview_widget.saveGeometry())
