@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo YakuLingo - Distribution Package Builder
echo ============================================================
echo.

cd /d "%~dp0"

:: ============================================================
:: Step 1: Check required files exist
:: ============================================================
echo [1/5] Checking required files...

set MISSING_FILES=0

if not exist ".venv" (
    echo [ERROR] .venv directory not found. Run install_deps.bat first.
    set MISSING_FILES=1
)
if not exist ".uv-python" (
    echo [ERROR] .uv-python directory not found. Run install_deps.bat first.
    set MISSING_FILES=1
)
if not exist ".playwright-browsers" (
    echo [ERROR] .playwright-browsers directory not found. Run install_deps.bat first.
    set MISSING_FILES=1
)
if not exist "app.py" (
    echo [ERROR] app.py not found.
    set MISSING_FILES=1
)
if not exist "yakulingo" (
    echo [ERROR] yakulingo directory not found.
    set MISSING_FILES=1
)

if !MISSING_FILES! equ 1 (
    echo.
    echo [ERROR] Missing required files. Please run install_deps.bat first.
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
if exist "yakulingo_settings.json" (
    echo [INFO] Backing up yakulingo_settings.json to yakulingo_settings.json.bak
    copy /y "yakulingo_settings.json" "yakulingo_settings.json.bak" >nul
    del /q "yakulingo_settings.json"
)

:: Remove any log files
del /q "*.log" 2>nul

echo [OK] User-specific files removed.

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
echo [INFO] Creating folder structure...
mkdir "%DIST_DIR%" 2>nul

:: Copy files to distribution folder
echo   Copying files...
for %%f in ("run.bat" "app.py" "glossary.csv" "pyproject.toml" "uv.lock" "uv.toml" "README.md") do (
    if exist "%%~f" copy /y "%%~f" "%DIST_DIR%\" >nul
)

:: Copy folders to distribution
for %%d in (".venv" ".uv-python" ".playwright-browsers" "yakulingo" "prompts" "config") do (
    if exist "%%~d" (
        echo   Copying: %%~d ...
        xcopy /s /e /i /q "%%~d" "%DIST_DIR%\%%~d" >nul
    )
)

:: Create ZIP archive
echo [INFO] Creating distribution archive...
cd dist_temp
tar -a -cf "..\%DIST_ZIP%" YakuLingo 2>nul
cd ..

:: Cleanup temp folder
rd /s /q "dist_temp" 2>nul

if exist "%DIST_ZIP%" (
    echo.
    echo ============================================================
    echo [SUCCESS] Distribution package created!
    echo.
    echo   File: %DIST_ZIP%
    for %%A in ("%DIST_ZIP%") do echo   Size: %%~zA bytes
    echo.
    echo Structure:
    echo   YakuLingo/
    echo     run.bat            ^<-- Application launcher
    echo     app.py, yakulingo/, ...
    echo.
    echo ============================================================
    echo.
    echo Creating share folder package...
    echo.

    :: Create share folder with network installer
    set SHARE_DIR=share_package
    if exist "%SHARE_DIR%" rd /s /q "%SHARE_DIR%"
    mkdir "%SHARE_DIR%"

    :: Copy ZIP and installer files
    copy /y "%DIST_ZIP%" "%SHARE_DIR%\" >nul
    copy /y "installer\share\setup.bat" "%SHARE_DIR%\" >nul
    copy /y "installer\share\README.txt" "%SHARE_DIR%\" >nul
    xcopy /s /e /i /q "installer\share\.scripts" "%SHARE_DIR%\.scripts" >nul

    echo [SUCCESS] Share folder package created!
    echo.
    echo   Folder: %SHARE_DIR%\
    echo     - setup.bat    ^<-- Users run this
    echo     - %DIST_ZIP%
    echo     - README.txt
    echo.
    echo Deploy the contents of "%SHARE_DIR%" to your network share.
    echo ============================================================
) else (
    echo [ERROR] Failed to create distribution package.
    pause
    exit /b 1
)

:: Restore config backup if exists
if exist "yakulingo_settings.json.bak" (
    move /y "yakulingo_settings.json.bak" "yakulingo_settings.json" >nul
)

echo.
pause
endlocal
exit /b 0
