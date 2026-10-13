"""Absolute paths to bundled assets, independent of the working directory."""

import os
from pathlib import Path

# src/vgeoint/common/paths.py -> repo root
ROOT = Path(__file__).resolve().parents[3]
UI_DIR = ROOT / "ui"
RESOURCES_DIR = ROOT / "resources"
CONFIG_DIR = ROOT / "config"
SQL_DIR = ROOT / "sql"
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "ai" / "scripts"
# Model weights are large and not in git; override with VGEOINT_MODELS_DIR.
MODELS_DIR = Path(os.environ.get("VGEOINT_MODELS_DIR", ROOT / "models"))


def ui_file(app: str, name: str) -> Path:
    """Path to a Qt Designer file, e.g. ui_file("app", "BandMathDialog")."""
    return UI_DIR / app / f"{name}.ui"


def resource(qrc_path: str) -> str:
    """Map a Qt resource path from the C++ app (":/myicon/x.svg") to a file path."""
    if qrc_path.startswith(":/"):
        return str(RESOURCES_DIR / qrc_path[2:])
    return qrc_path
