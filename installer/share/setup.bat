@echo off
:: ============================================================
:: YakuLingo One-Click Setup
:: Run this from the shared folder
:: ============================================================

cd /d "%~dp0"

echo.
echo ============================================================
echo                 YakuLingo Setup
echo ============================================================
echo.
echo This script will:
echo   1. Copy files to your local computer
echo   2. Create desktop shortcut
echo.

:: Confirmation prompt
set /p CONFIRM="Start setup? [Y/N]: "
if /i not "%CONFIRM%"=="Y" (
    echo Setup cancelled.
    timeout /t 3 > nul
    exit /b 0
)

echo.
echo Starting setup...
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

if errorlevel 1 (
    echo.
    echo ============================================================
    echo [ERROR] Setup failed.
    echo Please contact your administrator.
    echo ============================================================
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Setup completed!
echo Launch YakuLingo from the desktop shortcut.
echo ============================================================
echo.
pause
