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
    if ($script:cancelled) {
        exit 2  # Exit code 2 = cancelled
    }
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
$script:SetupUiTitle = "Setup - $($script:AppName)"
$script:SetupUiTitleError = "$($script:SetupUiTitle) - Error"

# Open UI after setup completes
function Open-PostSetupUi {
    param([string]$SetupPath)

    if ([string]::IsNullOrWhiteSpace($SetupPath)) {
        $SetupPath = Join-Path $env:LOCALAPPDATA $script:AppName
    }

    $openUiPath = Join-Path $SetupPath "YakuLingo_OpenUI.ps1"
    if (Test-Path $openUiPath) {
        try {
            $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $openUiPath)
            Start-Process -FilePath "powershell.exe" -ArgumentList $argList -WindowStyle Hidden | Out-Null
            try { "Opened UI: $openUiPath" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
        } catch {
            try { "Failed to open UI: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
        }
        return
    }

    $fallbackUrl = "http://127.0.0.1:8765/"
    try {
        Start-Process -FilePath $fallbackUrl | Out-Null
        try { "Opened UI fallback URL: $fallbackUrl" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
    } catch {
        try { "Failed to open UI fallback URL: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
    }
}

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
    $script:closingProgressForm = $false
    $script:holdProgressOpen = $false

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

        if ($script:progressForm -ne $null) {
            if ($script:progressForm.IsDisposed) {
                $script:progressForm = $null
            } else {
                if (-not $script:progressForm.Visible) {
                    $script:progressForm.Show()
                }
                if ($script:progressForm.WindowState -eq "Minimized") {
                    $script:progressForm.WindowState = "Normal"
                }
                $script:progressForm.TopMost = $true
                $script:progressForm.BringToFront()
            }
        }

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
                if (-not $script:closingProgressForm -and -not $script:cancelled) {
                    $script:cancelled = $true
                }
                if (-not $script:closingProgressForm) {
                    $e.Cancel = $true
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
            $script:progressForm.BringToFront()
            $script:progressForm.Refresh()
        } else {
            if ($Step -ne "") {
                $script:stepLabel.Text = $Step
            }
            $script:progressLabel.Text = $Status
            if ($Percent -lt 0) {
                if ($script:progressBar.Style -ne "Marquee") {
                    $script:progressBar.Style = "Marquee"
                    $script:progressBar.MarqueeAnimationSpeed = 30
                }
            } else {
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
        if ($script:holdProgressOpen) {
            return
        }
        if ($script:progressForm -ne $null) {
            $script:closingProgressForm = $true
            try {
                $script:progressForm.Close()
                $script:progressForm.Dispose()
                $script:progressForm = $null
            } finally {
                $script:closingProgressForm = $false
            }
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
        $ownerForm = $null
        $createdOwner = $false
        if ($script:progressForm -ne $null -and -not $script:progressForm.IsDisposed) {
            $ownerForm = $script:progressForm
            if (-not $ownerForm.Visible) {
                $ownerForm.Show()
            }
            if ($ownerForm.WindowState -eq "Minimized") {
                $ownerForm.WindowState = "Normal"
            }
            $ownerForm.Refresh()
        } else {
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
            $createdOwner = $true
        }

        [System.Windows.Forms.MessageBox]::Show(
            $ownerForm,
            $Message,
            $script:SetupUiTitleError,
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null

        if ($createdOwner) {
            $ownerForm.Close()
            $ownerForm.Dispose()
        }
        Close-Progress
    }

    function Show-Success {
        param([string]$Message)
        # 進捗表示を残したまま、完了メッセージの準備を行う
        $script:holdProgressOpen = $true
        $ownerForm = $null
        $createdOwner = $false
        try {
            if ($script:progressForm -ne $null -and -not $script:progressForm.IsDisposed) {
                $ownerForm = $script:progressForm
                if (-not $ownerForm.Visible) {
                    $ownerForm.Show()
                }
                if ($ownerForm.WindowState -eq "Minimized") {
                    $ownerForm.WindowState = "Normal"
                }
                $ownerForm.Activate()
                $ownerForm.Refresh()
            } else {
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
                $createdOwner = $true
            }

            [System.Windows.Forms.MessageBox]::Show(
                $ownerForm,
                $Message,
                $script:SetupUiTitle,
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Information
            ) | Out-Null
        } finally {
            if ($createdOwner -and $ownerForm) {
                $ownerForm.Close()
                $ownerForm.Dispose()
            }
            $script:holdProgressOpen = $false
        }
        Close-Progress
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
            Show-Progress -Title $script:SetupUiTitle -Status $Message -Step $Step -Percent $Percent
        }
    } else {
        Write-Host $Message -ForegroundColor $Color
    }
}

# ============================================================
# Helper Functions
# ============================================================
function Get-UniquePath {
    param(
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return $Path
    }

    $dir = Split-Path -Parent $Path
    $base = [System.IO.Path]::GetFileNameWithoutExtension($Path)
    $ext = [System.IO.Path]::GetExtension($Path)
    $counter = 1

    do {
        $candidate = Join-Path $dir "${base}_${counter}${ext}"
        $counter++
    } while (Test-Path $candidate)

    return $candidate
}

function Preserve-UserFile {
    param(
        [string]$UserBackupPath,
        [string]$TargetPath,
        [string]$DistPath
    )

    if (-not $UserBackupPath -or -not (Test-Path $UserBackupPath)) {
        return $null
    }

    if (-not (Test-Path $TargetPath)) {
        $parent = Split-Path -Parent $TargetPath
        if (-not (Test-Path $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -Path $UserBackupPath -Destination $TargetPath -Force
        return $null
    }

    $userHash = (Get-FileHash -Path $UserBackupPath -Algorithm MD5).Hash
    $newHash = (Get-FileHash -Path $TargetPath -Algorithm MD5).Hash
    if ($userHash -ne $newHash) {
        $safeDist = Get-UniquePath -Path $DistPath
        Copy-Item -Path $TargetPath -Destination $safeDist -Force
        Copy-Item -Path $UserBackupPath -Destination $TargetPath -Force
        return $safeDist
    }

    return $null
}

function Start-ResidentService {
    param(
        [string]$SetupPath,
        [string]$PythonwPath,
        [string]$AppPyPath,
        [string]$LauncherPath,
        [int]$Port = 8765
    )

    try {
        if ([string]::IsNullOrWhiteSpace($SetupPath)) {
            $SetupPath = Join-Path $env:LOCALAPPDATA $script:AppName
        }
        if ([string]::IsNullOrWhiteSpace($LauncherPath)) {
            $LauncherPath = Join-Path $SetupPath "YakuLingo.exe"
        }
        if ([string]::IsNullOrWhiteSpace($PythonwPath)) {
            $PythonwPath = Join-Path $SetupPath ".venv\Scripts\pythonw.exe"
        }
        if ([string]::IsNullOrWhiteSpace($AppPyPath)) {
            $AppPyPath = Join-Path $SetupPath "app.py"
        }
        try {
            "Start-ResidentService: SetupPath='$SetupPath' LauncherPath='$LauncherPath' PythonwPath='$PythonwPath' AppPyPath='$AppPyPath'" | Out-File -FilePath $debugLog -Append -Encoding UTF8
        } catch { }

        function Test-PortOpen([int]$p) {
            try {
                $client = New-Object System.Net.Sockets.TcpClient
                $async = $client.BeginConnect('127.0.0.1', $p, $null, $null)
                if (-not $async.AsyncWaitHandle.WaitOne(200)) { return $false }
                $client.EndConnect($async) | Out-Null
                $client.Close()
                return $true
            } catch {
                return $false
            }
        }

        $portOpen = Test-PortOpen $Port
        if (-not $portOpen) {
            if (Test-Path $LauncherPath -PathType Leaf) {
                Start-Process -FilePath $LauncherPath `
                    -WorkingDirectory $SetupPath `
                    -WindowStyle Hidden | Out-Null
            } elseif ((Test-Path $PythonwPath -PathType Leaf) -and (Test-Path $AppPyPath -PathType Leaf)) {
                $previousNoOpen = $env:YAKULINGO_NO_AUTO_OPEN
                $env:YAKULINGO_NO_AUTO_OPEN = "1"
                try {
                    Start-Process -FilePath $PythonwPath `
                        -ArgumentList @($AppPyPath) `
                        -WorkingDirectory $SetupPath `
                        -WindowStyle Hidden | Out-Null
                } finally {
                    if ($null -eq $previousNoOpen) {
                        Remove-Item Env:YAKULINGO_NO_AUTO_OPEN -ErrorAction SilentlyContinue
                    } else {
                        $env:YAKULINGO_NO_AUTO_OPEN = $previousNoOpen
                    }
                }
            }

            $deadline = (Get-Date).AddSeconds(30)
            while ((Get-Date) -lt $deadline -and -not (Test-PortOpen $Port)) {
                Start-Sleep -Milliseconds 200
                if ($GuiMode) {
                    [System.Windows.Forms.Application]::DoEvents()
                }
            }
        }

        if (-not (Test-PortOpen $Port)) {
            try { "Start-ResidentService: Port $Port did not open after setup." | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
            if (-not $GuiMode) {
                Write-Host "[WARN] YakuLingo resident service did not start (port $Port closed)." -ForegroundColor Yellow
            }
        }
        return (Test-PortOpen $Port)
    } catch {
        try { "Start-ResidentService failed: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
        if (-not $GuiMode) {
            Write-Host "[WARN] Failed to start YakuLingo resident service." -ForegroundColor Yellow
        }
        return $false
    }
}

function Wait-ResidentReady {
    param(
        [int]$Port = 8765,
        [int]$TimeoutSec = 1200
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $lastState = ""

    while ((Get-Date) -lt $deadline) {
        if ($GuiMode) {
            [System.Windows.Forms.Application]::DoEvents()
        }
        if ($GuiMode -and $script:cancelled) {
            throw "セットアップがキャンセルされました。"
        }

        $status = $null
        try {
            $status = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$Port/api/setup-status" -TimeoutSec 5
        } catch {
            $status = $null
        }

        $state = if ($status -and $status.state) { "$($status.state)" } else { "starting" }
        if ($state -ne $lastState) {
            $lastState = $state
            try { "Wait-ResidentReady: state=$state" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
        }

        $ready = $false
        $loginRequired = $false
        $gptReady = $true
        $active = $false
        $uiConnected = $false
        $uiReady = $true
        $hasError = $false
        if ($status) {
            $ready = [bool]$status.ready
            if ($status.PSObject.Properties.Name -contains "login_required") {
                $loginRequired = [bool]$status.login_required
            }
            if ($status.PSObject.Properties.Name -contains "gpt_mode_set") {
                $gptReady = [bool]$status.gpt_mode_set
            }
            if ($status.PSObject.Properties.Name -contains "active") {
                $active = [bool]$status.active
            }
            if ($status.PSObject.Properties.Name -contains "ui_connected") {
                $uiConnected = [bool]$status.ui_connected
            }
            if ($status.PSObject.Properties.Name -contains "ui_ready") {
                $uiReady = [bool]$status.ui_ready
            }
            if ($status.PSObject.Properties.Name -contains "error") {
                $hasError = -not [string]::IsNullOrEmpty([string]$status.error)
            }
        }
        if ($state -eq "login_required") {
            $loginRequired = $true
        }
        $uiOk = (-not $uiConnected) -or $uiReady
        if ($ready -and $gptReady -and -not $loginRequired -and -not $active -and -not $hasError -and $uiOk) {
            return $true
        }

        $message = "Copilotの準備中です..."
        if ($hasError) {
            $message = "YakuLingoの起動状態を確認中です..."
        } elseif ($loginRequired) {
            $message = "Copilotにログインしてください（右側の画面）..."
        } elseif ($uiConnected -and -not $uiReady) {
            $message = "UIを準備中です..."
        } elseif ($state -eq "loading") {
            $message = "Copilotを読み込み中です..."
        } elseif ($state -eq "ready" -and -not $gptReady) {
            $message = "Copilotを初期化中です..."
        }

        Write-Status -Message $message -Progress -Step "Step 4/4: Finalizing" -Percent -1
        Start-Sleep -Seconds 2
    }

    return $false
}

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
        if ((Test-IsUnderPath -Path $resolvedPath -Root $root) -or (Test-IsUnderPath -Path $targetPath -Root $root)) {
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

function Cleanup-OldTempCaches {
    param(
        [string]$TempRoot = $env:TEMP
    )

    if ([string]::IsNullOrWhiteSpace($TempRoot)) { return }
    if (-not (Test-Path $TempRoot)) { return }

    # Remove stale setup/backup temp folders from previous runs.
    $patterns = @("YakuLingo_Setup_*", "YakuLingo_Backup_*")
    foreach ($pattern in $patterns) {
        try {
            $dirs = Get-ChildItem -Path $TempRoot -Directory -Filter $pattern -ErrorAction SilentlyContinue
            foreach ($dir in $dirs) {
                try {
                    Remove-Item -Path $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue
                } catch { }
            }
        } catch { }
    }
}

function Prepare-TempWorkspace {
    param(
        [string]$ZipFileName
    )

    # Create new temp folder with timestamp (stale folders are cleaned up at startup)
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
            # Try to shut down the resident service gracefully via local API before failing.
            # This reduces friction when users forgot to run "YakuLingo 終了" before updating.
            Write-Status -Message "Closing running YakuLingo..." -Progress -Step "Step 1/4: Preparing" -Percent 1
            try {
                "Invoke-Setup: Detected running python process under '$expectedSetupPath'." | Out-File -FilePath $debugLog -Append -Encoding UTF8
            } catch { }

            $port = 8765
            $shutdownUrl = "http://127.0.0.1:$port/api/shutdown"
            $shutdownRequested = $false
            try {
                Invoke-WebRequest -UseBasicParsing -Method Post -Uri $shutdownUrl -TimeoutSec 8 -Headers @{ "X-YakuLingo-Exit" = "1" } | Out-Null
                $shutdownRequested = $true
                try { "Invoke-Setup: Shutdown requested via $shutdownUrl" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
            } catch {
                try { "Invoke-Setup: Shutdown request failed: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
            }

            # Wait briefly for the process to exit (app schedules a forced exit after 5s).
            $shutdownRetryRequested = $false
            $forceKillAttempted = $false
            $lastStatusSecond = -1
            $waitStart = Get-Date
            $deadline = $waitStart.AddSeconds(30)
            while ((Get-Date) -lt $deadline) {
                # Keep GUI responsive during wait
                if ($GuiMode) {
                    try { Test-Cancelled } catch { throw }
                }

                $elapsedSeconds = [int]((Get-Date) - $waitStart).TotalSeconds
                if ($elapsedSeconds -ne $lastStatusSecond) {
                    $lastStatusSecond = $elapsedSeconds
                    Write-Status -Message "Waiting for YakuLingo to exit... (${elapsedSeconds}s)" -Progress -Step "Step 1/4: Preparing" -Percent 1
                }

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
                if (-not $pythonProcesses) {
                    break
                }

                # Retry shutdown once after a short delay (handles cases where the service is busy
                # or the HTTP endpoint is temporarily unresponsive).
                if (-not $shutdownRetryRequested) {
                    if ($elapsedSeconds -ge 5) {
                        $shutdownRetryRequested = $true
                        try {
                            Invoke-WebRequest -UseBasicParsing -Method Post -Uri $shutdownUrl -TimeoutSec 5 -Headers @{ "X-YakuLingo-Exit" = "1" } | Out-Null
                            $shutdownRequested = $true
                            try { "Invoke-Setup: Shutdown re-requested via $shutdownUrl" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
                        } catch {
                            try { "Invoke-Setup: Shutdown re-request failed: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
                        }
                    }
                }

                # Last resort: if the service doesn't exit, forcibly stop processes under the install dir.
                if (-not $forceKillAttempted -and $elapsedSeconds -ge 12) {
                    $forceKillAttempted = $true
                    Write-Status -Message "Force closing YakuLingo..." -Progress -Step "Step 1/4: Preparing" -Percent 1
                    try {
                        $processesToStop = Get-Process -ErrorAction SilentlyContinue | Where-Object {
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
                        if ($processesToStop) {
                            try { "Invoke-Setup: Force stopping processes: $($processesToStop.Id -join ',')" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
                            $processesToStop | Stop-Process -Force -ErrorAction SilentlyContinue
                        }
                    } catch {
                        try { "Invoke-Setup: Force stop failed: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
                    }
                }

                Start-Sleep -Milliseconds 250
            }

            # Final refresh after wait/force-kill attempts
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
                $msg = "YakuLingo のプロセスがまだ実行中です。`n`n対処:`n- スタートメニュー > YakuLingo > 「YakuLingo 終了」を実行`n- それでも残る場合は、タスクマネージャーで pythonw.exe / python.exe を終了`n`nその後、もう一度 setup.vbs を実行してください。"
                if ($shutdownRequested) {
                    $msg = "YakuLingo が終了できませんでした（自動終了がタイムアウトしました）。`n`n対処:`n- スタートメニュー > YakuLingo > 「YakuLingo 終了」を実行`n- それでも残る場合は、タスクマネージャーで pythonw.exe / python.exe を終了`n`nその後、もう一度 setup.vbs を実行してください。"
                }
                throw $msg
            }
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

    Write-Status -Message "Cleaning up old cache..." -Progress -Step "Step 1/4: Preparing" -Percent 3
    Cleanup-OldTempCaches

    # ============================================================
    # Step 1: Prepare destination (backup user data first)
    # ============================================================
    Write-Status -Message "Preparing destination..." -Progress -Step "Step 1/4: Preparing" -Percent 5
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[1/4] Preparing destination..." -ForegroundColor Yellow
    }

    # Backup user data files before removing the directory
    # Note: glossary.csv and prompts\translation_rules.txt are preserved after extraction.
    # Note: settings.json は廃止、user_settings.json にユーザー設定のみ保存
    $BackupFiles = @()
    $UserDataFiles = @("config\user_settings.json")
    $script:GlossaryDistPath = $null
    $script:TranslationRulesDistPath = $null
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

        # Also backup prompts\translation_rules.txt separately for comparison later
        $rulesPath = Join-Path $SetupPath "prompts\translation_rules.txt"
        if (Test-Path $rulesPath) {
            if (-not (Test-Path $BackupDir)) {
                New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
            }
            $rulesBackupPath = Join-Path $BackupDir "prompts\translation_rules.txt"
            $rulesBackupParent = Split-Path -Parent $rulesBackupPath
            if (-not (Test-Path $rulesBackupParent)) {
                New-Item -ItemType Directory -Path $rulesBackupParent -Force | Out-Null
            }
            Copy-Item -Path $rulesPath -Destination $rulesBackupPath -Force
            if (-not $GuiMode) {
                Write-Host "      Backed up: prompts\\translation_rules.txt" -ForegroundColor Gray
            }
        }

        # Safety check: Only overwrite if it looks like a YakuLingo installation (or its data dir)
        # This prevents accidental overwriting of unrelated directories.
        #
        # NOTE: %LOCALAPPDATA%\YakuLingo may already exist even before installation
        # (e.g., launcher logs / Edge profile dirs from a portable run or a prior uninstall).
        # Treat those known data subfolders as valid markers to allow reinstall without data loss.
        $isYakuLingoDir = $false
        $markerPaths = @(
            # Program markers
            "YakuLingo.exe",
            "app.py",
            "yakulingo\__init__.py",
            ".venv\pyvenv.cfg"
        )

        # Data markers are only used for the default install path to avoid
        # accidentally treating arbitrary directories as "safe" to overwrite.
        $includeDataMarkers = $false
        if ($env:LOCALAPPDATA) {
            try {
                $defaultInstallRoot = Join-Path $env:LOCALAPPDATA $AppName
                $normalizedSetup = [System.IO.Path]::GetFullPath($SetupPath).TrimEnd('\')
                $normalizedDefault = [System.IO.Path]::GetFullPath($defaultInstallRoot).TrimEnd('\')
                $includeDataMarkers = $normalizedSetup.Equals($normalizedDefault, [System.StringComparison]::OrdinalIgnoreCase)
            } catch {
                $includeDataMarkers = $false
            }
        }

        if ($includeDataMarkers) {
            $markerPaths += @(
                "EdgeProfile",
                "AppWindowProfile",
                "logs\launcher.log",
                "updates\latest_release.json"
            )
        }
        foreach ($marker in $markerPaths) {
            if (Test-Path (Join-Path $SetupPath $marker)) {
                $isYakuLingoDir = $true
                break
            }
        }

        if (-not $isYakuLingoDir) {
            # Allow empty directory (e.g., leftover folder from a cancelled setup)
            $hasAnyChild = $false
            try {
                $hasAnyChild = @(
                    Get-ChildItem -Path $SetupPath -Force -ErrorAction SilentlyContinue |
                        Select-Object -First 1
                ).Count -gt 0
            } catch {
                $hasAnyChild = $true
            }

            if ($hasAnyChild) {
                throw "Directory exists but does not appear to be a YakuLingo installation: $SetupPath`n`nTo reinstall, please delete this directory manually first, or choose a different location."
            }
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
                Show-Progress -Title $script:SetupUiTitle -Status "Copying: ${copiedMB}MB / ${totalMB}MB" -Step "Step 2/4: Copying" -Percent $overallPercent
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
                    Show-Progress -Title $script:SetupUiTitle -Status "Extracting files$dots$timeInfo" -Step "Step 3/4: Extracting (this may take a few minutes)" -Percent 60
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

        # Remove app-level __pycache__ to avoid stale bytecode after updates.
        $appCacheRoot = Join-Path $SetupPath "yakulingo"
        if (Test-Path $appCacheRoot) {
            $cacheDirs = Get-ChildItem -Path $appCacheRoot -Directory -Filter "__pycache__" -Recurse -Force -ErrorAction SilentlyContinue
            foreach ($cache in $cacheDirs) {
                try {
                    Remove-Item -Path $cache.FullName -Recurse -Force -ErrorAction SilentlyContinue
                } catch { }
            }
            "Removed __pycache__ under yakulingo" | Out-File -FilePath $extractLogPath -Append -Encoding UTF8
            if (-not $GuiMode) {
                Write-Host "      Removed app __pycache__" -ForegroundColor Gray
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
    }

    # ============================================================
    # Preserve user-edited files (keep existing, store new as .dist)
    # ============================================================
    $userGlossaryBackup = $null
    $userRulesBackup = $null
    if (Test-Path $BackupDir) {
        $glossaryBackupPath = Join-Path $BackupDir "glossary.csv"
        if (Test-Path $glossaryBackupPath) {
            $userGlossaryBackup = $glossaryBackupPath
        }
        $rulesBackupPath = Join-Path $BackupDir "prompts\translation_rules.txt"
        if (Test-Path $rulesBackupPath) {
            $userRulesBackup = $rulesBackupPath
        }
    }

    if ($userGlossaryBackup -or $userRulesBackup) {
        Write-Status -Message "Preserving user files..." -Progress -Step "Step 3/4: Extracting" -Percent 88

        $userGlossaryPath = Join-Path $SetupPath "glossary.csv"
        $script:GlossaryDistPath = Preserve-UserFile `
            -UserBackupPath $userGlossaryBackup `
            -TargetPath $userGlossaryPath `
            -DistPath (Join-Path $SetupPath "glossary.dist.csv")

        $userRulesPath = Join-Path $SetupPath "prompts\translation_rules.txt"
        $script:TranslationRulesDistPath = Preserve-UserFile `
            -UserBackupPath $userRulesBackup `
            -TargetPath $userRulesPath `
            -DistPath (Join-Path $SetupPath "prompts\translation_rules.dist.txt")

        if (-not $GuiMode) {
            if ($script:GlossaryDistPath) {
                Write-Host "      New glossary saved: $script:GlossaryDistPath" -ForegroundColor Cyan
            }
            if ($script:TranslationRulesDistPath) {
                Write-Host "      New translation rules saved: $script:TranslationRulesDistPath" -ForegroundColor Cyan
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
    if ($BackupFiles.Count -gt 0 -or $userGlossaryBackup -or $userRulesBackup) {
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

    # Create helper scripts in install directory (resident / UI opener / exit).
    # These keep the UX simple:
    # - YakuLingo runs as a resident background service (hotkey enabled)
    # - UI is opened on demand
    # - Exit is explicit via shortcut

    $OpenUiScriptPath = Join-Path $SetupPath "YakuLingo_OpenUI.ps1"
    $ResidentScriptPath = Join-Path $SetupPath "YakuLingo_Resident.ps1"
    $ExitScriptPath = Join-Path $SetupPath "YakuLingo_Exit.ps1"
    $UninstallScriptPath = Join-Path $SetupPath "YakuLingo_Uninstall.ps1"

    $utf8NoBom = New-Object System.Text.UTF8Encoding $false

    $openUiScript = @"
`$ErrorActionPreference = 'Stop'

`$installDir = Split-Path -Parent `$MyInvocation.MyCommand.Definition
`$pythonw = Join-Path `$installDir '.venv\\Scripts\\pythonw.exe'
`$appPy = Join-Path `$installDir 'app.py'
`$port = 8765
`$url = "http://127.0.0.1:`$port/"
`$setupStatusUrl = "http://127.0.0.1:`$port/api/setup-status"
`$layoutUrl = "http://127.0.0.1:`$port/api/window-layout"
`$readyTimeoutSec = 1200
`$pollIntervalSec = 2
`$uiOpened = `$false
`$sourceHwndValue = 0

function Test-PortOpen([int]`$p) {
  try {
    `$client = New-Object System.Net.Sockets.TcpClient
    `$async = `$client.BeginConnect('127.0.0.1', `$p, `$null, `$null)
    if (-not `$async.AsyncWaitHandle.WaitOne(200)) { return `$false }
    `$client.EndConnect(`$async) | Out-Null
    `$client.Close()
    return `$true
  } catch { return `$false }
}

try {
  Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class YakuLingoWin32 { [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); }'
  `$sourceHwnd = [YakuLingoWin32]::GetForegroundWindow()
  if (`$sourceHwnd -ne [IntPtr]::Zero) { `$sourceHwndValue = `$sourceHwnd.ToInt64() }
} catch { }

function Show-Warning([string]`$Message) {
  try {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
      `$Message,
      "YakuLingo",
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Warning
    ) | Out-Null
  } catch { }
}

function Get-SetupStatus {
  try {
    return Invoke-RestMethod -Method Get -Uri `$setupStatusUrl -TimeoutSec 5
  } catch {
    return `$null
  }
}

function Open-UiWindow {
  if (`$script:uiOpened) { return }
  `$edge = `$null
  `$candidates = @(
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe'
  )
  foreach (`$p in `$candidates) {
    if (Test-Path `$p -PathType Leaf) { `$edge = `$p; break }
  }

  if (`$edge) {
    `$profileDir = Join-Path `$env:LOCALAPPDATA 'YakuLingo\\AppWindowProfile'
    New-Item -ItemType Directory -Force -Path `$profileDir | Out-Null
    `$args = @(
      "--app=`$url",
      "--disable-features=Translate",
      "--lang=ja",
      "--user-data-dir=`$profileDir",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-sync",
      "--proxy-bypass-list=localhost;127.0.0.1",
      "--disable-session-crashed-bubble",
      "--hide-crash-restore-bubble"
    )
    Start-Process -FilePath `$edge -ArgumentList `$args | Out-Null
  } else {
    Start-Process `$url | Out-Null
  }
  `$script:uiOpened = `$true
}

function Apply-WindowLayout {
  try {
    `$body = @{ source_hwnd = `$sourceHwndValue; edge_layout = "offscreen" } | ConvertTo-Json -Compress
    Invoke-WebRequest -UseBasicParsing -Method Post -Uri `$layoutUrl -Body `$body -ContentType 'application/json' -TimeoutSec 2 | Out-Null
  } catch { }
}

function Wait-ResidentReady {
  param(
    [int]`$TimeoutSec = 1200,
    [int]`$PollIntervalSec = 2
  )
  `$deadline = (Get-Date).AddSeconds(`$TimeoutSec)
  `$lastState = ""
  while ((Get-Date) -lt `$deadline) {
    `$status = Get-SetupStatus
    if (`$status -and `$status.ready) { return `$true }
    `$state = if (`$status -and `$status.state) { "`$(`$status.state)" } else { "starting" }
    if (`$state -ne `$lastState) {
      `$lastState = `$state
    }
    if (`$state -eq "login_required") {
      Open-UiWindow
    }
    Start-Sleep -Seconds `$PollIntervalSec
  }
  return `$false
}

if (-not (Test-PortOpen `$port)) {
  if (Test-Path `$pythonw -PathType Leaf) {
    Start-Process -FilePath `$pythonw -ArgumentList `$appPy -WorkingDirectory `$installDir -WindowStyle Hidden | Out-Null
    `$deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt `$deadline -and -not (Test-PortOpen `$port)) { Start-Sleep -Milliseconds 200 }
  }
}

if (-not (Test-PortOpen `$port)) {
  Show-Warning "YakuLingo の起動に失敗しました。しばらく待ってから再実行してください。"
  exit 1
}

`$ready = Wait-ResidentReady -TimeoutSec `$readyTimeoutSec -PollIntervalSec `$pollIntervalSec
if (-not `$ready) {
  Open-UiWindow
  Show-Warning "Copilot の準備が完了しませんでした。ログインを完了してから再実行してください。"
} elseif (-not `$uiOpened) {
  Open-UiWindow
}

Apply-WindowLayout
"@

    $residentScript = @"
`$ErrorActionPreference = 'SilentlyContinue'

`$installDir = Split-Path -Parent `$MyInvocation.MyCommand.Definition
`$launcher = Join-Path `$installDir 'YakuLingo.exe'
`$pythonw = Join-Path `$installDir '.venv\\Scripts\\pythonw.exe'
`$appPy = Join-Path `$installDir 'app.py'
`$port = 8765

function Test-PortOpen([int]`$p) {
  try {
    `$client = New-Object System.Net.Sockets.TcpClient
    `$async = `$client.BeginConnect('127.0.0.1', `$p, `$null, `$null)
    if (-not `$async.AsyncWaitHandle.WaitOne(200)) { return `$false }
    `$client.EndConnect(`$async) | Out-Null
    `$client.Close()
    return `$true
  } catch { return `$false }
}

if (-not (Test-PortOpen `$port)) {
  if (Test-Path `$launcher -PathType Leaf) {
    Start-Process -FilePath `$launcher -WorkingDirectory `$installDir -WindowStyle Hidden | Out-Null
  } elseif ((Test-Path `$pythonw -PathType Leaf) -and (Test-Path `$appPy -PathType Leaf)) {
    `$previousNoOpen = `$env:YAKULINGO_NO_AUTO_OPEN
    `$env:YAKULINGO_NO_AUTO_OPEN = "1"
    try {
      Start-Process -FilePath `$pythonw -ArgumentList `$appPy -WorkingDirectory `$installDir -WindowStyle Hidden | Out-Null
    } finally {
      if (`$null -eq `$previousNoOpen) {
        Remove-Item Env:YAKULINGO_NO_AUTO_OPEN -ErrorAction SilentlyContinue
      } else {
        `$env:YAKULINGO_NO_AUTO_OPEN = `$previousNoOpen
      }
    }

    `$deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt `$deadline -and -not (Test-PortOpen `$port)) { Start-Sleep -Milliseconds 200 }
  }
}
"@

    $exitScript = @"
`$ErrorActionPreference = 'SilentlyContinue'
`$port = 8765
`$shutdownUrl = "http://127.0.0.1:`$port/api/shutdown"

try {
  Invoke-WebRequest -UseBasicParsing -Method Post -Uri `$shutdownUrl -TimeoutSec 3 -Headers @{ "X-YakuLingo-Exit" = "1" } | Out-Null
  exit 0
} catch { }

# Fallback: kill the process listening on the UI port
try {
  `$conn = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort `$port -State Listen -ErrorAction Stop | Select-Object -First 1
  if (`$conn -and `$conn.OwningProcess) {
    Stop-Process -Id `$conn.OwningProcess -Force
    exit 0
  }
} catch { }

try {
  `$line = (& netstat -ano | Select-String ":`$port" | Select-String "LISTENING" | Select-Object -First 1).Line
  if (`$line) {
    `$pid = (`$line -split '\s+')[-1]
    if (`$pid -match '^\d+$') {
      Stop-Process -Id ([int]`$pid) -Force
      exit 0
    }
  }
} catch { }
exit 0
"@

    $uninstallScript = @"
`$ErrorActionPreference = 'Stop'

`$installDir = Split-Path -Parent `$MyInvocation.MyCommand.Definition
try {
  `$installDir = [System.IO.Path]::GetFullPath(`$installDir).TrimEnd('\')
} catch {
  Write-Host "Uninstall aborted: invalid install directory."
  exit 1
}

function Test-SafeInstallDir([string]`$dir) {
  if ([string]::IsNullOrWhiteSpace(`$dir)) { return `$false }
  try { `$full = [System.IO.Path]::GetFullPath(`$dir).TrimEnd('\') } catch { return `$false }
  `$root = [System.IO.Path]::GetPathRoot(`$full).TrimEnd('\')
  if (`$full -eq `$root) { return `$false }

  `$dangerous = @(
    `$env:USERPROFILE,
    `$env:LOCALAPPDATA,
    `$env:APPDATA,
    `$env:ProgramFiles,
    `${env:ProgramFiles(x86)},
    `$env:WINDIR
  )
  foreach (`$d in `$dangerous) {
    if (-not `$d) { continue }
    try {
      `$dd = [System.IO.Path]::GetFullPath(`$d).TrimEnd('\')
      if (`$full -eq `$dd) { return `$false }
    } catch { }
  }

  `$installMarkers = @('YakuLingo.exe', 'YakuLingo_Resident.ps1', 'YakuLingo_OpenUI.ps1', 'YakuLingo_Exit.ps1')
  `$appMarkers = @('app.py', 'yakulingo', 'config\\settings.template.json')
  `$hasInstallMarker = `$false
  foreach (`$m in `$installMarkers) {
    if (Test-Path (Join-Path `$full `$m)) { `$hasInstallMarker = `$true; break }
  }
  `$hasAppMarker = `$false
  foreach (`$m in `$appMarkers) {
    if (Test-Path (Join-Path `$full `$m)) { `$hasAppMarker = `$true; break }
  }
  return (`$hasInstallMarker -and `$hasAppMarker)
}

if (-not (Test-SafeInstallDir `$installDir)) {
  Write-Host "Uninstall aborted: directory does not look like a YakuLingo installation."
  Write-Host `$installDir
  exit 1
}

function Test-PortOpen([int]`$p) {
  try {
    `$client = New-Object System.Net.Sockets.TcpClient
    `$async = `$client.BeginConnect('127.0.0.1', `$p, `$null, `$null)
    if (-not `$async.AsyncWaitHandle.WaitOne(200)) { return `$false }
    `$client.EndConnect(`$async) | Out-Null
    `$client.Close()
    return `$true
  } catch { return `$false }
}

`$exitScript = Join-Path `$installDir 'YakuLingo_Exit.ps1'
if (Test-Path `$exitScript) {
  try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "`$exitScript" | Out-Null
  } catch { }
}

`$port = 8765
`$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt `$deadline -and (Test-PortOpen `$port)) { Start-Sleep -Milliseconds 200 }

if (Test-PortOpen `$port) {
  try {
    `$conn = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort `$port -State Listen -ErrorAction Stop | Select-Object -First 1
    if (`$conn -and `$conn.OwningProcess) {
      Stop-Process -Id `$conn.OwningProcess -Force
    }
  } catch { }
}

`$programs = [Environment]::GetFolderPath('Programs')
`$startup = [Environment]::GetFolderPath('Startup')
`$startMenuDir = Join-Path `$programs 'YakuLingo'
`$shortcutPaths = @(
  (Join-Path `$programs 'YakuLingo.lnk'),
  (Join-Path `$programs 'YakuLingo 終了.lnk'),
  (Join-Path `$programs 'YakuLingo アンインストール.lnk'),
  (Join-Path `$startup 'YakuLingo.lnk')
)
foreach (`$p in `$shortcutPaths) {
  if (Test-Path `$p) {
    try { Remove-Item -Path `$p -Force } catch { }
  }
}
if (Test-Path `$startMenuDir) {
  try { Remove-Item -Path `$startMenuDir -Recurse -Force } catch { }
}

`$cleanupScriptPath = Join-Path `$env:TEMP ("YakuLingo_uninstall_cleanup_{0}.ps1" -f ([guid]::NewGuid().ToString("N")))
`$cleanupScript = @'
param([string]`$TargetDir)
Start-Sleep -Seconds 2
if ([string]::IsNullOrWhiteSpace(`$TargetDir)) { exit 1 }
try { `$full = [System.IO.Path]::GetFullPath(`$TargetDir).TrimEnd('\') } catch { exit 1 }
`$root = [System.IO.Path]::GetPathRoot(`$full).TrimEnd('\')
if (`$full -eq `$root) { exit 1 }
`$installMarkers = @('YakuLingo.exe', 'YakuLingo_Resident.ps1', 'YakuLingo_OpenUI.ps1', 'YakuLingo_Exit.ps1')
`$appMarkers = @('app.py', 'yakulingo', 'config\\settings.template.json')
`$hasInstallMarker = `$false
foreach (`$m in `$installMarkers) {
  if (Test-Path (Join-Path `$full `$m)) { `$hasInstallMarker = `$true; break }
}
`$hasAppMarker = `$false
foreach (`$m in `$appMarkers) {
  if (Test-Path (Join-Path `$full `$m)) { `$hasAppMarker = `$true; break }
}
if (-not (`$hasInstallMarker -and `$hasAppMarker)) { exit 1 }
try { Remove-Item -Path `$full -Recurse -Force } catch { }
try { Remove-Item -Path `$MyInvocation.MyCommand.Definition -Force } catch { }
'@

[System.IO.File]::WriteAllText(`$cleanupScriptPath, `$cleanupScript, (New-Object System.Text.UTF8Encoding `$false))
Start-Process -FilePath powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"`$cleanupScriptPath`" -TargetDir `"`$installDir`"" -WindowStyle Hidden
exit 0
"@

    [System.IO.File]::WriteAllText($OpenUiScriptPath, $openUiScript, $utf8NoBom)
    [System.IO.File]::WriteAllText($ResidentScriptPath, $residentScript, $utf8NoBom)
    [System.IO.File]::WriteAllText($ExitScriptPath, $exitScript, $utf8NoBom)
    [System.IO.File]::WriteAllText($UninstallScriptPath, $uninstallScript, $utf8NoBom)

    # Common icon path
    $IconPath = Join-Path $SetupPath "yakulingo\ui\yakulingo.ico"

    # Desktop shortcut: remove if present (Start Menu only)
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $DesktopShortcutPath = Join-Path $DesktopPath "$AppName.lnk"
    if (Test-Path $DesktopShortcutPath) {
        try {
            Remove-Item -Path $DesktopShortcutPath -Force -ErrorAction Stop
        } catch {
            try { "Failed to remove desktop shortcut: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
        }
    }

    # Start Menu shortcuts (per-user, no subfolder)
    $ProgramsPath = [Environment]::GetFolderPath("Programs")
    $StartMenuDir = Join-Path $ProgramsPath $AppName
    if (Test-Path $StartMenuDir) {
        try {
            Remove-Item -Path $StartMenuDir -Recurse -Force -ErrorAction Stop
        } catch {
            try { "Failed to remove Start Menu folder: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
        }
    }

    $StartMenuOpenPath = Join-Path $ProgramsPath "$AppName.lnk"
    $StartMenuOpen = $WshShell.CreateShortcut($StartMenuOpenPath)
    $StartMenuOpen.TargetPath = "powershell.exe"
    $StartMenuOpen.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ResidentScriptPath`""
    $StartMenuOpen.WorkingDirectory = $SetupPath
    if (Test-Path $IconPath) {
        $StartMenuOpen.IconLocation = "$IconPath,0"
    }
    $StartMenuOpen.Description = "YakuLingo (常駐起動)"
    $StartMenuOpen.Save()

    $StartMenuExitPath = Join-Path $ProgramsPath "$AppName 終了.lnk"
    $StartMenuExit = $WshShell.CreateShortcut($StartMenuExitPath)
    $StartMenuExit.TargetPath = "powershell.exe"
    $StartMenuExit.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ExitScriptPath`""
    $StartMenuExit.WorkingDirectory = $SetupPath
    if (Test-Path $IconPath) {
        $StartMenuExit.IconLocation = "$IconPath,0"
    }
    $StartMenuExit.Description = "YakuLingo を終了"
    $StartMenuExit.Save()

    $StartMenuUninstallPath = Join-Path $ProgramsPath "$AppName アンインストール.lnk"
    $StartMenuUninstall = $WshShell.CreateShortcut($StartMenuUninstallPath)
    $StartMenuUninstall.TargetPath = "powershell.exe"
    $StartMenuUninstall.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$UninstallScriptPath`""
    $StartMenuUninstall.WorkingDirectory = $SetupPath
    if (Test-Path $IconPath) {
        $StartMenuUninstall.IconLocation = "$IconPath,0"
    }
    $StartMenuUninstall.Description = "YakuLingo をアンインストール"
    $StartMenuUninstall.Save()

    # Startup shortcut (auto-start resident service on logon; no UI auto-open)
    $StartupPath = [Environment]::GetFolderPath("Startup")
    $StartupShortcutPath = Join-Path $StartupPath "$AppName.lnk"
    $StartupShortcut = $WshShell.CreateShortcut($StartupShortcutPath)
    $StartupShortcut.TargetPath = "powershell.exe"
    $StartupShortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ResidentScriptPath`""
    $StartupShortcut.WorkingDirectory = $SetupPath
    if (Test-Path $IconPath) {
        $StartupShortcut.IconLocation = "$IconPath,0"
    }
    $StartupShortcut.Description = "YakuLingo (常駐起動)"
    $StartupShortcut.Save()
    if (-not $GuiMode) {
        Write-Host "      Start Menu (Resident): $StartMenuOpenPath" -ForegroundColor Gray
        Write-Host "      Start Menu (Exit): $StartMenuExitPath" -ForegroundColor Gray
        Write-Host "      Start Menu (Uninstall): $StartMenuUninstallPath" -ForegroundColor Gray
        Write-Host "      Startup: $StartupShortcutPath" -ForegroundColor Gray
        Write-Host "[OK] Shortcuts created" -ForegroundColor Green
    }

    # ============================================================
    # Remove legacy Office COM Add-in registration (deprecated)
    # ============================================================
    try {
        $progId = "YakuLingo.OfficeAddin"
        $clsid = "{2BD0EC3D-2947-4873-923C-BF4FC30DB4CB}"

        $officeApps = @("Outlook", "Word", "Excel", "PowerPoint")
        $officeVersions = @("16.0")

        foreach ($app in $officeApps) {
            try {
                $addinKey = "HKCU:\Software\Microsoft\Office\$app\Addins\$progId"
                if (Test-Path $addinKey) {
                    Remove-Item -Path $addinKey -Recurse -Force
                }
            } catch { }

            foreach ($version in $officeVersions) {
                try {
                    $versionedKey = "HKCU:\Software\Microsoft\Office\$version\$app\Addins\$progId"
                    if (Test-Path $versionedKey) {
                        Remove-Item -Path $versionedKey -Recurse -Force
                    }
                } catch { }
            }
        }

        $classesRoot = "HKCU:\Software\Classes"
        $progKey = Join-Path $classesRoot $progId
        if (Test-Path $progKey) {
            Remove-Item -Path $progKey -Recurse -Force
        }
        $clsidKey = Join-Path $classesRoot ("CLSID\$clsid")
        if (Test-Path $clsidKey) {
            Remove-Item -Path $clsidKey -Recurse -Force
        }

        $appKey = "HKCU:\Software\YakuLingo"
        if (Test-Path $appKey) {
            Remove-ItemProperty -Path $appKey -Name "SetupPath" -ErrorAction SilentlyContinue
            $props = (Get-ItemProperty -Path $appKey -ErrorAction SilentlyContinue | Get-Member -MemberType NoteProperty).Count
            if ($props -eq 0) {
                Remove-Item -Path $appKey -Recurse -Force
            }
        }
    } catch {
        try { "Office add-in cleanup failed: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8 } catch { }
    }

    # ============================================================
    # Done
    # ============================================================
    if ($GuiMode) {
        # Final cancellation check before showing success dialog
        if ($script:cancelled) {
            throw "セットアップがキャンセルされました。"
        }
        Write-Status -Message "Starting YakuLingo (resident mode)..." -Progress -Step "Step 4/4: Finalizing" -Percent 95
        # Start YakuLingo immediately in resident mode (no UI auto-open).
        $residentStarted = Start-ResidentService -SetupPath $SetupPath -PythonwPath $PythonwPath -AppPyPath $AppPyPath
        if (-not $residentStarted) {
            throw "YakuLingoの起動に失敗しました。"
        }
        $residentReady = Wait-ResidentReady -Port 8765 -TimeoutSec 1200
        if (-not $residentReady) {
            throw "Copilotの準備が完了しませんでした。ログインを完了してから再実行してください。"
        }

        Write-Status -Message "Setup completed!" -Progress -Step "Step 4/4: Finalizing" -Percent 100
        $successMsg = "セットアップが完了しました。`n`nYakuLingo の画面を開きます。"
        if ($script:GlossaryDistPath -or $script:TranslationRulesDistPath) {
            $successMsg += "`n`n既存ファイルは保持しました。新しい既定ファイル:"
            if ($script:GlossaryDistPath) {
                $successMsg += "`n- $script:GlossaryDistPath"
            }
            if ($script:TranslationRulesDistPath) {
                $successMsg += "`n- $script:TranslationRulesDistPath"
            }
        }
        Show-Success $successMsg
        Open-PostSetupUi -SetupPath $SetupPath
    } else {
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host " Setup completed!" -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host ""
        Write-Host " Location: $SetupPath" -ForegroundColor White
        Write-Host " YakuLingo will start automatically on logon (resident mode)." -ForegroundColor Cyan
        Write-Host " The YakuLingo UI will open now. Copilot login has completed during setup; you're ready to use the app." -ForegroundColor Cyan
        Write-Host " Exit: Start Menu > YakuLingo 終了" -ForegroundColor Cyan
        if ($script:GlossaryDistPath -or $script:TranslationRulesDistPath) {
            Write-Host ""
            Write-Host " Existing files preserved. New defaults saved to:" -ForegroundColor Yellow
            if ($script:GlossaryDistPath) {
                Write-Host "   $script:GlossaryDistPath" -ForegroundColor Yellow
            }
            if ($script:TranslationRulesDistPath) {
                Write-Host "   $script:TranslationRulesDistPath" -ForegroundColor Yellow
            }
        }
        Write-Host ""
        Write-Host " Log files (for troubleshooting):" -ForegroundColor Gray
        Write-Host "   Debug: $debugLog" -ForegroundColor Gray
        Write-Host "   Extract: $extractLogPath" -ForegroundColor Gray
        Write-Host ""

        Write-Host "[INFO] Starting YakuLingo (resident mode)..." -ForegroundColor Gray
        # Start YakuLingo immediately in resident mode (no UI auto-open).
        $residentStarted = Start-ResidentService -SetupPath $SetupPath -PythonwPath $PythonwPath -AppPyPath $AppPyPath
        if (-not $residentStarted) {
            throw "YakuLingoの起動に失敗しました。"
        }
        $residentReady = Wait-ResidentReady -Port 8765 -TimeoutSec 1200
        if (-not $residentReady) {
            throw "Copilotの準備が完了しませんでした。ログインを完了してから再実行してください。"
        }
        Open-PostSetupUi -SetupPath $SetupPath
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
        # Close progress dialog first
        Close-Progress

        # Don't show error dialog if cancelled by user
        if ($script:cancelled) {
            try {
                "=== CANCELLED: $(Get-Date) ===" | Out-File -FilePath $debugLog -Append -Encoding UTF8
            } catch { }
            exit 2  # Exit code 2 = cancelled
        }

        # Write error to debug log (catch block errors)
        try {
            "=== CATCH ERROR: $(Get-Date) ===" | Out-File -FilePath $debugLog -Append -Encoding UTF8
            "Exception: $($_.Exception.Message)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
            "ScriptStackTrace: $($_.ScriptStackTrace)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
            "InvocationInfo: $($_.InvocationInfo.PositionMessage)" | Out-File -FilePath $debugLog -Append -Encoding UTF8
        } catch { }

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
