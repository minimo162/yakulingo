@echo off
setlocal
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%prepare-python-runtime.ps1" %*
if errorlevel 1 (
  echo.
  echo Failed to prepare Python runtime.
  pause
  exit /b 1
)
endlocal
