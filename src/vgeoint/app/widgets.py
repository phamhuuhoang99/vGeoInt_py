"""Custom widgets promoted in the .ui files of this app (re-exported for uic)."""

from vgeoint.app.filter_widgets import (  # noqa: F401 - promoted in ImageFilterDialog.ui
    AveragingWidget,
    CannyWidget,
    GaussianWidget,
    MedianWidget,
    ScharrWidget,
    SobelWidget,
)
