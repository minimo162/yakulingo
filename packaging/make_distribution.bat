@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo YakuLingo - Distribution Package Builder
echo ============================================================
echo.

cd /d "%~dp0\.."

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
call :ShowProgress 1 "Preparing..."

:: Check required files using PowerShell (faster than multiple if exists)
echo        Checking required files...
for /f "delims=" %%r in ('powershell -NoProfile -Command ^
"$missing = @(); ^
$files = @('.venv','.venv\pyvenv.cfg','.uv-python','.playwright-browsers','app.py','yakulingo','YakuLingo.exe','prompts','packaging\installer\share\setup.vbs','packaging\installer\share\.scripts\setup.ps1','packaging\installer\share\README.txt'); ^
foreach ($f in $files) { if (-not (Test-Path $f)) { $missing += $f } }; ^
$7z = @(\"$env:ProgramFiles\7-Zip\7z.exe\",\"${env:ProgramFiles(x86)}\7-Zip\7z.exe\") | Where-Object { Test-Path $_ } | Select-Object -First 1; ^
if (-not $7z) { $7z = (Get-Command 7z.exe -ErrorAction SilentlyContinue).Source }; ^
if ($missing.Count -gt 0) { $missing -join '|'; exit 1 } ^
elseif (-not $7z) { Write-Output '7ZIP_NOT_FOUND'; exit 1 } ^
else { Write-Output $7z; exit 0 }"') do (
    set "CHECK_RESULT=%%r"
)
if errorlevel 1 (
    if "!CHECK_RESULT!"=="7ZIP_NOT_FOUND" (
        echo        [ERROR] 7-Zip not found. Please install from https://7-zip.org/
    ) else (
        for %%m in ("!CHECK_RESULT:|=" "!") do echo        [ERROR] Missing: %%~m
    )
    echo.
    echo [ERROR] Missing required files. Please run install_deps.bat first.
    pause
    exit /b 1
)
set "SEVENZIP=!CHECK_RESULT!"

:: Prepare: cleanup, fix pyvenv.cfg, get date, create dirs, copy files - all in one PowerShell call
echo        Cleaning up and preparing...
for /f "delims=" %%d in ('powershell -NoProfile -Command ^
"$ErrorActionPreference = 'SilentlyContinue'; ^
Get-ChildItem -Path '.venv','yakulingo' -Recurse -Directory -Filter '__pycache__' ^| Remove-Item -Recurse -Force; ^
Get-ChildItem -Path '.venv' -Recurse -Filter '*.pyc' ^| Remove-Item -Force; ^
Remove-Item -Path '.uv-cache','.wheels' -Recurse -Force; ^
Remove-Item -Path '*.tmp','.venv\pyvenv.cfg.tmp' -Force; ^
$ver = (Get-Content '.venv\pyvenv.cfg' ^| Where-Object { $_ -match '^version' }) -replace 'version\s*=\s*',''; ^
Set-Content '.venv\pyvenv.cfg' -Value \"home = __PYTHON_HOME__`ninclude-system-site-packages = false`nversion = $ver\"; ^
(Get-Date).ToString('yyyyMMdd')"') do set "DIST_DATE=%%d"

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
call :ShowProgress 2 "Copying folders..."

echo        Copying .venv, .uv-python, .playwright-browsers, yakulingo, prompts, config...

:: Use PowerShell Start-Process for true parallel execution with proper wait
powershell -NoProfile -Command ^
"$distDir = '%DIST_DIR%'; ^
$jobs = @(); ^
$folders = @('.venv','.uv-python','.playwright-browsers','yakulingo','prompts','config'); ^
foreach ($f in $folders) { ^
    if (Test-Path $f) { ^
        $mt = if ($f -in '.venv','.uv-python','.playwright-browsers') { 16 } else { 8 }; ^
        $jobs += Start-Process -FilePath 'robocopy' -ArgumentList \"$f\",\"$distDir\$f\",'/E',\"/MT:$mt\",'/NFL','/NDL','/NJH','/NJS','/NP','/R:1','/W:1' -NoNewWindow -PassThru ^
    } ^
}; ^
$jobs ^| Wait-Process"

:: ============================================================
:: Step 3: Create ZIP and finalize
:: ============================================================
call :ShowProgress 3 "Creating ZIP and finalizing..."

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
for /f %%e in ('powershell -NoProfile -Command ^
"$elapsed = ([DateTime]::Now.Ticks - %START_TICKS%) / 10000000; ^
$m = [math]::Floor($elapsed / 60); $s = [math]::Floor($elapsed %% 60); ^
if ($m -gt 0) { \"${m}m ${s}s\" } else { \"${s}s\" }"') do set "ELAPSED_TIME=%%e"

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
