# PyInstaller spec for Quanttum Downloader.
#   build:  pyinstaller --noconfirm QuanttumDownloader.spec        (or run build_exe.bat)
#   result: dist/QuanttumDownloader/QuanttumDownloader.exe   (folder build: fast start, easy to zip)
# To ship FFmpeg with the app, put ffmpeg.exe and ffprobe.exe in a folder called "ffmpeg" next to the exe.
import sys
from PyInstaller.utils.hooks import collect_submodules

ICON = "assets/icon.ico"

# yt-dlp loads its site extractors by name, so they must be collected explicitly.
hidden = collect_submodules("yt_dlp") + ["yt_dlp.compat._legacy", "yt_dlp.compat._deprecated"]

# Qt modules the app never uses; excluding them keeps the download small.
excluded_qt = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtQml",
    "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSpatialAudio",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtHttpServer", "PySide6.QtGraphs",
    "tkinter", "unittest", "pydoc", "test",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=[("assets/icon.png", "assets")],
    hiddenimports=hidden,
    excludes=excluded_qt,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="QuanttumDownloader",
    console=False,
    icon=ICON if sys.platform == "win32" else None,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="QuanttumDownloader")
