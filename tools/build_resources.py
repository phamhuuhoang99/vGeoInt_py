"""Compile the original .qrc files into binary .rcc bundles loaded at runtime.

Keeps every ':/myicon/...' and ':/images/...' path from the C++ app and .ui files working.
"""

import shutil
import subprocess
import sys
from pathlib import Path

RES = Path(__file__).resolve().parents[1] / "resources"
QRCS = [RES / "myicon" / "myicon.qrc", RES / "images" / "images.qrc"]


def find_rcc() -> str:
    candidates = [shutil.which("rcc")]
    lib = Path(sys.prefix) / "Library"
    candidates += [str(p) for p in lib.glob("**/rcc.exe")]
    for c in candidates:
        if c and Path(c).exists():
            return c
    sys.exit("rcc not found in the environment")


rcc = find_rcc()
for qrc in QRCS:
    out = RES / f"{qrc.parent.name}.rcc"
    subprocess.run([rcc, "--binary", str(qrc), "-o", str(out)], check=True)
    print(f"{qrc.relative_to(RES)} -> {out.name}")
