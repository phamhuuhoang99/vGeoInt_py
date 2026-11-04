"""Tăng cường ảnh and PCA (not in the C++ app)."""

import csv

import numpy as np
import pytest
from osgeo import gdal

from tests.conftest import make_raster


# ----------------------------------------------------------------- computations
@pytest.fixture
def ramp():
    a = np.tile(np.arange(100, dtype=np.float64), (10, 1))  # 0..99 on every row
    valid = np.ones(a.shape, bool)
    valid[0, 0] = False  # one nodata pixel
    return a, valid


def test_enhance_methods(ramp):
    from vgeoint.app.dialogs.raster_analysis import enhance

    a, valid = ramp
    p = {"low": 10.0, "high": 90.0, "k": 1.0, "clip": 2.0, "tiles": 4, "gamma": 0.5}
    out = {m: enhance(a, valid, m, p) for m in ("minmax", "percent", "stddev", "equalize", "clahe", "gamma", "log")}
    for m, o in out.items():
        assert o.dtype == np.uint8 and o[0, 0] == 0, m  # nodata stays 0
        assert o[valid].min() >= 1 and o[valid].max() <= 255, m
        if m != "clahe":  # CLAHE equalises tile by tile: not monotonic over the whole image by design
            assert np.all(np.diff(o[5].astype(int)) >= 0), m
    assert out["minmax"][5, 1] == 4 and out["minmax"][5, 99] == 255  # 1 + 254 * v/99
    pct = out["percent"][5]  # 10 % / 90 % of 1..99 -> saturated beyond
    assert pct[5] == 1 and pct[95] == 255 and 1 < pct[50] < 255
    sd = out["stddev"][5]  # mean 49.5, std 28.9: k = 1 -> clipped outside [20.6, 78.4]
    assert sd[10] == 1 and sd[90] == 255
    assert abs(int(out["equalize"][5, 50]) - 128) <= 3  # uniform values: equalisation ~ linear
    assert out["gamma"][5, 25] > out["minmax"][5, 25]  # gamma 0.5 brightens the dark half
    assert out["log"][5, 10] > out["minmax"][5, 10]  # log lifts the low values


def test_pca_recovers_the_structure():
    from vgeoint.app.dialogs.raster_analysis import PCA_NODATA, pca

    rng = np.random.default_rng(0)
    signal = rng.normal(0, 10, (60, 80))
    noise = rng.normal(0, 1, (3, 60, 80))
    # three bands = the same signal (weights 1, 2, -1) + small noise: PC1 carries almost all the variance
    bands = [signal + noise[0], 2 * signal + noise[1], -signal + noise[2]]
    valid = np.ones(signal.shape, bool)
    valid[:, :5] = False
    components, values, loadings = pca(bands, valid, 2)
    assert len(components) == 2 and components[0].dtype == np.float32
    assert np.all(components[0][~valid] == PCA_NODATA)
    assert values[0] / values.sum() > 0.98 and np.all(np.diff(values) <= 0)
    w = loadings[0] / np.linalg.norm(loadings[0])
    np.testing.assert_allclose(np.abs(w), np.abs(np.array([1, 2, -1]) / np.sqrt(6)), atol=0.01)
    pc1, pc2 = components[0][valid], components[1][valid]
    assert abs(np.corrcoef(pc1, pc2)[0, 1]) < 1e-6  # components are uncorrelated
    assert abs(np.var(pc1) / values[0] - 1) < 0.01
    # same signs on another run (largest loading positive)
    assert loadings[0][np.abs(loadings[0]).argmax()] > 0


# ----------------------------------------------------------------- dialogs
@pytest.fixture
def raster_window(window, tmp_path):
    path = make_raster(tmp_path / "anh.tif", bands=4)
    window.main_controller.add_raster(path)
    window.layer_tree_map_canvas_bridge.setCanvasLayers()
    return window, path, tmp_path


def _read(path):
    ds = gdal.Open(str(path))
    return ds.ReadAsArray(), ds.GetGeoTransform(), ds.GetProjection(), ds.GetRasterBand(1).DataType


def test_enhancement_dialog(raster_window):
    from vgeoint.app.dialogs.raster_analysis import ImageEnhancementDialog

    window, path, tmp_path = raster_window
    dlg = ImageEnhancementDialog(window, window.map_canvas, window.layer_tree_view)
    assert dlg.windowTitle() == "Tăng cường ảnh" and dlg.band_list.count() == 4
    assert dlg.output_edit.text().endswith("anh_tangcuong.tif")
    dlg.band_list.item(3).setCheckState(dlg.band_list.item(3).checkState().Unchecked)
    dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("clahe"))
    assert dlg.params["clip"].isVisibleTo(dlg) and not dlg.params["gamma"].isVisibleTo(dlg)
    out = tmp_path / "tc.tif"
    dlg.output_edit.setText(str(out))
    done = []
    dlg.complete.connect(lambda: done.append(True))
    assert dlg.apply() and done and dlg.output_files() == [str(out)]
    arr, gt, proj, dtype = _read(out)
    src, src_gt, _, _ = _read(path)
    assert arr.shape == (3, 48, 64) and dtype == gdal.GDT_Byte
    np.testing.assert_allclose(gt, src_gt)
    assert "32648" in proj or "UTM zone 48N" in proj
    assert window.message_bar.currentItem().text().startswith("Đã tăng cường 3 kênh")


def test_enhancement_dialog_failure_says_why(raster_window):
    from vgeoint.app.dialogs.raster_analysis import ImageEnhancementDialog

    window, _, tmp_path = raster_window
    dlg = ImageEnhancementDialog(window, window.map_canvas, window.layer_tree_view)
    dlg.output_edit.setText(str(tmp_path / "khong_co" / "x.tif"))
    assert not dlg.apply()
    assert "Thư mục lưu kết quả không tồn tại" in dlg.notice.text()


def test_pca_dialog(raster_window):
    from vgeoint.app.dialogs.raster_analysis import PcaDialog

    window, path, tmp_path = raster_window
    dlg = PcaDialog(window, window.map_canvas, window.layer_tree_view)
    assert dlg.components_spin.maximum() == 4 and dlg.components_spin.value() == 4
    dlg.band_list.item(0).setCheckState(dlg.band_list.item(0).checkState().Unchecked)
    assert dlg.components_spin.maximum() == 3
    dlg.components_spin.setValue(2)
    out = tmp_path / "pca.tif"
    dlg.output_edit.setText(str(out))
    assert dlg.apply()
    arr, gt, _, dtype = _read(out)
    assert arr.shape == (2, 48, 64) and dtype == gdal.GDT_Float32
    assert gdal.Open(str(out)).GetRasterBand(1).GetDescription() == "PC1"
    assert dlg.stats_table.rowCount() == 3  # all eigenvalues listed, 2 written
    with open(tmp_path / "pca_thongke.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert [r["thanh_phan"] for r in rows] == ["PC1", "PC2", "PC3"]
    assert abs(float(rows[-1]["phan_tram_tich_luy"]) - 100) < 1e-6
    assert list(rows[0])[-3:] == ["he_so_kenh_2", "he_so_kenh_3", "he_so_kenh_4"]


def test_pca_needs_two_bands(raster_window):
    from vgeoint.app.dialogs.raster_analysis import PcaDialog

    window, _, tmp_path = raster_window
    dlg = PcaDialog(window, window.map_canvas, window.layer_tree_view)
    for i in range(1, 4):
        dlg.band_list.item(i).setCheckState(dlg.band_list.item(i).checkState().Unchecked)
    dlg.output_edit.setText(str(tmp_path / "p.tif"))
    assert not dlg.apply() and "ít nhất 2 kênh" in dlg.notice.text()


def test_menu_items(window):
    tools = [a.text() for a in window.menu_bar_.tool_menu.actions()]
    i = tools.index("Chuyển đổi không gian màu")
    assert tools[i + 1:i + 3] == ["Tăng cường ảnh", "Phân tích thành phần chính (PCA)"]
