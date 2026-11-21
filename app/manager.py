"""Download manager: owns every download job, the queue order and the concurrency limit."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QPixmap

from app.choices import SPEED_LIMITS, in_window, parse_clock
from app.config import MAX_CONCURRENT_LIMIT, Settings
from app.downloader import (
    CancelToken, DownloadRequest, DownloadResult, ProgressInfo, remove_partials, run_download,
)
from app.errors import DownloadCancelled, friendly_message
from app.queue_store import item_for, load_queue, request_from_dict, save_queue
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
    from_queue: bool = False   # started by the queue (not by the user): may be paused by the schedule
    auto_paused: bool = False  # paused by the schedule; resumes when the window opens again
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
        self.clock = datetime.now            # replaced in tests
        self._store: Path | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_now)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(20_000)
        self._tick_timer.timeout.connect(self.tick)
        self._tick_timer.start()
        self.queue_changed.connect(self._schedule_save)
        self.job_added.connect(lambda _j: self._schedule_save())
        self.job_removed.connect(lambda _i: self._schedule_save())

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
        if any(j.request.output_dir == request.output_dir and j.title == request.title
               and j.request.url != request.url and not request.playlist and not j.request.playlist
               and j.state not in (JobState.CANCELLED, JobState.FAILED) for j in self._jobs.values()):
            request.unique_name = True   # different media, same title, same folder: keep both files
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
        job.auto_paused = False
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
        self.save_now()   # before the active jobs are paused, so they come back as "queued"
        self._closing = True
        for job in self._jobs.values():
            if job.token and job.state is JobState.ACTIVE:
                job.token.cancel(keep_partial=True)
        self._pool.clear()
        self._pool.waitForDone(wait_ms)

    def move_to(self, job_id: int, index: int) -> None:
        """Put a queued job at ``index`` among the queue jobs (0 = first). Used by drag and drop."""
        queue = [j.id for j in self.queue_jobs()]
        if job_id not in queue:
            return
        index = max(0, min(index, len(queue) - 1))
        if queue.index(job_id) == index:
            return
        queue.remove(job_id)
        queue.insert(index, job_id)
        # rewrite only the slots occupied by queue jobs, so finished jobs keep their places
        slots = [i for i, jid in enumerate(self._order) if jid in set(queue)]
        for slot, jid in zip(slots, queue):
            self._order[slot] = jid
        self.queue_changed.emit()

    # -- persistence -------------------------------------------------------
    def enable_persistence(self, path: Path) -> int:
        """Restore the saved queue from ``path`` and keep saving it. Returns the number restored."""
        self._store = path
        running, items = load_queue(path)
        restored = 0
        if running is not None:
            self.queue_running = running
        for item in items:
            request = request_from_dict(item["request"])
            if request is None or not request.output_dir:
                continue
            job = self.add(request, None, start_now=False)
            job.partials = [p for p in item.get("partials", []) if isinstance(p, str)]
            job.manual = bool(item.get("manual"))
            job.auto_paused = bool(item.get("auto_paused"))
            if item.get("state") == "paused":
                self._set_state(job, JobState.PAUSED)
            restored += 1
        self.queue_changed.emit()
        self._pump()
        return restored

    def _schedule_save(self) -> None:
        if self._store is not None and not self._closing:
            self._save_timer.start()

    def save_now(self) -> None:
        if self._store is None:
            return
        items = []
        for job in self.queue_jobs():
            state = "paused" if job.state is JobState.PAUSED else "queued"
            items.append(item_for(job.request, state, job.manual or job.state is JobState.ACTIVE
                                  and not job.from_queue, job.auto_paused, job.partials))
        save_queue(self._store, self.queue_running, items)

    # -- schedule ------------------------------------------------------------
    def schedule_enabled(self) -> bool:
        return bool(self.settings.get("schedule_enabled"))

    def schedule_open(self) -> bool:
        """True when queued downloads may run now (always true if no schedule is set)."""
        if not self.schedule_enabled():
            return True
        return in_window(self.clock().time(), parse_clock(self.settings.get("schedule_start")),
                         parse_clock(self.settings.get("schedule_end")))

    def schedule_text(self) -> str:
        if not self.schedule_enabled():
            return ""
        window = f"{self.settings.get('schedule_start')}–{self.settings.get('schedule_end')}"
        return f"Scheduled {window}" + ("" if self.schedule_open() else " · waiting for the window")

    def tick(self) -> None:
        """Called every 20 s (and on schedule changes): open/close the schedule window."""
        if self._closing:
            return
        if self.schedule_open():
            woke = [j for j in self._jobs.values() if j.state is JobState.PAUSED and j.auto_paused]
            for job in woke:
                job.auto_paused = False
                self._set_state(job, JobState.QUEUED)
            self._pump()
        else:
            for job in self._jobs.values():
                if job.state is JobState.ACTIVE and job.from_queue and job.token and not job.stop_reason:
                    job.stop_reason = "scheduled"
                    job.phase = "Waiting for the schedule…"
                    job.token.cancel(keep_partial=True)
                    self.job_updated.emit(job)
        self.queue_changed.emit()

    def speed_per_download(self) -> int:
        """Bytes/second each download may use so that all together stay under the chosen limit."""
        total = SPEED_LIMITS.get(self.settings.get("speed_limit"), 0)
        return total // max(1, self.settings.max_concurrent) if total else 0

    # -- scheduling --------------------------------------------------------
    def _on_setting_changed(self, key: str, _value: object) -> None:
        if key == "max_concurrent":
            self._pump()
        elif key.startswith("schedule_"):
            self.tick()

    def _pump(self) -> None:
        if self._closing:
            return
        limit = self.settings.max_concurrent
        active = self.active_count()
        waiting = [j for j in self.jobs() if j.state is JobState.QUEUED]
        waiting.sort(key=lambda j: not j.manual)  # stable: user-started jobs jump ahead
        open_now = self.schedule_open()
        for job in waiting:
            if active >= limit:
                break
            if job.manual or (self.queue_running and open_now):
                self._start(job)
                active += 1

    def _start(self, job: DownloadJob) -> None:
        job.token = CancelToken()
        job.stop_reason = ""
        job.from_queue = not job.manual
        job.manual = False
        job.request.rate_limit = self.speed_per_download()
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
        paused = job.stop_reason in ("paused", "scheduled")
        job.auto_paused = job.stop_reason == "scheduled"
        job.partials = partials if paused else []
        job.speed, job.eta, job.phase, job.stop_reason = None, None, "", ""
        self._set_state(job, JobState.PAUSED if paused else JobState.CANCELLED)
        self.queue_changed.emit()
        self._pump()
