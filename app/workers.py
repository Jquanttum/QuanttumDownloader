"""Background workers. Nothing here touches widgets; results travel via signals."""

from __future__ import annotations

import logging
import urllib.request

from PySide6.QtCore import QObject, QRunnable, Signal

from app.errors import friendly_message
from app.media_info import MediaInfo, analyse_url

log = logging.getLogger("quanttum.workers")

_MAX_THUMB_BYTES = 5_000_000


def fetch_thumbnail(url: str) -> bytes | None:
    """Download a thumbnail (size-capped, https/http only). Returns None on any failure."""
    if not url.lower().startswith(("http://", "https://")):
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - scheme checked above
            data = response.read(_MAX_THUMB_BYTES + 1)
        return data if 0 < len(data) <= _MAX_THUMB_BYTES else None
    except Exception:
        log.info("Thumbnail download failed for %s", url, exc_info=True)
        return None


class AnalyseSignals(QObject):
    """Signals for :class:`AnalyseWorker`. Owned by the UI so it outlives the runnable."""

    finished = Signal(int, object, object)  # token, MediaInfo, thumbnail bytes | None
    failed = Signal(int, str)               # token, friendly message


class AnalyseWorker(QRunnable):
    """Extracts metadata and thumbnail for one URL off the GUI thread."""

    def __init__(self, url: str, token: int, signals: AnalyseSignals,
                 cookies_browser: str = "", cookies_file: str = "") -> None:
        super().__init__()
        self.url, self.token, self.signals = url, token, signals
        self.cookies = (cookies_browser, cookies_file)

    def run(self) -> None:
        try:
            info: MediaInfo = analyse_url(self.url, *self.cookies)
        except Exception as exc:  # noqa: BLE001 - anything yt-dlp raises becomes a friendly message
            log.warning("Analysis failed for %s: %s", self.url, exc, exc_info=True)
            self.signals.failed.emit(self.token, friendly_message(exc))
            return
        thumb = fetch_thumbnail(info.thumbnail_url) if info.thumbnail_url else None
        self.signals.finished.emit(self.token, info, thumb)


class BatchSignals(QObject):
    """Signals for :class:`BatchWorker`."""

    item = Signal(int, str, object, object, str)  # batch id, url, MediaInfo|None, thumbnail|None, friendly error
    finished = Signal(int)                         # batch id


class BatchWorker(QRunnable):
    """Analyses many links one after another (one at a time keeps CPU and network use low)."""

    def __init__(self, batch_id: int, urls: list[str], signals: BatchSignals,
                 cookies_browser: str = "", cookies_file: str = "") -> None:
        super().__init__()
        self.batch_id, self.urls, self.signals = batch_id, urls, signals
        self.cookies = (cookies_browser, cookies_file)
        self.cancelled = False

    def run(self) -> None:
        for url in self.urls:
            if self.cancelled:
                break
            try:
                info = analyse_url(url, *self.cookies)
            except Exception as exc:  # noqa: BLE001
                log.warning("Batch analysis failed for %s: %s", url, exc, exc_info=True)
                self.signals.item.emit(self.batch_id, url, None, None, friendly_message(exc))
                continue
            thumb = fetch_thumbnail(info.thumbnail_url) if info.thumbnail_url else None
            self.signals.item.emit(self.batch_id, url, info, thumb, "")
        self.signals.finished.emit(self.batch_id)
