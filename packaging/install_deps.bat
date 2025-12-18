@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo YakuLingo Setup
echo ============================================================
echo.

cd /d "%~dp0\.."

:: ============================================================
:: Proxy Settings (optional)
:: ============================================================
set PROXY_SERVER=136.131.63.233:8082
set USE_PROXY=0
set SKIP_SSL=0

set UV_CACHE_DIR=.uv-cache
set UV_PYTHON_INSTALL_DIR=.uv-python
set PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers
:: Increase timeout for large packages like paddlepaddle (~500MB-1GB)
set UV_HTTP_TIMEOUT=600

:: ============================================================
:: Proxy Configuration (optional)
:: ============================================================
echo Do you need to use a proxy server?
echo.
echo   [1] Yes - Use proxy (corporate network)
echo   [2] No  - Direct connection
echo   [3] No  - Direct connection (skip SSL verification)
echo.
set /p PROXY_CHOICE="Enter choice (1, 2, or 3): "

:: Debug: show what was entered
echo [DEBUG] PROXY_CHOICE=[!PROXY_CHOICE!]

if "!PROXY_CHOICE!"=="1" goto :use_proxy
if "!PROXY_CHOICE!"=="3" goto :no_proxy_insecure
goto :no_proxy

:use_proxy
:: Use proxy
set USE_PROXY=1
echo.
echo Enter proxy server address (press Enter for default):
set /p PROXY_INPUT="Proxy server [!PROXY_SERVER!]: "
if defined PROXY_INPUT set PROXY_SERVER=!PROXY_INPUT!
echo.
echo [INFO] Proxy server: !PROXY_SERVER!
echo.
call :prompt_proxy_credentials
if not defined PROXY_USER (
    echo [ERROR] Proxy credentials are required when using proxy.
    pause
    exit /b 1
)
goto :proxy_done

:no_proxy_insecure
:: Direct connection with insecure SSL
set SKIP_SSL=1
:: Disable SSL verification for Python requests/urllib
set PYTHONHTTPSVERIFY=0
set REQUESTS_CA_BUNDLE=
set CURL_CA_BUNDLE=
set SSL_CERT_FILE=
echo.
echo [INFO] Using direct connection (SSL verification disabled).
echo.
goto :proxy_done

:no_proxy
echo.
echo [INFO] Using direct connection (no proxy).
echo.

:proxy_done
echo [DEBUG] Proxy config done, USE_PROXY=[!USE_PROXY!], SKIP_SSL=[!SKIP_SSL!]

:: ============================================================
:: Step 1: Download uv
:: ============================================================
if exist "uv.exe" (
    echo [1/6] SKIP - uv.exe already exists.
    goto :uv_done
)

echo.
echo [1/6] Downloading uv...

if not "!USE_PROXY!"=="1" goto :uv_download_direct

:: Download uv with proxy
powershell -ExecutionPolicy Bypass -Command ^
    "$ProgressPreference = 'SilentlyContinue'; " ^
    "$proxy = 'http://!PROXY_SERVER!'; " ^
    "$secPwd = ConvertTo-SecureString $env:PROXY_PASS -AsPlainText -Force; " ^
    "$cred = New-Object System.Management.Automation.PSCredential ($env:PROXY_USER, $secPwd); " ^
    "Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile 'uv.zip' -Proxy $proxy -ProxyCredential $cred -UseBasicParsing -TimeoutSec 60; " ^
    "Expand-Archive -Path 'uv.zip' -DestinationPath 'uv-temp' -Force; " ^
    "$uvExe = Get-ChildItem -Path 'uv-temp' -Filter 'uv.exe' -Recurse | Select-Object -First 1; " ^
    "if ($uvExe) { Copy-Item $uvExe.FullName -Destination '.' -Force }; " ^
    "$uvxExe = Get-ChildItem -Path 'uv-temp' -Filter 'uvx.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1; " ^
    "if ($uvxExe) { Copy-Item $uvxExe.FullName -Destination '.' -Force }; " ^
    "Remove-Item 'uv-temp' -Recurse -Force -ErrorAction SilentlyContinue; " ^
    "Remove-Item 'uv.zip' -ErrorAction SilentlyContinue"
goto :uv_check

:uv_download_direct
:: Download uv without proxy
powershell -ExecutionPolicy Bypass -Command ^
    "$ProgressPreference = 'SilentlyContinue'; " ^
    "Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile 'uv.zip' -UseBasicParsing -TimeoutSec 60; " ^
    "Expand-Archive -Path 'uv.zip' -DestinationPath 'uv-temp' -Force; " ^
    "$uvExe = Get-ChildItem -Path 'uv-temp' -Filter 'uv.exe' -Recurse | Select-Object -First 1; " ^
    "if ($uvExe) { Copy-Item $uvExe.FullName -Destination '.' -Force }; " ^
    "$uvxExe = Get-ChildItem -Path 'uv-temp' -Filter 'uvx.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1; " ^
    "if ($uvxExe) { Copy-Item $uvxExe.FullName -Destination '.' -Force }; " ^
    "Remove-Item 'uv-temp' -Recurse -Force -ErrorAction SilentlyContinue; " ^
    "Remove-Item 'uv.zip' -ErrorAction SilentlyContinue"

:uv_check
if not exist "uv.exe" (
    echo [ERROR] Failed to download uv.
    echo [INFO] Please check your network connection.
    pause
    exit /b 1
)
echo [DONE] uv downloaded.

:uv_done

:: ============================================================
:: Step 2: Install Python
:: ============================================================
echo.
echo [2/6] Installing Python...

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
if not "!USE_PROXY!"=="1" goto :python_download_direct

:: Download Python with proxy
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
goto :python_download_check

:python_download_direct
:: Download Python without proxy
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

:python_download_check

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
echo [3/6] Installing dependencies...
uv.exe venv --native-tls
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [INFO] Installing packages (including paddlepaddle ~500MB-1GB)...
echo [INFO] This may take 5-15 minutes depending on network speed...

:: Build uv sync command based on SSL settings
if "!SKIP_SSL!"=="1" (
    echo [INFO] SSL verification disabled for pypi.org and files.pythonhosted.org
    uv.exe sync --native-tls --extra ocr --allow-insecure-host pypi.org --allow-insecure-host files.pythonhosted.org
) else (
    uv.exe sync --native-tls --extra ocr
)
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    echo [INFO] If this was a timeout, try running the script again.
    pause
    exit /b 1
)

echo [DONE] Dependencies installed.

:: ============================================================
:: Step 4: Install Playwright browser
:: ============================================================
echo.
echo [4/6] Installing Playwright browser...

:: Use .venv Python directly to avoid uv run recreating the venv
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 (
    echo [ERROR] Failed to install Playwright browser.
    pause
    exit /b 1
)
echo [DONE] Playwright browser installed.

:: ============================================================
:: Step 5: Verify paddlepaddle installation
:: ============================================================
echo.
echo [5/6] Verifying paddlepaddle installation...

:: Check if venv python exists
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv\Scripts\python.exe not found.
    echo [INFO] Virtual environment may not have been created properly.
    echo [INFO] Please check the output of step 3.
    pause
    exit /b 1
)

echo [INFO] This may take a moment...
:: Use PowerShell to run paddle check (avoids batch quoting issues)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$script = 'import warnings; warnings.filterwarnings(''ignore''); import paddle; print(''[OK] paddlepaddle version:'', paddle.__version__)';" ^
    "& '.venv\Scripts\python.exe' -W ignore -c $script 2>$null;" ^
    "exit $LASTEXITCODE"
set PADDLE_ERROR=!errorlevel!
if !PADDLE_ERROR! neq 0 (
    echo [WARNING] paddlepaddle verification failed or not installed.
    echo [INFO] PDF layout analysis may not be available.
    echo [INFO] You can still try running YakuLingo - it will work for non-PDF files.
)

:: ============================================================
:: Step 6: Pre-compile Python bytecode for faster first launch
:: ============================================================
echo.
echo [6/6] Pre-compiling Python bytecode...
echo [INFO] This may take 3-5 minutes...

:: Compile all site-packages in parallel (-j 0 = use all CPUs)
:: This is critical for fast first launch - compiles all transitive dependencies
:: -x excludes Python 2 legacy files that cause SyntaxError
echo [INFO] Pre-compiling all site-packages (parallel)...
.venv\Scripts\python.exe -m compileall -q -j 0 -x "olefile2|test_" .venv\Lib\site-packages 2>nul
if errorlevel 1 (
    echo [WARNING] Some bytecode compilation failed, but this is not critical.
)

:: Compile yakulingo package
echo [INFO] Pre-compiling yakulingo package...
.venv\Scripts\python.exe -m compileall -q -j 0 yakulingo 2>nul

:: Warm up module cache by actually importing modules
:: This initializes Python's internal caches beyond just .pyc files
echo [INFO] Warming up module cache (takes ~30-60 seconds)...
.venv\Scripts\python.exe -c "import nicegui; from nicegui import ui, app, Client, events; import nicegui.elements; import fastapi; import uvicorn; import starlette; import pydantic; import httptools; import anyio; import h11; import watchfiles; import webview; from yakulingo.ui import app; from yakulingo.services import translation_service; print('[OK] Module cache warmed up.')" 2>nul
set IMPORT_ERROR=!errorlevel!
if !IMPORT_ERROR! neq 0 (
    echo [WARNING] Some module imports failed. This is usually not critical.
)

:: Pre-import paddle/paddleocr to download models and cache them (may take a while)
echo [INFO] Downloading paddleocr models (this may take a few minutes on first run)...
echo [INFO] - PP-DocLayout-L: Layout detection
echo [INFO] - TableCellsDetection: Table cell boundary detection (~124MB)
:: Use PowerShell to run paddleocr check (avoids batch quoting issues)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$script = 'import warnings; warnings.filterwarnings(''ignore''); import paddle; from paddleocr import LayoutDetection, TableCellsDetection; print(''[OK] paddleocr models ready.'')';" ^
    "& '.venv\Scripts\python.exe' -W ignore -c $script 2>$null;" ^
    "exit $LASTEXITCODE"
set OCR_ERROR=!errorlevel!
if !OCR_ERROR! neq 0 (
    echo [WARNING] paddleocr model download may have failed. PDF layout analysis may not work.
    echo [INFO] You can try running YakuLingo anyway - models will be downloaded on first PDF translation.
)
echo [DONE] Pre-compilation complete.

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
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "$p = Read-Host -AsSecureString; if ($p.Length -gt 0) { [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p)) } else { 'EMPTY_PASSWORD' }"`) do set PROXY_PASS=%%p

if not defined PROXY_PASS (
    echo [ERROR] Password input failed.
    exit /b 0
)
if "!PROXY_PASS!"=="EMPTY_PASSWORD" (
    echo [ERROR] Password is required.
    set PROXY_PASS=
    exit /b 0
)

set HTTP_PROXY=http://!PROXY_USER!:!PROXY_PASS!@!PROXY_SERVER!
set HTTPS_PROXY=http://!PROXY_USER!:!PROXY_PASS!@!PROXY_SERVER!
echo.
echo [OK] Credentials configured.
exit /b 0
