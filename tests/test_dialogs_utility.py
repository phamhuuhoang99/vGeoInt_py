"""Utility dialogs: colour composite, brightness/contrast, split/concatenate, labeling, metadata, settings."""

import numpy as np
import pytest
from osgeo import gdal
from qgis.core import Qgis, QgsFeature, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QColorDialog, QFileDialog

from tests.conftest import make_raster
from vgeoint.common.utils import settings


def _raster_layers(window):
    return [lyr for lyr in QgsProject.instance().mapLayers().values() if isinstance(lyr, QgsRasterLayer)]


def _add_raster(window, qtbot, path):
    """Add a raster and push it to the canvas now (the layer tree bridge update is deferred)."""
    n = len(window.map_canvas.layers())
    window.main_controller.add_raster(path)
    window.layer_tree_map_canvas_bridge.setCanvasLayers()
    assert len(window.map_canvas.layers()) == n + 1


@pytest.fixture
def raster_window(window, qtbot, sample_raster):
    _add_raster(window, qtbot, sample_raster)
    return window


def _std(dialog_cls, w):
    return dialog_cls(w, w.map_canvas, w.layer_tree_view)


def test_color_composite_apply(raster_window):
    from vgeoint.app.dialogs.color_composite import ColorCompositeDialog

    w = raster_window
    dlg = _std(ColorCompositeDialog, w)
    assert dlg.rasterLayerCbx.count() == 1
    assert dlg.redBandCbx.count() == 4  # "Không" + 3 kênh
    assert dlg.redBandCbx.itemText(0) == "Không"
    assert dlg.redBandCbx.itemText(1) == "Kênh 1"

    dlg.redBandCbx.setCurrentIndex(3)
    dlg.greenBandCbx.setCurrentIndex(1)
    dlg.blueBandCbx.setCurrentIndex(2)
    dlg.minMaxRbtn.setChecked(True)
    dlg.saveBandIndexesChbx.setChecked(True)
    done = []
    dlg.complete.connect(lambda: done.append(1))
    dlg.apply()

    renderer = _raster_layers(w)[0].renderer()
    assert (renderer.redBand(), renderer.greenBand(), renderer.blueBand()) == (3, 1, 2)
    assert renderer.minMaxOrigin().limits() == Qgis.RasterRangeLimit.MinimumMaximum
    assert done == [1]
    s = settings()
    assert int(s.value("ColorComposite/BandRed")) == 3
    assert int(s.value("ColorComposite/Limit")) == Qgis.RasterRangeLimit.MinimumMaximum.value

    # Reopening reflects the renderer; "default" reloads saved settings (index = band - 1)
    dlg2 = _std(ColorCompositeDialog, w)
    assert dlg2.redBandCbx.currentData() == 3
    assert dlg2.minMaxRbtn.isChecked()
    dlg2.defaultBtn.click()
    assert dlg2.redBandCbx.currentIndex() == 2


def test_color_composite_single_band(window, qtbot, tmp_path):
    from vgeoint.app.dialogs.color_composite import ColorCompositeDialog

    _add_raster(window, qtbot, make_raster(tmp_path / "one.tif", bands=1))
    dlg = _std(ColorCompositeDialog, window)
    assert dlg.redBandCbx.currentIndex() == 0
    assert not dlg.saveBandIndexesChbx.isEnabled()
    dlg.apply()  # must not crash on a gray renderer


def test_brightness_contrast(raster_window):
    from vgeoint.app.dialogs.brightness_contrast import BrightnessContrastDialog

    w = raster_window
    dlg = _std(BrightnessContrastDialog, w)
    assert dlg.windowTitle() == "Độ sáng / Độ tương phản"
    dlg.brightnessSdr.setValue(40)
    dlg.contrastSdr.setValue(-25)
    assert dlg.brightnessSbx.value() == 40  # .ui connections slider <-> spinbox
    dlg.apply()
    f = _raster_layers(w)[0].brightnessFilter()
    assert (f.brightness(), f.contrast()) == (40, -25)

    dlg2 = _std(BrightnessContrastDialog, w)
    assert dlg2.brightnessSdr.value() == 40
    dlg2.brightnessDefaultBtn.click()
    dlg2.contrastDefaultBtn.click()
    assert dlg2.brightnessSdr.value() == 0 and dlg2.contrastSdr.value() == 0


def test_image_split(raster_window, sample_raster, tmp_path, monkeypatch):
    from vgeoint.app.dialogs.image_split import ImageSplitDialog

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(out_dir))
    dlg = _std(ImageSplitDialog, raster_window)
    assert dlg.bandCountLedr.text() == "3"
    assert dlg.pixelTypeLedr.text() == "8 bit"
    assert dlg.bandLswg.item(0).text() == "sample-band1"
    dlg.selectFolderBtn.click()
    assert dlg.outputFolderLedr.text() == str(out_dir)
    assert settings().value("SaveImage/Dir") == str(out_dir)

    dlg.bandLswg.item(2).setText("blue")
    dlg.apply()
    assert "hoàn thành" in dlg.noticeLbl.text()
    assert dlg.output_files[2] == f"{out_dir}/blue.tif"

    src = gdal.Open(sample_raster)
    for i, path in enumerate(dlg.output_files):
        ds = gdal.Open(path)
        assert ds.RasterCount == 1 and ds.RasterXSize == 64 and ds.RasterYSize == 48
        assert ds.GetRasterBand(1).DataType == gdal.GDT_Byte
        assert np.array_equal(ds.GetRasterBand(1).ReadAsArray(), src.GetRasterBand(i + 1).ReadAsArray())
        assert ds.GetGeoTransform() == pytest.approx(src.GetGeoTransform())
        ds = None

    dlg.defaultBandNameBtn.click()
    assert dlg.bandLswg.item(2).text() == "sample-band3"


def test_image_concatenating(window, qtbot, tmp_path, monkeypatch):
    from vgeoint.app.dialogs.image_concatenating import ImageConcatenatingDialog

    a = make_raster(tmp_path / "a.tif", bands=2, seed=1)
    b = make_raster(tmp_path / "b.tif", bands=1, seed=2)
    _add_raster(window, qtbot, a)
    _add_raster(window, qtbot, b)
    out = str(tmp_path / "cat.tif")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (out, ""))

    dlg = _std(ImageConcatenatingDialog, window)
    dlg.apply()
    assert "Chưa có ảnh" in dlg.noticeLbl.text()

    names = [dlg.rasterLayerCbx.itemText(i) for i in range(dlg.rasterLayerCbx.count())]
    for name in ("b", "a"):
        dlg.rasterLayerCbx.setCurrentIndex(names.index(name))
        dlg.addBtn.click()
    dlg.bandLswg.setCurrentRow(1)
    dlg.upBtn.click()  # a, b
    assert [dlg.bandLswg.item(i).text() for i in range(2)] == ["a", "b"]

    dlg.apply()
    assert "Chưa đặt" in dlg.noticeLbl.text()
    dlg.selectFileNameBtn.click()
    assert dlg.outputFileNameLedr.text() == out
    dlg.apply()
    assert "hoàn thành" in dlg.noticeLbl.text()
    assert dlg.output_files == [out]

    ds = gdal.Open(out)
    assert ds.RasterCount == 3
    da, db = gdal.Open(a), gdal.Open(b)
    expected = [da.GetRasterBand(1), da.GetRasterBand(2), db.GetRasterBand(1)]
    for i, band in enumerate(expected):
        assert np.array_equal(ds.GetRasterBand(i + 1).ReadAsArray(), band.ReadAsArray())
    ds = None

    dlg.bandLswg.setCurrentRow(0)
    dlg.removeBtn.click()
    assert dlg.bandLswg.count() == 1


def test_image_concatenating_mismatch(window, qtbot, tmp_path):
    from vgeoint.app.dialogs.image_concatenating import ImageConcatenatingDialog

    _add_raster(window, qtbot, make_raster(tmp_path / "a.tif"))
    _add_raster(window, qtbot, make_raster(tmp_path / "small.tif", width=10, height=10))
    dlg = _std(ImageConcatenatingDialog, window)
    for i in range(2):
        dlg.rasterLayerCbx.setCurrentIndex(i)
        dlg.addBtn.click()
    dlg.outputFileNameLedr.setText(str(tmp_path / "x.tif"))
    dlg.apply()
    assert "không cùng khu vực" in dlg.noticeLbl.text()


def _points_layer():
    layer = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer&field=ten:string", "pts", "memory")
    f = QgsFeature(layer.fields())
    f.setAttributes([1, "A"])
    layer.dataProvider().addFeatures([f])
    QgsProject.instance().addMapLayer(layer)
    return layer


def test_vector_labeling(window, monkeypatch):
    from vgeoint.app.dialogs.vector_labeling import VectorLabelingDialog

    layer = _points_layer()
    dlg = VectorLabelingDialog(layer, window.map_canvas, window)
    assert dlg.layerNameLabel.text() == "pts"
    assert dlg.enableLabelCheckBox.isChecked()
    assert dlg.fieldComboBox.count() == 2

    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor(255, 0, 0))
    dlg.textColorButton.click()
    assert dlg.textColorButton.text() == "#FF0000"
    dlg.fieldComboBox.setCurrentIndex(1)
    dlg.fontSizeSpinBox.setValue(14)
    dlg.boldCheckBox.setChecked(True)
    dlg.bufferSizeSpinBox.setValue(2.0)
    dlg.apply()

    assert layer.labelsEnabled()
    pal = layer.labeling().settings()
    assert pal.fieldName == "ten"
    fmt = pal.format()
    assert fmt.size() == 14 and fmt.font().bold()
    assert fmt.color() == QColor(255, 0, 0)
    assert fmt.buffer().enabled() and fmt.buffer().size() == 2.0

    # Reopen: loads existing settings; disabling turns labels off
    dlg2 = VectorLabelingDialog(layer, window.map_canvas, window)
    assert dlg2.fieldComboBox.currentText() == "ten"
    assert dlg2.fontSizeSpinBox.value() == 14
    dlg2.enableLabelCheckBox.setChecked(False)
    assert not dlg2.settingsGroupBox.isEnabled()
    dlg2.apply()
    assert not layer.labelsEnabled()


def test_metadata_viewer(raster_window):
    from vgeoint.app.dialogs.metadata_viewer import MetadataViewerDialog

    dlg = _std(MetadataViewerDialog, raster_window)
    assert "sample" in dlg.textBrowser.toPlainText()


def test_settings_dialog(window, monkeypatch):
    from vgeoint.app.dialogs.settings import SettingsDialog

    dlg = SettingsDialog(window)
    assert dlg.crsCbx.count() == 6
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor(10, 20, 30))
    dlg.colorPickerBtn.click()
    dlg.crsCbx.setCurrentIndex(dlg.crsCbx.findData(32648))
    dlg.okBtn.click()

    assert QgsProject.instance().crs().authid() == "EPSG:32648"
    assert window.map_canvas.canvasColor() == QColor(10, 20, 30)
    s = settings()
    assert [int(s.value(f"MapCanvas/{k}")) for k in ("EPSG", "Red", "Green", "Blue")] == [32648, 10, 20, 30]

    dlg2 = SettingsDialog(window)
    assert dlg2.crsCbx.currentData() == 32648
    dlg2.defaultBtn.click()
    assert dlg2.crsCbx.currentData() == 4326 and dlg2.color == QColor(255, 255, 255)
    for k in ("EPSG", "Red", "Green", "Blue"):
        s.remove(f"MapCanvas/{k}")
