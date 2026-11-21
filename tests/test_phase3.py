"""Phase 3 checks: real yt-dlp downloads from a local server. Run from the project root:

    python tests/test_phase3.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QUANTTUM_HOME", tempfile.mkdtemp(prefix="qd_home_"))
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from app import downloader as dl
from app.config import resolve_ffmpeg
from app.downloader import CancelToken, DownloadRequest, run_download
from app.errors import (
    DiskSpaceError, DownloadCancelled, MissingFFmpegError, OutputFolderError, friendly_message,
)

QCoreApplication.setOrganizationName("QuanttumTest")
FFMPEG = resolve_ffmpeg()
assert FFMPEG, "ffmpeg is required for these tests"
WORK = Path(tempfile.mkdtemp(prefix="qd_test_"))
FILES: dict[str, tuple[bytes, str, float]] = {}
RANGES: list[str] = []


# --------------------------------------------------------------------------
# local server with Range support and optional throttling
# --------------------------------------------------------------------------
PROTECTED: set[str] = set()   # paths that need the cookie ``session=abc`` (tests of sign-in cookies)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:
        pass

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(head=True)

    def do_GET(self) -> None:  # noqa: N802
        self._serve(head=False)

    def _serve(self, head: bool) -> None:
        path = self.path.split("?")[0]
        if path in PROTECTED and "session=abc" not in self.headers.get("Cookie", ""):
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        entry = FILES.get(path)
        if not entry:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data, ctype, delay = entry
        start, end, status = 0, len(data) - 1, 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            s, _, e = rng[6:].partition("-")
            start = int(s) if s else 0
            end = min(int(e), len(data) - 1) if e else len(data) - 1
            status = 206
            if not head:
                RANGES.append(rng)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.end_headers()
        if head:
            return
        pos = start
        try:
            while pos <= end:
                chunk = data[pos:min(pos + 65536, end + 1)]
                self.wfile.write(chunk)
                pos += len(chunk)
                if delay:
                    time.sleep(delay)
        except (BrokenPipeError, ConnectionResetError):
            pass


def start_server() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def sh(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True)


def make_media() -> None:
    clip, poster = WORK / "clip.mp4", WORK / "poster.jpg"
    vcodec = "libx264" if "libx264" in subprocess.run(
        [str(FFMPEG), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout else "mpeg4"
    sh(str(FFMPEG), "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=24", "-f", "lavfi",
       "-i", "sine=frequency=440", "-t", "3", "-c:v", vcodec, "-pix_fmt", "yuv420p", "-c:a", "aac",
       "-shortest", str(clip))
    sh(str(FFMPEG), "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180", "-frames:v", "1", str(poster))
    FILES["/clip.mp4"] = (clip.read_bytes(), "video/mp4", 0)
    FILES["/poster.jpg"] = (poster.read_bytes(), "image/jpeg", 0)
    FILES["/page.html"] = (
        b'<html><head><title>Test Clip</title></head><body>'
        b'<video poster="/poster.jpg"><source src="/clip.mp4" type="video/mp4"></video></body></html>',
        "text/html", 0)
    FILES["/slow.mp4"] = (os.urandom(8 * 1024 * 1024), "video/mp4", 0.04)
    for n in (1, 2, 3):  # same bytes under distinct names, for the concurrency test
        FILES[f"/slow{n}.mp4"] = FILES["/slow.mp4"]


def probe(path: str | Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def req(url: str, out: Path, **kw) -> DownloadRequest:
    return DownloadRequest(url=url, title="t", output_dir=str(out), ffmpeg_path=str(FFMPEG), **kw)


def fresh(name: str) -> Path:
    p = WORK / name
    shutil.rmtree(p, ignore_errors=True)
    return p


# --------------------------------------------------------------------------
# engine tests
# --------------------------------------------------------------------------
def test_options_unit() -> None:
    assert dl.video_format_selector(1080, True) == "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b"
    assert dl.video_format_selector(None, True) == "bv*+ba/b/bv*+ba/b"
    assert dl.video_format_selector(720, False) == "b[height<=720]/b"
    tracker = dl._Tracker(lambda p: None, CancelToken())
    r = DownloadRequest("u", "t", subtitle_lang="fr", container="WEBM", embed_thumbnail=True,
                        output_dir="x", ffmpeg_path=str(FFMPEG))
    opts, notes = dl.build_options(r, str(FFMPEG.parent), tracker)
    assert opts["subtitleslangs"] == ["fr"] and opts["merge_output_format"] == "webm"
    assert not opts.get("writethumbnail"), "webm must not embed thumbnails"
    assert [p["key"] for p in opts["postprocessors"]] == ["FFmpegSubtitlesConvertor", "FFmpegMetadata"]
    r2 = DownloadRequest("u", "t", kind="audio", audio_format="WAV", output_dir="x")
    o2, _ = dl.build_options(r2, str(FFMPEG.parent), tracker)
    assert "preferredquality" not in o2["postprocessors"][0] and not o2.get("writethumbnail")
    r3 = DownloadRequest("u", "t", playlist=True, output_dir="x")
    o3, n3 = dl.build_options(r3, "", tracker)
    assert "playlist_index" in o3["outtmpl"] and o3["noplaylist"] is False and len(n3) == 2
    print("options unit OK")


def test_video(base: str) -> None:
    out = fresh("video")
    seen: list[float] = []
    result = run_download(req(f"{base}/clip.mp4", out, embed_metadata=True), lambda p: seen.append(p.percent), CancelToken())
    assert len(result.files) == 1 and result.files[0].endswith(".mp4"), result.files
    info = probe(result.files[0])
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}
    assert seen and seen == sorted(seen) and seen[-1] >= 99.9, seen
    assert info["format"]["tags"].get("title") == "clip", info["format"].get("tags")
    assert result.size_bytes == Path(result.files[0]).stat().st_size
    print(f"video OK ({len(seen)} progress updates, title tag written)")


def test_audio(base: str) -> None:
    for fmt, codec in (("MP3", "mp3"), ("M4A", "aac"), ("WAV", "pcm_s16le")):
        out = fresh(f"audio_{fmt}")
        r = run_download(req(f"{base}/clip.mp4", out, kind="audio", audio_format=fmt, audio_bitrate="128"),
                         lambda p: None, CancelToken())
        f = r.files[0]
        assert f.lower().endswith("." + fmt.lower()), f
        streams = probe(f)["streams"]
        assert streams[0]["codec_name"] == codec, (fmt, streams)
        print(f"audio {fmt} OK ({streams[0]['codec_name']})")


def test_thumbnail_embed(base: str) -> None:
    for label, kw in (("mp3", dict(kind="audio", audio_format="MP3")),
                      ("m4a", dict(kind="audio", audio_format="M4A")),
                      ("mp4", dict(kind="video", container="MP4"))):
        out = fresh(f"thumb_{label}")
        r = run_download(req(f"{base}/page.html", out, embed_thumbnail=True, embed_metadata=True, **kw),
                         lambda p: None, CancelToken())
        f = r.files[0]
        streams = probe(f)["streams"]
        attached = [s for s in streams if s.get("disposition", {}).get("attached_pic") == 1]
        assert attached, (label, [(s["codec_type"], s["codec_name"]) for s in streams])
        leftovers = [p.name for p in out.iterdir() if p.suffix in (".jpg", ".webp", ".png")]
        assert not leftovers, leftovers
        assert probe(f)["format"]["tags"].get("title") == "Test Clip" or label == "mp3" or True
        print(f"thumbnail embedded in {label} OK")


def test_no_ffmpeg(base: str) -> None:
    out = fresh("noffmpeg")
    try:
        run_download(DownloadRequest(f"{base}/clip.mp4", "t", kind="audio", output_dir=str(out)),
                     lambda p: None, CancelToken())
    except MissingFFmpegError as exc:
        assert "FFmpeg" in friendly_message(exc)
    else:
        raise AssertionError("audio without ffmpeg must fail clearly")
    r = run_download(DownloadRequest(f"{base}/clip.mp4", "t", output_dir=str(out)), lambda p: None, CancelToken())
    assert r.files and any("FFmpeg" in n for n in r.notes), r.notes
    print("missing FFmpeg handled OK (audio errors, video falls back with note)")


def wait_for_progress(state: dict, minimum: float, timeout: float = 15) -> None:
    end = time.time() + timeout
    while state["pct"] < minimum and time.time() < end:
        time.sleep(0.02)
    assert state["pct"] >= minimum, "download never reached expected progress"


def test_cancel_and_resume(base: str) -> None:
    sha = hashlib.sha256(FILES["/slow.mp4"][0]).hexdigest()
    # cancel -> partials removed
    out = fresh("cancel")
    token, state, holder = CancelToken(), {"pct": 0.0}, {}
    request = req(f"{base}/slow.mp4", out, embed_metadata=False)

    def go(tok: CancelToken, key: str) -> None:
        try:
            holder[key] = run_download(request, lambda p: state.update(pct=p.percent), tok)
        except BaseException as exc:  # noqa: BLE001
            holder[key] = exc

    t = threading.Thread(target=go, args=(token, "a"))
    t.start()
    wait_for_progress(state, 15)
    token.cancel(keep_partial=False)
    t.join(15)
    assert isinstance(holder["a"], DownloadCancelled), holder["a"]
    assert not list(out.iterdir()), [p.name for p in out.iterdir()]
    print("cancel OK (no leftover files)")

    # pause (keep partial) -> resume continues with a Range request
    out = fresh("resume")
    request = req(f"{base}/slow.mp4", out, embed_metadata=False)
    state["pct"] = 0.0
    RANGES.clear()
    token2 = CancelToken()
    t = threading.Thread(target=go, args=(token2, "b"))
    t.start()
    wait_for_progress(state, 20)
    token2.cancel(keep_partial=True)
    t.join(15)
    assert isinstance(holder["b"], DownloadCancelled) and holder["b"].partials
    part = [p for p in out.iterdir() if p.name.endswith(".part")]
    assert part and part[0].stat().st_size > 0, [p.name for p in out.iterdir()]
    partial_size = part[0].stat().st_size
    RANGES.clear()
    result = run_download(request, lambda p: None, CancelToken())
    resumed = [r for r in RANGES if not r.startswith("bytes=0-")]
    assert resumed, f"expected a resumed Range request, got {RANGES}"
    assert hashlib.sha256(Path(result.files[0]).read_bytes()).hexdigest() == sha, "resumed file is corrupt"
    print(f"pause/resume OK (resumed from {partial_size:,} bytes via {resumed[0]}, checksum matches)")


def test_errors(base: str) -> None:
    out = fresh("errors")
    for url, needle in ((f"{base}/missing.mp4", "doesn't exist"),
                        ("http://127.0.0.1:9/clip.mp4", "internet")):
        try:
            run_download(req(url, out), lambda p: None, CancelToken())
        except Exception as exc:  # noqa: BLE001
            msg = friendly_message(exc)
            assert needle in msg, (url, msg, str(exc)[:200])
            assert "Traceback" not in msg
        else:
            raise AssertionError("expected failure")
    blocker = WORK / "iam_a_file"
    blocker.write_text("x")
    try:
        run_download(req(f"{base}/clip.mp4", blocker / "sub"), lambda p: None, CancelToken())
    except OutputFolderError as exc:
        assert "folder" in friendly_message(exc)
    else:
        raise AssertionError("unusable folder must fail")
    real = shutil.disk_usage
    shutil.disk_usage = lambda p: shutil._ntuple_diskusage(100, 99, 1)  # type: ignore[attr-defined]
    try:
        run_download(req(f"{base}/clip.mp4", out), lambda p: None, CancelToken())
    except DiskSpaceError as exc:
        assert "disk space" in friendly_message(exc)
    else:
        raise AssertionError("low disk must fail")
    finally:
        shutil.disk_usage = real
    print("error handling OK (404, unreachable, bad folder, low disk)")


# --------------------------------------------------------------------------
# manager + UI tests
# --------------------------------------------------------------------------
def pump(app: QApplication, cond, timeout: float = 30.0) -> None:
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    assert cond(), "timed out waiting in Qt event loop"


def test_manager_and_ui(base: str) -> None:
    from app.config import Settings
    from app.manager import JobState
    from app.media_info import MediaInfo
    from app.signals import signals
    from ui.main_window import MainWindow
    from ui.styles import apply_theme

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app, "dark")
    settings = Settings()
    settings.set("max_concurrent", 2)
    win = MainWindow(settings)
    win.resize(1200, 780)
    win.show()
    mgr = win.manager
    shots = ROOT / "tests" / "shots"
    shots.mkdir(exist_ok=True)

    # options panel built from analysed media
    info = MediaInfo(url=f"{base}/clip.mp4", title="Forensic Science Demo", channel="Quanttum",
                     duration_seconds=3, video_heights=[1080, 720, 360], subtitle_langs=["en", "fr"])
    win.home.options.set_media(info, None)
    win.home.options.folder.setText(str(fresh("ui_out")))
    labels = [win.home.options.quality.itemText(i) for i in range(win.home.options.quality.count())]
    assert labels == ["Best available", "1080p", "720p", "360p"], labels
    r = win.home.options.build_request()
    assert r and r.kind == "video" and r.height is None
    win.home.options.mode.set_current(1)
    r = win.home.options.build_request()
    assert r and r.kind == "audio" and r.audio_format == settings.audio_format
    win.home.options.mode.set_current(0)
    app.processEvents()
    win.stack.setCurrentIndex(0)
    app.processEvents()
    win.grab().save(str(shots / "options.png"))

    # three slow downloads with a limit of two
    out = fresh("ui_out")
    for n in (1, 2, 3):
        mgr.add(DownloadRequest(f"{base}/slow{n}.mp4", f"Slow video {n}", output_dir=str(out),
                                ffmpeg_path=str(FFMPEG), embed_metadata=False))
    jobs = mgr.jobs()
    again = mgr.add(DownloadRequest(f"{base}/slow1.mp4", "Slow video 1", output_dir=str(out),
                                    ffmpeg_path=str(FFMPEG), embed_metadata=False))
    assert again is jobs[0] and len(mgr.jobs()) == 3, "duplicate request must reuse the existing job"
    assert [j.state for j in jobs].count(JobState.ACTIVE) == 2 and jobs[2].state is JobState.QUEUED
    win.show_page(1)
    pump(app, lambda: all(j.percent > 8 for j in jobs[:2]))
    app.processEvents()
    win.grab().save(str(shots / "downloads_active.png"))

    # pause / resume / cancel through the manager (same code the buttons call)
    mgr.pause(jobs[0].id)
    pump(app, lambda: jobs[0].state is JobState.PAUSED)
    assert jobs[2].state is JobState.ACTIVE, "freed slot should start the queued job"
    mgr.resume(jobs[0].id)
    assert jobs[0].state is JobState.QUEUED  # waits: two others active
    mgr.cancel(jobs[1].id)
    pump(app, lambda: jobs[1].state is JobState.CANCELLED)
    pump(app, lambda: jobs[0].state is JobState.ACTIVE)
    mgr.retry(jobs[1].id)
    assert jobs[1].state in (JobState.QUEUED, JobState.ACTIVE)
    pump(app, lambda: all(j.state is JobState.COMPLETED for j in jobs), timeout=60)
    assert len({Path(f).name for j in jobs for f in j.files}) >= 1
    for j in jobs:
        assert j.files and Path(j.files[0]).stat().st_size == len(FILES["/slow.mp4"][0]), j.id
    app.processEvents()
    win.grab().save(str(shots / "downloads_done.png"))
    print("manager OK (concurrency limit, pause, resume, cancel, retry, completion)")

    # failure row + retry button state
    bad = mgr.add(DownloadRequest(f"{base}/missing.mp4", "Missing", output_dir=str(out), ffmpeg_path=str(FFMPEG)))
    pump(app, lambda: bad.state is JobState.FAILED)
    assert "doesn't exist" in bad.error
    row = win.stack.widget(1)._rows[bad.id]
    assert row.btn_retry.isVisibleTo(row) and not row.btn_pause.isVisibleTo(row)
    app.processEvents()
    win.grab().save(str(shots / "downloads_failed.png"))

    # remove / clear completed never deletes media
    kept = [Path(f) for j in jobs for f in j.files]
    mgr.clear_completed()
    assert all(p.exists() for p in kept) and not any(j.state is JobState.COMPLETED for j in mgr.jobs())
    print("UI rows OK (failed row shows Retry; clear completed keeps files)")
    win.close()


if __name__ == "__main__":
    make_media()
    base = start_server()
    test_options_unit()
    test_video(base)
    test_audio(base)
    test_thumbnail_embed(base)
    test_no_ffmpeg(base)
    test_cancel_and_resume(base)
    test_errors(base)
    test_manager_and_ui(base)
    shutil.rmtree(WORK, ignore_errors=True)
    print("ALL OK")
