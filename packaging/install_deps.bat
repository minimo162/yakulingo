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
:: Increase timeout for large packages like paddlepaddle (~500MB-1GB)
set UV_HTTP_TIMEOUT=600

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
    echo [1/6] Downloading uv...

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

    if not exist "uv.exe" (
        echo [ERROR] Failed to download uv.
        echo [INFO] Please check your network connection and proxy settings.
        pause
        exit /b 1
    )
    echo [DONE] uv downloaded.
) else (
    echo [1/6] SKIP - uv.exe already exists.
)

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
echo [3/6] Installing dependencies...
uv.exe venv --native-tls
if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [INFO] Installing packages (including paddlepaddle ~500MB-1GB)...
echo [INFO] This may take 5-15 minutes depending on network speed...
uv.exe sync --native-tls --extra ocr
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

:: First test that Python itself works
echo [DEBUG] Testing basic Python...
.venv\Scripts\python.exe -c "print('Python OK')"
if errorlevel 1 (
    echo [ERROR] Basic Python test failed.
    pause
    exit /b 1
)

echo [INFO] This may take a moment...
:: Use -W ignore to suppress ccache and other warnings
:: Use cmd /c to run in isolated subprocess (prevents PaddlePaddle from affecting batch)
cmd /c ".venv\Scripts\python.exe -W ignore -c "import warnings; warnings.filterwarnings('ignore'); import paddle; print('[OK] paddlepaddle version:', paddle.__version__)"" 2>nul
set PADDLE_ERROR=!errorlevel!
echo [DEBUG] Python exit code: !PADDLE_ERROR!
if !PADDLE_ERROR! neq 0 (
    echo [WARNING] paddlepaddle is not installed correctly.
    echo [INFO] Attempting manual installation via uv pip...
    echo [INFO] paddlepaddle is large (~500MB-1GB), this may take several minutes...
    uv.exe pip install --native-tls paddlepaddle>=3.0.0 paddleocr>=3.0.0
    if errorlevel 1 (
        echo [ERROR] Failed to install paddlepaddle.
        echo [INFO] PDF layout analysis will not be available.
    ) else (
        echo [OK] paddlepaddle installed successfully.
        :: Verify again after install
        cmd /c ".venv\Scripts\python.exe -W ignore -c "import warnings; warnings.filterwarnings('ignore'); import paddle; print('[OK] paddlepaddle version:', paddle.__version__)"" 2>nul
    )
)

:: ============================================================
:: Step 6: Pre-compile Python bytecode for faster first launch
:: ============================================================
echo.
echo [6/6] Pre-compiling Python bytecode...
.venv\Scripts\python.exe -m compileall -q yakulingo
if errorlevel 1 (
    echo [WARNING] Some bytecode compilation failed, but this is not critical.
)

echo [INFO] Pre-importing modules for faster startup...
.venv\Scripts\python.exe -c "import nicegui; import pywebview; from yakulingo.ui import app; from yakulingo.services import translation_service"
if errorlevel 1 (
    echo [WARNING] Some module imports failed. Check the error above.
)

:: Pre-import paddle/paddleocr to download models and cache them (may take a while)
echo [INFO] Downloading paddleocr models (this may take a few minutes on first run)...
cmd /c ".venv\Scripts\python.exe -W ignore -c "import warnings; warnings.filterwarnings('ignore'); import paddle; from paddleocr import LayoutDetection; print('[OK] paddleocr models ready.')"" 2>nul
if errorlevel 1 (
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
