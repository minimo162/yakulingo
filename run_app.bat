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

".venv\Scripts\python.exe" app.py
