"""Main application window: sidebar + stacked pages."""

from __future__ import annotations

import logging
import sqlite3
import sys

from PySide6.QtCore import QPropertyAnimation
from PySide6.QtGui import QCloseEvent, QIcon, QShowEvent
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect, QHBoxLayout, QMainWindow, QStackedWidget, QWidget,
)

from app.config import APP_NAME, Settings
from app.history import HistoryDB, HistoryRecorder
from app.manager import DownloadManager
from app.notify import Notifier
from app.signals import signals
from ui.about_page import AboutPage
from ui.dialogs import confirm
from ui.downloads_page import DownloadsPage
from ui.history_page import HistoryPage
from ui.home_page import HomePage
from ui.queue_page import QueuePage
from ui.settings_page import SettingsPage
from ui.sidebar import Page, Sidebar
from ui.styles import current_theme
from ui.widgets import logo_pixmap

log = logging.getLogger("quanttum.window")


class MainWindow(QMainWindow):
    """Top-level window hosting navigation and all pages."""

    def __init__(self, settings: Settings, history_db: HistoryDB | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.history_db = history_db or self._open_history()
        self._anim: QPropertyAnimation | None = None

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(logo_pixmap(256)))
        self.setMinimumSize(980, 640)
        self.resize(1200, 780)
        geometry = settings.load_geometry()
        if geometry:
            self.restoreGeometry(geometry)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.manager = DownloadManager(settings, self)
        self.recorder = HistoryRecorder(self.history_db, self.manager, settings, self)
        self.notifier = Notifier(settings, self, self.manager)
        self.sidebar = Sidebar()
        self.stack = QStackedWidget()
        self.home = HomePage(settings, self.manager)
        pages: list[QWidget] = [
            self.home, DownloadsPage(self.manager), QueuePage(self.manager),
            HistoryPage(self.history_db, self.recorder, self.manager),
            SettingsPage(settings), AboutPage(settings),
        ]
        for page in pages:
            self.stack.addWidget(page)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)

        self.sidebar.page_requested.connect(self.show_page)
        signals.navigate.connect(self.show_page)
        signals.theme_changed.connect(self._on_theme_changed)
        self.sidebar.set_current(Page.HOME)

    @staticmethod
    def _open_history() -> HistoryDB:
        """Open the history database; if the file is unusable keep running with a temporary one."""
        try:
            return HistoryDB()
        except sqlite3.Error:
            log.exception("History database could not be opened; history won't be saved this session")
            return HistoryDB(":memory:")

    def show_page(self, index: int) -> None:
        """Switch to ``index`` with a short fade-in."""
        if index == self.stack.currentIndex():
            return
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        self.stack.setCurrentIndex(index)
        self.sidebar.set_current(index)
        page = self.stack.currentWidget()
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(140)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(lambda p=page, a=anim: self._finish_fade(p, a))
        self._anim = anim
        anim.start()

    def _finish_fade(self, page: QWidget, anim: QPropertyAnimation) -> None:
        """Remove the temporary opacity effect (it costs CPU) and release the animation."""
        page.setGraphicsEffect(None)
        if self._anim is anim:
            self._anim = None
        anim.deleteLater()

    # -- theme / native chrome ---------------------------------------------
    def _on_theme_changed(self, theme: str) -> None:
        self._apply_titlebar(theme == "dark")

    def _apply_titlebar(self, dark: bool) -> None:
        """Match the Windows title bar to the theme (no-op elsewhere)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            value = ctypes.c_int(1 if dark else 0)
            for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old id)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
                ) == 0:
                    break
        except Exception:  # pragma: no cover - cosmetic only
            log.debug("Could not set title bar theme", exc_info=True)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_titlebar(current_theme() == "dark")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        active = self.manager.active_count()
        if active and not confirm(
            self, "Downloads in progress",
            f"{active} download{'s are' if active != 1 else ' is'} still running. "
            "Quit anyway? Partial files are kept, so you can resume them next time.",
        ):
            event.ignore()
            return
        self.settings.save_geometry(self.saveGeometry())
        self.home.shutdown()
        self.manager.shutdown()
        self.history_db.close()
        super().closeEvent(event)
