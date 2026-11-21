# Quanttum Downloader — Windows install guide

Three ways to run it. Pick one.

## A. Easiest: double-click `setup_and_run.bat`
1. Install **Python 3.13** from <https://www.python.org/downloads/> and tick **"Add python.exe to PATH"**.
2. Unzip the project anywhere (a normal folder such as `Documents`, not inside the zip).
3. Double-click `setup_and_run.bat`. The first run creates a private `.venv`, installs PySide6 and yt-dlp, then starts the app. Later runs start in seconds.

## B. Build a standalone app (`.exe`)
1. Do step 1–2 above.
2. Double-click `build_exe.bat` (takes a few minutes).
3. Your app is in `dist\QuanttumDownloader\`. Run `QuanttumDownloader.exe`, or zip that whole folder to share it. Pin it to the taskbar if you like.

## C. Manual (for developers)
```bat
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## FFmpeg (needed for MP3/M4A/WAV, merging HD video, thumbnails and subtitles)
Without FFmpeg the app still downloads single-file video, and tells you what it can't do.
The app looks for FFmpeg in this order: the path set in **Settings**, a folder called `ffmpeg` next to the app, then your `PATH`.

**Option 1 – winget (recommended):** open Command Prompt and run
`winget install Gyan.FFmpeg`, then restart Quanttum Downloader.

**Option 2 – manual:** download a "release essentials" build from <https://www.gyan.dev/ffmpeg/builds/>, unzip it, and either
* copy `ffmpeg.exe` **and** `ffprobe.exe` into an `ffmpeg` folder next to `QuanttumDownloader.exe` (or the project folder), or
* choose the unzipped `bin` folder in **Settings → FFmpeg location**.

## Updating yt-dlp
Sites change often. If downloads start failing, open **Settings → yt-dlp → Check for updates → Update**, then restart.
(The standalone `.exe` can't update itself: rebuild with `build_exe.bat`, which fetches the newest yt-dlp.)

## Where things are stored
| What | Where |
|---|---|
| Settings | Windows registry (`HKCU\Software\Quanttum`) |
| History database, logs | project folder (`data\`, `logs\`) when run from source; `%LOCALAPPDATA%\QuanttumDownloader\` (`data`, `logs`) for the `.exe` |
| Downloads | the folder you choose (default: your Downloads folder) |

**Uninstall:** delete the app folder; optionally delete `%LOCALAPPDATA%\QuanttumDownloader` and the registry key above.

## Troubleshooting
* **"Python not found"** – reinstall Python and tick *Add python.exe to PATH*, or use the `py` launcher.
* **Windows SmartScreen warns about the `.exe`** – it's unsigned. Choose *More info → Run anyway*.
* **A download fails** – read the message in the app first (it's written in plain language). Update yt-dlp, then retry. Technical details are in the log: **About → Open log folder**.
* **"FFmpeg not found"** – see the FFmpeg section above.
* **Only use it for content you own or are allowed to download.** Respect the site's terms and copyright law.
