@echo off
:: YakuLingo Remove Script
:: Removes files and shortcuts

cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0remove.ps1"
