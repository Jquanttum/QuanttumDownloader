"""yt-dlp download engine. Qt-free: progress goes out via callbacks, cancellation comes in via a token."""

from __future__ import annotations

import glob
import logging
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.choices import FOLDER_LAYOUTS, NAME_TEMPLATES, trim_stamp
from app.config import ARCHIVE_PATH
from app.cookies import cookie_ydl_options
from app.errors import DiskSpaceError, DownloadCancelled, MissingFFmpegError, OutputFolderError

log = logging.getLogger("quanttum.downloader")

MIN_FREE_BYTES = 200 * 1024 * 1024
PROGRESS_INTERVAL = 0.25  # seconds between UI progress updates per download

VIDEO_CONTAINERS: tuple[str, ...] = ("MP4", "MKV", "WEBM")
AUDIO_BITRATES: tuple[str, ...] = ("128", "192", "256", "320")

_AUDIO_CODECS = {"MP3": "mp3", "M4A": "m4a", "WAV": "wav"}
_FORMAT_SORT = {
    "MP4": ["res", "vcodec:h264", "acodec:m4a"],
    "WEBM": ["res", "vcodec:vp9", "acodec:opus"],
    "MKV": ["res"],
}
_PP_PHASES = {
    "Merger": "Merging video and audio",
    "ExtractAudio": "Converting audio",
    "Metadata": "Writing metadata",
    "EmbedThumbnail": "Embedding thumbnail",
    "ThumbnailsConvertor": "Preparing thumbnail",
    "SubtitlesConvertor": "Converting subtitles",
    "MoveFiles": "Finishing",
}


@dataclass(slots=True)
class DownloadRequest:
    """Everything needed to perform one download."""

    url: str
    title: str
    kind: str = "video"            # "video" | "audio"
    height: int | None = None      # maximum video height; None = best available
    container: str = "MP4"         # video container
    audio_format: str = "MP3"
    audio_bitrate: str = "192"
    output_dir: str = ""
    subtitle_lang: str = ""
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    playlist: bool = False
    ffmpeg_path: str = ""          # resolved ffmpeg executable, or "" when unavailable
    cookies_browser: str = ""      # sign-in cookies: browser name, or ""
    cookies_file: str = ""         # sign-in cookies: Netscape cookies.txt, or ""
    site: str = ""                 # display name of the source site
    unique_name: bool = False      # add the video id to the file name (set when another job has the same title)
    name_template: str = "Title"   # key of choices.NAME_TEMPLATES
    folder_layout: str = "Flat"    # key of choices.FOLDER_LAYOUTS
    rate_limit: int = 0            # bytes/second for this download (0 = unlimited); set when it starts
    trim_start: float = 0.0        # seconds; with trim_end > 0 or trim_start > 0 only that part is saved
    trim_end: float = 0.0          # seconds; 0 = until the end
    playlist_items: str = ""       # yt-dlp item spec such as "1,3,5-7"; "" = all
    skip_downloaded: bool = False  # skip videos whose id is already in the download archive

    @property
    def is_audio(self) -> bool:
        return self.kind == "audio"

    @property
    def wants_trim(self) -> bool:
        return not self.playlist and (self.trim_start > 0 or self.trim_end > 0)

    @property
    def format_label(self) -> str:
        return self.audio_format if self.is_audio else self.container

    @property
    def quality_label(self) -> str:
        if self.is_audio:
            return "Lossless" if self.audio_format == "WAV" else f"{self.audio_bitrate} kbps"
        return f"Up to {self.height}p" if self.height else "Best quality"

    def key(self) -> tuple:
        """Identity of the output this request produces (used to avoid duplicate jobs)."""
        return (self.url, self.kind, self.height, self.container, self.audio_format,
                self.audio_bitrate, self.output_dir, self.playlist, self.subtitle_lang)

    def supports_thumbnail_embed(self) -> bool:
        if self.is_audio:
            return self.audio_format in ("MP3", "M4A")
        return self.container in ("MP4", "MKV")


@dataclass(slots=True)
class ProgressInfo:
    """A snapshot of download progress, safe to pass between threads."""

    percent: float = 0.0
    downloaded: int | None = None
    total: int | None = None
    speed: float | None = None
    eta: int | None = None
    phase: str = "Downloading"
    item: int = 1
    items: int = 1


@dataclass(slots=True)
class DownloadResult:
    """Outcome of a finished download."""

    files: list[str] = field(default_factory=list)
    size_bytes: int = 0
    notes: list[str] = field(default_factory=list)


class CancelToken:
    """Thread-safe cancellation flag. ``keep_partial`` distinguishes pause from cancel."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.keep_partial = True

    def cancel(self, keep_partial: bool = False) -> None:
        self.keep_partial = keep_partial
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


class _YtdlpLogger:
    """Send yt-dlp's own messages to our log file instead of the console."""

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        log.warning("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        log.error("yt-dlp: %s", msg)


def remove_partials(paths: list[str] | set[str]) -> None:
    """Delete leftover ``.part`` / ``.ytdl`` / fragment files that we saw yt-dlp create."""
    for path in paths:
        try:
            for match in glob.glob(glob.escape(path) + "*"):
                try:
                    os.remove(match)
                except OSError:
                    log.debug("Could not remove %s", match, exc_info=True)
        except Exception:  # pragma: no cover - cleanup must never raise
            log.debug("Partial cleanup failed for %s", path, exc_info=True)


class _Tracker:
    """Translates yt-dlp hook callbacks into throttled :class:`ProgressInfo` updates."""

    def __init__(self, on_progress: Callable[[ProgressInfo], None], token: CancelToken) -> None:
        self.on_progress = on_progress
        self.token = token
        self.partials: set[str] = set()
        self.files: list[str] = []
        self._streams: dict[str, int] = {}
        self._item: Any = None
        self._checked: set[str] = set()
        self._last_emit = 0.0
        self._last = ProgressInfo()

    # -- download hook -----------------------------------------------------
    def on_download(self, d: dict[str, Any]) -> None:
        # Record partial-file names first, so a cancel arriving at the very first callback
        # can still clean up the file yt-dlp has just created.
        tmp = d.get("tmpfilename")
        name = str(d.get("filename") or "")
        if tmp:
            self.partials.add(str(tmp))
        if name:
            self.partials.add(name + ".ytdl")
        if self.token.is_set():
            raise DownloadCancelled()
        status = d.get("status")
        if status not in ("downloading", "finished"):
            return
        info = d.get("info_dict") or {}

        item = int(info.get("playlist_index") or 1)
        items = int(info.get("n_entries") or 1)
        if item != self._item:
            self._item, self._streams = item, {}
        stream_idx = self._streams.setdefault(name, len(self._streams))
        n_streams = max(1, len(info.get("requested_formats") or ()))

        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        done = d.get("downloaded_bytes")
        if total and name and name not in self._checked:
            self._checked.add(name)
            self._check_space(name, int(total))

        if status == "finished":
            frac = 1.0
        elif total and done is not None:
            frac = min(1.0, done / total)
        elif d.get("fragment_count"):
            frac = min(1.0, (d.get("fragment_index") or 0) / d["fragment_count"])
        else:
            frac = 0.0

        percent = 100.0 * ((item - 1) + (min(stream_idx, n_streams - 1) + frac) / n_streams) / items
        phase = "Downloading"
        if n_streams > 1:
            phase += " video" if info.get("vcodec") not in (None, "none") else " audio"
        snapshot = ProgressInfo(
            percent=min(percent, 100.0),
            downloaded=int(done) if done is not None else None,
            total=int(total) if total else None,
            speed=d.get("speed"),
            eta=int(d["eta"]) if d.get("eta") is not None else None,
            phase=phase,
            item=item,
            items=items,
        )
        self._last = snapshot
        now = time.monotonic()
        if status == "finished" or now - self._last_emit >= PROGRESS_INTERVAL:
            self._last_emit = now
            self.on_progress(snapshot)

    @staticmethod
    def _check_space(filename: str, total: int) -> None:
        try:
            free = shutil.disk_usage(Path(filename).parent).free
        except OSError:
            return
        if free < total * 1.1:
            raise DiskSpaceError()

    # -- post-processing hooks --------------------------------------------
    def on_postprocess(self, d: dict[str, Any]) -> None:
        if d.get("status") != "started":
            return
        phase = _PP_PHASES.get(str(d.get("postprocessor")), "Processing")
        last = self._last
        self.on_progress(ProgressInfo(
            percent=last.percent, downloaded=last.downloaded, total=last.total,
            phase=phase, item=last.item, items=last.items,
        ))

    def on_file_done(self, filename: str) -> None:
        if filename and filename not in self.files:
            self.files.append(filename)


def _preflight(req: DownloadRequest) -> tuple[str, list[str]]:
    """Validate folder, disk space and FFmpeg. Returns (ffmpeg_dir, notes)."""
    out = Path(req.output_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=out):  # real write test (os.access lies on Windows)
            pass
    except PermissionError as exc:
        raise OutputFolderError("Permission was denied for the download folder. Choose another folder.") from exc
    except OSError as exc:
        raise OutputFolderError(
            "The download folder can't be used. Check that it exists and isn't read-only."
        ) from exc
    try:
        free = shutil.disk_usage(out).free
    except OSError:
        free = MIN_FREE_BYTES
    if free < MIN_FREE_BYTES:
        raise DiskSpaceError()

    ffmpeg = Path(req.ffmpeg_path) if req.ffmpeg_path else None
    ffmpeg_dir = str(ffmpeg.parent) if ffmpeg and ffmpeg.is_file() else ""
    if req.is_audio and not ffmpeg_dir:
        raise MissingFFmpegError()
    return ffmpeg_dir, []


def video_format_selector(height: int | None, have_ffmpeg: bool) -> str:
    """yt-dlp format expression for the requested height cap."""
    cap = f"[height<={height}]" if height else ""
    if have_ffmpeg:
        return f"bv*{cap}+ba/b{cap}/bv*+ba/b"
    return f"b{cap}/b"  # single-file formats only: no merging possible without FFmpeg


def _ffmpeg_location(ffmpeg_dir: str) -> str | None:
    """Value for yt-dlp's ``ffmpeg_location``, or None to let yt-dlp search PATH itself.

    yt-dlp accepts one folder for both ``ffmpeg`` and ``ffprobe``. When FFmpeg came from PATH and
    ``ffprobe`` lives elsewhere, passing the folder would hide ``ffprobe`` — so we pass nothing.
    """
    if not ffmpeg_dir:
        return None
    folder = Path(ffmpeg_dir)
    if any((folder / name).is_file() for name in ("ffprobe", "ffprobe.exe")):
        return ffmpeg_dir
    on_path = shutil.which("ffmpeg")
    if on_path and Path(on_path).parent == folder:
        return None
    return ffmpeg_dir


def build_options(req: DownloadRequest, ffmpeg_dir: str, tracker: _Tracker) -> tuple[dict[str, Any], list[str]]:
    """Translate a request into yt-dlp options. Returns (options, notes for the user)."""
    notes: list[str] = []
    have_ffmpeg = bool(ffmpeg_dir)
    name = NAME_TEMPLATES.get(req.name_template, NAME_TEMPLATES["Title"])
    if req.unique_name and "%(id)s" not in name:
        name += " [%(id)s]"
    if req.wants_trim:
        name += f" [{trim_stamp(req.trim_start, req.trim_end or None)}]"
    layout = FOLDER_LAYOUTS.get(req.folder_layout, "")
    template = f"{layout}{name}.%(ext)s"
    if req.playlist:
        template = f"{layout}%(playlist_title)s/%(playlist_index)s - {name}.%(ext)s"

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _YtdlpLogger(),
        "paths": {"home": req.output_dir},
        "outtmpl": template,
        "windowsfilenames": True,
        "trim_file_name": 150,
        "noplaylist": not req.playlist,
        "overwrites": False,
        "continuedl": True,
        "retries": 5,
        "fragment_retries": 5,
        "file_access_retries": 3,
        "socket_timeout": 20,
        "http_chunk_size": 10 * 1024 * 1024,
        "concurrent_fragment_downloads": 2,
        "progress_hooks": [tracker.on_download],
        "postprocessor_hooks": [tracker.on_postprocess],
        "post_hooks": [tracker.on_file_done],
    }
    location = _ffmpeg_location(ffmpeg_dir)
    if location:
        opts["ffmpeg_location"] = location
    opts.update(cookie_ydl_options(req.cookies_browser, req.cookies_file))
    if req.rate_limit > 0:
        opts["ratelimit"] = req.rate_limit
    if req.playlist and req.playlist_items:
        opts["playlist_items"] = req.playlist_items
    if req.playlist and req.skip_downloaded:
        ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        opts["download_archive"] = str(ARCHIVE_PATH)
    if req.wants_trim:
        if not have_ffmpeg:
            raise MissingFFmpegError("trim a video")
        from yt_dlp.utils import download_range_func

        opts["download_ranges"] = download_range_func(
            [], [(req.trim_start, req.trim_end if req.trim_end > 0 else float("inf"))])
        opts["force_keyframes_at_cuts"] = True

    pps: list[dict[str, Any]] = []
    if req.is_audio:
        codec = _AUDIO_CODECS.get(req.audio_format, "mp3")
        opts["format"] = "bestaudio/best"
        pp: dict[str, Any] = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
        if codec != "wav":
            pp["preferredquality"] = req.audio_bitrate
        pps.append(pp)
    else:
        opts["format"] = video_format_selector(req.height, have_ffmpeg)
        if have_ffmpeg:
            opts["merge_output_format"] = req.container.lower()
            opts["format_sort"] = _FORMAT_SORT.get(req.container, ["res"])
        else:
            notes.append("FFmpeg wasn't found, so a single-file format was downloaded (quality may be lower).")

    if req.subtitle_lang:
        opts.update(
            writesubtitles=True, writeautomaticsub=True,
            subtitleslangs=[req.subtitle_lang], subtitlesformat="srt/best",
        )
        if have_ffmpeg:
            pps.append({"key": "FFmpegSubtitlesConvertor", "format": "srt"})

    if req.embed_metadata:
        if have_ffmpeg:
            pps.append({"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True})
        else:
            notes.append("Metadata wasn't embedded because FFmpeg wasn't found.")

    if req.embed_thumbnail and req.supports_thumbnail_embed() and have_ffmpeg:
        opts["writethumbnail"] = True

    opts["postprocessors"] = pps
    return opts, notes


def _add_thumbnail_processors(ydl: Any, notes: list[str]) -> None:
    """Add thumbnail conversion + embedding that log and continue instead of failing the download."""
    from yt_dlp.postprocessor import EmbedThumbnailPP, FFmpegThumbnailsConvertorPP

    message = "The thumbnail couldn't be embedded (the file itself downloaded fine)."

    class SafeConvertor(FFmpegThumbnailsConvertorPP):
        def run(self, info: dict[str, Any]) -> Any:
            try:
                return super().run(info)
            except Exception:  # noqa: BLE001 - a thumbnail problem must not fail the download
                log.warning("Thumbnail conversion failed", exc_info=True)
                if message not in notes:
                    notes.append(message)
                return [], info

    class SafeEmbed(EmbedThumbnailPP):
        def run(self, info: dict[str, Any]) -> Any:
            try:
                return super().run(info)
            except Exception:  # noqa: BLE001
                log.warning("Thumbnail embedding failed", exc_info=True)
                if message not in notes:
                    notes.append(message)
                return [], info

    ydl.add_post_processor(SafeConvertor(ydl, format="jpg"), when="before_dl")
    ydl.add_post_processor(SafeEmbed(ydl), when="post_process")


def _subtitle_files(info: dict[str, Any] | None) -> list[str]:
    """Subtitle files yt-dlp wrote (after any conversion), from the info dict."""
    found: list[str] = []

    def visit(item: dict[str, Any] | None) -> None:
        if not item:
            return
        for entry in item.get("entries") or ():
            visit(entry)
        for dl in item.get("requested_downloads") or ():
            for sub in (dl.get("requested_subtitles") or {}).values():
                path = (sub or {}).get("filepath")
                if path and path not in found:
                    found.append(path)
        for sub in (item.get("requested_subtitles") or {}).values():
            path = (sub or {}).get("filepath")
            if path and path not in found:
                found.append(path)

    visit(info)
    return found


def _files_from_info(info: dict[str, Any] | None) -> list[str]:
    """Fallback: read output paths from yt-dlp's info dict."""
    found: list[str] = []

    def visit(item: dict[str, Any] | None) -> None:
        if not item:
            return
        for entry in item.get("entries") or ():
            visit(entry)
        for dl in item.get("requested_downloads") or ():
            path = dl.get("filepath")
            if path and path not in found:
                found.append(path)

    visit(info)
    return found


def run_download(req: DownloadRequest, on_progress: Callable[[ProgressInfo], None], token: CancelToken) -> DownloadResult:
    """Perform a download (blocking — run it on a worker thread).

    Raises :class:`DownloadCancelled` when the token is triggered, an
    :class:`~app.errors.AppError` for known problems, or yt-dlp's own exception.
    """
    ffmpeg_dir, notes = _preflight(req)
    import yt_dlp  # lazy: keeps start-up fast

    tracker = _Tracker(on_progress, token)
    opts, build_notes = build_options(req, ffmpeg_dir, tracker)
    notes += build_notes
    info: dict[str, Any] | None = None
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            if opts.get("writethumbnail"):
                _add_thumbnail_processors(ydl, notes)
            info = ydl.extract_info(req.url, download=True)
    except DownloadCancelled as exc:
        exc.partials = sorted(tracker.partials)
        if not token.keep_partial:
            remove_partials(tracker.partials)
        raise
    except Exception as exc:
        if token.is_set():  # yt-dlp wrapped our cancellation in one of its own errors
            cancelled = DownloadCancelled()
            cancelled.partials = sorted(tracker.partials)
            if not token.keep_partial:
                remove_partials(tracker.partials)
            raise cancelled from exc
        raise

    files = list(tracker.files) or _files_from_info(info)
    for sub in _subtitle_files(info):
        if sub not in files:
            files.append(sub)
    if req.subtitle_lang and not any(f.lower().endswith((".srt", ".vtt")) for f in files):
        notes.append(f"No subtitles were available for '{req.subtitle_lang}', so none were saved.")
    existing = [f for f in files if os.path.isfile(f)]
    if not existing and req.playlist and req.skip_downloaded:
        notes.append("Everything in this playlist was already downloaded, so nothing new was saved.")
        return DownloadResult(files=[], size_bytes=0, notes=notes)
    if not existing:
        raise RuntimeError("yt-dlp finished but no output file was found")
    size = sum(os.path.getsize(f) for f in existing)
    return DownloadResult(files=existing, size_bytes=size, notes=notes)
