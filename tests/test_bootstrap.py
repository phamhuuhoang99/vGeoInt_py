"""Start-up helpers shared by the three apps (vgeoint.common.bootstrap)."""

import signal
import sys


def test_ctrl_c_closes_the_windows(qgis_app, qtbot):
    """Ctrl+C in the console closes the app instead of a KeyboardInterrupt logged as an error."""
    from qgis.PyQt.QtWidgets import QWidget

    from vgeoint.common.bootstrap import install_ctrl_c_handler

    previous = signal.getsignal(signal.SIGINT)
    try:
        install_ctrl_c_handler()
        window = QWidget()
        window.show()
        qtbot.addWidget(window)
        signal.raise_signal(signal.SIGINT)
        qtbot.waitUntil(lambda: not window.isVisible(), timeout=3000)
    finally:
        signal.signal(signal.SIGINT, previous)  # keep Ctrl+C working for pytest
        qgis_app._ctrl_c_timer.stop()


def test_keyboard_interrupt_in_a_slot_is_not_an_error(qgis_app, qtbot, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox, QWidget

    from vgeoint.common import bootstrap

    boxes = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: boxes.append(a))
    previous = sys.excepthook
    try:
        bootstrap.install_exception_hook("vGeoInt_test")
        window = QWidget()
        window.show()
        qtbot.addWidget(window)
        try:
            raise KeyboardInterrupt
        except KeyboardInterrupt:
            sys.excepthook(*sys.exc_info())
        assert not window.isVisible() and boxes == []
    finally:
        sys.excepthook = previous
