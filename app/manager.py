"""Download manager: owns every download job, the queue order and the concurrency limit."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QPixmap

from app.config import MAX_CONCURRENT_LIMIT, Settings
from app.downloader import (
    CancelToken, DownloadRequest, DownloadResult, ProgressInfo, remove_partials, run_download,
)
from app.errors import DownloadCancelled, friendly_message
from app.signals import signals
from app.system import move_to_trash

log = logging.getLogger("quanttum.manager")


class JobState(str, Enum):
    QUEUED = "queued"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED_STATES = (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)
QUEUE_STATES = (JobState.QUEUED, JobState.ACTIVE, JobState.PAUSED)


@dataclass
class DownloadJob:
    """Live state of one download. Mutated only on the GUI thread."""

    id: int
    request: DownloadRequest
    thumbnail: QPixmap | None = None
    state: JobState = JobState.QUEUED
    phase: str = ""
    percent: float = 0.0
    downloaded: int | None = None
    total: int | None = None
    speed: float | None = None
    eta: int | None = None
    item: int = 1
    items: int = 1
    error: str = ""
    files: list[str] = field(default_factory=list)
    size_bytes: int = 0
    notes: list[str] = field(default_factory=list)
    partials: list[str] = field(default_factory=list)
    token: CancelToken | None = None
    stop_reason: str = ""      # "paused" | "cancelled" while a stop is pending
    manual: bool = False       # explicitly started by the user: ignores a stopped queue
    files_deleted: bool = False

    @property
    def title(self) -> str:
        return self.request.title

    @property
    def is_finished(self) -> bool:
        return self.state in FINISHED_STATES


class _WorkerSignals(QObject):
    progress = Signal(int, object)   # job id, ProgressInfo
    finished = Signal(int, object)   # job id, DownloadResult
    failed = Signal(int, str)        # job id, friendly message
    stopped = Signal(int, object)    # job id, list of partial files


class _DownloadWorker(QRunnable):
    """Runs one download on a pool thread and reports through signals."""

    def __init__(self, job_id: int, request: DownloadRequest, token: CancelToken, sig: _WorkerSignals) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.job_id, self.request, self.token, self.sig = job_id, request, token, sig

    def run(self) -> None:
        try:
            result = run_download(
                self.request, lambda p: self.sig.progress.emit(self.job_id, p), self.token,
            )
        except DownloadCancelled as exc:
            self.sig.stopped.emit(self.job_id, list(exc.partials))
        except Exception as exc:  # noqa: BLE001 - everything becomes a friendly message
            log.error("Download failed for %s: %s", self.request.url, exc, exc_info=True)
            self.sig.failed.emit(self.job_id, friendly_message(exc))
        else:
            self.sig.finished.emit(self.job_id, result)


class DownloadManager(QObject):
    """Creates, schedules and controls download jobs."""

    job_added = Signal(object)
    job_updated = Signal(object)
    job_removed = Signal(int)
    job_completed = Signal(object)   # history + notifications
    job_failed = Signal(object)      # notifications
    files_deleted = Signal(object)   # a job's files were deleted from disk (history sync)
    queue_changed = Signal()         # order or running/stopped state changed

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._jobs: dict[int, DownloadJob] = {}
        self._order: list[int] = []
        self._next_id = 1
        self._closing = False
        self.queue_running = True
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(MAX_CONCURRENT_LIMIT)
        self._sig = _WorkerSignals(self)
        self._sig.progress.connect(self._on_progress)
        self._sig.finished.connect(self._on_finished)
        self._sig.failed.connect(self._on_failed)
        self._sig.stopped.connect(self._on_stopped)
        signals.setting_changed.connect(self._on_setting_changed)

    # -- queries -----------------------------------------------------------
    def jobs(self) -> list[DownloadJob]:
        """All jobs in queue order."""
        return [self._jobs[i] for i in self._order if i in self._jobs]

    def queue_jobs(self) -> list[DownloadJob]:
        """Jobs that are waiting, running or paused, in the order they will start."""
        return [j for j in self.jobs() if j.state in QUEUE_STATES]

    def job(self, job_id: int) -> DownloadJob | None:
        return self._jobs.get(job_id)

    def active_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.state is JobState.ACTIVE)

    def waiting_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.state is JobState.QUEUED)

    # -- adding / removing -------------------------------------------------
    def add(self, request: DownloadRequest, thumbnail: QPixmap | None = None, start_now: bool = True) -> DownloadJob:
        """Register a download.

        ``start_now=True`` starts it as soon as a slot is free, even if the queue is stopped.
        ``start_now=False`` adds it to the queue, where it follows the queue's running state.
        An identical download that is already queued, running or paused is returned instead of
        creating a duplicate (two jobs would write to the same files).
        """
        for existing in self._jobs.values():
            if existing.state in QUEUE_STATES and existing.request.key() == request.key():
                if start_now and existing.state is JobState.QUEUED:
                    existing.manual = True
                    self._pump()
                return existing
        if thumbnail is not None and not thumbnail.isNull():
            thumbnail = thumbnail.scaled(
                256, 144, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )  # small copy: keeps memory low with many jobs
        else:
            thumbnail = None
        job = DownloadJob(id=self._next_id, request=request, thumbnail=thumbnail, manual=start_now)
        self._next_id += 1
        self._jobs[job.id] = job
        self._order.append(job.id)
        self.job_added.emit(job)
        self.queue_changed.emit()
        self._pump()
        return job

    def remove(self, job_id: int) -> None:
        """Remove a job from the list (never deletes downloaded media)."""
        job = self._jobs.get(job_id)
        if not job or job.state is JobState.ACTIVE:
            return
        if job.state is JobState.PAUSED:
            remove_partials(job.partials)
        self._jobs.pop(job_id, None)
        if job_id in self._order:
            self._order.remove(job_id)
        self.job_removed.emit(job_id)
        self.queue_changed.emit()
        self._pump()

    def clear_completed(self) -> None:
        for job in [j for j in self._jobs.values() if j.state is JobState.COMPLETED]:
            self.remove(job.id)

    def clear_queue(self) -> None:
        """Cancel every download that has not started yet (running ones are left alone)."""
        for job in [j for j in self.jobs() if j.state in (JobState.QUEUED, JobState.PAUSED)]:
            self.cancel(job.id)

    # -- per-job controls --------------------------------------------------
    def pause(self, job_id: int) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        if job.state is JobState.QUEUED:
            job.manual = False
            self._set_state(job, JobState.PAUSED)
        elif job.state is JobState.ACTIVE and job.token and not job.stop_reason:
            job.stop_reason = "paused"
            job.phase = "Pausing…"
            job.token.cancel(keep_partial=True)
            self.job_updated.emit(job)

    def resume(self, job_id: int) -> None:
        job = self._jobs.get(job_id)
        if job and job.state is JobState.PAUSED:
            job.manual = True
            self._set_state(job, JobState.QUEUED)
            self._pump()

    def cancel(self, job_id: int) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        if job.state is JobState.ACTIVE and job.token and job.stop_reason != "cancelled":
            job.stop_reason = "cancelled"
            job.phase = "Cancelling…"
            job.token.cancel(keep_partial=False)
            self.job_updated.emit(job)
        elif job.state in (JobState.QUEUED, JobState.PAUSED):
            remove_partials(job.partials)
            job.partials = []
            self._set_state(job, JobState.CANCELLED)
            self.queue_changed.emit()
            self._pump()

    def retry(self, job_id: int) -> None:
        job = self._jobs.get(job_id)
        if job and job.state in (JobState.FAILED, JobState.CANCELLED):
            job.error, job.percent, job.stop_reason = "", 0.0, ""
            job.downloaded = job.total = job.speed = job.eta = None
            job.manual = True
            self._set_state(job, JobState.QUEUED)
            self.queue_changed.emit()
            self._pump()

    def delete_files(self, job_id: int) -> tuple[int, int]:
        """Move a completed download's files to the Recycle Bin. Returns (deleted, failed)."""
        job = self._jobs.get(job_id)
        if not job or job.state is not JobState.COMPLETED or job.files_deleted:
            return 0, 0
        deleted = failed = 0
        for path in job.files:
            if not os.path.exists(path):
                deleted += 1  # already gone: nothing left to delete
            elif move_to_trash(path):
                deleted += 1
            else:
                failed += 1
        if failed == 0:
            job.files_deleted = True
        self.job_updated.emit(job)
        if job.files_deleted:
            self.files_deleted.emit(job)
        return deleted, failed

    # -- queue ordering and control ---------------------------------------
    def move(self, job_id: int, direction: int) -> None:
        """Move a waiting job one place up (-1) or down (+1) in the queue."""
        queue = [j.id for j in self.queue_jobs()]
        if job_id not in queue:
            return
        idx = queue.index(job_id)
        other = idx + direction
        if not 0 <= other < len(queue):
            return
        a, b = self._order.index(queue[idx]), self._order.index(queue[other])
        self._order[a], self._order[b] = self._order[b], self._order[a]
        self.queue_changed.emit()

    def start_queue(self) -> None:
        self.queue_running = True
        self.queue_changed.emit()
        self._pump()

    def stop_queue(self) -> None:
        """Stop starting new downloads. Running downloads finish normally."""
        self.queue_running = False
        self.queue_changed.emit()

    def shutdown(self, wait_ms: int = 8000) -> None:
        """Pause active downloads (keeping partial data) and wait for their threads."""
        self._closing = True
        for job in self._jobs.values():
            if job.token and job.state is JobState.ACTIVE:
                job.token.cancel(keep_partial=True)
        self._pool.clear()
        self._pool.waitForDone(wait_ms)

    # -- scheduling --------------------------------------------------------
    def _on_setting_changed(self, key: str, _value: object) -> None:
        if key == "max_concurrent":
            self._pump()

    def _pump(self) -> None:
        if self._closing:
            return
        limit = self.settings.max_concurrent
        active = self.active_count()
        waiting = [j for j in self.jobs() if j.state is JobState.QUEUED]
        waiting.sort(key=lambda j: not j.manual)  # stable: user-started jobs jump ahead
        for job in waiting:
            if active >= limit:
                break
            if job.manual or self.queue_running:
                self._start(job)
                active += 1

    def _start(self, job: DownloadJob) -> None:
        job.token = CancelToken()
        job.stop_reason = ""
        job.manual = False
        job.phase = "Starting…"
        job.percent = 0.0
        self._set_state(job, JobState.ACTIVE)
        self._pool.start(_DownloadWorker(job.id, job.request, job.token, self._sig))

    def _set_state(self, job: DownloadJob, state: JobState) -> None:
        job.state = state
        self.job_updated.emit(job)

    # -- worker results (GUI thread) ---------------------------------------
    def _on_progress(self, job_id: int, p: ProgressInfo) -> None:
        job = self._jobs.get(job_id)
        if not job or job.state is not JobState.ACTIVE or self._closing:
            return
        job.percent, job.downloaded, job.total = p.percent, p.downloaded, p.total
        job.speed, job.eta, job.item, job.items = p.speed, p.eta, p.item, p.items
        if not job.stop_reason:
            job.phase = p.phase
        self.job_updated.emit(job)

    def _on_finished(self, job_id: int, result: DownloadResult) -> None:
        job = self._jobs.get(job_id)
        if not job or self._closing:
            return
        job.files, job.size_bytes, job.notes = result.files, result.size_bytes, result.notes
        job.percent, job.speed, job.eta, job.phase, job.stop_reason = 100.0, None, None, "", ""
        self._set_state(job, JobState.COMPLETED)
        self.job_completed.emit(job)
        self.queue_changed.emit()
        self._pump()

    def _on_failed(self, job_id: int, message: str) -> None:
        job = self._jobs.get(job_id)
        if not job or self._closing:
            return
        job.error, job.speed, job.eta, job.phase, job.stop_reason = message, None, None, "", ""
        self._set_state(job, JobState.FAILED)
        self.job_failed.emit(job)
        self.queue_changed.emit()
        self._pump()

    def _on_stopped(self, job_id: int, partials: list[str]) -> None:
        job = self._jobs.get(job_id)
        if not job or self._closing:
            return
        paused = job.stop_reason == "paused"
        job.partials = partials if paused else []
        job.speed, job.eta, job.phase, job.stop_reason = None, None, "", ""
        self._set_state(job, JobState.PAUSED if paused else JobState.CANCELLED)
        self.queue_changed.emit()
        self._pump()
