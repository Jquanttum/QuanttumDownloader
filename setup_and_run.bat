@echo off
rem Creates a virtual environment on first run, installs dependencies and launches the app.
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher not found. Install Python 3.13 from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    pause
    exit /b 1
)
if not exist .venv (
    py -3.13 -m venv .venv 2>nul || py -3 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
python main.py
