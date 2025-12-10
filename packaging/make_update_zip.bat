@echo off
chcp 65001 >nul
setlocal

echo.
echo ============================================================
echo YakuLingo アップデートZIP作成
echo ============================================================
echo.

REM プロジェクトルートに移動
cd /d "%~dp0.."

REM Pythonスクリプトを実行
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe packaging\make_update_zip.py %*
) else if exist ".uv-python\python.exe" (
    .uv-python\python.exe packaging\make_update_zip.py %*
) else (
    python packaging\make_update_zip.py %*
)

echo.
pause
