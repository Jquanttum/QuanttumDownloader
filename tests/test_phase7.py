"""Phase 7 checks: layout regressions (clipped text), scrolling, resilience, FFmpeg lookup, budgets.

    python tests/test_phase7.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_phase3 as t3  # noqa: E402  (sets env, QUANTTUM_HOME, sys.path)

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QScrollArea  # noqa: E402

from app.config import Settings, resolve_ffmpeg  # noqa: E402
from app.history import HistoryDB  # noqa: E402
from app.media_info import MediaInfo  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.styles import apply_theme  # noqa: E402
from ui.widgets import ScrollSafeComboBox  # noqa: E402


def settle(app, seconds=0.25):
    for _ in range(15):
        app.processEvents()
    time.sleep(seconds)
    app.processEvents()


def clipped(page) -> list[str]:
    """Wrapped labels that need more height than they have, and placeholders wider than their field."""
    problems = []
    for lab in page.findChildren(QLabel):
        if not lab.isVisibleTo(page) or not lab.text() or not lab.wordWrap():
            continue
        need = QFontMetrics(lab.font()).boundingRect(0, 0, max(lab.width(), 1), 10000, 0x1000 | 0x0010,
                                                     lab.text()).height()
        if need > lab.height() + 1:
            problems.append(f"wrapped text clipped: {lab.text()[:40]!r} needs {need}px has {lab.height()}px")
    for le in page.findChildren(QLineEdit):
        ph = le.placeholderText()
        if ph and le.isVisibleTo(page) and QFontMetrics(le.font()).horizontalAdvance(ph) + 24 > le.width():
            problems.append(f"placeholder clipped: {ph!r}")
    return problems


def main() -> None:
    t3.make_media()
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app, "dark")

    t0 = time.perf_counter()
    win = MainWindow(Settings(), HistoryDB(t3.WORK / "p7.db"))
    win.resize(980, 640)          # the minimum supported size
    win.show()
    settle(app, 0.05)
    startup = time.perf_counter() - t0
    assert startup < 3.0, f"window creation too slow: {startup:.2f}s"
    assert "yt_dlp" not in sys.modules, "yt-dlp must stay lazily imported (fast startup)"
    print(f"startup OK ({startup:.2f}s, yt-dlp not loaded until needed)")

    # --- empty-state / placeholder text is fully visible on every page, at minimum size ---------
    info = MediaInfo(url="https://x/y", title="A rather long video title that goes on and on to test wrapping",
                     channel="Chan", duration_seconds=3725, video_heights=[1080, 720], subtitle_langs=["en"])
    for size in ((980, 640), (1200, 780), (1600, 900)):
        win.resize(*size)
        for index in range(6):
            win.show_page(index)
            if index == 0:
                win.home.preview.show_media(info, None)
                win.home.options.set_media(info, None)
                win.home.options.show_queued(1)
            settle(app)
            bad = clipped(win.stack.currentWidget())
            assert not bad, (size, index, bad)
    win.resize(980, 640)
    print("no clipped placeholder / empty-state text on any page (3 window sizes)")

    # --- tall pages scroll ----------------------------------------------------------------------
    win.show_page(0)
    settle(app)
    area = win.home.findChild(QScrollArea)
    bar = area.verticalScrollBar()
    assert bar.maximum() > 0, "Home must be scrollable when options are shown on a small window"
    viewport = area.viewport()
    pos = QPointF(40, 40)
    wheel = QWheelEvent(pos, viewport.mapToGlobal(pos), QPoint(0, 0), QPoint(0, -240), Qt.NoButton,
                        Qt.NoModifier, Qt.NoScrollPhase, False)
    app.sendEvent(viewport, wheel)
    assert bar.value() > 0, "mouse wheel must scroll the page"
    for combo in win.home.findChildren(ScrollSafeComboBox):
        ev = QWheelEvent(QPointF(5, 5), combo.mapToGlobal(QPointF(5, 5)), QPoint(0, 0), QPoint(0, -120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        before = combo.currentIndex()
        app.sendEvent(combo, ev)
        assert combo.currentIndex() == before and not ev.isAccepted(), "unfocused combo must not eat the wheel"
    print("scrolling OK (page scrolls; unfocused dropdowns pass the wheel on)")

    # --- resilience --------------------------------------------------------------------------
    bad_db = t3.WORK / "corrupt.db"
    bad_db.write_bytes(b"this is not a sqlite database" * 50)
    import ui.main_window as mw
    original = mw.HistoryDB
    mw.HistoryDB = lambda path=None: (_ for _ in ()).throw(sqlite3.DatabaseError("file is not a database")) \
        if path is None else original(path)
    db = MainWindow._open_history()
    mw.HistoryDB = original
    db.add(title="t", url="u", kind="video", format_label="", quality_label="", output_dir="", files=[],
           size_bytes=0, notes=[], request={})
    assert db.count() == 1
    print("unusable history database -> app keeps running with a temporary one OK")

    # --- single instance ---------------------------------------------------------------------
    import main as entry
    first = entry.acquire_single_instance()
    assert first is not None
    assert entry.acquire_single_instance() is None, "second instance must be refused"
    first.unlock()
    again = entry.acquire_single_instance()
    assert again is not None
    again.unlock()
    print("single-instance guard OK")

    # --- excepthook shows a friendly dialog, logs, never raises ------------------------------------
    import logging
    import ui.dialogs as dialogs
    shown = []
    dialogs.show_error = lambda parent, title, text: shown.append((title, text))
    previous_hook = sys.excepthook
    entry._install_excepthook(logging.getLogger("quanttum.test"))
    try:
        raise RuntimeError("boom with /secret/path")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    sys.excepthook = previous_hook
    assert shown and "boom" not in shown[0][1] and "log" in shown[0][1].lower(), shown
    print("global exception handler OK (friendly message, no traceback shown)")

    # --- FFmpeg lookup order -------------------------------------------------------------------------
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    folder = t3.fresh("ff_cfg")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / exe).write_text("x")
    assert resolve_ffmpeg(str(folder)) == folder / exe and resolve_ffmpeg(str(folder / exe)) == folder / exe
    assert resolve_ffmpeg(str(t3.WORK / "nowhere")) is None, "a wrong configured path must not silently fall back"
    import app.config as cfg
    bundled = t3.fresh("ff_bundle")
    bundled.mkdir(parents=True, exist_ok=True)
    (bundled / exe).write_text("x")
    saved = cfg._bundled_ffmpeg_dirs
    cfg._bundled_ffmpeg_dirs = lambda: [bundled]
    assert resolve_ffmpeg() == bundled / exe, "bundled copy beats PATH"
    cfg._bundled_ffmpeg_dirs = saved
    print("FFmpeg lookup order OK (configured > bundled > PATH)")

    # --- idle resource budget -------------------------------------------------------------------------
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    assert rss < 400, f"memory use unexpectedly high: {rss:.0f} MB"
    print(f"memory OK (peak {rss:.0f} MB incl. the whole test run)")
    win.close()


if __name__ == "__main__":
    main()
    import shutil
    shutil.rmtree(t3.WORK, ignore_errors=True)
    print("ALL OK")
