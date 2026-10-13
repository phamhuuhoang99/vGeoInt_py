"""Machine-readable events for the GUI (see vgeoint.ai.runner).

Scripts call e.g. `progress(42, "Đang xử lý")` or `result(output="out.shp", count=12)`. Each call prints
one line `@@VGEOINT {"type": ..., ...}`; the GUI parses these instead of matching free text.
Works stand-alone too (the line is just extra output on the console).
"""

import json
import sys

EVENT_PREFIX = "@@VGEOINT "


def emit(event_type: str, **data):
    payload = {"type": event_type, **data}
    sys.stdout.write(EVENT_PREFIX + json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def progress(value: float, message: str = "", **data):
    """value in percent (0-100); extra fields (e.g. frame=12) are passed through."""
    emit("progress", value=value, message=message, **data)


def result(**data):
    """Final results: output paths, counts, timings, statistics."""
    emit("result", **data)


def error(message: str):
    emit("error", message=message)
