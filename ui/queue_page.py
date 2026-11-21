"""Queue page: running and waiting downloads in start order, with reorder and queue controls."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from app.manager import QUEUE_STATES, DownloadJob, DownloadManager, JobState
from ui.dialogs import confirm
from ui.downloads_page import DownloadRow
from ui.widgets import BasePage, Card, EmptyState, ghost_button, make_label, primary_button, secondary_button


class QueuePage(BasePage):
    """Downloads that are running or waiting, in the order they will start."""

    def __init__(self, manager: DownloadManager) -> None:
        super().__init__("Queue", "Downloads run in this order, up to your simultaneous-download limit.")
        self.manager = manager
        self._rows: dict[int, DownloadRow] = {}

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.state_label = make_label("", "Dim", wrap=True)
        bar.addWidget(self.state_label, 1)
        self.start_btn = primary_button("Start queue", "play")
        self.stop_btn = secondary_button("Stop queue", "pause")
        self.clear_btn = ghost_button("Clear queue", "close")
        self.clear_btn.setObjectName("DangerGhost")
        self.start_btn.clicked.connect(manager.start_queue)
        self.stop_btn.clicked.connect(manager.stop_queue)
        self.clear_btn.clicked.connect(self._clear)
        for b in (self.start_btn, self.stop_btn, self.clear_btn):
            bar.addWidget(b)
        self.body.addLayout(bar)

        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(12)
        self.body.addLayout(self.list_layout)

        self.empty = Card()
        el = QVBoxLayout(self.empty)
        el.addWidget(EmptyState(
            "queue", "The queue is empty",
            "Use “Add to queue” on Home to line up downloads. They start in order as slots free up."))
        self.body.addWidget(self.empty)
        self.body.addStretch(1)

        manager.job_added.connect(self._sync)
        manager.job_updated.connect(self._sync)
        manager.job_removed.connect(self._drop)
        manager.queue_changed.connect(self._reorder)
        for job in manager.queue_jobs():
            self._sync(job)
        self._reorder()

    def _clear(self) -> None:
        waiting = sum(1 for j in self.manager.jobs() if j.state in (JobState.QUEUED, JobState.PAUSED))
        if waiting and confirm(
            self, "Clear queue",
            f"Cancel {waiting} waiting download{'s' if waiting != 1 else ''}? "
            "Downloads already running are not affected.",
        ):
            self.manager.clear_queue()

    def _sync(self, job: DownloadJob) -> None:
        in_queue = job.state in QUEUE_STATES
        row = self._rows.get(job.id)
        if in_queue and row is None:
            row = DownloadRow(job, self.manager, queue_mode=True)
            self._rows[job.id] = row
            self.list_layout.addWidget(row)
            self._reorder()
        elif in_queue and row is not None:
            row.update_from(job)
        elif not in_queue and row is not None:
            self._drop(job.id)

    def _drop(self, job_id: int) -> None:
        row = self._rows.pop(job_id, None)
        if row:
            self.list_layout.removeWidget(row)
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self._reorder()

    def _reorder(self) -> None:
        """Match the widget order and header to the manager's queue."""
        jobs = self.manager.queue_jobs()
        for index, job in enumerate(jobs):
            row = self._rows.get(job.id)
            if row:
                self.list_layout.insertWidget(index, row)  # re-inserting moves an existing widget
                row.update_from(job)
        running = self.manager.queue_running
        waiting = self.manager.waiting_count()
        active = self.manager.active_count()
        self.empty.setVisible(not jobs)
        self.start_btn.setVisible(not running)
        self.stop_btn.setVisible(running)
        self.clear_btn.setVisible(any(j.state in (JobState.QUEUED, JobState.PAUSED) for j in jobs))
        if running:
            text = f"Queue running · {active} active · {waiting} waiting"
        else:
            text = f"Queue stopped · {active} active · {waiting} waiting"
            if waiting:
                text += " — waiting downloads won't start until you press Start queue"
        self.state_label.setText(text)
