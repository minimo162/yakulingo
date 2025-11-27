@echo off
setlocal

echo.
echo ============================================================
echo Excel Translation Tool Setup
echo ============================================================
echo.

cd /d "%~dp0"

set UV_CACHE_DIR=.uv-cache
set UV_PYTHON_INSTALL_DIR=.uv-python
set PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers

if not exist "uv.exe" (
    echo [1/4] Downloading uv...
    powershell -ExecutionPolicy Bypass -Command ^
        "$ProgressPreference = 'SilentlyContinue'; " ^
        "Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile 'uv.zip'; " ^
        "Expand-Archive -Path 'uv.zip' -DestinationPath '.' -Force; " ^
        "Remove-Item 'uv.zip'"
    if not exist "uv.exe" (
        echo [ERROR] Failed to download uv.
        pause
        exit /b 1
    )
    echo [DONE] uv downloaded.
) else (
    echo [SKIP] uv.exe already exists.
)

echo.
echo [2/4] Installing Python...
uv.exe python install 3.11 --native-tls
if errorlevel 1 (
    echo [ERROR] Failed to install Python.
    pause
    exit /b 1
)
echo [DONE] Python installed.

echo.
echo [3/4] Installing dependencies...
uv.exe venv --native-tls
uv.exe sync --native-tls
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo [DONE] Dependencies installed.

echo.
echo [4/4] Installing Playwright browser...
uv.exe run --native-tls playwright install chromium
if errorlevel 1 (
    echo [ERROR] Failed to install Playwright browser.
    pause
    exit /b 1
)
echo [DONE] Playwright browser installed.

echo.
echo ============================================================
echo Setup completed!
echo Run the star-run.bat to start the translation tool.
echo ============================================================
echo.
pause
endlocal
