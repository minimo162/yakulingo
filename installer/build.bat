@echo off
echo Building YakuLingo Installer...
echo.

cd /d "%~dp0"

:: Inno Setup のパスを探す
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
)

if not defined ISCC (
    echo [ERROR] Inno Setup not found.
    echo Please install from: https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

echo Using: %ISCC%
echo.

%ISCC% yakulingo.iss

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Build complete!
echo Output: output\YakuLingo_Setup.exe
echo ============================================================
pause
