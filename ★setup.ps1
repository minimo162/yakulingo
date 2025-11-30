# YakuLingo ショートカット作成スクリプト
# ファイルを配置し、スタートメニュー・デスクトップにショートカットを作成します

$ErrorActionPreference = "Stop"

# 配置先
$appDir = "$env:LOCALAPPDATA\YakuLingo"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "YakuLingo セットアップ" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "配置先: $appDir"
Write-Host ""
Write-Host "このスクリプトは以下を行います:"
Write-Host "  - ファイルを上記フォルダにコピー（時間がかかります）"
Write-Host "  - スタートメニューにショートカットを作成"
Write-Host "  - (オプション) デスクトップにショートカットを作成"
Write-Host ""

# 確認
$response = Read-Host "続行しますか? (Y/N)"
if ($response -ne "Y" -and $response -ne "y") {
    Write-Host "キャンセルしました。"
    exit 0
}

# 配置先フォルダ作成
if (Test-Path $appDir) {
    Write-Host "[INFO] 既存のファイルを上書きします..."
}
New-Item -ItemType Directory -Path $appDir -Force | Out-Null

# ファイルをコピー
Write-Host "[1/3] ファイルをコピー中（時間がかかります）..."
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# コピー対象ファイル
$files = @(
    "app.py",
    "pyproject.toml",
    "requirements.txt",
    "glossary.csv"
)

# コピー対象フォルダ（アプリ + 依存関係）
$folders = @(
    "ecm_translate",
    "prompts",
    "config",
    ".venv",
    ".uv-python",
    ".playwright-browsers"
)

# ★run.bat を run.bat としてコピー
$runBatSource = Join-Path $scriptDir "★run.bat"
if (Test-Path $runBatSource) {
    Copy-Item $runBatSource "$appDir\run.bat" -Force
}

# ファイルをコピー
foreach ($file in $files) {
    $source = Join-Path $scriptDir $file
    if (Test-Path $source) {
        Copy-Item $source $appDir -Force
    }
}

# フォルダをコピー
foreach ($folder in $folders) {
    $source = Join-Path $scriptDir $folder
    if (Test-Path $source) {
        Write-Host "  コピー中: $folder ..."
        Copy-Item $source $appDir -Recurse -Force
    }
}

Write-Host "[OK] ファイルコピー完了"

# スタートメニューにショートカット作成
Write-Host "[2/3] ショートカットを作成中..."
$startMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"

$shell = New-Object -ComObject WScript.Shell

# YakuLingo ショートカット
$shortcut = $shell.CreateShortcut("$startMenuDir\YakuLingo.lnk")
$shortcut.TargetPath = "$appDir\run.bat"
$shortcut.WorkingDirectory = $appDir
$shortcut.IconLocation = "%SystemRoot%\System32\shell32.dll,13"
$shortcut.Description = "YakuLingo - 日英翻訳ツール"
$shortcut.Save()

Write-Host "[OK] スタートメニューに追加しました"

# デスクトップショートカット（オプション）
$desktopResponse = Read-Host "デスクトップにショートカットを作成しますか? (Y/N)"
if ($desktopResponse -eq "Y" -or $desktopResponse -eq "y") {
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $desktopShortcut = $shell.CreateShortcut("$desktopPath\YakuLingo.lnk")
    $desktopShortcut.TargetPath = "$appDir\run.bat"
    $desktopShortcut.WorkingDirectory = $appDir
    $desktopShortcut.IconLocation = "%SystemRoot%\System32\shell32.dll,13"
    $desktopShortcut.Description = "YakuLingo - 日英翻訳ツール"
    $desktopShortcut.Save()
    Write-Host "[OK] デスクトップに追加しました"
}

Write-Host "[3/3] 完了"
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "セットアップ完了!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "スタートメニューまたはデスクトップから「YakuLingo」を起動できます。"
Write-Host ""
Write-Host "配置先: $appDir"
Write-Host ""

Read-Host "Enterキーで終了"
