"""History page: finished downloads stored in SQLite, with search, sorting and file actions.

"Remove" deletes the history entry only. "Delete file" is a separate, confirmed action
that moves the media file(s) to the Recycle Bin.
"""

from __future__ import annotations

import os
from dataclasses import fields
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from app.config import Settings
from app.downloader import DownloadRequest
from app.history import SORTS, HistoryDB, HistoryEntry, HistoryRecorder
from app.manager import DownloadManager
from app.media_info import human_size, shorten
from app.signals import signals
from app.system import move_to_trash, open_path, reveal_in_folder
from ui.dialogs import confirm, show_error
from ui.widgets import (
    ScrollSafeComboBox,
    BasePage, Card, ElidedLabel, EmptyState, IconLabel, IconPushButton, make_label, repolish,
    secondary_button,
)

PAGE_SIZE = 100


def _icon_button(icon: str, tip: str, danger: bool = False) -> IconPushButton:
    button = IconPushButton("", icon, role="danger" if danger else "text_dim", object_name="IconOnly", icon_size=18)
    button.setToolTip(tip)
    button.setFixedSize(34, 34)
    return button


def request_from_dict(data: dict) -> DownloadRequest | None:
    """Rebuild a DownloadRequest from stored JSON, ignoring unknown/missing fields."""
    allowed = {f.name for f in fields(DownloadRequest)}
    try:
        return DownloadRequest(**{k: v for k, v in data.items() if k in allowed})
    except TypeError:
        return None


class HistoryRow(Card):
    """One history entry."""

    def __init__(self, entry: HistoryEntry, page: HistoryPage) -> None:
        super().__init__()
        self.entry_id = entry.id
        self.page = page
        self.exists = bool(entry.files) and not entry.files_deleted and os.path.exists(entry.files[0])

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 12, 12)
        row.setSpacing(14)
        row.addWidget(IconLabel("video" if entry.kind != "audio" else "history", 26, "accent"))

        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = ElidedLabel(entry.title, "RowTitle")
        when = datetime.fromtimestamp(entry.completed_at).strftime("%d %b %Y, %H:%M")
        site = str(entry.request.get("site") or "")
        self.meta = ElidedLabel(
            " · ".join(p for p in (site, entry.format_label, entry.quality_label,
                                    human_size(entry.size_bytes), when) if p), "Dim")
        if entry.files_deleted:
            status, bad = "File deleted from disk", False
        elif not entry.files or not self.exists:
            status, bad = "File not found — it may have been moved or deleted", True
        else:
            status, bad = shorten(entry.files[0], 80), False
        self.status = ElidedLabel(status, "Dim")
        if bad:
            self.status.setProperty("state", "bad")
            repolish(self.status)
        for w in (self.title, self.meta, self.status):
            col.addWidget(w)
        row.addLayout(col, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(2)
        self.btn_open = _icon_button("open", "Open file")
        self.btn_folder = _icon_button("folder", "Show in folder")
        self.btn_again = _icon_button("retry", "Download again")
        self.btn_delete = _icon_button("trash", "Delete file from disk…", danger=True)
        self.btn_remove = _icon_button("close", "Remove from history (keeps the file)")
        self.btn_open.setVisible(self.exists)
        self.btn_folder.setVisible(self.exists)
        self.btn_delete.setVisible(self.exists)
        self.btn_again.setVisible(bool(entry.request))
        for b in (self.btn_open, self.btn_folder, self.btn_again, self.btn_delete, self.btn_remove):
            buttons.addWidget(b)
        row.addLayout(buttons)

        eid = entry.id
        self.btn_open.clicked.connect(lambda: open_path(entry.files[0]))
        self.btn_folder.clicked.connect(lambda: reveal_in_folder(entry.files[0]))
        self.btn_again.clicked.connect(lambda: page.download_again(eid))
        self.btn_delete.clicked.connect(lambda: page.delete_files(eid))
        self.btn_remove.clicked.connect(lambda: page.remove_entry(eid))


class HistoryPage(BasePage):
    """Searchable, sortable download history."""

    def __init__(self, db: HistoryDB, recorder: HistoryRecorder, manager: DownloadManager) -> None:
        super().__init__("History", "Everything you've downloaded.")
        self.db, self.manager = db, manager
        self._limit = PAGE_SIZE
        self._dirty = True
        self._rows: list[HistoryRow] = []

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title or link…")
        self.search.setClearButtonEnabled(True)
        self.sort = ScrollSafeComboBox()
        self.sort.addItems(list(SORTS))
        self.clear_btn = secondary_button("Clear history", "trash")
        bar.addWidget(self.search, 1)
        bar.addWidget(self.sort)
        bar.addWidget(self.clear_btn)
        self.body.addLayout(bar)

        self.count_label = make_label("", "Dim")
        self.body.addWidget(self.count_label)
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(12)
        self.body.addLayout(self.list_layout)
        self.more_btn = secondary_button("Show more")
        self.body.addWidget(self.more_btn)

        self.empty = Card()
        lay = QVBoxLayout(self.empty)
        self.empty_state = EmptyState("history", "No history yet", "")
        lay.addWidget(self.empty_state)
        self.body.addWidget(self.empty)
        self.body.addStretch(1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self._reset_and_refresh)
        self.search.textChanged.connect(lambda _t: self._debounce.start())
        self.sort.currentTextChanged.connect(lambda _t: self._reset_and_refresh())
        self.clear_btn.clicked.connect(self.clear_history)
        self.more_btn.clicked.connect(self._show_more)
        recorder.changed.connect(self._on_db_changed)
        self.refresh()

    # -- refreshing --------------------------------------------------------
    def _on_db_changed(self) -> None:
        self._dirty = True
        if self.isVisible():
            self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._dirty:
            self.refresh()

    def _reset_and_refresh(self) -> None:
        self._limit = PAGE_SIZE
        self.refresh()

    def _show_more(self) -> None:
        self._limit += PAGE_SIZE
        self.refresh()

    def refresh(self) -> None:
        self._dirty = False
        text, sort = self.search.text().strip(), self.sort.currentText()
        entries = self.db.query(text, sort, self._limit)
        total = self.db.count(text)
        for row in self._rows:
            self.list_layout.removeWidget(row)
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self._rows = [HistoryRow(e, self) for e in entries]
        for row in self._rows:
            self.list_layout.addWidget(row)
        everything = self.db.count()
        self.empty.setVisible(not entries)
        if not entries:
            self.empty_state.set_texts(*(
                ("No matches", f"Nothing in your history matches “{text}”.") if everything else
                ("No history yet", "Completed downloads will be listed here so you can search them "
                                   "and reopen the files.")))
        self.more_btn.setVisible(total > len(entries))
        self.clear_btn.setVisible(everything > 0)
        self.count_label.setText(
            f"Showing {len(entries)} of {total}" + (f" matching “{text}”" if text else "") if entries else "")

    # -- actions -----------------------------------------------------------
    def remove_entry(self, entry_id: int) -> None:
        self.db.delete(entry_id)          # the media files are left alone
        self.refresh()

    def delete_files(self, entry_id: int) -> None:
        entry = self.db.get(entry_id)
        if not entry or not entry.files:
            return
        what = f"{len(entry.files)} downloaded files" if len(entry.files) > 1 else f"“{entry.title}”"
        if not confirm(
            self, "Delete from disk",
            f"Delete {what} from your computer?\n\n"
            "It will be moved to the Recycle Bin when possible. The history entry stays."):
            return
        failed = sum(1 for f in entry.files if os.path.exists(f) and not move_to_trash(f))
        if failed:
            show_error(self, "Couldn't delete everything",
                       f"{failed} file{'s' if failed != 1 else ''} couldn't be deleted. "
                       "They may be open in another program.")
        else:
            self.db.set_files_deleted(entry_id)
        self.refresh()

    def download_again(self, entry_id: int) -> None:
        entry = self.db.get(entry_id)
        request = request_from_dict(entry.request) if entry else None
        if not request:
            show_error(self, "Can't download again", "The saved details for this download are incomplete.")
            return
        request.cookies_browser, request.cookies_file = Settings().cookie_source   # current sign-in choice
        self.manager.add(request, start_now=True)
        signals.navigate.emit(1)

    def clear_history(self) -> None:
        if confirm(self, "Clear history",
                   "Remove every entry from the history?\n\nYour downloaded files are not touched."):
            self.db.clear()
            self.refresh()
