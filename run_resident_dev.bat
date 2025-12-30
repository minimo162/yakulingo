@echo off
setlocal

cd /d "%~dp0"

set UV_CMD=uv
if exist "%~dp0uv.exe" set UV_CMD="%~dp0uv.exe"

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating virtual environment and installing dependencies...
  %UV_CMD% sync
  if errorlevel 1 exit /b 1
)

set "YAKULINGO_NO_AUTO_OPEN=1"

".venv\Scripts\python.exe" -c "import app as _app; import sys; _app.setup_logging(); if not _app._ensure_single_instance(): _app._try_focus_existing_window(); sys.exit(0); from yakulingo.ui.app import run_app; run_app(host='127.0.0.1', port=8765, native=False)"
