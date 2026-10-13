"""Run once by the installer: record what activating the unpacked env changes in the environment.

pixi-unpack writes <app>/activate.bat (conda activation scripts: PATH, GDAL_DATA, PROJ_DATA, Qt...).
launcher.pyw replays the recorded changes, so the apps start from a shortcut without a console.
Usage: python make_launch_env.py <app_dir>
"""

import json
import os
import subprocess
import sys
from pathlib import Path

MARKER = "===VGEOINT-ENV==="


def environment_after(activate: Path) -> dict[str, str]:
    out = subprocess.run(
        f'call "{activate}" >nul 2>&1 && echo {MARKER} && set',
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    ).stdout
    lines = out.split(MARKER, 1)[1].splitlines()
    env = {}
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key:
            env[key.upper()] = value
    return env


def main():
    app_dir = Path(sys.argv[1]).resolve()
    before = {k.upper(): v for k, v in os.environ.items()}
    after = environment_after(app_dir / "activate.bat")

    old_path = [p for p in before.get("PATH", "").split(os.pathsep) if p]
    new_path = [p for p in after.get("PATH", "").split(os.pathsep) if p]
    prepend = [p for p in new_path if p not in old_path]

    ignore = {"PATH", "PROMPT", "_", "CD", "ERRORLEVEL"}
    changed = {k: v for k, v in after.items() if k not in ignore and before.get(k) != v}
    # Variables from other GIS installs (e.g. PostgreSQL's GDAL_DATA / PROJ_LIB) must not leak in.
    unset = [k for k in ("GDAL_DATA", "GDAL_DRIVER_PATH", "PROJ_LIB", "PROJ_DATA") if k in before and k not in after]

    (app_dir / "launch_env.json").write_text(
        json.dumps({"prepend_path": prepend, "set": changed, "unset": unset}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
