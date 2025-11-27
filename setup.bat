@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo Excel Translation Tool Setup
echo ============================================================
echo.

cd /d "%~dp0"

:: ============================================================
:: Proxy Settings
:: ============================================================
:: Auto-detect from system settings (IE/Edge proxy)
:: If auto-detect fails, manually set these:
::
:: set PROXY_SERVER=proxy.example.com:8080
:: set PROXY_USER=your_user_id
:: set PROXY_PASS=your_password
::
:: ============================================================

:: Try to auto-detect system proxy from registry (IE/Edge settings)
if not defined PROXY_SERVER (
    for /f "tokens=2*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable 2^>nul ^| find "REG_DWORD"') do (
        set /a PROXY_ENABLED=%%b
    )
    if "!PROXY_ENABLED!"=="1" (
        for /f "tokens=2*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2^>nul ^| find "REG_SZ"') do (
            set PROXY_SERVER=%%b
        )
        if defined PROXY_SERVER (
            echo [INFO] Auto-detected system proxy: !PROXY_SERVER!
        )
    )
)

:: Apply proxy settings if configured (manual or auto-detected)
if defined PROXY_SERVER (
    if defined PROXY_USER (
        set HTTP_PROXY=http://%PROXY_USER%:%PROXY_PASS%@%PROXY_SERVER%
        set HTTPS_PROXY=http://%PROXY_USER%:%PROXY_PASS%@%PROXY_SERVER%
        echo [INFO] Proxy configured with authentication
    ) else (
        set HTTP_PROXY=http://%PROXY_SERVER%
        set HTTPS_PROXY=http://%PROXY_SERVER%
        echo [INFO] Proxy configured: %PROXY_SERVER%
    )
    echo.
)

set UV_CACHE_DIR=.uv-cache
set UV_PYTHON_INSTALL_DIR=.uv-python
set PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers

if not exist "uv.exe" (
    echo [1/4] Downloading uv...
    powershell -ExecutionPolicy Bypass -Command ^
        "$ProgressPreference = 'SilentlyContinue'; " ^
        "$proxy = [System.Net.WebRequest]::GetSystemWebProxy(); " ^
        "$proxy.Credentials = [System.Net.CredentialCache]::DefaultCredentials; " ^
        "[System.Net.WebRequest]::DefaultWebProxy = $proxy; " ^
        "$url = 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip'; " ^
        "try { " ^
        "    Invoke-WebRequest -Uri $url -OutFile 'uv.zip' -UseDefaultCredentials -UseBasicParsing; " ^
        "} catch { " ^
        "    Invoke-WebRequest -Uri $url -OutFile 'uv.zip' -UseBasicParsing; " ^
        "} " ^
        "Expand-Archive -Path 'uv.zip' -DestinationPath '.' -Force; " ^
        "Remove-Item 'uv.zip'"
    if not exist "uv.exe" (
        echo [ERROR] Failed to download uv.
        echo.
        echo If you are behind a corporate proxy, edit setup.bat and set:
        echo   PROXY_SERVER=your.proxy.server:port
        echo   PROXY_USER=your_username
        echo   PROXY_PASS=your_password
        echo.
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
