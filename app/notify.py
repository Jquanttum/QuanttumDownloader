"""Desktop notifications for finished/failed downloads (system tray balloon)."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QWidget

from app.config import APP_NAME, Settings

log = logging.getLogger("quanttum.notify")


class Notifier(QObject):
    """Shows a notification when a download ends and the window isn't in front."""

    def __init__(self, settings: Settings, window: QWidget, manager: QObject) -> None:
        super().__init__(window)
        self.settings, self.window = settings, window
        self._tray: QSystemTrayIcon | None = None
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self._hide_tray)
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
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.info("No system tray available; skipping notification: %s", title)
            return
        if self._tray is None:
            self._tray = QSystemTrayIcon(self.window.windowIcon() or QIcon(), self)
            self._tray.messageClicked.connect(self._raise_window)
        self._tray.show()
        self._tray.showMessage(f"{APP_NAME} — {title}", text, QSystemTrayIcon.MessageIcon.Information, 6000)
        self._hide.start(12000)

    def _hide_tray(self) -> None:
        if self._tray:
            self._tray.hide()

    def _raise_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
