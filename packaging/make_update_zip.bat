@echo off
setlocal

cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe packaging\make_update_zip.py %*
) else if exist ".uv-python\python.exe" (
    .uv-python\python.exe packaging\make_update_zip.py %*
) else (
    python packaging\make_update_zip.py %*
)

pause
