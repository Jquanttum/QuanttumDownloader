"""Quanttum Downloader entry point."""

from __future__ import annotations

import logging
import sys
import threading

from PySide6.QtCore import QLockFile, Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from app.config import APP_NAME, DATA_DIR, ORG_NAME, Settings, ensure_dirs, setup_logging


def _install_excepthook(log: logging.Logger) -> None:
    """Log unhandled exceptions and show a friendly message instead of a traceback."""

    def hook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        log.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        try:
            from ui.dialogs import show_error

            show_error(None, "Unexpected error",
                       "Something went wrong. The details were saved to the log file.")
        except Exception:  # pragma: no cover
            pass

    sys.excepthook = hook

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        log.error("Unhandled exception in thread %s", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    threading.excepthook = thread_hook

    levels = {QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}

    def qt_handler(kind, _context, message) -> None:  # type: ignore[no-untyped-def]
        if kind in levels:
            log.log(levels[kind], "Qt: %s", message)

    qInstallMessageHandler(qt_handler)


def acquire_single_instance() -> QLockFile | None:
    """Return a held lock, or None if another copy of the app is already running."""
    ensure_dirs()
    lock = QLockFile(str(DATA_DIR / "app.lock"))
    lock.setStaleLockTime(0)  # a lock left by a crashed run is reclaimed automatically
    return lock if lock.tryLock(100) else None


def main() -> int:
    log = setup_logging()
    _install_excepthook(log)

    if sys.platform == "win32":
        try:  # own taskbar identity so the icon isn't grouped under python.exe
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Quanttum.Downloader")
        except Exception:
            log.debug("Could not set AppUserModelID", exc_info=True)

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    from ui.dialogs import show_error
    from ui.main_window import MainWindow
    from ui.styles import apply_theme

    lock = acquire_single_instance()
    if lock is None:
        show_error(None, APP_NAME, "Quanttum Downloader is already running. Check your taskbar.")
        return 0

    settings = Settings()
    apply_theme(app, settings.theme)
    window = MainWindow(settings)
    window.show()
    log.info("Quanttum Downloader started")
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
