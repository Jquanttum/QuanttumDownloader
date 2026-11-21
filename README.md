# Quanttum Downloader

A modern, lightweight video/audio downloader (YouTube and 1000+ other sites supported by yt-dlp) for Windows built with Python, PySide6 and yt-dlp.

**Current status: Phase 8 — works with any site yt-dlp supports.** Home shows the source site; *Several links* adds many links to the queue at once (or paste several links into the box); Settings → *Sign-in cookies* lets you use your own browser login or a cookies.txt for private / members-only / age-restricted media; error messages are written per situation (login needed, DRM, live stream, unsupported link…); two different videos with the same title no longer collide. Test it with `python tests/test_phase8.py`. Earlier: **Phase 7 — complete.** Added: error handling for crashes in threads/Qt, a single-instance guard, bundled-FFmpeg lookup, a PyInstaller spec (`build_exe.bat`), a Windows guide (`INSTALL_WINDOWS.md`) and fixes for clipped placeholder text and wheel-scrolling over dropdowns. Run all tests with `python tests/run_all.py`. Earlier — **Phase 6** — SQLite history (search, sort, open, show in folder, download again, remove entry *without* deleting the file, optional delete-file), notifications, and a yt-dlp update check/updater in Settings. History is stored in `data/downloads.db`. Earlier: **Phase 5** — audio (MP3/M4A/WAV, 128–320 kbps, tags + cover art) and subtitles (manual or automatic captions → .srt, saved next to the video; deleting a download also deletes them). Earlier: **Phase 4** — a real queue (Queue page: start/stop, reorder, clear; *Add to queue* vs *Download now*) and, on Downloads, **Delete file** (moves the file to the Recycle Bin after confirmation; the ✕ button only removes the list entry and never touches files). Plus link analysis and real downloads: video (MP4/MKV/WEBM, quality cap) and audio (MP3/M4A/WAV), subtitles, metadata and thumbnail embedding, playlists, pause/resume (partial files are kept), cancel, retry and a live Downloads page.
The full queue UI, history and packaging arrive in the following phases.

## Windows installation

1. Install **Python 3.13+** from <https://www.python.org/downloads/> (tick *Add python.exe to PATH*).
2. Extract this folder anywhere, e.g. `C:\QuanttumDownloader`.
3. Double-click **`setup_and_run.bat`** — it creates a virtual environment, installs dependencies and starts the app.

Manual alternative (PowerShell):

```powershell
cd C:\QuanttumDownloader
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## FFmpeg setup

FFmpeg is needed from Phase 3 onward (merging video+audio, MP3/WAV conversion).

- Easiest: `winget install Gyan.FFmpeg`, then restart the app.
- Or download a build from <https://www.gyan.dev/ffmpeg/builds/>, extract it, and either add its `bin` folder to PATH or set the path in **Settings → Tools → FFmpeg location**.

The Home screen shows an *FFmpeg ready / not found* indicator.

## yt-dlp

Installed through `requirements.txt`. Keep it current — sites change often:

```powershell
pip install -U yt-dlp
```

Settings → Tools → **Check installation** shows the installed version.

## Project layout

```
main.py                 entry point
app/                    non-UI logic (config, settings, URL helpers, signal bus)
ui/                     all PySide6 widgets and pages
data/  logs/            created on first run (in %LOCALAPPDATA%\QuanttumDownloader when packaged)
```

## Responsible use

Only download content you own, that is in the public domain, or that you have permission to download. You are responsible for complying with each site's terms and applicable copyright law.

## Notes on downloads

- **FFmpeg** is required for audio conversion, merging separate video+audio streams, metadata and thumbnail embedding. Without it, video falls back to single-file formats (lower quality) and audio is disabled.
- **MP4** prefers H.264/AAC where the site offers it; at 1440p/2160p sites usually only provide VP9/AV1, which still go into MP4 but may need a modern player. Choose **MKV** or **WEBM** if you prefer.
- **Pause** stops the transfer and keeps the partial file; **Resume** continues from where it stopped. **Cancel** deletes the partial file.
- Closing the app while downloads run asks for confirmation and keeps partial files.
- Identical downloads (same link, format and folder) are not queued twice.

## Running the tests

```powershell
python tests/test_phase2.py
python tests/test_phase7.py   # layout/scroll regressions, resilience, budgets
python tests/test_phase6.py   # history, notifications, update flow
python tests/test_phase5.py   # audio bitrates/tags, subtitles
python tests/test_phase4.py   # queue, reorder, delete-from-disk
python tests/test_phase3.py   # needs ffmpeg + ffprobe; downloads from a local test server, no internet
```


## Supported sites, sign-in cookies and responsible use
* Anything yt-dlp supports (1000+ sites: YouTube, Vimeo, SoundCloud, TikTok, Instagram, X, Reddit, Twitch, Bandcamp…). See yt-dlp's `supportedsites.md` for the full list.
* **Sign-in cookies** (Settings): choose *From browser* (Chrome, Edge, Firefox, Brave, Opera, Vivaldi, Chromium) or *From cookies.txt* (Netscape format). The app stores only the browser name / file path, never the cookies. Close the browser first if reading its cookies fails.
* **Not possible:** DRM-protected services (Netflix, Spotify, Disney+ …). The app tells you instead of trying.
* Only download content you own or are allowed to download, and respect each site's terms and copyright law.
