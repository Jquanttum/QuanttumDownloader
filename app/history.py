"""SQLite download history.

Entries describe finished downloads. Removing an entry never touches the media files;
deleting files is a separate, explicit action.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from app.config import DB_PATH, Settings, ensure_dirs

log = logging.getLogger("quanttum.history")

SORTS: dict[str, tuple[str, str]] = {
    "Newest first": ("completed_at DESC, id DESC", "newest"),
    "Oldest first": ("completed_at ASC, id ASC", "oldest"),
    "Title A–Z": ("title COLLATE NOCASE ASC, id DESC", "title"),
    "Largest first": ("size_bytes DESC, id DESC", "size"),
}
_SCHEMA_VERSION = 1


@dataclass(slots=True)
class HistoryEntry:
    id: int
    title: str
    url: str
    kind: str
    format_label: str
    quality_label: str
    output_dir: str
    files: list[str]
    size_bytes: int
    completed_at: float
    files_deleted: bool
    notes: list[str] = field(default_factory=list)
    request: dict[str, Any] = field(default_factory=dict)


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class HistoryDB:
    """Thin wrapper over a SQLite file. Used from the GUI thread only."""

    def __init__(self, path: Path | str = DB_PATH) -> None:
        if str(path) != ":memory:":
            ensure_dirs()
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(path))
        self._con.row_factory = sqlite3.Row
        try:
            self._con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:  # pragma: no cover - e.g. read-only media
            pass
        self._migrate()

    def _migrate(self) -> None:
        version = self._con.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            self._con.executescript(
                """
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    format_label TEXT NOT NULL DEFAULT '',
                    quality_label TEXT NOT NULL DEFAULT '',
                    output_dir TEXT NOT NULL DEFAULT '',
                    files TEXT NOT NULL DEFAULT '[]',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    completed_at REAL NOT NULL,
                    files_deleted INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '[]',
                    request TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_history_completed ON history(completed_at);
                """
            )
            self._con.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            self._con.commit()

    # -- writes ------------------------------------------------------------
    def add(self, *, title: str, url: str, kind: str, format_label: str, quality_label: str,
            output_dir: str, files: list[str], size_bytes: int, notes: list[str],
            request: dict[str, Any], completed_at: float | None = None) -> int:
        cur = self._con.execute(
            "INSERT INTO history (title,url,kind,format_label,quality_label,output_dir,files,"
            "size_bytes,completed_at,notes,request) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (title, url, kind, format_label, quality_label, output_dir, json.dumps(files), size_bytes,
             completed_at or time.time(), json.dumps(notes), json.dumps(request)),
        )
        self._con.commit()
        return int(cur.lastrowid)

    def set_files_deleted(self, entry_id: int, deleted: bool = True) -> None:
        self._con.execute("UPDATE history SET files_deleted=? WHERE id=?", (int(deleted), entry_id))
        self._con.commit()

    def delete(self, entry_id: int) -> None:
        """Remove the entry only — never the files."""
        self._con.execute("DELETE FROM history WHERE id=?", (entry_id,))
        self._con.commit()

    def clear(self) -> None:
        self._con.execute("DELETE FROM history")
        self._con.commit()

    # -- reads -------------------------------------------------------------
    @staticmethod
    def _entry(row: sqlite3.Row) -> HistoryEntry:
        def load(text: str, default: Any) -> Any:
            try:
                return json.loads(text)
            except (TypeError, ValueError):
                return default

        return HistoryEntry(
            id=row["id"], title=row["title"], url=row["url"], kind=row["kind"],
            format_label=row["format_label"], quality_label=row["quality_label"],
            output_dir=row["output_dir"], files=load(row["files"], []), size_bytes=row["size_bytes"],
            completed_at=row["completed_at"], files_deleted=bool(row["files_deleted"]),
            notes=load(row["notes"], []), request=load(row["request"], {}),
        )

    def get(self, entry_id: int) -> HistoryEntry | None:
        row = self._con.execute("SELECT * FROM history WHERE id=?", (entry_id,)).fetchone()
        return self._entry(row) if row else None

    def query(self, search: str = "", sort: str = "Newest first", limit: int = 200) -> list[HistoryEntry]:
        order = SORTS.get(sort, SORTS["Newest first"])[0]
        sql, args = "SELECT * FROM history", []
        words = search.split()
        if words:
            sql += " WHERE " + " AND ".join(
                "(title LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\')" for _ in words)
            for w in words:
                args += [_like(w), _like(w)]
        sql += f" ORDER BY {order} LIMIT ?"  # `order` comes from the fixed SORTS table
        args.append(max(1, limit))
        return [self._entry(r) for r in self._con.execute(sql, args)]

    def count(self, search: str = "") -> int:
        words = search.split()
        sql, args = "SELECT COUNT(*) FROM history", []
        if words:
            sql += " WHERE " + " AND ".join(
                "(title LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\')" for _ in words)
            for w in words:
                args += [_like(w), _like(w)]
        return int(self._con.execute(sql, args).fetchone()[0])

    def close(self) -> None:
        try:
            self._con.close()
        except sqlite3.Error:  # pragma: no cover
            pass


class HistoryRecorder(QObject):
    """Writes finished downloads into the database and keeps ``files_deleted`` in sync."""

    changed = Signal()

    def __init__(self, db: HistoryDB, manager: Any, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.db, self.settings = db, settings
        self._ids: dict[int, int] = {}   # job id -> history id
        manager.job_completed.connect(self._on_completed)
        manager.files_deleted.connect(self._on_files_deleted)

    def _on_completed(self, job: Any) -> None:
        if not self.settings.keep_history:
            return
        req = job.request
        try:
            self._ids[job.id] = self.db.add(
                title=job.title, url=req.url, kind=req.kind, format_label=req.format_label,
                quality_label=req.quality_label, output_dir=req.output_dir, files=list(job.files),
                size_bytes=job.size_bytes, notes=list(job.notes), request=asdict(req))
        except sqlite3.Error:
            log.exception("Could not save history entry")
            return
        self.changed.emit()

    def _on_files_deleted(self, job: Any) -> None:
        entry_id = self._ids.get(job.id)
        if entry_id is None:
            return
        try:
            self.db.set_files_deleted(entry_id)
        except sqlite3.Error:
            log.exception("Could not update history entry")
            return
        self.changed.emit()
