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

:: ============================================================
:: Step 1: Check required files exist
:: ============================================================
echo [1/5] Checking required files...

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

if !MISSING_FILES! equ 1 (
    echo.
    echo [ERROR] Missing required files. Please run install_deps.bat first.
    pause
    exit /b 1
)
echo        [OK] All required files found.

:: ============================================================
:: Step 2: Clean up unnecessary files
:: ============================================================
echo.
echo [2/5] Cleaning up unnecessary files...

:: Use PowerShell for fast parallel cleanup
echo        Removing __pycache__ and .pyc files...
powershell -NoProfile -Command "Get-ChildItem -Path '.venv','yakulingo' -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Get-ChildItem -Path '.venv' -Recurse -Filter '*.pyc' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue"

:: Remove uv cache (not needed for distribution)
echo        Removing cache directories...
if exist ".uv-cache" rd /s /q ".uv-cache" 2>nul
if exist ".wheels" rd /s /q ".wheels" 2>nul

:: Remove any temporary files
del /q "*.tmp" 2>nul
del /q ".venv\pyvenv.cfg.tmp" 2>nul

echo        [OK] Cleanup completed.

:: ============================================================
:: Step 3: Fix paths for portability
:: ============================================================
echo.
echo [3/5] Fixing paths for portability...

:: Find Python directory
set PYTHON_DIR=
for /d %%d in (".uv-python\cpython-*") do (
    set PYTHON_DIR=%%d
)

:: Get Python version from pyvenv.cfg
set PYTHON_VERSION=
for /f "tokens=2 delims==" %%v in ('type ".venv\pyvenv.cfg" ^| findstr /i "^version"') do (
    set PYTHON_VERSION=%%v
)

:: Rewrite pyvenv.cfg with placeholder (will be fixed by YakuLingo.exe on first run)
echo home = __PYTHON_HOME__> ".venv\pyvenv.cfg"
echo include-system-site-packages = false>> ".venv\pyvenv.cfg"
echo version =%PYTHON_VERSION%>> ".venv\pyvenv.cfg"

echo        [OK] Paths fixed for portability.

:: ============================================================
:: Step 4: Remove user-specific files
:: ============================================================
echo.
echo [4/5] Removing user-specific files...

:: Remove any log files
del /q "*.log" 2>nul

echo        [OK] User-specific files removed.

:: ============================================================
:: Step 5: Create distribution package with _internal structure
:: ============================================================
echo.
echo [5/5] Creating distribution package...

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
echo        Creating folder structure...
mkdir "%DIST_DIR%" 2>nul

:: Copy files to distribution folder
echo        [5a/5e] Copying individual files...
for %%f in ("YakuLingo.exe" "app.py" "glossary.csv" "pyproject.toml" "uv.lock" "uv.toml" "README.md") do (
    if exist "%%~f" copy /y "%%~f" "%DIST_DIR%\" >nul
)

:: Copy folders using robocopy (faster with /MT for multi-threading)
:: /E = include empty dirs, /MT:8 = 8 threads, /NFL /NDL /NJH /NJS = minimal output
echo        [5b/5e] Copying .venv (Python environment)...
robocopy ".venv" "%DIST_DIR%\.venv" /E /MT:8 /NFL /NDL /NJH /NJS /R:1 /W:1 >nul 2>&1

echo        [5c/5e] Copying .uv-python (Python runtime)...
robocopy ".uv-python" "%DIST_DIR%\.uv-python" /E /MT:8 /NFL /NDL /NJH /NJS /R:1 /W:1 >nul 2>&1

echo        [5d/5e] Copying .playwright-browsers (Chromium)...
robocopy ".playwright-browsers" "%DIST_DIR%\.playwright-browsers" /E /MT:8 /NFL /NDL /NJH /NJS /R:1 /W:1 >nul 2>&1

echo        [5e/5e] Copying application files...
for %%d in ("yakulingo" "prompts" "config") do (
    if exist "%%~d" robocopy "%%~d" "%DIST_DIR%\%%~d" /E /MT:8 /NFL /NDL /NJH /NJS /R:1 /W:1 >nul 2>&1
)

:: Create ZIP archive using .NET ZipFile (faster than Compress-Archive)
echo        Creating ZIP archive...
powershell -NoProfile -Command "Add-Type -Assembly 'System.IO.Compression.FileSystem'; [System.IO.Compression.ZipFile]::CreateFromDirectory('dist_temp\YakuLingo', '%DIST_ZIP%', [System.IO.Compression.CompressionLevel]::Fastest, $false)"

:: Cleanup temp folder
echo        Cleaning up...
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
