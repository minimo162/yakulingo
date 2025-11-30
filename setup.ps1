# YakuLingo Setup Script
# Copies files and creates Start Menu / Desktop shortcuts

$ErrorActionPreference = "Stop"

# Destination
$appDir = "$env:LOCALAPPDATA\YakuLingo"

# Confirmation dialog
Add-Type -AssemblyName System.Windows.Forms

$message = @"
Do you want to set up YakuLingo?

Destination: $appDir

This script will:
  - Copy files to the above folder
  - Create Start Menu and Desktop shortcuts
  - Delete the extracted folder
"@

$result = [System.Windows.Forms.MessageBox]::Show(
    $message,
    "YakuLingo Setup",
    [System.Windows.Forms.MessageBoxButtons]::OKCancel,
    [System.Windows.Forms.MessageBoxIcon]::Question
)

if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
    exit 0
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "YakuLingo Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Create destination folder
if (Test-Path $appDir) {
    Write-Host "[INFO] Overwriting existing files..."
}
New-Item -ItemType Directory -Path $appDir -Force | Out-Null

# Copy files
Write-Host "[1/3] Copying files (this may take a while)..."
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Files to copy
$files = @(
    "app.py",
    "pyproject.toml",
    "requirements.txt",
    "glossary.csv",
    "remove.bat",
    "remove.ps1"
)

# Folders to copy (app + dependencies)
$folders = @(
    "ecm_translate",
    "prompts",
    "config",
    ".venv",
    ".uv-python",
    ".playwright-browsers"
)

# Copy run.bat
$runBatSource = Join-Path $scriptDir "run.bat"
if (Test-Path $runBatSource) {
    Copy-Item $runBatSource "$appDir\run.bat" -Force
}

# Copy files
foreach ($file in $files) {
    $source = Join-Path $scriptDir $file
    if (Test-Path $source) {
        Copy-Item $source $appDir -Force
    }
}

# Copy folders
foreach ($folder in $folders) {
    $source = Join-Path $scriptDir $folder
    if (Test-Path $source) {
        Write-Host "  Copying: $folder ..."
        Copy-Item $source $appDir -Recurse -Force
    }
}

Write-Host "[OK] File copy complete"

# Create Start Menu shortcuts
Write-Host "[2/3] Creating shortcuts..."
$startMenuDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"

$shell = New-Object -ComObject WScript.Shell

# YakuLingo shortcut
$shortcut = $shell.CreateShortcut("$startMenuDir\YakuLingo.lnk")
$shortcut.TargetPath = "$appDir\run.bat"
$shortcut.WorkingDirectory = $appDir
$shortcut.IconLocation = "%SystemRoot%\System32\shell32.dll,13"
$shortcut.Description = "YakuLingo - JP/EN Translation Tool"
$shortcut.Save()

# YakuLingo Remove shortcut
$removeShortcut = $shell.CreateShortcut("$startMenuDir\YakuLingo Remove.lnk")
$removeShortcut.TargetPath = "$appDir\remove.bat"
$removeShortcut.WorkingDirectory = $appDir
$removeShortcut.IconLocation = "%SystemRoot%\System32\shell32.dll,131"
$removeShortcut.Description = "Remove YakuLingo"
$removeShortcut.Save()

Write-Host "[OK] Start Menu shortcuts created"

# Desktop shortcut
$desktopPath = [Environment]::GetFolderPath("Desktop")
$desktopShortcut = $shell.CreateShortcut("$desktopPath\YakuLingo.lnk")
$desktopShortcut.TargetPath = "$appDir\run.bat"
$desktopShortcut.WorkingDirectory = $appDir
$desktopShortcut.IconLocation = "%SystemRoot%\System32\shell32.dll,13"
$desktopShortcut.Description = "YakuLingo - JP/EN Translation Tool"
$desktopShortcut.Save()

Write-Host "[OK] Desktop shortcut created"

Write-Host "[3/3] Done"
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "You can launch YakuLingo from the Start Menu or Desktop."
Write-Host ""
Write-Host "Location: $appDir"
Write-Host ""

# Auto-delete extracted folder
$zipFolder = Split-Path -Parent $scriptDir  # YakuLingo folder (parent of _internal)
$cleanupScript = "$env:TEMP\yakulingo_cleanup.ps1"

@"
Start-Sleep -Seconds 3
Remove-Item -Path '$zipFolder' -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path '$cleanupScript' -Force -ErrorAction SilentlyContinue
"@ | Out-File $cleanupScript -Encoding UTF8

# Run in separate process (hidden)
Start-Process powershell -WindowStyle Hidden -ArgumentList "-ExecutionPolicy Bypass -File `"$cleanupScript`""

Write-Host ""
Write-Host "[INFO] The extracted folder will be deleted in a few seconds"
Write-Host ""
Read-Host "Press Enter to exit"
