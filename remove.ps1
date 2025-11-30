# YakuLingo Remove Script
# Removes files and shortcuts

$ErrorActionPreference = "SilentlyContinue"

$appDir = "$env:LOCALAPPDATA\YakuLingo"
$startMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
$startMenuShortcut = "$startMenuDir\YakuLingo.lnk"
$startMenuRemoveShortcut = "$startMenuDir\YakuLingo Remove.lnk"
$desktopShortcut = [Environment]::GetFolderPath("Desktop") + "\YakuLingo.lnk"

# Check what exists
$toDelete = @()
$messageItems = @()

if (Test-Path $appDir) {
    $toDelete += $appDir
    $messageItems += "- App folder: $appDir"
}
if (Test-Path $startMenuShortcut) {
    $toDelete += $startMenuShortcut
    $messageItems += "- Start Menu: YakuLingo"
}
if (Test-Path $startMenuRemoveShortcut) {
    $toDelete += $startMenuRemoveShortcut
    $messageItems += "- Start Menu: YakuLingo Remove"
}
if (Test-Path $desktopShortcut) {
    $toDelete += $desktopShortcut
    $messageItems += "- Desktop shortcut"
}

if ($toDelete.Count -eq 0) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Nothing to remove. YakuLingo is not installed.",
        "YakuLingo Remove",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Information
    )
    exit 0
}

# Confirmation dialog
Add-Type -AssemblyName System.Windows.Forms

$message = "Do you want to remove YakuLingo?`n`nThe following will be deleted:`n" + ($messageItems -join "`n")

$result = [System.Windows.Forms.MessageBox]::Show(
    $message,
    "YakuLingo Remove",
    [System.Windows.Forms.MessageBoxButtons]::OKCancel,
    [System.Windows.Forms.MessageBoxIcon]::Warning
)

if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
    exit 0
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "YakuLingo Remove" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Removing..."

# Remove app folder
if (Test-Path $appDir) {
    Remove-Item -Path $appDir -Recurse -Force
    Write-Host "[OK] App folder removed"
}

# Remove Start Menu shortcuts
if (Test-Path $startMenuShortcut) {
    Remove-Item -Path $startMenuShortcut -Force
    Write-Host "[OK] Start Menu shortcut (YakuLingo) removed"
}
if (Test-Path $startMenuRemoveShortcut) {
    Remove-Item -Path $startMenuRemoveShortcut -Force
    Write-Host "[OK] Start Menu shortcut (Remove) removed"
}

# Remove Desktop shortcut
if (Test-Path $desktopShortcut) {
    Remove-Item -Path $desktopShortcut -Force
    Write-Host "[OK] Desktop shortcut removed"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Removal Complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Read-Host "Press Enter to exit"
