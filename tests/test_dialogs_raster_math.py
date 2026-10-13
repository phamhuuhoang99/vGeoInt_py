"""Tests for BandMathDialog and ChangeDetectionDialog."""

import numpy as np
import pytest
from osgeo import gdal

from tests.conftest import make_raster


def _read(path):
    ds = gdal.Open(str(path))
    arr = ds.ReadAsArray()
    gt = ds.GetGeoTransform()
    ds = None
    return arr, gt


def _band(path, band=1):
    ds = gdal.Open(str(path))
    arr = ds.GetRasterBand(band).ReadAsArray().astype(np.float64)
    ds = None
    return arr


@pytest.fixture
def two_rasters(window, tmp_path):
    a = make_raster(tmp_path / "a.tif", seed=1)
    b = make_raster(tmp_path / "b.tif", seed=2)
    window.main_controller.add_raster(a)
    window.main_controller.add_raster(b)
    return a, b


# ---------------------------------------------------------------- band math
def _band_math(window):
    from vgeoint.app.dialogs.band_math import BandMathDialog

    return BandMathDialog(window, window.map_canvas, window.layer_tree_view)


def test_band_math_lists_bands_and_builds_expression(two_rasters, window):
    dlg = _band_math(window)
    items = sorted(dlg.bandLswg.item(i).text() for i in range(dlg.bandLswg.count()))
    assert items == ["a@k1", "a@k2", "a@k3", "b@k1", "b@k2", "b@k3"]

    from qgis.PyQt.QtCore import Qt

    dlg.bandLswg.itemDoubleClicked.emit(dlg.bandLswg.findItems("a@k1", Qt.MatchFlag.MatchExactly)[0])
    dlg.mPlusPushButton.click()
    dlg.mSqrtButton.click()
    assert dlg.expressionTder.toPlainText() == '"a@k1" +  sqrt ( '
    dlg.checkExpressionBtn.click()
    assert "không hợp lệ" in dlg.noticeLbl.text() and "red" in dlg.noticeLbl.text()

    dlg.clearExpressionBtn.click()
    dlg.expressionTder.setPlainText('"a@k1" + 1')
    dlg.checkExpressionBtn.click()
    assert "Biểu thức hợp lệ" in dlg.noticeLbl.text() and "green" in dlg.noticeLbl.text()
    assert dlg.quote_band_entry('x"y') == '"x\\"y"'


def test_band_math_apply(two_rasters, window, tmp_path):
    a, b = two_rasters
    dlg = _band_math(window)
    out = tmp_path / "out.tif"
    dlg.outputLedr.setText(str(out))
    dlg.expressionTder.setPlainText('("a@k1" + "b@k2") * 2 - "a@k3"')
    dlg.autoAddOutputChbx.setChecked(True)
    completed = []
    dlg.complete.connect(lambda: completed.append(True))
    dlg.apply()

    assert completed and dlg.output_files == [str(out)]
    result, gt = _read(out)
    expected = (_band(a, 1) + _band(b, 2)) * 2 - _band(a, 3)
    # Output keeps the input pixel size (the C++ app used map units as pixel counts)
    assert result.shape == (48, 64)
    np.testing.assert_allclose(result, expected)
    assert gt[0] == 500000 and gt[3] == 2300000


def test_band_math_invalid_expression(two_rasters, window, tmp_path):
    dlg = _band_math(window)
    out = tmp_path / "bad.tif"
    dlg.outputLedr.setText(str(out))
    dlg.expressionTder.setPlainText('"a@k1" +')
    dlg.apply()
    assert "Biểu thức không hợp lệ" in dlg.noticeLbl.text()
    assert not out.exists()


def test_band_math_browse(window, tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog

    from vgeoint.common.utils import settings

    target = str(tmp_path / "sub" / "x.tif")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (target, ""))
    dlg = _band_math(window)
    dlg.browseBtn.click()
    assert dlg.outputLedr.text() == target
    assert settings().value("SaveImage/Dir") == str(tmp_path / "sub").replace("\\", "/")


# --------------------------------------------------------- change detection
def _change_detection(window):
    from vgeoint.app.dialogs.change_detection import ChangeDetectionDialog
    from vgeoint.common.utils import settings

    settings().remove("ChangeDetection")
    return ChangeDetectionDialog(window, window.map_canvas, window.layer_tree_view)


def _select(cbx, name):
    cbx.setCurrentIndex(cbx.findText(name))


def test_change_detection_apply(two_rasters, window, tmp_path):
    a, b = two_rasters
    dlg = _change_detection(window)
    assert sorted(dlg.beforeRasterLayerCbx.itemText(i) for i in range(dlg.beforeRasterLayerCbx.count())) == ["a", "b"]
    _select(dlg.beforeRasterLayerCbx, "a")
    _select(dlg.afterRasterLayerCbx, "b")
    out = tmp_path / "change.tif"
    dlg.outputLedr.setText(str(out))
    completed = []
    dlg.complete.connect(lambda: completed.append(True))
    dlg.apply()

    assert completed and dlg.output_files == [str(out)], dlg.noticeLbl.text()
    assert not (tmp_path / "change_math.tif").exists()
    assert not (tmp_path / "change_segm.tif").exists()

    diff = _band(b, 1) - _band(a, 1)
    step = (diff.max() - diff.min()) / 3.0
    t1 = float(f"{diff.min() + step:g}")
    t2 = float(f"{diff.min() + 2 * step:g}")
    seg = np.where(diff <= t1, 0, np.where(diff < t2, 127, 255))
    colors = {0: (200, 0, 0, 255), 127: (200, 200, 200, 0), 255: (0, 200, 0, 255)}
    expected = np.zeros((4,) + seg.shape, dtype=np.uint8)
    for value, rgba in colors.items():
        for i, c in enumerate(rgba):
            expected[i][seg == value] = c

    result, gt = _read(out)
    assert result.shape == (4, 48, 64)
    np.testing.assert_array_equal(result, expected)
    assert gt[0] == 500000 and gt[3] == 2300000


def test_change_detection_validation(two_rasters, window):
    dlg = _change_detection(window)
    _select(dlg.beforeRasterLayerCbx, "a")
    _select(dlg.afterRasterLayerCbx, "a")
    dlg.outputLedr.setText("x.tif")
    dlg.apply()
    assert "Ảnh trước và sau phải khác nhau" in dlg.noticeLbl.text()

    _select(dlg.afterRasterLayerCbx, "b")
    dlg.outputLedr.setText("  ")
    dlg.apply()
    assert "Chưa chọn lưu ảnh kết quả" in dlg.noticeLbl.text()


def test_change_detection_colors(window, monkeypatch):
    from qgis.PyQt.QtGui import QColor
    from qgis.PyQt.QtWidgets import QColorDialog

    from vgeoint.common.utils import settings

    dlg = _change_detection(window)
    assert dlg.spreadAlphaSbx.value() == 255 and dlg.nochangeAlphaSbx.value() == 0
    assert dlg.loss_color_label().getRgb() == (200, 0, 0, 255)

    dlg.lossAlphaSdr.setValue(100)
    assert dlg.lossAlphaSbx.value() == 100
    assert dlg.loss_color_label().getRgb() == (200, 0, 0, 100)
    assert int(settings().value("ChangeDetection/LossAlpha")) == 100

    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor(1, 2, 3))
    dlg.spreadColorPickerBtn.click()
    assert dlg.spread_color_label().getRgb() == (1, 2, 3, 255)
    assert int(settings().value("ChangeDetection/SpreadBlue")) == 3

    dlg.defaultBtn.click()
    assert dlg.spread_color_label().getRgb() == (0, 200, 0, 255)
    assert dlg.loss_color_label().getRgb() == (200, 0, 0, 255)
    # default only resets the labels, not the saved settings
    assert int(settings().value("ChangeDetection/SpreadBlue")) == 3

    dlg2 = _change_detection(window)
    assert dlg2.nochange_color_label().getRgb() == (200, 200, 200, 0)


def test_band_math_degree_raster(window, tmp_path):
    """Rasters in degrees used to give ~0 columns in the C++ app."""
    from osgeo import gdal, osr

    path = make_raster(tmp_path / "geo.tif", bands=1, seed=3)
    ds = gdal.Open(path, gdal.GA_Update)
    ds.SetGeoTransform((105.0, 0.001, 0, 21.0, 0, -0.001))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    ds = None
    window.main_controller.add_raster(path)

    dlg = _band_math(window)
    out = tmp_path / "geo_out.tif"
    dlg.outputLedr.setText(str(out))
    dlg.expressionTder.setPlainText('"geo@k1" * 2')
    dlg.apply()
    result, _gt = _read(out)
    np.testing.assert_allclose(result, _band(path, 1) * 2)


@pytest.mark.parametrize("auto_add", [True, False])
def test_auto_add_output_via_controller(two_rasters, window, tmp_path, auto_add):
    from qgis.core import QgsProject

    mw = window
    dlg = mw.main_controller._exec_dialog(
        "band_math", "BandMathDialog", mw, mw.map_canvas, mw.layer_tree_view, modal_exec=False
    )
    out = tmp_path / "auto.tif"
    dlg.outputLedr.setText(str(out))
    dlg.expressionTder.setPlainText('"a@k1" + 1')
    dlg.autoAddOutputChbx.setChecked(auto_add)
    dlg.apply()
    assert bool(QgsProject.instance().mapLayersByName("auto")) == auto_add
