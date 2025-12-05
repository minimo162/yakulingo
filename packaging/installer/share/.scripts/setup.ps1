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

    # Extract ZIP directly to destination with progress (skip temp dir + robocopy)
    function Expand-ZipDirectWithProgress {
        param(
            [string]$ZipPath,
            [string]$DestPath,
            [string]$StripPrefix  # e.g., "YakuLingo/" to strip from entry paths
        )

        $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
        try {
            $totalEntries = $zip.Entries.Count
            $currentEntry = 0
            $lastPercent = -1
            $createdDirs = @{}  # Cache created directories
            $bufferSize = 81920  # 80KB buffer for faster copying

            foreach ($entry in $zip.Entries) {
                $currentEntry++

                # Update UI only every 2% (reduces DoEvents overhead significantly)
                $percent = [int](($currentEntry / $totalEntries) * 100)
                if ($percent -ge $lastPercent + 2 -or $percent -eq 100) {
                    $lastPercent = $percent
                    Show-Progress -Title "YakuLingo Setup" -Status "Extracting... ($currentEntry / $totalEntries files)" -Percent $percent -Step "Step 2/3: Extracting files"
                }

                # Get relative path, stripping prefix if present
                $entryPath = $entry.FullName
                if ($StripPrefix -and $entryPath.StartsWith($StripPrefix)) {
                    $entryPath = $entryPath.Substring($StripPrefix.Length)
                }

                # Skip empty paths (the prefix directory itself)
                if ([string]::IsNullOrEmpty($entryPath)) {
                    continue
                }

                $destFile = Join-Path $DestPath $entryPath

                if ($entry.FullName.EndsWith('/')) {
                    # Directory entry
                    if (-not $createdDirs.ContainsKey($destFile)) {
                        [System.IO.Directory]::CreateDirectory($destFile) | Out-Null
                        $createdDirs[$destFile] = $true
                    }
                } else {
                    # File entry - ensure parent directory exists
                    $destDir = [System.IO.Path]::GetDirectoryName($destFile)
                    if (-not $createdDirs.ContainsKey($destDir)) {
                        [System.IO.Directory]::CreateDirectory($destDir) | Out-Null
                        $createdDirs[$destDir] = $true
                    }

                    # Use buffered streams for faster extraction
                    $entryStream = $entry.Open()
                    try {
                        $fileStream = [System.IO.File]::Create($destFile)
                        try {
                            $entryStream.CopyTo($fileStream, $bufferSize)
                        } finally {
                            $fileStream.Close()
                        }
                    } finally {
                        $entryStream.Close()
                    }
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
        $script:SetupPath = Join-Path $env:LOCALAPPDATA $AppName
    }

    # ============================================================
    # Step 1: Prepare destination
    # ============================================================
    Write-Status -Message "Preparing destination..." -Progress -Step "Step 1/3: Preparing"
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[1/3] Preparing destination..." -ForegroundColor Yellow
    }

    if (Test-Path $SetupPath) {
        if (-not $GuiMode) {
            Write-Host "      Removing existing files: $SetupPath" -ForegroundColor Gray
        }
        # Fast parallel removal using robocopy (mirror empty dir is faster than Remove-Item)
        $emptyDir = Join-Path $env:TEMP "empty_$(Get-Date -Format 'yyyyMMddHHmmss')"
        New-Item -ItemType Directory -Path $emptyDir -Force | Out-Null
        $robocopyArgs = @($emptyDir, $SetupPath, "/MIR", "/MT:8", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")
        Start-Process -FilePath "robocopy.exe" -ArgumentList $robocopyArgs -NoNewWindow -Wait | Out-Null
        Remove-Item -Path $emptyDir -Force -ErrorAction SilentlyContinue
        Remove-Item -Path $SetupPath -Force -ErrorAction SilentlyContinue
    }

    # Create destination directory
    New-Item -ItemType Directory -Path $SetupPath -Force | Out-Null

    if (-not $GuiMode) {
        Write-Host "[OK] Destination ready: $SetupPath" -ForegroundColor Green
    }

    # ============================================================
    # Step 2: Extract ZIP directly to destination (skip temp + robocopy)
    # ============================================================
    Write-Status -Message "Extracting files..." -Progress -Step "Step 2/3: Extracting files"
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[2/3] Extracting files directly to destination..." -ForegroundColor Yellow
    }

    # Determine the prefix to strip (e.g., "YakuLingo/")
    Add-Type -Assembly 'System.IO.Compression.FileSystem'
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipFile)
    $firstEntry = $zip.Entries | Select-Object -First 1
    $stripPrefix = ""
    if ($firstEntry -and $firstEntry.FullName -match "^([^/]+)/") {
        $stripPrefix = $Matches[1] + "/"
    }
    $zip.Dispose()

    if ($GuiMode) {
        # Direct extraction with progress (no temp dir, no robocopy)
        Expand-ZipDirectWithProgress -ZipPath $ZipFile -DestPath $SetupPath -StripPrefix $stripPrefix
    } else {
        # Console mode: extract to temp then move (allows for progress bar via robocopy)
        $TempDir = Join-Path $env:TEMP "YakuLingo_setup_$(Get-Date -Format 'yyyyMMddHHmmss')"
        [System.IO.Compression.ZipFile]::ExtractToDirectory($ZipFile, $TempDir)

        # Find extracted folder
        $ExtractedDir = Get-ChildItem -Path $TempDir -Directory | Where-Object { $_.Name -like "YakuLingo*" } | Select-Object -First 1
        if (-not $ExtractedDir) {
            throw "Failed to extract ZIP file.`n`nFile: $ZipFileName"
        }

        # Move files using robocopy (fast with progress)
        Write-Host "      Copying files..." -ForegroundColor Gray
        $robocopyArgs = @($ExtractedDir.FullName, $SetupPath, "/E", "/MOVE", "/MT:16", "/NFL", "/NDL", "/NJH", "/NJS", "/R:1", "/W:1")
        Start-Process -FilePath "robocopy.exe" -ArgumentList $robocopyArgs -NoNewWindow -Wait | Out-Null

        # Cleanup temp
        Remove-Item -Path $TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    if (-not $GuiMode) {
        Write-Host "[OK] Extraction completed" -ForegroundColor Green
    }

    # ============================================================
    # Step 3: Create shortcuts
    # ============================================================
    Write-Status -Message "Creating shortcuts..." -Progress -Step "Step 3/3: Finalizing"
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[3/3] Creating shortcuts..." -ForegroundColor Yellow
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
    # Launch application
    # ============================================================
    Write-Status -Message "Launching YakuLingo..." -Progress -Step "Complete!"
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
