# YakuLingo パッケージ作成スクリプト
# 依存関係を含めた配布用パッケージを作成します

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
$packageDir = Join-Path $tempDir "YakuLingo"  # zip内のフォルダ名

# 依存関係フォルダの確認
$requiredDeps = @(".venv", ".uv-python", ".playwright-browsers")
$missingDeps = @()

foreach ($dep in $requiredDeps) {
    $depPath = Join-Path $projectDir $dep
    if (-not (Test-Path $depPath)) {
        $missingDeps += $dep
    }
}

if ($missingDeps.Count -gt 0) {
    Write-Host "[ERROR] 以下の依存関係フォルダが見つかりません:" -ForegroundColor Red
    foreach ($dep in $missingDeps) {
        Write-Host "  - $dep" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "先に install_deps.bat を実行して依存関係を取得してください。"
    Write-Host ""
    Read-Host "Enterキーで終了"
    exit 1
}

Write-Host "[OK] 依存関係フォルダを確認しました"

# 出力ディレクトリ作成
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

# 一時ディレクトリをクリーンアップ
if (Test-Path $tempDir) {
    Remove-Item -Path $tempDir -Recurse -Force
}
New-Item -ItemType Directory -Path $packageDir -Force | Out-Null

Write-Host ""
Write-Host "[1/4] アプリファイルをコピー中..."

# コピー対象ファイル
$files = @(
    "app.py",
    "pyproject.toml",
    "requirements.txt",
    "glossary.csv",
    "remove.bat",
    "remove.ps1"
)

# コピー対象フォルダ（アプリ）
$appFolders = @(
    "ecm_translate",
    "prompts",
    "config"
)

# ファイルをコピー
foreach ($file in $files) {
    $source = Join-Path $projectDir $file
    if (Test-Path $source) {
        Copy-Item $source $packageDir -Force
    }
}

# ★setup.bat と setup.ps1 をコピー
Copy-Item (Join-Path $projectDir "★setup.bat") $packageDir -Force
Copy-Item (Join-Path $projectDir "setup.ps1") $packageDir -Force

# ★run.bat を run.bat としてコピー（★を外す）
Copy-Item (Join-Path $projectDir "★run.bat") (Join-Path $packageDir "run.bat") -Force

# アプリフォルダをコピー
foreach ($folder in $appFolders) {
    $source = Join-Path $projectDir $folder
    if (Test-Path $source) {
        Copy-Item $source $packageDir -Recurse -Force
    }
}

Write-Host "[OK] アプリファイルコピー完了"

Write-Host "[2/4] 依存関係をコピー中（時間がかかります）..."

# 依存関係フォルダをコピー
foreach ($dep in $requiredDeps) {
    $source = Join-Path $projectDir $dep
    Write-Host "  コピー中: $dep ..."
    Copy-Item $source $packageDir -Recurse -Force
}

Write-Host "[OK] 依存関係コピー完了"

Write-Host "[3/4] ZIP作成中（時間がかかります）..."

# 出力ファイル名
$zipPath = Join-Path $outputDir "YakuLingo.zip"

# 既存のzipを削除
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

# ZIP作成（YakuLingoフォルダごと圧縮）
Compress-Archive -Path $packageDir -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host "[OK] ZIP作成完了"

Write-Host "[4/4] クリーンアップ中..."

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
Write-Host "  2. ユーザーは展開して ★setup.bat を実行"
Write-Host "  3. スタートメニュー or デスクトップから起動"
Write-Host ""

Read-Host "Enterキーで終了"
