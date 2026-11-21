"""Media metadata extraction (yt-dlp) plus URL and formatting helpers. No Qt imports."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.cookies import cookie_ydl_options

log = logging.getLogger("quanttum.media")

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BARE_DOMAIN_RE = re.compile(r"^[\w-]+(\.[\w-]+)+(/|$)", re.IGNORECASE)


@dataclass(slots=True)
class MediaInfo:
    """Metadata describing an analysed URL."""

    url: str
    title: str
    channel: str = ""
    duration_seconds: int | None = None
    thumbnail_url: str = ""
    video_heights: list[int] = field(default_factory=list)
    has_audio: bool = True
    subtitle_langs: list[str] = field(default_factory=list)
    is_playlist: bool = False
    entry_count: int = 1
    extractor: str = ""
    part_of_playlist: bool = False  # a single video whose link also names a playlist
    site: str = ""                  # display name of the source site (YouTube, Vimeo, example.com…)


# --------------------------------------------------------------------------
# URL helpers
# --------------------------------------------------------------------------
def first_url(text: str) -> str | None:
    """Return the first http(s) URL found in ``text`` (only the first 2 KB is scanned)."""
    match = _URL_RE.search(text[:2048])
    return match.group(0).rstrip(").,;") if match else None


def all_urls(text: str, limit: int = 200) -> list[str]:
    """Every distinct http(s) link in ``text`` (any whitespace/newline separated), in order."""
    seen: dict[str, None] = {}
    for match in _URL_RE.finditer(text[:200_000]):
        seen.setdefault(match.group(0).rstrip(").,;"), None)
        if len(seen) >= limit:
            break
    if not seen:  # accept bare domains such as "youtu.be/abc" one per line
        for token in text.split():
            candidate = normalise_url(token)
            if candidate.startswith("http") and is_valid_url(candidate):
                seen.setdefault(candidate, None)
    return list(seen)


_SITE_NAMES = {
    "youtube": "YouTube", "youtubetab": "YouTube", "youtubeplaylist": "YouTube", "tiktok": "TikTok",
    "twitter": "X (Twitter)", "soundcloud": "SoundCloud", "vimeo": "Vimeo", "facebook": "Facebook",
    "instagram": "Instagram", "twitch": "Twitch", "dailymotion": "Dailymotion", "reddit": "Reddit",
    "bandcamp": "Bandcamp", "bilibili": "Bilibili", "vk": "VK", "odnoklassniki": "OK.ru",
    "mixcloud": "Mixcloud", "streamable": "Streamable", "rumble": "Rumble", "linkedin": "LinkedIn",
}


def site_name(extractor: str, url: str) -> str:
    """Friendly site name from yt-dlp's extractor key, falling back to the link's host."""
    key = re.sub(r"(Playlist|Tab|User|Channel|Album|Set|Live|Clip|Short)s?$", "", extractor or "")
    low = key.lower() or (extractor or "").lower()
    if low in _SITE_NAMES:
        return _SITE_NAMES[low]
    if not extractor or extractor.lower() == "generic":
        return host_of(url) or "Web"
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key or extractor)


def normalise_url(text: str) -> str:
    """Trim whitespace and add ``https://`` to scheme-less links like ``youtu.be/abc``."""
    text = text.strip()
    if text and "://" not in text and _BARE_DOMAIN_RE.match(text):
        return "https://" + text
    return text


def is_valid_url(url: str) -> bool:
    """True when ``url`` is a well-formed http(s) address with a real-looking host."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = parsed.hostname or ""
    return parsed.scheme in ("http", "https") and "." in host and " " not in url


def is_video_in_playlist(url: str) -> bool:
    """True for YouTube links that name both a video and a playlist (``watch?v=…&list=…``)."""
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
    except ValueError:
        return False
    host = (parsed.hostname or "").removeprefix("www.")
    is_youtube = host.endswith("youtube.com") or host == "youtu.be" or host.endswith("youtube-nocookie.com")
    return is_youtube and "list" in query and ("v" in query or host == "youtu.be")


def host_of(url: str) -> str:
    """Return the host part of ``url`` without a leading ``www.``."""
    host = urlparse(url).hostname or ""
    return host.removeprefix("www.")


def shorten(text: str, limit: int = 70) -> str:
    """Shorten long strings (such as URLs) in the middle."""
    if len(text) <= limit:
        return text
    head = int(limit * 0.65)
    return f"{text[:head]}…{text[-(limit - head - 1):]}"


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def format_duration(seconds: int | None) -> str:
    """Format seconds as ``M:SS`` or ``H:MM:SS``."""
    if seconds is None:
        return "—"
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def human_size(num_bytes: float | None) -> str:
    """Format a byte count using binary units."""
    if num_bytes is None:
        return "—"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------
class _YtdlpLogger:
    """Route yt-dlp output into our log file instead of the console."""

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        log.debug("yt-dlp warning: %s", msg)

    def error(self, msg: str) -> None:
        log.debug("yt-dlp error: %s", msg)


def _best_thumbnail(info: dict[str, Any]) -> str:
    """Pick a JPEG thumbnail URL where possible (WebP support varies)."""
    thumbs = [t for t in (info.get("thumbnails") or []) if t.get("url")]
    jpgs = [t for t in thumbs if ".jpg" in t["url"].lower() or ".jpeg" in t["url"].lower()]
    if info.get("thumbnail"):
        return str(info["thumbnail"])
    pool = jpgs or thumbs
    return str(pool[-1]["url"]) if pool else ""


def build_media_info(url: str, info: dict[str, Any]) -> MediaInfo:
    """Convert a yt-dlp info dict into a :class:`MediaInfo`."""
    if info.get("_type") == "playlist" or "entries" in info:
        entries = [e for e in (info.get("entries") or []) if e]
        thumb = _best_thumbnail(info)
        if not thumb and entries:
            thumb = _best_thumbnail(entries[0])
        return MediaInfo(
            url=url,
            title=str(info.get("title") or "Untitled playlist"),
            channel=str(info.get("uploader") or info.get("channel") or ""),
            thumbnail_url=thumb,
            is_playlist=True,
            entry_count=int(info.get("playlist_count") or len(entries)),
            extractor=str(info.get("extractor_key") or ""),
            site=site_name(str(info.get("extractor_key") or ""), url),
        )

    formats = info.get("formats") or []
    heights = sorted(
        {int(f["height"]) for f in formats
         if f.get("height") and f.get("vcodec") not in (None, "none")},
        reverse=True,
    )
    has_audio = any(f.get("acodec") not in (None, "none") for f in formats) if formats else True
    duration = info.get("duration")
    return MediaInfo(
        url=url,
        title=str(info.get("title") or "Untitled"),
        channel=str(info.get("channel") or info.get("uploader") or ""),
        duration_seconds=int(duration) if duration else None,
        thumbnail_url=_best_thumbnail(info),
        video_heights=heights,
        has_audio=has_audio,
        subtitle_langs=sorted((info.get("subtitles") or {}).keys()),
        extractor=str(info.get("extractor_key") or ""),
        site=site_name(str(info.get("extractor_key") or ""), url),
    )


def analyse_url(url: str, cookies_browser: str = "", cookies_file: str = "") -> MediaInfo:
    """Fetch metadata for ``url`` with yt-dlp (blocking — call from a worker thread).

    Raises whatever yt-dlp raises; callers translate it with ``errors.friendly_message``.
    """
    import yt_dlp  # imported lazily so the UI starts fast and works without yt-dlp installed

    in_playlist = is_video_in_playlist(url)
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": in_playlist,  # preview just the video; the options panel offers the whole list
        "extract_flat": "in_playlist",
        "socket_timeout": 15,
        "retries": 2,
        "logger": _YtdlpLogger(),
    }
    options.update(cookie_ydl_options(cookies_browser, cookies_file))
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise ValueError("No media information was returned for this link.")
    media = build_media_info(url, info)
    media.part_of_playlist = in_playlist and not media.is_playlist
    return media
