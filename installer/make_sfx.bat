@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo YakuLingo 自己解凍インストーラー作成
echo ============================================================
echo.

cd /d "%~dp0\.."

:: 7-Zip のパスを探す
set SEVENZIP=
if exist "C:\Program Files\7-Zip\7z.exe" set SEVENZIP="C:\Program Files\7-Zip\7z.exe"
if exist "C:\Program Files (x86)\7-Zip\7z.exe" set SEVENZIP="C:\Program Files (x86)\7-Zip\7z.exe"

if not defined SEVENZIP (
    echo [ERROR] 7-Zip が見つかりません。
    echo インストール: https://www.7-zip.org/
    pause
    exit /b 1
)

echo [INFO] 7-Zip: %SEVENZIP%

:: 出力ディレクトリ
set OUTPUT_DIR=installer\output
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

:: 一時ディレクトリ
set TEMP_DIR=installer\temp_package
if exist "%TEMP_DIR%" rmdir /s /q "%TEMP_DIR%"
mkdir "%TEMP_DIR%"

echo.
echo [1/3] ファイルをコピー中...

:: 必要なファイルをコピー
copy app.py "%TEMP_DIR%\" >nul
copy pyproject.toml "%TEMP_DIR%\" >nul
copy requirements.txt "%TEMP_DIR%\" >nul
copy glossary.csv "%TEMP_DIR%\" >nul
copy setup.bat "%TEMP_DIR%\" >nul
copy "★run.bat" "%TEMP_DIR%\run.bat" >nul
copy install.ps1 "%TEMP_DIR%\" >nul
copy install.bat "%TEMP_DIR%\" >nul

xcopy ecm_translate "%TEMP_DIR%\ecm_translate\" /E /I /Q >nul
xcopy prompts "%TEMP_DIR%\prompts\" /E /I /Q >nul
xcopy config "%TEMP_DIR%\config\" /E /I /Q >nul

echo [OK] ファイルコピー完了

echo.
echo [2/3] アーカイブ作成中...

:: 7z アーカイブ作成
%SEVENZIP% a -t7z "%OUTPUT_DIR%\YakuLingo.7z" ".\%TEMP_DIR%\*" -mx=9 >nul

if not exist "%OUTPUT_DIR%\YakuLingo.7z" (
    echo [ERROR] アーカイブ作成に失敗しました。
    pause
    exit /b 1
)

echo [OK] アーカイブ作成完了

echo.
echo [3/3] 自己解凍exe作成中...

:: SFX設定ファイル作成
(
echo ;!@Install@!UTF-8!
echo Title="YakuLingo インストーラー"
echo BeginPrompt="YakuLingo をインストールしますか?"
echo RunProgram="install.bat"
echo ;!@InstallEnd@!
) > "%OUTPUT_DIR%\sfx_config.txt"

:: 7-Zip SFXモジュールのパス
set SFX_MODULE=
if exist "C:\Program Files\7-Zip\7z.sfx" set SFX_MODULE="C:\Program Files\7-Zip\7z.sfx"
if exist "C:\Program Files (x86)\7-Zip\7z.sfx" set SFX_MODULE="C:\Program Files (x86)\7-Zip\7z.sfx"

if not defined SFX_MODULE (
    echo [WARN] 7z.sfx が見つかりません。
    echo 代わりに .7z ファイルを配布してください: %OUTPUT_DIR%\YakuLingo.7z
    echo.
    echo ユーザーは以下の手順でインストール:
    echo   1. YakuLingo.7z を展開
    echo   2. install.bat を実行
    goto :cleanup
)

:: SFX exe 作成 (sfxモジュール + 設定 + アーカイブ を結合)
copy /b %SFX_MODULE% + "%OUTPUT_DIR%\sfx_config.txt" + "%OUTPUT_DIR%\YakuLingo.7z" "%OUTPUT_DIR%\YakuLingo_Setup.exe" >nul

if exist "%OUTPUT_DIR%\YakuLingo_Setup.exe" (
    echo [OK] 自己解凍exe作成完了
    echo.
    echo ============================================================
    echo 完了!
    echo ============================================================
    echo.
    echo 出力ファイル:
    echo   %OUTPUT_DIR%\YakuLingo_Setup.exe  ^(自己解凍インストーラー^)
    echo   %OUTPUT_DIR%\YakuLingo.7z         ^(7zアーカイブ^)
) else (
    echo [WARN] 自己解凍exe作成に失敗しました。
    echo .7z ファイルを配布してください。
)

:cleanup
:: 一時ファイル削除
del "%OUTPUT_DIR%\sfx_config.txt" 2>nul
rmdir /s /q "%TEMP_DIR%" 2>nul

echo.
pause
