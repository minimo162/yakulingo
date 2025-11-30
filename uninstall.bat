@echo off
:: YakuLingo 削除スクリプト
:: 配置したファイルとショートカットを削除します

cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
