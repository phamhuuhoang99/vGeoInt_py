"""Processing dialogs tell the user how the task ended (the C++ closed them silently on "Đồng ý")."""

import pytest
from qgis.core import Qgis

from tests.conftest import make_raster


def _last_message(window):
    item = window.message_bar.currentItem()
    return (item.level(), item.title(), item.text()) if item is not None else None


@pytest.fixture
def raster(window, tmp_path):
    path = make_raster(tmp_path / "anh.tif")
    window.main_controller.add_raster(path)
    window.layer_tree_map_canvas_bridge.setCanvasLayers()
    return path


def _track_close(monkeypatch, dialog):
    closed = []
    monkeypatch.setattr(dialog, "close", lambda: closed.append(True) or True)
    return closed


def test_image_split_success_notifies_and_closes(window, raster, tmp_path, monkeypatch):
    from vgeoint.app.dialogs.image_split import ImageSplitDialog

    dlg = ImageSplitDialog(window, window.map_canvas, window.layer_tree_view)
    closed = _track_close(monkeypatch, dlg)
    out = tmp_path / "out"
    out.mkdir()
    dlg.outputFolderLedr.setText(str(out))
    dlg.okBtn.click()

    assert closed == [True]
    level, title, text = _last_message(window)
    assert level == Qgis.MessageLevel.Success and title == "Tách kênh ảnh"
    assert "Đã tách 3 kênh" in text and "href=" in text
    assert len(list(out.glob("*.tif"))) == 3


def test_image_split_failure_keeps_dialog_open(window, raster, monkeypatch):
    from vgeoint.app.dialogs.image_split import ImageSplitDialog

    dlg = ImageSplitDialog(window, window.map_canvas, window.layer_tree_view)
    closed = _track_close(monkeypatch, dlg)
    dlg.outputFolderLedr.setText("")  # no folder: used to write "/<band>.tif" at the drive root
    dlg.okBtn.click()

    assert closed == []
    assert "Chưa chọn thư mục" in dlg.noticeLbl.text()
    level, _title, text = _last_message(window)
    assert level == Qgis.MessageLevel.Critical and "Chưa chọn thư mục" in text


def test_image_concatenating_notifies(window, raster, tmp_path, monkeypatch):
    from vgeoint.app.dialogs.image_concatenating import ImageConcatenatingDialog

    dlg = ImageConcatenatingDialog(window, window.map_canvas, window.layer_tree_view)
    closed = _track_close(monkeypatch, dlg)
    dlg.okBtn.click()  # nothing added
    assert closed == [] and _last_message(window)[0] == Qgis.MessageLevel.Critical

    dlg._add()  # the same raster twice -> a 6-band image
    dlg._add()
    dlg.outputFileNameLedr.setText(str(tmp_path / "gop.tif"))
    dlg.okBtn.click()
    assert closed == [True]
    level, _title, text = _last_message(window)
    assert level == Qgis.MessageLevel.Success and "gop.tif" in text


def test_image_filter_notifies(window, raster, tmp_path, monkeypatch):
    from vgeoint.app.dialogs.image_filter import ImageFilterDialog

    dlg = ImageFilterDialog(window, window.map_canvas, window.layer_tree_view)
    closed = _track_close(monkeypatch, dlg)
    dlg.okBtn.click()  # no output file
    assert closed == [] and "Chưa chọn ảnh kết quả" in _last_message(window)[2]

    dlg.outputFileLedr.setText(str(tmp_path / "loc.tif"))
    dlg.okBtn.click()
    assert closed == [True]
    level, _title, text = _last_message(window)
    assert level == Qgis.MessageLevel.Success and "loc.tif" in text


def test_band_math_notifies(window, raster, tmp_path, monkeypatch):
    from vgeoint.app.dialogs.band_math import BandMathDialog

    dlg = BandMathDialog(window, window.map_canvas, window.layer_tree_view)
    _track_close(monkeypatch, dlg)
    dlg.outputLedr.setText(str(tmp_path / "bm.tif"))
    dlg.expressionTder.setPlainText('"anh@k1" * 2')
    dlg.apply()
    level, _title, text = _last_message(window)
    assert level == Qgis.MessageLevel.Success and "bm.tif" in text
