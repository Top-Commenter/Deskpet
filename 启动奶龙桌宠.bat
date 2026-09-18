@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo First run: creating virtual environment...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

if not exist "node_modules\NeteaseCloudMusicApi\app.js" (
    npm install NeteaseCloudMusicApi
)

start "" ".venv\Scripts\pythonw.exe" main.py
