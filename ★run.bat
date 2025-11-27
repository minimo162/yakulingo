@echo off
setlocal enabledelayedexpansion

cd /d %~dp0

set VENV_DIR=%~dp0.venv
set PLAYWRIGHT_BROWSERS_PATH=%~dp0.playwright-browsers

REM Dynamically find Python directory in .uv-python
set PYTHON_DIR=
for /d %%d in ("%~dp0.uv-python\cpython-*") do (
    set PYTHON_DIR=%%d
)

if not defined PYTHON_DIR (
    echo [ERROR] Python not found in .uv-python directory.
    echo Please run setup.bat first.
    pause
    exit /b 1
)

set PATH=%VENV_DIR%\Scripts;%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%PATH%
set VIRTUAL_ENV=%VENV_DIR%

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [ERROR] .venv not found.
    echo Please run setup.bat first.
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
