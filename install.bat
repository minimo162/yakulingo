@echo off
:: YakuLingo インストーラー起動
:: install.ps1 を実行します

cd /d "%~dp0"

echo.
echo YakuLingo インストーラーを起動しています...
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"

if errorlevel 1 (
    echo.
    echo [ERROR] インストールに失敗しました。
    pause
)
