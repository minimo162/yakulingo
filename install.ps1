# YakuLingo インストールスクリプト
# 右クリック → PowerShellで実行 または install.bat から実行

$ErrorActionPreference = "Stop"

# インストール先
$installDir = "$env:LOCALAPPDATA\YakuLingo"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "YakuLingo インストーラー" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "インストール先: $installDir"
Write-Host ""

# 確認
$response = Read-Host "インストールを続行しますか? (Y/N)"
if ($response -ne "Y" -and $response -ne "y") {
    Write-Host "キャンセルしました。"
    exit 0
}

# インストール先フォルダ作成
if (Test-Path $installDir) {
    Write-Host "[INFO] 既存のインストールを上書きします..."
}
New-Item -ItemType Directory -Path $installDir -Force | Out-Null

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

# ★run.bat は run.bat としてコピー
if (Test-Path "$scriptDir\★run.bat") {
    Copy-Item "$scriptDir\★run.bat" "$installDir\run.bat" -Force
}
if (Test-Path "$scriptDir\run.bat") {
    Copy-Item "$scriptDir\run.bat" "$installDir\run.bat" -Force
}

foreach ($item in $items) {
    $source = Join-Path $scriptDir $item
    if (Test-Path $source) {
        $dest = Join-Path $installDir $item
        if (Test-Path $source -PathType Container) {
            Copy-Item $source $installDir -Recurse -Force
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
$shortcut.TargetPath = "$installDir\run.bat"
$shortcut.WorkingDirectory = $installDir
$shortcut.IconLocation = "%SystemRoot%\System32\shell32.dll,13"
$shortcut.Description = "YakuLingo - 日英翻訳ツール"
$shortcut.Save()

# セットアップ ショートカット
$shortcut2 = $shell.CreateShortcut("$startMenuDir\YakuLingo セットアップ.lnk")
$shortcut2.TargetPath = "$installDir\setup.bat"
$shortcut2.WorkingDirectory = $installDir
$shortcut2.Description = "YakuLingo 依存関係インストール"
$shortcut2.Save()

Write-Host "[OK] スタートメニューに追加しました"

# デスクトップショートカット（オプション）
$desktopResponse = Read-Host "デスクトップにショートカットを作成しますか? (Y/N)"
if ($desktopResponse -eq "Y" -or $desktopResponse -eq "y") {
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $desktopShortcut = $shell.CreateShortcut("$desktopPath\YakuLingo.lnk")
    $desktopShortcut.TargetPath = "$installDir\run.bat"
    $desktopShortcut.WorkingDirectory = $installDir
    $desktopShortcut.IconLocation = "%SystemRoot%\System32\shell32.dll,13"
    $desktopShortcut.Description = "YakuLingo - 日英翻訳ツール"
    $desktopShortcut.Save()
    Write-Host "[OK] デスクトップに追加しました"
}

Write-Host "[3/3] 初回セットアップを実行中..."
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "インストール完了!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "次のステップ:"
Write-Host "  1. スタートメニューから「YakuLingo セットアップ」を実行 (初回のみ)"
Write-Host "  2. スタートメニューから「YakuLingo」を起動"
Write-Host ""
Write-Host "インストール先: $installDir"
Write-Host ""

# セットアップを実行するか確認
$setupResponse = Read-Host "今すぐセットアップを実行しますか? (Y/N)"
if ($setupResponse -eq "Y" -or $setupResponse -eq "y") {
    Start-Process -FilePath "$installDir\setup.bat" -WorkingDirectory $installDir -Wait
}

Write-Host ""
Write-Host "完了しました。ウィンドウを閉じてください。"
Read-Host "Enterキーで終了"
