@echo off
:: YakuLingo ショートカット作成
:: ファイルを配置し、スタートメニューにショートカットを作成します

cd /d "%~dp0"

echo.
echo YakuLingo セットアップを起動しています...
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0setup_shortcut.ps1"

if errorlevel 1 (
    echo.
    echo [ERROR] セットアップに失敗しました。
    pause
)
