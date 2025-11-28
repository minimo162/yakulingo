@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo Excel Translation Tool - Distribution Package Builder
echo ============================================================
echo.

cd /d "%~dp0"

:: ============================================================
:: Step 1: Check required files exist
:: ============================================================
echo [1/5] Checking required files...

set MISSING_FILES=0

if not exist ".venv" (
    echo [ERROR] .venv directory not found. Run setup.bat first.
    set MISSING_FILES=1
)
if not exist ".uv-python" (
    echo [ERROR] .uv-python directory not found. Run setup.bat first.
    set MISSING_FILES=1
)
if not exist ".playwright-browsers" (
    echo [ERROR] .playwright-browsers directory not found. Run setup.bat first.
    set MISSING_FILES=1
)
if not exist "translate.py" (
    echo [ERROR] translate.py not found.
    set MISSING_FILES=1
)

if !MISSING_FILES! equ 1 (
    echo.
    echo [ERROR] Missing required files. Please run setup.bat first.
    pause
    exit /b 1
)
echo [OK] All required files found.

:: ============================================================
:: Step 2: Clean up unnecessary files
:: ============================================================
echo.
echo [2/5] Cleaning up unnecessary files...

:: Remove Python cache files
for /r ".venv" %%f in (*.pyc) do del /q "%%f" 2>nul
for /r ".venv" %%d in (__pycache__) do rd /s /q "%%d" 2>nul
for /r "." %%d in (__pycache__) do rd /s /q "%%d" 2>nul

:: Remove uv cache (not needed for distribution)
if exist ".uv-cache" rd /s /q ".uv-cache" 2>nul

:: Remove wheels directory (already installed)
if exist ".wheels" rd /s /q ".wheels" 2>nul

:: Remove any temporary files
del /q "*.tmp" 2>nul
del /q ".venv\pyvenv.cfg.tmp" 2>nul

echo [OK] Cleanup completed.

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

:: Rewrite pyvenv.cfg with placeholder (will be fixed by run.bat on first run)
echo home = __PYTHON_HOME__> ".venv\pyvenv.cfg"
echo include-system-site-packages = false>> ".venv\pyvenv.cfg"
echo version =%PYTHON_VERSION%>> ".venv\pyvenv.cfg"

echo [OK] Paths fixed for portability.

:: ============================================================
:: Step 4: Remove user-specific files
:: ============================================================
echo.
echo [4/5] Removing user-specific files...

:: Remove config file (users should configure their own)
if exist "translation_config.json" (
    echo [INFO] Backing up translation_config.json to translation_config.json.bak
    copy /y "translation_config.json" "translation_config.json.bak" >nul
    del /q "translation_config.json"
)

:: Remove any log files
del /q "*.log" 2>nul

echo [OK] User-specific files removed.

:: ============================================================
:: Step 5: Create distribution package
:: ============================================================
echo.
echo [5/5] Creating distribution package...

:: Get current date for filename
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /format:list') do set datetime=%%I
set DIST_DATE=%datetime:~0,8%

set DIST_NAME=ExcelTranslator_%DIST_DATE%
set DIST_ZIP=%DIST_NAME%.zip

:: Remove old distribution if exists
if exist "%DIST_ZIP%" del /q "%DIST_ZIP%"

:: Create file list for distribution
echo [INFO] Creating distribution archive...

:: Use PowerShell to create zip (more reliable than tar)
powershell -ExecutionPolicy Bypass -Command ^
    "$files = @(" ^
    "    '.venv'," ^
    "    '.uv-python'," ^
    "    '.playwright-browsers'," ^
    "    'translate.py'," ^
    "    'ui.py'," ^
    "    'config_manager.py'," ^
    "    'pyproject.toml'," ^
    "    'uv.lock'," ^
    "    '★run.bat'," ^
    "    'README.md'," ^
    "    'DISTRIBUTION.md'" ^
    "); " ^
    "$existingFiles = $files | Where-Object { Test-Path $_ }; " ^
    "Compress-Archive -Path $existingFiles -DestinationPath '%DIST_ZIP%' -Force"

if exist "%DIST_ZIP%" (
    echo.
    echo ============================================================
    echo [SUCCESS] Distribution package created!
    echo.
    echo   File: %DIST_ZIP%
    for %%A in ("%DIST_ZIP%") do echo   Size: %%~zA bytes
    echo.
    echo Instructions for users:
    echo   1. Extract the zip file to any location
    echo   2. Double-click "★run.bat" to start
    echo ============================================================
) else (
    echo [ERROR] Failed to create distribution package.
    pause
    exit /b 1
)

:: Restore config backup if exists
if exist "translation_config.json.bak" (
    move /y "translation_config.json.bak" "translation_config.json" >nul
)

echo.
pause
endlocal
exit /b 0
