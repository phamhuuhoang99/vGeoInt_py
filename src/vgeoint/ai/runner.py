"""Run the AI scripts in their own Python environment and stream their output.

Replaces the per-dialog QProcess code of the C++ app, which started "python_env/python.exe" with paths
relative to the working directory and parsed free text with QRegExp. Scripts now report machine
readable events through `vgeoint.ai.scripts._events` (one JSON line prefixed with EVENT_PREFIX);
every other line is plain log text shown to the user as before.
"""

import json
import os
import sys
from pathlib import Path

from qgis.PyQt.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

from vgeoint.common.paths import MODELS_DIR, ROOT, SCRIPTS_DIR

EVENT_PREFIX = "@@VGEOINT "


GUI_ENV = "gui"  # the environment running the app itself (GDAL, Qt), for scripts that need no AI package


def python_for(env: str = "ai") -> str:
    """Interpreter of a pixi environment; VGEOINT_<ENV>_PYTHON overrides it."""
    override = os.environ.get(f"VGEOINT_{env.upper()}_PYTHON")
    if override:
        return override
    if env == GUI_ENV:
        # python.exe rather than the pythonw.exe of the installed launcher: its output goes to the pipe.
        console = Path(sys.executable).with_name("python.exe")
        return str(console) if sys.platform == "win32" and console.exists() else sys.executable
    # .pixi/envs/<env>: development checkout; envs/<env>: installed by the AI add-on installer.
    for env_dir in (ROOT / ".pixi" / "envs" / env, ROOT / "envs" / env):
        exe = env_dir / ("python.exe" if sys.platform == "win32" else "bin/python")
        if exe.exists():
            return str(exe)
    return sys.executable


def env_available(env: str) -> bool:
    """True when the env has its own interpreter (or an override), i.e. not falling back to sys.executable."""
    if env == GUI_ENV:
        return True
    return python_for(env) != sys.executable or bool(os.environ.get(f"VGEOINT_{env.upper()}_PYTHON"))


def _has_foreign_gdal(directory: str, env_prefix: Path) -> bool:
    try:
        p = Path(directory)
        return not p.is_relative_to(env_prefix) and any(p.glob("gdal*.dll"))
    except OSError:
        return False


def activated_environment(python: str) -> dict[str, str]:
    """Environment variables equivalent to activating the conda/pixi env that owns `python`.

    QProcess starts python.exe directly (no `pixi run`), so the env's DLL folders must be put on PATH
    and GDAL/PROJ data paths set by hand. Folders holding another GDAL build (OSGeo4W, OTB,
    PostgreSQL...) are dropped from PATH: rasterio adds every PATH folder containing gdal*.dll to the
    DLL search path and would otherwise load the wrong gdal.dll.
    """
    env = dict(os.environ)
    prefix = Path(python).resolve().parent
    if sys.platform == "win32":
        lib = prefix / "Library"
        own = [prefix, lib / "mingw-w64" / "bin", lib / "usr" / "bin", lib / "bin", prefix / "Scripts", prefix / "bin"]
        data = lib / "share"
    else:
        prefix = prefix.parent
        own = [prefix / "bin"]
        data = prefix / "share"
    inherited = [d for d in env.get("PATH", "").split(os.pathsep) if d and not _has_foreign_gdal(d, prefix)]
    env["PATH"] = os.pathsep.join([*map(str, own), *inherited])
    env["CONDA_PREFIX"] = str(prefix)
    for key in ("GDAL_DATA", "GDAL_DRIVER_PATH", "PROJ_LIB", "PROJ_DATA"):
        env.pop(key, None)
    if (data / "gdal").exists():
        env["GDAL_DATA"] = str(data / "gdal")
    if (data / "proj").exists():
        env["PROJ_DATA"] = env["PROJ_LIB"] = str(data / "proj")
    return env


def script_path(name: str) -> Path:
    return SCRIPTS_DIR / name


def model_path(relative: str) -> Path:
    """Absolute path of a model given the C++ relative form, e.g. "models/best.pt" or "best.pt"."""
    rel = relative.replace("\\", "/")
    if rel.startswith("models/"):
        rel = rel[len("models/"):]
    return MODELS_DIR / rel


def parse_event(line: str) -> dict | None:
    if not line.startswith(EVENT_PREFIX):
        return None
    try:
        return json.loads(line[len(EVENT_PREFIX):])
    except json.JSONDecodeError:
        return None


class ScriptRunner(QObject):
    """QProcess wrapper with line-based signals.

    Signals:
        output_line(str)  – a stdout line that is not an event
        error_line(str)   – a stderr line
        event_received(dict) – a parsed event, e.g. {"type": "progress", "value": 42}
        finished(int, bool) – exit code, crashed
    """

    output_line = pyqtSignal(str)
    error_line = pyqtSignal(str)
    event_received = pyqtSignal(dict)  # not "event": that would shadow QObject.event()
    finished = pyqtSignal(int, bool)
    started = pyqtSignal()

    def __init__(self, parent=None, env: str = "ai"):
        super().__init__(parent)
        self.env = env
        self.process = QProcess(self)
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._finished)
        self.process.started.connect(self.started.emit)
        self.process.errorOccurred.connect(self._error)

    # ---------------------------------------------------------------- control
    def start_script(self, script: str, args: list[str], working_dir: str | None = None, program: str | None = None):
        """Run `python <scripts/script> args...` (or `program args...` when given)."""
        python = python_for(self.env)
        variables = activated_environment(python)
        variables["PYTHONIOENCODING"] = "utf-8"
        variables["PYTHONUNBUFFERED"] = "1"
        # Lets scripts import vgeoint.ai.scripts._events regardless of their working directory.
        src_dir = str(Path(__file__).resolve().parents[2])
        existing = variables.get("PYTHONPATH", "")
        variables["PYTHONPATH"] = src_dir + (os.pathsep + existing if existing else "")
        variables["VGEOINT_MODELS_DIR"] = str(MODELS_DIR)
        environment = QProcessEnvironment()
        for key, value in variables.items():
            environment.insert(key, value)
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(working_dir or str(ROOT))

        self._stdout_buffer = self._stderr_buffer = ""
        if program is None and not env_available(self.env):
            # Installed copy without the AI add-on: report it instead of an ImportError from the script.
            QTimer.singleShot(0, self._missing_env)
            return
        if program is None:
            self.process.start(python, ["-u", str(script_path(script)), *map(str, args)])
        else:
            self.process.start(program, [*map(str, args)])

    def _missing_env(self):
        self.error_line.emit(
            "Chưa cài gói AI (môi trường \"ai\"). Hãy cài vGeoInt-AI-Setup rồi chạy lại chức năng này."
        )
        self.finished.emit(-1, True)

    def is_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def kill(self):
        if self.is_running():
            self.process.kill()
            self.process.waitForFinished(3000)

    def wait(self, msecs: int = -1) -> bool:
        return self.process.waitForFinished(msecs)

    # --------------------------------------------------------------- reading
    @staticmethod
    def _decode(data) -> str:
        return bytes(data).decode("utf-8", errors="replace")

    def _split(self, buffer: str, chunk: str) -> tuple[list[str], str]:
        buffer += chunk.replace("\r\n", "\n").replace("\r", "\n")
        *lines, rest = buffer.split("\n")
        return lines, rest

    def _read_stdout(self):
        lines, self._stdout_buffer = self._split(self._stdout_buffer, self._decode(self.process.readAllStandardOutput()))
        for line in lines:
            self._emit_stdout(line)

    def _emit_stdout(self, line: str):
        ev = parse_event(line)
        if ev is not None:
            self.event_received.emit(ev)
        elif line.strip():
            self.output_line.emit(line)

    def _read_stderr(self):
        lines, self._stderr_buffer = self._split(self._stderr_buffer, self._decode(self.process.readAllStandardError()))
        for line in lines:
            if line.strip():
                self.error_line.emit(line)

    def _finished(self, exit_code: int, exit_status):
        self._read_stdout()
        self._read_stderr()
        if self._stdout_buffer:
            self._emit_stdout(self._stdout_buffer)
        if self._stderr_buffer.strip():
            self.error_line.emit(self._stderr_buffer)
        self._stdout_buffer = self._stderr_buffer = ""
        self.finished.emit(exit_code, exit_status == QProcess.ExitStatus.CrashExit)

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.error_line.emit(f"Không thể khởi động Python: {python_for(self.env)}")
            self.finished.emit(-1, True)
