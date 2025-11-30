@echo off
:: YakuLingo Setup
:: Copies files and creates shortcuts

cd /d "%~dp0"

echo.
echo Starting YakuLingo Setup...
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0_internal\setup.ps1"

if errorlevel 1 (
    echo.
    echo [ERROR] Setup failed.
    pause
)
