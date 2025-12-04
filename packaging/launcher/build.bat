@echo off
REM ============================================================
REM YakuLingo Launcher Build Script (Rust)
REM
REM Requirements:
REM   - Rust toolchain (rustup): https://rustup.rs/
REM ============================================================

setlocal

cd /d "%~dp0"

REM Check if cargo is available
where cargo >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Rust not found!
    echo.
    echo Please install Rust from: https://rustup.rs/
    echo Or download YakuLingo.exe from GitHub Actions artifacts.
    exit /b 1
)

echo Building with Rust...
cargo build --release

if %errorlevel%==0 (
    copy /y target\release\yakulingo-launcher.exe YakuLingo.exe >nul
    echo.
    echo Build successful: YakuLingo.exe
    echo Size:
    for %%A in (YakuLingo.exe) do echo   %%~zA bytes
) else (
    echo Build failed!
    exit /b 1
)

echo.
echo To use: Copy YakuLingo.exe to the application root directory
