"""Sign-in cookies for sites that require a login (your own account only).

The app never stores cookies itself: it remembers only *which browser* or *which cookies.txt file*
to hand to yt-dlp, and yt-dlp reads them at download time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

BROWSERS = ["Chrome", "Edge", "Firefox", "Brave", "Opera", "Vivaldi", "Chromium"]
MODES = ["Off", "From browser", "From cookies.txt"]


def cookie_settings(mode: str, browser: str, file: str) -> tuple[str, str]:
    """Return (browser, cookies_file) to put on a request; at most one is non-empty."""
    if mode == "From browser" and browser.lower() in {b.lower() for b in BROWSERS}:
        return browser.lower(), ""
    if mode == "From cookies.txt" and file:
        return "", file
    return "", ""


def cookie_ydl_options(browser: str = "", file: str = "") -> dict[str, Any]:
    """yt-dlp options for the chosen cookie source (empty dict when none)."""
    if browser:
        return {"cookiesfrombrowser": (browser.lower(),)}
    if file:
        return {"cookiefile": file}
    return {}


def check_cookies_file(path: str) -> str:
    """Return "" if ``path`` looks like a usable Netscape cookies file, else a friendly problem."""
    if not path:
        return "Choose a cookies.txt file."
    p = Path(path)
    if not p.is_file():
        return "That cookies file doesn't exist."
    try:
        head = p.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return "That cookies file can't be read."
    has_header = "netscape" in head.lower() or "# http cookie file" in head.lower()
    has_rows = any(line.count("\t") >= 6 for line in head.splitlines() if line and not line.startswith("#")
                   or line.startswith("#HttpOnly_"))
    if not (has_header or has_rows):
        return "That doesn't look like a Netscape-format cookies.txt file."
    return ""
