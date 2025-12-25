# ============================================================
# YakuLingo Network Setup Script
# Copies from shared folder to local machine
# ============================================================

param(
    [string]$SetupPath = "",
    [switch]$GuiMode = $false,
    [string]$ShareDir = ""  # Original share directory (passed when script is copied to TEMP due to non-ASCII path)
)

$ErrorActionPreference = "Stop"

# Debug log for troubleshooting (write to TEMP)
$debugLog = Join-Path $env:TEMP "YakuLingo_setup_debug.log"
try {
    "=== Setup started: $(Get-Date) ===" | Out-File -FilePath $debugLog -Encoding UTF8
    "PSScriptRoot: $PSScriptRoot" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    "MyInvocation.MyCommand.Definition: $($MyInvocation.MyCommand.Definition)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    "SetupPath param: $SetupPath" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    "GuiMode param: $GuiMode" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    "ShareDir param: $ShareDir" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    "YAKULINGO_SHARE_DIR env: $env:YAKULINGO_SHARE_DIR" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    "TEMP: $env:TEMP" | Out-File -FilePath $debugLog -Append -Encoding UTF8
} catch {
    # Ignore logging errors
}

# Global error handler - writes error to stderr for VBS to capture
function Write-ErrorLog {
    param(
        [System.Management.Automation.ErrorRecord]$ErrorRecord
    )

    if (-not $ErrorRecord) { return }

    $errorMsg = "PowerShell Error: $($ErrorRecord.Exception.Message)`nAt: $($ErrorRecord.InvocationInfo.PositionMessage)"
    [Console]::Error.WriteLine($errorMsg)
}

trap {
    # Write error to debug log (more reliable than stderr capture)
    try {
        "=== ERROR: $(Get-Date) ===" | Out-File -FilePath $debugLog -Append -Encoding UTF8
        "Exception: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
        "ScriptStackTrace: $($_.ScriptStackTrace)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
        "InvocationInfo: $($_.InvocationInfo.PositionMessage)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    } catch { }
    Write-ErrorLog -ErrorRecord $_
    exit 1
}

# Script directory (must be resolved at top-level, not inside functions)
$script:ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }

# Debug: Log script directory resolution
try {
    "ScriptDir resolved: $($script:ScriptDir)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
} catch { }

# Use provided ShareDir if available (when script is copied to TEMP due to non-ASCII path)
# Priority: 1. File (Unicode safe), 2. Environment variable, 3. Parameter, 4. Derive from script location
$shareDirFile = Join-Path $script:ScriptDir "share_dir.txt"
try {
    "shareDirFile path: $shareDirFile" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    "shareDirFile exists: $(Test-Path $shareDirFile)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
} catch { }

if (Test-Path $shareDirFile) {
    # Read UTF-16 LE file (written by VBS CreateTextFile with Unicode flag)
    try {
        "Reading share_dir.txt as UTF-16 LE..." | Out-File -FilePath $debugLog -Append -Encoding UTF8
    } catch { }
    $script:ShareDir = [System.IO.File]::ReadAllText($shareDirFile, [System.Text.Encoding]::Unicode).Trim()
    try {
        "ShareDir from file: $($script:ShareDir)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    } catch { }
} elseif (-not [string]::IsNullOrEmpty($env:YAKULINGO_SHARE_DIR)) {
    $script:ShareDir = $env:YAKULINGO_SHARE_DIR
    try { "ShareDir from env: $($script:ShareDir)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
} elseif (-not [string]::IsNullOrEmpty($ShareDir)) {
    $script:ShareDir = $ShareDir
    try { "ShareDir from param: $($script:ShareDir)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
} else {
    $script:ShareDir = Split-Path -Parent $script:ScriptDir
    try { "ShareDir from parent: $($script:ShareDir)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
}
$script:AppName = "YakuLingo"

# Debug: Log resolved paths
try {
    "ScriptDir: $($script:ScriptDir)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    "ShareDir: $($script:ShareDir)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    "ShareDir exists: $(Test-Path $script:ShareDir)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
} catch { }

# Find 7-Zip (optional, falls back to Expand-Archive if not found)
# Check multiple locations including registry for reliable detection
$script:SevenZip = $null

# Method 1: Check standard installation paths
$standardPaths = @(
    "$env:ProgramFiles\7-Zip\7z.exe",
    "$env:ProgramW6432\7-Zip\7z.exe",
    "${env:ProgramFiles(x86)}\7-Zip\7z.exe"
)
# Also check with explicit path construction for reliability
$standardPaths += @(
    [System.IO.Path]::Combine($env:ProgramFiles, "7-Zip", "7z.exe")
)
if ($env:ProgramW6432) {
    $standardPaths += [System.IO.Path]::Combine($env:ProgramW6432, "7-Zip", "7z.exe")
}
$x86Path = [Environment]::GetFolderPath("ProgramFilesX86")
if ($x86Path) {
    $standardPaths += [System.IO.Path]::Combine($x86Path, "7-Zip", "7z.exe")
}

foreach ($path in $standardPaths | Select-Object -Unique) {
    if ($path -and (Test-Path $path)) {
        $script:SevenZip = $path
        break
    }
}

# Method 2: Check registry for installation path
if (-not $script:SevenZip) {
    $regPaths = @(
        "HKLM:\SOFTWARE\7-Zip",
        "HKLM:\SOFTWARE\WOW6432Node\7-Zip",
        "HKCU:\SOFTWARE\7-Zip"
    )
    foreach ($regPath in $regPaths) {
        try {
            $installPath = (Get-ItemProperty -Path $regPath -Name "Path" -ErrorAction SilentlyContinue).Path
            if ($installPath) {
                $candidate = Join-Path $installPath "7z.exe"
                if (Test-Path $candidate) {
                    $script:SevenZip = $candidate
                    break
                }
            }
        } catch {
            # Ignore registry access errors
        }
    }
}

# Method 3: Check PATH
if (-not $script:SevenZip) {
    $script:SevenZip = (Get-Command "7z.exe" -ErrorAction SilentlyContinue).Source
}

# Flag to track extraction method
$script:Use7Zip = [bool]$script:SevenZip

# ============================================================
# GUI Helper Functions (for silent setup via VBS)
# ============================================================
if ($GuiMode) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    # Cancellation flag
    $script:cancelled = $false

    # Create progress form
    $script:progressForm = $null
    $script:progressBar = $null
    $script:progressLabel = $null
    $script:stepLabel = $null
    $script:cancelButton = $null

    function Show-Progress {
        param([string]$Title, [string]$Status, [int]$Percent = -1, [string]$Step = "")

        # If cancelled, do nothing
        if ($script:cancelled) { return }

        if ($script:progressForm -eq $null) {
            $script:progressForm = New-Object System.Windows.Forms.Form
            $script:progressForm.Text = $Title
            $script:progressForm.Size = New-Object System.Drawing.Size(420, 200)
            $script:progressForm.StartPosition = "CenterScreen"
            $script:progressForm.FormBorderStyle = "FixedDialog"
            $script:progressForm.MaximizeBox = $false
            $script:progressForm.MinimizeBox = $false
            $script:progressForm.TopMost = $true

            # Handle form closing (X button) as cancel
            $script:progressForm.add_FormClosing({
                param($sender, $e)
                if (-not $script:cancelled) {
                    $script:cancelled = $true
                }
            })

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

            # Cancel button
            $script:cancelButton = New-Object System.Windows.Forms.Button
            $script:cancelButton.Location = New-Object System.Drawing.Point(160, 120)
            $script:cancelButton.Size = New-Object System.Drawing.Size(100, 30)
            $script:cancelButton.Text = "キャンセル"
            $script:cancelButton.add_Click({
                $script:cancelled = $true
                $script:cancelButton.Enabled = $false
                $script:cancelButton.Text = "中止中..."
                $script:progressLabel.Text = "キャンセル中..."
                $script:progressForm.Refresh()
            })
            $script:progressForm.Controls.Add($script:cancelButton)

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

    # Check if cancelled and throw if so
    function Test-Cancelled {
        [System.Windows.Forms.Application]::DoEvents()
        if ($script:cancelled) {
            throw "セットアップがキャンセルされました。"
        }
    }

    function Show-Error {
        param([string]$Message)
        Close-Progress

        # 前面表示用の親フォームを作成
        $ownerForm = New-Object System.Windows.Forms.Form
        $ownerForm.TopMost = $true
        $ownerForm.StartPosition = "CenterScreen"
        $ownerForm.Width = 0
        $ownerForm.Height = 0
        $ownerForm.FormBorderStyle = "None"
        $ownerForm.ShowInTaskbar = $false
        $ownerForm.Show()
        $ownerForm.Activate()

        [System.Windows.Forms.MessageBox]::Show(
            $ownerForm,
            $Message,
            "YakuLingo Setup - Error",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null

        $ownerForm.Close()
        $ownerForm.Dispose()
    }

    function Show-Success {
        param([string]$Message)
        Close-Progress

        # 前面表示用の親フォームを作成
        $ownerForm = New-Object System.Windows.Forms.Form
        $ownerForm.TopMost = $true
        $ownerForm.StartPosition = "CenterScreen"
        $ownerForm.Width = 0
        $ownerForm.Height = 0
        $ownerForm.FormBorderStyle = "None"
        $ownerForm.ShowInTaskbar = $false
        $ownerForm.Show()
        $ownerForm.Activate()

        [System.Windows.Forms.MessageBox]::Show(
            $ownerForm,
            $Message,
            "YakuLingo Setup",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null

        $ownerForm.Close()
        $ownerForm.Dispose()
    }
}

# Console output wrapper (respects GuiMode)
function Write-Status {
    param(
        [string]$Message,
        [string]$Color = "White",
        [switch]$Progress,
        [string]$Step = "",
        [int]$Percent = -1
    )
    if ($GuiMode) {
        if ($Progress) {
            Show-Progress -Title "YakuLingo Setup" -Status $Message -Step $Step -Percent $Percent
        }
    } else {
        Write-Host $Message -ForegroundColor $Color
    }
}

# ============================================================
# Helper Functions
# ============================================================
function Get-LatestZipFile {
    param(
        [string]$ShareDir
    )

    $zip = Get-ChildItem -Path $ShareDir -Filter "YakuLingo*.zip" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $zip) {
        throw "YakuLingo*.zip not found.`n`nPlease place the ZIP file in the setup folder.`n`nFolder: $ShareDir"
    }
    return $zip
}

function Test-IsUnderPath {
    param(
        [string]$Path,
        [string]$Root
    )

    if ([string]::IsNullOrEmpty($Path) -or [string]::IsNullOrEmpty($Root)) {
        return $false
    }

    try {
        $normalizedPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
        $normalizedRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
        return $normalizedPath.StartsWith($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase)
    } catch {
        return $false
    }
}

function Resolve-SetupPath {
    param(
        [string]$InputPath,
        [string]$AppName
    )

    $targetPath = if ([string]::IsNullOrEmpty($InputPath)) { Join-Path $env:LOCALAPPDATA $AppName } else { $InputPath }

    $resolvedPath = $targetPath
    try {
        $resolvedPath = (Resolve-Path -Path $targetPath -ErrorAction Stop).ProviderPath
    } catch {
        # Path does not exist yet; keep original
    }

    # Debug: Log the resolved path
    try {
        "Resolve-SetupPath: InputPath='$InputPath' AppName='$AppName'" | Out-File -FilePath $debugLog -Append -Encoding UTF8
        "Resolve-SetupPath: targetPath='$targetPath'" | Out-File -FilePath $debugLog -Append -Encoding UTF8
        "Resolve-SetupPath: resolvedPath='$resolvedPath'" | Out-File -FilePath $debugLog -Append -Encoding UTF8
        "Resolve-SetupPath: LOCALAPPDATA='$env:LOCALAPPDATA'" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    } catch { }

    # Debug: Log that we're about to check dangerous roots
    try {
        "Resolve-SetupPath: Checking drive root..." | Out-File -FilePath $debugLog -Append -Encoding UTF8
    } catch { }

    $driveRoot = [System.IO.Path]::GetPathRoot($resolvedPath)
    if ($resolvedPath -eq $driveRoot) {
        throw "SetupPath points to a drive root. Please specify a subdirectory (e.g., $($env:LOCALAPPDATA)\\$AppName)."
    }

    # Build dangerous roots list safely (some GetFolderPath calls may fail on certain systems)
    $dangerousRoots = @()
    if ($env:USERPROFILE) { $dangerousRoots += $env:USERPROFILE }
    if ($env:LOCALAPPDATA) { $dangerousRoots += $env:LOCALAPPDATA }
    if ($env:APPDATA) { $dangerousRoots += $env:APPDATA }
    try { $path = [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows); if ($path) { $dangerousRoots += $path } } catch { }
    try { $path = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles); if ($path) { $dangerousRoots += $path } } catch { }
    try { $path = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86); if ($path) { $dangerousRoots += $path } } catch { }
    try { $path = [Environment]::GetFolderPath([Environment+SpecialFolder]::System); if ($path) { $dangerousRoots += $path } } catch { }
    try { $path = [Environment]::GetFolderPath([Environment+SpecialFolder]::SystemX86); if ($path) { $dangerousRoots += $path } } catch { }

    # Debug: Log the number of dangerous roots found
    try {
        "Resolve-SetupPath: Found $($dangerousRoots.Count) dangerous roots to check" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    } catch { }

    foreach ($dangerousRoot in $dangerousRoots) {
        if ($resolvedPath.TrimEnd('\\') -eq $dangerousRoot.TrimEnd('\\')) {
            throw "SetupPath cannot be a system directory: $resolvedPath"
        }
    }

    # Prevent installing into OneDrive-synced folders to avoid sync-related corruption
    $oneDriveRoots = @()
    foreach ($envVar in @("OneDrive", "OneDriveCommercial", "OneDriveConsumer")) {
        $value = (Get-Item "Env:$envVar" -ErrorAction SilentlyContinue).Value
        if (-not [string]::IsNullOrEmpty($value)) {
            $oneDriveRoots += $value
        }
    }
    $oneDriveRoots = $oneDriveRoots | Select-Object -Unique

    foreach ($root in $oneDriveRoots) {
        if (Test-IsUnderPath -Path $resolvedPath -Root $root -or Test-IsUnderPath -Path $targetPath -Root $root) {
            throw "SetupPath cannot be inside OneDrive: $resolvedPath`n`nPlease use a local path such as $($env:LOCALAPPDATA)\\$AppName."
        }
    }
    if ($resolvedPath -match "\\\\OneDrive(\\\\|$)") {
        throw "SetupPath appears to be under OneDrive: $resolvedPath`n`nPlease use a local path such as $($env:LOCALAPPDATA)\\$AppName."
    }

    # Debug: Log successful completion
    try {
        "Resolve-SetupPath: Returning targetPath='$targetPath'" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    } catch { }

    return $targetPath
}

function Prepare-TempWorkspace {
    param(
        [string]$ZipFileName
    )

    # Create new temp folder with timestamp (old folders are cleaned up by Windows automatically)
    $TempZipDir = Join-Path $env:TEMP "YakuLingo_Setup_$(Get-Date -Format 'yyyyMMddHHmmss')"
    New-Item -ItemType Directory -Path $TempZipDir -Force | Out-Null

    return @{ TempZipDir = $TempZipDir; TempZipFile = Join-Path $TempZipDir $ZipFileName }
}

function Copy-FileBuffered {
    param(
        [string]$Source,
        [string]$Destination,
        [int]$BufferSize = 1MB,
        [int]$MaxRetries = 4,
        [scriptblock]$OnProgress = $null
    )

    $retryDelays = @(2, 4, 8, 16)  # Exponential backoff in seconds
    $lastError = $null

    for ($attempt = 0; $attempt -le $MaxRetries; $attempt++) {
        $sourceStream = $null
        $destStream = $null
        try {
            # Use ReadWrite + Delete sharing to allow other processes to delete/modify the file
            # This prevents SMB file locks from persisting on the server when script is interrupted
            $sourceStream = [System.IO.File]::Open($Source, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
            $destStream = [System.IO.File]::Create($Destination, $BufferSize)
            $totalBytes = $sourceStream.Length
            $copiedBytes = 0
            $buffer = New-Object byte[] $BufferSize
            $lastProgressUpdate = [DateTime]::Now

            while ($true) {
                $bytesRead = $sourceStream.Read($buffer, 0, $BufferSize)
                if ($bytesRead -eq 0) { break }
                $destStream.Write($buffer, 0, $bytesRead)
                $copiedBytes += $bytesRead

                # Update progress every 200ms to avoid GUI overhead
                $now = [DateTime]::Now
                if (($now - $lastProgressUpdate).TotalMilliseconds -ge 200) {
                    $lastProgressUpdate = $now
                    if ($OnProgress) {
                        & $OnProgress -CopiedBytes $copiedBytes -TotalBytes $totalBytes
                    }
                    # Keep GUI responsive and check for cancellation
                    if ($GuiMode) {
                        [System.Windows.Forms.Application]::DoEvents()
                        if ($script:cancelled) {
                            throw "セットアップがキャンセルされました。"
                        }
                    }
                }
            }

            # Final progress update
            if ($OnProgress) {
                & $OnProgress -CopiedBytes $copiedBytes -TotalBytes $totalBytes
            }
            return  # Success
        } catch {
            $lastError = $_
            if ($attempt -lt $MaxRetries) {
                $delay = $retryDelays[$attempt]
                if (-not $script:GuiMode) {
                    Write-Host "      Network error, retrying in ${delay}s... (attempt $($attempt + 1)/$MaxRetries)" -ForegroundColor Yellow
                }
                Start-Sleep -Seconds $delay
                # Clean up partial destination file
                if (Test-Path $Destination) {
                    Remove-Item -Path $Destination -Force -ErrorAction SilentlyContinue
                }
            }
        } finally {
            if ($destStream) { $destStream.Dispose() }
            if ($sourceStream) { $sourceStream.Dispose() }
        }
    }

    # All retries failed
    throw "Failed to copy file after $MaxRetries retries.`n`nSource: $Source`nError: $($lastError.Exception.Message)"
}

function Cleanup-Directory {
    param(
        [string]$Path
    )

    if (Test-Path $Path) {
        # Safety check: only delete if path is in TEMP and has YakuLingo_ prefix
        $leafName = Split-Path -Leaf $Path
        if ($Path.StartsWith($env:TEMP, [System.StringComparison]::OrdinalIgnoreCase) -and $leafName.StartsWith("YakuLingo_")) {
            & cmd /c "rd /s /q `"$Path`" 2>nul"
        }
    }
}

function Update-PyVenvConfig {
    param(
        [string]$SetupPath
    )

    $pyvenvPath = Join-Path $SetupPath ".venv\\pyvenv.cfg"
    if (-not (Test-Path $pyvenvPath)) {
        throw "pyvenv.cfg not found.`n`nExpected location: $pyvenvPath`n`nThe ZIP package may be corrupted or incomplete. Please re-download from the network share."
    }

    $uvPythonDir = Join-Path $SetupPath ".uv-python"
    if (-not (Test-Path $uvPythonDir)) {
        throw "Python runtime directory not found.`n`nExpected location: $uvPythonDir`n`nThe ZIP package may be corrupted or incomplete. Please re-download from the network share."
    }

    # pyvenv.cfg is read by Python with encoding='utf-8' (no BOM).
    # Use UTF-8 without BOM here to support non-ASCII install paths while avoiding a BOM that would break parsing.
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false

    try {
        $pyvenvLines = [System.IO.File]::ReadAllLines($pyvenvPath, $utf8NoBom)
    } catch {
        throw "Failed to read pyvenv.cfg as UTF-8.`n`nPath: $pyvenvPath`nError: $($_.Exception.Message)"
    }

    # Extract the desired Python version from pyvenv.cfg (uv uses version_info, venv uses version).
    $desiredVersionText = $null
    foreach ($line in $pyvenvLines) {
        if ($line -match '^\s*version_info\s*=\s*(.+?)\s*$') {
            $desiredVersionText = $Matches[1].Trim()
            break
        }
        if ($line -match '^\s*version\s*=\s*(.+?)\s*$') {
            $desiredVersionText = $Matches[1].Trim()
            break
        }
    }

    $desiredVersion = $null
    if ($desiredVersionText) {
        try { $desiredVersion = [Version]$desiredVersionText } catch { $desiredVersion = $null }
    }

    # Find python.exe in .uv-python (structure: .uv-python/cpython-x.x.x-*/python.exe)
    # Only search one level deep to avoid slow recursive enumeration.
    $searchedDirs = @()
    $candidates = @()
    foreach ($dir in (Get-ChildItem -Path $uvPythonDir -Directory -ErrorAction SilentlyContinue)) {
        $searchedDirs += $dir.Name
        $pythonExePath = Join-Path $dir.FullName "python.exe"
        if (-not (Test-Path $pythonExePath)) {
            continue
        }

        $candidateVersion = $null
        if ($dir.Name -match '^cpython-(\d+\.\d+\.\d+)-') {
            try { $candidateVersion = [Version]$Matches[1] } catch { $candidateVersion = $null }
        }

        $candidates += [PSCustomObject]@{
            Directory = $dir
            PythonExe = $pythonExePath
            Version = $candidateVersion
        }
    }

    if (-not $candidates -or $candidates.Count -eq 0) {
        $searchedInfo = if ($searchedDirs.Count -gt 0) { "Searched in: $($searchedDirs -join ', ')" } else { "No subdirectories found in .uv-python" }
        throw "python.exe not found in bundled Python runtime.`n`nLocation: $uvPythonDir`n$searchedInfo`n`nThe ZIP package may be corrupted or incomplete. Please re-download from the network share."
    }

    # Prefer an exact version match; otherwise prefer latest patch within the same major.minor; otherwise choose the latest available.
    $selected = $null
    if ($desiredVersion) {
        $selected = $candidates | Where-Object { $_.Version -and $_.Version -eq $desiredVersion } | Sort-Object Version -Descending | Select-Object -First 1
        if (-not $selected) {
            $selected = $candidates | Where-Object { $_.Version -and $_.Version.Major -eq $desiredVersion.Major -and $_.Version.Minor -eq $desiredVersion.Minor } | Sort-Object Version -Descending | Select-Object -First 1
        }
    }
    if (-not $selected) {
        $selected = $candidates | Where-Object { $_.Version } | Sort-Object Version -Descending | Select-Object -First 1
    }
    if (-not $selected) {
        $selected = $candidates | Select-Object -First 1
    }

    $pythonHome = Split-Path -Parent $selected.PythonExe

    $updated = $false
    $newLines = foreach ($line in $pyvenvLines) {
        if ($line -match '^\s*home\s*=') {
            $updated = $true
            "home = $pythonHome"
        } else {
            $line
        }
    }

    if (-not $updated) {
        $newLines = @("home = $pythonHome") + $newLines
    }

    try {
        [System.IO.File]::WriteAllLines($pyvenvPath, $newLines, $utf8NoBom)
    } catch {
        throw "Failed to write pyvenv.cfg.`n`nPath: $pyvenvPath`nError: $($_.Exception.Message)"
    }
}

# ============================================================
# Main Setup Logic (wrapped in function for error handling)
# ============================================================
function Invoke-Setup {
    # ============================================================
    # Check if YakuLingo is running
    # ============================================================
    $runningProcess = Get-Process -Name "YakuLingo" -ErrorAction SilentlyContinue
    if ($runningProcess) {
        throw "YakuLingo is currently running.`n`nPlease close YakuLingo and try again."
    }

    # Also check for Python processes running from the YakuLingo install directory
    # This catches cases where YakuLingo.exe has exited but Python is still running
    $expectedSetupPath = if ([string]::IsNullOrEmpty($SetupPath)) { Join-Path $env:LOCALAPPDATA $script:AppName } else { $SetupPath }
    if (Test-Path $expectedSetupPath) {
        $pythonProcesses = Get-Process -Name "python*" -ErrorAction SilentlyContinue | Where-Object {
            try {
                $processPath = $_.Path
                if ($processPath) {
                    $processPath.StartsWith($expectedSetupPath, [System.StringComparison]::OrdinalIgnoreCase)
                } else {
                    $false
                }
            } catch {
                $false
            }
        }
        if ($pythonProcesses) {
            throw "YakuLingo's Python process is still running.`n`nPlease close YakuLingo completely and try again."
        }
    }

    # ============================================================
    # Check requirements
    # ============================================================
    # 7-Zip is optional; Expand-Archive is used as fallback (slower but always available)

    # ============================================================
    # Configuration
    # ============================================================
    # Use script-scope variables defined at top-level
    $AppName = $script:AppName
    $ScriptDir = $script:ScriptDir
    $ShareDir = $script:ShareDir

    # Auto-detect ZIP file (use newest one)
    $ZipInfo = Get-LatestZipFile -ShareDir $ShareDir
    $ZipFile = $ZipInfo.FullName
    $ZipFileName = $ZipInfo.Name
    if (-not $GuiMode) {
        Write-Host "[INFO] Using: $ZipFileName" -ForegroundColor Cyan
    }

    # Default path: LocalAppData\YakuLingo with safety checks
    try {
        "Invoke-Setup: Calling Resolve-SetupPath..." | Out-File -FilePath $debugLog -Append -Encoding UTF8
    } catch { }
    $SetupPath = Resolve-SetupPath -InputPath $SetupPath -AppName $AppName
    try {
        "Invoke-Setup: SetupPath resolved to '$SetupPath'" | Out-File -FilePath $debugLog -Append -Encoding UTF8
    } catch { }

    # ============================================================
    # Step 1: Prepare destination (backup user data first)
    # ============================================================
    Write-Status -Message "Preparing destination..." -Progress -Step "Step 1/4: Preparing" -Percent 5
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[1/4] Preparing destination..." -ForegroundColor Yellow
    }

    # Backup user data files before removing the directory
    # Note: glossary.csv is handled separately (compare & backup to Desktop if changed)
    # Note: settings.json は廃止、user_settings.json にユーザー設定のみ保存
    $BackupFiles = @()
    $UserDataFiles = @("config\user_settings.json")
    $script:GlossaryBackupPath = $null  # Will be set if glossary was backed up
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

        # Also backup glossary.csv separately for comparison later
        $glossaryPath = Join-Path $SetupPath "glossary.csv"
        if (Test-Path $glossaryPath) {
            if (-not (Test-Path $BackupDir)) {
                New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
            }
            $glossaryBackupPath = Join-Path $BackupDir "glossary.csv"
            Copy-Item -Path $glossaryPath -Destination $glossaryBackupPath -Force
            if (-not $GuiMode) {
                Write-Host "      Backed up: glossary.csv" -ForegroundColor Gray
            }
        }

        # Safety check: Only overwrite if it looks like a YakuLingo installation
        # This prevents accidental overwriting of unrelated directories
        # (robocopy /MIR will delete files not in source, so this check is critical)
        $isYakuLingoDir = $false
        $markerFiles = @("YakuLingo.exe", "app.py", "yakulingo\__init__.py", ".venv\pyvenv.cfg")
        foreach ($marker in $markerFiles) {
            if (Test-Path (Join-Path $SetupPath $marker)) {
                $isYakuLingoDir = $true
                break
            }
        }

        if (-not $isYakuLingoDir) {
            # Directory exists but doesn't look like YakuLingo - refuse to overwrite
            throw "Directory exists but does not appear to be a YakuLingo installation: $SetupPath`n`nTo reinstall, please delete this directory manually first, or choose a different location."
        }

        if (-not $GuiMode) {
            Write-Host "      Found existing installation, will update in place" -ForegroundColor Gray
        }
    }

    if (-not $GuiMode) {
        Write-Host "[OK] Destination ready: $SetupPath" -ForegroundColor Green
    }
    Write-Status -Message "Destination prepared" -Progress -Step "Step 1/4: Preparing" -Percent 25

    # ============================================================
    # Step 2: Copy ZIP to temp folder (faster than extracting over network)
    # ============================================================
    Write-Status -Message "Copying files..." -Progress -Step "Step 2/4: Copying" -Percent 30
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[2/4] Copying ZIP to local temp folder..." -ForegroundColor Yellow
    }

    $workspace = Prepare-TempWorkspace -ZipFileName $ZipFileName
    $TempZipDir = $workspace.TempZipDir
    $TempZipFile = $workspace.TempZipFile

    if (-not $GuiMode) {
        Write-Host "      TEMP folder: $TempZipDir" -ForegroundColor Gray
    }

    # Use .NET FileStream with large buffer for fast network file copy
    # 1MB buffer matches Explorer's copy performance better than robocopy for single large files
    # Progress callback updates GUI to prevent "Not Responding" state
    $copyProgress = {
        param([long]$CopiedBytes, [long]$TotalBytes)
        if ($TotalBytes -gt 0) {
            $percentComplete = [int](($CopiedBytes / $TotalBytes) * 100)
            $copiedMB = [math]::Round($CopiedBytes / 1MB, 1)
            $totalMB = [math]::Round($TotalBytes / 1MB, 1)
            # Map to 30-50% of overall progress
            $overallPercent = 30 + [int]($percentComplete * 0.2)
            if ($GuiMode) {
                Show-Progress -Title "YakuLingo Setup" -Status "Copying: ${copiedMB}MB / ${totalMB}MB" -Step "Step 2/4: Copying" -Percent $overallPercent
            }
        }
    }
    Copy-FileBuffered -Source $ZipFile -Destination $TempZipFile -OnProgress $copyProgress

    if (-not $GuiMode) {
        Write-Host "[OK] ZIP copied to temp folder" -ForegroundColor Green
    }
    Write-Status -Message "Files copied" -Progress -Step "Step 2/4: Copying" -Percent 50

    # ============================================================
    # Step 3: Extract ZIP directly to destination (skip TEMP to avoid double file creation)
    # ============================================================
    # Note: Extracting directly to SetupPath avoids antivirus scanning files twice
    # (once in TEMP, once in SetupPath via robocopy)
    $extractMethod = if ($script:Use7Zip) { "7-Zip" } else { "Windows built-in (slower)" }
    Write-Status -Message "Extracting files..." -Progress -Step "Step 3/4: Installing ($extractMethod)" -Percent 55
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[3/4] Installing files..." -ForegroundColor Yellow
        if (-not $script:Use7Zip) {
            Write-Host "      [WARNING] 7-Zip not found - using Windows built-in extractor (5-10x slower)" -ForegroundColor Yellow
        }
    }

    # Create parent directory of SetupPath to extract into
    $SetupParent = Split-Path -Parent $SetupPath
    if (-not (Test-Path $SetupParent)) {
        New-Item -ItemType Directory -Path $SetupParent -Force | Out-Null
    }

    # Create extraction log file
    $extractLogPath = Join-Path $env:TEMP "YakuLingo_extract.log"
    try {
        "=== Extraction started: $(Get-Date) ===" | Out-File -FilePath $extractLogPath -Encoding UTF8
        "ZIP file: $TempZipFile" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8
        "Target: $SetupPath" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8
        "Method: $(if ($script:Use7Zip) { '7-Zip' } else { 'Expand-Archive' })" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8
    } catch { }

    try {
        # Extract directly to SetupPath (ZIP has flat structure, no parent folder)
        if ($script:Use7Zip) {
            if (-not $GuiMode) {
                Write-Host "      Extracting with 7-Zip: $($script:SevenZip)" -ForegroundColor Gray
                Write-Host "      Log: $extractLogPath" -ForegroundColor Gray
            }
            # Create SetupPath if not exists
            if (-not (Test-Path $SetupPath)) {
                New-Item -ItemType Directory -Path $SetupPath -Force | Out-Null
            }
            # Run 7-Zip via cmd.exe with output redirected to log file
            # -aoa: Overwrite all existing files without prompt
            # -bb1: Show names of processed files (verbose logging)
            # Using cmd.exe for reliable output redirection
            $psi = New-Object System.Diagnostics.ProcessStartInfo
            $psi.FileName = "cmd.exe"
            $psi.Arguments = "/c `"`"$($script:SevenZip)`" x `"$TempZipFile`" `"-o$SetupPath`" -y -mmt=on -aoa -bb1 >> `"$extractLogPath`" 2>&1`""
            $psi.UseShellExecute = $false
            $psi.CreateNoWindow = $true
            $psi.RedirectStandardOutput = $false
            $psi.RedirectStandardError = $false

            $proc = [System.Diagnostics.Process]::Start($psi)

            # Wait for completion with DoEvents for GUI responsiveness
            while (-not $proc.HasExited) {
                if ($GuiMode) {
                    [System.Windows.Forms.Application]::DoEvents()
                    # Check for cancellation
                    if ($script:cancelled) {
                        try {
                            $proc.Kill()
                            $proc.WaitForExit(3000)
                        } catch { }
                        $proc.Dispose()
                        throw "セットアップがキャンセルされました。"
                    }
                }
                Start-Sleep -Milliseconds 100
            }

            $proc.WaitForExit()
            $exitCode = $proc.ExitCode
            $proc.Dispose()

            # Log completion
            try {
                "Exit code: $exitCode" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8
                "=== Extraction completed: $(Get-Date) ===" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8
            } catch { }

            if ($exitCode -ne 0) {
                if (-not $GuiMode) {
                    Write-Host "      [ERROR] 7-Zip failed. See log: $extractLogPath" -ForegroundColor Red
                }
                throw "Failed to extract ZIP file.`n`nFile: $ZipFileName`nExit code: $exitCode`n`nSee log: $extractLogPath"
            }

            if (-not $GuiMode) {
                # Count extracted files from log
                try {
                    $logContent = Get-Content -Path $extractLogPath -Raw -ErrorAction SilentlyContinue
                    $extractedCount = ([regex]::Matches($logContent, "^- ", "Multiline")).Count
                    Write-Host "      Extracted $extractedCount files" -ForegroundColor Gray
                } catch {
                    Write-Host "      Extraction completed" -ForegroundColor Gray
                }
            }
        } else {
            if (-not $GuiMode) {
                Write-Host "      Extracting with Expand-Archive (7-Zip not found, this may take longer)..." -ForegroundColor Gray
            }
            # Create SetupPath if not exists
            if (-not (Test-Path $SetupPath)) {
                New-Item -ItemType Directory -Path $SetupPath -Force | Out-Null
            }
            # Extract directly to SetupPath (ZIP has flat structure)
            if ($GuiMode) {
                $extractJob = Start-Job -ScriptBlock {
                    param($TempZipFile, $SetupPath)
                    try {
                        Expand-Archive -Path $TempZipFile -DestinationPath $SetupPath -Force
                        return $true
                    } catch {
                        return $false
                    }
                } -ArgumentList $TempZipFile, $SetupPath

                $dotCount = 0
                $elapsedSeconds = 0
                while ($extractJob.State -eq 'Running') {
                    Start-Sleep -Milliseconds 500
                    [System.Windows.Forms.Application]::DoEvents()

                    # Check for cancellation
                    if ($script:cancelled) {
                        try {
                            Stop-Job -Job $extractJob -ErrorAction SilentlyContinue
                            Remove-Job -Job $extractJob -Force -ErrorAction SilentlyContinue
                        } catch { }
                        throw "セットアップがキャンセルされました。"
                    }

                    $elapsedSeconds += 0.5
                    $dotCount = ($dotCount + 1) % 4
                    $dots = "." * ($dotCount + 1)
                    $elapsedMinutes = [math]::Floor($elapsedSeconds / 60)
                    $elapsedSec = [int]($elapsedSeconds % 60)
                    if ($elapsedMinutes -gt 0) {
                        $timeInfo = " (${elapsedMinutes}m ${elapsedSec}s)"
                    } else {
                        $timeInfo = " (${elapsedSec}s)"
                    }
                    Show-Progress -Title "YakuLingo Setup" -Status "Extracting files$dots$timeInfo" -Step "Step 3/4: Extracting (this may take a few minutes)" -Percent 60
                }

                $jobResult = Receive-Job -Job $extractJob
                Remove-Job -Job $extractJob
                if (-not $jobResult) {
                    throw "Failed to extract ZIP file.`n`nFile: $ZipFileName"
                }
            } else {
                Expand-Archive -Path $TempZipFile -DestinationPath $SetupPath -Force
            }
        }
    } finally {
        # Clean up temp folder
        Cleanup-Directory -Path $TempZipDir
    }

    if (-not $GuiMode) {
        Write-Host "[OK] Extraction completed" -ForegroundColor Green
    }
    Write-Status -Message "Files extracted" -Progress -Step "Step 3/4: Extracting" -Percent 80

    # Verify extracted files and log
    try {
        "=== Verification: $(Get-Date) ===" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8
        $criticalFiles = @(
            "YakuLingo.exe",
            "app.py",
            "yakulingo\__init__.py",
            "yakulingo\ui\app.py",
            "yakulingo\ui\styles.css",
            "yakulingo\ui\components\text_panel.py",
            "yakulingo\ui\components\file_panel.py",
            ".venv\pyvenv.cfg"
        )
        $missingFiles = @()
        foreach ($file in $criticalFiles) {
            $fullPath = Join-Path $SetupPath $file
            $exists = Test-Path $fullPath
            "$file : $(if ($exists) { 'OK' } else { 'MISSING' })" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8
            if (-not $exists) {
                $missingFiles += $file
            }
        }

        # Log UI file timestamps for debugging
        "=== UI File Timestamps ===" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8
        $uiDir = Join-Path $SetupPath "yakulingo\ui"
        if (Test-Path $uiDir) {
            Get-ChildItem -Path $uiDir -File | ForEach-Object {
                "$($_.Name) : $($_.LastWriteTime)" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8
            }
        }

        if ($missingFiles.Count -gt 0) {
            if (-not $GuiMode) {
                Write-Host "      [WARNING] Missing files after extraction:" -ForegroundColor Yellow
                foreach ($f in $missingFiles) {
                    Write-Host "        - $f" -ForegroundColor Yellow
                }
                Write-Host "      See log: $extractLogPath" -ForegroundColor Yellow
            }
        }
    } catch {
        # Ignore verification errors
    }

    # Clean up updates folder to prevent stale files from affecting the app
    # NOTE: __pycache__ directories are intentionally preserved for faster first launch
    # The distribution package includes pre-compiled .pyc files with unchecked-hash mode
    # which survives ZIP extraction and provides ~23 seconds faster startup
    Write-Status -Message "Cleaning up cache..." -Progress -Step "Step 3/4: Extracting" -Percent 82
    try {
        "=== Cache Cleanup ===" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8

        # Remove updates folder (auto-update cache)
        $updatesDir = Join-Path $SetupPath "updates"
        if (Test-Path $updatesDir) {
            Remove-Item -Path $updatesDir -Recurse -Force -ErrorAction SilentlyContinue
            "Removed updates directory" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8
            if (-not $GuiMode) {
                Write-Host "      Removed updates directory" -ForegroundColor Gray
            }
        }
    } catch {
        # Ignore cleanup errors
    }

    # Fix pyvenv.cfg placeholder (__PYTHON_HOME__) to the actual bundled runtime path
    Write-Status -Message "Configuring Python runtime..." -Progress -Step "Step 3/4: Extracting" -Percent 85
    Update-PyVenvConfig -SetupPath $SetupPath
    if (-not $GuiMode) {
        Write-Host "      Updated pyvenv.cfg with bundled Python path" -ForegroundColor Gray
    }

    # ============================================================
    # Restore/Merge backed up user data files
    # ============================================================
    # Check for cancellation before starting user data restore
    if ($GuiMode -and $script:cancelled) {
        throw "セットアップがキャンセルされました。"
    }

    if ($BackupFiles.Count -gt 0) {
        Write-Status -Message "Restoring user data..." -Progress -Step "Step 3/4: Extracting" -Percent 87
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

                # user_settings.json はそのまま復元（ユーザー設定を保持）
                Copy-Item -Path $backupPath -Destination $restorePath -Force
                if (-not $GuiMode) {
                    Write-Host "      Restored: $file" -ForegroundColor Gray
                }
            }
        }

        # ============================================================
        # Handle glossary.csv: Compare and backup to Desktop if changed
        # (Must be done BEFORE cleaning up backup directory)
        # ============================================================
        $userGlossaryPath = Join-Path $SetupPath "glossary.csv"

        # Check if user had a glossary.csv before extraction
        if (Test-Path $BackupDir) {
            $userGlossaryBackup = Get-ChildItem -Path $BackupDir -Filter "glossary.csv" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        }

        # If user's glossary existed and new glossary exists, compare them
        if ($userGlossaryBackup -and (Test-Path $userGlossaryPath)) {
            Write-Status -Message "Checking glossary updates..." -Progress -Step "Step 3/4: Extracting" -Percent 88

            # Compare file hashes
            $userHash = (Get-FileHash -Path $userGlossaryBackup.FullName -Algorithm MD5).Hash
            $newHash = (Get-FileHash -Path $userGlossaryPath -Algorithm MD5).Hash

            # Also check against glossary_old.csv (previous version)
            # Skip backup if user's glossary matches either new or old version (not customized)
            $oldGlossaryPath = Join-Path $SetupPath "glossary_old.csv"
            $oldHash = $null
            if (Test-Path $oldGlossaryPath) {
                $oldHash = (Get-FileHash -Path $oldGlossaryPath -Algorithm MD5).Hash
            }

            # Only backup if user's glossary differs from both new and old versions
            $matchesNew = ($userHash -eq $newHash)
            $matchesOld = ($oldHash -and $userHash -eq $oldHash)

            if (-not $matchesNew -and -not $matchesOld) {
                # Files are different - backup user's glossary to Desktop
                $desktopPath = [Environment]::GetFolderPath("Desktop")
                $timestamp = Get-Date -Format "yyyyMMdd"
                $backupFileName = "glossary_backup_$timestamp.csv"
                $script:GlossaryBackupPath = Join-Path $desktopPath $backupFileName

                # Avoid overwriting existing backup
                $counter = 1
                while (Test-Path $script:GlossaryBackupPath) {
                    $backupFileName = "glossary_backup_${timestamp}_$counter.csv"
                    $script:GlossaryBackupPath = Join-Path $desktopPath $backupFileName
                    $counter++
                }

                Copy-Item -Path $userGlossaryBackup.FullName -Destination $script:GlossaryBackupPath -Force

                if (-not $GuiMode) {
                    Write-Host "      Glossary updated - backup saved to Desktop: $backupFileName" -ForegroundColor Cyan
                }
            } else {
                # User's glossary matches new or old version (not customized) - no backup needed
                if (-not $GuiMode) {
                    if ($matchesNew) {
                        Write-Host "      Glossary unchanged" -ForegroundColor Gray
                    } else {
                        Write-Host "      Glossary not customized (matches previous version)" -ForegroundColor Gray
                    }
                }
            }
        }

        # Clean up backup directory (with safety check)
        if (Test-Path $BackupDir) {
            $backupLeafName = Split-Path -Leaf $BackupDir
            if ($BackupDir.StartsWith($env:TEMP, [System.StringComparison]::OrdinalIgnoreCase) -and $backupLeafName.StartsWith("YakuLingo_")) {
                & cmd /c "rd /s /q `"$BackupDir`" 2>nul"
            }
        }
        Write-Status -Message "User data restored" -Progress -Step "Step 3/4: Extracting" -Percent 89
        if (-not $GuiMode) {
            Write-Host "[OK] User data restored" -ForegroundColor Green
        }
    }

    # ============================================================
    # Finalize: Create shortcuts
    # ============================================================
    # Check for cancellation before creating shortcuts
    if ($GuiMode -and $script:cancelled) {
        throw "セットアップがキャンセルされました。"
    }

    Write-Status -Message "Creating shortcuts..." -Progress -Step "Step 4/4: Finalizing" -Percent 90
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[4/4] Creating shortcuts..." -ForegroundColor Yellow
    }

    $WshShell = New-Object -ComObject WScript.Shell

    # Desktop shortcut - use YakuLingo.exe for silent launch
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $ShortcutPath = Join-Path $DesktopPath "$AppName.lnk"
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $ExePath = Join-Path $SetupPath "YakuLingo.exe"
    $Shortcut.TargetPath = $ExePath
    $Shortcut.WorkingDirectory = $SetupPath
    # Prefer explicit ICO file for reliable desktop rendering
    $IconPath = Join-Path $SetupPath "yakulingo\ui\yakulingo.ico"
    if (Test-Path $IconPath) {
        $Shortcut.IconLocation = "$IconPath,0"
    } else {
        $Shortcut.IconLocation = "$ExePath,0"
    }
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
        # Final cancellation check before showing success dialog
        if ($script:cancelled) {
            throw "セットアップがキャンセルされました。"
        }
        Write-Status -Message "Setup completed!" -Progress -Step "Step 4/4: Finalizing" -Percent 100
        $successMsg = "セットアップが完了しました。`n`nデスクトップのショートカットからYakuLingoを起動してください。"
        if ($script:GlossaryBackupPath) {
            $backupFileName = Split-Path -Leaf $script:GlossaryBackupPath
            $successMsg += "`n`n用語集が更新されました。`n以前の用語集はデスクトップに保存しました:`n  $backupFileName"
        }
        Show-Success $successMsg
    } else {
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host " Setup completed!" -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host ""
        Write-Host " Location: $SetupPath" -ForegroundColor White
        Write-Host " Please launch YakuLingo from the desktop shortcut." -ForegroundColor Cyan
        if ($script:GlossaryBackupPath) {
            Write-Host ""
            $backupFileName = Split-Path -Leaf $script:GlossaryBackupPath
            Write-Host " Glossary updated. Previous version backed up to Desktop:" -ForegroundColor Yellow
            Write-Host "   $backupFileName" -ForegroundColor Yellow
        }
        Write-Host ""
        Write-Host " Log files (for troubleshooting):" -ForegroundColor Gray
        Write-Host "   Debug: $debugLog" -ForegroundColor Gray
        Write-Host "   Extract: $extractLogPath" -ForegroundColor Gray
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
        # Write error to debug log (catch block errors)
        try {
            "=== CATCH ERROR: $(Get-Date) ===" | Out-File -FilePath $debugLog -Append -Encoding UTF8
            "Exception: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
            "ScriptStackTrace: $($_.ScriptStackTrace)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
            "InvocationInfo: $($_.InvocationInfo.PositionMessage)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
        } catch { }

        # Close progress dialog first
        Close-Progress

        # Don't show error dialog if cancelled by user
        if ($script:cancelled) {
            exit 2  # Exit code 2 = cancelled
        }

        Write-ErrorLog -ErrorRecord $_
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
