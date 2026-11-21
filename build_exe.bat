@echo off
rem Builds dist\QuanttumDownloader\QuanttumDownloader.exe (a folder you can zip and share).
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher not found. Install Python 3.13 from https://www.python.org/downloads/ first.
    pause
    exit /b 1
)
if not exist .venv ( py -3.13 -m venv .venv 2>nul || py -3 -m venv .venv )
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt pyinstaller
if errorlevel 1 ( echo Installing dependencies failed. & pause & exit /b 1 )
pyinstaller --noconfirm --clean QuanttumDownloader.spec
if errorlevel 1 ( echo Build failed. See the messages above. & pause & exit /b 1 )
echo.
echo Done: dist\QuanttumDownloader\QuanttumDownloader.exe
echo Optional: copy ffmpeg.exe and ffprobe.exe into dist\QuanttumDownloader\ffmpeg\ to bundle FFmpeg.
pause
