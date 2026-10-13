"""ScriptRunner: line splitting, events, exit codes, model paths."""

import sys
import textwrap

import pytest

from vgeoint.common.paths import ROOT

FAKE_SCRIPT = textwrap.dedent(
    """
    import sys
    from vgeoint.ai.scripts._events import progress, result
    print("Bắt đầu xử lý")
    progress(50, "nửa chừng")
    print("cảnh báo", file=sys.stderr)
    result(output="out.shp", count=3)
    sys.exit(int(sys.argv[1]))
    """
)


@pytest.fixture
def fake_script(tmp_path, monkeypatch):
    from vgeoint.ai import runner

    (tmp_path / "fake.py").write_text(FAKE_SCRIPT, encoding="utf-8")
    monkeypatch.setattr(runner, "SCRIPTS_DIR", tmp_path)
    monkeypatch.setenv("VGEOINT_AI_PYTHON", sys.executable)
    return "fake.py"


@pytest.mark.parametrize("code", [0, 2])
def test_runner_streams_lines_and_events(qgis_app, qtbot, fake_script, code):
    from vgeoint.ai.runner import ScriptRunner

    r = ScriptRunner()
    out, err, events, done = [], [], [], []
    r.output_line.connect(out.append)
    r.error_line.connect(err.append)
    r.event_received.connect(events.append)
    r.finished.connect(lambda c, crashed: done.append((c, crashed)))
    with qtbot.waitSignal(r.finished, timeout=20000):
        r.start_script(fake_script, [code])

    assert out == ["Bắt đầu xử lý"]
    assert err == ["cảnh báo"]
    assert events == [
        {"type": "progress", "value": 50, "message": "nửa chừng"},
        {"type": "result", "output": "out.shp", "count": 3},
    ]
    assert done == [(code, False)]


def test_model_path():
    from vgeoint.ai.runner import model_path
    from vgeoint.common.paths import MODELS_DIR

    assert model_path("models/best.pt") == MODELS_DIR / "best.pt"
    assert model_path("onnx_output/model.onnx") == MODELS_DIR / "onnx_output" / "model.onnx"


AI_PYTHON = ROOT / ".pixi" / "envs" / "ai" / "python.exe"


@pytest.mark.skipif(not AI_PYTHON.exists(), reason="ai environment not installed")
def test_ai_env_imports(qgis_app, qtbot, tmp_path, monkeypatch):
    """The ai env must import its geo/AI stack even with other GDAL builds (OSGeo4W, OTB) on PATH."""
    from vgeoint.ai import runner

    (tmp_path / "imports.py").write_text(
        "import rasterio, rasterio.warp, geopandas, cv2, torch, ultralytics, onnxruntime, joblib\n"
        "from vgeoint.ai.scripts._events import result\n"
        "result(gdal=rasterio.__gdal_version__)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "SCRIPTS_DIR", tmp_path)
    monkeypatch.delenv("VGEOINT_AI_PYTHON", raising=False)
    r = runner.ScriptRunner()
    events, err = [], []
    r.event_received.connect(events.append)
    r.error_line.connect(err.append)
    with qtbot.waitSignal(r.finished, timeout=120000) as blocker:
        r.start_script("imports.py", [])
    assert blocker.args[0] == 0, "\n".join(err)
    assert events and events[0]["type"] == "result"
