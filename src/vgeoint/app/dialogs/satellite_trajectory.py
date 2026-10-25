"""Phát hiện quỹ đạo bằng ảnh vệ tinh (ships on multi-date PlanetScope SuperDove scenes).

The code of D:/detectship/shiptrack (see vgeoint/ai/scripts/shiptrack/BAO_CAO_GIAI_PHAP.md) runs in the ai
environment through shiptrack/run_pipeline.py: YOLO-OBB (trained weights) or CFAR detection per scene, ships
linked across dates, shapefiles and an overview map. The dialog follows the UAV trajectory one: options on the
left, result images / table of ships seen on several dates / log on the right, results added to the map
(ship boxes, points, track lines coloured per ship, and the scenes in true colour).

Scenes are days apart: only anchored / slow ships can be linked by position (moving ships need AIS), and the
heading from the SuperDove band offset is not calibrated; the dialog says so.
"""

import json
import os
import re

from qgis.core import (
    Qgis,
    QgsContrastEnhancement,
    QgsCoordinateTransform,
    QgsMultiBandColorRenderer,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QTextCursor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
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
from vgeoint.app.dialogs.uav_trajectory import ImageView, ScrollInsteadOfWheel, _set_label, color_by_track
from vgeoint.common.paths import MODELS_DIR
from vgeoint.common.utils import get_icon, settings

SCRIPT = "shiptrack/run_pipeline.py"
SETTINGS_KEY = "SatelliteTrajectory/Settings"
SCENE_SUFFIX = "_AnalyticMS_8b.tif"  # PlanetScope SuperDove 3B AnalyticMS, 8 bands
# 1-based bands of AnalyticMS_8b (coastal, blue, green_i, green, yellow, red, rededge, nir)
TRUE_COLOR = (6, 4, 2)

METHODS = [
    ("yolo", "YOLO-OBB (mô hình đã huấn luyện, khuyên dùng)"),
    ("cfar", "Theo luật CFAR (không cần mô hình)"),
]

DEFAULTS = {
    "input_dir": "",
    "output_dir": "",
    "weights": "",
    "method": "yolo",
    "conf": 0.25,
    "k": 6.0,
    "gate_m": 800.0,
    "moving_m": 15.0,
    "device": "auto",
    "add_to_map": True,
}

TRACK_COLUMNS = [
    ("track", "Tàu"), ("n_obs", "Số lần thấy"), ("dates", "Các ngày"), ("dist_m", "Dịch chuyển (m)"),
    ("bearing", "Hướng dịch (°)"), ("length_m", "Dài TB (m)"),
]


def default_weights() -> str:
    return str(MODELS_DIR / "ship_obb_v2.pt")


def load_settings() -> dict:
    s = dict(DEFAULTS, weights=default_weights())
    try:
        s.update(json.loads(str(settings().value(SETTINGS_KEY, "") or "{}")))
    except ValueError:
        pass
    return s


def scene_files(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.endswith(SCENE_SUFFIX)]


def true_color(layer: QgsRasterLayer):
    """Red / green / blue bands of an 8-band SuperDove scene, stretched (2-98 %) on a sample."""
    if layer.bandCount() < max(TRUE_COLOR):
        return
    renderer = QgsMultiBandColorRenderer(layer.dataProvider(), *TRUE_COLOR)
    for band, setter in zip(TRUE_COLOR, (renderer.setRedContrastEnhancement, renderer.setGreenContrastEnhancement,
                                         renderer.setBlueContrastEnhancement)):
        enhancement = QgsContrastEnhancement(layer.dataProvider().dataType(band))
        enhancement.setContrastEnhancementAlgorithm(QgsContrastEnhancement.ContrastEnhancementAlgorithm.StretchToMinimumMaximum)
        lo, hi = layer.dataProvider().cumulativeCut(band, 0.02, 0.98, layer.extent(), 250000)
        enhancement.setMinimumValue(lo)
        enhancement.setMaximumValue(hi)
        setter(enhancement)
    layer.setRenderer(renderer)


class SatelliteTrajectoryDialog(QDialog):
    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.s = load_settings()
        self.process: ScriptRunner | None = None
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
        return "SatelliteTrajectory"

    def vn_name(self) -> str:
        return "Phát hiện quỹ đạo bằng ảnh vệ tinh"

    def get_icon(self):
        return get_icon("ship_detection.svg")

    # ---------------------------------------------------------------- UI
    def _build(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(splitter)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(430)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self._data_group())
        left_layout.addWidget(self._parameters_group())
        left_layout.addWidget(self._run_group())
        left_layout.addStretch()
        scroll.setWidget(left)
        splitter.addWidget(scroll)
        self.param_scroll = scroll
        self._wheel_guard = ScrollInsteadOfWheel(scroll, self)
        for box in left.findChildren(QAbstractSpinBox) + left.findChildren(QComboBox):
            box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            box.installEventFilter(self._wheel_guard)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._images_tab(), "Ảnh kết quả")
        self.tabs.addTab(self._tracks_tab(), "Tàu thấy ở nhiều ngày")
        self.tabs.addTab(self._log_tab(), "Nhật ký")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([440, 960])

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
            "input_dir": self._path_row(form, "Thư mục ảnh PlanetScope 8 băng (*_AnalyticMS_8b.tif):", "input_dir", True),
            "output_dir": self._path_row(form, "Thư mục kết quả:", "output_dir", True),
            "weights": self._path_row(form, "Mô hình YOLO-OBB (.pt):", "weights", False),
        }
        self.count_label = QLabel(self)
        self.count_label.setWordWrap(True)
        form.addRow(self.count_label)
        self.edits["input_dir"].textChanged.connect(self.count_scenes)
        self.count_scenes()
        return group

    def _parameters_group(self) -> QGroupBox:
        group = QGroupBox("Tham số", self)
        form = QFormLayout(group)
        self.method_combo = QComboBox(self)
        for key, label in METHODS:
            self.method_combo.addItem(label, key)
        self.method_combo.setCurrentIndex(max(0, self.method_combo.findData(self.s["method"])))
        form.addRow("Phương pháp", self.method_combo)

        def spin(key, lo, hi, step, decimals, tip):
            box = QDoubleSpinBox(self)
            box.setRange(lo, hi)
            box.setSingleStep(step)
            box.setDecimals(decimals)
            box.setValue(float(self.s[key]))
            box.setToolTip(tip)
            return box

        self.spins = {
            "conf": spin("conf", 0.05, 0.95, 0.05, 2, "YOLO-OBB: giảm nếu bị sót tàu, tăng nếu báo động giả"),
            "k": spin("k", 3, 15, 0.5, 1, "CFAR: ngưỡng điểm sáng so với nền (số sigma)"),
            "gate_m": spin("gate_m", 50, 5000, 50, 0, "Khoảng cách tối đa để coi là cùng một tàu giữa hai ngày"),
            "moving_m": spin("moving_m", 1, 100, 1, 0, "Độ lệch băng phổ trên mức này: nghi tàu đang chạy"),
        }
        labels = {"conf": "Ngưỡng tin cậy (YOLO)", "k": "Ngưỡng CFAR (sigma)",
                  "gate_m": "Khoảng cách ghép tối đa (m)", "moving_m": "Ngưỡng tàu đang chạy (m)"}
        for key, box in self.spins.items():
            form.addRow(labels[key], box)
        self.device_combo = QComboBox(self)
        self.device_combo.addItems(["auto", "cuda:0", "cpu"])
        self.device_combo.setCurrentText(self.s["device"])
        form.addRow("Thiết bị", self.device_combo)
        note = QLabel(
            "Ảnh cách nhau nhiều ngày: chỉ ghép được tàu neo / chạy chậm. Tàu đang chạy cần dữ liệu AIS để nối "
            "giữa các ngày. Hướng từ độ lệch băng phổ chưa hiệu chỉnh, chỉ để tham khảo.", self)
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 8pt;")
        form.addRow(note)
        self.method_combo.currentIndexChanged.connect(self._method_changed)
        self._method_changed()
        return group

    def _run_group(self) -> QWidget:
        box = QWidget(self)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        self.run_btn = QPushButton("▶  Phát hiện tàu && ghép quỹ đạo", self)
        self.run_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self.run_btn.clicked.connect(self.run)
        self.stop_btn = QPushButton("■  Dừng", self)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.status_label = QLabel("Sẵn sàng", self)
        self.status_label.setWordWrap(True)
        self.add_to_map_check = QCheckBox("Thêm kết quả và ảnh lên bản đồ khi xong", self)
        self.add_to_map_check.setChecked(bool(self.s["add_to_map"]))
        for w in (self.run_btn, self.stop_btn, self.progress, self.status_label, self.add_to_map_check):
            layout.addWidget(w)
        for text, slot in (
            ("Thêm kết quả lên bản đồ", self.add_results_to_map),
            ("Mở thư mục kết quả", self.open_output),
            ("Mở thư mục Shapefile", lambda: self.open_file("shapefile")),
        ):
            button = QPushButton(text, self)
            button.clicked.connect(lambda _=False, f=slot: f())
            layout.addWidget(button)
        return box

    def _images_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QHBoxLayout(tab)
        self.image_list = QListWidget(self)
        self.image_list.setFixedWidth(280)
        self.image_list.currentRowChanged.connect(self.on_select_image)
        layout.addWidget(self.image_list)
        self.viewer = ImageView(self)
        layout.addWidget(self.viewer, 1)
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
    def _method_changed(self, *_):
        yolo = self.method_combo.currentData() == "yolo"
        self.spins["conf"].setEnabled(yolo)
        self.spins["k"].setEnabled(not yolo)
        self.edits["weights"].setEnabled(yolo)

    def browse(self, key: str, folder: bool):
        current = self.edits[key].text()
        start = current if os.path.isdir(current) else os.path.dirname(current)
        if folder:
            path = QFileDialog.getExistingDirectory(self, "Chọn thư mục", start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Chọn mô hình", start, "YOLO model (*.pt);;All (*.*)")
        if path:
            path = os.path.normpath(path)
            self.edits[key].setText(path)
            if key == "input_dir" and not self.edits["output_dir"].text():
                self.edits["output_dir"].setText(path + "_tau")

    def count_scenes(self, *_):
        folder = self.edits["input_dir"].text()
        if not os.path.isdir(folder):
            self.count_label.setText("")
            return
        n = len(scene_files(folder))
        color = "#2a7" if n >= 2 else "#c33"
        text = f"→ {n} cảnh" + ("" if n >= 2 else " (cần ít nhất 2 ngày để ghép quỹ đạo)")
        self.count_label.setText(f"<font color='{color}'>{text}</font>")

    def current_settings(self) -> dict:
        s = {key: edit.text().strip() for key, edit in self.edits.items()}
        s.update({key: box.value() for key, box in self.spins.items()})
        s["method"] = self.method_combo.currentData()
        s["device"] = self.device_combo.currentText()
        s["add_to_map"] = self.add_to_map_check.isChecked()
        return s

    def save_settings(self, s: dict | None = None):
        settings().setValue(SETTINGS_KEY, json.dumps(s or self.current_settings(), ensure_ascii=False))

    def arguments(self, s: dict) -> list[str]:
        args = ["--input-dir", s["input_dir"], "--output-dir", s["output_dir"], "--method", s["method"],
                "--gate-m", str(s["gate_m"]), "--moving-m", str(s["moving_m"]), "--device", s["device"]]
        if s["method"] == "yolo":
            args += ["--weights", s["weights"], "--conf", str(s["conf"])]
        else:
            args += ["--k", str(s["k"])]
        return args

    def log(self, line: str):
        color = ""
        if "[ERROR]" in line or "Traceback" in line or "Error" in line:
            color = "#ff6b6b"
        elif "[OK]" in line:
            color = "#7ee787"
        elif "[WARN]" in line or line.startswith("SKIP"):
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
        elif not scene_files(s["input_dir"]):
            problem = f"Thư mục không có ảnh PlanetScope 8 băng (*{SCENE_SUFFIX})."
        elif not s["output_dir"]:
            problem = "Chưa chọn thư mục kết quả."
        elif s["method"] == "yolo" and not os.path.isfile(s["weights"]):
            problem = f"Không tìm thấy mô hình:\n{s['weights']}"
        if problem:
            QMessageBox.critical(self, "Lỗi", problem)
            return
        self.save_settings(s)
        args = self.arguments(s)
        self.log_edit.clear()
        self.log("> python " + SCRIPT + " " + " ".join(f'"{a}"' if " " in a else a for a in args))
        self.tabs.setCurrentIndex(2)
        self.progress.setValue(0)
        self._stopped = False
        self.set_running(True, "Đang phát hiện tàu...")
        if self.process is not None:
            self.process.deleteLater()
        self.process = ScriptRunner(self)
        self.process.output_line.connect(self.handle_line)
        self.process.error_line.connect(self.handle_line)
        self.process.event_received.connect(self._on_event)
        self.process.finished.connect(self.on_done)
        self.process.start_script(SCRIPT, args)

    def handle_line(self, line: str):
        line = line.rstrip("\n")
        if line.strip():
            self.log(line)
            m = re.match(r"Cảnh (\d+)/(\d+):", line)
            if m:
                self.status_label.setText(f"Phát hiện tàu: cảnh {m.group(1)}/{m.group(2)}")

    def _on_event(self, event: dict):
        if event.get("type") == "progress":
            self.progress.setValue(int(event.get("value", 0)))

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
        overview = os.path.join(out, "tracks_overview.png")
        if os.path.isfile(overview):
            files.append(("★ Bản đồ tổng quan quỹ đạo", overview))
        if os.path.isdir(out):
            for f in sorted(os.listdir(out)):
                if f.endswith("_quicklook.jpg"):
                    files.append((f.replace("_quicklook.jpg", ""), os.path.join(out, f)))
        self.result_files = files
        self.image_list.clear()
        self.image_list.addItems([name for name, _ in files])
        if files:
            self.image_list.setCurrentRow(0)

        table = self.track_table
        table.setSortingEnabled(False)
        table.setRowCount(0)
        lines = os.path.join(out, "shapefile", "tracks_lines.shp")
        layer = QgsVectorLayer(lines, "tracks", "ogr") if os.path.isfile(lines) else None
        if layer is not None and layer.isValid():
            names = layer.fields().names()
            for feature in layer.getFeatures():
                row = table.rowCount()
                table.insertRow(row)
                for col, (key, _) in enumerate(TRACK_COLUMNS):
                    value = feature[key] if key in names else ""
                    item = QTableWidgetItem()
                    item.setData(Qt.ItemDataRole.DisplayRole, value if isinstance(value, (int, float)) else str(value or ""))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row, col, item)
        table.setSortingEnabled(True)
        table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def on_select_image(self, row: int):
        if 0 <= row < len(self.result_files):
            self.viewer.show_image(self.result_files[row][1])

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

    def add_results_to_map(self) -> int:
        """Track lines, ship points and hull boxes (one colour per ship) over the scenes (true colour)."""
        out = self.output_dir()
        shp = os.path.join(out, "shapefile")
        vectors = []
        for file_name, title in (("tracks_lines.shp", "Quỹ đạo tàu (≥ 2 ngày)"), ("ships_points.shp", "Vị trí tàu"),
                                 ("ships_boxes.shp", "Khung thân tàu")):
            path = os.path.join(shp, file_name)
            if not os.path.isfile(path):
                continue
            layer = QgsVectorLayer(path, title, "ogr")
            if not layer.isValid():
                continue
            color_by_track(layer, "track")
            if file_name == "tracks_lines.shp":
                _set_label(layer, "'#' || \"track\" || ' · ' || format_number(\"dist_m\", 0) || ' m'",
                           Qgis.LabelPlacement.Line)
            elif file_name == "ships_points.shp":
                # "#12 15/04" (date YYYY-MM-DD -> dd/mm)
                _set_label(layer, "'#' || \"track\" || ' ' || substr(\"date\", 9, 2) || '/' || substr(\"date\", 6, 2)",
                           Qgis.LabelPlacement.AroundPoint)
            vectors.append(layer)
        if not vectors:
            QMessageBox.information(self, "Thông báo", "Chưa có kết quả (thư mục shapefile).")
            return 0
        images = [QgsRasterLayer(p, os.path.basename(p)[:23], "gdal")
                  for p in scene_files(self.edits["input_dir"].text().strip())]
        images = [layer for layer in images if layer.isValid()]
        for layer in images:
            true_color(layer)

        project = QgsProject.instance()
        group = project.layerTreeRoot().insertGroup(0, f"Quỹ đạo tàu - {os.path.basename(out)}")
        for layer in vectors:
            project.addMapLayer(layer, False)
            node = group.addLayer(layer)
            node.setExpanded(False)
        if images:
            image_group = group.addGroup("Ảnh vệ tinh")
            for i, layer in enumerate(reversed(images)):  # latest on top, only it shown
                project.addMapLayer(layer, False)
                node = image_group.addLayer(layer)
                node.setItemVisibilityChecked(i == 0)
                node.setExpanded(False)
        self.output_files = [layer.source() for layer in vectors + images]

        if self.map_canvas is not None:
            dest = self.map_canvas.mapSettings().destinationCrs()
            focus = vectors[0] if vectors[0].featureCount() else (vectors[1] if len(vectors) > 1 else vectors[0])
            box = QgsCoordinateTransform(focus.crs(), dest, project).transformBoundingBox(focus.extent())
            if not box.isEmpty():
                self.map_canvas.setExtent(box.buffered(max(box.width(), box.height()) * 0.15))
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
