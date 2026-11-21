"""Saves the download queue to disk so it survives restarts (JSON, written atomically)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from app.downloader import DownloadRequest

log = logging.getLogger("quanttum.queue")
VERSION = 1


def save_queue(path: Path, running: bool, items: list[dict[str, Any]]) -> bool:
    """Write the queue. Returns False (and logs) if the file couldn't be written."""
    data = {"version": VERSION, "running": running, "items": items}
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        log.exception("Could not save the queue")
        return False


def load_queue(path: Path) -> tuple[bool | None, list[dict[str, Any]]]:
    """Read the queue; a missing or damaged file gives an empty queue (never raises).

    The first value is the saved running/stopped state, or None when there is nothing saved."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = [i for i in data.get("items", []) if isinstance(i, dict) and isinstance(i.get("request"), dict)]
        return bool(data.get("running", True)), items
    except FileNotFoundError:
        return None, []
    except (OSError, ValueError, AttributeError):
        log.warning("Queue file unreadable; starting with an empty queue", exc_info=True)
        return None, []


def request_from_dict(data: dict[str, Any]) -> DownloadRequest | None:
    """Rebuild a DownloadRequest, ignoring unknown fields (older/newer versions)."""
    allowed = {f.name for f in fields(DownloadRequest)}
    try:
        return DownloadRequest(**{k: v for k, v in data.items() if k in allowed})
    except TypeError:
        return None


def item_for(request: DownloadRequest, state: str, manual: bool, auto_paused: bool,
             partials: list[str]) -> dict[str, Any]:
    return {"request": asdict(request), "state": state, "manual": manual,
            "auto_paused": auto_paused, "partials": partials}
