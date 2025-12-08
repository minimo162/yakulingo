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

:SkipFunctions

:: ============================================================
:: Step 1: Prepare (check files, cleanup, fix paths, copy files)
:: ============================================================
call :ShowProgress 0 "Preparing..."

:: Check required files
echo        Checking required files...
set "MISSING="
for %%f in (.venv .uv-python .playwright-browsers app.py yakulingo YakuLingo.exe prompts) do (
    if not exist "%%f" set "MISSING=!MISSING! %%f"
)
if not exist ".venv\pyvenv.cfg" set "MISSING=!MISSING! .venv\pyvenv.cfg"
if not exist "packaging\installer\share\setup.vbs" set "MISSING=!MISSING! packaging\installer\share\setup.vbs"
if not exist "packaging\installer\share\.scripts\setup.ps1" set "MISSING=!MISSING! packaging\installer\share\.scripts\setup.ps1"
if not exist "packaging\installer\share\README.txt" set "MISSING=!MISSING! packaging\installer\share\README.txt"
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

:: Delete __pycache__ directories
for /d /r ".venv" %%d in (__pycache__) do if exist "%%d" rd /s /q "%%d" 2>nul
for /d /r "yakulingo" %%d in (__pycache__) do if exist "%%d" rd /s /q "%%d" 2>nul

:: Delete .pyc files
del /s /q ".venv\*.pyc" 2>nul

:: Delete cache directories
if exist ".uv-cache" rd /s /q ".uv-cache" 2>nul
if exist ".wheels" rd /s /q ".wheels" 2>nul

:: Delete temp files
del /q "*.tmp" 2>nul
del /q ".venv\pyvenv.cfg.tmp" 2>nul

:: Fix pyvenv.cfg - extract version and rewrite
set "PYTHON_VERSION="
for /f "tokens=2 delims==" %%v in ('findstr /b "version" ".venv\pyvenv.cfg"') do set "PYTHON_VERSION=%%v"
set "PYTHON_VERSION=!PYTHON_VERSION: =!"
(
    echo home = __PYTHON_HOME__
    echo include-system-site-packages = false
    echo version = !PYTHON_VERSION!
) > ".venv\pyvenv.cfg"

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
for %%f in ("YakuLingo.exe" "app.py" "glossary.csv" "pyproject.toml" "uv.lock" "uv.toml" "README.md") do (
    if exist "%%~f" copy /y "%%~f" "%DIST_DIR%\" >nul
)

:: ============================================================
:: Step 2: Copy folders (parallel robocopy via PowerShell jobs)
:: ============================================================
call :ShowProgress 1 "Copying folders..."

echo        Copying .venv, .uv-python, .playwright-browsers, yakulingo, prompts, config...

:: Copy folders using robocopy
for %%f in (.venv .uv-python .playwright-browsers) do (
    if exist "%%f" robocopy "%%f" "%DIST_DIR%\%%f" /E /MT:16 /NFL /NDL /NJH /NJS /NP /R:1 /W:1 >nul
)
for %%f in (yakulingo prompts config) do (
    if exist "%%f" robocopy "%%f" "%DIST_DIR%\%%f" /E /MT:8 /NFL /NDL /NJH /NJS /NP /R:1 /W:1 >nul
)

:: ============================================================
:: Step 3: Create ZIP and finalize
:: ============================================================
call :ShowProgress 2 "Creating ZIP and finalizing..."

:: Create ZIP archive
echo        Creating ZIP archive...
pushd dist_temp
"%SEVENZIP%" a -tzip -mx=1 -mmt=on -bsp1 "..\%SHARE_DIR%\%DIST_ZIP%" YakuLingo >nul
popd

:: Copy installer files and cleanup in parallel
echo        Copying installer files...
copy /y "packaging\installer\share\setup.vbs" "%SHARE_DIR%\" >nul
copy /y "packaging\installer\share\README.txt" "%SHARE_DIR%\" >nul
xcopy /E /I /Q /Y "packaging\installer\share\.scripts" "%SHARE_DIR%\.scripts" >nul
rd /s /q "dist_temp" 2>nul

:: Calculate elapsed time using PowerShell ticks
for /f %%e in ('powershell -NoProfile -Command "$e=([DateTime]::Now.Ticks-%START_TICKS%)/10000000;$m=[math]::Floor($e/60);$s=[math]::Floor($e%%60);if($m-gt0){\"${m}m ${s}s\"}else{\"${s}s\"}"') do set "ELAPSED_TIME=%%e"

call :ShowProgress 3 "Complete!"

if exist "%SHARE_DIR%\%DIST_ZIP%" (
    echo.
    echo ============================================================
    echo [SUCCESS] Distribution package created!
    echo.
    echo   Folder: %SHARE_DIR%\
    echo     - setup.vbs    ^<-- Users run this
    echo     - %DIST_ZIP%
    echo     - README.txt
    echo.
    for %%A in ("%SHARE_DIR%\%DIST_ZIP%") do echo   Size: %%~zA bytes
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
