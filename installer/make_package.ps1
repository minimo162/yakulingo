# YakuLingo Package Creation Script
# Creates a distribution package with bundled dependencies

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "YakuLingo Package Creator" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Path settings
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir
$outputDir = Join-Path $scriptDir "output"
$tempDir = Join-Path $scriptDir "temp_package"
$packageDir = Join-Path $tempDir "YakuLingo"  # Folder name in zip
$internalDir = Join-Path $packageDir "_internal"  # Internal files

# Check for dependency folders
$requiredDeps = @(".venv", ".uv-python", ".playwright-browsers")
$missingDeps = @()

foreach ($dep in $requiredDeps) {
    $depPath = Join-Path $projectDir $dep
    if (-not (Test-Path $depPath)) {
        $missingDeps += $dep
    }
}

if ($missingDeps.Count -gt 0) {
    Write-Host "[ERROR] The following dependency folders are missing:" -ForegroundColor Red
    foreach ($dep in $missingDeps) {
        Write-Host "  - $dep" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Please run install_deps.bat first to get dependencies."
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[OK] Dependency folders verified"

# Create output directory
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

# Clean up temp directory
if (Test-Path $tempDir) {
    Remove-Item -Path $tempDir -Recurse -Force
}
New-Item -ItemType Directory -Path $packageDir -Force | Out-Null
New-Item -ItemType Directory -Path $internalDir -Force | Out-Null

Write-Host ""
Write-Host "[1/4] Copying app files..."

# Files to copy
$files = @(
    "app.py",
    "pyproject.toml",
    "requirements.txt",
    "glossary.csv",
    "remove.bat",
    "remove.ps1"
)

# App folders to copy
$appFolders = @(
    "yakulingo",
    "prompts",
    "config"
)

# Copy files to _internal
foreach ($file in $files) {
    $source = Join-Path $projectDir $file
    if (Test-Path $source) {
        Copy-Item $source $internalDir -Force
    }
}

# Copy setup.bat to root (the only file users see)
Copy-Item (Join-Path $projectDir "★setup.bat") $packageDir -Force

# Copy setup.ps1 to _internal
Copy-Item (Join-Path $projectDir "setup.ps1") $internalDir -Force

# Copy run.bat to _internal (remove star)
Copy-Item (Join-Path $projectDir "★run.bat") (Join-Path $internalDir "run.bat") -Force

# Copy app folders to _internal
foreach ($folder in $appFolders) {
    $source = Join-Path $projectDir $folder
    if (Test-Path $source) {
        Copy-Item $source $internalDir -Recurse -Force
    }
}

Write-Host "[OK] App files copied"

Write-Host "[2/4] Copying dependencies (this may take a while)..."

# Copy dependency folders to _internal
foreach ($dep in $requiredDeps) {
    $source = Join-Path $projectDir $dep
    Write-Host "  Copying: $dep ..."
    Copy-Item $source $internalDir -Recurse -Force
}

Write-Host "[OK] Dependencies copied"

Write-Host "[3/4] Creating ZIP (this may take a while)..."

# Output file name
$zipPath = Join-Path $outputDir "YakuLingo.zip"

# Delete existing zip
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

# Create ZIP (compress entire YakuLingo folder)
Compress-Archive -Path $packageDir -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host "[OK] ZIP created"

Write-Host "[4/4] Cleaning up..."

# Delete temp folder
Remove-Item -Path $tempDir -Recurse -Force

Write-Host "[OK] Cleanup complete"

# Display file size
$zipSize = (Get-Item $zipPath).Length / 1MB
$zipSizeStr = "{0:N2} MB" -f $zipSize

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Package Created!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Output: $zipPath"
Write-Host "Size: $zipSizeStr"
Write-Host ""
Write-Host "Distribution:"
Write-Host "  1. Send YakuLingo.zip to users"
Write-Host "  2. Users extract and run setup.bat"
Write-Host "  3. Launch from Start Menu or Desktop"
Write-Host ""

Read-Host "Press Enter to exit"
