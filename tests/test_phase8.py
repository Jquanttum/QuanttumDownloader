"""Phase 8 checks: any-site support helpers, site names, sign-in cookies, several links at once.

    python tests/test_phase8.py        (reuses the local test server from test_phase3.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_phase3 as t3  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import Settings  # noqa: E402
from app.cookies import check_cookies_file, cookie_settings, cookie_ydl_options  # noqa: E402
from app.downloader import CancelToken, DownloadRequest, run_download  # noqa: E402
from app.errors import friendly_message  # noqa: E402
from app.history import HistoryDB  # noqa: E402
from app.manager import JobState  # noqa: E402
from app.media_info import MediaInfo, all_urls, analyse_url, site_name  # noqa: E402
from ui.batch_dialog import PRESETS, BatchChoice, BatchDialog  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.styles import apply_theme  # noqa: E402

BASE = ""


def netscape(path: Path, value: str = "abc") -> Path:
    path.write_text("# Netscape HTTP Cookie File\n"
                    f"127.0.0.1\tFALSE\t/\tFALSE\t4102444800\tsession\t{value}\n", encoding="utf-8")
    return path


def test_helpers() -> None:
    text = "see https://a.com/x?v=1, and\nhttps://b.org/y.\n  https://a.com/x?v=1 twice; youtu.be/zzz"
    assert all_urls(text) == ["https://a.com/x?v=1", "https://b.org/y"], all_urls(text)
    assert all_urls("youtu.be/abc\nvimeo.com/123") == ["https://youtu.be/abc", "https://vimeo.com/123"]
    assert all_urls("nothing here") == [] and len(all_urls("\n".join(f"https://x.com/{i}" for i in range(500)))) == 200
    assert site_name("Youtube", "u") == "YouTube" and site_name("YoutubeTab", "u") == "YouTube"
    assert site_name("Vimeo", "u") == "Vimeo" and site_name("TikTok", "u") == "TikTok"
    assert site_name("Generic", "https://www.example.com/a.mp4") == "example.com"
    assert site_name("SomeNewSite", "u") == "Some New Site" and site_name("", "https://x.org/y") == "x.org"
    print("link and site-name helpers OK")

    assert cookie_settings("Off", "Chrome", "f.txt") == ("", "")
    assert cookie_settings("From browser", "Firefox", "") == ("firefox", "")
    assert cookie_settings("From browser", "Netscape", "") == ("", ""), "unknown browser is ignored"
    assert cookie_settings("From cookies.txt", "Chrome", "c.txt") == ("", "c.txt")
    assert cookie_ydl_options("edge") == {"cookiesfrombrowser": ("edge",)}
    assert cookie_ydl_options("", "c.txt") == {"cookiefile": "c.txt"} and cookie_ydl_options() == {}
    good = netscape(t3.WORK / "ok.txt")
    assert check_cookies_file(str(good)) == ""
    (t3.WORK / "bad.txt").write_text("hello world")
    assert "Netscape" in check_cookies_file(str(t3.WORK / "bad.txt"))
    assert "doesn't exist" in check_cookies_file(str(t3.WORK / "none.txt")) and check_cookies_file("")
    print("cookie helpers OK")

    cases = {
        "ERROR: [Instagram] login required": "sign in", "Sign in to confirm your age": "age-restricted",
        "ERROR: Unsupported URL: http://x": "isn't supported", "This video is DRM protected": "DRM",
        "Could not copy Chrome cookie database": "cookies", "ERROR: This video is private": "private",
        "HTTP Error 403: Forbidden": "Sign-in cookies", "This live event will begin in 2 hours": "live",
        "ERROR: No video formats found": "No downloadable", "Requested format is not available": "isn't available",
        "Failed to decrypt with DPAPI": "cookies", "[Site] Video unavailable": "unavailable",
    }
    for raw, needle in cases.items():
        assert needle.lower() in friendly_message(Exception(raw)).lower(), (raw, friendly_message(Exception(raw)))
    assert friendly_message(Exception("something odd")).startswith("Something went wrong")
    print("per-site error messages OK")


def test_cookies_engine() -> None:
    t3.PROTECTED.add("/private.mp4")
    t3.FILES["/private.mp4"] = t3.FILES["/clip.mp4"]
    url = f"{BASE}/private.mp4"
    cookie = netscape(t3.WORK / "session.txt")

    # analysis
    try:
        analyse_url(url)
        raise AssertionError("analysis without cookies must fail")
    except AssertionError:
        raise
    except Exception as exc:  # noqa: BLE001
        assert "cookies" in friendly_message(exc).lower(), friendly_message(exc)
    info = analyse_url(url, cookies_file=str(cookie))
    assert info.site == "127.0.0.1" and info.title
    # wrong cookie value is still refused
    wrong = netscape(t3.WORK / "wrong.txt", "nope")
    try:
        analyse_url(url, cookies_file=str(wrong))
        raise AssertionError("wrong cookie must fail")
    except AssertionError:
        raise
    except Exception:  # noqa: BLE001
        pass
    print("analysis with sign-in cookies OK (refused without, allowed with)")

    # download
    out = t3.fresh("cookie_dl")
    req = DownloadRequest(url, "Private", output_dir=str(out), ffmpeg_path=str(t3.FFMPEG), embed_metadata=False)
    try:
        run_download(req, lambda p: None, CancelToken())
        raise AssertionError("download without cookies must fail")
    except AssertionError:
        raise
    except Exception as exc:  # noqa: BLE001
        assert "cookies" in friendly_message(exc).lower()
    req.cookies_file = str(cookie)
    result = run_download(req, lambda p: None, CancelToken())
    assert result.files and Path(result.files[0]).stat().st_size > 1000
    print("download with sign-in cookies OK")


def main() -> None:
    global BASE
    t3.make_media()
    BASE = t3.start_server()
    test_helpers()
    test_cookies_engine()

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app, "dark")
    settings = Settings()
    settings.set("cookies_mode", "Off")
    db = HistoryDB(t3.WORK / "p8.db")
    win = MainWindow(settings, db)
    win.resize(1200, 780)
    win.show()
    mgr, home = win.manager, win.home

    # --- site chip -----------------------------------------------------------------------
    info = MediaInfo(url="https://vimeo.com/1", title="T", site="Vimeo", video_heights=[720])
    home.preview.show_media(info, None)
    chips = [home.preview.chips.itemAt(i).widget().text() for i in range(home.preview.chips.count())
             if home.preview.chips.itemAt(i).widget()]
    assert "Vimeo" in chips, chips
    print("site chip on the preview OK")

    # --- requests carry the sign-in choice and site -----------------------------------------
    home.options.set_media(info, None)
    req = home.options.build_request()
    assert req.site == "Vimeo" and (req.cookies_browser, req.cookies_file) == ("", "")
    settings.set("cookies_mode", "From browser")
    settings.set("cookies_browser", "Firefox")
    assert home.options.build_request().cookies_browser == "firefox"
    cookie = netscape(t3.WORK / "ui.txt")
    settings.set("cookies_mode", "From cookies.txt")
    settings.set("cookies_file", str(cookie))
    assert home.options.build_request().cookies_file == str(cookie)
    print("requests carry sign-in cookies and site OK")

    # --- settings page ---------------------------------------------------------------------
    win.show_page(4)
    sp = win.stack.widget(4)
    sp.cookie_mode.setCurrentText("From browser")
    sp.cookie_mode.setCurrentText("Off")
    assert settings.get("cookies_mode") == "Off" and not sp.cookie_browser.isVisibleTo(sp)
    sp.cookie_mode.setCurrentText("From browser")
    assert sp.cookie_browser.isVisibleTo(sp) and not sp.cookie_file.isVisibleTo(sp)
    sp.cookie_mode.setCurrentText("From cookies.txt")
    sp.cookie_file.setText(str(t3.WORK / "bad.txt"))
    sp.cookie_file.editingFinished.emit()
    assert "Netscape" in sp.cookie_status.text() and sp.cookie_status.property("state") == "bad"
    sp.cookie_file.setText(str(cookie))
    sp.cookie_file.editingFinished.emit()
    assert "looks good" in sp.cookie_status.text() and settings.get("cookies_file") == str(cookie)
    print("settings: sign-in cookies section OK")
    settings.set("cookies_mode", "Off")
    sp.cookie_mode.setCurrentText("Off")

    # --- dialog ---------------------------------------------------------------------------------
    dlg = BatchDialog(settings, win, "junk https://a.com/1 https://b.com/2\nhttps://a.com/1")
    assert "2 links" in dlg.count.text() and dlg.add_btn.isEnabled()
    dlg.preset.setCurrentText("Video · up to 720p")
    dlg.folder.setText(str(t3.fresh("dlg")))
    dlg.add_btn.click()
    c = dlg.choice
    assert c and c.urls == ["https://a.com/1", "https://b.com/2"] and (c.kind, c.height) == ("video", 720)
    empty = BatchDialog(settings, win, "no links")
    assert not empty.add_btn.isEnabled() and "No links" in empty.count.text()
    audio = BatchDialog(settings, win, "https://a.com/1")
    audio.preset.setCurrentText("Audio · M4A")
    audio.folder.setText(str(t3.fresh("dlg2")))
    audio.add_btn.click()
    assert audio.choice.kind == "audio" and audio.choice.audio_format == "M4A"
    assert set(PRESETS) >= {"Video · best quality", "Audio · MP3"}
    print("batch dialog OK")

    # --- several links in the URL box open the dialog instead of failing ---------------------------
    opened = []
    home.open_batch = lambda text="": opened.append(text)
    home.url_input.setText("https://a.com/1 https://b.com/2")
    home._on_analyse()
    assert opened and "b.com" in opened[0]
    del home.open_batch
    print("multiple links in the box -> batch dialog OK")

    # --- run a batch: good, duplicate, missing, protected ---------------------------------------------
    import ui.home_page as hp
    errors = []
    hp.show_error = lambda parent, title, text, details=None: errors.append(text)
    out = t3.fresh("batch_out")
    urls = [f"{BASE}/clip.mp4", f"{BASE}/clip.mp4?x=2", f"{BASE}/missing.mp4", f"{BASE}/private.mp4"]
    home.start_batch(BatchChoice(urls, "audio", None, "MP3", str(out)))
    t3.pump(app, lambda: home.batch_btn.isEnabled() and home.batch_summary[0] + len(home.batch_summary[1]) == 4
            or (home.batch_btn.isEnabled() and home.batch_summary[0] > 0))
    added, failed = home.batch_summary
    assert added == 2 and len(failed) == 2, (added, failed)
    assert any("exist" in m for _u, m in failed) and any("cookies" in m.lower() for _u, m in failed), failed
    assert errors and "missing.mp4" in errors[0] and "private.mp4" in errors[0]
    assert home.batch_note.isVisibleTo(home) and "Added 2" in home.batch_note.text()
    jobs = [j for j in mgr.jobs() if j.request.kind == "audio" and j.request.output_dir == str(out)]
    assert len(jobs) == 2 and all(j.request.site == "127.0.0.1" for j in jobs)
    t3.pump(app, lambda: all(j.state is JobState.COMPLETED for j in jobs))
    mp3s = sorted(p.name for p in out.iterdir() if p.suffix == ".mp3")
    assert len(mp3s) == 2, f"same title from two links must not overwrite or collide: {mp3s}"
    assert any(j.request.unique_name for j in jobs) and not all(j.request.unique_name for j in jobs)
    print("batch of links OK (added, failures reported in plain language, downloads complete)")

    # --- history shows the site ---------------------------------------------------------------------------
    win.show_page(3)
    t3.pump(app, lambda: win._anim is None, 5)
    page = win.stack.widget(3)
    page.refresh()
    assert any("127.0.0.1" in r.meta._full for r in page._rows), [r.meta._full for r in page._rows]
    print("history shows the source site OK")

    win.close()


if __name__ == "__main__":
    main()
    import shutil
    shutil.rmtree(t3.WORK, ignore_errors=True)
    print("ALL OK")
