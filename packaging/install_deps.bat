@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo YakuLingo Setup
echo ============================================================
echo.

cd /d "%~dp0\.."

:: Ensure YakuLingo is not running (close it if needed)
set "ROOT_DIR=%CD%"
call :ensure_yakulingo_closed
if errorlevel 1 exit /b 1

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
:: Use a supported Python version (Playwright/greenlet are not compatible with Python 3.14+ yet)
set VENV_PYTHON_SPEC=3.11
set VENV_PYTHON_PATH=

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
    echo [1/7] SKIP - uv.exe already exists.
    goto :uv_done
)

echo.
echo [1/7] Downloading uv...

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
echo [2/7] Installing Python...

:: Check if Python is already installed via uv
uv.exe python find !VENV_PYTHON_SPEC! >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Python !VENV_PYTHON_SPEC! already installed.
    goto :python_done
)

:: Try uv python install first
uv.exe python install !VENV_PYTHON_SPEC! --native-tls 2>nul
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
set VENV_PYTHON_PATH=!PYTHON_INSTALL_DIR!\python.exe

:python_done
echo [DONE] Python installed.

:: ============================================================
:: Step 3: Install dependencies
:: ============================================================
echo.
echo [3/7] Installing dependencies...
call :ensure_yakulingo_closed
if errorlevel 1 exit /b 1

if not exist ".venv" goto :skip_clean_venv
echo [INFO] Cleaning existing .venv...
set CLEAN_VENV_RETRY=0
:clean_venv_retry
rmdir /s /q ".venv" >nul 2>&1
if not exist ".venv" goto :skip_clean_venv
set /a CLEAN_VENV_RETRY+=1
if !CLEAN_VENV_RETRY! geq 6 goto :clean_venv_failed
timeout /t 1 /nobreak >nul
goto :clean_venv_retry

:clean_venv_failed
echo [ERROR] Failed to clean .venv (it may be in use).
echo [INFO] Please close YakuLingo and retry.
pause
exit /b 1
:skip_clean_venv

echo [INFO] Installing packages (including paddlepaddle ~500MB-1GB)...
echo [INFO] This may take 5-15 minutes depending on network speed...

:: Ensure uv uses the intended Python for the project environment (prevents uv from re-creating .venv with a different Python)
set UV_SYNC_PYTHON_ARG=-p !VENV_PYTHON_SPEC!
if defined VENV_PYTHON_PATH set UV_SYNC_PYTHON_ARG=-p "!VENV_PYTHON_PATH!"

:: Build uv sync command based on SSL settings
if "!SKIP_SSL!"=="1" (
    echo [INFO] SSL verification disabled for pypi.org and files.pythonhosted.org
    uv.exe sync !UV_SYNC_PYTHON_ARG! --native-tls --extra ocr --allow-insecure-host pypi.org --allow-insecure-host files.pythonhosted.org
) else (
    uv.exe sync !UV_SYNC_PYTHON_ARG! --native-tls --extra ocr
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
echo [4/7] Installing Playwright browser...

:: Use .venv Python directly to avoid uv run recreating the venv
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 (
    echo [ERROR] Failed to install Playwright browser.
    pause
    exit /b 1
)
echo [DONE] Playwright browser installed.

:: ============================================================
:: Step 5: Verify paddlepaddle/paddleocr installation
:: ============================================================
echo.
echo [5/7] Verifying paddlepaddle/paddleocr installation...

:: Check if venv python exists
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv\Scripts\python.exe not found.
    echo [INFO] Virtual environment may not have been created properly.
    echo [INFO] Please check the output of step 3.
    pause
    exit /b 1
)

echo [INFO] This may take a moment...
:: Use PowerShell to run dependency check (avoids batch quoting issues)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$script = 'import warnings; warnings.filterwarnings(''ignore''); import paddle; import paddleocr; print(''[OK] paddlepaddle version:'', paddle.__version__); print(''[OK] paddleocr version:'', getattr(paddleocr, ''__version__'', ''(unknown)''))';" ^
    "& '.venv\Scripts\python.exe' -W ignore -c $script 2>$null;" ^
    "exit $LASTEXITCODE"
set "OCR_DEPS_ERROR=%ERRORLEVEL%"

if not "%OCR_DEPS_ERROR%"=="0" goto :reinstall_ocr_deps
goto :verify_ocr_deps_done

:reinstall_ocr_deps
echo [WARNING] paddlepaddle/paddleocr verification failed. Attempting to reinstall paddlepaddle/paddleocr...

if "!SKIP_SSL!"=="1" (
    uv.exe sync !UV_SYNC_PYTHON_ARG! --native-tls --extra ocr --reinstall-package paddlepaddle --reinstall-package paddleocr --allow-insecure-host pypi.org --allow-insecure-host files.pythonhosted.org
) else (
    uv.exe sync !UV_SYNC_PYTHON_ARG! --native-tls --extra ocr --reinstall-package paddlepaddle --reinstall-package paddleocr
)
if errorlevel 1 (
    echo [ERROR] Failed to reinstall paddlepaddle/paddleocr.
    echo [INFO] Please check your network connection and try again.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$script = 'import warnings; warnings.filterwarnings(''ignore''); import paddle; import paddleocr; print(''[OK] paddlepaddle version:'', paddle.__version__); print(''[OK] paddleocr version:'', getattr(paddleocr, ''__version__'', ''(unknown)''))';" ^
    "& '.venv\Scripts\python.exe' -W ignore -c $script 2>$null;" ^
    "exit $LASTEXITCODE"
set "OCR_DEPS_ERROR=%ERRORLEVEL%"

:verify_ocr_deps_done
if not "%OCR_DEPS_ERROR%"=="0" goto :verify_ocr_deps_failed
echo [DONE] paddlepaddle/paddleocr verified.
goto :verify_ocr_deps_exit

:verify_ocr_deps_failed
if not defined OCR_REQUIREMENTS_RETRY (
    set "OCR_REQUIREMENTS_RETRY=1"
    echo [WARNING] paddlepaddle/paddleocr is not available. Installing requirements_pdf.txt as a fallback...
    echo [INFO] Trying: uv.exe pip install -r requirements_pdf.txt
    if "!SKIP_SSL!"=="1" (
        uv.exe pip install !UV_SYNC_PYTHON_ARG! --native-tls --allow-insecure-host pypi.org --allow-insecure-host files.pythonhosted.org -r requirements_pdf.txt
    ) else (
        uv.exe pip install !UV_SYNC_PYTHON_ARG! --native-tls -r requirements_pdf.txt
    )
    if errorlevel 1 (
        echo [WARNING] uv pip install failed. Trying ensurepip + pip...
        .venv\Scripts\python.exe -m ensurepip --upgrade
        if errorlevel 1 (
            echo [ERROR] Failed to install pip via ensurepip.
            goto :verify_ocr_deps_failed_final
        )
        if "!SKIP_SSL!"=="1" (
            .venv\Scripts\python.exe -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements_pdf.txt
        ) else (
            .venv\Scripts\python.exe -m pip install -r requirements_pdf.txt
        )
        if errorlevel 1 goto :verify_ocr_deps_failed_final
    )

    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$script = 'import warnings; warnings.filterwarnings(''ignore''); import paddle; import paddleocr; print(''[OK] paddlepaddle version:'', paddle.__version__); print(''[OK] paddleocr version:'', getattr(paddleocr, ''__version__'', ''(unknown)''))';" ^
        "& '.venv\Scripts\python.exe' -W ignore -c $script 2>$null;" ^
        "exit $LASTEXITCODE"
    set "OCR_DEPS_ERROR=%ERRORLEVEL%"
    if "%OCR_DEPS_ERROR%"=="0" (
        echo [DONE] paddlepaddle/paddleocr verified.
        goto :verify_ocr_deps_exit
    )
)
goto :verify_ocr_deps_failed_final

:verify_ocr_deps_failed_final
echo [ERROR] paddlepaddle/paddleocr is not available in the virtual environment.
echo [INFO] PDF layout analysis (PP-DocLayout-L) requires paddlepaddle/paddleocr.
echo [INFO] Retry this installer, or run: uv.exe sync --extra ocr
echo [INFO] If uv sync fails, run: uv.exe pip install -r requirements_pdf.txt
echo [INFO] If pip is missing, run: .venv\Scripts\python.exe -m ensurepip --upgrade
echo [INFO] Then run: .venv\Scripts\python.exe -m pip install -r requirements_pdf.txt
pause
exit /b 1

:verify_ocr_deps_exit

:: ============================================================
:: Step 6: Pre-compile Python bytecode for faster first launch
:: ============================================================
echo.
echo [6/7] Pre-compiling Python bytecode...
echo [INFO] This may take 3-5 minutes...

:: Compile all site-packages in parallel (-j 0 = use all CPUs)
:: This is critical for fast first launch - compiles all transitive dependencies
:: -x excludes Python 2 legacy files that cause SyntaxError
:: --invalidation-mode=unchecked-hash: Uses hash-based cache that survives ZIP extraction
:: (Without this, mtime changes after ZIP extraction cause full recompilation: 23s -> <100ms)
echo [INFO] Pre-compiling all site-packages (parallel)...
.venv\Scripts\python.exe -m compileall -q -j 0 --invalidation-mode=unchecked-hash -x "olefile2|test_" .venv\Lib\site-packages 2>nul
if errorlevel 1 (
    echo [WARNING] Some bytecode compilation failed, but this is not critical.
)

:: Compile yakulingo package
echo [INFO] Pre-compiling yakulingo package...
.venv\Scripts\python.exe -m compileall -q -j 0 --invalidation-mode=unchecked-hash yakulingo 2>nul

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

:: ============================================================
:: Step 7: Download Local AI runtime (llama.cpp + optional model)
:: ============================================================
echo.
echo [7/7] Installing Local AI runtime (llama.cpp + optional model)...
echo [INFO] This step may download large files (model may be a few GB).

echo.
echo Do you want to install Local AI runtime now?
echo   [1] Yes - Download llama.cpp + AgentCPM-Explore model (build 4bit; very large download)
echo   [2] Yes - Download llama.cpp only (default; add model later)
echo   [3] No  - Skip this step
echo.
set /p LOCAL_AI_CHOICE="Enter choice (1, 2, or 3) [2]: "
if not defined LOCAL_AI_CHOICE set "LOCAL_AI_CHOICE=2"
if not "!LOCAL_AI_CHOICE!"=="1" if not "!LOCAL_AI_CHOICE!"=="2" if not "!LOCAL_AI_CHOICE!"=="3" set "LOCAL_AI_CHOICE=2"

if "!LOCAL_AI_CHOICE!"=="3" (
    echo [7/7] SKIP - Local AI runtime installation skipped.
    goto :local_ai_done
)

set "LOCAL_AI_SKIP_MODEL=0"
if "!LOCAL_AI_CHOICE!"=="2" set "LOCAL_AI_SKIP_MODEL=1"

if not exist "local_ai\\manifest.json" (
    if "!LOCAL_AI_SKIP_MODEL!"=="1" (
        echo [INFO] Local AI model: SKIP (LOCAL_AI_SKIP_MODEL=1)
    ) else (
        if not defined LOCAL_AI_MODEL_KIND set "LOCAL_AI_MODEL_KIND=hf"
        if not defined LOCAL_AI_MODEL_REPO set "LOCAL_AI_MODEL_REPO=openbmb/AgentCPM-Explore"
        if not defined LOCAL_AI_MODEL_QUANT set "LOCAL_AI_MODEL_QUANT=Q4_K_M"
        if not defined LOCAL_AI_MODEL_BASE_NAME set "LOCAL_AI_MODEL_BASE_NAME=AgentCPM-Explore"
        echo [INFO] Local AI model: AgentCPM-Explore (LOCAL_AI_MODEL_KIND=!LOCAL_AI_MODEL_KIND!, quant=!LOCAL_AI_MODEL_QUANT!)
        echo [INFO] NOTE: HF^>GGUF^>4bit may require extra Python deps and can take a long time.
    )
)

if not exist "local_ai\\manifest.json" (
    if "!LOCAL_AI_SKIP_MODEL!"=="1" (
        echo [INFO] You can add a model later via LOCAL_AI_MODEL_KIND=gguf/hf and rerun: powershell -NoProfile -ExecutionPolicy Bypass -File packaging\install_local_ai.ps1
    )
)

if not defined LOCAL_AI_LLAMA_CPP_VARIANT (
    if not exist "local_ai\\manifest.json" (
        set "LOCAL_AI_LLAMA_CPP_VARIANT=cpu"
        echo [INFO] llama.cpp variant: !LOCAL_AI_LLAMA_CPP_VARIANT! ^(default for new install^)
    ) else (
        echo [INFO] llama.cpp variant: manifest.json ^(set LOCAL_AI_LLAMA_CPP_VARIANT to override^)
    )
) else (
    echo [INFO] llama.cpp variant: !LOCAL_AI_LLAMA_CPP_VARIANT! ^(env override^)
)

powershell -NoProfile -ExecutionPolicy Bypass -File "packaging\install_local_ai.ps1"
if errorlevel 1 (
    echo [WARNING] Failed to install Local AI runtime ^(optional^).
    echo [INFO] Copilot translation will still work.
    echo [INFO] You can retry later: powershell -NoProfile -ExecutionPolicy Bypass -File packaging\install_local_ai.ps1
    echo [INFO] If HF build failed, you can switch to GGUF download: set LOCAL_AI_MODEL_KIND=gguf (and set LOCAL_AI_MODEL_REPO/FILE), or choose option [2] (llama.cpp only).
    echo [INFO] Or manually place files under local_ai\ ^(llama_cpp + models^).
)

:local_ai_done

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
:: Function: Ensure YakuLingo is not running
:: ============================================================
:ensure_yakulingo_closed
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'SilentlyContinue';" ^
    "$root = [System.IO.Path]::GetFullPath('%ROOT_DIR%');" ^
    "$installRoot = Join-Path $env:LOCALAPPDATA 'YakuLingo';" ^
    "$pathsToCheck = @($root, $installRoot) | Where-Object { $_ -and (Test-Path $_) };" ^
    "function Get-YakuPythonProcs { $targets = @(); foreach ($p in (Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe','pythonw.exe') })) { $exe = $p.ExecutablePath; $cmd = $p.CommandLine; $cwd = $p.WorkingDirectory; $match = $false; foreach ($dir in $pathsToCheck) { if (-not $dir) { continue }; if (($exe -and $exe.StartsWith($dir, [System.StringComparison]::OrdinalIgnoreCase)) -or ($cwd -and $cwd.StartsWith($dir, [System.StringComparison]::OrdinalIgnoreCase)) -or ($cmd -and $cmd.IndexOf($dir, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)) { $match = $true; break } }; if ($match) { $proc = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue; if ($proc) { $targets += $proc } } }; return $targets };" ^
    "$yakuProc = Get-Process -Name 'YakuLingo' -ErrorAction SilentlyContinue;" ^
    "$pyProcs = Get-YakuPythonProcs;" ^
    "if (-not $yakuProc -and (-not $pyProcs -or $pyProcs.Count -eq 0)) { exit 0 };" ^
    "Write-Host '[INFO] Closing running YakuLingo...';" ^
    "$shutdownUrl = 'http://127.0.0.1:8765/api/shutdown';" ^
    "$shutdownRequested = $false;" ^
    "try { Invoke-WebRequest -UseBasicParsing -Method Post -Uri $shutdownUrl -TimeoutSec 8 -Headers @{ 'X-YakuLingo-Exit' = '1' } | Out-Null; $shutdownRequested = $true } catch { };" ^
    "$waitStart = Get-Date;" ^
    "$deadline = $waitStart.AddSeconds(30);" ^
    "$forceKillAttempted = $false;" ^
    "while ((Get-Date) -lt $deadline) { $pyProcs = Get-YakuPythonProcs; $yakuProc = Get-Process -Name 'YakuLingo' -ErrorAction SilentlyContinue; if (-not $yakuProc -and (-not $pyProcs -or $pyProcs.Count -eq 0)) { exit 0 }; $elapsed = [int]((Get-Date) - $waitStart).TotalSeconds; if (-not $shutdownRequested -and $elapsed -ge 5) { try { Invoke-WebRequest -UseBasicParsing -Method Post -Uri $shutdownUrl -TimeoutSec 5 -Headers @{ 'X-YakuLingo-Exit' = '1' } | Out-Null; $shutdownRequested = $true } catch { } }; if (-not $forceKillAttempted -and $elapsed -ge 12) { $forceKillAttempted = $true; $targets = @(); if ($yakuProc) { $targets += $yakuProc }; if ($pyProcs) { $targets += $pyProcs }; if ($targets) { $targets | Stop-Process -Force -ErrorAction SilentlyContinue } }; Start-Sleep -Milliseconds 250 };" ^
    "Write-Host '[ERROR] YakuLingo is still running. Please close it and retry.';" ^
    "exit 1"
if errorlevel 1 (
    echo [ERROR] YakuLingo is still running. Please close it and retry.
    pause
    exit /b 1
)
exit /b 0

:: ============================================================
:: Function: Prompt for proxy credentials
:: ============================================================
:prompt_proxy_credentials
setlocal DisableDelayedExpansion
echo ============================================================
echo Proxy Authentication
echo Server: %PROXY_SERVER%
echo ============================================================
set /p PROXY_USER="Username: "
if not defined PROXY_USER (
    endlocal
    exit /b 0
)

:: Use PowerShell to securely input password (masked)
echo Password (input will be hidden):
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "$p = Read-Host -AsSecureString; if ($p.Length -gt 0) { [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($p)) } else { 'EMPTY_PASSWORD' }"`) do set "PROXY_PASS=%%p"

if not defined PROXY_PASS (
    echo [ERROR] Password input failed.
    endlocal
    exit /b 0
)
if "%PROXY_PASS%"=="EMPTY_PASSWORD" (
    echo [ERROR] Password is required.
    set "PROXY_PASS="
    endlocal
    exit /b 0
)

set "HTTP_PROXY=http://%PROXY_USER%:%PROXY_PASS%@%PROXY_SERVER%"
set "HTTPS_PROXY=http://%PROXY_USER%:%PROXY_PASS%@%PROXY_SERVER%"

:: Escape for delayed expansion (handles ! and ^ in credentials)
set "ESC_PROXY_USER=%PROXY_USER:^=^^%"
set "ESC_PROXY_USER=%ESC_PROXY_USER:!=^!%"
set "ESC_PROXY_PASS=%PROXY_PASS:^=^^%"
set "ESC_PROXY_PASS=%ESC_PROXY_PASS:!=^!%"
set "ESC_HTTP_PROXY=%HTTP_PROXY:^=^^%"
set "ESC_HTTP_PROXY=%ESC_HTTP_PROXY:!=^!%"
set "ESC_HTTPS_PROXY=%HTTPS_PROXY:^=^^%"
set "ESC_HTTPS_PROXY=%ESC_HTTPS_PROXY:!=^!%"

endlocal & (
    set "PROXY_USER=%ESC_PROXY_USER%"
    set "PROXY_PASS=%ESC_PROXY_PASS%"
    set "HTTP_PROXY=%ESC_HTTP_PROXY%"
    set "HTTPS_PROXY=%ESC_HTTPS_PROXY%"
)
echo.
echo [OK] Credentials configured.
exit /b 0
