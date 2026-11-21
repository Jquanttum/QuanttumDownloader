"""About page: version, runtime details and responsible-use notice."""

from __future__ import annotations

import platform
import sys

import PySide6
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.config import APP_NAME, APP_VERSION, DATA_DIR, LOGS_DIR, Settings, ensure_dirs, get_ytdlp_version, resolve_ffmpeg
from ui.widgets import BasePage, Card, divider, logo_pixmap, make_label, secondary_button


def _kv_row(key: str, value: str) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 8, 0, 8)
    lay.setSpacing(16)
    k = make_label(key, "Dim")
    k.setFixedWidth(110)
    v = make_label(value, "RowTitle", wrap=True)
    from PySide6.QtCore import Qt
    v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lay.addWidget(k)
    lay.addWidget(v, 1)
    return row


class AboutPage(BasePage):
    """Static information about the application and its environment."""

    def __init__(self, settings: Settings) -> None:
        super().__init__("About")
        header = QHBoxLayout()
        header.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(64))
        logo.setFixedSize(64, 64)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(make_label(APP_NAME, "MediaTitle"))
        text.addWidget(make_label(f"Version {APP_VERSION} · by Quanttum", "Subtitle"))
        header.addWidget(logo)
        header.addLayout(text, 1)
        self.body.addLayout(header)

        ffmpeg = resolve_ffmpeg(settings.ffmpeg_path)
        runtime = Card()
        rl = QVBoxLayout(runtime)
        rl.setContentsMargins(22, 18, 22, 12)
        rl.setSpacing(0)
        rl.addWidget(make_label("Runtime", "CardTitle"))
        rows = [
            ("Python", f"{platform.python_version()} ({platform.system()} {platform.release()})"),
            ("PySide6", PySide6.__version__),
            ("yt-dlp", get_ytdlp_version() or "Not installed"),
            ("FFmpeg", str(ffmpeg) if ffmpeg else "Not found"),
            ("Data folder", str(DATA_DIR)),
            ("Log folder", str(LOGS_DIR)),
        ]
        for i, (k, v) in enumerate(rows):
            if i:
                rl.addWidget(divider())
            rl.addWidget(_kv_row(k, v))
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 10, 0, 6)
        open_logs = secondary_button("Open log folder", "folder")
        open_data = secondary_button("Open data folder", "folder")
        open_logs.clicked.connect(lambda: self._open(LOGS_DIR))
        open_data.clicked.connect(lambda: self._open(DATA_DIR))
        buttons.addWidget(open_logs)
        buttons.addWidget(open_data)
        buttons.addStretch(1)
        rl.addLayout(buttons)
        self.body.addWidget(runtime)

        notice = Card()
        nl = QVBoxLayout(notice)
        nl.setContentsMargins(22, 18, 22, 18)
        nl.setSpacing(6)
        nl.addWidget(make_label("Responsible use", "CardTitle"))
        nl.addWidget(make_label(
            "Quanttum Downloader is intended for content you own, content in the public domain, "
            "or content you have permission to download. You are responsible for following the "
            "terms of service of the sites you use and applicable copyright law.",
            "Subtitle", wrap=True))
        self.body.addWidget(notice)
        self.body.addStretch(1)

    @staticmethod
    def _open(path) -> None:
        ensure_dirs()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
