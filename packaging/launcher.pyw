"""Start a vGeoInt app from an installed copy: `pythonw.exe launcher.pyw vgeoint.app`.

Applies the environment recorded at install time by make_launch_env.py (the conda env activation:
DLL folders on PATH, GDAL/PROJ data...) and runs the given module, with src/ on sys.path.
"""

import json
import os
import runpy
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def apply_launch_env():
    config = json.loads((APP_DIR / "launch_env.json").read_text(encoding="utf-8"))
    os.environ.update(config["set"])
    for key in config["unset"]:
        os.environ.pop(key, None)
    prepend = config["prepend_path"]
    keep = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and d not in prepend and not _foreign_gdal(d)]
    os.environ["PATH"] = os.pathsep.join(prepend + keep)
    for d in prepend:
        if os.path.isdir(d):
            os.add_dll_directory(d)
    # PYTHONPATH from the activation (QGIS' Library/python) only takes effect at interpreter start.
    for p in reversed([p for p in config["set"].get("PYTHONPATH", "").split(os.pathsep) if p]):
        if p not in sys.path:
            sys.path.insert(0, p)


def _foreign_gdal(directory: str) -> bool:
    """Other GDAL builds (OSGeo4W, OTB...) on PATH would be picked up instead of the env's own."""
    try:
        p = Path(directory)
        return not p.is_relative_to(sys.prefix) and any(p.glob("gdal*.dll"))
    except OSError:
        return False


def main():
    apply_launch_env()
    sys.path.insert(0, str(APP_DIR / "src"))
    module = sys.argv[1] if len(sys.argv) > 1 else "vgeoint.app"
    sys.argv = [module, *sys.argv[2:]]
    os.chdir(APP_DIR)
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
