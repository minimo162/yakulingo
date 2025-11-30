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
Write-Host "  - ファイルを上記フォルダにコピー"
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
Write-Host "[1/3] ファイルをコピー中..."
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# コピー対象
$items = @(
    "app.py",
    "pyproject.toml",
    "requirements.txt",
    "glossary.csv",
    "setup.bat",
    "ecm_translate",
    "prompts",
    "config"
)

# ★run.bat を run.bat としてコピー
if (Test-Path "$scriptDir\★run.bat") {
    Copy-Item "$scriptDir\★run.bat" "$appDir\run.bat" -Force
}
if (Test-Path "$scriptDir\run.bat") {
    Copy-Item "$scriptDir\run.bat" "$appDir\run.bat" -Force
}

foreach ($item in $items) {
    $source = Join-Path $scriptDir $item
    if (Test-Path $source) {
        $dest = Join-Path $appDir $item
        if (Test-Path $source -PathType Container) {
            Copy-Item $source $appDir -Recurse -Force
        } else {
            Copy-Item $source $dest -Force
        }
    }
}
Write-Host "[OK] ファイルコピー完了"

# スタートメニューにショートカット作成
Write-Host "[2/3] ショートカットを作成中..."
$startMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\YakuLingo"
New-Item -ItemType Directory -Path $startMenuDir -Force | Out-Null

$shell = New-Object -ComObject WScript.Shell

# YakuLingo ショートカット
$shortcut = $shell.CreateShortcut("$startMenuDir\YakuLingo.lnk")
$shortcut.TargetPath = "$appDir\run.bat"
$shortcut.WorkingDirectory = $appDir
$shortcut.IconLocation = "%SystemRoot%\System32\shell32.dll,13"
$shortcut.Description = "YakuLingo - 日英翻訳ツール"
$shortcut.Save()

# 依存関係セットアップ ショートカット
$shortcut2 = $shell.CreateShortcut("$startMenuDir\YakuLingo 依存関係セットアップ.lnk")
$shortcut2.TargetPath = "$appDir\setup.bat"
$shortcut2.WorkingDirectory = $appDir
$shortcut2.Description = "YakuLingo 依存関係の取得"
$shortcut2.Save()

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

Write-Host "[3/3] 完了処理..."
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "セットアップ完了!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "次のステップ:"
Write-Host "  1. スタートメニューから「YakuLingo 依存関係セットアップ」を実行 (初回のみ)"
Write-Host "  2. スタートメニューから「YakuLingo」を起動"
Write-Host ""
Write-Host "配置先: $appDir"
Write-Host ""

# セットアップを実行するか確認
$setupResponse = Read-Host "今すぐ依存関係セットアップを実行しますか? (Y/N)"
if ($setupResponse -eq "Y" -or $setupResponse -eq "y") {
    Start-Process -FilePath "$appDir\setup.bat" -WorkingDirectory $appDir -Wait
}

Write-Host ""
Write-Host "完了しました。"
Read-Host "Enterキーで終了"
