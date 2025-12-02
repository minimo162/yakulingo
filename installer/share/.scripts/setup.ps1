# ============================================================
# YakuLingo Network Setup Script
# Copies from shared folder to local machine
# ============================================================

param(
    [string]$InstallPath = "",
    [switch]$GuiMode = $false
)

$ErrorActionPreference = "Stop"

# ============================================================
# GUI Helper Functions (for silent setup via VBS)
# ============================================================
if ($GuiMode) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    # Create progress form
    $script:progressForm = $null
    $script:progressBar = $null
    $script:progressLabel = $null

    function Show-Progress {
        param([string]$Title, [string]$Status)

        if ($script:progressForm -eq $null) {
            $script:progressForm = New-Object System.Windows.Forms.Form
            $script:progressForm.Text = $Title
            $script:progressForm.Size = New-Object System.Drawing.Size(400, 150)
            $script:progressForm.StartPosition = "CenterScreen"
            $script:progressForm.FormBorderStyle = "FixedDialog"
            $script:progressForm.MaximizeBox = $false
            $script:progressForm.MinimizeBox = $false
            $script:progressForm.TopMost = $true

            $script:progressLabel = New-Object System.Windows.Forms.Label
            $script:progressLabel.Location = New-Object System.Drawing.Point(20, 20)
            $script:progressLabel.Size = New-Object System.Drawing.Size(340, 30)
            $script:progressLabel.Text = $Status
            $script:progressForm.Controls.Add($script:progressLabel)

            $script:progressBar = New-Object System.Windows.Forms.ProgressBar
            $script:progressBar.Location = New-Object System.Drawing.Point(20, 60)
            $script:progressBar.Size = New-Object System.Drawing.Size(340, 30)
            $script:progressBar.Style = "Marquee"
            $script:progressBar.MarqueeAnimationSpeed = 30
            $script:progressForm.Controls.Add($script:progressBar)

            $script:progressForm.Show()
            $script:progressForm.Refresh()
        } else {
            $script:progressLabel.Text = $Status
            $script:progressForm.Refresh()
        }
        [System.Windows.Forms.Application]::DoEvents()
    }

    function Close-Progress {
        if ($script:progressForm -ne $null) {
            $script:progressForm.Close()
            $script:progressForm.Dispose()
            $script:progressForm = $null
        }
    }

    function Show-Error {
        param([string]$Message)
        Close-Progress
        [System.Windows.Forms.MessageBox]::Show(
            $Message,
            "YakuLingo Setup - Error",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }

    function Show-Success {
        param([string]$Message)
        Close-Progress
        [System.Windows.Forms.MessageBox]::Show(
            $Message,
            "YakuLingo Setup",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    }
}

# Console output wrapper (respects GuiMode)
function Write-Status {
    param(
        [string]$Message,
        [string]$Color = "White",
        [switch]$Progress
    )
    if ($GuiMode) {
        if ($Progress) {
            Show-Progress -Title "YakuLingo Setup" -Status $Message
        }
    } else {
        Write-Host $Message -ForegroundColor $Color
    }
}

# ============================================================
# Configuration
# ============================================================
$AppName = "YakuLingo"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ShareDir = Split-Path -Parent $ScriptDir  # Parent of .scripts folder

# Auto-detect ZIP file (use newest one)
$ZipFiles = Get-ChildItem -Path $ShareDir -Filter "YakuLingo*.zip" | Sort-Object LastWriteTime -Descending
if ($ZipFiles.Count -eq 0) {
    if ($GuiMode) {
        Show-Error "YakuLingo*.zip not found.`n`nPlease place the ZIP file in the setup folder."
    } else {
        Write-Host "[ERROR] YakuLingo*.zip not found." -ForegroundColor Red
        Write-Host "        Please place the ZIP file in the setup folder." -ForegroundColor Red
    }
    exit 1
}
$ZipFile = $ZipFiles[0].FullName
$ZipFileName = $ZipFiles[0].Name
if (-not $GuiMode) {
    Write-Host "[INFO] Using: $ZipFileName" -ForegroundColor Cyan
}

# Default path: LocalAppData\YakuLingo
if ([string]::IsNullOrEmpty($InstallPath)) {
    $InstallPath = Join-Path $env:LOCALAPPDATA $AppName
}

# ============================================================
# Step 1: Check existing installation
# ============================================================
Write-Status -Message "Checking installation..." -Progress
if (-not $GuiMode) {
    Write-Host ""
    Write-Host "[1/4] Checking destination..." -ForegroundColor Yellow
}

if (Test-Path $InstallPath) {
    if (-not $GuiMode) {
        Write-Host "      Found existing installation: $InstallPath" -ForegroundColor Gray
    }

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
            if (-not $GuiMode) {
                Write-Host "      Backed up: $file" -ForegroundColor Gray
            }
        }
    }

    # Remove old files (keep environment folders)
    if (-not $GuiMode) {
        Write-Host "      Removing old source files..." -ForegroundColor Gray
    }
    $KeepDirs = @(".venv", ".uv-python", ".playwright-browsers")
    Get-ChildItem -Path $InstallPath | Where-Object {
        $_.Name -notin $KeepDirs
    } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $GuiMode) {
    Write-Host "[OK] Destination: $InstallPath" -ForegroundColor Green
}

# ============================================================
# Step 2: Copy ZIP to local
# ============================================================
Write-Status -Message "Copying files..." -Progress
if (-not $GuiMode) {
    Write-Host ""
    Write-Host "[2/4] Copying files..." -ForegroundColor Yellow
}

$TempDir = Join-Path $env:TEMP "YakuLingo_setup_$(Get-Date -Format 'yyyyMMddHHmmss')"
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

$LocalZip = Join-Path $TempDir $ZipFileName
Copy-Item -Path $ZipFile -Destination $LocalZip -Force

if (-not $GuiMode) {
    Write-Host "[OK] Copy completed" -ForegroundColor Green
}

# ============================================================
# Step 3: Extract ZIP
# ============================================================
Write-Status -Message "Extracting files..." -Progress
if (-not $GuiMode) {
    Write-Host ""
    Write-Host "[3/4] Extracting files..." -ForegroundColor Yellow
}

Expand-Archive -Path $LocalZip -DestinationPath $TempDir -Force

# Find extracted folder (YakuLingo*)
$ExtractedDir = Get-ChildItem -Path $TempDir -Directory | Where-Object { $_.Name -like "YakuLingo*" } | Select-Object -First 1

if (-not $ExtractedDir) {
    if ($GuiMode) {
        Show-Error "Failed to extract ZIP file."
    } else {
        Write-Host "[ERROR] Failed to extract ZIP file." -ForegroundColor Red
    }
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
    if (-not $GuiMode) {
        Write-Host "      Restoring user settings..." -ForegroundColor Gray
    }
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

if (-not $GuiMode) {
    Write-Host "[OK] Extraction completed" -ForegroundColor Green
}

# ============================================================
# Step 4: Create shortcuts
# ============================================================
Write-Status -Message "Creating shortcuts..." -Progress
if (-not $GuiMode) {
    Write-Host ""
    Write-Host "[4/4] Creating shortcuts..." -ForegroundColor Yellow
}

$WshShell = New-Object -ComObject WScript.Shell

# Desktop shortcut - use YakuLingo.exe for silent launch
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "$AppName.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $InstallPath "YakuLingo.exe"
$Shortcut.WorkingDirectory = $InstallPath
$Shortcut.IconLocation = "shell32.dll,21"
$Shortcut.Description = "YakuLingo Translation Tool"
$Shortcut.Save()
if (-not $GuiMode) {
    Write-Host "      Desktop: $ShortcutPath" -ForegroundColor Gray
}

if (-not $GuiMode) {
    Write-Host "[OK] Shortcuts created" -ForegroundColor Green
}

# ============================================================
# Cleanup
# ============================================================
Remove-Item -Path $TempDir -Recurse -Force -ErrorAction SilentlyContinue

# ============================================================
# Done
# ============================================================
if ($GuiMode) {
    Show-Success "Setup completed!`n`nYakuLingo has been installed.`n`nTo launch:`n  - Double-click the 'YakuLingo' shortcut on your desktop"
} else {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host " Setup completed!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host " Location: $InstallPath" -ForegroundColor White
    Write-Host ""
    Write-Host " To launch:" -ForegroundColor White
    Write-Host "   - Double-click the '$AppName' shortcut on your desktop" -ForegroundColor Gray
    Write-Host ""
}

exit 0
