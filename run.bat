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
    echo Please reinstall the application.
    pause
    exit /b 1
)

REM Fix pyvenv.cfg home path for portability (runs on every start)
if exist "%VENV_DIR%\pyvenv.cfg" (
    set PYVENV_CFG=%VENV_DIR%\pyvenv.cfg
    set TEMP_CFG=%VENV_DIR%\pyvenv.cfg.tmp

    REM Rewrite pyvenv.cfg with correct Python path
    (
        echo home = !PYTHON_DIR!
        echo include-system-site-packages = false
        for /f "tokens=1,* delims==" %%a in ('type "!PYVENV_CFG!" ^| findstr /i "^version"') do (
            echo version =%%b
        )
    ) > "!TEMP_CFG!"
    move /y "!TEMP_CFG!" "!PYVENV_CFG!" >nul 2>&1
)

set PATH=%VENV_DIR%\Scripts;%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%PATH%
set VIRTUAL_ENV=%VENV_DIR%

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [ERROR] .venv not found.
    echo Please reinstall the application.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Starting YakuLingo...
echo ============================================================
echo.

"%VENV_DIR%\Scripts\python.exe" app.py

if errorlevel 1 (
    echo.
    echo [ERROR] An error occurred during execution.
    pause
)
endlocal
