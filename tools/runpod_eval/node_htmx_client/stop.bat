@echo off
setlocal
set SCRIPT_DIR=%~dp0
echo stop.bat is deprecated.
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%_internal\stop.ps1" %*
endlocal
