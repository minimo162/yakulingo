param(
  [string]$NodeVersion = "v20.20.0",
  [string]$CodexPackage = "@openai/codex@latest"
)

$ErrorActionPreference = "Stop"

$baseDir = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $baseDir ".runtime"
$nodeDir = Join-Path $runtimeRoot "node"
$nodeExe = Join-Path $nodeDir "node.exe"
$codexRoot = Join-Path $runtimeRoot "codex"
$codexBinFile = Join-Path $runtimeRoot "codex-bin.txt"
$npmCli = Join-Path $nodeDir "node_modules\npm\bin\npm-cli.js"

function Resolve-BundledCodexExe {
  param([Parameter(Mandatory = $true)][string]$CodexRoot)
  $candidates = @(
    (Join-Path $CodexRoot "node_modules\.bin\codex.cmd"),
    (Join-Path $CodexRoot "node_modules\.bin\codex.ps1"),
    (Join-Path $CodexRoot "node_modules\.bin\codex")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      try {
        return (Resolve-Path $candidate).Path
      } catch {
        return $candidate
      }
    }
  }
  return $null
}

$nodeReady = Test-Path $nodeExe
if ($nodeReady) {
  Write-Host "Node runtime already exists:"
  Write-Host "  $nodeExe"
  & $nodeExe -v
} else {
  $arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
  $zipName = "node-$NodeVersion-win-$arch.zip"
  $url = "https://nodejs.org/dist/$NodeVersion/$zipName"
  $tmpZip = Join-Path $env:TEMP $zipName
  $tmpExtract = Join-Path $env:TEMP ("node-extract-" + [Guid]::NewGuid().ToString("N"))

  Write-Host "Downloading Node runtime:"
  Write-Host "  $url"
  Invoke-WebRequest -Uri $url -OutFile $tmpZip

  Write-Host "Extracting archive..."
  Expand-Archive -Path $tmpZip -DestinationPath $tmpExtract -Force

  $extractedRoot = Join-Path $tmpExtract ("node-$NodeVersion-win-$arch")
  if (!(Test-Path $extractedRoot)) {
    throw "Extracted Node folder not found: $extractedRoot"
  }

  New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
  if (Test-Path $nodeDir) {
    Remove-Item -Recurse -Force $nodeDir
  }
  Move-Item -Path $extractedRoot -Destination $nodeDir

  Remove-Item -Force $tmpZip -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force $tmpExtract -ErrorAction SilentlyContinue

  Write-Host "Node runtime prepared:"
  Write-Host "  $nodeExe"
  & $nodeExe -v
}

if (!(Test-Path $npmCli)) {
  throw "npm-cli.js was not found in bundled Node runtime: $npmCli"
}

$bundledCodex = Resolve-BundledCodexExe -CodexRoot $codexRoot
if ([string]::IsNullOrWhiteSpace($bundledCodex)) {
  Write-Host "Bundled Codex CLI not found. Installing package:"
  Write-Host "  $CodexPackage"
  New-Item -ItemType Directory -Force -Path $codexRoot | Out-Null
  & $nodeExe $npmCli install --prefix $codexRoot --no-audit --no-fund $CodexPackage
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to install bundled Codex CLI package (exit=$LASTEXITCODE)."
  }
  $bundledCodex = Resolve-BundledCodexExe -CodexRoot $codexRoot
  if ([string]::IsNullOrWhiteSpace($bundledCodex)) {
    throw "Bundled Codex executable was not found after install."
  }
} else {
  Write-Host "Bundled Codex CLI already exists:"
  Write-Host "  $bundledCodex"
}

Set-Content -Path $codexBinFile -Value $bundledCodex -Encoding UTF8
Write-Host "Bundled Codex CLI ready:"
Write-Host "  $bundledCodex"
try {
  & $bundledCodex --version
} catch {
  Write-Warning "Failed to execute bundled codex --version: $($_.Exception.Message)"
}
