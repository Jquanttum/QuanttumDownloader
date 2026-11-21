"""Phase 4 checks: queue ordering, stop/start, add-to-queue, delete-from-disk, Queue page.

    python tests/test_phase4.py        (reuses the local test server from test_phase3.py)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_phase3 as t3  # noqa: E402  (sets up env vars, sys.path and helpers)

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import Settings  # noqa: E402
from app.downloader import DownloadRequest  # noqa: E402
from app.manager import JobState  # noqa: E402
from app.media_info import MediaInfo  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.styles import apply_theme  # noqa: E402

ROOT = t3.ROOT


def pump(app: QApplication, cond, timeout: float = 40.0) -> None:
    t3.pump(app, cond, timeout)


def slow(base: str, n: int, out: Path, title: str | None = None) -> DownloadRequest:
    return DownloadRequest(f"{base}/slow{n}.mp4", title or f"Slow video {n}", output_dir=str(out),
                           ffmpeg_path=str(t3.FFMPEG), embed_metadata=False)


def main() -> None:
    t3.make_media()
    base = t3.start_server()
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app, "dark")
    settings = Settings()
    settings.set("max_concurrent", 1)
    win = MainWindow(settings)
    win.resize(1200, 780)
    win.show()
    mgr = win.manager
    queue_page = win.stack.widget(2)
    downloads_page = win.stack.widget(1)
    shots = ROOT / "tests" / "shots"
    shots.mkdir(exist_ok=True)
    out = t3.fresh("p4_out")

    # --- regression: switching pages after a fade has finished must not crash ----------------
    for index in (1, 2, 0, 4, 0):
        win.show_page(index)
        pump(app, lambda: win._anim is None, timeout=5)   # wait for the fade to finish and clean up
    print("page switching after fades OK")

    # --- stopped queue: nothing auto-starts; "download now" does ---------------------------
    mgr.stop_queue()
    a = mgr.add(slow(base, 1, out), start_now=False)
    b = mgr.add(slow(base, 2, out), start_now=False)
    c = mgr.add(slow(base, 3, out), start_now=False)
    app.processEvents()
    assert [j.state for j in (a, b, c)] == [JobState.QUEUED] * 3, "stopped queue must not start jobs"
    assert "stopped" in queue_page.state_label.text()
    assert queue_page.start_btn.isVisibleTo(queue_page) and not queue_page.stop_btn.isVisibleTo(queue_page)
    print("stopped queue holds jobs OK")

    # --- reordering ----------------------------------------------------------------------
    mgr.move(c.id, -1)
    mgr.move(c.id, -1)
    mgr.move(c.id, -1)   # already first: no-op
    mgr.move(b.id, +1)
    order = [j.id for j in mgr.queue_jobs()]
    assert order == [c.id, a.id, b.id], order
    ids_in_layout = [queue_page.list_layout.itemAt(i).widget().job_id for i in range(queue_page.list_layout.count())]
    assert ids_in_layout == order, "Queue page widgets must follow the manager's order"
    print("reorder OK (manager and Queue page agree):", [mgr.job(i).title for i in order])

    # --- start queue: first job in order runs, the rest wait (limit = 1) ------------------
    mgr.start_queue()
    app.processEvents()
    assert c.state is JobState.ACTIVE and a.state is JobState.QUEUED and b.state is JobState.QUEUED
    pump(app, lambda: c.percent > 8)
    app.processEvents()
    win.show_page(2)
    pump(app, lambda: win._anim is None, timeout=5)
    win.grab().save(str(shots / "queue_running.png"))
    print("start queue OK (starts in the chosen order, honours limit of 1)")

    # --- "download now" jumps ahead of waiting jobs ---------------------------------------
    d = mgr.add(slow(base, 4 if False else 1, out, "Duplicate of A"), start_now=False)
    assert d is a, "identical queued request must reuse the existing job"
    mgr.stop_queue()
    mgr.cancel(c.id)
    pump(app, lambda: c.state is JobState.CANCELLED)
    app.processEvents()
    assert a.state is JobState.QUEUED and b.state is JobState.QUEUED, "stopped queue must not start the next job"
    mgr.add(slow(base, 1, out), start_now=True)   # same as A: promotes it to manual
    pump(app, lambda: a.state is JobState.ACTIVE)
    assert b.state is JobState.QUEUED
    print("manual start bypasses stopped queue OK")

    # --- clear queue cancels waiting jobs only ---------------------------------------------
    mgr.clear_queue()
    app.processEvents()
    assert b.state is JobState.CANCELLED and a.state is JobState.ACTIVE
    mgr.cancel(a.id)
    pump(app, lambda: a.state is JobState.CANCELLED)
    assert not [p for p in out.iterdir()], f"cancelled jobs must leave no files: {list(out.iterdir())}"
    print("clear queue OK (waiting cancelled, running untouched, no leftovers)")

    # --- delete from disk ------------------------------------------------------------------
    mgr.start_queue()
    mgr.add(DownloadRequest(f"{base}/clip.mp4", "Clip", output_dir=str(out), ffmpeg_path=str(t3.FFMPEG),
                            embed_metadata=False), start_now=True)
    clip = [j for j in mgr.jobs() if j.title == "Clip"][0]
    pump(app, lambda: clip.state is JobState.COMPLETED)
    path = Path(clip.files[0])
    assert path.exists()
    row = downloads_page._rows[clip.id]
    assert row.btn_delete.isVisibleTo(row) and row.btn_open.isVisibleTo(row)

    # cancelling the confirmation keeps the file
    import ui.downloads_page as dp
    original = dp.confirm
    dp.confirm = lambda *a, **k: False
    row.btn_delete.click()
    assert path.exists() and not clip.files_deleted
    # confirming removes it
    dp.confirm = lambda *a, **k: True
    row.btn_delete.click()
    dp.confirm = original
    assert not path.exists() and clip.files_deleted, "file must be gone after confirmed delete"
    assert not row.btn_open.isVisibleTo(row) and not row.btn_delete.isVisibleTo(row)
    assert "deleted" in row.status._full.lower() and clip.state is JobState.COMPLETED
    assert mgr.delete_files(clip.id) == (0, 0), "second delete is a harmless no-op"
    print("delete from disk OK (confirm required, file removed, row updated)")

    # remove-from-list never touches files
    keep = mgr.add(DownloadRequest(f"{base}/clip.mp4", "Keep me", output_dir=str(t3.fresh("p4_keep")),
                                   ffmpeg_path=str(t3.FFMPEG), embed_metadata=False), start_now=True)
    pump(app, lambda: keep.state is JobState.COMPLETED)
    kept_path = Path(keep.files[0])
    mgr.remove(keep.id)
    assert kept_path.exists() and mgr.job(keep.id) is None
    print("remove from list keeps the file OK")

    # --- options panel: both buttons -------------------------------------------------------
    info = MediaInfo(url=f"{base}/clip.mp4", title="Panel test", video_heights=[720, 360])
    panel = win.home.options
    panel.set_media(info, None)
    panel.folder.setText(str(t3.fresh("p4_panel")))
    seen: list[bool] = []
    panel.download_requested.connect(lambda r, th, start: seen.append(start))
    win.manager.stop_queue()
    panel.queue_btn.click()
    panel.download_btn.click()
    assert seen == [False, True], seen
    queued = [j for j in mgr.jobs() if j.title == "Panel test"]
    assert len(queued) == 1, "same request twice is one job"
    assert panel.feedback.isVisibleTo(panel) and "position" in panel.feedback.text()
    win.show_page(0)
    pump(app, lambda: win._anim is None, timeout=5)
    win.grab().save(str(shots / "home_queue_buttons.png"))
    pump(app, lambda: queued[0].state is JobState.COMPLETED)
    print("options panel OK (Add to queue vs Download now, de-duplicated)")

    # --- screenshots of a mixed queue ------------------------------------------------------
    mgr.stop_queue()
    shot_dir = t3.fresh("p4_shot")
    for n in (1, 2, 3):
        mgr.add(slow(base, n, shot_dir), start_now=(n == 1))
    pump(app, lambda: mgr.queue_jobs()[0].percent > 10)
    win.show_page(2)
    pump(app, lambda: win._anim is None, timeout=5)
    win.grab().save(str(shots / "queue_mixed.png"))
    print("queue page rendering OK")

    # --- closing with active downloads asks first; declining keeps the window open ---------
    import ui.main_window as mw
    asked: list[str] = []
    mw.confirm = lambda parent, title, text: (asked.append(text), False)[1]
    win.close()
    assert asked and "still running" in asked[0] and win.isVisible(), "quit must be confirmed first"
    mw.confirm = lambda *a, **k: True
    win.close()
    assert not win.isVisible()
    print("quit confirmation OK (decline keeps running, accept pauses and closes)")


if __name__ == "__main__":
    main()
    import shutil
    shutil.rmtree(t3.WORK, ignore_errors=True)
    print("ALL OK")
