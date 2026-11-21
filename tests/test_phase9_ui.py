"""Phase 9 UI checks: playlist spec, trim validation, drag-and-drop reorder, tray, shortcuts, persistence, system theme."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_phase3 as t3  # noqa: E402

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QGuiApplication, QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import QUEUE_FILE, Settings  # noqa: E402
from app.history import HistoryDB  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.playlist_dialog import items_spec  # noqa: E402
from ui.styles import resolve_theme  # noqa: E402
from ui.widgets import QUEUE_MIME  # noqa: E402


def main() -> None:
    app = QApplication.instance() or QApplication([])
    assert items_spec([1, 2, 3], 3) == "" and items_spec([1, 2, 3, 5, 7, 8], 9) == "1-3,5,7-8"
    assert items_spec([2], 5) == "2" and items_spec([], 5) == ""
    print("playlist items spec OK")

    assert resolve_theme("system") in ("dark", "light") and resolve_theme("dark") == "dark"
    work = t3.WORK / "ui9"
    work.mkdir(exist_ok=True)

    s = Settings()
    s.set("close_to_tray", False)
    win = MainWindow(s, HistoryDB(work / "h.db"), persist_queue=True)
    win.resize(980, 640)
    win.show()
    app.processEvents()

    # shortcuts exist and switch pages
    assert len(win._shortcuts) == 8
    win.show_page(0)
    win._shortcuts[2].activated.emit()
    app.processEvents()
    assert win.stack.currentIndex() == 2, win.stack.currentIndex()
    win._shortcuts[0].activated.emit()
    assert win.stack.currentIndex() == 0
    print("shortcuts OK")

    # queue + drag/drop reorder
    from app.downloader import DownloadRequest
    ids = []
    for i in range(3):
        r = DownloadRequest(url=f"http://127.0.0.1:1/{i}", title=f"v{i}", output_dir=str(work), ffmpeg_path="")
        ids.append(win.manager.add(r, start_now=False).id)
    qp = win.stack.widget(2)
    win.show_page(2)
    app.processEvents()
    assert [j.id for j in win.manager.queue_jobs()] == ids
    mime = QMimeData()
    mime.setData(QUEUE_MIME, str(ids[0]).encode())
    last = qp._rows[ids[2]]
    y = last.mapTo(qp, last.rect().bottomLeft()).y() + 5
    pos = QPointF(20, y)
    qp.dragEnterEvent(QDragEnterEvent(pos.toPoint(), Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    qp.dropEvent(QDropEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert [j.id for j in win.manager.queue_jobs()] == [ids[1], ids[2], ids[0]], [j.id for j in win.manager.queue_jobs()]
    print("drag-and-drop reorder OK")

    # persistence written
    win.manager.save_now()
    data = json.loads(Path(QUEUE_FILE).read_text(encoding="utf-8"))
    assert data, "queue file empty"
    print("queue persisted OK")

    # trim validation
    op = win.home.options
    assert op._trim_problem() == ""  # no info yet
    # close to tray: close hides instead of quitting
    s.set("close_to_tray", True)
    win.tray.sync()
    if win.tray.available():
        win.close()
        assert not win.isVisible()
        win.show()
    else:
        assert not win.tray.should_hide_on_close()
    s.set("close_to_tray", False)

    # system theme switching
    s.set("theme", "system")
    win._on_system_scheme()
    print("tray / system theme OK")
    import ui.main_window as mw
    mw.confirm = lambda *a, **k: True
    win._quitting = True
    win.close()
    print("ALL OK")


if __name__ == "__main__":
    main()
