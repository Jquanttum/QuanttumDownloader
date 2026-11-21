"""yt-dlp version check and update (network work happens off the GUI thread)."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import urllib.request

from PySide6.QtCore import QObject, QRunnable, Signal

from app.config import FROZEN, get_ytdlp_version

log = logging.getLogger("quanttum.updater")
PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def is_newer(latest: str, installed: str | None) -> bool:
    if not installed:
        return True
    try:
        return version_key(latest) > version_key(installed)
    except ValueError:
        return False


def latest_ytdlp_version(timeout: float = 10.0) -> str:
    """Latest yt-dlp release on PyPI. Raises OSError / ValueError on problems."""
    with urllib.request.urlopen(PYPI_URL, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
        data = json.load(resp)
    return str(data["info"]["version"])


def update_ytdlp() -> tuple[bool, str]:
    """Run ``pip install -U yt-dlp``. Returns (ok, short message)."""
    if FROZEN:
        return False, ("This packaged app can't update itself. Download the newest Quanttum Downloader "
                       "release to get the latest yt-dlp.")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.SubprocessError):
        log.exception("pip failed to start")
        return False, "Couldn't run pip. Update manually with: pip install -U yt-dlp"
    if proc.returncode != 0:
        log.error("pip install -U yt-dlp failed:\n%s", proc.stderr or proc.stdout)
        return False, "The update failed. Check your internet connection or run: pip install -U yt-dlp"
    return True, "yt-dlp was updated. Restart Quanttum Downloader to use the new version."


class UpdateSignals(QObject):
    checked = Signal(object, str)   # latest version (or None), friendly error ("" if ok)
    updated = Signal(bool, str)     # ok, message


class CheckWorker(QRunnable):
    def __init__(self, sig: UpdateSignals) -> None:
        super().__init__()
        self.sig = sig

    def run(self) -> None:
        try:
            self.sig.checked.emit(latest_ytdlp_version(), "")
        except Exception:  # noqa: BLE001
            log.warning("yt-dlp version check failed", exc_info=True)
            self.sig.checked.emit(None, "Couldn't check for updates. Are you online?")


class UpdateWorker(QRunnable):
    def __init__(self, sig: UpdateSignals) -> None:
        super().__init__()
        self.sig = sig

    def run(self) -> None:
        ok, message = update_ytdlp()
        self.sig.updated.emit(ok, message)


__all__ = ["CheckWorker", "UpdateWorker", "UpdateSignals", "is_newer", "latest_ytdlp_version",
           "update_ytdlp", "get_ytdlp_version"]
