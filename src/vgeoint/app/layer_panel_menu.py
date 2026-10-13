"""Port of LayerPanelMenu.cpp — right-click menu of the layer panel."""

from qgis.core import Qgis, QgsCoordinateTransform, QgsCsException, QgsLayerTree, QgsProject
from qgis.gui import QgsLayerTreeView, QgsLayerTreeViewMenuProvider, QgsMapCanvas
from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import QMenu

from vgeoint.common.utils import get_icon

R_BRIGHTNESS_CONTRAST = "R_BrightnessContrastPlugin"
R_COLOR_COMPOSITE = "R_ColorCompositePlugin"
T_COLOR_SPACE_CONVERTION = "T_ColorSpaceConvertionPlugin"
T_IMAGE_SPLIT = "T_ImageSplitPlugin"
T_IMAGE_CONCATENATING = "T_ImageConcatenatingPlugin"
T_METADATA_VIEWER = "T_MetadataViewer"
V_VECTOR_RENDER = "V_VectorRenderPlugin"
V_VECTOR_LABELING = "V_VectorLabelingPlugin"


class LayerPanelMenu(QgsLayerTreeViewMenuProvider):
    def __init__(self, view: QgsLayerTreeView, map_canvas: QgsMapCanvas, main_controller):
        super().__init__()
        self.view = view
        self.map_canvas = map_canvas
        self.main_controller = main_controller

    def createContextMenu(self) -> QMenu:
        menu = QMenu()
        actions = self.view.defaultActions()
        idx = self.view.currentIndex()

        if not idx.isValid():
            add_group = actions.actionAddGroup(menu)
            add_group.setText("Thêm nhóm mới")
            menu.addAction(add_group)
            menu.addAction(get_icon("mActionExpandTree.svg"), "Mở rộng tất cả", self.view.expandAll)
            menu.addAction(get_icon("mActionCollapseTree.svg"), "Thu gọn tất cả", self.view.collapseAll)
            menu.addSeparator()
            return menu

        node = self.view.currentNode()
        if node is None:
            return menu

        if QgsLayerTree.isGroup(node):
            zoom_to_group = actions.actionZoomToGroup(self.map_canvas, menu)
            zoom_to_group.setText("Đi tới nhóm này")
            menu.addAction(zoom_to_group)

            add_group = actions.actionAddGroup(menu)
            add_group.setText("Thêm nhóm con")
            menu.addAction(add_group)
        elif QgsLayerTree.isLayer(node):
            # PyQGIS already returns the node as QgsLayerTreeLayer (no QgsLayerTree.toLayer binding).
            layer = node.layer()

            zoom_to_layer = QAction("Đi tới layer này", menu)
            zoom_to_layer.triggered.connect(lambda: self._zoom_to_layer(layer))
            menu.addAction(zoom_to_layer)

            show_in_overview = actions.actionShowInOverview(menu)
            show_in_overview.setText("Xem tổng quan")
            menu.addAction(show_in_overview)

            if layer is not None:
                if layer.type() == Qgis.LayerType.Raster:
                    self.add_menu_by_module_code(menu, R_BRIGHTNESS_CONTRAST)
                    band_count = layer.bandCount()
                    if band_count >= 3:
                        self.add_menu_by_module_code(menu, R_COLOR_COMPOSITE)
                        self.add_menu_by_module_code(menu, T_COLOR_SPACE_CONVERTION)
                    if band_count >= 2:
                        self.add_menu_by_module_code(menu, T_IMAGE_SPLIT)
                    self.add_menu_by_module_code(menu, T_IMAGE_CONCATENATING)
                elif layer.type() == Qgis.LayerType.Vector:
                    label_action = QAction(get_icon("Labeling.svg"), "Hiển thị nhãn...", menu)
                    label_action.triggered.connect(lambda: self.main_controller.vector_labeling(layer))
                    menu.addAction(label_action)
                    self.add_menu_by_module_code(menu, V_VECTOR_RENDER)
                    self.add_menu_by_module_code(menu, V_VECTOR_LABELING)

        rename_action = actions.actionRenameGroupOrLayer(menu)
        rename_action.setText("Đổi tên")
        rename_action.setIcon(get_icon("Rename.svg"))
        menu.addAction(rename_action)

        save_as_action = QAction(get_icon("SaveAs.svg"), "Xuất ra với tên...", menu)
        save_as_action.triggered.connect(self.main_controller.save_as)
        menu.addAction(save_as_action)

        remove_action = QAction(get_icon("mActionRemoveLayer.svg"), "Gỡ bỏ", menu)
        remove_action.triggered.connect(self.main_controller.remove_layer)
        menu.addAction(remove_action)

        if len(self.view.selectedNodes(True)) > 1:
            group_selected = actions.actionGroupSelected(menu)
            group_selected.setText("Gom nhóm")
            menu.addAction(group_selected)

        self.add_menu_by_module_code(menu, T_METADATA_VIEWER)
        return menu

    def _zoom_to_layer(self, layer):
        if layer is None or self.map_canvas is None:
            return
        extent = layer.extent()
        if extent.isEmpty():
            return
        dest_crs = self.map_canvas.mapSettings().destinationCrs()
        if layer.crs() != dest_crs:
            transform = QgsCoordinateTransform(layer.crs(), dest_crs, QgsProject.instance())
            try:
                extent = transform.transformBoundingBox(extent)
            except QgsCsException:
                pass  # Use original extent if transformation fails
        self.map_canvas.setExtent(extent)
        self.map_canvas.refresh()

    def add_menu_by_module_code(self, menu: QMenu, code: str):
        # Only the metadata entry is active in the C++ app; plugin entries are commented out there.
        if code == T_METADATA_VIEWER:
            metadata_action = QAction(get_icon("Metadata.svg"), "Xem siêu dữ liệu", menu)
            metadata_action.triggered.connect(self.main_controller.view_metadata)
            menu.addAction(metadata_action)
