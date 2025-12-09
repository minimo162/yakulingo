@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo YakuLingo Setup
echo ============================================================
echo.

cd /d "%~dp0\.."

:: ============================================================
:: Proxy Settings
:: ============================================================
set PROXY_SERVER=136.131.63.233:8082

set UV_CACHE_DIR=.uv-cache
set UV_PYTHON_INSTALL_DIR=.uv-python
set PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers

:: ============================================================
:: Proxy Authentication (required)
:: ============================================================
echo [INFO] Proxy server: !PROXY_SERVER!
echo.
call :prompt_proxy_credentials
if not defined PROXY_USER (
    echo [ERROR] Proxy credentials are required.
    pause
    exit /b 1
)

:: ============================================================
:: Step 1: Download uv
:: ============================================================
if not exist "uv.exe" (
    echo.
    echo [1/5] Downloading uv...

    powershell -ExecutionPolicy Bypass -Command ^
        "$ProgressPreference = 'SilentlyContinue'; " ^
        "$proxy = 'http://!PROXY_SERVER!'; " ^
        "$secPwd = ConvertTo-SecureString $env:PROXY_PASS -AsPlainText -Force; " ^
        "$cred = New-Object System.Management.Automation.PSCredential ($env:PROXY_USER, $secPwd); " ^
        "Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile 'uv.zip' -Proxy $proxy -ProxyCredential $cred -UseBasicParsing -TimeoutSec 60; " ^
        "Expand-Archive -Path 'uv.zip' -DestinationPath '.' -Force; " ^
        "Remove-Item 'uv.zip'"

    if not exist "uv.exe" (
        echo [ERROR] Failed to download uv.
        pause
        exit /b 1
    )
    echo [DONE] uv downloaded.
) else (
    echo [1/5] SKIP - uv.exe already exists.
)

:: ============================================================
:: Step 2: Install Python
:: ============================================================
echo.
echo [2/5] Installing Python...

:: Check if Python 3.11 is already installed via uv
uv.exe python find 3.11 >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Python 3.11 already installed.
    goto :python_done
)

:: Try uv python install first
uv.exe python install 3.11 --native-tls 2>nul
if not errorlevel 1 (
    echo [DONE] Python installed via uv.
    goto :python_done
)

:: If uv failed, download manually using PowerShell
echo [INFO] uv download failed, trying manual download...
set PYTHON_VERSION=3.11.14
set PYTHON_BUILD=20251120
set PYTHON_URL=https://github.com/astral-sh/python-build-standalone/releases/download/!PYTHON_BUILD!/cpython-!PYTHON_VERSION!+!PYTHON_BUILD!-x86_64-pc-windows-msvc-install_only_stripped.tar.gz
set PYTHON_ARCHIVE=python-!PYTHON_VERSION!.tar.gz
set PYTHON_INSTALL_DIR=!UV_PYTHON_INSTALL_DIR!\cpython-!PYTHON_VERSION!-windows-x86_64-none

:: Create python install directory
if not exist "!UV_PYTHON_INSTALL_DIR!" mkdir "!UV_PYTHON_INSTALL_DIR!"

:: Download Python using PowerShell
powershell -ExecutionPolicy Bypass -Command ^
    "$ProgressPreference = 'SilentlyContinue'; " ^
    "$url = '!PYTHON_URL!'; " ^
    "$proxy = 'http://!PROXY_SERVER!'; " ^
    "$secPwd = ConvertTo-SecureString $env:PROXY_PASS -AsPlainText -Force; " ^
    "$cred = New-Object System.Management.Automation.PSCredential ($env:PROXY_USER, $secPwd); " ^
    "Write-Host '[INFO] Downloading Python from GitHub...'; " ^
    "try { " ^
    "    Invoke-WebRequest -Uri $url -OutFile '!PYTHON_ARCHIVE!' -Proxy $proxy -ProxyCredential $cred -UseBasicParsing -TimeoutSec 120; " ^
    "    Write-Host '[OK] Download complete.'; " ^
    "} catch { " ^
    "    Write-Host \"[ERROR] Download failed: $_\"; " ^
    "    exit 1; " ^
    "}"

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
echo [3/5] Installing dependencies...
uv.exe venv --native-tls
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

uv.exe sync --native-tls --extra ocr
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:: Verify PaddleOCR installation
echo [INFO] Verifying PaddleOCR installation...
.venv\Scripts\python.exe -c "import paddle; print(f'[OK] PaddlePaddle {paddle.__version__}')" 2>nul
if errorlevel 1 (
    echo [WARNING] PaddlePaddle import failed. Attempting reinstall...
    .venv\Scripts\pip.exe install --upgrade paddlepaddle>=3.0.0
)

.venv\Scripts\python.exe -c "from paddleocr import LayoutDetection; print('[OK] PaddleOCR LayoutDetection available')" 2>nul
if errorlevel 1 (
    echo [WARNING] PaddleOCR import failed. Attempting reinstall...
    .venv\Scripts\pip.exe install --upgrade paddleocr>=3.0.0

    :: Verify again after reinstall
    .venv\Scripts\python.exe -c "from paddleocr import LayoutDetection; print('[OK] PaddleOCR LayoutDetection available')" 2>nul
    if errorlevel 1 (
        echo [WARNING] PaddleOCR still not working. PDF layout analysis will be disabled.
        echo [INFO] You can manually install with: pip install paddleocr paddlepaddle
    )
)

echo [DONE] Dependencies installed.

:: ============================================================
:: Step 4: Install Playwright browser
:: ============================================================
echo.
echo [4/5] Installing Playwright browser...

uv.exe run --native-tls playwright install chromium
if errorlevel 1 (
    echo [ERROR] Failed to install Playwright browser.
    pause
    exit /b 1
)
echo [DONE] Playwright browser installed.

:: ============================================================
:: Step 5: Pre-compile Python bytecode for faster first launch
:: ============================================================
echo.
echo [5/5] Pre-compiling Python bytecode...
.venv\Scripts\python.exe -m compileall -q yakulingo 2>nul
.venv\Scripts\python.exe -c "import nicegui; import pywebview; from yakulingo.ui import app; from yakulingo.services import translation_service" 2>nul
:: Pre-import paddle/paddleocr to download models and cache them (may take a while)
.venv\Scripts\python.exe -c "import paddle; from paddleocr import LayoutDetection" 2>nul
echo [DONE] Bytecode pre-compiled.

echo.
echo ============================================================
echo Setup completed!
echo Double-click YakuLingo.exe to start YakuLingo.
echo ============================================================
echo.
pause
endlocal
exit /b 0

:: ============================================================
:: Function: Prompt for proxy credentials
:: ============================================================
:prompt_proxy_credentials
echo ============================================================
echo Proxy Authentication
echo Server: !PROXY_SERVER!
echo ============================================================
set /p PROXY_USER="Username: "
if not defined PROXY_USER exit /b 0

:: Use PowerShell to securely input password (masked)
echo Password (input will be hidden):
for /f "delims=" %%p in ('powershell -Command "$p = Read-Host -AsSecureString; [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p))"') do set PROXY_PASS=%%p

if not defined PROXY_PASS (
    echo [ERROR] Password is required.
    exit /b 0
)

set HTTP_PROXY=http://!PROXY_USER!:!PROXY_PASS!@!PROXY_SERVER!
set HTTPS_PROXY=http://!PROXY_USER!:!PROXY_PASS!@!PROXY_SERVER!
echo.
echo [OK] Credentials configured.
exit /b 0
