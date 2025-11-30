@echo off
:: YakuLingo パッケージ作成
:: PowerShellスクリプトを実行

cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0make_package.ps1"
