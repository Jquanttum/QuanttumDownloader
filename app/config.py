"""Application configuration: paths, logging, persistent settings, tool detection."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from importlib import metadata
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings

APP_NAME = "Quanttum Downloader"
ORG_NAME = "Quanttum"
APP_VERSION = "0.1.0"

FROZEN: bool = bool(getattr(sys, "frozen", False))
RESOURCE_DIR: Path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def _user_root() -> Path:
    """Where writable data lives: project folder in dev, %LOCALAPPDATA% when packaged.

    ``QUANTTUM_HOME`` overrides it (used by the tests so they never touch real data).
    """
    override = os.environ.get("QUANTTUM_HOME")
    if override:
        return Path(override)
    if FROZEN:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "QuanttumDownloader"
    return Path(__file__).resolve().parent.parent


USER_ROOT: Path = _user_root()
DATA_DIR: Path = USER_ROOT / "data"
LOGS_DIR: Path = USER_ROOT / "logs"
DB_PATH: Path = DATA_DIR / "downloads.db"
LOG_FILE: Path = LOGS_DIR / "quanttum.log"
QUEUE_FILE: Path = DATA_DIR / "queue.json"
ARCHIVE_PATH: Path = DATA_DIR / "downloaded_ids.txt"   # ids of videos already downloaded (skip-duplicates option)

VIDEO_QUALITIES: list[str] = [
    "Best available", "2160p (4K)", "1440p", "1080p", "720p", "480p", "360p",
]
AUDIO_FORMATS: list[str] = ["MP3", "M4A", "WAV"]
THEMES: tuple[str, ...] = ("dark", "light", "system")
MAX_CONCURRENT_LIMIT = 6

DEFAULTS: dict[str, Any] = {
    "theme": "dark",
    "download_dir": str(Path.home() / "Downloads" / "Quanttum"),
    "max_concurrent": 2,
    "video_quality": "Best available",
    "audio_format": "MP3",
    "clipboard_detection": True,
    "notifications": True,
    "keep_history": True,
    "embed_metadata": True,
    "ffmpeg_path": "",
    "cookies_mode": "Off",
    "cookies_browser": "Chrome",
    "cookies_file": "",
    "speed_limit": "Unlimited",
    "schedule_enabled": False,
    "schedule_start": "01:00",
    "schedule_end": "06:00",
    "name_template": "Title",
    "folder_layout": "Flat",
    "auto_queue": False,
    "check_updates": True,
    "last_update_check": 0,
    "close_to_tray": False,
}


def ensure_dirs() -> None:
    """Create the data and log directories if they do not exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging() -> logging.Logger:
    """Configure rotating file logging and return the application logger."""
    ensure_dirs()
    logger = logging.getLogger("quanttum")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    if not FROZEN:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        logger.addHandler(console)
    return logger


class Settings:
    """Typed wrapper around QSettings with validated defaults."""

    def __init__(self) -> None:
        self._qs = QSettings(ORG_NAME, "QuanttumDownloader")

    # -- generic access ---------------------------------------------------
    def get(self, key: str) -> Any:
        default = DEFAULTS[key]
        if isinstance(default, bool):
            return self._qs.value(key, default, type=bool)
        if isinstance(default, int):
            return self._qs.value(key, default, type=int)
        return str(self._qs.value(key, default))

    def set(self, key: str, value: Any) -> None:
        self._qs.setValue(key, value)

    # -- validated properties --------------------------------------------
    @property
    def theme(self) -> str:
        value = self.get("theme")
        return value if value in THEMES else DEFAULTS["theme"]

    @property
    def download_dir(self) -> str:
        return self.get("download_dir") or DEFAULTS["download_dir"]

    @property
    def max_concurrent(self) -> int:
        return max(1, min(MAX_CONCURRENT_LIMIT, self.get("max_concurrent")))

    @property
    def video_quality(self) -> str:
        value = self.get("video_quality")
        return value if value in VIDEO_QUALITIES else DEFAULTS["video_quality"]

    @property
    def audio_format(self) -> str:
        value = self.get("audio_format")
        return value if value in AUDIO_FORMATS else DEFAULTS["audio_format"]

    @property
    def clipboard_detection(self) -> bool:
        return self.get("clipboard_detection")

    @property
    def notifications(self) -> bool:
        return self.get("notifications")

    @property
    def cookie_source(self) -> tuple[str, str]:
        """(browser, cookies_file) to use for sign-in cookies; both empty when disabled."""
        from app.cookies import cookie_settings

        return cookie_settings(self.get("cookies_mode"), self.get("cookies_browser"), self.get("cookies_file"))

    @property
    def keep_history(self) -> bool:
        return self.get("keep_history")

    @property
    def embed_metadata(self) -> bool:
        return self.get("embed_metadata")

    @property
    def ffmpeg_path(self) -> str:
        return self.get("ffmpeg_path")

    # -- window geometry --------------------------------------------------
    def load_geometry(self) -> Any:
        return self._qs.value("window_geometry")

    def save_geometry(self, data: Any) -> None:
        self._qs.setValue("window_geometry", data)


def _bundled_ffmpeg_dirs() -> list[Path]:
    """Folders where a copy of FFmpeg shipped with the app may live (next to the exe / project)."""
    dirs = [RESOURCE_DIR / "ffmpeg", RESOURCE_DIR / "ffmpeg" / "bin"]
    if FROZEN:
        exe_dir = Path(sys.executable).resolve().parent
        dirs = [exe_dir / "ffmpeg", exe_dir / "ffmpeg" / "bin", exe_dir, *dirs]
    return dirs


def resolve_ffmpeg(configured: str = "") -> Path | None:
    """Locate FFmpeg: the configured path, then a copy shipped with the app, then PATH."""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if configured:
        candidate = Path(configured)
        if candidate.is_dir():
            candidate = candidate / exe
        return candidate if candidate.is_file() else None
    for folder in _bundled_ffmpeg_dirs():
        candidate = folder / exe
        if candidate.is_file():
            return candidate
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def get_ytdlp_version() -> str | None:
    """Return the installed yt-dlp version, or None if it is not installed."""
    try:
        return metadata.version("yt-dlp")
    except metadata.PackageNotFoundError:
        return None
