"""Phase 6 checks: SQLite history, History page, settings, yt-dlp update flow, notifications.

    python tests/test_phase6.py        (reuses the local test server from test_phase3.py)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_phase3 as t3  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import Settings  # noqa: E402
from app.downloader import DownloadRequest  # noqa: E402
from app.history import HistoryDB  # noqa: E402
from app.manager import JobState  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.styles import apply_theme  # noqa: E402

ROOT = t3.ROOT


def pump(app, cond, timeout=40.0):
    t3.pump(app, cond, timeout)


def test_db() -> None:
    path = t3.WORK / "h.db"
    db = HistoryDB(path)
    ids = [db.add(title=t, url=u, kind="video", format_label="MP4", quality_label="Best", output_dir="/x",
                  files=[f"/x/{t}.mp4"], size_bytes=s, notes=[], request={}, completed_at=100 + i)
           for i, (t, u, s) in enumerate([("Alpha 100%", "http://a/1", 5), ("beta_tune", "http://b/2", 50),
                                          ("Gamma", "http://c/3", 20)])]
    assert [e.title for e in db.query()] == ["Gamma", "beta_tune", "Alpha 100%"]
    assert [e.title for e in db.query(sort="Oldest first")][0] == "Alpha 100%"
    assert [e.title for e in db.query(sort="Title A–Z")] == ["Alpha 100%", "beta_tune", "Gamma"]
    assert [e.title for e in db.query(sort="Largest first")][0] == "beta_tune"
    assert [e.title for e in db.query("beta")] == ["beta_tune"]
    assert [e.title for e in db.query("http://c")] == ["Gamma"], "search covers the link"
    assert [e.title for e in db.query("100%")] == ["Alpha 100%"], "% is literal"
    assert db.query("_") == [db.get(ids[1])], "_ is literal, not a wildcard"
    assert db.query("a'; DROP TABLE history;--") == [] and db.count() == 3, "SQL injection safe"
    assert len(db.query(limit=2)) == 2 and db.count("a") == 3
    db.set_files_deleted(ids[0])
    assert db.get(ids[0]).files_deleted
    db.delete(ids[2])
    assert db.count() == 2 and db.get(ids[2]) is None
    db.close()
    db = HistoryDB(path)   # persists across reopen
    assert db.count() == 2
    db.clear()
    assert db.count() == 0
    db.close()
    print("history database OK (sort, search, escaping, persistence)")


def main() -> None:
    t3.make_media()
    base = t3.start_server()
    test_db()

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app, "dark")
    settings = Settings()
    settings.set("max_concurrent", 2)
    settings.set("keep_history", True)
    db = HistoryDB(t3.WORK / "ui.db")
    win = MainWindow(settings, db)
    win.resize(1200, 780)
    win.show()
    mgr = win.manager
    page = win.stack.widget(3)
    out = t3.fresh("p6_out")
    shots = ROOT / "tests" / "shots"
    shots.mkdir(exist_ok=True)

    # empty state
    win.show_page(3)
    app.processEvents()
    assert page.empty.isVisibleTo(page) and not page._rows
    print("empty history OK")

    # completed downloads are recorded automatically
    def clip(title: str, folder: Path) -> DownloadRequest:
        return DownloadRequest(f"{base}/clip.mp4", title, output_dir=str(folder),
                               ffmpeg_path=str(t3.FFMPEG), embed_metadata=False)

    jobs = []
    for i, title in enumerate(("Forensic lecture", "Bioscience demo", "Cats compilation")):
        jobs.append(mgr.add(clip(title, t3.fresh(f"p6_{i}")), start_now=True))
        pump(app, lambda: jobs[-1].state is JobState.COMPLETED)
        time.sleep(0.01)
    assert db.count() == 3
    assert len(page._rows) == 3, "page refreshes live when visible"
    assert [r.title._full for r in page._rows] == ["Cats compilation", "Bioscience demo", "Forensic lecture"]
    print("downloads recorded and shown OK")

    # failed downloads are not recorded
    bad = mgr.add(DownloadRequest(f"{base}/nope.mp4", "Broken", output_dir=str(out)), start_now=True)
    pump(app, lambda: bad.state is JobState.FAILED)
    assert db.count() == 3
    print("failed downloads not recorded OK")

    # search + sort through the UI
    page.search.setText("bio")
    pump(app, lambda: len(page._rows) == 1, 5)
    assert page._rows[0].title._full == "Bioscience demo" and "1 of 1" in page.count_label.text()
    page.search.setText("zzzz")
    pump(app, lambda: not page._rows, 5)
    assert page.empty.isVisibleTo(page) and "No matches" in page.empty_state._heading.text()
    page.search.setText("")
    pump(app, lambda: len(page._rows) == 3, 5)
    page.sort.setCurrentText("Title A–Z")
    assert [r.title._full for r in page._rows] == ["Bioscience demo", "Cats compilation", "Forensic lecture"]
    page.sort.setCurrentText("Newest first")
    print("search and sort in the UI OK")

    # remove entry keeps the file
    victim = jobs[0]
    path = Path(victim.files[0])
    row = [r for r in page._rows if r.title._full == victim.title][0]
    assert row.exists and row.btn_open.isVisibleTo(row) and row.btn_delete.isVisibleTo(row)
    row.btn_remove.click()
    assert db.count() == 2 and path.exists(), "removing an entry must never delete the media file"
    print("remove entry keeps the file OK")

    # delete file from history (confirm required)
    import ui.history_page as hp
    original = hp.confirm
    target = jobs[1]
    tpath = Path(target.files[0])
    row = [r for r in page._rows if r.title._full == target.title][0]
    hp.confirm = lambda *a, **k: False
    row.btn_delete.click()
    assert tpath.exists()
    hp.confirm = lambda *a, **k: True
    row.btn_delete.click()
    hp.confirm = original
    assert not tpath.exists()
    row = [r for r in page._rows if r.title._full == target.title][0]
    assert "deleted from disk" in row.status._full and not row.btn_open.isVisibleTo(row)
    assert db.count() == 2, "entry stays after deleting the file"
    print("delete file from history OK")

    # deleting from the Downloads page updates history too
    other = jobs[2]
    opath = Path(other.files[0])
    import ui.downloads_page as dp
    dp_orig = dp.confirm
    dp.confirm = lambda *a, **k: True
    win.stack.widget(1)._rows[other.id].btn_delete.click()
    dp.confirm = dp_orig
    assert not opath.exists()
    entry = [e for e in db.query() if e.title == other.title][0]
    assert entry.files_deleted
    print("Downloads-page delete synced to history OK")

    # externally missing file is flagged
    ext = mgr.add(clip("External", t3.fresh("p6_ext")), start_now=True)
    pump(app, lambda: ext.state is JobState.COMPLETED)
    Path(ext.files[0]).unlink()
    page.refresh()
    row = [r for r in page._rows if r.title._full == "External"][0]
    assert "not found" in row.status._full and not row.btn_open.isVisibleTo(row)
    print("missing file flagged OK")

    # download again
    n_before = len(mgr.jobs())
    ext_entry = [e for e in db.query() if e.title == "External"][0]
    page.download_again(ext_entry.id)
    again = mgr.jobs()[-1]
    assert len(mgr.jobs()) == n_before + 1 and again.request.url == f"{base}/clip.mp4"
    assert win.stack.currentIndex() == 1
    pump(app, lambda: again.state is JobState.COMPLETED)
    assert Path(again.files[0]).exists()
    print("download again OK")

    # screenshot
    win.show_page(3)
    pump(app, lambda: win._anim is None, 5)
    win.grab().save(str(shots / "history.png"))

    # clear history never touches files
    keep = Path(again.files[0])
    hp.confirm = lambda *a, **k: True
    page.clear_history()
    hp.confirm = original
    assert db.count() == 0 and keep.exists() and page.empty.isVisibleTo(page)
    print("clear history keeps files OK")

    # keep_history off
    settings.set("keep_history", False)
    k = mgr.add(clip("Not recorded", t3.fresh("p6_off")), start_now=True)
    pump(app, lambda: k.state is JobState.COMPLETED)
    assert db.count() == 0
    settings.set("keep_history", True)
    print("keep_history setting OK")

    # --- notifications ------------------------------------------------------------------
    shown: list[tuple[str, str]] = []
    win.notifier._emit = lambda title, text: shown.append((title, text))
    win.notifier.should_notify = lambda: settings.notifications   # offscreen app is never "active"
    settings.set("notifications", True)
    n = mgr.add(clip("Notify me", t3.fresh("p6_n1")), start_now=True)
    pump(app, lambda: n.state is JobState.COMPLETED)
    assert shown and shown[-1][0] == "Download finished" and "Notify me" in shown[-1][1], shown
    f = mgr.add(DownloadRequest(f"{base}/nope2.mp4", "Will fail", output_dir=str(out)), start_now=True)
    pump(app, lambda: f.state is JobState.FAILED)
    assert shown[-1][0] == "Download failed" and "Will fail" in shown[-1][1]
    count = len(shown)
    settings.set("notifications", False)
    n2 = mgr.add(clip("Silent", t3.fresh("p6_n2")), start_now=True)
    pump(app, lambda: n2.state is JobState.COMPLETED)
    assert len(shown) == count, "notifications off must be silent"
    settings.set("notifications", True)
    del win.notifier.should_notify   # real rule: an active window suppresses notifications
    assert win.notifier.notify("x", "y") in (True, False)
    print("notifications OK (finished, failed, setting respected)")

    # --- settings: yt-dlp update flow (network and pip mocked) ---------------------------
    import app.updater as up
    sp = win.stack.widget(4)
    assert up.is_newer("2026.11.01", "2026.10.26") and not up.is_newer("2026.10.26", "2026.10.26")
    assert not up.is_newer("2025.1.1", "2026.10.26") and up.is_newer("2026.10.26", None)
    up.latest_ytdlp_version = lambda timeout=10.0: "2099.01.01"
    sp.check_ytdlp_updates()
    pump(app, lambda: sp.ytdlp_update.isVisibleTo(sp), 5)
    assert "2099.01.01" in sp.ytdlp_update.text() and sp.ytdlp_check.isEnabled()
    up.update_ytdlp = lambda: (True, "yt-dlp was updated. Restart Quanttum Downloader to use the new version.")
    sp.run_ytdlp_update()
    pump(app, lambda: "updated" in sp.ytdlp_note.text(), 5)
    assert not sp.ytdlp_update.isVisibleTo(sp)

    def offline(timeout=10.0):
        raise OSError("offline")
    up.latest_ytdlp_version = offline
    sp.check_ytdlp_updates()
    pump(app, lambda: "online" in sp.ytdlp_note.text(), 5)
    assert sp.ytdlp_check.isEnabled()
    up.latest_ytdlp_version = lambda timeout=10.0: __import__("app.config", fromlist=["x"]).get_ytdlp_version()
    sp.check_ytdlp_updates()
    pump(app, lambda: "up to date" in sp.ytdlp_note.text(), 5)
    print("yt-dlp update flow OK (newer, updated, offline, up to date)")

    # --- quit with everything idle closes cleanly ---------------------------------------
    win.close()
    assert not win.isVisible()
    print("close OK")


if __name__ == "__main__":
    main()
    import shutil
    shutil.rmtree(t3.WORK, ignore_errors=True)
    print("ALL OK")
