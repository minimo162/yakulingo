# YakuLingo パッケージ作成スクリプト
# PowerShell のみ使用（7-Zip不要）

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "YakuLingo パッケージ作成" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# パス設定
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir
$outputDir = Join-Path $scriptDir "output"
$tempDir = Join-Path $scriptDir "temp_package"

# 出力ディレクトリ作成
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

# 一時ディレクトリをクリーンアップ
if (Test-Path $tempDir) {
    Remove-Item -Path $tempDir -Recurse -Force
}
New-Item -ItemType Directory -Path $tempDir | Out-Null

Write-Host "[1/3] ファイルをコピー中..."

# コピー対象ファイル
$files = @(
    "app.py",
    "pyproject.toml",
    "requirements.txt",
    "glossary.csv",
    "setup.bat",
    "setup_shortcut.bat",
    "setup_shortcut.ps1",
    "uninstall.bat",
    "uninstall.ps1"
)

# コピー対象フォルダ
$folders = @(
    "ecm_translate",
    "prompts",
    "config"
)

# ファイルをコピー
foreach ($file in $files) {
    $source = Join-Path $projectDir $file
    if (Test-Path $source) {
        Copy-Item $source $tempDir -Force
    }
}

# ★run.bat を run.bat としてコピー
$runBatSource = Join-Path $projectDir "★run.bat"
if (Test-Path $runBatSource) {
    Copy-Item $runBatSource (Join-Path $tempDir "run.bat") -Force
}

# フォルダをコピー
foreach ($folder in $folders) {
    $source = Join-Path $projectDir $folder
    if (Test-Path $source) {
        Copy-Item $source $tempDir -Recurse -Force
    }
}

Write-Host "[OK] ファイルコピー完了"

Write-Host "[2/3] ZIP作成中..."

# 出力ファイル名
$zipPath = Join-Path $outputDir "YakuLingo.zip"

# 既存のzipを削除
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

# ZIP作成
Compress-Archive -Path "$tempDir\*" -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host "[OK] ZIP作成完了"

Write-Host "[3/3] クリーンアップ中..."

# 一時フォルダ削除
Remove-Item -Path $tempDir -Recurse -Force

Write-Host "[OK] クリーンアップ完了"

# ファイルサイズ表示
$zipSize = (Get-Item $zipPath).Length / 1MB
$zipSizeStr = "{0:N2} MB" -f $zipSize

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "パッケージ作成完了!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "出力ファイル: $zipPath"
Write-Host "サイズ: $zipSizeStr"
Write-Host ""
Write-Host "配布方法:"
Write-Host "  1. YakuLingo.zip をユーザーに送る"
Write-Host "  2. ユーザーは展開後 setup_shortcut.bat を実行（ショートカット作成）"
Write-Host "     または ★run.bat を直接実行（ショートカット不要の場合）"
Write-Host ""

Read-Host "Enterキーで終了"
