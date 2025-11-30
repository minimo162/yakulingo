# ============================================================
# YakuLingo ネットワークインストーラー
# 共有フォルダからローカルへのインストールを行います
# ============================================================

param(
    [string]$InstallPath = ""
)

$ErrorActionPreference = "Stop"

# ============================================================
# 設定
# ============================================================
$AppName = "YakuLingo"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ZIPファイルを自動検出（最新のものを使用）
$ZipFiles = Get-ChildItem -Path $ScriptDir -Filter "YakuLingo*.zip" | Sort-Object LastWriteTime -Descending
if ($ZipFiles.Count -eq 0) {
    Write-Host "[エラー] YakuLingo*.zip が見つかりません。" -ForegroundColor Red
    Write-Host "        このスクリプトと同じフォルダにZIPファイルを配置してください。" -ForegroundColor Red
    exit 1
}
$ZipFile = $ZipFiles[0].FullName
$ZipFileName = $ZipFiles[0].Name
Write-Host "[INFO] 使用するZIPファイル: $ZipFileName" -ForegroundColor Cyan

# インストール先（デフォルト: LocalAppData\YakuLingo）
if ([string]::IsNullOrEmpty($InstallPath)) {
    $InstallPath = Join-Path $env:LOCALAPPDATA $AppName
}

# ============================================================
# Step 1: 既存インストールのチェック
# ============================================================
Write-Host ""
Write-Host "[1/4] インストール先を確認しています..." -ForegroundColor Yellow

if (Test-Path $InstallPath) {
    Write-Host "      既存のインストールが見つかりました: $InstallPath" -ForegroundColor Gray

    # ユーザー設定のバックアップ
    $BackupDir = Join-Path $env:TEMP "YakuLingo_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    $UserFiles = @("glossary.csv", "config\settings.json")

    foreach ($file in $UserFiles) {
        $srcPath = Join-Path $InstallPath $file
        if (Test-Path $srcPath) {
            $dstPath = Join-Path $BackupDir $file
            $dstDir = Split-Path $dstPath -Parent
            if (-not (Test-Path $dstDir)) {
                New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
            }
            Copy-Item -Path $srcPath -Destination $dstPath -Force
            Write-Host "      バックアップ: $file" -ForegroundColor Gray
        }
    }

    # 既存フォルダを削除（環境ファイル以外）
    Write-Host "      既存のソースコードを削除しています..." -ForegroundColor Gray
    $KeepDirs = @(".venv", ".uv-python", ".playwright-browsers")
    Get-ChildItem -Path $InstallPath | Where-Object {
        $_.Name -notin $KeepDirs
    } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "[OK] インストール先: $InstallPath" -ForegroundColor Green

# ============================================================
# Step 2: ZIPファイルをローカルにコピー
# ============================================================
Write-Host ""
Write-Host "[2/4] ZIPファイルをコピーしています..." -ForegroundColor Yellow

$TempDir = Join-Path $env:TEMP "YakuLingo_install_$(Get-Date -Format 'yyyyMMddHHmmss')"
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

$LocalZip = Join-Path $TempDir $ZipFileName
Copy-Item -Path $ZipFile -Destination $LocalZip -Force

Write-Host "[OK] コピー完了" -ForegroundColor Green

# ============================================================
# Step 3: ZIPを展開
# ============================================================
Write-Host ""
Write-Host "[3/4] ZIPファイルを展開しています..." -ForegroundColor Yellow

# 展開
Expand-Archive -Path $LocalZip -DestinationPath $TempDir -Force

# 展開されたフォルダを特定（YakuLingoフォルダ）
$ExtractedDir = Get-ChildItem -Path $TempDir -Directory | Where-Object { $_.Name -like "YakuLingo*" } | Select-Object -First 1

if (-not $ExtractedDir) {
    Write-Host "[エラー] ZIPファイルの展開に失敗しました。" -ForegroundColor Red
    exit 1
}

# _internal フォルダの内容をインストール先にコピー
$InternalDir = Join-Path $ExtractedDir.FullName "_internal"
if (Test-Path $InternalDir) {
    $SourceDir = $InternalDir
} else {
    $SourceDir = $ExtractedDir.FullName
}

# インストール先ディレクトリを作成
if (-not (Test-Path $InstallPath)) {
    New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
}

# ファイルをコピー
Get-ChildItem -Path $SourceDir | ForEach-Object {
    $dest = Join-Path $InstallPath $_.Name
    if ($_.PSIsContainer) {
        # ディレクトリの場合、環境フォルダはスキップ（既存を保持）
        if ($_.Name -in @(".venv", ".uv-python", ".playwright-browsers")) {
            if (-not (Test-Path $dest)) {
                Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
            }
        } else {
            Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
        }
    } else {
        Copy-Item -Path $_.FullName -Destination $dest -Force
    }
}

# バックアップからユーザー設定を復元
if ($BackupDir -and (Test-Path $BackupDir)) {
    Write-Host "      ユーザー設定を復元しています..." -ForegroundColor Gray
    Get-ChildItem -Path $BackupDir -Recurse -File | ForEach-Object {
        $relativePath = $_.FullName.Substring($BackupDir.Length + 1)
        $destPath = Join-Path $InstallPath $relativePath
        $destDir = Split-Path $destPath -Parent
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        Copy-Item -Path $_.FullName -Destination $destPath -Force
    }
    Remove-Item -Path $BackupDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "[OK] 展開完了" -ForegroundColor Green

# ============================================================
# Step 4: ショートカット作成
# ============================================================
Write-Host ""
Write-Host "[4/4] ショートカットを作成しています..." -ForegroundColor Yellow

$WshShell = New-Object -ComObject WScript.Shell

# デスクトップショートカット
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "$AppName.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $InstallPath "run.bat"
$Shortcut.WorkingDirectory = $InstallPath
$Shortcut.IconLocation = "shell32.dll,21"
$Shortcut.Description = "YakuLingo - 翻訳ツール"
$Shortcut.Save()
Write-Host "      デスクトップ: $ShortcutPath" -ForegroundColor Gray

# スタートメニュー
$StartMenuPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$StartShortcutPath = Join-Path $StartMenuPath "$AppName.lnk"
$StartShortcut = $WshShell.CreateShortcut($StartShortcutPath)
$StartShortcut.TargetPath = Join-Path $InstallPath "run.bat"
$StartShortcut.WorkingDirectory = $InstallPath
$StartShortcut.IconLocation = "shell32.dll,21"
$StartShortcut.Description = "YakuLingo - 翻訳ツール"
$StartShortcut.Save()
Write-Host "      スタートメニュー: $StartShortcutPath" -ForegroundColor Gray

Write-Host "[OK] ショートカット作成完了" -ForegroundColor Green

# ============================================================
# クリーンアップ
# ============================================================
Remove-Item -Path $TempDir -Recurse -Force -ErrorAction SilentlyContinue

# ============================================================
# 完了
# ============================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " インストールが完了しました！" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host " インストール先: $InstallPath" -ForegroundColor White
Write-Host ""
Write-Host " 起動方法:" -ForegroundColor White
Write-Host "   - デスクトップの「$AppName」ショートカットをダブルクリック" -ForegroundColor Gray
Write-Host "   - またはスタートメニューから「$AppName」を検索" -ForegroundColor Gray
Write-Host ""

exit 0
