param(
  [string]$EnvFile = ".env.example",
  [string]$ApiKey = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$resolvedEnvFile = $EnvFile
if (!(Split-Path -Path $resolvedEnvFile -IsAbsolute)) {
  $resolvedEnvFile = Join-Path $PSScriptRoot $resolvedEnvFile
}

if (!(Test-Path $resolvedEnvFile)) {
  Write-Host "Env file not found: $resolvedEnvFile"
  exit 1
}

function Get-EnvValue {
  param([Parameter(Mandatory = $true)][string]$Key)
  $line = Get-Content $resolvedEnvFile | Where-Object { $_ -match "^\s*$Key=" } | Select-Object -First 1
  if (!$line) { return $null }
  return (($line -split "=", 2)[1]).Trim()
}

function Test-PlaceholderValue {
  param([string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
  if ($Value -match "<pod-id>" -or $Value -match "^replace_with_" -or $Value -eq "__USE_DPAPI__") { return $true }
  return $false
}

function Mask-Url {
  param([string]$Url)
  if ([string]::IsNullOrWhiteSpace($Url)) { return "<empty>" }
  try {
    $uri = [Uri]$Url
    $maskedHost = $uri.Host -replace "^[^.-]+-", "***-"
    return "$($uri.Scheme)://$maskedHost$($uri.PathAndQuery)"
  }
  catch {
    return "<masked>"
  }
}

$baseUrl = Get-EnvValue -Key "RUNPOD_BASE_URL"
$token = $ApiKey
if ([string]::IsNullOrWhiteSpace($token)) {
  $token = $env:RUNPOD_API_KEY
}
if ([string]::IsNullOrWhiteSpace($token)) {
  $token = Get-EnvValue -Key "RUNPOD_API_KEY"
}

if (Test-PlaceholderValue -Value $baseUrl) {
  Write-Host "RUNPOD_BASE_URL is missing or placeholder in env file: $resolvedEnvFile"
  exit 1
}

if (Test-PlaceholderValue -Value $token) {
  Write-Host "RUNPOD_API_KEY is missing."
  Write-Host "Set env RUNPOD_API_KEY, pass -ApiKey, or store local DPAPI via set-runpod-api-key.ps1."
  exit 1
}

$modelsUrl = "$($baseUrl.TrimEnd('/'))/models"
$maskedModelsUrl = Mask-Url -Url $modelsUrl
$headers = @{
  Authorization = "Bearer $token"
  "x-api-key"  = $token
}

Write-Host "Testing RunPod endpoint: $maskedModelsUrl"

try {
  $resp = Invoke-RestMethod -Uri $modelsUrl -Headers $headers -Method GET -TimeoutSec 30
}
catch {
  $msg = $_.Exception.Message
  if ($msg) {
    $msg = $msg.Replace($modelsUrl, $maskedModelsUrl)
    $msg = $msg.Replace($baseUrl, (Mask-Url -Url $baseUrl))
  }
  Write-Error "RunPod connection failed ($maskedModelsUrl): $msg"
  exit 1
}

if (!$resp.data) {
  Write-Error "Unexpected response shape. .data not found."
  exit 1
}

Write-Host "RunPod connection OK ($maskedModelsUrl). Models:"
$resp.data | ForEach-Object { Write-Host ("- " + $_.id) }
