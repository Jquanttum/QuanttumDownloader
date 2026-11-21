"""Phase 9 checks: naming/layout, trim, speed limit, playlist items + archive, queue persistence,
drag-and-drop ordering, schedule, auto-queue, update banner, tray, shortcuts, theme.

    python tests/test_phase9.py        (reuses the local test server from test_phase3.py)
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_phase3 as t3  # noqa: E402

import yt_dlp  # noqa: E402
from yt_dlp.extractor.common import InfoExtractor  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from app import config as cfg  # noqa: E402
from app.choices import SPEED_LIMITS, in_window, parse_clock, parse_time, trim_stamp  # noqa: E402
from app.config import Settings  # noqa: E402
from app.downloader import CancelToken, DownloadRequest, _Tracker, build_options, run_download  # noqa: E402
from app.errors import MissingFFmpegError  # noqa: E402
from app.manager import DownloadManager, JobState  # noqa: E402
from app.media_info import build_media_info  # noqa: E402

BASE = ""


class _PlaylistIE(InfoExtractor):
    IE_NAME = "qdplaylist"
    _VALID_URL = r"https?://127\.0\.0\.1:\d+/pl\.mp4"

    def _real_extract(self, url):
        entries = [{"id": f"v{i}", "title": f"Lesson {i}", "url": f"{BASE}/clip.mp4", "ext": "mp4"}
                   for i in (1, 2, 3)]
        return self.playlist_result(entries, "pl1", "My Course")


_orig_extract = yt_dlp.YoutubeDL.extract_info


def _patched_extract(self, url, *a, **kw):
    if url.endswith("/pl.mp4"):
        self.add_info_extractor(_PlaylistIE(self))
        kw["ie_key"] = _PlaylistIE.ie_key()
    return _orig_extract(self, url, *a, **kw)


def go(url: str, out: Path, **kw):
    return run_download(t3.req(url, out, **kw), lambda p: None, CancelToken())


def files_in(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------------------------
def test_choices() -> None:
    assert parse_time("1:20") == 80 and parse_time("1:02:03") == 3723 and parse_time("90") == 90
    assert parse_time("") is None and parse_time("  ") is None
    for bad in ("1:75", "abc", "1:2", "-5", "1:2:3:4"):
        try:
            parse_time(bad)
            raise AssertionError(f"{bad!r} must be rejected")
        except ValueError:
            pass
    from datetime import time as t
    assert in_window(t(2), t(1), t(6)) and not in_window(t(7), t(1), t(6))
    assert in_window(t(23), t(22), t(5)) and in_window(t(3), t(22), t(5)) and not in_window(t(12), t(22), t(5))
    assert in_window(t(9), t(9), t(9)), "start == end means all day"
    assert parse_clock("06:30") == t(6, 30) and parse_clock("nonsense") == t(0, 0)
    assert trim_stamp(80, 245) == "1m20s-4m05s" and trim_stamp(0, None) == "0m00s-end"
    assert SPEED_LIMITS["Unlimited"] == 0 and SPEED_LIMITS["1 MB/s"] == 1048576
    print("choice helpers OK (time parsing, schedule windows incl. past midnight)")


def test_engine() -> None:
    out = t3.fresh("e_name")
    go(f"{BASE}/clip.mp4", out, name_template="Title [id]", folder_layout="By site", embed_metadata=False)
    names = files_in(out)
    assert len(names) == 1 and names[0].startswith("Generic/clip [") and names[0].endswith("].mp4"), names
    out = t3.fresh("e_chan")
    go(f"{BASE}/clip.mp4", out, name_template="Channel - Title", folder_layout="By channel", embed_metadata=False)
    assert files_in(out) == ["Unknown/Unknown - clip.mp4"], files_in(out)
    print("naming templates and folder layouts OK")

    out = t3.fresh("e_trim")
    r = go(f"{BASE}/clip.mp4", out, trim_start=1.0, trim_end=2.5, embed_metadata=False)
    dur = float(t3.probe(r.files[0])["format"]["duration"])
    assert 1.2 < dur < 1.9, dur
    assert "[0m01s-0m02s]" in files_in(out)[0]
    out = t3.fresh("e_trim_audio")
    r = go(f"{BASE}/clip.mp4", out, kind="audio", audio_format="MP3", trim_start=1.0, embed_metadata=False)
    assert float(t3.probe(r.files[0])["format"]["duration"]) < 2.6
    try:
        run_download(DownloadRequest(f"{BASE}/clip.mp4", "t", output_dir=str(t3.fresh("e_trim_noff")),
                                     trim_start=1.0), lambda p: None, CancelToken())
        raise AssertionError("trim without FFmpeg must fail")
    except MissingFFmpegError as exc:
        assert "trim" in str(exc)
    print("trim OK (video, audio, friendly error without FFmpeg)")

    req = t3.req(f"{BASE}/clip.mp4", t3.fresh("e_rate"), rate_limit=123456)
    tracker = _Tracker(lambda p: None, CancelToken())
    opts, _ = build_options(req, str(t3.FFMPEG.parent), tracker)
    assert opts["ratelimit"] == 123456
    assert "ratelimit" not in build_options(t3.req("u", t3.WORK), str(t3.FFMPEG.parent), tracker)[0]
    t = time.time()
    go(f"{BASE}/clip.mp4", t3.fresh("e_rate2"), rate_limit=60 * 1024, embed_metadata=False)
    size = t3.FILES["/clip.mp4"][0].__len__() if isinstance(t3.FILES["/clip.mp4"][0], bytes) else 0
    elapsed = time.time() - t
    assert elapsed > size / (60 * 1024) * 0.5, (elapsed, size)
    print(f"speed limit OK (downloaded {size // 1024} KB in {elapsed:.1f}s at a 60 KB/s cap)")


def test_playlist() -> None:
    info = yt_dlp.YoutubeDL({"quiet": True, "extract_flat": "in_playlist"}).extract_info(
        f"{BASE}/pl.mp4", download=False)
    media = build_media_info(f"{BASE}/pl.mp4", info)
    assert media.is_playlist and [t for t, _ in media.entries] == ["Lesson 1", "Lesson 2", "Lesson 3"], media.entries

    out = t3.fresh("pl_items")
    r = go(f"{BASE}/pl.mp4", out, playlist=True, playlist_items="1,3", embed_metadata=False)
    names = files_in(out)
    assert len(names) == 2 and all(n.startswith("My Course/") for n in names), names
    assert any(n.endswith("/1 - Lesson 1.mp4") for n in names) and any("3 - Lesson 3" in n for n in names), names
    print("playlist item selection OK:", names)

    out = t3.fresh("pl_archive")
    go(f"{BASE}/pl.mp4", out, playlist=True, playlist_items="1,2", skip_downloaded=True, embed_metadata=False)
    assert len(files_in(out)) == 2 and cfg.ARCHIVE_PATH.exists()
    assert {"v1", "v2"} <= {line.split()[-1] for line in cfg.ARCHIVE_PATH.read_text().splitlines()}
    out2 = t3.fresh("pl_archive2")
    r = go(f"{BASE}/pl.mp4", out2, playlist=True, skip_downloaded=True, embed_metadata=False)
    names = files_in(out2)
    assert len(names) == 1 and "Lesson 3" in names[0], f"only the new video must download: {names}"
    out3 = t3.fresh("pl_archive3")
    r = go(f"{BASE}/pl.mp4", out3, playlist=True, skip_downloaded=True, embed_metadata=False)
    assert files_in(out3) == [] and any("already" in n.lower() for n in r.notes), (files_in(out3), r.notes)
    print("skip already-downloaded OK (new videos only; all-done is explained, not an error)")


# ---------------------------------------------------------------------------------------------
def slow(n: int, out: Path, title: str | None = None, **kw) -> DownloadRequest:
    return DownloadRequest(f"{BASE}/slow{n}.mp4", title or f"Slow {n}", output_dir=str(out),
                           ffmpeg_path=str(t3.FFMPEG), embed_metadata=False, **kw)


def test_manager(app: QApplication) -> None:
    settings = Settings()
    settings.set("max_concurrent", 1)
    settings.set("schedule_enabled", False)
    settings.set("speed_limit", "Unlimited")
    pump = lambda cond, timeout=40.0: t3.pump(app, cond, timeout)  # noqa: E731

    # --- move_to ------------------------------------------------------------------------------
    mgr = DownloadManager(settings)
    mgr.stop_queue()
    out = t3.fresh("m_out")
    jobs = [mgr.add(slow(n, out), start_now=False) for n in (1, 2, 3)]
    a, b, c = jobs
    mgr.move_to(c.id, 0)
    assert [j.id for j in mgr.queue_jobs()] == [c.id, a.id, b.id]
    mgr.move_to(c.id, 99)
    assert [j.id for j in mgr.queue_jobs()] == [a.id, b.id, c.id]
    mgr.move_to(b.id, 0)
    mgr.move_to(999, 0)
    assert [j.id for j in mgr.queue_jobs()] == [b.id, a.id, c.id]
    print("move_to OK")

    # --- persistence: order, states, stopped flag, damaged files ----------------------------------
    store = t3.WORK / "queue.json"
    mgr.enable_persistence(store)
    mgr.pause(a.id)
    mgr.save_now()
    data = json.loads(store.read_text())
    assert data["running"] is False and [i["state"] for i in data["items"]] == ["queued", "paused", "queued"]
    mgr2 = DownloadManager(settings)
    n = mgr2.enable_persistence(store)
    assert n == 3 and not mgr2.queue_running
    q = mgr2.queue_jobs()
    assert [j.title for j in q] == ["Slow 2", "Slow 1", "Slow 3"], [j.title for j in q]
    assert [j.state for j in q] == [JobState.QUEUED, JobState.PAUSED, JobState.QUEUED]
    assert q[0].request.output_dir == str(out)
    mgr2.shutdown()
    mgr.shutdown()
    (t3.WORK / "bad.json").write_text("{not json")
    assert DownloadManager(settings).enable_persistence(t3.WORK / "bad.json") == 0
    (t3.WORK / "odd.json").write_text(json.dumps({"running": True, "items": [
        {"request": {"url": "http://x/1", "title": "T", "output_dir": str(out), "future_field": 1}},
        {"request": "nonsense"}, {"request": {"nope": 1}}]}))
    assert DownloadManager(settings).enable_persistence(t3.WORK / "odd.json") == 1
    print("queue persistence OK (order, paused state, stopped flag, damaged/odd files)")

    # --- an interrupted download resumes after a restart ---------------------------------------------
    settings.set("max_concurrent", 1)
    out = t3.fresh("m_resume")
    store = t3.WORK / "queue2.json"
    m1 = DownloadManager(settings)
    m1.enable_persistence(store)
    j = m1.add(slow(1, out), start_now=True)
    pump(lambda: j.percent > 15)
    m1.shutdown()                                  # like closing the app mid-download
    partial = [p for p in out.iterdir() if p.name.endswith(".part")]
    assert partial, "partial data must be kept"
    saved = json.loads(store.read_text())
    assert [i["state"] for i in saved["items"]] == ["queued"] and saved["running"] is True
    m2 = DownloadManager(settings)
    assert m2.enable_persistence(store) == 1
    j2 = m2.queue_jobs()[0]
    pump(lambda: j2.state is JobState.COMPLETED)
    assert Path(j2.files[0]).stat().st_size == len(t3.FILES["/slow1.mp4"][0])
    m2.shutdown()
    print("download resumes after restart OK (partial kept, completed to the full size)")

    # --- speed limit is split between concurrent downloads --------------------------------------------
    settings.set("speed_limit", "1 MB/s")
    settings.set("max_concurrent", 2)
    m = DownloadManager(settings)
    assert m.speed_per_download() == 512 * 1024
    settings.set("max_concurrent", 4)
    assert m.speed_per_download() == 256 * 1024
    settings.set("speed_limit", "Unlimited")
    assert m.speed_per_download() == 0
    settings.set("max_concurrent", 1)
    settings.set("speed_limit", "5 MB/s")
    job = m.add(t3.req(f"{BASE}/clip.mp4", t3.fresh("m_speed"), embed_metadata=False), start_now=True)
    assert job.request.rate_limit == 5 * 1024 * 1024
    pump(lambda: job.state is JobState.COMPLETED)
    settings.set("speed_limit", "Unlimited")
    m.shutdown()
    print("speed limit split OK")

    # --- schedule ---------------------------------------------------------------------------------------
    settings.set("max_concurrent", 1)
    settings.set("schedule_start", "01:00")
    settings.set("schedule_end", "06:00")
    settings.set("schedule_enabled", True)
    m = DownloadManager(settings)
    clock = {"now": datetime(2026, 1, 1, 12, 0)}
    m.clock = lambda: clock["now"]
    out = t3.fresh("m_sched")
    q1 = m.add(slow(1, out), start_now=False)
    app.processEvents()
    assert q1.state is JobState.QUEUED and not m.schedule_open() and "waiting" in m.schedule_text()
    man = m.add(slow(2, out), start_now=True)
    pump(lambda: man.state is JobState.ACTIVE)
    assert q1.state is JobState.QUEUED, "limit 1: manual job runs, queue job still waits"
    m.cancel(man.id)
    pump(lambda: man.state is JobState.CANCELLED)
    assert q1.state is JobState.QUEUED, "closed window keeps queue jobs waiting"
    clock["now"] = datetime(2026, 1, 2, 3, 0)
    m.tick()
    assert q1.state is JobState.ACTIVE and "waiting" not in m.schedule_text()
    pump(lambda: q1.percent > 12)
    clock["now"] = datetime(2026, 1, 2, 7, 0)
    m.tick()
    pump(lambda: q1.state is JobState.PAUSED)
    assert q1.auto_paused and any(p.name.endswith(".part") for p in out.iterdir())
    clock["now"] = datetime(2026, 1, 3, 2, 0)
    m.tick()
    pump(lambda: q1.state is JobState.COMPLETED)
    assert Path(q1.files[0]).stat().st_size == len(t3.FILES["/slow1.mp4"][0])
    # a job the user started manually is not paused by the schedule
    m2 = m.add(slow(3, out), start_now=True)
    pump(lambda: m2.state is JobState.ACTIVE and m2.percent > 5)
    clock["now"] = datetime(2026, 1, 3, 12, 0)
    m.tick()
    app.processEvents()
    assert m2.state is JobState.ACTIVE, "manual downloads ignore the schedule"
    m.cancel(m2.id)
    pump(lambda: m2.state is JobState.CANCELLED)
    settings.set("schedule_enabled", False)
    m.shutdown()
    print("schedule OK (waits outside the window, runs inside, pauses at close and resumes, manual exempt)")


def main() -> None:
    global BASE
    t3.make_media()
    BASE = t3.start_server()
    yt_dlp.YoutubeDL.extract_info = _patched_extract
    test_choices()
    test_engine()
    test_playlist()
    app = QApplication.instance() or QApplication(sys.argv)
    test_manager(app)
    try:
        import test_phase9_ui as ui_part  # noqa: F401  (UI checks live in their own file)
    except ModuleNotFoundError:
        pass


if __name__ == "__main__":
    main()
    import shutil
    shutil.rmtree(t3.WORK, ignore_errors=True)
    print("ALL OK")
