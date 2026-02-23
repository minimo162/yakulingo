$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Get-UserSlug {
  $raw = "$env:USERNAME".ToLower()
  $slug = ($raw -replace "[^a-z0-9-]", "")
  if ([string]::IsNullOrWhiteSpace($slug)) { return "user" }
  return $slug
}

$userSlug = Get-UserSlug
$userDir = Join-Path $env:LOCALAPPDATA "YakuLingoRunpodHtmx"
$pidFile = Join-Path $userDir "runpod-htmx-$userSlug.pid"

if (!(Test-Path $pidFile)) {
  Write-Host "No PID file found: $pidFile"
  exit 0
}

$pidRaw = (Get-Content -Raw $pidFile).Trim()
[int]$targetPid = 0
[void][int]::TryParse($pidRaw, [ref]$targetPid)

if ($targetPid -le 0) {
  Remove-Item -Force $pidFile -ErrorAction SilentlyContinue
  Write-Host "Invalid PID file removed."
  exit 0
}

$proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
if ($proc) {
  Stop-Process -Id $targetPid -Force
  Write-Host "Stopped RunPod HTMX client process: PID=$targetPid"
}
else {
  Write-Host "Process already stopped: PID=$targetPid"
}

Remove-Item -Force $pidFile -ErrorAction SilentlyContinue
