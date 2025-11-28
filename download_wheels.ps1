# PowerShell script to download Python wheels using Windows authentication
# This script is used as a fallback when uv sync fails due to proxy authentication

param(
    [string]$ProxyServer,
    [string]$WheelsDir = ".wheels",
    [string]$PythonVersion = "3.11"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Configure proxy with Windows authentication
if ($ProxyServer) {
    $proxy = New-Object System.Net.WebProxy("http://$ProxyServer")
    $proxy.Credentials = [System.Net.CredentialCache]::DefaultNetworkCredentials
    [System.Net.WebRequest]::DefaultWebProxy = $proxy
    Write-Host "[INFO] Proxy configured: $ProxyServer (Windows authentication)"
}

# Create wheels directory
if (-not (Test-Path $WheelsDir)) {
    New-Item -ItemType Directory -Path $WheelsDir | Out-Null
}

# Package list with version constraints
$packages = @(
    @{name="playwright"; version="1.40.0"; op=">="},
    @{name="pywin32"; version="306"; op=">="},
    @{name="customtkinter"; version="5.2.0"; op=">="},
    @{name="pillow"; version="10.0.0"; op=">="},
    @{name="keyboard"; version="0.13.5"; op=">="}
)

# Function to get package info from PyPI
function Get-PyPIPackageInfo {
    param([string]$PackageName)

    $url = "https://pypi.org/pypi/$PackageName/json"
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 30
        return $response.Content | ConvertFrom-Json
    } catch {
        Write-Host "[ERROR] Failed to get package info for $PackageName : $_"
        return $null
    }
}

# Function to find compatible wheel
function Find-CompatibleWheel {
    param(
        [object]$PackageInfo,
        [string]$PythonVersion
    )

    $pyVer = "cp" + ($PythonVersion -replace "\.", "")  # e.g., "cp311"
    $releases = $PackageInfo.urls

    # Priority: Windows x64 wheel > any wheel > source
    $candidates = @()

    foreach ($file in $releases) {
        if ($file.filename -match "\.whl$") {
            $score = 0

            # Check Python version compatibility
            if ($file.filename -match "$pyVer" -or $file.filename -match "py3-none-any") {
                $score += 10
            } elseif ($file.filename -match "py3" -or $file.filename -match "cp3") {
                $score += 5
            }

            # Check platform compatibility
            if ($file.filename -match "win_amd64") {
                $score += 20
            } elseif ($file.filename -match "win32") {
                $score += 15
            } elseif ($file.filename -match "none-any") {
                $score += 10
            }

            if ($score -gt 0) {
                $candidates += @{
                    url = $file.url
                    filename = $file.filename
                    score = $score
                }
            }
        }
    }

    if ($candidates.Count -gt 0) {
        return ($candidates | Sort-Object -Property score -Descending)[0]
    }
    return $null
}

# Function to download a file
function Download-File {
    param(
        [string]$Url,
        [string]$OutFile
    )

    try {
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 120
        return $true
    } catch {
        Write-Host "[ERROR] Download failed: $_"
        return $false
    }
}

# Function to get all dependencies recursively
function Get-AllDependencies {
    param(
        [string]$PackageName,
        [hashtable]$Visited = @{}
    )

    if ($Visited.ContainsKey($PackageName.ToLower())) {
        return @()
    }
    $Visited[$PackageName.ToLower()] = $true

    $info = Get-PyPIPackageInfo -PackageName $PackageName
    if (-not $info) {
        return @()
    }

    $deps = @($PackageName)

    if ($info.info.requires_dist) {
        foreach ($req in $info.info.requires_dist) {
            # Parse requirement (e.g., "packaging>=20.0" or "typing-extensions; python_version < '3.8'")
            # Skip optional/conditional dependencies
            if ($req -match "extra\s*==" -or $req -match ";\s*python_version\s*<") {
                continue
            }

            # Extract package name
            if ($req -match "^([a-zA-Z0-9_-]+)") {
                $depName = $Matches[1]
                $subDeps = Get-AllDependencies -PackageName $depName -Visited $Visited
                $deps += $subDeps
            }
        }
    }

    return $deps
}

Write-Host ""
Write-Host "============================================================"
Write-Host "Downloading Python packages with Windows authentication"
Write-Host "============================================================"
Write-Host ""

# Collect all dependencies
Write-Host "[INFO] Resolving dependencies..."
$allPackages = @{}

foreach ($pkg in $packages) {
    Write-Host "[INFO] Checking dependencies for $($pkg.name)..."
    $deps = Get-AllDependencies -PackageName $pkg.name
    foreach ($dep in $deps) {
        $allPackages[$dep.ToLower()] = $true
    }
}

$packageList = $allPackages.Keys | Sort-Object
Write-Host "[INFO] Total packages to download: $($packageList.Count)"
Write-Host ""

# Download each package
$downloadedCount = 0
$failedPackages = @()

foreach ($pkgName in $packageList) {
    Write-Host "[INFO] Processing: $pkgName"

    $info = Get-PyPIPackageInfo -PackageName $pkgName
    if (-not $info) {
        Write-Host "[WARN] Skipping $pkgName (not found)"
        $failedPackages += $pkgName
        continue
    }

    $wheel = Find-CompatibleWheel -PackageInfo $info -PythonVersion $PythonVersion
    if (-not $wheel) {
        Write-Host "[WARN] No compatible wheel found for $pkgName"
        $failedPackages += $pkgName
        continue
    }

    $outPath = Join-Path $WheelsDir $wheel.filename

    if (Test-Path $outPath) {
        Write-Host "[SKIP] Already downloaded: $($wheel.filename)"
        $downloadedCount++
        continue
    }

    Write-Host "[DOWN] Downloading: $($wheel.filename)"
    if (Download-File -Url $wheel.url -OutFile $outPath) {
        Write-Host "[OK] Downloaded: $($wheel.filename)"
        $downloadedCount++
    } else {
        $failedPackages += $pkgName
    }
}

Write-Host ""
Write-Host "============================================================"
Write-Host "Download Summary"
Write-Host "============================================================"
Write-Host "Downloaded: $downloadedCount packages"
if ($failedPackages.Count -gt 0) {
    Write-Host "Failed: $($failedPackages.Count) packages"
    Write-Host "Failed packages: $($failedPackages -join ', ')"
    exit 1
}
Write-Host "[OK] All packages downloaded successfully"
exit 0
