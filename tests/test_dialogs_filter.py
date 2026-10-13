"""Tests for ImageFilterDialog (+ filter widgets) and ColorSpaceConvertionDialog."""

import cv2
import numpy as np
import pytest
from osgeo import gdal

from tests.conftest import make_raster


def _read(path):
    ds = gdal.Open(str(path))
    arr = ds.ReadAsArray()
    gt, proj = ds.GetGeoTransform(), ds.GetProjection()
    dtype = ds.GetRasterBand(1).DataType
    ds = None
    return arr, gt, proj, dtype


def _band(path, b):
    ds = gdal.Open(str(path))
    arr = ds.GetRasterBand(b).ReadAsArray()
    ds = None
    return arr


def _sync_canvas(window):
    # the layer tree -> canvas bridge updates canvas layers deferred; force it without spinning the event loop
    window.layer_tree_map_canvas_bridge.setCanvasLayers()


@pytest.fixture
def loaded(window, sample_raster, qtbot):
    window.main_controller.add_raster(sample_raster)
    _sync_canvas(window)
    return window


@pytest.fixture
def filter_dialog(loaded, qtbot):
    from vgeoint.app.dialogs.image_filter import ImageFilterDialog

    w = loaded
    dlg = ImageFilterDialog(w, w.map_canvas, w.layer_tree_view)
    qtbot.addWidget(dlg)
    return dlg


def _select_filter(dlg, code):
    dlg.filterTypeCbx.setCurrentIndex(dlg.filterTypeCbx.findData(code))


# ------------------------------------------------------------------ widgets
def test_widgets_keep_odd_and_canny_link(qgis_app, qtbot):
    from vgeoint.app.widgets import CannyWidget, SobelWidget

    s = SobelWidget()
    qtbot.addWidget(s)
    s.kernelSbx.setValue(6)
    assert s.kernelSbx.value() == 5
    assert not s.rowSbx.isEnabled()
    s.gaussFilterChbx.setChecked(True)
    assert s.rowSbx.isEnabled() and s.colSbx.isEnabled()

    c = CannyWidget()
    qtbot.addWidget(c)
    c.lowThresholdSbx.setValue(40)
    assert c.highThresholdSbx.value() == 120
    assert c.highThresholdSlr.value() == 120


def test_filter_dialog_init(filter_dialog, sample_raster):
    dlg = filter_dialog
    assert dlg.windowTitle() == "Lọc ảnh"
    assert dlg.filterTypeCbx.count() == 6
    assert dlg.rasterLayerCbx.count() == 1
    assert [dlg.bandCbx.itemText(i) for i in range(dlg.bandCbx.count())] == ["Kênh 1", "Kênh 2", "Kênh 3"]
    np.testing.assert_array_equal(dlg._src_image, _band(sample_raster, 1))
    assert not dlg.srcImageLbl.pixmap().isNull()

    from vgeoint.app.dialogs.image_filter import LOC_CANNY

    _select_filter(dlg, LOC_CANNY)
    assert dlg.stackedWidget.currentWidget() is dlg.cannyWidget

    dlg.bandCbx.setCurrentIndex(2)
    np.testing.assert_array_equal(dlg._src_image, _band(sample_raster, 3))
    dlg.view()
    assert not dlg.dstImageLbl.pixmap().isNull()


def _expected(code, src, dlg):
    from vgeoint.app.dialogs import image_filter as m

    if code == m.LOC_TB:
        return cv2.blur(src, (7, 5))
    if code == m.LOC_TV:
        return cv2.medianBlur(src, 5)
    if code == m.LOC_GAUSS:
        return cv2.GaussianBlur(src, (7, 5), 1.5, sigmaY=0.5)
    if code == m.LOC_SOBEL:
        img = cv2.GaussianBlur(src, (5, 3), 0)
        return cv2.convertScaleAbs(cv2.Sobel(img, cv2.CV_16S, 0, 1, ksize=5))
    if code == m.LOC_SCHARR:
        return cv2.convertScaleAbs(cv2.Scharr(src, cv2.CV_16S, 1, 0))
    if code == m.LOC_CANNY:
        return cv2.Canny(cv2.blur(src, (3, 5)), 30.0, 90.0, apertureSize=3)


def _configure(code, dlg):
    from vgeoint.app.dialogs import image_filter as m

    if code == m.LOC_TB:
        dlg.averagingWidget.colSbx.setValue(7)
        dlg.averagingWidget.rowSbx.setValue(5)
    elif code == m.LOC_TV:
        dlg.medianWidget.kernelSbx.setValue(5)
    elif code == m.LOC_GAUSS:
        g = dlg.gaussianWidget
        g.colSbx.setValue(7)
        g.rowSbx.setValue(5)
        g.sigmaXSbx.setValue(1.5)
        g.sigmaYSbx.setValue(0.5)
    elif code == m.LOC_SOBEL:
        s = dlg.sobelWidget
        s.gaussFilterChbx.setChecked(True)
        s.colSbx.setValue(5)
        s.rowSbx.setValue(3)
        s.yAxisRbtn.setChecked(True)
        s.kernelSbx.setValue(5)
    elif code == m.LOC_CANNY:
        c = dlg.cannyWidget
        c.averagingFilterChbx.setChecked(True)
        c.colSbx.setValue(3)
        c.rowSbx.setValue(5)
        c.lowThresholdSbx.setValue(30)  # high = 90


@pytest.mark.parametrize("code", ["LOC_TB", "LOC_TV", "LOC_GAUSS", "LOC_SOBEL", "LOC_SCHARR", "LOC_CANNY"])
def test_filter_apply(filter_dialog, sample_raster, tmp_path, code):
    from qgis.core import QgsProject

    dlg = filter_dialog
    _select_filter(dlg, code)
    _configure(code, dlg)
    dlg.bandCbx.setCurrentIndex(1)
    out = tmp_path / f"{code}.tif"
    dlg.outputFileLedr.setText(str(out))
    n_layers = len(QgsProject.instance().mapLayers())
    completed = []
    dlg.complete.connect(lambda: completed.append(True))
    dlg.apply()

    arr, gt, proj, dtype = _read(out)
    src_arr, src_gt, _, _ = _read(sample_raster)
    assert dtype == gdal.GDT_Byte and arr.shape == (48, 64)
    np.testing.assert_allclose(gt, src_gt)
    assert "32648" in proj or "UTM zone 48N" in proj
    np.testing.assert_array_equal(arr, _expected(code, src_arr[1], dlg))
    assert completed and dlg.output_files() == [str(out)]
    # C++: không có ai nhận tín hiệu complete() -> không tự thêm layer
    assert len(QgsProject.instance().mapLayers()) == n_layers


def test_canny_invalid_threshold_writes_original(filter_dialog, sample_raster, tmp_path, no_modal):
    from vgeoint.app.dialogs.image_filter import LOC_CANNY

    dlg = filter_dialog
    _select_filter(dlg, LOC_CANNY)
    dlg.cannyWidget.lowThresholdSbx.setValue(100)
    dlg.cannyWidget.highThresholdSbx.setValue(50)
    out = tmp_path / "canny.tif"
    dlg.outputFileLedr.setText(str(out))
    dlg.apply()
    np.testing.assert_array_equal(_band(out, 1), _band(sample_raster, 1))
    dlg.view()
    assert dlg.dstImageLbl.pixmap().isNull()


def test_filter_browse(filter_dialog, tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog

    from vgeoint.common.utils import settings

    target = (tmp_path / "x.tif").as_posix()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (target, ""))
    filter_dialog.browseBtn.click()
    assert filter_dialog.outputFileLedr.text() == target
    assert settings().value("AddRasterLayer/Dir") == tmp_path.as_posix()


# ------------------------------------------------------------------ color space
@pytest.fixture
def color_dialog(loaded, qtbot):
    from vgeoint.app.dialogs.color_space_convertion import ColorSpaceConvertionDialog

    w = loaded
    dlg = ColorSpaceConvertionDialog(w, w.map_canvas, w.layer_tree_view)
    qtbot.addWidget(dlg)
    return dlg


@pytest.mark.parametrize(
    "src_cs,dst_cs,code",
    [("RGB", "HSV", cv2.COLOR_BGR2HSV), ("RGB", "HLS", cv2.COLOR_BGR2HLS), ("HSV", "RGB", cv2.COLOR_HSV2BGR),
     ("HLS", "RGB", cv2.COLOR_HLS2BGR)],
)
def test_color_space_convert(color_dialog, sample_raster, tmp_path, src_cs, dst_cs, code):
    dlg = color_dialog
    assert dlg.windowTitle() == "Chuyển đổi không gian màu"
    assert dlg.rasterLayerCbx.count() == 1
    dlg.fromColorCbx.setCurrentText(src_cs)
    dlg.toColorCbx.setCurrentText(dst_cs)
    out = tmp_path / "cs.tif"
    dlg.outputLedr.setText(str(out))
    completed = []
    dlg.complete.connect(lambda: completed.append(True))
    dlg.apply()

    arr, gt, _, dtype = _read(out)
    src, src_gt, _, _ = _read(sample_raster)
    assert dtype == gdal.GDT_Byte and arr.shape == (3, 48, 64)
    np.testing.assert_allclose(gt, src_gt)
    dst = cv2.cvtColor(np.dstack((src[2], src[1], src[0])), code)
    # C++: kết quả split ghi vào block3, block2, block1 -> band1 = kênh 2 của dst
    np.testing.assert_array_equal(arr, np.stack((dst[:, :, 2], dst[:, :, 1], dst[:, :, 0])))
    assert completed and dlg.output_files() == [str(out)]
    assert "thành công" in dlg.noticeLbl.text()


def test_color_space_errors(color_dialog, tmp_path, window, qtbot):
    dlg = color_dialog
    dlg.apply()
    assert "Chưa chọn thư mục lưu kết quả" in dlg.noticeLbl.text()

    dlg.fromColorCbx.setCurrentText("HSV")
    dlg.toColorCbx.setCurrentText("HLS")  # không hỗ trợ
    dlg.outputLedr.setText(str(tmp_path / "x.tif"))
    dlg.apply()
    assert "Chuyển đổi thất bại" in dlg.noticeLbl.text()

    # raster 1 kênh -> thất bại
    from qgis.core import QgsProject

    QgsProject.instance().removeAllMapLayers()
    window.main_controller.add_raster(make_raster(tmp_path / "one.tif", bands=1))
    _sync_canvas(window)
    dlg.populate_raster_layers()
    dlg.fromColorCbx.setCurrentText("RGB")
    dlg.toColorCbx.setCurrentText("HSV")
    dlg.noticeLbl.clear()
    dlg.apply()
    assert "Chuyển đổi thất bại" in dlg.noticeLbl.text()
