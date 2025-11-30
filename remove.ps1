# YakuLingo 削除スクリプト
# 配置したファイルとショートカットを削除します

$ErrorActionPreference = "SilentlyContinue"

$appDir = "$env:LOCALAPPDATA\YakuLingo"
$startMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
$startMenuShortcut = "$startMenuDir\YakuLingo.lnk"
$startMenuRemoveShortcut = "$startMenuDir\YakuLingo を削除.lnk"
$desktopShortcut = [Environment]::GetFolderPath("Desktop") + "\YakuLingo.lnk"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "YakuLingo 削除" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "以下を削除します:"

$toDelete = @()

if (Test-Path $appDir) {
    Write-Host "  - $appDir"
    $toDelete += $appDir
}
if (Test-Path $startMenuShortcut) {
    Write-Host "  - スタートメニュー: YakuLingo"
    $toDelete += $startMenuShortcut
}
if (Test-Path $startMenuRemoveShortcut) {
    Write-Host "  - スタートメニュー: YakuLingo を削除"
    $toDelete += $startMenuRemoveShortcut
}
if (Test-Path $desktopShortcut) {
    Write-Host "  - デスクトップショートカット"
    $toDelete += $desktopShortcut
}

if ($toDelete.Count -eq 0) {
    Write-Host ""
    Write-Host "削除対象が見つかりませんでした。"
    Write-Host ""
    Read-Host "Enterキーで終了"
    exit 0
}

Write-Host ""
$response = Read-Host "削除しますか? (Y/N)"
if ($response -ne "Y" -and $response -ne "y") {
    Write-Host "キャンセルしました。"
    exit 0
}

Write-Host ""
Write-Host "削除中..."

# アプリフォルダ削除
if (Test-Path $appDir) {
    Remove-Item -Path $appDir -Recurse -Force
    Write-Host "[OK] アプリフォルダを削除しました"
}

# スタートメニューショートカット削除
if (Test-Path $startMenuShortcut) {
    Remove-Item -Path $startMenuShortcut -Force
    Write-Host "[OK] スタートメニュー (YakuLingo) を削除しました"
}
if (Test-Path $startMenuRemoveShortcut) {
    Remove-Item -Path $startMenuRemoveShortcut -Force
    Write-Host "[OK] スタートメニュー (削除) を削除しました"
}

# デスクトップショートカット削除
if (Test-Path $desktopShortcut) {
    Remove-Item -Path $desktopShortcut -Force
    Write-Host "[OK] デスクトップショートカットを削除しました"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "削除完了!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Read-Host "Enterキーで終了"
