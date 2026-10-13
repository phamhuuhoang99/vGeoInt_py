"""Static check: every dotted name starting with a Qt/QGIS class (e.g. Qt.AlignmentFlag.AlignCenter,
QgsCoordinateFormatter.Format.FormatPair, QgsMapTool.cursor) must exist in the installed bindings.

Catches Qt5/QGIS3 -> Qt6/QGIS4 enum renames that otherwise only fail when the line runs.
Usage: pixi run python tools/check_attributes.py [paths...]
"""

import ast
import importlib
import sys
from pathlib import Path

MODULES = ["qgis.core", "qgis.gui", "qgis.analysis", "qgis.PyQt.QtCore", "qgis.PyQt.QtGui",
           "qgis.PyQt.QtWidgets", "qgis.PyQt.QtSql", "qgis.PyQt.QtNetwork"]


def namespace() -> dict:
    ns = {}
    for name in MODULES:
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        for attr in dir(mod):
            if attr[:1].isupper():
                ns.setdefault(attr, getattr(mod, attr))
    return ns


def chains(tree):
    """Yield (lineno, [Name, attr, attr...]) for maximal attribute chains rooted at a Name."""
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and not isinstance(parents.get(node), ast.Attribute):
            parts, cur = [], node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                yield node.lineno, [cur.id, *reversed(parts)]


def main():
    ns = namespace()
    roots = [Path(p) for p in sys.argv[1:]] or [Path(__file__).resolve().parents[1] / "src" / "vgeoint"]
    problems = 0
    for root in roots:
        for path in sorted(root.rglob("*.py")) if root.is_dir() else [root]:
            if "ai/scripts" in path.as_posix():
                continue  # run in the ai env, no Qt/QGIS
            tree = ast.parse(path.read_text(encoding="utf-8"))
            local_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            for lineno, chain in chains(tree):
                if chain[0] not in ns or chain[0] in local_names:
                    continue
                obj = ns[chain[0]]
                for i, attr in enumerate(chain[1:], 1):
                    if not hasattr(obj, attr):
                        print(f"{path}:{lineno}: {'.'.join(chain[:i + 1])} does not exist")
                        problems += 1
                        break
                    obj = getattr(obj, attr)
    print(f"{problems} problem(s)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
