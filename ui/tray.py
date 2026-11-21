"""System tray icon: keeps the app running in the background and shows notifications."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from app.config import APP_NAME, Settings
from app.manager import DownloadManager
from app.signals import signals

log = logging.getLogger("quanttum.tray")


class TrayController(QObject):
    """Owns the one tray icon. It is permanent when "Keep running in the tray" is on, and otherwise
    appears briefly to show a notification."""

    def __init__(self, window: QWidget, manager: DownloadManager, settings: Settings) -> None:
        super().__init__(window)
        self.window, self.manager, self.settings = window, manager, settings
        self.icon: QSystemTrayIcon | None = None
        self._told = False
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self._maybe_hide)
        self.quit_requested = None   # callable set by the main window
        signals.setting_changed.connect(lambda key, _v: self.sync() if key == "close_to_tray" else None)
        manager.queue_changed.connect(self._refresh_menu)
        self.sync()

    # -- state ---------------------------------------------------------------
    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def persistent(self) -> bool:
        return bool(self.settings.get("close_to_tray")) and self.available()

    def _ensure(self) -> QSystemTrayIcon | None:
        if not self.available():
            return None
        if self.icon is None:
            self.icon = QSystemTrayIcon(self.window.windowIcon(), self)
            self.icon.setToolTip(APP_NAME)
            self.menu = QMenu()
            self.act_show = QAction(f"Show {APP_NAME}", self.menu)
            self.act_queue = QAction("", self.menu)
            self.act_quit = QAction("Quit", self.menu)
            for act in (self.act_show, self.act_queue):
                self.menu.addAction(act)
            self.menu.addSeparator()
            self.menu.addAction(self.act_quit)
            self.act_show.triggered.connect(self.show_window)
            self.act_queue.triggered.connect(self._toggle_queue)
            self.act_quit.triggered.connect(self._quit)
            self.icon.setContextMenu(self.menu)
            self.icon.activated.connect(self._activated)
            self.icon.messageClicked.connect(self.show_window)
            self._refresh_menu()
        return self.icon

    def sync(self) -> None:
        """Show or hide the permanent icon to match the setting."""
        if self.persistent():
            icon = self._ensure()
            if icon:
                icon.show()
        elif self.icon is not None and not self._hide.isActive():
            self.icon.hide()

    # -- actions ---------------------------------------------------------------
    def should_hide_on_close(self) -> bool:
        return self.persistent()

    def hide_to_tray(self) -> None:
        self.window.hide()
        icon = self._ensure()
        if icon and not self._told:
            self._told = True
            icon.showMessage(APP_NAME, "Still running in the tray. Downloads continue; use the tray icon to "
                             "open or quit.", QSystemTrayIcon.MessageIcon.Information, 5000)

    def show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def message(self, title: str, text: str) -> None:
        icon = self._ensure()
        if icon is None:
            log.info("No system tray available; skipping notification: %s", title)
            return
        icon.show()
        icon.showMessage(f"{APP_NAME} — {title}", text, QSystemTrayIcon.MessageIcon.Information, 6000)
        self._hide.start(12000)

    def _maybe_hide(self) -> None:
        if self.icon is not None and not self.persistent():
            self.icon.hide()

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def _toggle_queue(self) -> None:
        if self.manager.queue_running:
            self.manager.stop_queue()
        else:
            self.manager.start_queue()

    def _refresh_menu(self) -> None:
        if self.icon is None:
            return
        n = self.manager.active_count()
        self.act_queue.setText("Stop queue" if self.manager.queue_running else "Start queue")
        self.icon.setToolTip(f"{APP_NAME} — {n} download{'s' if n != 1 else ''} running" if n else APP_NAME)

    def _quit(self) -> None:
        if self.quit_requested:
            self.quit_requested()
