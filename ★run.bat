@echo off
setlocal

cd /d %~dp0

set VENV_DIR=%~dp0.venv
set PYTHON_DIR=%~dp0.uv-python\cpython-3.11.14-windows-x86_64-none
set PLAYWRIGHT_BROWSERS_PATH=%~dp0.playwright-browsers

set PATH=%VENV_DIR%\Scripts;%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%PATH%
set VIRTUAL_ENV=%VENV_DIR%

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [ERROR] .venv not found.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Starting Excel Translation Tool...
echo ============================================================
echo.

"%VENV_DIR%\Scripts\python.exe" translate.py

if errorlevel 1 (
    echo.
    echo [ERROR] An error occurred during execution.
    pause
)
endlocal
