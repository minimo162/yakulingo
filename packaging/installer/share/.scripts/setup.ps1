# ============================================================
# YakuLingo Network Setup Script
# Copies from shared folder to local machine
# ============================================================

param(
    [string]$SetupPath = "",
    [switch]$GuiMode = $false
)

$ErrorActionPreference = "Stop"

# ============================================================
# GUI Helper Functions (for silent setup via VBS)
# ============================================================
if ($GuiMode) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    # Create progress form
    $script:progressForm = $null
    $script:progressBar = $null
    $script:progressLabel = $null

    function Show-Progress {
        param([string]$Title, [string]$Status, [int]$Percent = -1)

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

    # Extract ZIP with progress updates (non-blocking, optimized)
    function Expand-ZipWithProgress {
        param(
            [string]$ZipPath,
            [string]$DestPath
        )

        $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
        try {
            $totalEntries = $zip.Entries.Count
            $currentEntry = 0
            $lastPercent = -1
            $createdDirs = @{}  # Cache created directories

            foreach ($entry in $zip.Entries) {
                $currentEntry++

                # Update UI only when percent changes (reduces DoEvents overhead)
                $percent = [int](($currentEntry / $totalEntries) * 100)
                if ($percent -ne $lastPercent) {
                    $lastPercent = $percent
                    Show-Progress -Title "YakuLingo Setup" -Status "Extracting files... ($percent%)" -Percent $percent
                }

                $destFile = Join-Path $DestPath $entry.FullName

                if ($entry.FullName.EndsWith('/')) {
                    # Directory entry
                    if (-not $createdDirs.ContainsKey($destFile)) {
                        [System.IO.Directory]::CreateDirectory($destFile) | Out-Null
                        $createdDirs[$destFile] = $true
                    }
                } else {
                    # File entry - ensure parent directory exists
                    $destDir = Split-Path -Parent $destFile
                    if (-not $createdDirs.ContainsKey($destDir)) {
                        [System.IO.Directory]::CreateDirectory($destDir) | Out-Null
                        $createdDirs[$destDir] = $true
                    }
                    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destFile, $true)
                }
            }
        } finally {
            $zip.Dispose()
        }
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
if ([string]::IsNullOrEmpty($SetupPath)) {
    $SetupPath = Join-Path $env:LOCALAPPDATA $AppName
}

# ============================================================
# Step 1: Check existing setup
# ============================================================
Write-Status -Message "Checking setup..." -Progress
if (-not $GuiMode) {
    Write-Host ""
    Write-Host "[1/4] Checking destination..." -ForegroundColor Yellow
}

if (Test-Path $SetupPath) {
    if (-not $GuiMode) {
        Write-Host "      Found existing setup: $SetupPath" -ForegroundColor Gray
    }

    # Remove all files (including environment folders for clean setup)
    if (-not $GuiMode) {
        Write-Host "      Removing old files..." -ForegroundColor Gray
    }
    Get-ChildItem -Path $SetupPath | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $GuiMode) {
    Write-Host "[OK] Destination: $SetupPath" -ForegroundColor Green
}

# ============================================================
# Step 2: Prepare temp directory (skip local ZIP copy for speed)
# ============================================================
Write-Status -Message "Preparing..." -Progress
if (-not $GuiMode) {
    Write-Host ""
    Write-Host "[2/4] Preparing extraction..." -ForegroundColor Yellow
}

$TempDir = Join-Path $env:TEMP "YakuLingo_setup_$(Get-Date -Format 'yyyyMMddHHmmss')"
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

# Use network ZIP directly (no local copy - faster)
$LocalZip = $ZipFile

if (-not $GuiMode) {
    Write-Host "[OK] Ready to extract" -ForegroundColor Green
}

# ============================================================
# Step 3: Extract ZIP
# ============================================================
Write-Status -Message "Extracting files..." -Progress
if (-not $GuiMode) {
    Write-Host ""
    Write-Host "[3/4] Extracting files..." -ForegroundColor Yellow
}

# Use custom extraction function with progress for GUI mode
# Both modes use .NET ZipFile for speed (Expand-Archive is slower)
if ($GuiMode) {
    Expand-ZipWithProgress -ZipPath $LocalZip -DestPath $TempDir
} else {
    # Fast extraction using .NET (no progress display)
    Add-Type -Assembly 'System.IO.Compression.FileSystem'
    [System.IO.Compression.ZipFile]::ExtractToDirectory($LocalZip, $TempDir)
}

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
if (-not (Test-Path $SetupPath)) {
    New-Item -ItemType Directory -Path $SetupPath -Force | Out-Null
}

# Copy all files using robocopy for parallel file transfer (much faster)
Write-Status -Message "Copying files to destination..." -Progress
# robocopy /E = include empty dirs, /MT:8 = 8 threads, /NFL /NDL /NJH /NJS /NP = minimal output
$robocopyArgs = @($SourceDir, $SetupPath, "/E", "/MT:8", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")
$robocopyResult = Start-Process -FilePath "robocopy.exe" -ArgumentList $robocopyArgs -NoNewWindow -Wait -PassThru
# robocopy exit codes: 0-7 = success, 8+ = error
if ($robocopyResult.ExitCode -ge 8) {
    # Fallback to Copy-Item if robocopy fails
    Get-ChildItem -Path $SourceDir | ForEach-Object {
        $dest = Join-Path $SetupPath $_.Name
        if ($_.PSIsContainer) {
            Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
        } else {
            Copy-Item -Path $_.FullName -Destination $dest -Force
        }
    }
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
$Shortcut.TargetPath = Join-Path $SetupPath "YakuLingo.exe"
$Shortcut.WorkingDirectory = $SetupPath
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
# Launch application
# ============================================================
Write-Status -Message "Launching YakuLingo..." -Progress
$ExePath = Join-Path $SetupPath "YakuLingo.exe"
Start-Process -FilePath $ExePath -WorkingDirectory $SetupPath

# ============================================================
# Done
# ============================================================
if ($GuiMode) {
    Show-Success "Setup completed!`n`nYakuLingo has been set up and launched."
} else {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host " Setup completed!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host " Location: $SetupPath" -ForegroundColor White
    Write-Host " YakuLingo is now starting..." -ForegroundColor Cyan
    Write-Host ""
}

exit 0
