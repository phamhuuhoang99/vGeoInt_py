"""Completion messages on the main window's message bar.

The C++ processing dialogs only set a label inside the dialog and beeped, then closed it right away on
"Đồng ý", so the user never saw whether the task succeeded. The message bar outlives the dialog and links
to the result.
"""

from pathlib import Path

from qgis.core import Qgis
from qgis.PyQt.QtCore import QDir, QUrl

DURATION = 10  # seconds


def _message_bar():
    from vgeoint.app.main_window import MainWindow  # lazy: avoid import cycle

    window = MainWindow.instance()
    return window.message_bar if window is not None else None


def notify_success(title: str, text: str, path: str | None = None):
    bar = _message_bar()
    if bar is None:
        return
    if path:
        p = Path(path)
        folder = p if p.is_dir() else p.parent
        url = QUrl.fromLocalFile(str(folder)).toString()
        text += f': <a href="{url}">{QDir.toNativeSeparators(str(p))}</a>'
    bar.pushMessage(title, text, Qgis.MessageLevel.Success, DURATION)


def notify_failure(title: str, text: str):
    bar = _message_bar()
    if bar is not None:
        bar.pushMessage(title, text, Qgis.MessageLevel.Critical, DURATION)
