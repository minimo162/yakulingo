# ============================================================
# YakuLingo Network Setup Script
# Copies from shared folder to local machine
# ============================================================

param(
    [string]$SetupPath = "",
    [switch]$GuiMode = $false
)

$ErrorActionPreference = "Stop"

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
    Write-ErrorLog -ErrorRecord $_
    exit 1
}

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

    $driveRoot = [System.IO.Path]::GetPathRoot($resolvedPath)
    if ($resolvedPath -eq $driveRoot) {
        throw "SetupPath points to a drive root. Please specify a subdirectory (e.g., $($env:LOCALAPPDATA)\\$AppName)."
    }

    $dangerousRoots = @(
        $env:USERPROFILE,
        $env:LOCALAPPDATA,
        $env:APPDATA,
        [Environment]::GetFolderPath("Windows"),
        [Environment]::GetFolderPath("ProgramFiles"),
        [Environment]::GetFolderPath("ProgramFilesX86"),
        [Environment]::GetFolderPath("System"),
        [Environment]::GetFolderPath("SystemX86")
    ) | Where-Object { $_ }

    foreach ($dangerousRoot in $dangerousRoots) {
        if ($resolvedPath.TrimEnd('\\') -eq $dangerousRoot.TrimEnd('\\')) {
            throw "SetupPath cannot be a system directory: $resolvedPath"
        }
    }

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
        [int]$BufferSize = 1MB
    )

    $sourceStream = $null
    $destStream = $null
    try {
        $sourceStream = [System.IO.File]::Open($Source, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
        $destStream = [System.IO.File]::Create($Destination, $BufferSize)
        $sourceStream.CopyTo($destStream, $BufferSize)
    } finally {
        if ($destStream) { $destStream.Dispose() }
        if ($sourceStream) { $sourceStream.Dispose() }
    }
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
        throw "pyvenv.cfg not found. The package seems to be incomplete." 
    }

    # Find python.exe in .uv-python (structure: .uv-python/cpython-x.x.x-*/python.exe)
    # Only search one level deep to avoid slow recursive enumeration
    $uvPythonDir = Join-Path $SetupPath ".uv-python"
    $pythonExe = $null
    Get-ChildItem -Path $uvPythonDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $candidate = Join-Path $_.FullName "python.exe"
        if (Test-Path $candidate) {
            $pythonExe = Get-Item $candidate
            return  # Break out of ForEach-Object
        }
    }
    if (-not $pythonExe) {
        throw "python.exe not found under .uv-python. Please ensure the distribution contains the bundled Python runtime."
    }

    $pythonHome = Split-Path -Parent $pythonExe.FullName

    $updated = $false
    $newLines = Get-Content -Path $pyvenvPath | ForEach-Object {
        if ($_ -match '^home\s*=') {
            $updated = $true
            "home = $pythonHome"
        } else {
            $_
        }
    }

    if (-not $updated) {
        $newLines += "home = $pythonHome"
    }

    $newLines | Set-Content -Path $pyvenvPath -Encoding ASCII
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
    $ZipInfo = Get-LatestZipFile -ShareDir $ShareDir
    $ZipFile = $ZipInfo.FullName
    $ZipFileName = $ZipInfo.Name
    if (-not $GuiMode) {
        Write-Host "[INFO] Using: $ZipFileName" -ForegroundColor Cyan
    }

    # Default path: LocalAppData\YakuLingo with safety checks
    $SetupPath = Resolve-SetupPath -InputPath $SetupPath -AppName $AppName

    # ============================================================
    # Step 1: Prepare destination (backup user data first)
    # ============================================================
    Write-Status -Message "Preparing destination..." -Progress -Step "Step 1/4: Preparing" -Percent 5
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[1/4] Preparing destination..." -ForegroundColor Yellow
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

    # Use .NET FileStream with large buffer for fast network file copy
    # 1MB buffer matches Explorer's copy performance better than robocopy for single large files
    Copy-FileBuffered -Source $ZipFile -Destination $TempZipFile

    if (-not $GuiMode) {
        Write-Host "[OK] ZIP copied to temp folder" -ForegroundColor Green
    }
    Write-Status -Message "Files copied" -Progress -Step "Step 2/4: Copying" -Percent 50

    # ============================================================
    # Step 3: Extract ZIP locally (much faster than over network)
    # ============================================================
    Write-Status -Message "Extracting files..." -Progress -Step "Step 3/4: Extracting" -Percent 60
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[3/4] Extracting files locally..." -ForegroundColor Yellow
        Write-Host "      Extracting with 7-Zip..." -ForegroundColor Gray
    }

    try {
        # Extract to temp folder first
        & $script:SevenZip x "$TempZipFile" "-o$TempZipDir" -y -bso0 -bsp0 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to extract ZIP file.`n`nFile: $ZipFileName"
        }

        # Find extracted folder
        $ExtractedDir = Get-ChildItem -Path $TempZipDir -Directory | Where-Object { $_.Name -like "YakuLingo*" } | Select-Object -First 1
        if (-not $ExtractedDir) {
            throw "Failed to extract ZIP file.`n`nFile: $ZipFileName"
        }

        # Copy extracted folder to destination using robocopy /MIR (mirror mode)
        # /MIR = /E + /PURGE: copies all files and removes files not in source
        # This ensures clean updates without needing to delete the destination first
        # /R:0 /W:0: don't retry locked files (skip them instead of hanging)
        $robocopyResult = & robocopy $ExtractedDir.FullName $SetupPath /MIR /MT:8 /R:0 /W:0 /NFL /NDL /NJH /NJS /NP 2>&1
        $robocopyExitCode = $LASTEXITCODE
        # robocopy returns 0-7 for success, 8+ for errors
        if ($robocopyExitCode -ge 8) {
            throw "Failed to copy files to destination.`n`nDestination: $SetupPath"
        }
        # Warn if some files were skipped (exit code 1-7 indicates partial success)
        if ($robocopyExitCode -gt 0 -and $robocopyExitCode -lt 8) {
            if (-not $GuiMode) {
                Write-Host "      Warning: Some files may have been skipped (exit code: $robocopyExitCode)" -ForegroundColor Yellow
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

    # Fix pyvenv.cfg placeholder (__PYTHON_HOME__) to the actual bundled runtime path
    Write-Status -Message "Configuring Python runtime..." -Progress -Step "Step 3/4: Extracting" -Percent 85
    Update-PyVenvConfig -SetupPath $SetupPath
    if (-not $GuiMode) {
        Write-Host "      Updated pyvenv.cfg with bundled Python path" -ForegroundColor Gray
    }

    # ============================================================
    # Restore/Merge backed up user data files
    # ============================================================
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

                if ($file -eq "glossary.csv") {
                    # 用語集はマージ（新規用語ペアのみ追加）
                    # 重複判定は「ソース,翻訳」のペア全体で行う（同じソースでも翻訳が違えば追加）
                    $newGlossaryPath = $restorePath
                    if (Test-Path $newGlossaryPath) {
                        # 新しい用語集を一時保存
                        $tempNewGlossary = Join-Path $BackupDir "glossary_new.csv"
                        Copy-Item -Path $newGlossaryPath -Destination $tempNewGlossary -Force

                        # 既存の用語ペア（ソース,翻訳の組み合わせ）を収集
                        # Trimして正規化した値をキーとして使用
                        $existingPairs = @{}
                        Get-Content -Path $backupPath -Encoding UTF8 | ForEach-Object {
                            $line = $_.Trim()
                            if ($line -and -not $line.StartsWith("#")) {
                                # ペア全体をキーとして保存（正規化済み）
                                $existingPairs[$line] = $true
                            }
                        }

                        # バックアップを復元（ユーザーの用語集を戻す）
                        Copy-Item -Path $backupPath -Destination $restorePath -Force

                        # ファイル末尾に改行があるか確認し、なければ追加
                        $content = [System.IO.File]::ReadAllText($restorePath)
                        if ($content.Length -gt 0 -and -not $content.EndsWith("`n")) {
                            Add-Content -Path $restorePath -Value "" -Encoding UTF8
                        }

                        # 新しい用語集から、既存にないペアを追加
                        $addedCount = 0
                        Get-Content -Path $tempNewGlossary -Encoding UTF8 | ForEach-Object {
                            $line = $_.Trim()
                            if ($line -and -not $line.StartsWith("#")) {
                                # ペア全体で重複判定（正規化済みの値で比較）
                                if (-not $existingPairs.ContainsKey($line)) {
                                    # 正規化した値を追加（末尾スペース等を除去）
                                    Add-Content -Path $restorePath -Value $line -Encoding UTF8
                                    $addedCount++
                                }
                            }
                        }

                        if (-not $GuiMode) {
                            if ($addedCount -gt 0) {
                                Write-Host "      Merged: $file (+$addedCount new terms)" -ForegroundColor Gray
                            } else {
                                Write-Host "      Restored: $file (no new terms)" -ForegroundColor Gray
                            }
                        }
                    } else {
                        # 新しい用語集がなければバックアップを復元
                        Copy-Item -Path $backupPath -Destination $restorePath -Force
                        if (-not $GuiMode) {
                            Write-Host "      Restored: $file" -ForegroundColor Gray
                        }
                    }
                } elseif ($file -eq "config\settings.json") {
                    # 設定ファイルはマージ（ユーザー保護対象の設定のみ保持）
                    # 新しい設定をベースとし、ユーザー設定の一部のみ上書き
                    $newSettingsPath = $restorePath
                    $templateSettingsPath = Join-Path $SetupPath "config\\settings.template.json"
                    if (-not (Test-Path $newSettingsPath) -and (Test-Path $templateSettingsPath)) {
                        # settings.json が無い場合はテンプレートを使用（アップデーターと同様の挙動）
                        $newSettingsPath = $templateSettingsPath
                    }

                    if (Test-Path $newSettingsPath) {
                        # 新しい設定を一時保存
                        $tempNewSettings = Join-Path $BackupDir "settings_new.json"
                        Copy-Item -Path $newSettingsPath -Destination $tempNewSettings -Force

                        # ユーザーがUIで変更した設定（これ以外は開発者が自由に変更可能）
                        $UserProtectedSettings = @(
                            # 翻訳スタイル設定（設定ダイアログで変更）
                            "translation_style",
                            "text_translation_style",
                            # フォント設定（設定ダイアログで変更）
                            "font_jp_to_en",
                            "font_en_to_jp",
                            "font_size_adjustment_jp_to_en",
                            # 出力オプション（ファイル翻訳パネルで変更）
                            "bilingual_output",
                            "export_glossary",
                            "use_bundled_glossary",
                            # UI状態（自動保存）
                            "last_tab",
                            "onboarding_completed",
                            # 更新設定（更新ダイアログで変更）
                            "skipped_version"
                        )

                        # JSONをマージ
                        try {
                            $userData = Get-Content -Path $backupPath -Encoding UTF8 | ConvertFrom-Json
                            $newDataJson = Get-Content -Path $tempNewSettings -Encoding UTF8 -Raw
                            $newData = $newDataJson | ConvertFrom-Json
                            $preservedCount = 0

                            # 新しい設定をベースにする（深いコピー: JSON経由で再生成）
                            $mergedData = $newDataJson | ConvertFrom-Json

                            # ユーザー保護対象の設定のみを上書き
                            foreach ($key in $UserProtectedSettings) {
                                if ($userData.PSObject.Properties.Name -contains $key) {
                                    # 新しい設定にもキーが存在する場合のみ復元（削除された設定は復元しない）
                                    if ($newData.PSObject.Properties.Name -contains $key) {
                                        $mergedData.$key = $userData.$key
                                        $preservedCount++
                                    }
                                }
                            }

                            # 保存
                            $mergedData | ConvertTo-Json -Depth 10 | Set-Content -Path $restorePath -Encoding UTF8

                            # 変更カウント
                            $addedKeys = $newData.PSObject.Properties.Name | Where-Object { -not ($userData.PSObject.Properties.Name -contains $_) }
                            $removedKeys = $userData.PSObject.Properties.Name | Where-Object { -not ($newData.PSObject.Properties.Name -contains $_) }

                            if (-not $GuiMode) {
                                $addedCount = @($addedKeys).Count
                                $removedCount = @($removedKeys).Count
                                if ($addedCount -gt 0 -or $removedCount -gt 0) {
                                    $msg = "      Merged: $file"
                                    if ($addedCount -gt 0) { $msg += " (+$addedCount new)" }
                                    if ($removedCount -gt 0) { $msg += " (-$removedCount removed)" }
                                    Write-Host $msg -ForegroundColor Gray
                                } else {
                                    Write-Host "      Merged: $file (user settings preserved)" -ForegroundColor Gray
                                }
                            }
                        } catch {
                            # マージに失敗した場合は新しい設定を使用
                            if (-not $GuiMode) {
                                Write-Host "      Using new settings: $file (merge failed)" -ForegroundColor Gray
                            }
                        }
                    } else {
                        # 新しい設定がなければバックアップを復元
                        Copy-Item -Path $backupPath -Destination $restorePath -Force
                        if (-not $GuiMode) {
                            Write-Host "      Restored: $file" -ForegroundColor Gray
                        }
                    }
                } else {
                    # その他のファイルはそのまま復元
                    Copy-Item -Path $backupPath -Destination $restorePath -Force
                    if (-not $GuiMode) {
                        Write-Host "      Restored: $file" -ForegroundColor Gray
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
        Write-Status -Message "Setup completed!" -Progress -Step "Step 4/4: Finalizing" -Percent 100
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
