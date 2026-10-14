"""Download images from Google Earth Engine (replaces GoogleEarthEngineDialog.cpp).

The C++ dialog asked for three free-text values: a Google Cloud project ID, an Earth Engine image ID
("COPERNICUS/S2_SR_HARMONIZED/20240115T032059_...") and a "minLon,minLat,maxLon,maxLat" string, and the
script always downloaded bands B3,B8,B11 (Sentinel-2 only). Now:
- the dataset is picked from a list (with band combinations, dates, cloud cover) and "Tìm ảnh" lists the
  matching images to pick from; an image ID can still be typed in "Nâng cao";
- the region comes from QgsExtentWidget: map canvas extent, a layer extent or a rectangle drawn on the map,
  with an estimate of the download size (Earth Engine refuses direct downloads over ~48 MB);
- the project is remembered, can be checked, and the dialog links to the Earth Engine registration page;
  existing Earth Engine credentials on the machine count as logged in.

Login: `earthengine authenticate --force` run with the ai environment interpreter (AUTH_ARGUMENTS), so the
credentials are stored for the earthengine-api used by gee_download.py (in ~/.config/earthengine).
"""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsRasterLayer, QgsRectangle
from qgis.gui import QgsCollapsibleGroupBox, QgsExtentWidget
from qgis.PyQt.QtCore import QDate, QDateTime, QDir, QFileInfo, QStandardPaths
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from vgeoint.ai.runner import ScriptRunner, python_for, script_path
from vgeoint.common.utils import get_icon, settings

SCRIPT = "gee_download.py"
# `earthengine authenticate --force` run through the ai interpreter (python -c sets sys.argv[1:]).
AUTH_ARGUMENTS = ["-c", "from ee.cli.eecli import main; main()", "authenticate", "--force"]
DEFAULT_PROJECT = "root-clover-471000-e0"  # the C++ default
DEFAULT_REGION = QgsRectangle(105.7, 20.9, 106.0, 21.1)  # the C++ default
MAX_DOWNLOAD_MB = 48  # Earth Engine getDownloadUrl limit (50331648 bytes)
REGISTER_URL = "https://code.earthengine.google.com/register"
PROJECTS_URL = "https://console.cloud.google.com/projectselector2/home/dashboard"
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")

# QgsExtentWidget children (QGIS translations are not loaded): Vietnamese labels; None hides the widget.
EXTENT_WIDGET_TEXTS = {
    "mYMaxLabel": "Bắc", "mYMinLabel": "Nam", "mXMaxLabel": "Đông", "mXMinLabel": "Tây",
    "calculateLabel": "Lấy theo", "mButtonCalcFromLayer": "Lớp trên bản đồ",
    "mCurrentExtentButton": "Khung bản đồ đang xem", "mButtonDrawOnCanvas": "Vẽ trên bản đồ",
    "mButtonCalcFromLayout": None, "mButtonCalcFromBookmark": None,
}

_LOG_ICONS = {"SUCCESS": "✓", "ERROR": "❌", "WARNING": "⚠️", "SYSTEM": "🔧", "INFO": "ℹ️"}


@dataclass(frozen=True)
class Dataset:
    name: str
    collection: str
    scale: int  # native pixel size (m)
    presets: list[tuple[str, str]]  # (label, comma-separated bands)
    cloud_property: str | None = None
    bytes_per_pixel: int = 2
    dated: bool = True
    filters: list[str] = field(default_factory=list)
    methods: tuple[str, ...] = ("least_cloudy", "median", "mosaic")


DATASETS = [
    Dataset(
        "Sentinel-2 (quang học, 10 m)", "COPERNICUS/S2_SR_HARMONIZED", 10,
        [("Màu thật (B4, B3, B2)", "B4,B3,B2"), ("Hồng ngoại màu giả (B8, B4, B3)", "B8,B4,B3"),
         ("Nông nghiệp (B11, B8, B2)", "B11,B8,B2"), ("Như bản cũ (B3, B8, B11)", "B3,B8,B11"),
         ("4 kênh 10 m (B2, B3, B4, B8)", "B2,B3,B4,B8")],
        cloud_property="CLOUDY_PIXEL_PERCENTAGE",
    ),
    Dataset(
        "Landsat 9 (quang học, 30 m)", "LANDSAT/LC09/C02/T1_L2", 30,
        [("Màu thật (B4, B3, B2)", "SR_B4,SR_B3,SR_B2"), ("Hồng ngoại màu giả (B5, B4, B3)", "SR_B5,SR_B4,SR_B3"),
         ("Hồng ngoại sóng ngắn (B7, B5, B4)", "SR_B7,SR_B5,SR_B4")],
        cloud_property="CLOUD_COVER",
    ),
    Dataset(
        "Landsat 8 (quang học, 30 m)", "LANDSAT/LC08/C02/T1_L2", 30,
        [("Màu thật (B4, B3, B2)", "SR_B4,SR_B3,SR_B2"), ("Hồng ngoại màu giả (B5, B4, B3)", "SR_B5,SR_B4,SR_B3"),
         ("Hồng ngoại sóng ngắn (B7, B5, B4)", "SR_B7,SR_B5,SR_B4")],
        cloud_property="CLOUD_COVER",
    ),
    Dataset(
        "Sentinel-1 (radar, chụp xuyên mây, 10 m)", "COPERNICUS/S1_GRD", 10,
        [("Phân cực VV, VH", "VV,VH"), ("Phân cực VV", "VV")],
        bytes_per_pixel=4, filters=["instrumentMode=IW"],
    ),
    Dataset(
        "Độ cao Copernicus DEM (30 m)", "COPERNICUS/DEM/GLO30", 30, [("Độ cao (DEM)", "DEM")],
        bytes_per_pixel=4, dated=False, methods=("mosaic",),
    ),
]

METHOD_LABELS = {
    "least_cloudy": "Một ảnh: ít mây nhất trong khoảng thời gian",
    "median": "Ảnh tổng hợp trung vị (lọc mây, nhiều ngày)",
    "mosaic": "Ghép các ảnh (ảnh mới nhất nằm trên)",
}

_TOO_LARGE = "Vùng quá lớn để tải trực tiếp: thu nhỏ vùng hoặc tăng độ phân giải (số mét lớn hơn)."
_IMAGE_NOT_FOUND = "Không tìm thấy ảnh với ID đã nhập (hoặc tài khoản không có quyền xem ảnh đó)."
_OFFLINE = "Không kết nối được Internet / máy chủ Google."
# (text in the Earth Engine error, explanation for the user); {project} is filled in.
_ERROR_HINTS = [
    ("does not have required permission to use project",
     "Tài khoản đang đăng nhập không có quyền dùng project “{project}”. Hãy nhập ID project của chính bạn "
     "(đã đăng ký Earth Engine), hoặc nhờ chủ project cấp quyền cho tài khoản này."),
    ("not registered to use earth engine",
     "Project “{project}” chưa đăng ký dùng Earth Engine. Đăng ký tại " + REGISTER_URL),
    ("has not been used in project",
     "Project “{project}” chưa bật Earth Engine API. Đăng ký/bật tại " + REGISTER_URL),
    ("not found or deleted",
     "Không tìm thấy project “{project}”. Kiểm tra lại ID project (là ID, không phải tên hiển thị)."),
    ("invalid_grant", "Phiên đăng nhập Google đã hết hạn hoặc bị thu hồi: bấm “Đăng nhập lại”."),
    ("please authorize access", "Chưa đăng nhập Earth Engine trên máy này: bấm “Đăng nhập”."),
    ("request size", _TOO_LARGE),
    ("must be less than or equal to", _TOO_LARGE),
    ("no image matches",
     "Không có ảnh nào khớp khoảng thời gian / độ mây / vùng: nới khoảng thời gian hoặc độ mây."),
    ("image asset", _IMAGE_NOT_FOUND),
    ("not found", _IMAGE_NOT_FOUND),
    ("band pattern", "Ảnh không có kênh đã chọn: kiểm tra Tổ hợp kênh / ô Kênh."),
    ("nameresolutionerror", _OFFLINE),
    ("connectionerror", _OFFLINE),
]


def explain_error(lines: list[str], project: str) -> str:
    """The script's first error line (the cause; later lines are generic hints), explained in Vietnamese."""
    if not lines:
        return "Không rõ lý do: xem mục “Chi tiết tiến trình”."
    detail = lines[0] if len(lines[0]) <= 300 else lines[0][:300] + "…"
    text = " ".join(lines).lower()
    for needle, hint in _ERROR_HINTS:
        if needle in text:
            return f"{hint.format(project=project)}\n\nChi tiết: {detail}"
    return detail


def credentials_path() -> Path:
    """Where `earthengine authenticate` stores the refresh token (same path on Windows)."""
    return Path(os.path.expanduser("~/.config/earthengine/credentials"))


def estimate(extent: QgsRectangle, scale: float, bands: int, bytes_per_pixel: int) -> tuple[float, int, int, float]:
    """(area km², width px, height px, size MB) of a WGS 84 extent downloaded at `scale` metres."""
    lat = math.radians((extent.yMinimum() + extent.yMaximum()) / 2)
    width_m = extent.width() * 111_320 * math.cos(lat)
    height_m = extent.height() * 110_574
    width_px, height_px = max(1, round(width_m / scale)), max(1, round(height_m / scale))
    size_mb = width_px * height_px * bands * bytes_per_pixel / 1024 / 1024
    return width_m * height_m / 1e6, width_px, height_px, size_mb


class GoogleEarthEngineDialog(QDialog):
    # The C++ dialog emitted complete() after adding the layer itself; MainController never connected it
    # for dialogs, so there is no `complete` signal here (it would add the image twice).

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.is_logged_in = credentials_path().exists()
        self.output_files: list[str] = []
        self._process: ScriptRunner | None = None
        self._task = ""  # "download" | "list" | "check"
        self._process_start_time = QDateTime()
        self._downloaded_file = ""
        self._started = False

        self._setup_ui()
        self._load_settings()
        self._update_login_state()
        self._dataset_changed()

        self.login_btn.clicked.connect(self.on_login_clicked)
        self.check_project_btn.clicked.connect(self.on_check_project_clicked)
        self.search_btn.clicked.connect(self.on_search_clicked)
        self.download_btn.clicked.connect(self.on_download_clicked)
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        self.clear_log_btn.clicked.connect(self.clear_log)
        self.save_log_btn.clicked.connect(self.save_log)
        self.browse_output_btn.clicked.connect(self.browse_output)
        self.dataset_combo.currentIndexChanged.connect(self._dataset_changed)
        for signal in (self.preset_combo.currentIndexChanged, self.method_combo.currentIndexChanged,
                       self.scale_spin.valueChanged, self.extent_widget.extentChanged):
            signal.connect(self._update_estimate)
        for signal in (self.dataset_combo.currentIndexChanged, self.start_date.dateChanged,
                       self.end_date.dateChanged, self.cloud_spin.valueChanged, self.extent_widget.extentChanged):
            signal.connect(self._clear_images)
        self.images_table.itemSelectionChanged.connect(self._update_selection_label)
        self.extent_widget.toggleDialogVisibility.connect(self.setVisible)

        self.add_log("Giao diện Google Earth Engine đã sẵn sàng", "SYSTEM")

    # BPluginInterface
    def name(self) -> str:
        return "GoogleEarthEngine"

    def vn_name(self) -> str:
        return "Tải ảnh từ Google Earth Engine"

    def get_icon(self):
        return get_icon("GoogleEarthEngine.svg")

    def auto_add_output_files(self) -> bool:
        return self.auto_add_check_box.isChecked()

    # ---------------------------------------------------------------- UI
    def _setup_ui(self):
        self.setWindowTitle("Tải ảnh từ Google Earth Engine")
        self.setWindowIcon(self.get_icon())
        layout = QVBoxLayout(self)
        columns = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(self._create_account_group())
        left.addWidget(self._create_image_group())
        left.addStretch()
        right.addWidget(self._create_region_group())
        right.addWidget(self._create_output_group())
        right.addStretch()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns)
        layout.addLayout(self._create_buttons())
        layout.addWidget(self._create_log_group())

    def _create_account_group(self) -> QGroupBox:
        group = QGroupBox("1. Tài khoản Google Earth Engine", self)
        form = QFormLayout(group)

        self.login_label = QLabel(self)
        self.login_btn = QPushButton("Đăng nhập", self)
        row = QHBoxLayout()
        row.addWidget(self.login_label, 1)
        row.addWidget(self.login_btn)
        form.addRow("Trạng thái:", row)

        self.project_combo = QComboBox(self)
        self.project_combo.setEditable(True)
        self.project_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.project_combo.lineEdit().setPlaceholderText("ví dụ: ten-du-an-123456")
        self.project_combo.setToolTip(
            "ID của Google Cloud project đã đăng ký dùng Earth Engine (không phải tên hiển thị).\n"
            "Các project đã dùng thành công được nhớ lại trong danh sách."
        )
        self.check_project_btn = QPushButton("Kiểm tra", self)
        self.check_project_btn.setToolTip("Kiểm tra tài khoản có dùng được project này không")
        row = QHBoxLayout()
        row.addWidget(self.project_combo, 1)
        row.addWidget(self.check_project_btn)
        form.addRow("Project:", row)

        help_label = QLabel(
            f'Chưa có project? <a href="{REGISTER_URL}">Đăng ký dùng Earth Engine</a> (miễn phí cho '
            f'nghiên cứu/phi thương mại) · <a href="{PROJECTS_URL}">Xem ID các project của bạn</a>',
            self,
        )
        help_label.setOpenExternalLinks(True)
        help_label.setWordWrap(True)
        form.addRow(help_label)
        return group

    def _create_image_group(self) -> QGroupBox:
        group = QGroupBox("2. Ảnh cần tải", self)
        form = QFormLayout(group)

        self.dataset_combo = QComboBox(self)
        for ds in DATASETS:
            self.dataset_combo.addItem(ds.name)
        form.addRow("Bộ dữ liệu:", self.dataset_combo)

        self.preset_combo = QComboBox(self)
        form.addRow("Tổ hợp kênh:", self.preset_combo)

        self.start_date = QDateEdit(self)
        self.end_date = QDateEdit(self)
        for edit in (self.start_date, self.end_date):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("dd/MM/yyyy")
        today = QDate.currentDate()
        self.start_date.setDate(today.addMonths(-6))
        self.end_date.setDate(today)
        self.date_row = QHBoxLayout()
        self.date_row.addWidget(QLabel("Từ", self))
        self.date_row.addWidget(self.start_date)
        self.date_row.addWidget(QLabel("đến", self))
        self.date_row.addWidget(self.end_date)
        self.date_row.addStretch()
        self.date_label = QLabel("Thời gian chụp:", self)
        form.addRow(self.date_label, self.date_row)

        self.cloud_spin = QSpinBox(self)
        self.cloud_spin.setRange(0, 100)
        self.cloud_spin.setValue(20)
        self.cloud_spin.setSuffix(" %")
        self.cloud_label = QLabel("Mây tối đa:", self)
        form.addRow(self.cloud_label, self.cloud_spin)

        self.method_combo = QComboBox(self)
        form.addRow("Cách lấy ảnh:", self.method_combo)

        self.scale_spin = QSpinBox(self)
        self.scale_spin.setRange(1, 10000)
        self.scale_spin.setSuffix(" m")
        self.scale_spin.setToolTip("Kích thước một điểm ảnh khi tải. Tăng lên để tải vùng lớn hơn.")
        form.addRow("Độ phân giải:", self.scale_spin)

        self.search_btn = QPushButton("Tìm ảnh trong vùng", self)
        self.search_btn.setToolTip("Liệt kê các ảnh khớp thời gian, độ mây và vùng quan tâm để chọn")
        self.images_table = QTableWidget(0, 3, self)
        self.images_table.setHorizontalHeaderLabels(["Ngày chụp (UTC)", "Mây", "ID ảnh"])
        self.images_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.images_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.images_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.images_table.verticalHeader().hide()
        header = self.images_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.images_table.setMaximumHeight(120)
        self.images_table.hide()
        self.selection_label = QLabel(self)
        self.selection_label.setWordWrap(True)
        form.addRow(self.search_btn, self.selection_label)
        form.addRow(self.images_table)

        self.advanced_group = QgsCollapsibleGroupBox("Nâng cao: tải theo ID ảnh", self)
        self.advanced_group.setCollapsed(True)
        adv = QFormLayout(self.advanced_group)
        self.data_id_edit = QLineEdit(self)
        self.data_id_edit.setPlaceholderText("ví dụ: COPERNICUS/S2_SR_HARMONIZED/20240115T032059_20240115T033524_T48QWJ")
        self.data_id_edit.setClearButtonEnabled(True)
        self.bands_edit = QLineEdit(self)
        self.bands_edit.setPlaceholderText("để trống = theo Tổ hợp kênh ở trên")
        adv.addRow("ID ảnh:", self.data_id_edit)
        adv.addRow("Kênh:", self.bands_edit)
        form.addRow(self.advanced_group)
        return group

    def _create_region_group(self) -> QGroupBox:
        group = QGroupBox("3. Vùng quan tâm", self)
        layout = QVBoxLayout(group)
        self.extent_widget = QgsExtentWidget(self, QgsExtentWidget.WidgetStyle.ExpandedStyle)
        self.extent_widget.setOutputCrs(WGS84)
        if self.map_canvas is not None:
            self.extent_widget.setMapCanvas(self.map_canvas)
        for name, text in EXTENT_WIDGET_TEXTS.items():
            child = self.extent_widget.findChild(QWidget, name)
            if child is None:
                continue
            if text is None:
                child.hide()
            else:
                child.setText(text)
        layout.addWidget(self.extent_widget)
        hint = QLabel("Toạ độ theo độ (WGS 84). Bấm “Vẽ trên bản đồ” rồi kéo một hình chữ nhật, hoặc lấy theo "
                      "khung bản đồ đang xem / một lớp.", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.estimate_label = QLabel(self)
        self.estimate_label.setWordWrap(True)
        layout.addWidget(self.estimate_label)
        return group

    def _create_output_group(self) -> QGroupBox:
        group = QGroupBox("4. Lưu kết quả", self)
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self.output_path_edit = QLineEdit(self)
        self.browse_output_btn = QPushButton("Chọn...", self)
        row.addWidget(QLabel("Thư mục:", self))
        row.addWidget(self.output_path_edit, 1)
        row.addWidget(self.browse_output_btn)
        layout.addLayout(row)
        self.auto_add_check_box = QCheckBox("Tự động thêm ảnh vào bản đồ", self)
        self.auto_add_check_box.setChecked(True)
        layout.addWidget(self.auto_add_check_box)
        return group

    def _create_buttons(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setVisible(False)
        self.status_label = QLabel("Sẵn sàng", self)
        self.download_btn = QPushButton("Tải ảnh", self)
        self.download_btn.setDefault(True)
        self.cancel_btn = QPushButton("Đóng", self)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.progress_bar, 1)
        layout.addWidget(self.download_btn)
        layout.addWidget(self.cancel_btn)
        return layout

    def _create_log_group(self) -> QgsCollapsibleGroupBox:
        self.log_group = QgsCollapsibleGroupBox("Chi tiết tiến trình", self)
        self.log_group.setCollapsed(True)
        layout = QVBoxLayout(self.log_group)
        self.log_text_edit = QTextEdit(self)
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setMinimumHeight(120)
        log_button_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("Xóa log", self)
        self.save_log_btn = QPushButton("Lưu log", self)
        log_button_layout.addWidget(self.clear_log_btn)
        log_button_layout.addWidget(self.save_log_btn)
        log_button_layout.addStretch()
        layout.addWidget(self.log_text_edit)
        layout.addLayout(log_button_layout)
        return self.log_group

    # ---------------------------------------------------------------- state
    def dataset(self) -> Dataset:
        return DATASETS[max(0, self.dataset_combo.currentIndex())]

    def bands(self) -> str:
        return self.bands_edit.text().strip() or (self.preset_combo.currentData() or "")

    def method(self) -> str:
        return self.method_combo.currentData() or self.dataset().methods[0]

    def project_id(self) -> str:
        return self.project_combo.currentText().strip()

    def region(self) -> QgsRectangle:
        return self.extent_widget.outputExtent()

    def region_text(self) -> str:
        r = self.region()
        return ",".join(f"{v:.6f}".rstrip("0").rstrip(".") for v in (r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()))

    def selected_image_id(self) -> str:
        rows = self.images_table.selectionModel().selectedRows()
        return self.images_table.item(rows[0].row(), 2).text() if rows else ""

    def _dataset_changed(self, *_):
        ds = self.dataset()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for label, bands in ds.presets:
            self.preset_combo.addItem(label, bands)
        self.preset_combo.blockSignals(False)
        self.method_combo.blockSignals(True)
        self.method_combo.clear()
        for m in ds.methods:
            label = METHOD_LABELS[m] if (m != "least_cloudy" or ds.cloud_property) else "Một ảnh: mới nhất trong khoảng thời gian"
            self.method_combo.addItem(label, m)
        self.method_combo.blockSignals(False)
        self.scale_spin.setValue(ds.scale)
        for w in (self.start_date, self.end_date, self.date_label):
            w.setEnabled(ds.dated)
        for w in (self.cloud_spin, self.cloud_label):
            w.setEnabled(ds.cloud_property is not None)
        self.search_btn.setEnabled(ds.dated)
        self._update_estimate()

    def _update_estimate(self, *_):
        extent = self.region()
        if not self.extent_widget.isValid() or extent.isEmpty():
            self.estimate_label.setText("<font color='#c0392b'>Chưa chọn vùng quan tâm</font>")
            return
        ds = self.dataset()
        n_bands = max(1, len([b for b in self.bands().split(",") if b.strip()]))
        bpp = 4 if self.method() == "median" else ds.bytes_per_pixel
        area, w, h, mb = estimate(extent, self.scale_spin.value(), n_bands, bpp)
        text = f"Diện tích ≈ {area:,.1f} km² · ảnh ≈ {w:,} × {h:,} điểm ảnh · ≈ {mb:,.1f} MB"
        if mb > MAX_DOWNLOAD_MB:
            need = math.ceil(self.scale_spin.value() * math.sqrt(mb / MAX_DOWNLOAD_MB))
            text = (f"<font color='#c0392b'>{text}<br>Quá giới hạn tải trực tiếp của Earth Engine (~{MAX_DOWNLOAD_MB} MB): "
                    f"thu nhỏ vùng hoặc tăng độ phân giải lên ≥ {need} m.</font>")
        self.estimate_label.setText(text)

    def _clear_images(self, *_):
        self.images_table.setRowCount(0)
        self.images_table.hide()
        self._update_selection_label()

    def _update_selection_label(self):
        image_id = self.selected_image_id()
        if image_id:
            self.selection_label.setText(f"Sẽ tải ảnh đã chọn: <b>{image_id.rsplit('/', 1)[-1]}</b>")
        elif self.images_table.rowCount():
            self.selection_label.setText("Chọn một ảnh trong bảng, hoặc để trống để lấy theo “Cách lấy ảnh”.")
        else:
            self.selection_label.setText("")

    def _update_login_state(self):
        if self.is_logged_in:
            self.login_label.setText("<font color='#27ae60'>✓ Đã đăng nhập trên máy này</font>")
            self.login_btn.setText("Đăng nhập lại")
        else:
            self.login_label.setText("<font color='#c0392b'>Chưa đăng nhập</font> — bấm Đăng nhập, trình duyệt sẽ mở trang Google")
            self.login_btn.setText("Đăng nhập")

    # ---------------------------------------------------------------- settings
    def _projects(self) -> list[str]:
        saved = str(settings().value("GoogleEarthEngine/Projects", "") or "")
        return [p for p in saved.split("|") if p]

    def _remember_project(self, project: str):
        projects = [project] + [p for p in self._projects() if p != project]
        settings().setValue("GoogleEarthEngine/Projects", "|".join(projects[:10]))
        if self.project_combo.findText(project) < 0:
            self.project_combo.insertItem(0, project)

    def _load_settings(self):
        s = settings()
        projects = self._projects() or [DEFAULT_PROJECT]
        self.project_combo.addItems(projects)
        self.project_combo.setCurrentText(str(s.value("GoogleEarthEngine/Project", projects[0])))
        self.dataset_combo.setCurrentIndex(int(s.value("GoogleEarthEngine/Dataset", 0)))
        self.cloud_spin.setValue(int(s.value("GoogleEarthEngine/MaxCloud", 20)))
        default_out = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation),
                           "vGeoInt", "GoogleEarthEngine")
        self.output_path_edit.setText(str(s.value("GoogleEarthEngine/Output", str(default_out))))

        saved = str(s.value("GoogleEarthEngine/Region", "") or "")
        try:
            x0, y0, x1, y1 = (float(v) for v in saved.split(","))
            self.extent_widget.setOutputExtentFromUser(QgsRectangle(x0, y0, x1, y1), WGS84)
        except ValueError:
            # The map view when it shows layers, else the C++ default region (Hà Nội).
            canvas = self.map_canvas
            if canvas is not None and canvas.layers() and not canvas.extent().isEmpty():
                self.extent_widget.setCurrentExtent(canvas.extent(), canvas.mapSettings().destinationCrs())
                self.extent_widget.setOutputExtentFromCurrent()
            else:
                self.extent_widget.setOutputExtentFromUser(DEFAULT_REGION, WGS84)

    def _save_settings(self):
        s = settings()
        s.setValue("GoogleEarthEngine/Project", self.project_id())
        s.setValue("GoogleEarthEngine/Dataset", self.dataset_combo.currentIndex())
        s.setValue("GoogleEarthEngine/MaxCloud", self.cloud_spin.value())
        s.setValue("GoogleEarthEngine/Output", self.output_path_edit.text().strip())
        if self.extent_widget.isValid():
            s.setValue("GoogleEarthEngine/Region", self.region_text())

    # ---------------------------------------------------------------- login
    def on_login_clicked(self):
        self.add_log("Bắt đầu quá trình đăng nhập Google Earth Engine...", "INFO")
        self.login_label.setText("Đang chờ đăng nhập trong trình duyệt...")
        process = ScriptRunner(self)
        state = {"started": False}
        process.started.connect(lambda: state.update(started=True))
        process.output_line.connect(lambda line: self.add_log(line.strip(), "INFO"))
        process.error_line.connect(lambda line: self.add_log(line.strip(), "INFO"))
        process.finished.connect(lambda code, crashed: self._login_finished(process, state["started"], code))
        self.login_btn.setEnabled(False)
        process.start_script("", AUTH_ARGUMENTS, program=python_for(process.env))

    def _login_finished(self, process: ScriptRunner, started: bool, exit_code: int):
        process.deleteLater()
        self.login_btn.setEnabled(True)
        if not started:
            self._update_login_state()
            self.add_log("Không thể khởi động script!", "ERROR")
            QMessageBox.critical(self, "Lỗi", "Không thể khởi động script!")
            return
        if exit_code == 0:
            self.is_logged_in = True
            self._update_login_state()
            self.add_log("Đăng nhập thành công!", "SUCCESS")
            QMessageBox.information(self, "Thành công", "Đăng nhập thành công!")
        else:
            self._update_login_state()
            self.add_log("Đăng nhập thất bại!", "ERROR")
            QMessageBox.warning(self, "Lỗi", "Đăng nhập thất bại!")

    # ---------------------------------------------------------------- actions
    def _validate(self, need_region: bool = True) -> bool:
        problem = ""
        if not self.is_logged_in:
            problem = "Vui lòng đăng nhập trước!"
        elif not self.project_id():
            problem = "Vui lòng nhập Project!"
        elif need_region and (not self.extent_widget.isValid() or self.region().isEmpty()):
            problem = "Vui lòng chọn vùng quan tâm!"
        elif self.dataset().dated and self.start_date.date() > self.end_date.date():
            problem = "Ngày bắt đầu phải trước ngày kết thúc!"
        if problem:
            self.add_log(problem, "WARNING")
            QMessageBox.warning(self, "Cảnh báo", problem)
            return False
        return True

    def _collection_arguments(self) -> list[str]:
        ds = self.dataset()
        args = ["--collection", ds.collection]
        if ds.dated:
            args += ["--start", self.start_date.date().toString("yyyy-MM-dd"),
                     "--end", self.end_date.date().addDays(1).toString("yyyy-MM-dd")]
        if ds.cloud_property:
            args += ["--cloud_property", ds.cloud_property, "--max_cloud", str(self.cloud_spin.value())]
        for f in ds.filters:
            args += ["--filter", f]
        return args

    def on_check_project_clicked(self):
        if self._validate(need_region=False):
            self.add_log(f"Kiểm tra project {self.project_id()}...", "INFO")
            self._run("check", ["--check"])

    def on_search_clicked(self):
        if self._validate():
            self.add_log(f"Tìm ảnh {self.dataset().name}...", "INFO")
            self._run("list", [*self._collection_arguments(), "--list"])

    def on_download_clicked(self):
        if not self._validate():
            return
        output_path = self.output_path_edit.text().strip()
        if not output_path:
            output_path = str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation),
                                   "vGeoInt", "GoogleEarthEngine"))
            self.output_path_edit.setText(output_path)
        image_id = self.data_id_edit.text().strip() or self.selected_image_id()
        args = ["--output", os.path.abspath(output_path), "--scale", str(self.scale_spin.value())]
        if self.bands():
            args += ["--bands", self.bands()]
        if image_id:
            args += ["--data_id", image_id]
        else:
            short = self.dataset().collection.split("/")[0]
            args += [*self._collection_arguments(), "--method", self.method(), "--name", f"{short}_{self.method()}"]
        self.add_log("Bắt đầu tải dữ liệu...", "INFO")
        self._save_settings()
        self._run("download", args)

    def on_cancel_clicked(self):
        self.close()

    def _set_busy(self, busy: bool, text: str = ""):
        for w in (self.download_btn, self.search_btn, self.check_project_btn, self.login_btn):
            w.setEnabled(not busy)
        if not busy:
            self.search_btn.setEnabled(self.dataset().dated)
        self.progress_bar.setVisible(busy)
        self.status_label.setText(text)

    def _run(self, task: str, args: list[str]):
        if self._process is not None:
            self._process.deleteLater()
        self._task = task
        self._process_start_time = QDateTime.currentDateTime()
        self._process = ScriptRunner(self)
        self._process.started.connect(self._on_process_started)
        self._process.finished.connect(self.on_process_finished)
        self._process.output_line.connect(self.on_process_ready_read_standard_output)
        self._process.error_line.connect(self.on_process_ready_read_standard_error)
        self._process.event_received.connect(self._on_event)
        self._downloaded_file = ""
        self._error_lines: list[str] = []

        script = script_path(SCRIPT)
        if not script.exists():
            self.add_log(f"Lỗi: Script Python không tồn tại: {script}", "ERROR")
            self.on_process_error("Không thể khởi động process")
            return
        arguments = ["--project_id", self.project_id(), "--region", self.region_text(), *args]
        self.add_log(f"python {script.name} {' '.join(arguments)}", "INFO")
        texts = {"download": "Đang tải ảnh...", "list": "Đang tìm ảnh...", "check": "Đang kiểm tra project..."}
        self._set_busy(True, texts[task])
        self._started = False
        self._process.start_script(SCRIPT, arguments)

    def _on_process_started(self):
        self._started = True

    def _on_event(self, event: dict):
        if event.get("type") != "result":
            return
        if event.get("output"):
            self._downloaded_file = event["output"]
        if "images" in event:
            self._show_images(event["images"], int(event.get("total", len(event["images"]))))

    def _show_images(self, images: list[dict], total: int):
        self.images_table.setRowCount(0)
        for image in images:
            row = self.images_table.rowCount()
            self.images_table.insertRow(row)
            cloud = image.get("cloud")
            values = [image.get("date", ""), "" if cloud is None else f"{cloud:g} %", image.get("id", "")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 2:
                    item.setToolTip(value)
                self.images_table.setItem(row, col, item)
        self.images_table.setVisible(bool(images))
        shown = f" (hiện {len(images)} ảnh ít mây nhất)" if total > len(images) else ""
        self.status_label.setText(f"Tìm thấy {total} ảnh{shown}" if total else "Không có ảnh nào khớp")
        self._update_selection_label()

    def on_process_finished(self, exit_code: int, crashed: bool):
        task = self._task
        if not self._started:
            self.add_log("Lỗi: Không thể khởi động Python process", "ERROR")
            self.on_process_error("Không thể khởi động process")
            return
        ms = self._process_start_time.msecsTo(QDateTime.currentDateTime())
        time_str = f"{ms // 1000}.{(ms % 1000) // 100}s"
        self.add_log(f"Kết thúc sau {time_str}, mã thoát {exit_code}{' (crashed)' if crashed else ''}", "SYSTEM")
        status = self.status_label.text()
        self._set_busy(False)
        ok = not crashed and exit_code == 0
        reason = explain_error(self._error_lines, self.project_id())

        if task == "check":
            if ok:
                self._remember_project(self.project_id())
                self.status_label.setText(f"Project {self.project_id()} dùng được")
                QMessageBox.information(self, "Project", f"Project “{self.project_id()}” dùng được với Earth Engine.")
            else:
                self.status_label.setText("Project không dùng được")
                QMessageBox.warning(
                    self, "Project",
                    f"Không dùng được project “{self.project_id()}”.\n\n{reason}",
                )
            return
        if task == "list":
            if ok:
                self._remember_project(self.project_id())
                rows = self.images_table.rowCount()
                self.status_label.setText(status if rows else "Không có ảnh nào khớp: nới khoảng thời gian hoặc độ mây")
            else:
                self.status_label.setText("Tìm ảnh thất bại")
                QMessageBox.critical(self, "Lỗi", f"Tìm ảnh thất bại!\n\n{reason}")
            return

        if not ok:
            self.status_label.setText("Tải dữ liệu thất bại!")
            self.add_log("❌ Quá trình tải dữ liệu thất bại!", "ERROR")
            QMessageBox.critical(
                self, "Lỗi",
                f"Tải dữ liệu thất bại!\n\n{reason}",
            )
            return

        self._remember_project(self.project_id())
        self.status_label.setText("Hoàn thành thành công!")
        self.add_log("✅ Quá trình tải dữ liệu hoàn tất thành công!", "SUCCESS")
        full_path = self._downloaded_file
        if not full_path or not QFileInfo.exists(full_path):
            # C++ fallback: last *.tif / *.tiff / *.geotiff of the output folder (by name)
            out_dir = QDir(os.path.abspath(self.output_path_edit.text().strip()))
            files = out_dir.entryList(["*.tif", "*.tiff", "*.geotiff"], QDir.Filter.Files)
            full_path = out_dir.filePath(files[-1]) if files else ""
        if not full_path:
            self.add_log("⚠️ Cảnh báo: Không tìm thấy file đã tải", "WARNING")
            QMessageBox.warning(self, "Cảnh báo", "Tải dữ liệu hoàn tất nhưng không tìm thấy file đã tải.")
            return
        info = QFileInfo(full_path)
        self.add_log(f"📄 File đã tải: {info.fileName()}")
        self.add_log(f"📊 Kích thước: {info.size() / 1024.0:.1f} KB")
        if self.auto_add_output_files():
            self.output_files = [full_path]
            if self.add_output_to_map():
                self.add_log("✅ Đã thêm kết quả vào bản đồ thành công", "SUCCESS")
            else:
                self.add_log("⚠️ Không thể thêm kết quả vào bản đồ", "WARNING")
            QApplication.beep()
        QMessageBox.information(
            self, "Thành công", f"Tải dữ liệu hoàn thành!\n\nFile: {info.filePath()}\nThời gian xử lý: {time_str}"
        )

    def on_process_error(self, error_msg: str):
        self._set_busy(False, "Lỗi")
        self.add_log(f"❌ Lỗi process: {error_msg}", "ERROR")

    def on_process_ready_read_standard_output(self, line: str):
        trimmed = line.strip()
        if not trimmed:
            return
        if "[OK]" in trimmed:
            self.add_log(trimmed, "SUCCESS")
        elif "[ERROR]" in trimmed:
            self._error_lines.append(trimmed.split("[ERROR]", 1)[1].strip())
            self.add_log(trimmed, "ERROR")
        elif "[WARN]" in trimmed:
            self.add_log(trimmed, "WARNING")
        else:
            self.add_log(trimmed, "INFO")

    def on_process_ready_read_standard_error(self, line: str):
        if line.strip():
            self.add_log(line.strip(), "ERROR")

    # ---------------------------------------------------------------- log
    def add_log(self, message: str, log_type: str = "INFO"):
        self.log_text_edit.append(self.format_log_message(message, log_type))
        bar = self.log_text_edit.verticalScrollBar()
        bar.setValue(bar.maximum())

    def add_log_with_timestamp(self, message: str, log_type: str = "INFO"):
        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
        self.add_log(f"[{timestamp}] {message}", log_type)

    def clear_log(self):
        self.log_text_edit.clear()
        self.add_log("Log đã được xóa", "SYSTEM")

    def save_log(self):
        s = settings()
        default_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        dir_ = s.value("GoogleEarthEngine/LogDir", default_dir)
        timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_hhmmss")
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Lưu log", QDir(dir_).filePath(f"gee_download_log_{timestamp}.txt"), "Text files (*.txt);;All files (*)"
        )
        if not file_name:
            return
        try:
            with open(file_name, "w", encoding="utf-8") as f:
                f.write("=== vGeoInt Google Earth Engine Download Log ===\n")
                f.write(f"Timestamp: {QDateTime.currentDateTime().toString('yyyy-MM-dd hh:mm:ss')}\n\n")
                f.write(self.log_text_edit.toPlainText())
        except OSError:
            QMessageBox.critical(self, "Lỗi", f"Không thể lưu log vào file:\n{file_name}")
            return
        self.add_log(f"✅ Log đã được lưu: {QFileInfo(file_name).fileName()}", "SUCCESS")
        store_dir = QFileInfo(file_name).dir().path()
        if store_dir != dir_:
            s.setValue("GoogleEarthEngine/LogDir", store_dir)

    def format_log_message(self, message: str, log_type: str) -> str:
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        return f"[{timestamp}] {_LOG_ICONS.get(log_type, '•')} {message}"

    def browse_output(self):
        current = self.output_path_edit.text().strip()
        start = current if QDir(current).exists() else QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        folder_path = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục lưu ảnh", start,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if folder_path:
            self.output_path_edit.setText(QDir.toNativeSeparators(folder_path))

    def add_output_to_map(self) -> bool:
        if not self.output_files:
            return False
        output_path = self.output_files[0]
        if not QFileInfo.exists(output_path):
            self.add_log(f"❌ File đầu ra không tồn tại: {output_path}", "ERROR")
            return False
        info = QFileInfo(output_path)
        if info.suffix().lower() not in ("tif", "tiff", "geotiff"):
            self.add_log(f"❌ Định dạng file không được hỗ trợ: {info.suffix()}", "ERROR")
            return False
        layer = QgsRasterLayer(output_path, info.completeBaseName(), "gdal")
        if not layer.isValid():
            self.add_log("❌ Ảnh vệ tinh không hợp lệ", "ERROR")
            return False
        self.add_log(f"✅ Ảnh vệ tinh hợp lệ - {layer.width()}x{layer.height()} pixels", "SUCCESS")
        QgsProject.instance().addMapLayer(layer)
        if self.map_canvas is not None:
            self.map_canvas.refresh()
        return True

    def done(self, result: int):
        # Kill a running script when the dialog closes (C++ deleteLater'd the QProcess in the destructor).
        for runner in self.findChildren(ScriptRunner):
            if runner.is_running():
                runner.finished.disconnect()
                runner.kill()
        self._save_settings()
        super().done(result)
