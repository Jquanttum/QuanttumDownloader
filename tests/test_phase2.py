"""Phase 2 checks. Run from the project root:  python tests/test_phase2.py"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
os.environ.setdefault("QUANTTUM_HOME", tempfile.mkdtemp(prefix="qd_home_"))
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QCoreApplication, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import app.workers as workers
from app.errors import GENERIC_MESSAGE, friendly_message
from app.media_info import MediaInfo, build_media_info

QCoreApplication.setOrganizationName("QuanttumTest")


def wait_until(app: QApplication, cond, timeout: float = 20.0) -> None:
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond(), "timed out"


def test_pure() -> None:
    video = {
        "title": "Demo", "channel": "Chan", "duration": 125, "thumbnail": "https://x/t.jpg",
        "extractor_key": "Youtube", "subtitles": {"en": [], "fr": []},
        "formats": [
            {"height": 1080, "vcodec": "avc1", "acodec": "none"},
            {"height": 720, "vcodec": "avc1", "acodec": "mp4a"},
            {"height": 720, "vcodec": "vp9", "acodec": "none"},
            {"height": None, "vcodec": "none", "acodec": "opus"},
        ],
    }
    m = build_media_info("https://y/v", video)
    assert m.video_heights == [1080, 720] and m.has_audio and m.duration_seconds == 125
    assert m.subtitle_langs == ["en", "fr"] and not m.is_playlist

    audio_only = build_media_info("u", {"title": "A", "formats": [{"vcodec": "none", "acodec": "opus"}]})
    assert audio_only.video_heights == [] and audio_only.has_audio

    pl = build_media_info("u", {"_type": "playlist", "title": "P", "uploader": "U",
                                "entries": [{"thumbnail": "https://x/1.jpg"}, None, {"id": "b"}]})
    assert pl.is_playlist and pl.entry_count == 2 and pl.thumbnail_url.endswith("1.jpg")

    cases = {
        "ERROR: Private video. Sign in": "private",
        "Sign in to confirm your age": "age-restricted",
        "Unsupported URL: https://x": "supported",
        "Video unavailable": "unavailable",
        "HTTP Error 429: Too Many Requests": "rate-limiting",
        "<urlopen error [Errno -3] Temporary failure in name resolution>": "internet",
    }
    for text, needle in cases.items():
        assert needle in friendly_message(Exception(text)), text
    assert friendly_message(Exception("weird")) == GENERIC_MESSAGE
    print("pure helpers OK")


def png_bytes() -> bytes:
    img = QImage(320, 180, QImage.Format.Format_RGB32)
    img.fill(QColor("#c0392b"))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def test_gui() -> None:
    from app.config import Settings
    from ui.main_window import MainWindow
    from ui.styles import apply_theme

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app, "dark")
    win = MainWindow(Settings())
    win.resize(1200, 780)
    win.show()
    home = win.home
    shots = ROOT / "tests" / "shots"
    shots.mkdir(exist_ok=True)

    # 1) success path with mocked extractor + thumbnail
    workers.analyse_url = lambda url: MediaInfo(
        url=url, title="A Demo Video About Forensic Science", channel="Quanttum Labs",
        duration_seconds=754, thumbnail_url="https://x/t.jpg",
        video_heights=[2160, 1080, 720, 480, 360], subtitle_langs=["en", "fr"], extractor="Youtube")
    workers.fetch_thumbnail = lambda url: png_bytes()
    home.url_input.setText("https://www.youtube.com/watch?v=demo")
    home._on_analyse()
    assert not home.analyse_btn.isEnabled() and home.analyse_btn.text() == "Analysing…"
    wait_until(app, lambda: home.current_media is not None)
    assert home.analyse_btn.isEnabled() and home.analyse_btn.text() == "Analyse"
    assert home.preview.title.text().startswith("A Demo Video")
    assert home.preview.thumb._pixmap is not None
    app.processEvents()
    win.grab().save(str(shots / "analysed.png"))
    print("success path OK")

    # 2) failure path with a private-video style error
    def boom(url: str):
        raise RuntimeError("ERROR: [youtube] abc: Private video. Sign in if you've been granted access")

    workers.analyse_url = boom
    home.url_input.setText("https://www.youtube.com/watch?v=priv")
    home._on_analyse()
    wait_until(app, lambda: home.analyse_btn.isEnabled())
    assert "private" in home.error_label.text().lower() and home.error_label.isVisible()
    print("failure path OK")

    # 3) stale result is ignored (token mismatch)
    home._token += 5
    before = home.preview.title.text()
    home._on_analysis_done(1, MediaInfo(url="u", title="STALE"), None)
    assert home.preview.title.text() == before
    print("stale result ignored OK")

    win.close()


def test_real_network_error() -> None:
    """The real yt-dlp path must turn a network failure into a friendly message, not a traceback."""
    import importlib

    importlib.reload(workers)
    import app.media_info as mi

    try:
        mi.analyse_url("https://nonexistent-host.invalid/watch?v=1")
    except Exception as exc:  # noqa: BLE001
        msg = friendly_message(exc)
        print("real error ->", msg)
        assert msg != "" and "Traceback" not in msg
    else:
        raise AssertionError("expected an error")


if __name__ == "__main__":
    test_pure()
    test_gui()
    test_real_network_error()
    print("ALL OK")
