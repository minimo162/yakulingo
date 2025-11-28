@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo Excel Translation Tool Setup
echo ============================================================
echo.

cd /d "%~dp0"

:: ============================================================
:: Proxy Settings (Pre-configured by distributor)
:: ============================================================
set PROXY_SERVER=136.131.63.233:8082
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
    echo [INFO] Proxy server: !PROXY_SERVER!

    :: Step 1a: Try with Windows authentication first
    echo [INFO] Trying Windows authentication...
    powershell -ExecutionPolicy Bypass -Command ^
        "$ProgressPreference = 'SilentlyContinue'; " ^
        "$proxy = New-Object System.Net.WebProxy('http://!PROXY_SERVER!'); " ^
        "$proxy.Credentials = [System.Net.CredentialCache]::DefaultNetworkCredentials; " ^
        "[System.Net.WebRequest]::DefaultWebProxy = $proxy; " ^
        "$url = 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip'; " ^
        "try { " ^
        "    Invoke-WebRequest -Uri $url -OutFile 'uv.zip' -UseBasicParsing -TimeoutSec 30; " ^
        "    Expand-Archive -Path 'uv.zip' -DestinationPath '.' -Force; " ^
        "    Remove-Item 'uv.zip'; " ^
        "} catch { " ^
        "    exit 1; " ^
        "}" 2>nul

    if exist "uv.exe" (
        echo [OK] Windows authentication successful.
    ) else (
        echo [WARN] Windows authentication failed.

        :: Step 1b: Prompt for manual credentials as last resort
        echo [INFO] Requesting manual credentials...
        call :prompt_proxy_credentials
        if defined PROXY_USER (
            echo [INFO] Retrying with manual credentials...
            powershell -ExecutionPolicy Bypass -Command ^
                "$ProgressPreference = 'SilentlyContinue'; " ^
                "Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile 'uv.zip' -Proxy '!HTTP_PROXY!' -UseBasicParsing -TimeoutSec 60; " ^
                "Expand-Archive -Path 'uv.zip' -DestinationPath '.' -Force; " ^
                "Remove-Item 'uv.zip'"

            if exist "uv.exe" (
                echo [OK] Manual authentication successful.
            ) else (
                echo [ERROR] Manual authentication failed.
            )
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

:: Check if Python 3.11 is already installed via uv
uv.exe python find 3.11 >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Python 3.11 already installed.
    goto :python_done
)

:: Try uv python install first (works without proxy auth)
uv.exe python install 3.11 --native-tls 2>nul
if not errorlevel 1 (
    echo [DONE] Python installed via uv.
    goto :python_done
)

:: If uv failed (likely proxy auth issue), download manually using PowerShell
echo [INFO] uv download failed, trying manual download with Windows auth...
set PYTHON_VERSION=3.11.14
set PYTHON_BUILD=20251120
set PYTHON_URL=https://github.com/astral-sh/python-build-standalone/releases/download/!PYTHON_BUILD!/cpython-!PYTHON_VERSION!+!PYTHON_BUILD!-x86_64-pc-windows-msvc-install_only_stripped.tar.gz
set PYTHON_ARCHIVE=python-!PYTHON_VERSION!.tar.gz
set PYTHON_INSTALL_DIR=!UV_PYTHON_INSTALL_DIR!\cpython-!PYTHON_VERSION!-windows-x86_64-none

:: Create python install directory
if not exist "!UV_PYTHON_INSTALL_DIR!" mkdir "!UV_PYTHON_INSTALL_DIR!"

:: Download Python using PowerShell with Windows authentication
if defined PROXY_SERVER (
    powershell -ExecutionPolicy Bypass -Command ^
        "$ProgressPreference = 'SilentlyContinue'; " ^
        "$proxy = New-Object System.Net.WebProxy('http://!PROXY_SERVER!'); " ^
        "$proxy.Credentials = [System.Net.CredentialCache]::DefaultNetworkCredentials; " ^
        "[System.Net.WebRequest]::DefaultWebProxy = $proxy; " ^
        "$url = '!PYTHON_URL!'; " ^
        "Write-Host '[INFO] Downloading Python from GitHub...'; " ^
        "try { " ^
        "    Invoke-WebRequest -Uri $url -OutFile '!PYTHON_ARCHIVE!' -UseBasicParsing -TimeoutSec 120; " ^
        "    Write-Host '[OK] Download complete.'; " ^
        "} catch { " ^
        "    Write-Host \"[ERROR] Download failed: $_\"; " ^
        "    exit 1; " ^
        "}"
) else (
    powershell -ExecutionPolicy Bypass -Command ^
        "$ProgressPreference = 'SilentlyContinue'; " ^
        "$url = '!PYTHON_URL!'; " ^
        "Write-Host '[INFO] Downloading Python from GitHub...'; " ^
        "try { " ^
        "    Invoke-WebRequest -Uri $url -OutFile '!PYTHON_ARCHIVE!' -UseBasicParsing -TimeoutSec 120; " ^
        "    Write-Host '[OK] Download complete.'; " ^
        "} catch { " ^
        "    Write-Host \"[ERROR] Download failed: $_\"; " ^
        "    exit 1; " ^
        "}"
)

if not exist "!PYTHON_ARCHIVE!" (
    echo [ERROR] Failed to download Python.
    pause
    exit /b 1
)

:: Extract Python archive using tar (available on Windows 10+)
echo [INFO] Extracting Python...
if not exist "!PYTHON_INSTALL_DIR!" mkdir "!PYTHON_INSTALL_DIR!"
tar -xzf "!PYTHON_ARCHIVE!" -C "!PYTHON_INSTALL_DIR!" --strip-components=1
if errorlevel 1 (
    echo [ERROR] Failed to extract Python.
    del "!PYTHON_ARCHIVE!" 2>nul
    pause
    exit /b 1
)

:: Clean up archive
del "!PYTHON_ARCHIVE!" 2>nul
echo [DONE] Python installed manually.

:python_done
echo [DONE] Python installed.

:: ============================================================
:: Step 3: Install dependencies
:: ============================================================
echo.
echo [3/4] Installing dependencies...
uv.exe venv --native-tls

:: Try uv sync first
uv.exe sync --native-tls 2>nul
if not errorlevel 1 goto :deps_done

:: If failed, try with manual proxy credentials
echo [WARN] uv sync failed. Proxy authentication may be required.
echo [INFO] Requesting proxy credentials for PyPI access...
call :prompt_proxy_credentials
if defined PROXY_USER (
    echo [INFO] Retrying with proxy credentials...
    uv.exe sync --native-tls
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
) else (
    echo [ERROR] Failed to install dependencies. Proxy credentials required.
    pause
    exit /b 1
)

:deps_done
echo [DONE] Dependencies installed.

:: ============================================================
:: Step 4: Install Playwright browser
:: ============================================================
echo.
echo [4/4] Installing Playwright browser...

:: Try playwright install first
uv.exe run --native-tls playwright install chromium 2>nul
if not errorlevel 1 goto :playwright_done

:: If failed, try with manual proxy credentials (if not already set)
echo [WARN] Playwright install failed. Proxy authentication may be required.
if not defined PROXY_USER (
    echo [INFO] Requesting proxy credentials for Playwright download...
    call :prompt_proxy_credentials
)
if defined PROXY_USER (
    echo [INFO] Retrying Playwright install with proxy credentials...
    uv.exe run --native-tls playwright install chromium
    if errorlevel 1 (
        echo [ERROR] Failed to install Playwright browser.
        pause
        exit /b 1
    )
) else (
    echo [ERROR] Failed to install Playwright browser. Proxy credentials required.
    pause
    exit /b 1
)

:playwright_done
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
