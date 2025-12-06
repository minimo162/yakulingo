@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo YakuLingo - Distribution Package Builder
echo ============================================================
echo.

cd /d "%~dp0\.."

:: Timer start
set START_TIME=%TIME%

:: Progress bar settings
set "PROGRESS_CHARS=##################################################"
set "PROGRESS_EMPTY=.................................................."
set TOTAL_STEPS=4
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

:SkipFunctions

:: ============================================================
:: Step 1: Prepare (check files, cleanup, fix paths)
:: ============================================================
call :ShowProgress 1 "Preparing..."

echo        Checking required files...

set MISSING_FILES=0

if not exist ".venv" (
    echo        [ERROR] .venv directory not found. Run install_deps.bat first.
    set MISSING_FILES=1
)
if not exist ".uv-python" (
    echo        [ERROR] .uv-python directory not found. Run install_deps.bat first.
    set MISSING_FILES=1
)
if not exist ".playwright-browsers" (
    echo        [ERROR] .playwright-browsers directory not found. Run install_deps.bat first.
    set MISSING_FILES=1
)
if not exist "app.py" (
    echo        [ERROR] app.py not found.
    set MISSING_FILES=1
)
if not exist "yakulingo" (
    echo        [ERROR] yakulingo directory not found.
    set MISSING_FILES=1
)
if not exist "YakuLingo.exe" (
    echo        [ERROR] YakuLingo.exe not found. Build the launcher first.
    set MISSING_FILES=1
)
if not exist "prompts" (
    echo        [ERROR] prompts directory not found.
    set MISSING_FILES=1
)

if !MISSING_FILES! equ 1 (
    echo.
    echo [ERROR] Missing required files. Please run install_deps.bat first.
    pause
    exit /b 1
)

:: Clean up unnecessary files
echo        Cleaning up cache files...
powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; Get-ChildItem -Path '.venv','yakulingo' -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force; Get-ChildItem -Path '.venv' -Recurse -Filter '*.pyc' | Remove-Item -Force; Remove-Item -Path '.uv-cache','.wheels' -Recurse -Force; Remove-Item -Path '*.tmp','.venv\pyvenv.cfg.tmp' -Force"

:: Fix paths for portability
echo        Fixing paths for portability...

:: Get Python version from pyvenv.cfg
set PYTHON_VERSION=
for /f "tokens=2 delims==" %%v in ('type ".venv\pyvenv.cfg" ^| findstr /i "^version"') do (
    set PYTHON_VERSION=%%v
)

:: Rewrite pyvenv.cfg with placeholder (will be fixed by YakuLingo.exe on first run)
(
    echo home = __PYTHON_HOME__
    echo include-system-site-packages = false
    echo version =%PYTHON_VERSION%
) > ".venv\pyvenv.cfg"

:: Prepare distribution folder
echo        Preparing distribution folder...

:: Get current date for filename
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /format:list') do set datetime=%%I
set DIST_DATE=%datetime:~0,8%

set DIST_NAME=YakuLingo_%DIST_DATE%
set DIST_ZIP=%DIST_NAME%.zip
set DIST_DIR=dist_temp\YakuLingo

:: Remove old distribution if exists
if exist "%DIST_ZIP%" del /q "%DIST_ZIP%"
if exist "dist_temp" rd /s /q "dist_temp"

:: Create distribution folder structure
mkdir "%DIST_DIR%" 2>nul

:: Copy individual files (fast)
for %%f in ("YakuLingo.exe" "app.py" "glossary.csv" "pyproject.toml" "uv.lock" "uv.toml" "README.md") do (
    if exist "%%~f" copy /y "%%~f" "%DIST_DIR%\" >nul
)

:: ============================================================
:: Step 2: Copy folders
:: ============================================================
call :ShowProgress 2 "Copying folders..."

echo        Copying .venv, .uv-python, .playwright-browsers...

:: Start all robocopy operations in parallel
start /B "" robocopy ".venv" "%DIST_DIR%\.venv" /E /MT:16 /NFL /NDL /NJH /NJS /NP /R:1 /W:1 >nul 2>&1
start /B "" robocopy ".uv-python" "%DIST_DIR%\.uv-python" /E /MT:16 /NFL /NDL /NJH /NJS /NP /R:1 /W:1 >nul 2>&1
start /B "" robocopy ".playwright-browsers" "%DIST_DIR%\.playwright-browsers" /E /MT:16 /NFL /NDL /NJH /NJS /NP /R:1 /W:1 >nul 2>&1

:: Wait for parallel robocopy operations to complete
:WaitLoop1
tasklist /FI "IMAGENAME eq robocopy.exe" 2>nul | find /I "robocopy.exe" >nul
if !errorlevel! equ 0 (
    timeout /t 1 /nobreak >nul
    goto :WaitLoop1
)

:: Copy smaller folders (fast, don't need parallel)
echo        Copying yakulingo, prompts, config...
for %%d in ("yakulingo" "prompts" "config") do (
    if exist "%%~d" robocopy "%%~d" "%DIST_DIR%\%%~d" /E /MT:8 /NFL /NDL /NJH /NJS /NP /R:1 /W:1 >nul 2>&1
)

:: ============================================================
:: Step 3: Create ZIP archive (this takes the longest time)
:: ============================================================
call :ShowProgress 3 "Creating ZIP archive..."

:: Try 7-Zip first (much faster with multi-threading)
set "SEVENZIP="
if exist "%ProgramFiles%\7-Zip\7z.exe" set "SEVENZIP=%ProgramFiles%\7-Zip\7z.exe"
if exist "%ProgramFiles(x86)%\7-Zip\7z.exe" set "SEVENZIP=%ProgramFiles(x86)%\7-Zip\7z.exe"

if defined SEVENZIP (
    echo        Using 7-Zip ^(multi-threaded^)...
    pushd dist_temp
    "%SEVENZIP%" a -tzip -mx=1 -mmt=on -bsp1 "..\%DIST_ZIP%" YakuLingo >nul
    popd
) else (
    echo.
    echo        7-Zip not found. Using PowerShell ^(slower^)...
    echo        Install 7-Zip for faster builds: https://7-zip.org/
    echo.
    powershell -NoProfile -Command ^
        "$ErrorActionPreference = 'Stop'; " ^
        "Add-Type -Assembly 'System.IO.Compression.FileSystem'; " ^
        "$srcPath = (Resolve-Path 'dist_temp\YakuLingo').Path; " ^
        "$zipPath = (Resolve-Path '.').Path + '\%DIST_ZIP%'; " ^
        "$files = Get-ChildItem -Path $srcPath -Recurse -File; " ^
        "$total = $files.Count; " ^
        "$i = 0; " ^
        "$zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create'); " ^
        "try { " ^
        "    foreach ($file in $files) { " ^
        "        $i++; " ^
        "        $relPath = $file.FullName.Substring($srcPath.Length + 1); " ^
        "        $entry = $zip.CreateEntry('YakuLingo/' + $relPath.Replace('\', '/'), 'Fastest'); " ^
        "        $stream = $entry.Open(); " ^
        "        $fileStream = [System.IO.File]::OpenRead($file.FullName); " ^
        "        $fileStream.CopyTo($stream); " ^
        "        $fileStream.Close(); " ^
        "        $stream.Close(); " ^
        "        if ($i %% 200 -eq 0) { " ^
        "            $pct = [int]($i * 100 / $total); " ^
        "            Write-Host \"`r        [$pct%%] $i / $total files\" -NoNewline; " ^
        "        } " ^
        "    } " ^
        "    Write-Host \"`r        [100%%] $total / $total files    \"; " ^
        "} finally { " ^
        "    $zip.Dispose(); " ^
        "}"
)

:: ============================================================
:: Step 4: Cleanup and create share package
:: ============================================================
call :ShowProgress 4 "Finalizing..."

:: Cleanup temp folder
rd /s /q "dist_temp" 2>nul

:: Calculate elapsed time
set END_TIME=%TIME%
call :CalcElapsed "%START_TIME%" "%END_TIME%"

if exist "%DIST_ZIP%" (
    echo.
    echo ============================================================
    echo [SUCCESS] Distribution package created!
    echo.
    echo   File: %DIST_ZIP%
    for %%A in ("%DIST_ZIP%") do echo   Size: %%~zA bytes
    echo   Time: %ELAPSED_TIME%
    echo.
    echo ============================================================
    echo.
    echo Creating share folder package...

    :: Create share folder with network installer
    set SHARE_DIR=share_package
    if exist "!SHARE_DIR!" rd /s /q "!SHARE_DIR!"
    mkdir "!SHARE_DIR!"

    :: Copy ZIP and installer files
    copy /y "!DIST_ZIP!" "!SHARE_DIR!\" >nul
    copy /y "packaging\installer\share\setup.vbs" "!SHARE_DIR!\" >nul
    copy /y "packaging\installer\share\README.txt" "!SHARE_DIR!\" >nul
    robocopy "packaging\installer\share\.scripts" "!SHARE_DIR!\.scripts" /E /NFL /NDL /NJH /NJS >nul 2>&1

    echo.
    echo [SUCCESS] Share folder package created!
    echo.
    echo   Folder: !SHARE_DIR!\
    echo     - setup.vbs    ^<-- Users run this
    echo     - !DIST_ZIP!
    echo     - README.txt
    echo.
    echo Deploy the contents of "!SHARE_DIR!" to your network share.
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

:: ============================================================
:: Subroutine: Calculate elapsed time
:: ============================================================
:CalcElapsed
set "start=%~1"
set "end=%~2"

:: Parse start time
for /f "tokens=1-4 delims=:." %%a in ("%start%") do (
    set /a "start_h=%%a, start_m=1%%b-100, start_s=1%%c-100, start_ms=1%%d-100"
)

:: Parse end time
for /f "tokens=1-4 delims=:." %%a in ("%end%") do (
    set /a "end_h=%%a, end_m=1%%b-100, end_s=1%%c-100, end_ms=1%%d-100"
)

:: Calculate total seconds
set /a "start_total=start_h*3600 + start_m*60 + start_s"
set /a "end_total=end_h*3600 + end_m*60 + end_s"
set /a "elapsed=end_total - start_total"

:: Handle negative (crossed midnight)
if %elapsed% lss 0 set /a "elapsed+=86400"

:: Format output
set /a "elapsed_m=elapsed/60"
set /a "elapsed_s=elapsed%%60"
if %elapsed_m% gtr 0 (
    set "ELAPSED_TIME=%elapsed_m%m %elapsed_s%s"
) else (
    set "ELAPSED_TIME=%elapsed_s%s"
)
exit /b 0
