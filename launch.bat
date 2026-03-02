@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: .venv not found. Run: uv sync
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python launcher.py
if errorlevel 1 (
    echo.
    echo Launcher exited with an error.
    pause
)
