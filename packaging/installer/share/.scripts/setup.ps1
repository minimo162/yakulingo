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
trap {
    $errorMsg = "PowerShell Error: $($_.Exception.Message)`nAt: $($_.InvocationInfo.PositionMessage)"
    [Console]::Error.WriteLine($errorMsg)
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
    Write-Status -Message "Preparing destination..." -Progress -Step "Step 1/3: Preparing"
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[1/3] Preparing destination..." -ForegroundColor Yellow
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
    # Step 2: Copy ZIP to temp folder (faster than extracting over network)
    # ============================================================
    Write-Status -Message "Copying files..." -Progress -Step "Step 2/3: Copying"
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[2/3] Copying ZIP to local temp folder..." -ForegroundColor Yellow
    }

    # Clean up any old temp folders first
    Get-ChildItem -Path $env:TEMP -Directory -Filter "YakuLingo_Setup_*" -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item -Path $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }

    $TempZipDir = Join-Path $env:TEMP "YakuLingo_Setup_$(Get-Date -Format 'yyyyMMddHHmmss')"
    New-Item -ItemType Directory -Path $TempZipDir -Force | Out-Null
    $TempZipFile = Join-Path $TempZipDir $ZipFileName
    # Use .NET FileStream with large buffer for fast network file copy
    # 1MB buffer matches Explorer's copy performance better than robocopy for single large files
    $bufferSize = 1MB
    $sourceStream = $null
    $destStream = $null
    try {
        $sourceStream = [System.IO.File]::Open($ZipFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
        $destStream = [System.IO.File]::Create($TempZipFile, $bufferSize)
        $sourceStream.CopyTo($destStream, $bufferSize)
    } finally {
        if ($destStream) { $destStream.Dispose() }
        if ($sourceStream) { $sourceStream.Dispose() }
    }

    if (-not $GuiMode) {
        Write-Host "[OK] ZIP copied to temp folder" -ForegroundColor Green
    }

    # ============================================================
    # Step 3: Extract ZIP locally (much faster than over network)
    # ============================================================
    Write-Status -Message "Extracting files..." -Progress -Step "Step 3/3: Extracting"
    if (-not $GuiMode) {
        Write-Host ""
        Write-Host "[3/3] Extracting files locally..." -ForegroundColor Yellow
        Write-Host "      Extracting with 7-Zip..." -ForegroundColor Gray
    }

    # Extract to temp folder first
    & $script:SevenZip x "$TempZipFile" "-o$TempZipDir" -y -bso0 -bsp0 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        # Clean up temp folder on error
        if (Test-Path $TempZipDir) {
            Remove-Item -Path $TempZipDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw "Failed to extract ZIP file.`n`nFile: $ZipFileName"
    }

    # Find extracted folder
    $ExtractedDir = Get-ChildItem -Path $TempZipDir -Directory | Where-Object { $_.Name -like "YakuLingo*" } | Select-Object -First 1
    if (-not $ExtractedDir) {
        # Clean up temp folder on error
        if (Test-Path $TempZipDir) {
            Remove-Item -Path $TempZipDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw "Failed to extract ZIP file.`n`nFile: $ZipFileName"
    }

    # Copy extracted folder to destination using robocopy (more robust than Move-Item)
    $robocopyResult = & robocopy $ExtractedDir.FullName $SetupPath /E /MOVE /MT:8 /R:3 /W:1 /NFL /NDL /NJH /NJS /NP 2>&1
    # robocopy returns 0-7 for success, 8+ for errors
    if ($LASTEXITCODE -ge 8) {
        # Clean up temp folder on error
        if (Test-Path $TempZipDir) {
            Remove-Item -Path $TempZipDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw "Failed to copy files to destination.`n`nDestination: $SetupPath"
    }

    # Clean up temp folder (robocopy /MOVE should handle most of it, but ensure cleanup)
    if (Test-Path $TempZipDir) {
        Remove-Item -Path $TempZipDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    if (-not $GuiMode) {
        Write-Host "[OK] Extraction completed" -ForegroundColor Green
    }

    # ============================================================
    # Restore/Merge backed up user data files
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

                if ($file -eq "glossary.csv") {
                    # 用語集はマージ（新規用語ペアのみ追加）
                    # 重複判定は「ソース,翻訳」のペア全体で行う（同じソースでも翻訳が違えば追加）
                    $newGlossaryPath = $restorePath
                    if (Test-Path $newGlossaryPath) {
                        # 新しい用語集を一時保存
                        $tempNewGlossary = Join-Path $BackupDir "glossary_new.csv"
                        Copy-Item -Path $newGlossaryPath -Destination $tempNewGlossary -Force

                        # 既存の用語ペア（ソース,翻訳の組み合わせ）を収集
                        $existingPairs = @{}
                        Get-Content -Path $backupPath -Encoding UTF8 | ForEach-Object {
                            $line = $_.Trim()
                            if ($line -and -not $line.StartsWith("#")) {
                                # ペア全体をキーとして保存
                                $existingPairs[$line] = $true
                            }
                        }

                        # バックアップを復元（ユーザーの用語集を戻す）
                        Copy-Item -Path $backupPath -Destination $restorePath -Force

                        # 新しい用語集から、既存にないペアを追加
                        $addedCount = 0
                        Get-Content -Path $tempNewGlossary -Encoding UTF8 | ForEach-Object {
                            $line = $_.Trim()
                            if ($line -and -not $line.StartsWith("#")) {
                                # ペア全体で重複判定
                                if (-not $existingPairs.ContainsKey($line)) {
                                    Add-Content -Path $restorePath -Value $_ -Encoding UTF8
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
                            $newData = Get-Content -Path $tempNewSettings -Encoding UTF8 | ConvertFrom-Json
                            $preservedCount = 0

                            # 新しい設定をベースにする
                            $mergedData = $newData.PSObject.Copy()

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
