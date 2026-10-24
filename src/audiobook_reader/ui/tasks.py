"""Run blocking work in a background thread and deliver the result on the GUI thread."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)
_running: set["BackgroundTask"] = set()


class BackgroundTask(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    progress = Signal(int, int)

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs
        self.cancel_event = threading.Event()

    def start(self) -> "BackgroundTask":
        _running.add(self)
        threading.Thread(target=self._run, daemon=True, name="bg-task").start()
        return self

    def _run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except BaseException as exc:  # reported to the GUI, never swallowed silently
            if not isinstance(exc, Exception):
                log.warning("Background task interrupted: %r", exc)
            else:
                log.info("Background task failed: %s", type(exc).__name__)
            self.failed.emit(exc)
        else:
            self.succeeded.emit(result)
        finally:
            _running.discard(self)


def run_background(fn: Callable, *args, on_success: Callable | None = None,
                   on_error: Callable | None = None, **kwargs) -> BackgroundTask:
    task = BackgroundTask(fn, *args, **kwargs)
    if on_success:
        task.succeeded.connect(on_success)
    if on_error:
        task.failed.connect(on_error)
    return task.start()
