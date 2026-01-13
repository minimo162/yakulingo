@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: Step 7 extracted from packaging/install_deps.bat
:: - Must never terminate the parent installer window
:: - Always return via exit /b

cd /d "%~dp0\.."

if not defined USE_PROXY set "USE_PROXY=0"
if not defined SKIP_SSL set "SKIP_SSL=0"

echo.
echo [7/7] Installing Local AI runtime (llama.cpp + optional model)...
echo [INFO] This step may download large files (model may be a few GB).

echo.
echo Do you want to install Local AI runtime now?
echo   [1] Yes - Download llama.cpp + Nemotron-Flash-3B-Instruct model (build 4bit; very large download)
echo   [2] Yes - Download llama.cpp only (default; add model later)
echo   [3] No  - Skip this step
echo.
set /p LOCAL_AI_CHOICE="Enter choice (1, 2, or 3) [2]: "
for /f "tokens=1" %%A in ("!LOCAL_AI_CHOICE!") do set "LOCAL_AI_CHOICE=%%A"
if not defined LOCAL_AI_CHOICE set "LOCAL_AI_CHOICE=2"
if not "!LOCAL_AI_CHOICE!"=="1" if not "!LOCAL_AI_CHOICE!"=="2" if not "!LOCAL_AI_CHOICE!"=="3" (
    echo [WARNING] Invalid choice "!LOCAL_AI_CHOICE!". Defaulting to [2] (llama.cpp only).
    set "LOCAL_AI_CHOICE=2"
)

if "!LOCAL_AI_CHOICE!"=="3" (
    echo [7/7] SKIP - Local AI runtime installation skipped.
    goto :local_ai_done
)

set "LOCAL_AI_SKIP_MODEL=0"
if "!LOCAL_AI_CHOICE!"=="2" set "LOCAL_AI_SKIP_MODEL=1"

echo [INFO] Step 7 selection: choice=!LOCAL_AI_CHOICE! (LOCAL_AI_SKIP_MODEL=!LOCAL_AI_SKIP_MODEL!)
if exist "local_ai\\manifest.json" (
    echo [INFO] Local AI manifest: exists (local_ai\manifest.json)
) else (
    echo [INFO] Local AI manifest: not found (new install defaults will be applied)
)
if "!USE_PROXY!"=="1" (
    echo [INFO] Proxy: enabled (USE_PROXY=1)
) else (
    echo [INFO] Proxy: disabled (USE_PROXY=0)
)
if "!SKIP_SSL!"=="1" (
    echo [WARNING] SSL verification is disabled (SKIP_SSL=1).
)

:: Ensure local endpoints are not proxied (keep existing entries)
if not defined NO_PROXY set "NO_PROXY=127.0.0.1,localhost"
echo(!NO_PROXY!| findstr /i /l /c:"127.0.0.1" >nul || set "NO_PROXY=!NO_PROXY!,127.0.0.1"
echo(!NO_PROXY!| findstr /i /l /c:"localhost" >nul || set "NO_PROXY=!NO_PROXY!,localhost"
set "no_proxy=!NO_PROXY!"

if not exist "local_ai\\manifest.json" (
    if "!LOCAL_AI_SKIP_MODEL!"=="1" (
        echo [INFO] Local AI model: SKIP (LOCAL_AI_SKIP_MODEL=1)
    ) else (
        if not defined LOCAL_AI_MODEL_KIND set "LOCAL_AI_MODEL_KIND=hf"
        if not defined LOCAL_AI_MODEL_REPO set "LOCAL_AI_MODEL_REPO=nvidia/Nemotron-Flash-3B-Instruct"
        if not defined LOCAL_AI_MODEL_QUANT set "LOCAL_AI_MODEL_QUANT=Q4_K_M"
        if not defined LOCAL_AI_MODEL_BASE_NAME set "LOCAL_AI_MODEL_BASE_NAME=Nemotron-Flash-3B-Instruct"
        echo [INFO] Local AI model: Nemotron-Flash-3B-Instruct (LOCAL_AI_MODEL_KIND=!LOCAL_AI_MODEL_KIND!, quant=!LOCAL_AI_MODEL_QUANT!)
        echo [INFO] NOTE: HF^>GGUF^>4bit may require extra Python deps and can take a long time.
    )
)

if not exist "local_ai\\manifest.json" (
    if "!LOCAL_AI_SKIP_MODEL!"=="1" (
        echo [INFO] You can add a model later via LOCAL_AI_MODEL_KIND=gguf/hf and rerun: powershell -NoProfile -ExecutionPolicy Bypass -File packaging\install_local_ai.ps1
    )
)

if /i "!LOCAL_AI_MODEL_KIND!"=="hf" (
    if "!LOCAL_AI_SKIP_MODEL!"=="0" (
        call :ensure_hf_deps
    )
)

if not defined LOCAL_AI_LLAMA_CPP_VARIANT (
    if not exist "local_ai\\manifest.json" (
        set "LOCAL_AI_LLAMA_CPP_VARIANT=vulkan"
        echo [INFO] llama.cpp variant: !LOCAL_AI_LLAMA_CPP_VARIANT! ^(default for new install^)
    ) else (
        echo [INFO] llama.cpp variant: manifest.json ^(set LOCAL_AI_LLAMA_CPP_VARIANT to override^)
    )
) else (
    echo [INFO] llama.cpp variant: !LOCAL_AI_LLAMA_CPP_VARIANT! ^(env override^)
)

powershell -NoProfile -ExecutionPolicy Bypass -File "packaging\install_local_ai.ps1"
set LOCAL_AI_INSTALL_EXIT=!errorlevel!
if !LOCAL_AI_INSTALL_EXIT! neq 0 (
    echo [WARNING] Failed to install Local AI runtime ^(optional^) (exit=!LOCAL_AI_INSTALL_EXIT!).
    echo [INFO] Copilot translation will still work.
    echo [INFO] You can retry later: powershell -NoProfile -ExecutionPolicy Bypass -File packaging\install_local_ai.ps1
    echo [INFO] If HF build failed, you can switch to GGUF download: set LOCAL_AI_MODEL_KIND=gguf (and set LOCAL_AI_MODEL_REPO/FILE), or choose option [2] (llama.cpp only).
    echo [INFO] Or manually place files under local_ai\ ^(llama_cpp + models^).
) else (
    echo [DONE] Local AI runtime installation finished successfully.
)

:local_ai_done
endlocal
exit /b 0

:: ============================================================
:: Function: Ensure HF deps are available (huggingface_hub)
:: ============================================================
:ensure_hf_deps
echo [INFO] Ensuring HF dependencies (for HF^>GGUF^>4bit)...
if not exist ".venv\Scripts\python.exe" (
    echo [WARNING] .venv\Scripts\python.exe not found. Cannot install HF deps.
    exit /b 0
)
.venv\Scripts\python.exe -c "import huggingface_hub" >nul 2>&1
if errorlevel 1 (
    echo [INFO] huggingface_hub is missing.
)

set "HF_MISSING="
for %%P in (huggingface_hub torch transformers sentencepiece safetensors) do (
    .venv\Scripts\python.exe -c "import %%P" >nul 2>&1
    if errorlevel 1 (
        if not defined HF_MISSING (
            set "HF_MISSING=%%P"
        ) else (
            set "HF_MISSING=!HF_MISSING! %%P"
        )
    )
)
if not defined HF_MISSING (
    echo [DONE] HF build dependencies already available.
    exit /b 0
)

echo [INFO] Installing HF build dependencies: !HF_MISSING!
.venv\Scripts\python.exe -m pip --version >nul 2>&1
if errorlevel 1 (
    .venv\Scripts\python.exe -m ensurepip --upgrade
)
if "!SKIP_SSL!"=="1" (
    .venv\Scripts\python.exe -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -U !HF_MISSING!
) else (
    .venv\Scripts\python.exe -m pip install -U !HF_MISSING!
)
.venv\Scripts\python.exe -c "import huggingface_hub; print('ok')" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Required HF deps are still missing. HF^>GGUF^>4bit may fail.
    echo [INFO] You can retry later: .venv\Scripts\python.exe -m pip install -U !HF_MISSING!
    echo [INFO] Or switch to GGUF download: set LOCAL_AI_MODEL_KIND=gguf
) else (
    echo [DONE] HF build dependencies installed.
)
exit /b 0

