"""Desktop notifications for finished/failed downloads (system tray balloon)."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QWidget

from app.config import Settings

log = logging.getLogger("quanttum.notify")


class Notifier(QObject):
    """Shows a notification when a download ends and the window isn't in front."""

    def __init__(self, settings: Settings, window: QWidget, manager: QObject) -> None:
        super().__init__(window)
        self.settings, self.window = settings, window
        manager.job_completed.connect(lambda j: self.notify("Download finished", j.title))
        manager.job_failed.connect(lambda j: self.notify("Download failed", f"{j.title}\n{j.error}"))

    def should_notify(self) -> bool:
        if not self.settings.notifications:
            return False
        app = QApplication.instance()
        return not (self.window.isActiveWindow() and app is not None and app.applicationState().name == "ApplicationActive")

    def notify(self, title: str, text: str) -> bool:
        if not self.should_notify():
            return False
        self._emit(title, text)
        return True

    def _emit(self, title: str, text: str) -> None:
        tray = getattr(self.window, "tray", None)
        if tray is not None:
            tray.message(title, text)
        else:
            log.info("No tray controller; skipping notification: %s", title)
