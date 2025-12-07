# ============================================================
# YakuLingo Network Setup Script
# Copies from shared folder to local machine
# ============================================================

param(
    [string]$SetupPath = "",
    [switch]$GuiMode = $false
)

$ErrorActionPreference = "Stop"

# Script directory (must be resolved at top-level, not inside functions)
$script:ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
$script:ShareDir = Split-Path -Parent $script:ScriptDir

# Find 7-Zip (required for fast extraction)
$script:SevenZip = @(
    "$env:ProgramFiles\7-Zip\7z.exe",
    "${env:ProgramFiles(x86)}\7-Zip\7z.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $script:SevenZip) {
    $script:SevenZip = (Get-Command "7z.exe" -ErrorAction SilentlyContinue).Source
}

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
    $script:stepLabel = $null

    function Show-Progress {
        param([string]$Title, [string]$Status, [int]$Percent = -1, [string]$Step = "")

        if ($script:progressForm -eq $null) {
            $script:progressForm = New-Object System.Windows.Forms.Form
            $script:progressForm.Text = $Title
            $script:progressForm.Size = New-Object System.Drawing.Size(420, 170)
            $script:progressForm.StartPosition = "CenterScreen"
            $script:progressForm.FormBorderStyle = "FixedDialog"
            $script:progressForm.MaximizeBox = $false
            $script:progressForm.MinimizeBox = $false
            $script:progressForm.TopMost = $true

            # Step label (e.g., "Step 2/3")
            $script:stepLabel = New-Object System.Windows.Forms.Label
            $script:stepLabel.Location = New-Object System.Drawing.Point(20, 15)
            $script:stepLabel.Size = New-Object System.Drawing.Size(360, 20)
            $script:stepLabel.Text = $Step
            $script:stepLabel.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
            $script:progressForm.Controls.Add($script:stepLabel)

            # Status label
            $script:progressLabel = New-Object System.Windows.Forms.Label
            $script:progressLabel.Location = New-Object System.Drawing.Point(20, 40)
            $script:progressLabel.Size = New-Object System.Drawing.Size(360, 25)
            $script:progressLabel.Text = $Status
            $script:progressForm.Controls.Add($script:progressLabel)

            # Progress bar
            $script:progressBar = New-Object System.Windows.Forms.ProgressBar
            $script:progressBar.Location = New-Object System.Drawing.Point(20, 75)
            $script:progressBar.Size = New-Object System.Drawing.Size(360, 30)
            $script:progressBar.Minimum = 0
            $script:progressBar.Maximum = 100
            if ($Percent -lt 0) {
                $script:progressBar.Style = "Marquee"
                $script:progressBar.MarqueeAnimationSpeed = 30
            } else {
                $script:progressBar.Style = "Continuous"
                $script:progressBar.Value = $Percent
            }
            $script:progressForm.Controls.Add($script:progressBar)

            $script:progressForm.Show()
            $script:progressForm.Refresh()
        } else {
            if ($Step -ne "") {
                $script:stepLabel.Text = $Step
            }
            $script:progressLabel.Text = $Status
            if ($Percent -ge 0) {
                if ($script:progressBar.Style -ne "Continuous") {
                    $script:progressBar.Style = "Continuous"
                }
                $script:progressBar.Value = [Math]::Min($Percent, 100)
            }
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
        [switch]$Progress,
        [string]$Step = ""
    )
    if ($GuiMode) {
        if ($Progress) {
            Show-Progress -Title "YakuLingo Setup" -Status $Message -Step $Step
        }
    } else {
        Write-Host $Message -ForegroundColor $Color
    }
}

# ============================================================
# Main Setup Logic (wrapped in function for error handling)
# ============================================================
function Invoke-Setup {
    # ============================================================
    # Check requirements
    # ============================================================
    if (-not $script:SevenZip) {
        throw "7-Zip not found.`n`nPlease install 7-Zip from https://7-zip.org/"
    }

    # ============================================================
    # Configuration
    # ============================================================
    $AppName = "YakuLingo"
    # Use script-scope variables defined at top-level
    $ScriptDir = $script:ScriptDir
    $ShareDir = $script:ShareDir

    # Auto-detect ZIP file (use newest one)
    $ZipFiles = Get-ChildItem -Path $ShareDir -Filter "YakuLingo*.zip" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    if ($ZipFiles.Count -eq 0) {
        throw "YakuLingo*.zip not found.`n`nPlease place the ZIP file in the setup folder.`n`nFolder: $ShareDir"
    }
    $ZipFile = $ZipFiles[0].FullName
    $ZipFileName = $ZipFiles[0].Name
    if (-not $GuiMode) {
        Write-Host "[INFO] Using: $ZipFileName" -ForegroundColor Cyan
    }

    # Default path: LocalAppData\YakuLingo
    if ([string]::IsNullOrEmpty($SetupPath)) {
        $SetupPath = Join-Path $env:LOCALAPPDATA $AppName
    }

    # ============================================================
    # Step 1: Prepare destination (backup user data first)
    # ============================================================
    Write-Status -Message "Preparing destination..." -Progress -Step "Step 1/2: Preparing"
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[1/2] Preparing destination..." -ForegroundColor Yellow
    }

    # Backup user data files before removing the directory
    $BackupFiles = @()
    $UserDataFiles = @("glossary.csv", "config\settings.json")
    $BackupDir = Join-Path $env:TEMP "YakuLingo_Backup_$(Get-Date -Format 'yyyyMMddHHmmss')"

    if (Test-Path $SetupPath) {
        foreach ($file in $UserDataFiles) {
            $filePath = Join-Path $SetupPath $file
            if (Test-Path $filePath) {
                if (-not (Test-Path $BackupDir)) {
                    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
                }
                $backupPath = Join-Path $BackupDir $file
                $backupParent = Split-Path -Parent $backupPath
                if (-not (Test-Path $backupParent)) {
                    New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
                }
                Copy-Item -Path $filePath -Destination $backupPath -Force
                $BackupFiles += $file
                if (-not $GuiMode) {
                    Write-Host "      Backed up: $file" -ForegroundColor Gray
                }
            }
        }

        if (-not $GuiMode) {
            Write-Host "      Removing existing files: $SetupPath" -ForegroundColor Gray
        }
        # Fast removal using .NET (handles long paths better than Remove-Item)
        [System.IO.Directory]::Delete($SetupPath, $true)
    }

    if (-not $GuiMode) {
        Write-Host "[OK] Destination ready: $SetupPath" -ForegroundColor Green
    }

    # ============================================================
    # Step 2: Extract ZIP directly to destination
    # ============================================================
    Write-Status -Message "Extracting files..." -Progress -Step "Step 2/2: Extracting files"
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[2/2] Extracting files to destination..." -ForegroundColor Yellow
        Write-Host "      Extracting with 7-Zip..." -ForegroundColor Gray
    }

    # Extract directly to destination parent, then rename (avoids temp + move)
    $ParentDir = Split-Path -Parent $SetupPath
    & $script:SevenZip x "$ZipFile" "-o$ParentDir" -y -bso0 -bsp0 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to extract ZIP file.`n`nFile: $ZipFileName"
    }

    # Find extracted folder and rename to destination
    $ExtractedDir = Get-ChildItem -Path $ParentDir -Directory | Where-Object { $_.Name -like "YakuLingo*" -and $_.FullName -ne $SetupPath } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $ExtractedDir) {
        throw "Failed to extract ZIP file.`n`nFile: $ZipFileName"
    }

    # Rename extracted folder to destination (instant operation)
    if ($ExtractedDir.FullName -ne $SetupPath) {
        Move-Item -Path $ExtractedDir.FullName -Destination $SetupPath -Force
    }

    if (-not $GuiMode) {
        Write-Host "[OK] Extraction completed" -ForegroundColor Green
    }

    # ============================================================
    # Restore backed up user data files
    # ============================================================
    if ($BackupFiles.Count -gt 0) {
        if (-not $GuiMode) {
            Write-Host ""
            Write-Host "      Restoring user data..." -ForegroundColor Gray
        }
        foreach ($file in $BackupFiles) {
            $backupPath = Join-Path $BackupDir $file
            $restorePath = Join-Path $SetupPath $file
            if (Test-Path $backupPath) {
                $restoreParent = Split-Path -Parent $restorePath
                if (-not (Test-Path $restoreParent)) {
                    New-Item -ItemType Directory -Path $restoreParent -Force | Out-Null
                }
                Copy-Item -Path $backupPath -Destination $restorePath -Force
                if (-not $GuiMode) {
                    Write-Host "      Restored: $file" -ForegroundColor Gray
                }
            }
        }
        # Clean up backup directory
        if (Test-Path $BackupDir) {
            Remove-Item -Path $BackupDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (-not $GuiMode) {
            Write-Host "[OK] User data restored" -ForegroundColor Green
        }
    }

    # ============================================================
    # Finalize: Create shortcuts
    # ============================================================
    Write-Status -Message "Creating shortcuts..." -Progress -Step "Finalizing..."
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[OK] Creating shortcuts..." -ForegroundColor Yellow
    }

    $WshShell = New-Object -ComObject WScript.Shell

    # Desktop shortcut - use YakuLingo.exe for silent launch
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $ShortcutPath = Join-Path $DesktopPath "$AppName.lnk"
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $ExePath = Join-Path $SetupPath "YakuLingo.exe"
    $Shortcut.TargetPath = $ExePath
    $Shortcut.WorkingDirectory = $SetupPath
    $Shortcut.IconLocation = "$ExePath,0"
    $Shortcut.Description = "YakuLingo Translation Tool"
    $Shortcut.Save()
    if (-not $GuiMode) {
        Write-Host "      Desktop: $ShortcutPath" -ForegroundColor Gray
        Write-Host "[OK] Shortcuts created" -ForegroundColor Green
    }

    # ============================================================
    # Done
    # ============================================================
    if ($GuiMode) {
        Show-Success "Setup completed!`n`nPlease launch YakuLingo from the desktop shortcut."
    } else {
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host " Setup completed!" -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host ""
        Write-Host " Location: $SetupPath" -ForegroundColor White
        Write-Host " Please launch YakuLingo from the desktop shortcut." -ForegroundColor Cyan
        Write-Host ""
    }
}

# ============================================================
# Execute setup with error handling
# ============================================================
if ($GuiMode) {
    try {
        Invoke-Setup
        exit 0
    } catch {
        Show-Error $_.Exception.Message
        exit 1
    }
} else {
    try {
        Invoke-Setup
        exit 0
    } catch {
        Write-Host ""
        Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
        Write-Host ""
        exit 1
    }
}
