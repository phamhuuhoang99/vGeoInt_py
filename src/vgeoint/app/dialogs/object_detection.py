"""Phát hiện đối tượng: xe tăng / máy bay on satellite or UAV images (code of D:/detecttank).

objdetect/run_detect.py runs in the ai environment (YOLO11-OBB: DOTA model for aircraft and helicopters,
the trained tank model for armoured vehicles, tiled inference + rotated NMS of detecttank/common.py).
Same layout as the trajectory dialogs: options on the left; result images / table / log on the right.
Results are added to the map with their images: georeferenced images (GeoTIFF) in place, plain photos
(JPG/PNG) in pixel coordinates (one sub-group per image).
"""

import csv
import json
import os

from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRendererCategory,
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
from vgeoint.app.dialogs.uav_trajectory import ImageView, ScrollInsteadOfWheel, _set_label
from vgeoint.common.paths import MODELS_DIR
from vgeoint.common.utils import get_icon, settings

SCRIPT = "objdetect/run_detect.py"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")
# class name -> (Vietnamese label, outline colour) ; colours of detecttank/common.py COLORS (BGR there)
CLASS_STYLE = {
    "armored_vehicle": ("Xe tăng/xe bọc thép", "#ff0000"),
    "aircraft": ("Máy bay", "#ffff00"),
    "helicopter": ("Trực thăng", "#00ffff"),
}


class ObjectDetectionDialog(QDialog):
    TARGET = "tank"  # "tank" | "aircraft"
    TITLE = ""
    ICON = ""
    CLASSES: tuple[str, ...] = ()

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self.settings_key = f"ObjectDetection/{self.TARGET}"
        self.s = self.load_settings()
        self.process: ScriptRunner | None = None
        self.result_files: list[tuple[str, str]] = []
        self.output_files: list[str] = []
        self._stopped = False
        self.setWindowTitle(self.TITLE)
        self.setWindowIcon(get_icon(self.ICON))
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1300, 800)
        self._build()
        if self.s["output_dir"] and os.path.isdir(self.s["output_dir"]):
            self.load_results()

    # BPluginInterface
    def name(self) -> str:
        return f"ObjectDetection_{self.TARGET}"

    def vn_name(self) -> str:
        return self.TITLE

    def get_icon(self):
        return get_icon(self.ICON)

    # ---------------------------------------------------------------- settings
    def defaults(self) -> dict:
        return {"source": "", "output_dir": "", "dota_weights": str(MODELS_DIR / "yolo11s-obb.pt"),
                "tank_weights": str(MODELS_DIR / "tank_obb_final.pt"), "conf": 0.25, "tile": 1024,
                "imgsz": 1024, "tank_imgsz": 1600, "device": "auto", "add_to_map": True}

    def load_settings(self) -> dict:
        s = self.defaults()
        try:
            s.update(json.loads(str(settings().value(self.settings_key, "") or "{}")))
        except ValueError:
            pass
        return s

    def save_settings(self, s: dict | None = None):
        settings().setValue(self.settings_key, json.dumps(s or self.current_settings(), ensure_ascii=False))

    # ---------------------------------------------------------------- UI
    def _build(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(splitter)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(400)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self._data_group())
        left_layout.addWidget(self._parameters_group())
        left_layout.addWidget(self._run_group())
        left_layout.addStretch()
        scroll.setWidget(left)
        splitter.addWidget(scroll)
        self._wheel_guard = ScrollInsteadOfWheel(scroll, self)
        for box in left.findChildren(QAbstractSpinBox) + left.findChildren(QComboBox):
            box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            box.installEventFilter(self._wheel_guard)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._images_tab(), "Ảnh kết quả")
        self.tabs.addTab(self._table_tab(), "Bảng đối tượng")
        self.tabs.addTab(self._log_tab(), "Nhật ký")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 880])

    def _path_edit(self, key: str) -> QLineEdit:
        return QLineEdit(str(self.s[key]), self)

    def _data_group(self) -> QGroupBox:
        group = QGroupBox("Dữ liệu", self)
        form = QFormLayout(group)
        self.edits = {key: self._path_edit(key) for key in ("source", "output_dir", "dota_weights", "tank_weights")}

        form.addRow(QLabel("Ảnh vệ tinh / UAV (một ảnh hoặc cả thư mục):", self))
        form.addRow(self.edits["source"])
        row = QHBoxLayout()
        for text, slot in (("Chọn ảnh...", self.browse_image), ("Chọn thư mục...", self.browse_folder),
                           ("Lớp đang chọn", self.use_current_layer)):
            button = QPushButton(text, self)
            button.clicked.connect(slot)
            row.addWidget(button)
        form.addRow(row)
        self.count_label = QLabel(self)
        self.count_label.setWordWrap(True)
        form.addRow(self.count_label)

        for key, label, folder in (("output_dir", "Thư mục kết quả:", True),
                                   ("dota_weights", "Model máy bay / trực thăng (DOTA, .pt):", False),
                                   ("tank_weights", "Model xe tăng (.pt):", False)):
            if key == "tank_weights" and self.TARGET != "tank":
                continue
            button = QToolButton(self)
            button.setText("...")
            button.clicked.connect(lambda _=False, k=key, f=folder: self.browse(k, f))
            line = QHBoxLayout()
            line.addWidget(self.edits[key], 1)
            line.addWidget(button)
            form.addRow(QLabel(label, self))
            form.addRow(line)
        self.edits["source"].textChanged.connect(self.count_images)
        self.count_images()
        return group

    def _parameters_group(self) -> QGroupBox:
        group = QGroupBox("Tham số", self)
        form = QFormLayout(group)
        self.conf_spin = QDoubleSpinBox(self)
        self.conf_spin.setRange(0.01, 0.95)
        self.conf_spin.setSingleStep(0.05)
        self.conf_spin.setValue(float(self.s["conf"]))
        self.conf_spin.setToolTip("Giảm nếu bị sót đối tượng, tăng nếu báo nhầm")
        form.addRow("Ngưỡng tin cậy", self.conf_spin)
        self.int_spins = {}
        for key, label, lo, hi, step, tip in (
            ("tile", "Kích thước ô cắt (px)", 256, 4096, 128, "Ảnh lớn (vệ tinh) được cắt thành các ô chồng lấp"),
            ("imgsz", "Cỡ ảnh vào model DOTA (px)", 320, 2048, 32, "Model máy bay / trực thăng"),
            ("tank_imgsz", "Cỡ ảnh vào model xe tăng (px)", 320, 3200, 32,
             "Phóng ảnh lên cho model xe tăng (xe trong ảnh thường nhỏ hơn dữ liệu huấn luyện)"),
        ):
            if key == "tank_imgsz" and self.TARGET != "tank":
                continue
            box = QSpinBox(self)
            box.setRange(lo, hi)
            box.setSingleStep(step)
            box.setValue(int(self.s[key]))
            box.setToolTip(tip)
            self.int_spins[key] = box
            form.addRow(label, box)
        self.device_combo = QComboBox(self)
        self.device_combo.addItems(["auto", "cuda:0", "cpu"])
        self.device_combo.setCurrentText(self.s["device"])
        form.addRow("Thiết bị", self.device_combo)
        return group

    def _run_group(self) -> QWidget:
        box = QWidget(self)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        self.run_btn = QPushButton(f"▶  Phát hiện {self.TITLE.split(': ')[-1].lower()}", self)
        self.run_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self.run_btn.clicked.connect(self.run)
        self.stop_btn = QPushButton("■  Dừng", self)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.status_label = QLabel("Sẵn sàng", self)
        self.status_label.setWordWrap(True)
        self.add_to_map_check = QCheckBox("Thêm kết quả lên bản đồ khi xong", self)
        self.add_to_map_check.setChecked(bool(self.s["add_to_map"]))
        for w in (self.run_btn, self.stop_btn, self.progress, self.status_label, self.add_to_map_check):
            layout.addWidget(w)
        for text, slot in (("Thêm kết quả lên bản đồ", self.add_results_to_map),
                           ("Mở thư mục kết quả", self.open_output)):
            button = QPushButton(text, self)
            button.clicked.connect(lambda _=False, f=slot: f())
            layout.addWidget(button)
        return box

    def _images_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QHBoxLayout(tab)
        self.image_list = QListWidget(self)
        self.image_list.setFixedWidth(240)
        self.image_list.currentRowChanged.connect(self.on_select_image)
        layout.addWidget(self.image_list)
        self.viewer = ImageView(self)
        layout.addWidget(self.viewer, 1)
        return tab

    def _table_tab(self) -> QWidget:
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Ảnh", "Loại", "Độ tin cậy", "Tâm (x, y)"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSortingEnabled(True)
        return self.table

    def _log_tab(self) -> QWidget:
        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet("background: #111; color: #ddd; font-family: Consolas; font-size: 9pt;")
        return self.log_edit

    # ---------------------------------------------------------------- helpers
    def source_files(self) -> list[str]:
        src = self.edits["source"].text().strip()
        if os.path.isdir(src):
            return [os.path.join(src, f) for f in sorted(os.listdir(src)) if f.lower().endswith(IMAGE_EXTS)]
        return [src] if os.path.isfile(src) and src.lower().endswith(IMAGE_EXTS) else []

    def count_images(self, *_):
        n = len(self.source_files())
        if not self.edits["source"].text().strip():
            self.count_label.setText("")
        else:
            color = "#2a7" if n else "#c33"
            self.count_label.setText(f"<font color='{color}'>→ {n} ảnh</font>")

    def _start_dir(self, key: str) -> str:
        current = self.edits[key].text()
        return current if os.path.isdir(current) else os.path.dirname(current)

    def _set_source(self, path: str):
        path = os.path.normpath(path)
        self.edits["source"].setText(path)
        if not self.edits["output_dir"].text():
            base = path if os.path.isdir(path) else os.path.splitext(path)[0]
            self.edits["output_dir"].setText(base + f"_{self.TARGET}")

    def browse_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh", self._start_dir("source"),
                                              "Ảnh (*.tif *.tiff *.jpg *.jpeg *.png *.bmp)")
        if path:
            self._set_source(path)

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục ảnh", self._start_dir("source"))
        if path:
            self._set_source(path)

    def use_current_layer(self):
        layer = self.layer_tree_view.currentLayer() if self.layer_tree_view is not None else None
        path = layer.source().split("|")[0] if isinstance(layer, QgsRasterLayer) else ""
        if not os.path.isfile(path):
            QMessageBox.information(self, "Thông báo", "Hãy chọn một lớp ảnh (raster) từ file trong bảng Layers.")
            return
        self._set_source(path)

    def browse(self, key: str, folder: bool):
        if folder:
            path = QFileDialog.getExistingDirectory(self, "Chọn thư mục", self._start_dir(key))
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Chọn model", self._start_dir(key), "YOLO (*.pt);;All (*.*)")
        if path:
            self.edits[key].setText(os.path.normpath(path))

    def current_settings(self) -> dict:
        s = dict(self.s)
        s.update({key: edit.text().strip() for key, edit in self.edits.items()})
        s.update({key: box.value() for key, box in self.int_spins.items()})
        s["conf"] = self.conf_spin.value()
        s["device"] = self.device_combo.currentText()
        s["add_to_map"] = self.add_to_map_check.isChecked()
        return s

    def arguments(self, s: dict) -> list[str]:
        args = ["--source", s["source"], "--output-dir", s["output_dir"], "--target", self.TARGET,
                "--dota-weights", s["dota_weights"], "--conf", str(s["conf"]), "--tile", str(s["tile"]),
                "--imgsz", str(s["imgsz"]), "--device", s["device"]]
        if self.TARGET == "tank":
            args += ["--tank-weights", s["tank_weights"], "--tank-imgsz", str(s["tank_imgsz"])]
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
        if not self.source_files():
            problem = "Chưa chọn ảnh hoặc thư mục ảnh hợp lệ."
        elif not s["output_dir"]:
            problem = "Chưa chọn thư mục kết quả."
        elif not os.path.isfile(s["dota_weights"]):
            problem = f"Không tìm thấy model DOTA:\n{s['dota_weights']}"
        elif self.TARGET == "tank" and not os.path.isfile(s["tank_weights"]):
            problem = f"Không tìm thấy model xe tăng:\n{s['tank_weights']}"
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
        self.set_running(True, "Đang phát hiện...")
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
            if line.startswith("Ảnh ") and ":" in line:
                self.status_label.setText(line.split(":")[0])

    def _on_event(self, event: dict):
        if event.get("type") == "progress":
            self.progress.setValue(int(event.get("value", 0)))
        elif event.get("type") == "result" and isinstance(event.get("counts"), dict):
            self._counts = event["counts"]

    def on_done(self, code: int, crashed: bool):
        if code == 0 and not crashed:
            self.progress.setValue(100)
            counts = getattr(self, "_counts", {})
            summary = ", ".join(f"{v} {CLASS_STYLE[k][0].lower()}" for k, v in counts.items() if k in CLASS_STYLE)
            self.set_running(False, "Hoàn thành ✔" + (f": {summary}" if summary else ""))
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

    def detections_shapefile(self) -> str:
        path = os.path.join(self.output_dir(), "shapefile", "detections.shp")
        return path if os.path.isfile(path) else ""

    def load_results(self):
        out = self.output_dir()
        files = [(f[:-8], os.path.join(out, f)) for f in sorted(os.listdir(out)) if f.endswith("_det.jpg")] \
            if os.path.isdir(out) else []
        self.result_files = files
        self.image_list.clear()
        self.image_list.addItems([name for name, _ in files])
        if files:
            self.image_list.setCurrentRow(0)
        table = self.table
        table.setSortingEnabled(False)
        table.setRowCount(0)
        path = os.path.join(out, "detections.csv")
        if os.path.isfile(path):
            with open(path, encoding="utf-8-sig") as f:
                for rec in csv.DictReader(f):
                    if rec.get("class") not in self.CLASSES:
                        continue
                    row = table.rowCount()
                    table.insertRow(row)
                    values = [rec["image"], CLASS_STYLE[rec["class"]][0], float(rec["conf"]),
                              f"{float(rec['cx']):.0f}, {float(rec['cy']):.0f}"]
                    for col, value in enumerate(values):
                        item = QTableWidgetItem()
                        item.setData(Qt.ItemDataRole.DisplayRole, value)
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        table.setItem(row, col, item)
        table.setSortingEnabled(True)

    def on_select_image(self, row: int):
        if 0 <= row < len(self.result_files):
            self.viewer.show_image(self.result_files[row][1])

    def open_output(self):
        if os.path.isdir(self.output_dir()):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir()))
        else:
            QMessageBox.information(self, "Thông báo", "Thư mục kết quả chưa tồn tại.")

    def style_boxes(self, layer: QgsVectorLayer):
        """Outline per class, label "<loại> <độ tin cậy>"."""
        categories = [QgsRendererCategory(name, QgsFillSymbol.createSimple(
            {"color": "0,0,0,0", "style": "no", "outline_color": color, "outline_width": "0.6"}), label)
            for name, (label, color) in CLASS_STYLE.items() if name in self.CLASSES]
        layer.setRenderer(QgsCategorizedSymbolRenderer("class", categories))
        _set_label(layer, "\"loai\" || ' ' || format_number(\"conf\", 2)", Qgis.LabelPlacement.OverPoint)

    def pixel_results(self) -> list[tuple[str, QgsRasterLayer, QgsVectorLayer]]:
        """(name, image, boxes) of the images without georeferencing, in pixel coordinates.

        QGIS places such an image at x = column, y = -row with no CRS (GDAL then complains when drawing):
        a VRT next to the results gives it that same frame with a CRS (EPSG:3857 metres = pixels), and the
        boxes of detections.csv are drawn as (x, -y) in it. The images themselves are not modified.
        """
        from osgeo import gdal

        rows: dict[str, list[dict]] = {}
        path = os.path.join(self.output_dir(), "detections.csv")
        if os.path.isfile(path):
            with open(path, encoding="utf-8-sig") as f:
                for rec in csv.DictReader(f):
                    if rec.get("class") in self.CLASSES and not rec.get("map_x"):
                        rows.setdefault(rec["image"], []).append(rec)
        by_name = {os.path.basename(p): p for p in self.source_files()}
        vrt_dir = os.path.join(self.output_dir(), "pixel")
        results = []
        for name, path in by_name.items():
            ds = gdal.Open(path)
            if ds is None or ds.GetGeoTransform(can_return_null=True) is not None or ds.GetProjection():
                continue  # unreadable, or georeferenced (those come with the shapefile)
            os.makedirs(vrt_dir, exist_ok=True)
            vrt = os.path.join(vrt_dir, os.path.splitext(name)[0] + ".vrt")
            gdal.Translate(vrt, ds, format="VRT", outputSRS="EPSG:3857",
                           outputBounds=[0, 0, ds.RasterXSize, -ds.RasterYSize])
            ds = None
            stem = os.path.splitext(name)[0]
            raster = QgsRasterLayer(vrt, stem, "gdal")
            boxes = QgsVectorLayer("Polygon?crs=EPSG:3857&field=image:string&field=class:string&field=loai:string"
                                   "&field=conf:double", self.TITLE.split(": ")[-1], "memory")
            features = []
            for rec in rows.get(name, []):
                ring = [QgsPointXY(float(rec[f"x{i}"]), -float(rec[f"y{i}"])) for i in range(1, 5)]
                feature = QgsFeature(boxes.fields())
                feature.setGeometry(QgsGeometry.fromPolygonXY([ring + [ring[0]]]))
                feature.setAttributes([name, rec["class"], CLASS_STYLE[rec["class"]][0], float(rec["conf"])])
                features.append(feature)
            boxes.dataProvider().addFeatures(features)
            boxes.updateExtents()
            self.style_boxes(boxes)
            results.append((stem, raster, boxes))
        return results

    def add_results_to_map(self) -> int:
        """Detected boxes over their images: georeferenced ones in place, the others in pixel coordinates."""
        path = self.detections_shapefile()
        layer = QgsVectorLayer(path, self.TITLE.split(": ")[-1], "ogr") if path else None
        pixel = self.pixel_results()
        if (layer is None or not layer.isValid()) and not pixel:
            QMessageBox.information(self, "Thông báo", "Chưa có kết quả. Hãy chạy phát hiện trước.")
            return 0

        project = QgsProject.instance()
        group = project.layerTreeRoot().insertGroup(0, f"{self.TITLE} - {os.path.basename(self.output_dir())}")
        added, focus = [], None
        if layer is not None and layer.isValid():
            self.style_boxes(layer)
            images = [QgsRasterLayer(p, os.path.splitext(os.path.basename(p))[0], "gdal") for p in self.source_files()]
            images = [im for im in images if im.isValid() and im.crs().isValid()]
            project.addMapLayer(layer, False)
            group.addLayer(layer)
            for image in images:
                project.addMapLayer(image, False)
                group.addLayer(image).setExpanded(False)
            added += [layer, *images]
            focus = layer if layer.featureCount() else None
        # Images without coordinates: one sub-group each (boxes + image); only one is shown (they all sit
        # at the same pixel coordinates): the first one with detections
        shown = next((i for i, (_, _, boxes) in enumerate(pixel) if boxes.featureCount()), 0)
        for i, (stem, raster, boxes) in enumerate(pixel):
            sub = group.addGroup(f"{stem} (ảnh không có toạ độ, hiển thị theo pixel)")
            sub.setItemVisibilityChecked(i == shown and focus is None)
            sub.setExpanded(i == shown)
            for item in (boxes, raster):
                project.addMapLayer(item, False)
                sub.addLayer(item).setExpanded(False)
            added += [boxes, raster]
            if i == shown and focus is None:
                focus = raster
        self.output_files = [item.source() for item in added]
        if self.map_canvas is not None and focus is not None:
            box = QgsCoordinateTransform(focus.crs(), self.map_canvas.mapSettings().destinationCrs(),
                                         project).transformBoundingBox(focus.extent())
            self.map_canvas.setExtent(box.buffered(max(box.width(), box.height()) * 0.05))
            self.map_canvas.refresh()
        return len(added)

    def done(self, result: int):
        if self.process is not None and self.process.is_running():
            if QMessageBox.question(self, "Thoát", "Đang chạy. Dừng và thoát?") != QMessageBox.StandardButton.Yes:
                return
            self.process.finished.disconnect()
            self.process.kill()
        self.save_settings()
        super().done(result)


class TankObjectDialog(ObjectDetectionDialog):
    TARGET = "tank"
    TITLE = "Phát hiện đối tượng: Xe tăng"
    ICON = "Engine/Tank.svg"
    CLASSES = ("armored_vehicle",)


class AircraftObjectDialog(ObjectDetectionDialog):
    TARGET = "aircraft"
    TITLE = "Phát hiện đối tượng: Máy bay"
    ICON = "Engine/Airplane.svg"
    CLASSES = ("aircraft", "helicopter")
