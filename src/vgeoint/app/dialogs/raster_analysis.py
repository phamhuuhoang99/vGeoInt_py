"""Tăng cường ảnh (contrast enhancement written to a new image) and PCA. Not in the C++ app.

Both read the whole raster of a file-based layer with GDAL, keep its georeferencing, mask nodata, and
follow the processing dialogs' contract (complete signal, auto_add_output_files, output_files) so that
MainController opens the result on the map.

Enhancement (one 8-bit output band per selected band, 0 = nodata):
  min-max, percent clip, mean ± k·std, histogram equalisation, CLAHE, gamma, logarithm.
PCA: covariance (or correlation) of the selected bands on the valid pixels, components sorted by
eigenvalue; float32 PC bands + a CSV of eigenvalues, % variance and loadings.
"""

import csv
import os

import cv2
import numpy as np
from osgeo import gdal
from qgis.core import QgsRasterLayer
from qgis.PyQt.QtCore import QCoreApplication, QFileInfo, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
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
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
)

from vgeoint.app.dialogs._feedback import notify_failure, notify_success
from vgeoint.app.dialogs.image_filter import canvas_raster_layers, populate_raster_combo
from vgeoint.app.plugins import RASTER
from vgeoint.common.utils import get_icon, settings

PCA_NODATA = -9999.0


# ----------------------------------------------------------------- computations (no Qt)
def read_bands(path: str, bands: list[int]):
    """float64 arrays of `bands` (1-based), a valid-pixel mask, and the dataset (for georeferencing)."""
    ds = gdal.Open(path)
    if ds is None:
        raise RuntimeError(f"Không mở được ảnh: {path}")
    arrays, valid = [], np.ones((ds.RasterYSize, ds.RasterXSize), bool)
    for b in bands:
        band = ds.GetRasterBand(b)
        a = band.ReadAsArray().astype(np.float64)
        nodata = band.GetNoDataValue()
        if nodata is not None:
            valid &= a != nodata
        valid &= np.isfinite(a)
        arrays.append(a)
    return arrays, valid, ds


def write_like(ds, path: str, arrays: list[np.ndarray], gdal_type, nodata=None, names=None):
    out = gdal.GetDriverByName("GTiff").Create(path, ds.RasterXSize, ds.RasterYSize, len(arrays), gdal_type,
                                               options=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"])
    if out is None:
        raise RuntimeError(f"Không ghi được file {path}")
    out.SetGeoTransform(ds.GetGeoTransform())
    out.SetProjection(ds.GetProjection())
    for i, a in enumerate(arrays, 1):
        band = out.GetRasterBand(i)
        band.WriteArray(a)
        if nodata is not None:
            band.SetNoDataValue(nodata)
        if names:
            band.SetDescription(names[i - 1])
    out.FlushCache()


def _scale(a: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return np.clip((a - lo) / max(hi - lo, 1e-12), 0.0, 1.0)


def enhance(a: np.ndarray, valid: np.ndarray, method: str, params: dict) -> np.ndarray:
    """One band -> uint8 (1-255 on valid pixels, 0 = nodata)."""
    v = a[valid]
    if v.size == 0:
        return np.zeros(a.shape, np.uint8)
    lo, hi = float(v.min()), float(v.max())
    if method == "minmax":
        n = _scale(a, lo, hi)
    elif method == "percent":
        n = _scale(a, *np.percentile(v, [params["low"], params["high"]]))
    elif method == "stddev":
        m, s = float(v.mean()), float(v.std())
        n = _scale(a, m - params["k"] * s, m + params["k"] * s)
    elif method == "equalize":
        hist, edges = np.histogram(v, bins=4096, range=(lo, hi if hi > lo else lo + 1))
        cdf = np.cumsum(hist).astype(np.float64)
        cdf = (cdf - cdf[0]) / max(cdf[-1] - cdf[0], 1)
        n = np.interp(a, edges[1:], cdf)
    elif method == "clahe":
        u16 = np.round(_scale(a, lo, hi) * 65535).astype(np.uint16)
        clahe = cv2.createCLAHE(clipLimit=params["clip"], tileGridSize=(params["tiles"], params["tiles"]))
        n = clahe.apply(u16).astype(np.float64) / 65535.0
    elif method == "gamma":
        n = _scale(a, lo, hi) ** params["gamma"]
    elif method == "log":
        n = np.log1p(np.clip(a - lo, 0, None)) / np.log1p(max(hi - lo, 1e-12))
    else:
        raise ValueError(method)
    out = np.round(1 + n * 254).astype(np.uint8)  # 0 is kept for nodata
    out[~valid] = 0
    return out


def pca(arrays: list[np.ndarray], valid: np.ndarray, n_components: int, standardize: bool = False,
        sample: int = 2_000_000):
    """(components [n_components arrays, float32, nodata outside valid], eigenvalues, loadings [k x bands]).

    Statistics come from at most `sample` valid pixels (evenly spaced), the projection uses all of them.
    """
    x = np.stack([a[valid] for a in arrays], axis=1)  # pixels x bands
    if x.shape[0] < len(arrays) + 1:
        raise RuntimeError("Không đủ điểm ảnh hợp lệ để tính PCA")
    stats = x[:: max(1, x.shape[0] // sample)]
    mean = stats.mean(axis=0)
    std = stats.std(axis=0)
    std[std == 0] = 1.0
    z = (stats - mean) / std if standardize else stats - mean
    cov = np.cov(z, rowvar=False)
    values, vectors = np.linalg.eigh(np.atleast_2d(cov))
    order = np.argsort(values)[::-1]
    values, vectors = values[order], vectors[:, order]
    # sign convention: largest loading of each component positive (results do not flip between runs)
    vectors *= np.where(vectors[np.abs(vectors).argmax(axis=0), range(vectors.shape[1])] < 0, -1, 1)
    xc = (x - mean) / std if standardize else x - mean
    scores = xc @ vectors[:, :n_components]
    components = []
    for k in range(n_components):
        c = np.full(valid.shape, PCA_NODATA, np.float32)
        c[valid] = scores[:, k]
        components.append(c)
    return components, values, vectors.T


# ----------------------------------------------------------------- dialogs
class _RasterToolDialog(QDialog):
    """Layer + bands + output file + run, shared by the two dialogs."""

    complete = pyqtSignal()
    TITLE = ""
    ICON = "Raster.svg"
    SETTINGS = ""
    SUFFIX = ""

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent)
        self.map_canvas = map_canvas
        self.layer_tree_view = layer_tree_view
        self._output_files: list[str] = []
        self.setWindowTitle(self.TITLE)
        self.setWindowIcon(get_icon(self.ICON))
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)

        source = QGroupBox("Ảnh đầu vào", self)
        form = QFormLayout(source)
        self.layer_combo = QComboBox(self)
        form.addRow("Lớp ảnh:", self.layer_combo)
        self.band_list = QListWidget(self)
        self.band_list.setMaximumHeight(130)
        form.addRow("Kênh:", self.band_list)
        layout.addWidget(source)

        self.options = QGroupBox("Tham số", self)
        self.options_form = QFormLayout(self.options)
        layout.addWidget(self.options)
        self.build_options(self.options_form)

        out = QGroupBox("Kết quả", self)
        out_layout = QVBoxLayout(out)
        row = QHBoxLayout()
        self.output_edit = QLineEdit(self)
        browse = QToolButton(self)
        browse.setText("...")
        browse.clicked.connect(self._browse)
        row.addWidget(QLabel("File:", self))
        row.addWidget(self.output_edit, 1)
        row.addWidget(browse)
        out_layout.addLayout(row)
        self.auto_add_check = QCheckBox("Tự động mở ảnh kết quả khi hoàn thành", self)
        self.auto_add_check.setChecked(True)
        out_layout.addWidget(self.auto_add_check)
        layout.addWidget(out)
        self.build_results(layout)

        self.progress = QProgressBar(self)
        self.progress.hide()
        self.notice = QLabel(self)
        self.notice.setWordWrap(True)
        buttons = QHBoxLayout()
        self.run_btn = QPushButton("Đồng ý", self)
        self.run_btn.setDefault(True)
        close = QPushButton("Đóng", self)
        close.clicked.connect(self.close)
        self.run_btn.clicked.connect(self.apply)
        buttons.addWidget(self.notice, 1)
        buttons.addWidget(self.run_btn)
        buttons.addWidget(close)
        layout.addWidget(self.progress)
        layout.addLayout(buttons)

        self._layers = [l for l in canvas_raster_layers(map_canvas) if os.path.isfile(l.source().split("|")[0])] \
            if map_canvas is not None else []
        populate_raster_combo(self.layer_combo, self._layers, layer_tree_view)
        self.layer_combo.currentIndexChanged.connect(self._layer_changed)
        self._layer_changed()

    # BPluginInterface
    def name(self) -> str:
        return type(self).__name__

    def vn_name(self) -> str:
        return self.TITLE

    def get_icon(self):
        return get_icon(self.ICON)

    def auto_add_output_files(self) -> bool:
        return self.auto_add_check.isChecked()

    def output_files(self) -> list[str]:
        return list(self._output_files)

    def output_data_type(self) -> int:
        return RASTER

    # hooks
    def build_options(self, form: QFormLayout):
        pass

    def build_results(self, layout: QVBoxLayout):
        pass

    def process(self, path: str, bands: list[int], output: str) -> str:
        """Run; return the success message (raise on failure)."""
        raise NotImplementedError

    # helpers
    def layer(self) -> QgsRasterLayer | None:
        return self.layer_combo.currentData()

    def selected_bands(self) -> list[int]:
        return [self.band_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.band_list.count())
                if self.band_list.item(i).checkState() == Qt.CheckState.Checked]

    def _layer_changed(self, *_):
        self.band_list.clear()
        layer = self.layer()
        if layer is None:
            return
        for b in range(1, layer.bandCount() + 1):
            name = layer.bandName(b)
            item = QListWidgetItem(name if name else f"Kênh {b}")
            item.setData(Qt.ItemDataRole.UserRole, b)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.band_list.addItem(item)
        base = os.path.splitext(layer.source().split("|")[0])[0]
        self.output_edit.setText(f"{base}_{self.SUFFIX}.tif")
        self.layer_bands_changed()

    def layer_bands_changed(self):
        pass

    def _browse(self):
        s = settings()
        directory = s.value("SaveImage/Dir", QCoreApplication.applicationDirPath())
        file_name, _ = QFileDialog.getSaveFileName(self, "Lưu ảnh kết quả", directory, "GeoTIFF (*.tif *.tiff)")
        if file_name:
            self.output_edit.setText(file_name)
            s.setValue("SaveImage/Dir", QFileInfo(file_name).dir().path())

    def _fail(self, reason: str) -> bool:
        self.notice.setText(f"<font color='red'>Thất bại: {reason}</font>")
        notify_failure(self.TITLE, f"Thất bại: {reason}")
        return False

    def apply(self) -> bool:
        layer, bands, output = self.layer(), self.selected_bands(), self.output_edit.text().strip()
        if layer is None:
            return self._fail("Chưa có lớp ảnh (raster từ file) trên bản đồ")
        if not bands:
            return self._fail("Chưa chọn kênh nào")
        if not output:
            return self._fail("Chưa chọn file lưu kết quả")
        folder = os.path.dirname(os.path.abspath(output))
        if not os.path.isdir(folder):
            return self._fail(f"Thư mục lưu kết quả không tồn tại: {folder}")
        self.progress.show()
        self.progress.setRange(0, 0)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            message = self.process(layer.source().split("|")[0], bands, output)
        except (RuntimeError, ValueError, MemoryError, cv2.error, np.linalg.LinAlgError) as e:
            return self._fail(str(e))
        finally:
            QApplication.restoreOverrideCursor()
            self.progress.hide()
        self._output_files = [output]
        self.notice.setText(f"<font color='green'>{message}</font>")
        notify_success(self.TITLE, message, output)
        QApplication.beep()
        self.complete.emit()
        return True


ENHANCEMENTS = [
    ("percent", "Giãn theo phần trăm (cắt hai đầu histogram)"),
    ("minmax", "Giãn tuyến tính min–max"),
    ("stddev", "Giãn theo độ lệch chuẩn (trung bình ± k·σ)"),
    ("equalize", "Cân bằng histogram"),
    ("clahe", "Cân bằng histogram thích nghi (CLAHE)"),
    ("gamma", "Hiệu chỉnh gamma"),
    ("log", "Biến đổi logarit (làm rõ vùng tối)"),
]


class ImageEnhancementDialog(_RasterToolDialog):
    TITLE = "Tăng cường ảnh"
    ICON = "BrightnessContrast.svg"
    SUFFIX = "tangcuong"

    def build_options(self, form):
        self.method_combo = QComboBox(self)
        for key, label in ENHANCEMENTS:
            self.method_combo.addItem(label, key)
        form.addRow("Phương pháp:", self.method_combo)

        def dspin(lo, hi, step, value, decimals=1):
            box = QDoubleSpinBox(self)
            box.setRange(lo, hi)
            box.setSingleStep(step)
            box.setDecimals(decimals)
            box.setValue(value)
            return box

        self.params = {
            "low": dspin(0, 49, 0.5, 2.0), "high": dspin(51, 100, 0.5, 98.0), "k": dspin(0.5, 5, 0.5, 2.0),
            "clip": dspin(0.5, 20, 0.5, 2.0), "gamma": dspin(0.1, 5, 0.1, 0.7, 2),
        }
        self.tiles_spin = QSpinBox(self)
        self.tiles_spin.setRange(2, 32)
        self.tiles_spin.setValue(8)
        rows = [("low", "Cắt dưới (%):"), ("high", "Cắt trên (%):"), ("k", "Hệ số k:"),
                ("clip", "Giới hạn tương phản:"), ("gamma", "Gamma (< 1 làm sáng, > 1 làm tối):")]
        self._rows = {}
        for key, label in rows:
            form.addRow(label, self.params[key])
            self._rows[key] = self.params[key]
        form.addRow("Số ô (CLAHE):", self.tiles_spin)
        self._rows["tiles"] = self.tiles_spin
        self.method_combo.currentIndexChanged.connect(self._method_changed)
        self._method_changed()

    def _method_changed(self, *_):
        used = {"percent": {"low", "high"}, "stddev": {"k"}, "clahe": {"clip", "tiles"},
                "gamma": {"gamma"}}.get(self.method_combo.currentData(), set())
        form = self.options_form
        for key, widget in self._rows.items():
            widget.setVisible(key in used)
            label = form.labelForField(widget)
            if label is not None:
                label.setVisible(key in used)

    def parameters(self) -> dict:
        p = {k: w.value() for k, w in self.params.items()}
        p["tiles"] = self.tiles_spin.value()
        return p

    def process(self, path, bands, output):
        method = self.method_combo.currentData()
        arrays, valid, ds = read_bands(path, bands)
        out = [enhance(a, valid, method, self.parameters()) for a in arrays]
        write_like(ds, output, out, gdal.GDT_Byte, nodata=0,
                   names=[f"Kênh {b} ({method})" for b in bands])
        return f"Đã tăng cường {len(bands)} kênh ({self.method_combo.currentText().split(' (')[0].lower()})"


class PcaDialog(_RasterToolDialog):
    TITLE = "Phân tích thành phần chính (PCA)"
    ICON = "Band.svg"
    SUFFIX = "pca"

    def build_options(self, form):
        self.components_spin = QSpinBox(self)
        self.components_spin.setRange(1, 1)
        form.addRow("Số thành phần (PC) xuất ra:", self.components_spin)
        self.standardize_check = QCheckBox("Chuẩn hoá các kênh (PCA trên ma trận tương quan)", self)
        self.standardize_check.setToolTip("Nên bật khi các kênh có đơn vị / thang giá trị khác nhau")
        form.addRow(self.standardize_check)
        self.band_list_changed_connected = False

    def build_results(self, layout):
        box = QGroupBox("Thống kê (sau khi chạy)", self)
        v = QVBoxLayout(box)
        self.stats_table = QTableWidget(0, 4, self)
        self.stats_table.setHorizontalHeaderLabels(["Thành phần", "Trị riêng", "% phương sai", "% tích luỹ"])
        self.stats_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.stats_table.verticalHeader().hide()
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stats_table.setMaximumHeight(170)
        v.addWidget(self.stats_table)
        layout.addWidget(box)

    def layer_bands_changed(self):
        if not self.band_list_changed_connected:
            self.band_list.itemChanged.connect(lambda *_: self._update_components())
            self.band_list_changed_connected = True
        self._update_components()

    def _update_components(self):
        n = max(1, len(self.selected_bands()))
        self.components_spin.setRange(1, n)
        self.components_spin.setValue(n)

    def process(self, path, bands, output):
        if len(bands) < 2:
            raise ValueError("PCA cần ít nhất 2 kênh")
        arrays, valid, ds = read_bands(path, bands)
        k = self.components_spin.value()
        components, values, loadings = pca(arrays, valid, k, self.standardize_check.isChecked())
        write_like(ds, output, components, gdal.GDT_Float32, nodata=PCA_NODATA,
                   names=[f"PC{i}" for i in range(1, k + 1)])
        total = float(values.sum()) or 1.0
        stats_path = os.path.splitext(output)[0] + "_thongke.csv"
        with open(stats_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["thanh_phan", "tri_rieng", "phan_tram_phuong_sai", "phan_tram_tich_luy",
                        *[f"he_so_kenh_{b}" for b in bands]])
            cumulative = 0.0
            self.stats_table.setRowCount(0)
            for i, (value, vector) in enumerate(zip(values, loadings), 1):
                share = 100 * value / total
                cumulative += share
                w.writerow([f"PC{i}", f"{value:.6g}", f"{share:.3f}", f"{cumulative:.3f}",
                            *[f"{c:.6f}" for c in vector]])
                row = self.stats_table.rowCount()
                self.stats_table.insertRow(row)
                for col, text in enumerate([f"PC{i}", f"{value:.4g}", f"{share:.2f}", f"{cumulative:.2f}"]):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.stats_table.setItem(row, col, item)
        self.stats_path = stats_path
        return (f"PCA xong: {k} thành phần, PC1 giữ {100 * values[0] / total:.1f}% phương sai "
                f"(thống kê: {os.path.basename(stats_path)})")
