@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo Excel Translation Tool Setup
echo ============================================================
echo.

cd /d "%~dp0"

:: ============================================================
:: Proxy Settings (配布者が事前に設定)
:: ============================================================
:: 自動検出できない場合は、以下にプロキシサーバーを記入してください
:: set PROXY_SERVER=proxy.yourcompany.co.jp:8080
:: ============================================================

set UV_CACHE_DIR=.uv-cache
set UV_PYTHON_INSTALL_DIR=.uv-python
set PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers

:: Try to auto-detect system proxy from registry (IE/Edge settings)
if not defined PROXY_SERVER (
    for /f "tokens=2*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable 2^>nul ^| find "REG_DWORD"') do (
        set /a PROXY_ENABLED=%%b
    )
    if "!PROXY_ENABLED!"=="1" (
        for /f "tokens=2*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2^>nul ^| find "REG_SZ"') do (
            set PROXY_SERVER=%%b
        )
    )
)

if defined PROXY_SERVER (
    echo [INFO] Proxy server: !PROXY_SERVER!
    set HTTP_PROXY=http://!PROXY_SERVER!
    set HTTPS_PROXY=http://!PROXY_SERVER!
)

:: ============================================================
:: Step 1: Download uv
:: ============================================================
if not exist "uv.exe" (
    echo.
    echo [1/4] Downloading uv...

    :: Try with Windows authentication first
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
        "Remove-Item 'uv.zip'" 2>nul

    if not exist "uv.exe" (
        if defined PROXY_SERVER (
            echo [WARN] Download failed. Proxy authentication may be required.
            call :prompt_proxy_credentials
            if defined HTTP_PROXY (
                echo [INFO] Retrying with authentication...
                powershell -ExecutionPolicy Bypass -Command ^
                    "$ProgressPreference = 'SilentlyContinue'; " ^
                    "Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile 'uv.zip' -Proxy '!HTTP_PROXY!' -UseBasicParsing; " ^
                    "Expand-Archive -Path 'uv.zip' -DestinationPath '.' -Force; " ^
                    "Remove-Item 'uv.zip'"
            )
        ) else (
            echo [ERROR] Download failed. No proxy detected.
            echo Please check your internet connection.
        )
    )

    if not exist "uv.exe" (
        echo [ERROR] Failed to download uv.
        pause
        exit /b 1
    )
    echo [DONE] uv downloaded.
) else (
    echo [1/4] SKIP - uv.exe already exists.
)

:: ============================================================
:: Step 2: Install Python
:: ============================================================
echo.
echo [2/4] Installing Python...
uv.exe python install 3.11 --native-tls
if errorlevel 1 (
    echo [ERROR] Failed to install Python.
    pause
    exit /b 1
)
echo [DONE] Python installed.

:: ============================================================
:: Step 3: Install dependencies
:: ============================================================
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

:: ============================================================
:: Step 4: Install Playwright browser
:: ============================================================
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
exit /b 0

:: ============================================================
:: Function: Prompt for proxy credentials (username/password only)
:: ============================================================
:prompt_proxy_credentials
echo.
echo ============================================================
echo Proxy Authentication Required
echo Server: %PROXY_SERVER%
echo ============================================================
set /p PROXY_USER="Username (or press Enter to skip): "
if not defined PROXY_USER (
    exit /b 0
)

:: Use PowerShell to securely input password (masked)
echo Password (input will be hidden):
for /f "delims=" %%p in ('powershell -Command "$p = Read-Host -AsSecureString; [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p))"') do set PROXY_PASS=%%p

set HTTP_PROXY=http://!PROXY_USER!:!PROXY_PASS!@!PROXY_SERVER!
set HTTPS_PROXY=http://!PROXY_USER!:!PROXY_PASS!@!PROXY_SERVER!
echo [INFO] Credentials configured.
exit /b 0
