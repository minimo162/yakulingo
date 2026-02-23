@echo off
setlocal
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%_internal\start.ps1" %*
if errorlevel 1 (
  echo.
  echo Start failed. Press any key to close.
  pause >nul
  exit /b 1
)
endlocal
