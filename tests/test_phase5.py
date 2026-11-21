"""Phase 5 checks: audio extraction (formats, bitrates, tags), subtitles, FFmpeg edge cases.

    python tests/test_phase5.py        (reuses the local test server from test_phase3.py)

Subtitles need an extractor that reports them, so the test registers a tiny yt-dlp extractor
for ``/sub.mp4`` that points at real files served by the local test server.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_phase3 as t3  # noqa: E402

import yt_dlp  # noqa: E402
from yt_dlp.extractor.common import InfoExtractor  # noqa: E402

from app.downloader import CancelToken, DownloadRequest, run_download  # noqa: E402

VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHello subtitles\n\n00:00:01.500 --> 00:00:03.000\nSecond line\n"
VTT_FR = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nBonjour auto\n"
BASE = ""


class _SubIE(InfoExtractor):
    IE_NAME = "qdsub"
    _VALID_URL = r"https?://127\.0\.0\.1:\d+/sub\.mp4"

    def _real_extract(self, url):
        return {
            "id": "sub1", "title": "Subtitle Clip", "url": f"{BASE}/clip.mp4", "ext": "mp4",
            "subtitles": {"en": [{"url": f"{BASE}/sub_en.vtt", "ext": "vtt"}]},
            "automatic_captions": {"fr": [{"url": f"{BASE}/sub_fr.vtt", "ext": "vtt"}]},
        }


_orig_extract = yt_dlp.YoutubeDL.extract_info


def _patched_extract(self, url, *a, **kw):
    if url.endswith("/sub.mp4"):
        self.add_info_extractor(_SubIE(self))
        kw["ie_key"] = _SubIE.ie_key()
    return _orig_extract(self, url, *a, **kw)


def run(url: str, out: Path, **kw):
    return run_download(t3.req(url, out, **kw), lambda p: None, CancelToken())


def test_audio_bitrates() -> None:
    sizes = {}
    for br in ("128", "320"):
        out = t3.fresh(f"br{br}")
        r = run(f"{BASE}/clip.mp4", out, kind="audio", audio_format="MP3", audio_bitrate=br, embed_metadata=False)
        kbps = int(t3.probe(r.files[0])["format"]["bit_rate"]) / 1000
        sizes[br] = kbps
        assert abs(kbps - int(br)) < 25, (br, kbps)
    assert sizes["320"] > sizes["128"] * 2
    print(f"audio bitrate OK (128 -> {sizes['128']:.0f} kbps, 320 -> {sizes['320']:.0f} kbps)")


def test_audio_tags() -> None:
    for fmt in ("MP3", "M4A"):
        out = t3.fresh(f"tags_{fmt}")
        r = run(f"{BASE}/page.html", out, kind="audio", audio_format=fmt, embed_metadata=True, embed_thumbnail=True)
        tags = {k.lower(): v for k, v in t3.probe(r.files[0])["format"].get("tags", {}).items()}
        assert tags.get("title", "").startswith("Test Clip"), (fmt, tags)
        assert len(r.files) == 1 and not r.notes, (r.files, r.notes)
    print("audio tags OK (title written, thumbnail embedded, single output file)")


def test_audio_only_no_video_stream() -> None:
    out = t3.fresh("novideo")
    r = run(f"{BASE}/clip.mp4", out, kind="audio", audio_format="M4A", embed_metadata=False, embed_thumbnail=False)
    kinds = {s["codec_type"] for s in t3.probe(r.files[0])["streams"]}
    assert kinds == {"audio"}, kinds
    assert [p.name for p in out.iterdir()] == [Path(r.files[0]).name], "intermediate source file must be removed"
    print("audio extraction OK (audio-only output, source file removed)")


def test_subtitles() -> None:
    # manual subtitles
    out = t3.fresh("subs_en")
    r = run(f"{BASE}/sub.mp4", out, subtitle_lang="en", embed_metadata=False)
    srt = out / "Subtitle Clip [sub1].en.srt"
    names = sorted(p.name for p in out.iterdir())
    srts = [p for p in out.iterdir() if p.suffix == ".srt"]
    assert len(srts) == 1 and "Hello subtitles" in srts[0].read_text(encoding="utf-8"), names
    assert not [p for p in out.iterdir() if p.suffix == ".vtt"], f"vtt must be converted away: {names}"
    assert any(f.endswith(".mp4") for f in r.files)
    assert any(f.endswith(".srt") for f in r.files), f"subtitle file must be reported: {r.files}"
    print("manual subtitles OK ->", srts[0].name)

    # automatic captions fallback
    out = t3.fresh("subs_fr")
    run(f"{BASE}/sub.mp4", out, subtitle_lang="fr", embed_metadata=False)
    srts = [p for p in out.iterdir() if p.suffix == ".srt"]
    assert len(srts) == 1 and "Bonjour auto" in srts[0].read_text(encoding="utf-8")
    print("automatic captions OK ->", srts[0].name)

    # language that does not exist: download still succeeds
    out = t3.fresh("subs_de")
    r = run(f"{BASE}/sub.mp4", out, subtitle_lang="de", embed_metadata=False)
    assert any(f.endswith(".mp4") for f in r.files) and not [p for p in out.iterdir() if p.suffix == ".srt"]
    assert any("subtitle" in n.lower() for n in r.notes), r.notes
    print("missing subtitle language OK (video kept, note added)")

    # audio + subtitles
    out = t3.fresh("subs_audio")
    r = run(f"{BASE}/sub.mp4", out, kind="audio", audio_format="MP3", subtitle_lang="en", embed_metadata=False)
    assert [p for p in out.iterdir() if p.suffix == ".srt"] and [p for p in out.iterdir() if p.suffix == ".mp3"]
    print("audio + subtitles OK")

    # without ffmpeg the .vtt is kept and the download still works
    out = t3.fresh("subs_noff")
    r = run_download(DownloadRequest(f"{BASE}/sub.mp4", "t", output_dir=str(out), subtitle_lang="en"),
                     lambda p: None, CancelToken())
    assert [p for p in out.iterdir() if p.suffix in (".vtt", ".srt")], list(out.iterdir())
    print("subtitles without FFmpeg OK")


def test_manager_deletes_subtitles() -> None:
    from PySide6.QtWidgets import QApplication
    from app.config import Settings
    from app.manager import DownloadManager, JobState

    app = QApplication.instance() or QApplication(sys.argv)
    mgr = DownloadManager(Settings())
    out = t3.fresh("subs_mgr")
    job = mgr.add(t3.req(f"{BASE}/sub.mp4", out, subtitle_lang="en", embed_metadata=False), start_now=True)
    t3.pump(app, lambda: job.state is JobState.COMPLETED)
    assert any(f.endswith(".srt") for f in job.files), job.files
    deleted, failed = mgr.delete_files(job.id)
    assert failed == 0 and deleted == len(job.files) and not list(out.iterdir()), list(out.iterdir())
    mgr.shutdown()
    print("delete from disk also removes subtitle files OK")


def main() -> None:
    global BASE
    t3.make_media()
    t3.FILES["/sub_en.vtt"] = (VTT.encode(), "text/vtt", 0)
    t3.FILES["/sub_fr.vtt"] = (VTT_FR.encode(), "text/vtt", 0)
    BASE = t3.start_server()
    yt_dlp.YoutubeDL.extract_info = _patched_extract
    test_audio_bitrates()
    test_audio_tags()
    test_audio_only_no_video_stream()
    test_subtitles()
    test_manager_deletes_subtitles()


if __name__ == "__main__":
    main()
    import shutil
    shutil.rmtree(t3.WORK, ignore_errors=True)
    print("ALL OK")
