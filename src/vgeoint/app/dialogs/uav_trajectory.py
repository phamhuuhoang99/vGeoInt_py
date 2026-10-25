"""Phát hiện quỹ đạo trên ảnh UAV (Qt port of D:/detectandraw/detect_and_draw_gui.py, a Tkinter app).

Same options, log, result image viewer (wheel zoom, drag, double-click to fit) and track table as the
Tkinter GUI; the detection itself is the original detect_and_draw.py, run in the ai environment. New: the
tracks / points can be added to the map (GeoJSON in the CRS of the images) when the run finishes.
"""

import colorsys
import json
import os
import re

from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateTransform,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerLineSymbolLayer,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRasterLayer,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QEvent, QObject, QRectF, Qt, QUrl
from qgis.PyQt.QtGui import QAction, QColor, QDesktopServices, QImageReader, QPainter, QPixmap, QTextCursor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vgeoint.ai.runner import ScriptRunner
from vgeoint.common.paths import MODELS_DIR
from vgeoint.common.utils import get_icon, settings

SCRIPT = "detect_and_draw.py"
SETTINGS_KEY = "UavTrajectory/Settings"
IMAGE_EXTS = (".tif", ".tiff", ".jpg", ".jpeg", ".png")
# Results saved next to the images, skipped by detect_and_draw.py (scan_input_directory)
DERIVED_MARKS = ("_det", "_mask", "_preview", "_output")


def default_model() -> str:
    for name in ("yolo26x.pt", "yolov8x.pt"):
        if (MODELS_DIR / name).exists():
            return str(MODELS_DIR / name)
    return str(MODELS_DIR / "yolo26x.pt")


DEFAULTS = {
    "input_dir": "",
    "output_dir": "",
    "model": "",
    "conf": 0.25,
    "max_speed": 90.0,
    "max_gap": 2,
    "min_speed": 5.0,
    "min_track_len": 2,
    "tile_size": 640,
    "overlap": 0.2,
    "device": "auto",
    "no_sahi": False,
    "no_tta": False,
    "low_conf": 0.08,
    "no_redetect": False,
    "min_track_score": 0.45,
    "min_track_score_2w": 0.3,
    "max_link_dist": 60.0,
    "static_dist": 3.0,
    "no_align": False,
    "keep_static": False,
    "add_to_map": True,
    "classes": ["car", "truck", "bus", "motorcycle", "bicycle"],
}

# (tên lớp trong model, nhãn hiển thị). Vehicles only: "person" of the Tkinter GUI was removed.
CLASS_OPTIONS = [
    ("car", "Ô tô (car)"),
    ("truck", "Xe tải (truck)"),
    ("bus", "Xe buýt (bus)"),
    ("motorcycle", "Xe máy (motorbike)"),
    ("bicycle", "Xe đạp (bicycle)"),
]

# (nhãn, khóa, min, max, bước, ghi chú, số chữ số thập phân; 0 = số nguyên)
PARAMETERS = [
    ("Ngưỡng tin cậy", "conf", 0.05, 0.95, 0.05, "Giảm nếu bị sót đối tượng", 2),
    ("Vận tốc tối đa (km/h)", "max_speed", 1, 300, 5, "Giới hạn khoảng cách nối giữa 2 ảnh", 1),
    ("Khoảng cách nối tối đa (m)", "max_link_dist", 0, 500, 5, "Giới hạn khi 2 ảnh cách nhau lâu; 0 = tắt", 1),
    ("Số ảnh được mất dấu", "max_gap", 0, 10, 1, "Đối tượng biến mất tạm thời tối đa", 0),
    ("Ngưỡng tin cậy thấp", "low_conf", 0.01, 0.5, 0.01, "Chỉ dùng để nối tiếp xe đã có", 2),
    ("Độ tin cậy tối thiểu / track (ô tô)", "min_track_score", 0, 1, 0.05,
     "Ô tô/xe tải/xe buýt: bỏ track không khung nào đạt mức này", 2),
    ("Độ tin cậy tối thiểu / track (xe 2 bánh)", "min_track_score_2w", 0, 1, 0.05,
     "Xe máy/xe đạp: model cho điểm thấp hơn", 2),
    ("Ngưỡng xe đứng yên (m)", "static_dist", 0, 20, 0.5, "Độ dời thật dưới mức này = đứng yên; 0 = tắt", 1),
    ("Vận tốc tối thiểu (km/h)", "min_speed", 0, 200, 1, "Bỏ xe đứng yên; 0 = giữ tất cả", 1),
    ("Số điểm tối thiểu / quỹ đạo", "min_track_len", 2, 20, 1, "Quỹ đạo ngắn hơn không vẽ", 0),
    ("Kích thước ô cắt (px)", "tile_size", 256, 2048, 64, "SAHI: cắt ảnh lớn thành ô", 0),
    ("Độ chồng lấn ô", "overlap", 0.0, 0.5, 0.05, "", 2),
]

# (khóa, nhãn) of the switches passed as --no-sahi, --no-tta, ...
SWITCHES = [
    ("no_sahi", "Không cắt ô (ảnh nhỏ, chạy nhanh hơn)"),
    ("no_tta", "Không xoay ảnh 4 hướng (nhanh x4, dễ sót xe)"),
    ("no_redetect", "Không detect lại vùng xe bị sót"),
    ("no_align", "Không căn chỉnh ảnh giữa các thời điểm"),
    ("keep_static", "Giữ cả xe đứng yên (đánh dấu trạng thái)"),
]

TRACK_COLUMNS = [
    ("track_id", "ID"), ("class", "Lớp"), ("num_pts", "Số điểm"), ("start_time", "Bắt đầu"),
    ("end_time", "Kết thúc"), ("tot_dist_m", "Quãng đường (m)"), ("avg_spd_k", "V TB (km/h)"),
    ("max_spd_k", "V max (km/h)"), ("heading", "Hướng"), ("status", "Trạng thái"), ("check", "Kiểm tra"),
]


def track_color(track_id: int) -> QColor:
    """Colour of a track, as detect_and_draw.track_color() draws it on the result images (golden-ratio hues)."""
    r, g, b = colorsys.hsv_to_rgb((track_id * 0.61803398875) % 1.0, 0.85, 1.0)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


def _track_symbol(geometry_type, color: QColor):
    name = color.name()
    if geometry_type == Qgis.GeometryType.Line:
        symbol = QgsLineSymbol.createSimple({"color": name, "width": "0.9", "capstyle": "round"})
        arrow = QgsMarkerLineSymbolLayer()  # arrow head at the last point: direction of travel
        arrow.setPlacements(Qgis.MarkerLinePlacement.LastVertex)
        arrow.setSubSymbol(QgsMarkerSymbol.createSimple(
            {"name": "arrowhead", "color": name, "outline_color": name, "size": "3.5", "outline_width": "0.6"}))
        symbol.appendSymbolLayer(arrow)
        return symbol
    if geometry_type == Qgis.GeometryType.Polygon:  # outline only, the image stays visible
        return QgsFillSymbol.createSimple(
            {"color": "0,0,0,0", "outline_color": name, "outline_width": "0.5", "style": "no"})
    return QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": name, "outline_color": "#000000", "size": "2.6", "outline_width": "0.3"})


def color_by_track(layer: QgsVectorLayer, field: str = "track_id"):
    """One colour per track (legend "#<id>", each one can be hidden); a single red style without `field`."""
    if field in layer.fields().names():
        categories = []
        for value in sorted(v for v in layer.uniqueValues(layer.fields().indexOf(field)) if v is not None):
            try:
                color = track_color(int(value))
            except (TypeError, ValueError):
                color = QColor("#e31a1c")
            categories.append(QgsRendererCategory(value, _track_symbol(layer.geometryType(), color), f"#{value}"))
        layer.setRenderer(QgsCategorizedSymbolRenderer(field, categories))
    else:
        layer.setRenderer(QgsSingleSymbolRenderer(_track_symbol(layer.geometryType(), QColor("#e31a1c"))))


def style_result_layer(layer: QgsVectorLayer):
    """One colour per vehicle (same as on the result images): tracks with an arrow at the end, points."""
    color_by_track(layer, "track_id")
    if layer.geometryType() == Qgis.GeometryType.Line:
        label_speed(layer)
    else:
        label_time(layer)


def _first_field(layer: QgsVectorLayer, *names: str) -> str | None:
    """The first of `names` the layer has (shapefile field names differ from the GeoJSON ones)."""
    fields = layer.fields().names()
    return next((name for name in names if name in fields), None)


def _set_label(layer: QgsVectorLayer, expression: str, placement):
    settings = QgsPalLayerSettings()
    settings.fieldName = expression
    settings.isExpression = True
    settings.placement = placement
    settings.dist = 1.5
    text = QgsTextFormat()
    text.setSize(9)
    text.setColor(QColor("#000000"))
    font = text.font()
    font.setBold(True)
    text.setFont(font)
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(1.0)
    buffer.setColor(QColor("#ffffff"))
    text.setBuffer(buffer)
    settings.setFormat(text)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def _track_prefix(layer: QgsVectorLayer) -> str:
    return "'#' || \"track_id\" || ' ' || " if _first_field(layer, "track_id") else ""


def label_time(layer: QgsVectorLayer):
    """Label each vehicle point "#<track> <capture time>" ("#1 16:29:47.528"; the date is left out)."""
    time_field = _first_field(layer, "thoi_gian", "time")
    if time_field:
        _set_label(layer, f"{_track_prefix(layer)}left(\"{time_field}\", 12)", Qgis.LabelPlacement.AroundPoint)


def label_speed(layer: QgsVectorLayer):
    """Label each track along its line with its average speed: "#1 · TB 53.1 km/h"."""
    speed_field = _first_field(layer, "v_tb_kmh", "avg_spd_k")
    if speed_field:
        prefix = "'#' || \"track_id\" || ' · ' || " if _first_field(layer, "track_id") else ""
        _set_label(layer, f"{prefix}'TB ' || format_number(\"{speed_field}\", 1) || ' km/h'",
                   Qgis.LabelPlacement.Line)


def load_settings() -> dict:
    s = dict(DEFAULTS, model=default_model())
    try:
        s.update(json.loads(str(settings().value(SETTINGS_KEY, "") or "{}")))
    except ValueError:
        pass
    offered = {key for key, _ in CLASS_OPTIONS}
    s["classes"] = [c for c in s["classes"] if c in offered]  # e.g. "person" saved by an older version
    return s


def count_images(folder: str) -> int:
    return sum(1 for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in IMAGE_EXTS)


class ImageView(QGraphicsView):
    """Wheel: zoom under the mouse, drag: move, double-click: fit (as in the Tkinter viewer)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self._item: QGraphicsPixmapItem | None = None
        self._fitted = True
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#1e1e1e"))
        self.message = ""

    def show_image(self, path: str):
        self.scene().clear()
        self._item = None
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            self.message = f"Không mở được ảnh: {reader.errorString()}"
            self.scene().addText(self.message).setDefaultTextColor(QColor("white"))
            return
        self.message = ""
        self._item = self.scene().addPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(QRectF(image.rect()))
        self.fit()

    def fit(self):
        if self._item is not None:
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
            self._fitted = True

    def zoom(self) -> float:
        return self.transform().m11()

    def wheelEvent(self, event):
        if self._item is None:
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        if 0.02 <= self.zoom() * factor <= 16:
            self.scale(factor, factor)
            self._fitted = False

    def mouseDoubleClickEvent(self, event):
        self.fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fitted:
            self.fit()


class ScrollInsteadOfWheel(QObject):
    """Event filter: a wheel turn over a spin box / combo box scrolls `scroll_area` instead of changing it."""

    def __init__(self, scroll_area: QScrollArea, parent=None):
        super().__init__(parent)
        self.scroll_area = scroll_area

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            bar = self.scroll_area.verticalScrollBar()
            steps = event.angleDelta().y() / 120
            bar.setValue(bar.value() - int(steps * bar.singleStep() * 3))
            return True
        return False


class UavTrajectoryDialog(QDialog):
    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.s = load_settings()
        self.process: ScriptRunner | None = None
        self.n_frames = 0
        self.steps_done = 0
        self.result_files: list[tuple[str, str]] = []
        self.output_files: list[str] = []
        self._stopped = False

        self.setWindowTitle(self.vn_name())
        self.setWindowIcon(self.get_icon())
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1400, 850)
        self._build()
        if self.s["output_dir"] and os.path.isdir(self.s["output_dir"]):
            self.load_results()

    # BPluginInterface
    def name(self) -> str:
        return "UavTrajectory"

    def vn_name(self) -> str:
        return "Phát hiện quỹ đạo trên ảnh UAV"

    def get_icon(self):
        return get_icon("tracking.svg")

    # ---------------------------------------------------------------- UI
    def _build(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(splitter)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(340)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self._data_group())
        left_layout.addWidget(self._classes_group())
        left_layout.addWidget(self._parameters_group())
        left_layout.addWidget(self._run_group())
        left_layout.addStretch()
        scroll.setWidget(left)
        splitter.addWidget(scroll)
        self.param_scroll = scroll
        # The wheel scrolls the panel; it no longer changes the number / choice under the mouse.
        self._wheel_guard = ScrollInsteadOfWheel(scroll, self)
        for box in left.findChildren(QAbstractSpinBox) + left.findChildren(QComboBox):
            box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            box.installEventFilter(self._wheel_guard)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._images_tab(), "Ảnh kết quả")
        self.tabs.addTab(self._tracks_tab(), "Bảng quỹ đạo")
        self.tabs.addTab(self._log_tab(), "Nhật ký")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 1040])

    def _path_row(self, form: QFormLayout, label: str, key: str, folder: bool) -> QLineEdit:
        edit = QLineEdit(str(self.s[key]), self)
        button = QToolButton(self)
        button.setText("...")
        button.clicked.connect(lambda: self.browse(key, folder))
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(button)
        form.addRow(QLabel(label, self))
        form.addRow(row)
        return edit

    def _data_group(self) -> QGroupBox:
        group = QGroupBox("Dữ liệu", self)
        form = QFormLayout(group)
        self.edits = {
            "input_dir": self._path_row(form, "Thư mục ảnh (GeoTIFF):", "input_dir", True),
            "output_dir": self._path_row(form, "Thư mục kết quả:", "output_dir", True),
            "model": self._path_row(form, "Model YOLO (.pt):", "model", False),
        }
        self.count_label = QLabel(self)
        form.addRow(self.count_label)
        self.edits["input_dir"].textChanged.connect(self.count_images)
        self.count_images()
        return group

    def _classes_group(self) -> QGroupBox:
        group = QGroupBox("Đối tượng theo dõi", self)
        grid = QGridLayout(group)
        self.class_checks = {}
        for i, (key, label) in enumerate(CLASS_OPTIONS):
            check = QCheckBox(label, self)
            check.setChecked(key in self.s["classes"])
            self.class_checks[key] = check
            grid.addWidget(check, i // 2, i % 2)
        row = QHBoxLayout()
        all_vehicles = QPushButton("Tất cả xe", self)
        all_vehicles.clicked.connect(lambda: self.set_classes([k for k, _ in CLASS_OPTIONS]))
        none = QPushButton("Bỏ chọn", self)
        none.clicked.connect(lambda: self.set_classes([]))
        row.addWidget(all_vehicles)
        row.addWidget(none)
        row.addStretch()
        grid.addLayout(row, (len(CLASS_OPTIONS) + 1) // 2, 0, 1, 2)
        return group

    def _parameters_group(self) -> QGroupBox:
        group = QGroupBox("Tham số", self)
        form = QFormLayout(group)
        self.spins = {}
        for label, key, lo, hi, step, tip, decimals in PARAMETERS:
            if decimals:
                spin = QDoubleSpinBox(self)
                spin.setDecimals(decimals)
            else:
                spin = QSpinBox(self)
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setValue(type(spin.value())(self.s[key]))
            spin.setToolTip(tip)
            self.spins[key] = spin
            form.addRow(label, spin)
            if tip:
                note = QLabel(tip, self)
                note.setStyleSheet("color: #888; font-size: 8pt;")
                note.setWordWrap(True)
                form.addRow(note)
        self.device_combo = QComboBox(self)
        self.device_combo.addItems(["auto", "cuda:0", "cpu"])
        self.device_combo.setCurrentText(self.s["device"])
        form.addRow("Thiết bị", self.device_combo)
        self.switches = {}
        for key, label in SWITCHES:
            check = QCheckBox(label, self)
            check.setChecked(bool(self.s[key]))
            self.switches[key] = check
            form.addRow(check)
        reset = QPushButton("Khôi phục mặc định", self)
        reset.clicked.connect(self.reset_defaults)
        form.addRow(reset)
        return group

    def _run_group(self) -> QWidget:
        box = QWidget(self)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        self.run_btn = QPushButton("▶  Chạy phát hiện && nối quỹ đạo", self)
        self.run_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self.run_btn.clicked.connect(self.run)
        self.stop_btn = QPushButton("■  Dừng", self)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label = QLabel("Sẵn sàng", self)
        self.status_label.setWordWrap(True)
        self.add_to_map_check = QCheckBox("Thêm quỹ đạo lên bản đồ khi xong", self)
        self.add_to_map_check.setChecked(bool(self.s["add_to_map"]))
        for w in (self.run_btn, self.stop_btn, self.progress, self.status_label, self.add_to_map_check):
            layout.addWidget(w)
        for text, slot in (
            ("Thêm kết quả lên bản đồ", self.add_results_to_map),
            ("Mở thư mục kết quả", self.open_output),
            ("Mở detections.csv", lambda: self.open_file("detections.csv")),
            ("Mở thư mục Shapefile", lambda: self.open_file("shapefile")),
        ):
            button = QPushButton(text, self)
            button.clicked.connect(lambda _=False, f=slot: f())
            layout.addWidget(button)
        return box

    def _images_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QHBoxLayout(tab)
        side = QVBoxLayout()
        self.image_list = QListWidget(self)
        self.image_list.setFixedWidth(260)
        self.image_list.currentRowChanged.connect(self.on_select_image)
        side.addWidget(self.image_list)
        nav = QHBoxLayout()
        prev_btn = QPushButton("◀ Trước", self)
        prev_btn.clicked.connect(lambda: self.step_image(-1))
        next_btn = QPushButton("Sau ▶", self)
        next_btn.clicked.connect(lambda: self.step_image(1))
        nav.addWidget(prev_btn)
        nav.addWidget(next_btn)
        side.addLayout(nav)
        open_btn = QPushButton("Mở bằng trình xem ảnh", self)
        open_btn.clicked.connect(self.open_current_image)
        side.addWidget(open_btn)
        layout.addLayout(side)
        self.viewer = ImageView(self)
        layout.addWidget(self.viewer, 1)
        for key, step in ((Qt.Key.Key_Left, -1), (Qt.Key.Key_Right, 1)):
            action = QAction(self)
            action.setShortcut(key)
            action.triggered.connect(lambda _=False, d=step: self.step_image(d))
            tab.addAction(action)
        return tab

    def _tracks_tab(self) -> QWidget:
        self.track_table = QTableWidget(0, len(TRACK_COLUMNS), self)
        self.track_table.setHorizontalHeaderLabels([title for _, title in TRACK_COLUMNS])
        self.track_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.track_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.track_table.verticalHeader().hide()
        self.track_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.track_table.setSortingEnabled(True)
        return self.track_table

    def _log_tab(self) -> QWidget:
        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet("background: #111; color: #ddd; font-family: Consolas; font-size: 9pt;")
        return self.log_edit

    # ---------------------------------------------------------------- helpers
    def browse(self, key: str, folder: bool):
        current = self.edits[key].text()
        start = current if os.path.isdir(current) else os.path.dirname(current)
        if folder:
            path = QFileDialog.getExistingDirectory(self, "Chọn thư mục", start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Chọn model", start, "YOLO model (*.pt *.onnx);;All (*.*)")
        if path:
            path = os.path.normpath(path)
            self.edits[key].setText(path)
            if key == "input_dir" and not self.edits["output_dir"].text():
                self.edits["output_dir"].setText(path + "_ketqua")

    def count_images(self, *_):
        folder = self.edits["input_dir"].text()
        if not os.path.isdir(folder):
            self.count_label.setText("")
            return
        n = count_images(folder)
        meta = next((m for m in ("metadata.txt", "metadata.csv") if os.path.isfile(os.path.join(folder, m))), None)
        text = f"→ {n} ảnh" + (f", thời gian chụp lấy từ {meta}" if meta else ", thời gian lấy từ tên file")
        color = "#2a7" if n >= 2 else "#c33"
        self.count_label.setText(f"<font color='{color}'>{text}</font>")

    def set_classes(self, keys: list[str]):
        for key, check in self.class_checks.items():
            check.setChecked(key in keys)

    def reset_defaults(self):
        for key, spin in self.spins.items():
            spin.setValue(type(spin.value())(DEFAULTS[key]))
        for key, check in self.switches.items():
            check.setChecked(bool(DEFAULTS[key]))
        self.device_combo.setCurrentText(DEFAULTS["device"])
        self.set_classes(DEFAULTS["classes"])

    def current_settings(self) -> dict:
        s = {key: edit.text().strip() for key, edit in self.edits.items()}
        s.update({key: spin.value() for key, spin in self.spins.items()})
        s.update({key: check.isChecked() for key, check in self.switches.items()})
        s["device"] = self.device_combo.currentText()
        s["classes"] = [key for key, _ in CLASS_OPTIONS if self.class_checks[key].isChecked()]
        s["add_to_map"] = self.add_to_map_check.isChecked()
        return s

    def save_settings(self, s: dict | None = None):
        settings().setValue(SETTINGS_KEY, json.dumps(s or self.current_settings(), ensure_ascii=False))

    def arguments(self, s: dict) -> list[str]:
        args = ["--input-dir", s["input_dir"], "--output-dir", s["output_dir"], "--model", s["model"],
                "--conf", str(s["conf"]), "--max-speed", str(s["max_speed"]), "--max-gap", str(s["max_gap"]),
                "--min-speed", str(s["min_speed"]), "--low-conf", str(s["low_conf"]),
                "--min-track-score", str(s["min_track_score"]),
                "--min-track-score-2w", str(s["min_track_score_2w"]), "--static-dist", str(s["static_dist"]),
                "--max-link-dist", str(s["max_link_dist"]), "--min-track-len", str(s["min_track_len"]),
                "--tile-size", str(s["tile_size"]), "--overlap", str(s["overlap"]), "--device", s["device"]]
        for key in ("no_sahi", "no_tta"):
            if s[key]:
                args.append("--" + key.replace("_", "-"))
        args += ["--classes", ",".join(s["classes"])]
        for key in ("no_redetect", "no_align", "keep_static"):
            if s[key]:
                args.append("--" + key.replace("_", "-"))
        return args

    def log(self, line: str):
        color = ""
        if "[ERROR]" in line or "Traceback" in line or "Error" in line:
            color = "#ff6b6b"
        elif "[OK]" in line:
            color = "#7ee787"
        elif "[WARN]" in line:
            color = "#f0c674"
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        html = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cursor.insertHtml((f"<span style='color:{color}'>{html}</span>" if color else html) + "<br>")
        self.log_edit.setTextCursor(cursor)
        self.log_edit.ensureCursorVisible()

    # ---------------------------------------------------------------- run
    def run(self):
        s = self.current_settings()
        problem = ""
        if not os.path.isdir(s["input_dir"]):
            problem = "Chưa chọn thư mục ảnh hợp lệ."
        elif not s["output_dir"]:
            problem = "Chưa chọn thư mục kết quả."
        elif not s["classes"]:
            problem = "Hãy chọn ít nhất một loại đối tượng cần theo dõi."
        elif not os.path.isfile(s["model"]):
            problem = f"Không tìm thấy model:\n{s['model']}"
        if problem:
            QMessageBox.critical(self, "Lỗi", problem)
            return
        self.save_settings(s)

        args = self.arguments(s)
        self.log_edit.clear()
        self.log("> python " + SCRIPT + " " + " ".join(f'"{a}"' if " " in a else a for a in args))
        self.tabs.setCurrentIndex(2)
        self.n_frames, self.steps_done = 0, 0
        self.progress.setValue(0)
        self._stopped = False
        self.set_running(True, "Đang tải model...")

        if self.process is not None:
            self.process.deleteLater()
        self.process = ScriptRunner(self)
        self.process.output_line.connect(self.handle_line)
        self.process.error_line.connect(self.handle_line)
        self.process.finished.connect(self.on_done)
        self.process.start_script(SCRIPT, args)

    def handle_line(self, line: str):
        line = line.rstrip("\n")
        if not line.strip():
            return
        self.log(line)
        m = re.match(r"Tìm thấy (\d+) ảnh", line)
        if m:
            self.n_frames = int(m.group(1))
        m = re.match(r"Frame (\d+)/(\d+) (.*?): (\d+) đối tượng", line)
        if m:
            self.steps_done += 1
            self.status_label.setText(f"Phát hiện ảnh {m.group(1)}/{m.group(2)}: {m.group(4)} đối tượng")
        elif line.startswith("[OK] Vẽ"):
            self.steps_done += 1
            self.status_label.setText(f"Đang vẽ ảnh {self.steps_done - self.n_frames}/{self.n_frames}")
        elif line.startswith("[OK] SAHI") or line.startswith("[OK] Ultralytics"):
            self.status_label.setText("Đang phát hiện đối tượng...")
        if self.n_frames:
            self.progress.setValue(min(100, int(self.steps_done / (2 * self.n_frames) * 100)))

    def on_done(self, code: int, crashed: bool):
        if code == 0 and not crashed:
            self.progress.setValue(100)
            self.set_running(False, "Hoàn thành ✔")
            self.load_results()
            self.tabs.setCurrentIndex(0)
            if self.add_to_map_check.isChecked():
                self.add_results_to_map()
        else:
            self.set_running(False, "Đã dừng" if self._stopped else f"Lỗi (mã {code}) - xem tab Nhật ký")

    def stop(self):
        if self.process is not None and self.process.is_running():
            self._stopped = True
            self.process.kill()
            self.log("[WARN] Đã dừng theo yêu cầu.")

    def set_running(self, running: bool, status: str):
        self.run_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.status_label.setText(status)

    # ---------------------------------------------------------------- results
    def output_dir(self) -> str:
        return self.edits["output_dir"].text().strip()

    def load_results(self):
        out = self.output_dir()
        files = []
        summary = os.path.join(out, "trajectories_summary.jpg")
        if os.path.isfile(summary):
            files.append(("★ Tổng hợp quỹ đạo", summary))
        annotated = os.path.join(out, "annotated")
        if os.path.isdir(annotated):
            for f in sorted(os.listdir(annotated)):
                if f.lower().endswith(".jpg"):
                    files.append((f.replace("_det.jpg", ""), os.path.join(annotated, f)))
        self.result_files = files
        self.image_list.clear()
        self.image_list.addItems([name for name, _ in files])
        if files:
            self.image_list.setCurrentRow(0)

        table = self.track_table
        table.setSortingEnabled(False)
        table.setRowCount(0)
        tracks = os.path.join(out, "tracks.geojson")
        if os.path.isfile(tracks):
            try:
                with open(tracks, encoding="utf-8") as f:
                    features = json.load(f).get("features", [])
            except (OSError, ValueError) as e:
                self.log(f"[WARN] Không đọc được tracks.geojson: {e}")
                features = []
            for feature in features:
                p = feature.get("properties", {})
                check = bool(p.get("need_check"))
                status = p.get("status") or "di chuyển"
                values = {
                    **p,
                    "heading": f"{p.get('heading_deg')}° {p.get('direction', '')} ({p.get('dir_code', '')})",
                    "status": status,
                    "check": "Cần kiểm tra" if check else "",
                }
                row = table.rowCount()
                table.insertRow(row)
                color = QColor("#888888") if check else QColor("#1f6fd1") if status == "đứng yên" else None
                for col, (key, _) in enumerate(TRACK_COLUMNS):
                    value = values.get(key)
                    item = QTableWidgetItem()
                    item.setData(Qt.ItemDataRole.DisplayRole, value if isinstance(value, (int, float)) else str(value or ""))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if color is not None:
                        item.setForeground(color)
                    table.setItem(row, col, item)
        table.setSortingEnabled(True)
        table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def on_select_image(self, row: int):
        if 0 <= row < len(self.result_files):
            self.viewer.show_image(self.result_files[row][1])

    def step_image(self, delta: int):
        if self.result_files:
            row = max(0, min(len(self.result_files) - 1, self.image_list.currentRow() + delta))
            self.image_list.setCurrentRow(row)

    def open_current_image(self):
        row = self.image_list.currentRow()
        if 0 <= row < len(self.result_files):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.result_files[row][1]))

    def open_output(self):
        if os.path.isdir(self.output_dir()):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir()))
        else:
            QMessageBox.information(self, "Thông báo", "Thư mục kết quả chưa tồn tại.")

    def open_file(self, name: str):
        path = os.path.join(self.output_dir(), name)
        if os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(self, "Thông báo", f"Chưa có {name}. Hãy chạy trước.")

    def frame_images(self) -> list[str]:
        """The images detect_and_draw.py reads from the input folder (same filter), in name/time order."""
        folder = self.edits["input_dir"].text().strip()
        if not os.path.isdir(folder):
            return []
        return [
            os.path.join(folder, f) for f in sorted(os.listdir(folder))
            if os.path.splitext(f)[1].lower() in IMAGE_EXTS and not any(k in f.lower() for k in DERIVED_MARKS)
        ]

    def add_results_to_map(self) -> int:
        """Shapefiles (vehicle points, tracks) and the UAV images of the last run, in one layer group.

        The images go into a sub-group under the vectors; only the last one is shown so that they do not
        hide each other (tick another one to compare). Falls back to the GeoJSON files when there is no
        shapefile (results of an older version).
        """
        out = self.output_dir()
        name = os.path.basename(out)
        vectors = []
        for shp, geojson, title in (
            ("2_duong_di_phuong_tien.shp", "tracks.geojson", "Đường đi phương tiện"),
            ("1_diem_phuong_tien.shp", "points.geojson", "Điểm phương tiện"),
        ):
            path = next((p for p in (os.path.join(out, "shapefile", shp), os.path.join(out, geojson))
                         if os.path.isfile(p)), None)
            if path is None:
                continue
            layer = QgsVectorLayer(path, title, "ogr")
            if layer.isValid():
                style_result_layer(layer)
                vectors.append(layer)
        if not vectors:
            QMessageBox.information(self, "Thông báo", "Chưa có kết quả (shapefile / tracks.geojson).")
            return 0
        images = [QgsRasterLayer(p, os.path.splitext(os.path.basename(p))[0], "gdal") for p in self.frame_images()]
        images = [layer for layer in images if layer.isValid()]

        project = QgsProject.instance()
        group = project.layerTreeRoot().insertGroup(0, f"Quỹ đạo UAV - {name}")
        for layer in vectors:
            project.addMapLayer(layer, False)
            group.addLayer(layer)
        if images:
            image_group = group.addGroup("Ảnh UAV")
            for i, layer in enumerate(reversed(images)):  # latest on top
                project.addMapLayer(layer, False)
                node = image_group.addLayer(layer)
                node.setItemVisibilityChecked(i == 0)
                node.setExpanded(False)  # no Band 1/2/3 legend rows
        self.output_files = [layer.source() for layer in vectors + images]

        if self.map_canvas is not None:
            dest = self.map_canvas.mapSettings().destinationCrs()
            extent = None
            for layer in images or vectors:
                box = QgsCoordinateTransform(layer.crs(), dest, project).transformBoundingBox(layer.extent())
                if extent is None:
                    extent = box
                else:
                    extent.combineExtentWith(box)
            if extent is not None and not extent.isEmpty():
                self.map_canvas.setExtent(extent.scaled(1.1))
            self.map_canvas.refresh()
        return len(vectors) + len(images)

    def done(self, result: int):
        if self.process is not None and self.process.is_running():
            if QMessageBox.question(self, "Thoát", "Đang chạy. Dừng và thoát?") != QMessageBox.StandardButton.Yes:
                return
            self.process.finished.disconnect()
            self.process.kill()
        self.save_settings()
        super().done(result)
