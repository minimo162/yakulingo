# ============================================================
# YakuLingo Network Setup Script
# Copies from shared folder to local machine
# ============================================================

param(
    [string]$InstallPath = ""
)

$ErrorActionPreference = "Stop"

# ============================================================
# Configuration
# ============================================================
$AppName = "YakuLingo"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ShareDir = Split-Path -Parent $ScriptDir  # Parent of .scripts folder

# Auto-detect ZIP file (use newest one)
$ZipFiles = Get-ChildItem -Path $ShareDir -Filter "YakuLingo*.zip" | Sort-Object LastWriteTime -Descending
if ($ZipFiles.Count -eq 0) {
    Write-Host "[ERROR] YakuLingo*.zip not found." -ForegroundColor Red
    Write-Host "        Please place the ZIP file in the setup folder." -ForegroundColor Red
    exit 1
}
$ZipFile = $ZipFiles[0].FullName
$ZipFileName = $ZipFiles[0].Name
Write-Host "[INFO] Using: $ZipFileName" -ForegroundColor Cyan

# Default path: LocalAppData\YakuLingo
if ([string]::IsNullOrEmpty($InstallPath)) {
    $InstallPath = Join-Path $env:LOCALAPPDATA $AppName
}

# ============================================================
# Step 1: Check existing installation
# ============================================================
Write-Host ""
Write-Host "[1/4] Checking destination..." -ForegroundColor Yellow

if (Test-Path $InstallPath) {
    Write-Host "      Found existing installation: $InstallPath" -ForegroundColor Gray

    # Backup user files
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
            Write-Host "      Backed up: $file" -ForegroundColor Gray
        }
    }

    # Remove old files (keep environment folders)
    Write-Host "      Removing old source files..." -ForegroundColor Gray
    $KeepDirs = @(".venv", ".uv-python", ".playwright-browsers")
    Get-ChildItem -Path $InstallPath | Where-Object {
        $_.Name -notin $KeepDirs
    } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "[OK] Destination: $InstallPath" -ForegroundColor Green

# ============================================================
# Step 2: Copy ZIP to local
# ============================================================
Write-Host ""
Write-Host "[2/4] Copying files..." -ForegroundColor Yellow

$TempDir = Join-Path $env:TEMP "YakuLingo_setup_$(Get-Date -Format 'yyyyMMddHHmmss')"
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

$LocalZip = Join-Path $TempDir $ZipFileName
Copy-Item -Path $ZipFile -Destination $LocalZip -Force

Write-Host "[OK] Copy completed" -ForegroundColor Green

# ============================================================
# Step 3: Extract ZIP
# ============================================================
Write-Host ""
Write-Host "[3/4] Extracting files..." -ForegroundColor Yellow

Expand-Archive -Path $LocalZip -DestinationPath $TempDir -Force

# Find extracted folder (YakuLingo*)
$ExtractedDir = Get-ChildItem -Path $TempDir -Directory | Where-Object { $_.Name -like "YakuLingo*" } | Select-Object -First 1

if (-not $ExtractedDir) {
    Write-Host "[ERROR] Failed to extract ZIP file." -ForegroundColor Red
    exit 1
}

# Use _internal folder if present
$InternalDir = Join-Path $ExtractedDir.FullName "_internal"
if (Test-Path $InternalDir) {
    $SourceDir = $InternalDir
} else {
    $SourceDir = $ExtractedDir.FullName
}

# Create destination directory
if (-not (Test-Path $InstallPath)) {
    New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
}

# Copy files
Get-ChildItem -Path $SourceDir | ForEach-Object {
    $dest = Join-Path $InstallPath $_.Name
    if ($_.PSIsContainer) {
        # Skip environment folders if they already exist
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

# Restore user files from backup
if ($BackupDir -and (Test-Path $BackupDir)) {
    Write-Host "      Restoring user settings..." -ForegroundColor Gray
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

Write-Host "[OK] Extraction completed" -ForegroundColor Green

# ============================================================
# Step 4: Create shortcuts
# ============================================================
Write-Host ""
Write-Host "[4/4] Creating shortcuts..." -ForegroundColor Yellow

$WshShell = New-Object -ComObject WScript.Shell

# Desktop shortcut
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "$AppName.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $InstallPath "run.bat"
$Shortcut.WorkingDirectory = $InstallPath
$Shortcut.IconLocation = "shell32.dll,21"
$Shortcut.Description = "YakuLingo Translation Tool"
$Shortcut.Save()
Write-Host "      Desktop: $ShortcutPath" -ForegroundColor Gray

# Start Menu shortcut
$StartMenuPath = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$StartShortcutPath = Join-Path $StartMenuPath "$AppName.lnk"
$StartShortcut = $WshShell.CreateShortcut($StartShortcutPath)
$StartShortcut.TargetPath = Join-Path $InstallPath "run.bat"
$StartShortcut.WorkingDirectory = $InstallPath
$StartShortcut.IconLocation = "shell32.dll,21"
$StartShortcut.Description = "YakuLingo Translation Tool"
$StartShortcut.Save()
Write-Host "      Start Menu: $StartShortcutPath" -ForegroundColor Gray

# Start Menu Remove shortcut
$RemoveShortcutPath = Join-Path $StartMenuPath "$AppName Remove.lnk"
$RemoveShortcut = $WshShell.CreateShortcut($RemoveShortcutPath)
$RemoveShortcut.TargetPath = Join-Path $InstallPath "remove.bat"
$RemoveShortcut.WorkingDirectory = $InstallPath
$RemoveShortcut.IconLocation = "shell32.dll,131"
$RemoveShortcut.Description = "Remove YakuLingo"
$RemoveShortcut.Save()
Write-Host "      Start Menu: $RemoveShortcutPath" -ForegroundColor Gray

Write-Host "[OK] Shortcuts created" -ForegroundColor Green

# ============================================================
# Cleanup
# ============================================================
Remove-Item -Path $TempDir -Recurse -Force -ErrorAction SilentlyContinue

# ============================================================
# Done
# ============================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Setup completed!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host " Location: $InstallPath" -ForegroundColor White
Write-Host ""
Write-Host " To launch:" -ForegroundColor White
Write-Host "   - Double-click the '$AppName' shortcut on your desktop" -ForegroundColor Gray
Write-Host "   - Or search '$AppName' in the Start Menu" -ForegroundColor Gray
Write-Host ""

exit 0
