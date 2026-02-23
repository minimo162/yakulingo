@echo off
setlocal
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%prepare-node-runtime.ps1" %*
if errorlevel 1 (
  echo.
  echo Failed to prepare Node runtime.
  pause
  exit /b 1
)
endlocal
