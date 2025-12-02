@echo off
REM ============================================================
REM YakuLingo Launcher Build Script
REM
REM Requirements:
REM   - MinGW-w64 (gcc) in PATH
REM   OR
REM   - Visual Studio with cl.exe in PATH
REM ============================================================

setlocal

cd /d "%~dp0"

REM Try MinGW first
where gcc >nul 2>&1
if %errorlevel%==0 (
    echo Building with MinGW-w64...
    gcc -mwindows -O2 -s launcher.c -o YakuLingo.exe -lwinhttp -lshlwapi
    if %errorlevel%==0 (
        echo.
        echo Build successful: YakuLingo.exe
        echo Size:
        for %%A in (YakuLingo.exe) do echo   %%~zA bytes
    ) else (
        echo Build failed!
        exit /b 1
    )
    goto :done
)

REM Try MSVC
where cl >nul 2>&1
if %errorlevel%==0 (
    echo Building with MSVC...
    cl /O2 /MT /W3 launcher.c /Fe:YakuLingo.exe /link winhttp.lib shlwapi.lib user32.lib /SUBSYSTEM:WINDOWS
    if %errorlevel%==0 (
        echo.
        echo Build successful: YakuLingo.exe
        del *.obj 2>nul
    ) else (
        echo Build failed!
        exit /b 1
    )
    goto :done
)

echo Error: No compiler found!
echo.
echo Please install one of the following:
echo   - MinGW-w64: https://www.mingw-w64.org/
echo   - Visual Studio Build Tools: https://visualstudio.microsoft.com/downloads/
exit /b 1

:done
echo.
echo To use: Copy YakuLingo.exe to the application root directory
