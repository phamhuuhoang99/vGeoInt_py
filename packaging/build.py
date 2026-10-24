"""Build the Windows installers.

    pixi run -e package package            # main installer
    pixi run -e package package --ai       # AI add-on installer
    pixi run -e package package --all

Steps: compile .qrc -> .rcc, stage the app files, `pixi-pack` the runtime/ai environment into a
folder of conda packages, compile the Inno Setup script. Intermediate folders under build/ are
removed after each installer to save disk space (the AI pack is several GB).
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
ISCC_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]


def run(cmd: list, **kwargs):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kwargs)


def version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def tool(name: str) -> Path:
    found = shutil.which(name) or shutil.which(name + ".exe")
    if not found:
        sys.exit(f"{name} not found; run through `pixi run -e package package`")
    return Path(found)


def iscc() -> Path:
    for candidate in [*(Path(p) for p in filter(None, [shutil.which("iscc")])), *ISCC_CANDIDATES]:
        if candidate.exists():
            return candidate
    sys.exit("Inno Setup 6 (ISCC.exe) not found")


def iss_with_bom(name: str) -> Path:
    """Inno Setup needs a UTF-8 BOM to read the Vietnamese texts correctly."""
    target = BUILD / name
    target.write_text((PACKAGING / name).read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    return target


def pixi_pack(env: str, out: Path):
    if out.exists():
        shutil.rmtree(out)
    # Downloaded packages are kept in build/pack-cache: a failed download (a few GB for the ai env) can be
    # retried without starting over, and later builds only fetch what changed.
    run([tool("pixi-pack"), "--environment", env, "--directory-only", "--ignore-pypi-non-wheel",
         "--use-cache", ROOT / "build" / "pack-cache", "--output-file", out, ROOT / "pixi.toml"])


def stage_app() -> Path:
    stage = BUILD / "stage"
    if stage.exists():
        shutil.rmtree(stage)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info")
    for folder in ("src", "ui", "resources", "config", "sql"):
        shutil.copytree(ROOT / folder, stage / folder, ignore=ignore)
    for f in ("launcher.pyw", "make_launch_env.py"):
        shutil.copy2(PACKAGING / f, stage / f)
    shutil.copy2(ROOT / "README.md", stage / "README.md")
    # Background maps of vGeoCatalog (data/catalog may be a junction to the old app's data folder).
    catalog_data = ROOT / "data" / "catalog"
    if catalog_data.exists():
        shutil.copytree(catalog_data, stage / "data" / "catalog")
    else:
        print("WARNING: data/catalog missing - vGeoCatalog will have no background map")
    return stage


def build_resources():
    rcc_script = ROOT / "tools" / "build_resources.py"
    run([tool("pixi"), "run", "--manifest-path", ROOT / "pixi.toml", "python", rcc_script])


def build_main(keep: bool):
    build_resources()
    stage = stage_app()
    pack = BUILD / "pack-runtime"
    pixi_pack("runtime", pack)
    run([
        iscc(),
        f"/DAppVersion={version()}",
        f"/DStageDir={stage}",
        f"/DPackDir={pack}",
        f"/DUnpackExe={tool('pixi-unpack')}",
        f"/DOutputDir={DIST}",
        iss_with_bom("vgeoint.iss"),
    ])
    if not keep:
        shutil.rmtree(stage)
        shutil.rmtree(pack)


def build_ai(keep: bool):
    models = ROOT / "models"
    if not models.exists():
        sys.exit("models/ not found (junction or folder with the model weights)")
    pack = BUILD / "pack-ai"
    pixi_pack("ai", pack)
    run([
        iscc(),
        f"/DAppVersion={version()}",
        f"/DPackDir={pack}",
        f"/DUnpackExe={tool('pixi-unpack')}",
        f"/DModelsDir={models.resolve()}",
        f"/DOutputDir={DIST}",
        iss_with_bom("vgeoint-ai.iss"),
    ])
    if not keep:
        shutil.rmtree(pack)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ai", action="store_true", help="build the AI add-on instead of the main installer")
    parser.add_argument("--all", action="store_true", help="build both installers")
    parser.add_argument("--keep", action="store_true", help="keep build/ intermediates")
    args = parser.parse_args()

    BUILD.mkdir(exist_ok=True)
    DIST.mkdir(exist_ok=True)
    if args.all or not args.ai:
        build_main(args.keep)
    if args.all or args.ai:
        build_ai(args.keep)
    for f in sorted(DIST.glob("*.exe")):
        print(f"{f.name}: {f.stat().st_size / 2**30:.2f} GB")


if __name__ == "__main__":
    main()
