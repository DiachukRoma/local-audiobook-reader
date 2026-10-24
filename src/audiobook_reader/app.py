"""Application entry point: ``python -m audiobook_reader``."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .storage.settings import DEFAULT_DATA_DIR, RESOURCE_ROOT


def _setup_logging(data_dir: Path) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Third-party libraries can be chatty; book text is never logged by this application.
    for noisy in ("supertonic", "httpx", "huggingface_hub", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _set_macos_app_name(name: str) -> None:
    """Show ``name`` instead of "Python" in the macOS menu bar (best effort, via the ObjC runtime)."""
    if sys.platform != "darwin":
        return
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        send = objc.objc_msgSend
        msg0 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(ctypes.cast(send, ctypes.c_void_p).value)
        msg_str = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)(
            ctypes.cast(send, ctypes.c_void_p).value)
        msg_set = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
            ctypes.cast(send, ctypes.c_void_p).value)
        sel = objc.sel_registerName
        bundle = msg0(objc.objc_getClass(b"NSBundle"), sel(b"mainBundle"))
        info = msg0(bundle, sel(b"infoDictionary"))
        ns_string = objc.objc_getClass(b"NSString")
        value = msg_str(ns_string, sel(b"stringWithUTF8String:"), name.encode())
        key = msg_str(ns_string, sel(b"stringWithUTF8String:"), b"CFBundleName")
        if info and value and key:
            msg_set(info, sel(b"setObject:forKey:"), value, key)
    except Exception:  # purely cosmetic
        logging.getLogger(__name__).debug("Could not set macOS app name", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # Privacy: no Hugging Face telemetry; model loading is offline (download only on explicit request).
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")

    data_dir = Path(os.environ.get("AUDIOBOOK_READER_DATA", DEFAULT_DATA_DIR))
    data_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(data_dir)
    log = logging.getLogger("audiobook_reader")
    log.info("Starting Local Audiobook Reader")

    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .ui.main_window import APP_NAME, MainWindow

    class Application(QApplication):
        """Receives files opened from Finder ("Open With", dropping onto the Dock icon)."""
        window: MainWindow | None = None
        pending: list[Path] = []

        def event(self, event):  # noqa: N802 (Qt API)
            if event.type() == QEvent.FileOpen:
                path = Path(event.file())
                if self.window is not None:
                    self.window.open_path(path)
                else:
                    self.pending.append(path)
                return True
            return super().event(event)

    _set_macos_app_name(APP_NAME)
    app = Application(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("Local")
    icon_path = RESOURCE_ROOT / "assets" / "icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow(data_dir)
    app.window = window
    window.show()
    for path in app.pending:
        window.open_path(path)
    # A document path may be passed on the command line (or by Finder via the .app launcher).
    for arg in argv[1:]:
        if not arg.startswith("-") and Path(arg).is_file():
            window.open_path(Path(arg))
            break
    code = app.exec()
    log.info("Exited with code %s", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
