param(
  [string]$NodeVersion = "v20.20.0"
)

$ErrorActionPreference = "Stop"

$baseDir = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $baseDir ".runtime"
$nodeDir = Join-Path $runtimeRoot "node"
$nodeExe = Join-Path $nodeDir "node.exe"

if (Test-Path $nodeExe) {
  Write-Host "Node runtime already exists:"
  Write-Host "  $nodeExe"
  & $nodeExe -v
  exit 0
}

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
