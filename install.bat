@echo off
chcp 65001 >nul
echo ============================================
echo   Excel Translator - インストール
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python がインストールされていません
    echo Python 3.10以上をインストールしてください
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] Python依存関係をインストール中...
pip install playwright pywin32 customtkinter pillow keyboard -q

echo [2/3] Playwrightブラウザをインストール中...
playwright install chromium

echo [3/3] 完了!
echo.
echo ============================================
echo   インストール完了
echo   run.bat をダブルクリックして起動
echo ============================================
pause
