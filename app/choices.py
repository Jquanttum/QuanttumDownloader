"""Fixed lists of choices (file naming, folder layout, speed limits) and small parsers. Qt-free."""

from __future__ import annotations

import re
from datetime import time as dtime

# label -> yt-dlp output template fragment (no free text: users pick from a safe list)
NAME_TEMPLATES: dict[str, str] = {
    "Title": "%(title)s",
    "Channel - Title": "%(uploader,channel|Unknown)s - %(title)s",
    "Title [id]": "%(title)s [%(id)s]",
    "Date - Title": "%(upload_date>%Y-%m-%d|Unknown)s - %(title)s",
}
FOLDER_LAYOUTS: dict[str, str] = {
    "Flat": "",
    "By site": "%(extractor_key)s/",
    "By channel": "%(uploader,channel|Unknown)s/",
}
# label -> total bytes per second (0 = unlimited)
SPEED_LIMITS: dict[str, int] = {
    "Unlimited": 0, "256 KB/s": 256 * 1024, "512 KB/s": 512 * 1024, "1 MB/s": 1024 * 1024,
    "2 MB/s": 2 * 1024 * 1024, "5 MB/s": 5 * 1024 * 1024,
}

_TIME_RE = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)\s*$|^\s*(\d+(?:\.\d+)?)\s*s?\s*$")


def parse_time(text: str) -> float | None:
    """Parse ``90``, ``1:20`` or ``1:02:03`` into seconds. ``""`` -> None. Raises ValueError if invalid."""
    text = text.strip()
    if not text:
        return None
    m = _TIME_RE.match(text)
    if not m:
        raise ValueError(f"Not a time: {text!r}")
    if m.group(4) is not None:
        return float(m.group(4))
    hours, minutes, seconds = int(m.group(1) or 0), int(m.group(2)), float(m.group(3))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Not a time: {text!r}")
    return hours * 3600 + minutes * 60 + seconds


def format_clock(seconds: float) -> str:
    """Seconds -> ``M:SS`` / ``H:MM:SS`` for display."""
    total = int(round(seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_clock(text: str) -> dtime:
    """``"HH:MM"`` -> time. Falls back to midnight on bad input."""
    try:
        hh, mm = text.split(":")
        return dtime(int(hh) % 24, int(mm) % 60)
    except (ValueError, AttributeError):
        return dtime(0, 0)


def in_window(now: dtime, start: dtime, end: dtime) -> bool:
    """True when ``now`` is inside [start, end). Windows may cross midnight; start == end means all day."""
    if start == end:
        return True
    if start < end:
        return start <= now < end
    return now >= start or now < end


def sections_label(start: float | None, end: float | None) -> str:
    return f"{format_clock(start or 0)}–{format_clock(end) if end else 'end'}"


def trim_stamp(start: float | None, end: float | None) -> str:
    """File-name-safe label for a trimmed section, e.g. ``1m20s-4m05s`` or ``0m10s-end``."""
    def part(sec: float) -> str:
        total = int(round(sec))
        h, rest = divmod(total, 3600)
        m, sec_ = divmod(rest, 60)
        return f"{h}h{m:02d}m{sec_:02d}s" if h else f"{m}m{sec_:02d}s"

    return f"{part(start or 0)}-{part(end) if end else 'end'}"
