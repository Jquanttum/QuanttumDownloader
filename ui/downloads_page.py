"""Download rows shared by the Downloads and Queue pages, plus the Downloads page itself."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QVBoxLayout

from app.manager import DownloadJob, DownloadManager, JobState
from app.media_info import format_duration, human_size, shorten
from app.system import open_path, reveal_in_folder
from ui.dialogs import confirm, show_error
from ui.widgets import (
    BasePage, Card, ElidedLabel, EmptyState, IconPushButton, ThumbnailLabel, make_label,
    repolish, secondary_button,
)

_BAR_STATE = {
    JobState.QUEUED: "idle", JobState.ACTIVE: "", JobState.PAUSED: "idle",
    JobState.COMPLETED: "ok", JobState.FAILED: "bad", JobState.CANCELLED: "idle",
}


def _icon_button(icon: str, tip: str, danger: bool = False) -> IconPushButton:
    button = IconPushButton("", icon, role="danger" if danger else "text_dim", object_name="IconOnly", icon_size=18)
    button.setToolTip(tip)
    button.setFixedSize(34, 34)
    return button


class DownloadRow(Card):
    """One download: thumbnail, title, progress bar, status line and action buttons."""

    def __init__(self, job: DownloadJob, manager: DownloadManager, queue_mode: bool = False) -> None:
        super().__init__()
        self.job_id = job.id
        self.manager = manager
        self.queue_mode = queue_mode
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 12, 12)
        row.setSpacing(14)

        self.thumb = ThumbnailLabel(128, 72)
        self.thumb.set_pixmap(job.thumbnail)
        row.addWidget(self.thumb)

        col = QVBoxLayout()
        col.setSpacing(5)
        self.title = ElidedLabel(job.title, "RowTitle")
        req = job.request
        where = shorten(req.output_dir, 48)
        self.meta = ElidedLabel(f"{req.format_label} · {req.quality_label} · {where}", "Dim")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.status = ElidedLabel("", "Dim")
        for widget in (self.title, self.meta, self.bar, self.status):
            col.addWidget(widget)
        row.addLayout(col, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(2)
        self.btn_up = _icon_button("up", "Move up in queue")
        self.btn_down = _icon_button("down", "Move down in queue")
        self.btn_pause = _icon_button("pause", "Pause")
        self.btn_resume = _icon_button("play", "Resume")
        self.btn_retry = _icon_button("retry", "Retry")
        self.btn_open = _icon_button("open", "Open file")
        self.btn_folder = _icon_button("folder", "Show in folder")
        self.btn_cancel = _icon_button("close", "Cancel download", danger=True)
        self.btn_delete = _icon_button("trash", "Delete file from disk…", danger=True)
        self.btn_remove = _icon_button("close", "Remove from list (keeps the file)")
        for b in (self.btn_up, self.btn_down, self.btn_pause, self.btn_resume, self.btn_retry,
                  self.btn_open, self.btn_folder, self.btn_cancel, self.btn_delete, self.btn_remove):
            buttons.addWidget(b)
        row.addLayout(buttons)

        jid = job.id
        self.btn_up.clicked.connect(lambda: manager.move(jid, -1))
        self.btn_down.clicked.connect(lambda: manager.move(jid, +1))
        self.btn_pause.clicked.connect(lambda: manager.pause(jid))
        self.btn_resume.clicked.connect(lambda: manager.resume(jid))
        self.btn_retry.clicked.connect(lambda: manager.retry(jid))
        self.btn_cancel.clicked.connect(lambda: manager.cancel(jid))
        self.btn_remove.clicked.connect(lambda: manager.remove(jid))
        self.btn_open.clicked.connect(self._open_file)
        self.btn_folder.clicked.connect(self._reveal)
        self.btn_delete.clicked.connect(self._delete_files)
        self.update_from(job)

    # -- actions ---------------------------------------------------------
    def _first_file(self) -> str | None:
        job = self.manager.job(self.job_id)
        return job.files[0] if job and job.files else None

    def _open_file(self) -> None:
        path = self._first_file()
        if path:
            open_path(path)

    def _reveal(self) -> None:
        job = self.manager.job(self.job_id)
        if job:
            reveal_in_folder(job.files[0] if job.files else job.request.output_dir)

    def _delete_files(self) -> None:
        job = self.manager.job(self.job_id)
        if not job or not job.files:
            return
        many = len(job.files) > 1
        what = f"{len(job.files)} downloaded files" if many else f"“{job.title}”"
        if not confirm(
            self, "Delete from disk",
            f"Delete {what} from your computer?\n\n"
            "It will be moved to the Recycle Bin when possible. This can't be undone from here.",
        ):
            return
        _deleted, failed = self.manager.delete_files(self.job_id)
        if failed:
            show_error(self, "Couldn't delete everything",
                       f"{failed} file{'s' if failed != 1 else ''} couldn't be deleted. "
                       "They may be open in another program.")

    # -- rendering -------------------------------------------------------
    def _status_text(self, job: DownloadJob) -> str:
        state = job.state
        if state is JobState.QUEUED:
            if not self.manager.queue_running and not job.manual:
                return "Queued — the queue is stopped"
            return "Waiting for a free download slot…"
        if state is JobState.PAUSED:
            return f"Paused at {job.percent:.0f}% — press Resume to continue"
        if state is JobState.CANCELLED:
            return "Cancelled"
        if state is JobState.FAILED:
            return job.error or "Download failed"
        if state is JobState.COMPLETED:
            if job.files_deleted:
                return f"File deleted from disk · was {human_size(job.size_bytes)}"
            head = f"Completed · {human_size(job.size_bytes)}"
            if len(job.files) > 1:
                head = f"Completed · {len(job.files)} files · {human_size(job.size_bytes)}"
            return " · ".join([head, *job.notes])
        parts = [job.phase or "Downloading"]
        if job.items > 1:
            parts[0] += f" ({job.item}/{job.items})"
        if job.phase.startswith("Download"):
            parts.append(f"{job.percent:.0f}%")
            if job.speed:
                parts.append(f"{human_size(job.speed)}/s")
            if job.eta is not None:
                parts.append(f"ETA {format_duration(job.eta)}")
            if job.downloaded is not None:
                parts.append(human_size(job.downloaded) + (f" of {human_size(job.total)}" if job.total else ""))
        return " · ".join(parts)

    def update_from(self, job: DownloadJob) -> None:
        state = job.state
        self.bar.setValue(int(job.percent * 10))
        bar_state = _BAR_STATE[state]
        if self.bar.property("state") != bar_state:
            self.bar.setProperty("state", bar_state)
            repolish(self.bar)
        self.status.setText(self._status_text(job))
        bad = "bad" if state is JobState.FAILED else ""
        if (self.status.property("state") or "") != bad:
            self.status.setProperty("state", bad)
            repolish(self.status)

        stopping = bool(job.stop_reason)
        has_files = state is JobState.COMPLETED and not job.files_deleted
        self.btn_up.setVisible(self.queue_mode and state in (JobState.QUEUED, JobState.PAUSED))
        self.btn_down.setVisible(self.queue_mode and state in (JobState.QUEUED, JobState.PAUSED))
        self.btn_pause.setVisible(state in (JobState.ACTIVE, JobState.QUEUED))
        self.btn_pause.setEnabled(not stopping)
        self.btn_resume.setVisible(state is JobState.PAUSED)
        self.btn_retry.setVisible(state in (JobState.FAILED, JobState.CANCELLED))
        self.btn_cancel.setVisible(state in (JobState.ACTIVE, JobState.QUEUED, JobState.PAUSED))
        self.btn_cancel.setEnabled(job.stop_reason != "cancelled")
        self.btn_open.setVisible(has_files)
        self.btn_folder.setVisible(has_files)
        self.btn_delete.setVisible(has_files)
        self.btn_remove.setVisible(job.is_finished)


class DownloadsPage(BasePage):
    """Shows every download and keeps its rows in sync with the manager."""

    def __init__(self, manager: DownloadManager) -> None:
        super().__init__("Downloads", "Downloads in progress and recently finished.")
        self.manager = manager
        self._rows: dict[int, DownloadRow] = {}

        bar = QHBoxLayout()
        self.count_label = make_label("", "Dim")
        bar.addWidget(self.count_label, 1)
        self.clear_btn = secondary_button("Clear completed", "check")
        self.clear_btn.clicked.connect(manager.clear_completed)
        bar.addWidget(self.clear_btn)
        self.body.addLayout(bar)

        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(12)
        self.body.addLayout(self.list_layout)

        self.empty = Card()
        el = QVBoxLayout(self.empty)
        el.addWidget(EmptyState(
            "download", "No downloads yet",
            "Analyse a link on Home and press Download. Progress, speed and time remaining will show here."))
        self.body.addWidget(self.empty)
        self.body.addStretch(1)

        manager.job_added.connect(self._add_row)
        manager.job_updated.connect(self._update_row)
        manager.job_removed.connect(self._remove_row)
        for job in manager.jobs():
            self._add_row(job)
        self._refresh_summary()

    def _add_row(self, job: DownloadJob) -> None:
        row = DownloadRow(job, self.manager)
        self._rows[job.id] = row
        self.list_layout.insertWidget(0, row)  # newest first
        self._refresh_summary()

    def _update_row(self, job: DownloadJob) -> None:
        row = self._rows.get(job.id)
        if row:
            row.update_from(job)
            if job.state is not JobState.ACTIVE:
                self._refresh_summary()

    def _remove_row(self, job_id: int) -> None:
        row = self._rows.pop(job_id, None)
        if row:
            self.list_layout.removeWidget(row)
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        jobs = self.manager.jobs()
        active = sum(1 for j in jobs if j.state is JobState.ACTIVE)
        done = sum(1 for j in jobs if j.state is JobState.COMPLETED)
        self.empty.setVisible(not jobs)
        self.clear_btn.setVisible(bool(done))
        self.count_label.setText(
            f"{active} active · {done} completed · {len(jobs)} total" if jobs else "")
