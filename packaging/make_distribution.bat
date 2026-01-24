@echo off
setlocal enabledelayedexpansion

:: Error trap to ensure pause on unexpected exit
if "%~1"=="--no-trap" goto :no_trap
cmd /c "%~f0" --no-trap %*
if errorlevel 1 (
    echo.
    echo [ERROR] Script terminated unexpectedly.
    pause
)
exit /b %errorlevel%

:no_trap

echo.
echo ============================================================
echo YakuLingo - Distribution Package Builder
echo ============================================================
echo.

cd /d "%~dp0\.."

:: Check if PowerShell is available
where powershell >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PowerShell not found.
    exit /b 1
)

:: Ensure YakuLingo is not running (close it if needed)
set "ROOT_DIR=%CD%"
call :EnsureYakuLingoClosed
if errorlevel 1 exit /b 1

:: Timer start (using PowerShell for accuracy)
for /f %%t in ('powershell -NoProfile -Command "[DateTime]::Now.Ticks"') do set START_TICKS=%%t

:: Progress bar settings
set "PROGRESS_CHARS=##################################################"
set "PROGRESS_EMPTY=.................................................."
set TOTAL_STEPS=3
set CURRENT_STEP=0

:: ============================================================
:: Progress display function
:: ============================================================
goto :SkipFunctions

:ShowProgress
:: %1 = step number, %2 = description
set /a "CURRENT_STEP=%~1"
set /a "PERCENT=CURRENT_STEP*100/TOTAL_STEPS"
set /a "FILLED=PERCENT/2"
set /a "EMPTY=50-FILLED"
set "BAR=!PROGRESS_CHARS:~0,%FILLED%!!PROGRESS_EMPTY:~0,%EMPTY%!"
<nul set /p "=[%BAR%] %PERCENT%%% - %~2                    "
echo.
exit /b 0

:EnsureYakuLingoClosed
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'SilentlyContinue'; $root = [System.IO.Path]::GetFullPath('%ROOT_DIR%'); $installRoot = Join-Path $env:LOCALAPPDATA 'YakuLingo'; $pathsToCheck = @($root, $installRoot) | Where-Object { $_ -and (Test-Path $_) }; $yakuProc = Get-Process -Name 'YakuLingo' -ErrorAction SilentlyContinue; $pyProcs = Get-Process -Name 'python','pythonw' -ErrorAction SilentlyContinue | Where-Object { try { $p = $_.Path } catch { return $false }; if (-not $p) { return $false }; foreach ($dir in $pathsToCheck) { if ($p.StartsWith($dir, [System.StringComparison]::OrdinalIgnoreCase)) { return $true } }; return $false }; if (-not $yakuProc -and -not $pyProcs) { exit 0 }; Write-Host '[INFO] Closing running YakuLingo...'; $shutdownUrl = 'http://127.0.0.1:8765/api/shutdown'; $shutdownRequested = $false; try { Invoke-WebRequest -UseBasicParsing -Method Post -Uri $shutdownUrl -TimeoutSec 8 -Headers @{ 'X-YakuLingo-Exit' = '1' } | Out-Null; $shutdownRequested = $true } catch { }; $waitStart = Get-Date; $deadline = $waitStart.AddSeconds(30); $forceKillAttempted = $false; while ((Get-Date) -lt $deadline) { $pyProcs = Get-Process -Name 'python','pythonw' -ErrorAction SilentlyContinue | Where-Object { try { $p = $_.Path } catch { return $false }; if (-not $p) { return $false }; foreach ($dir in $pathsToCheck) { if ($p.StartsWith($dir, [System.StringComparison]::OrdinalIgnoreCase)) { return $true } }; return $false }; $yakuProc = Get-Process -Name 'YakuLingo' -ErrorAction SilentlyContinue; if (-not $yakuProc -and -not $pyProcs) { exit 0 }; $elapsed = [int]((Get-Date) - $waitStart).TotalSeconds; if (-not $shutdownRequested -and $elapsed -ge 5) { try { Invoke-WebRequest -UseBasicParsing -Method Post -Uri $shutdownUrl -TimeoutSec 5 -Headers @{ 'X-YakuLingo-Exit' = '1' } | Out-Null; $shutdownRequested = $true } catch { } }; if (-not $forceKillAttempted -and $elapsed -ge 12) { $forceKillAttempted = $true; $targets = @(); if ($yakuProc) { $targets += $yakuProc }; if ($pyProcs) { $targets += $pyProcs }; if ($targets) { $targets | Stop-Process -Force -ErrorAction SilentlyContinue } }; Start-Sleep -Milliseconds 250 }; Write-Host '[ERROR] YakuLingo is still running. Please close it and retry.'; exit 1"
if errorlevel 1 exit /b 1
exit /b 0

:SkipFunctions

:: ============================================================
:: Step 1: Prepare (check files, cleanup, fix paths, copy files)
:: ============================================================
call :ShowProgress 0 "Preparing..."

:: Check required files
echo        Checking required files...
set "MISSING="
for %%f in (.venv .uv-python app.py yakulingo YakuLingo.exe prompts config local_ai) do (
    if not exist "%%f" set "MISSING=!MISSING! %%f"
)
if not exist ".venv\pyvenv.cfg" set "MISSING=!MISSING! .venv\pyvenv.cfg"
:: Ensure PDF layout analysis dependencies are bundled (PP-DocLayout-L via PaddleOCR)
if not exist ".venv\Lib\site-packages\paddle" set "MISSING=!MISSING! .venv\Lib\site-packages\paddle(paddlepaddle)"
if not exist ".venv\Lib\site-packages\paddleocr" set "MISSING=!MISSING! .venv\Lib\site-packages\paddleocr"
if not exist "config\settings.template.json" set "MISSING=!MISSING! config\settings.template.json"
if not exist "packaging\installer\share\setup.vbs" set "MISSING=!MISSING! packaging\installer\share\setup.vbs"
if not exist "packaging\installer\share\.scripts\setup.ps1" set "MISSING=!MISSING! packaging\installer\share\.scripts\setup.ps1"
if not exist "packaging\installer\share\README.html" set "MISSING=!MISSING! packaging\installer\share\README.html"
if defined MISSING (
    echo        [ERROR] Missing:!MISSING!
    echo.
    echo [ERROR] Missing required files. Please run install_deps.bat first.
    pause
    exit /b 1
)

:: Check 7-Zip
set "SEVENZIP="
if exist "%ProgramFiles%\7-Zip\7z.exe" set "SEVENZIP=%ProgramFiles%\7-Zip\7z.exe"
if not defined SEVENZIP if exist "%ProgramFiles(x86)%\7-Zip\7z.exe" set "SEVENZIP=%ProgramFiles(x86)%\7-Zip\7z.exe"
if not defined SEVENZIP (
    for /f "delims=" %%p in ('where 7z.exe 2^>nul') do set "SEVENZIP=%%p"
)
if not defined SEVENZIP (
    echo        [ERROR] 7-Zip not found. Please install from https://7-zip.org/
    pause
    exit /b 1
)

:: Prepare: cleanup, fix pyvenv.cfg, get date
echo        Cleaning up and preparing...

:: Delete cache directories (but keep __pycache__ for faster startup)
if exist ".uv-cache" rd /s /q ".uv-cache" 2>nul
if exist ".wheels" rd /s /q ".wheels" 2>nul

:: Delete temp files
del /q "*.tmp" 2>nul
del /q ".venv\pyvenv.cfg.tmp" 2>nul

:: ============================================================
:: Pre-compile Python bytecode for faster first launch
:: This ensures .pyc files are included in the distribution
:: ============================================================
echo        Pre-compiling Python bytecode (parallel)...
:: Compile all site-packages in parallel (-j 0 = use all CPUs)
:: This is critical for fast first launch - compiles all transitive dependencies
:: -x excludes Python 2 legacy files that cause SyntaxError
:: --invalidation-mode=unchecked-hash: Uses hash-based cache that survives ZIP extraction
:: (Without this, mtime changes after ZIP extraction cause full recompilation: 23s -> <100ms)
.venv\Scripts\python.exe -m compileall -q -j 0 --invalidation-mode=unchecked-hash -x "olefile2|test_" .venv\Lib\site-packages 2>nul
.venv\Scripts\python.exe -m compileall -q -j 0 --invalidation-mode=unchecked-hash yakulingo 2>nul
:: Warm up module cache to initialize Python's internal caches
echo        Warming up module cache...
.venv\Scripts\python.exe -c "import nicegui; from nicegui import ui, app, Client, events; import nicegui.elements; import fastapi; import uvicorn; import starlette; import pydantic; import httptools; import anyio; import h11; import watchfiles; import webview; from yakulingo.ui import app; from yakulingo.services import translation_service" 2>nul

:: NOTE: Do NOT modify the local .venv\pyvenv.cfg here (it breaks the developer venv).
:: We patch the copied file in dist_temp after robocopy instead.

:: Get current date (YYYYMMDD format)
for /f %%d in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyyMMdd')"') do set "DIST_DATE=%%d"

set DIST_ZIP=YakuLingo_%DIST_DATE%.zip
set DIST_DIR=dist_temp\YakuLingo
set SHARE_DIR=share_package

:: Remove old distribution and create new structure
if exist "%SHARE_DIR%" rd /s /q "%SHARE_DIR%"
if exist "dist_temp" rd /s /q "dist_temp"
mkdir "%DIST_DIR%"
mkdir "%SHARE_DIR%"

:: Copy individual files
for %%f in ("YakuLingo.exe" "app.py" ".python-version" "glossary.csv" "glossary_old.csv" "pyproject.toml" "uv.lock" "uv.toml" "README.md") do (
    if exist "%%~f" copy /y "%%~f" "%DIST_DIR%\" >nul
)

:: Include README.html inside the ZIP (not alongside it)
copy /y "packaging\installer\share\README.html" "%DIST_DIR%\README.html" >nul
if errorlevel 1 (
    echo        [ERROR] Failed to copy README.html into dist folder.
    pause
    exit /b 1
)

:: ============================================================
:: Step 2: Copy folders (parallel robocopy via PowerShell jobs)
:: ============================================================
call :ShowProgress 1 "Copying folders..."

echo        Copying .venv, .uv-python, yakulingo, prompts, config, local_ai...
set "FIXED_MODEL_GGUF=translategemma-4b-it.i1-Q4_K_S.gguf"

:: Copy folders using robocopy
:: Exit codes: 0=no change, 1=copied, 2-7=warnings, 8+=errors
set "ROBOCOPY_WARNINGS="
set "ROBOCOPY_LOG=%~dp0..\dist_temp\robocopy.log"
echo. > "%ROBOCOPY_LOG%"
for %%f in (.venv .uv-python) do (
    if exist "%%f" (
        echo        Copying %%f...
        echo ============================================================ >> "%ROBOCOPY_LOG%"
        echo Copying: %%f >> "%ROBOCOPY_LOG%"
        echo ============================================================ >> "%ROBOCOPY_LOG%"
        robocopy "%%f" "%DIST_DIR%\%%f" /E /MT:16 /NP /R:1 /W:1 >> "%ROBOCOPY_LOG%" 2>&1
        set "RC=!errorlevel!"
        echo Exit code: !RC! >> "%ROBOCOPY_LOG%"
        echo. >> "%ROBOCOPY_LOG%"
        if !RC! GEQ 8 (
            echo        [ERROR] Failed to copy %%f ^(exit code: !RC!^)
            echo        See log: %ROBOCOPY_LOG%
            type "%ROBOCOPY_LOG%"
            pause
            exit /b 1
        ) else if !RC! GEQ 2 (
            set "ROBOCOPY_WARNINGS=!ROBOCOPY_WARNINGS! %%f"
            echo        [WARNING] Some files skipped in %%f ^(exit code: !RC!^)
        )
    )
)
for %%f in (yakulingo prompts config) do (
    if exist "%%f" (
        echo        Copying %%f...
        echo ============================================================ >> "%ROBOCOPY_LOG%"
        echo Copying: %%f >> "%ROBOCOPY_LOG%"
        echo ============================================================ >> "%ROBOCOPY_LOG%"
        robocopy "%%f" "%DIST_DIR%\%%f" /E /MT:8 /NP /R:1 /W:1 >> "%ROBOCOPY_LOG%" 2>&1
        set "RC=!errorlevel!"
        echo Exit code: !RC! >> "%ROBOCOPY_LOG%"
        echo. >> "%ROBOCOPY_LOG%"
        if !RC! GEQ 8 (
            echo        [ERROR] Failed to copy %%f ^(exit code: !RC!^)
            echo        See log: %ROBOCOPY_LOG%
            type "%ROBOCOPY_LOG%"
            pause
            exit /b 1
        ) else if !RC! GEQ 2 (
            set "ROBOCOPY_WARNINGS=!ROBOCOPY_WARNINGS! %%f"
            echo        [WARNING] Some files skipped in %%f ^(exit code: !RC!^)
        )
    )
)
if exist "local_ai" (
    echo        Copying local_ai ^(excluding extra GGUF models^)...
    echo ============================================================ >> "%ROBOCOPY_LOG%"
    echo Copying: local_ai >> "%ROBOCOPY_LOG%"
    echo ============================================================ >> "%ROBOCOPY_LOG%"
    robocopy "local_ai" "%DIST_DIR%\local_ai" /E /MT:8 /NP /R:1 /W:1 /XF *.gguf* >> "%ROBOCOPY_LOG%" 2>&1
    set "RC=!errorlevel!"
    echo Exit code: !RC! >> "%ROBOCOPY_LOG%"
    echo. >> "%ROBOCOPY_LOG%"
    if !RC! GEQ 8 (
        echo        [ERROR] Failed to copy local_ai ^(exit code: !RC!^)
        echo        See log: %ROBOCOPY_LOG%
        type "%ROBOCOPY_LOG%"
        pause
        exit /b 1
    ) else if !RC! GEQ 2 (
        set "ROBOCOPY_WARNINGS=!ROBOCOPY_WARNINGS! local_ai"
        echo        [WARNING] Some files skipped in local_ai ^(exit code: !RC!^)
    )

    if exist "local_ai\models\%FIXED_MODEL_GGUF%" (
        echo        Copying local_ai\models\%FIXED_MODEL_GGUF%...
        echo ============================================================ >> "%ROBOCOPY_LOG%"
        echo Copying: local_ai\models\%FIXED_MODEL_GGUF% >> "%ROBOCOPY_LOG%"
        echo ============================================================ >> "%ROBOCOPY_LOG%"
        robocopy "local_ai\models" "%DIST_DIR%\local_ai\models" "%FIXED_MODEL_GGUF%" /MT:8 /NP /R:1 /W:1 >> "%ROBOCOPY_LOG%" 2>&1
        set "RC=!errorlevel!"
        echo Exit code: !RC! >> "%ROBOCOPY_LOG%"
        echo. >> "%ROBOCOPY_LOG%"
        if !RC! GEQ 8 (
            echo        [ERROR] Failed to copy fixed model ^(exit code: !RC!^)
            echo        See log: %ROBOCOPY_LOG%
            type "%ROBOCOPY_LOG%"
            pause
            exit /b 1
        ) else if !RC! GEQ 2 (
            set "ROBOCOPY_WARNINGS=!ROBOCOPY_WARNINGS! local_ai\models\%FIXED_MODEL_GGUF%"
            echo        [WARNING] Some files skipped while copying fixed model ^(exit code: !RC!^)
        )
    ) else (
        if exist "local_ai\models\*.gguf*" (
            echo        [ERROR] Found GGUF models in local_ai\models, but fixed model is missing: %FIXED_MODEL_GGUF%
            echo        Remove other models or place the fixed model before building the distribution.
            pause
            exit /b 1
        )
        echo        [WARNING] Fixed model not found: local_ai\models\%FIXED_MODEL_GGUF% ^(no GGUF models will be included^)
    )
)
if defined ROBOCOPY_WARNINGS (
    echo.
    echo        [WARNING] Some files were skipped. Check log for details:
    echo        %ROBOCOPY_LOG%
    echo.
    echo        --- Skipped/Failed files ---
    findstr /C:"FAILED" /C:"Skipped" "%ROBOCOPY_LOG%"
    echo        ----------------------------
)

:: ============================================================
:: Patch dist pyvenv.cfg (relocatable, no dev-machine paths)
:: - Ensure UTF-8 without BOM (Python reads pyvenv.cfg as UTF-8)
:: - Replace "home =" with placeholder (setup.ps1 will rewrite to bundled runtime)
:: ============================================================
echo        Patching dist pyvenv.cfg...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$pyvenv = '%DIST_DIR%\.venv\pyvenv.cfg';" ^
    "if (-not (Test-Path $pyvenv)) { Write-Host ('[ERROR] pyvenv.cfg not found: ' + $pyvenv); exit 1 };" ^
    "$utf8NoBom = New-Object System.Text.UTF8Encoding $false;" ^
    "$lines = [System.IO.File]::ReadAllLines($pyvenv, $utf8NoBom);" ^
    "$updated = $false;" ^
    "$newLines = foreach ($line in $lines) { if ($line -match '^\\s*home\\s*=') { $updated = $true; 'home = __PYTHON_HOME__' } else { $line } };" ^
    "if (-not $updated) { $newLines = @('home = __PYTHON_HOME__') + $newLines };" ^
    "[System.IO.File]::WriteAllLines($pyvenv, $newLines, $utf8NoBom)"
if errorlevel 1 (
    echo        [ERROR] Failed to patch dist pyvenv.cfg.
    pause
    exit /b 1
)

:: ============================================================
:: Step 3: Create ZIP and finalize
:: ============================================================
call :ShowProgress 2 "Creating ZIP and finalizing..."

:: Create ZIP archive (flat structure - no parent folder)
echo        Creating ZIP archive...
pushd dist_temp\YakuLingo
"%SEVENZIP%" a -tzip -mx=1 -mmt=on -bsp1 "..\..\%SHARE_DIR%\%DIST_ZIP%" * >nul
set "ZIP_RC=!errorlevel!"
popd
if not "%ZIP_RC%"=="0" (
    echo        [ERROR] 7-Zip failed with exit code: %ZIP_RC%
    pause
    exit /b 1
)

:: Copy installer files and cleanup in parallel
echo        Copying installer files...
copy /y "packaging\installer\share\setup.vbs" "%SHARE_DIR%\" >nul
xcopy /E /I /Q /Y "packaging\installer\share\.scripts" "%SHARE_DIR%\.scripts" >nul

:: Move log to share_package before cleanup
if exist "%ROBOCOPY_LOG%" (
    move /y "%ROBOCOPY_LOG%" "%SHARE_DIR%\robocopy.log" >nul
    echo        Log saved to: %SHARE_DIR%\robocopy.log
)

rd /s /q "dist_temp" 2>nul

:: Remove local __pycache__ created by compileall (exclude venv and output folders)
echo        Cleaning local __pycache__...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$excludePattern = '\\\\.venv\\\\|\\\\dist_temp\\\\|\\\\share_package\\\\|\\\\\\.uv-cache\\\\|\\\\\\.uv-python\\\\';" ^
    "Get-ChildItem -Path . -Directory -Filter '__pycache__' -Recurse -Force -ErrorAction SilentlyContinue |" ^
    "Where-Object { $_.FullName -notmatch $excludePattern } |" ^
    "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"

:: Calculate elapsed time using PowerShell ticks
for /f %%e in ('powershell -NoProfile -Command "$e=([DateTime]::Now.Ticks-%START_TICKS%)/10000000;$m=[math]::Floor($e/60);$s=[math]::Floor($e%%60);if($m-gt0){\"${m}m ${s}s\"}else{\"${s}s\"}"') do set "ELAPSED_TIME=%%e"

call :ShowProgress 3 "Complete!"

set "ZIP_PATH=%SHARE_DIR%\%DIST_ZIP%"
if exist "%ZIP_PATH%" (
    for %%A in ("%ZIP_PATH%") do set "ZIP_SIZE=%%~zA"
    if "!ZIP_SIZE!"=="0" (
        echo [ERROR] ZIP file is empty: %ZIP_PATH%
        pause
        exit /b 1
    )
    echo.
    echo ============================================================
    echo [SUCCESS] Distribution package created!
    echo.
    echo   Folder: %SHARE_DIR%\
    echo     - setup.vbs    ^<-- Users run this
    echo     - %DIST_ZIP%   ^<-- contains README.html
    echo.
    for %%A in ("%ZIP_PATH%") do echo   Size: %%~zA bytes
    echo   Time: %ELAPSED_TIME%
    echo.
    echo Deploy the contents of "%SHARE_DIR%" to your network share.
    echo ============================================================
) else (
    echo [ERROR] Failed to create distribution package.
    pause
    exit /b 1
)

echo.
pause
endlocal
exit /b 0
