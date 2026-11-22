"""The client's own log: %LOCALAPPDATA%\\7HillsLink\\link.log (rotated at 1 MB, 2 old files kept).

Also records uncaught Python errors in any thread and, through faulthandler,
native crashes (for example inside gRPC) that would otherwise close the app
without a trace.
"""

from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import sys
import threading

from .paths import data_dir

log = logging.getLogger("7hillslink")
_crash_file = None


def setup() -> None:
    global _crash_file
    if log.handlers:
        return
    path = data_dir() / "link.log"
    h = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    try:
        _crash_file = open(data_dir() / "crash.log", "a", encoding="utf-8")
        faulthandler.enable(_crash_file)
    except OSError:
        pass

    def on_error(exc_type, exc, tb):
        log.error("uncaught error", exc_info=(exc_type, exc, tb))
    sys.excepthook = on_error

    def on_thread_error(args):
        log.error("uncaught error in thread %s", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = on_thread_error
