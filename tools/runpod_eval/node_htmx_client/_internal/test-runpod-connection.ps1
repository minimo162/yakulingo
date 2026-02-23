param(
  [string]$EnvFile = ".env.local",
  [string]$FallbackEnvFile = ".env.example",
  [string]$ApiKey = "",
  [int]$MaxAttempts = 0,
  [int]$RetryDelaySec = 0,
  [int]$RequestTimeoutSec = 0,
  [switch]$SoftFail
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$resolvedEnvFile = $EnvFile
if (!(Split-Path -Path $resolvedEnvFile -IsAbsolute)) {
  $resolvedEnvFile = Join-Path $PSScriptRoot $resolvedEnvFile
}

$resolvedFallbackEnvFile = $FallbackEnvFile
if (!(Split-Path -Path $resolvedFallbackEnvFile -IsAbsolute)) {
  $resolvedFallbackEnvFile = Join-Path $PSScriptRoot $resolvedFallbackEnvFile
}

function Get-EnvValue {
  param(
    [Parameter(Mandatory = $true)][string]$Key,
    [Parameter(Mandatory = $true)][string]$FilePath
  )
  if (!(Test-Path $FilePath)) { return $null }
  $line = Get-Content $FilePath | Where-Object { $_ -match "^\s*$Key=" } | Select-Object -First 1
  if (!$line) { return $null }
  return (($line -split "=", 2)[1]).Trim()
}

function Get-ConfigValue {
  param([Parameter(Mandatory = $true)][string]$Key)
  $v = Get-EnvValue -Key $Key -FilePath $resolvedEnvFile
  if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
  return Get-EnvValue -Key $Key -FilePath $resolvedFallbackEnvFile
}

function Convert-ToIntOrDefault {
  param(
    [Parameter(Mandatory = $false)][string]$Value,
    [Parameter(Mandatory = $true)][int]$DefaultValue,
    [Parameter(Mandatory = $true)][int]$MinValue,
    [Parameter(Mandatory = $true)][int]$MaxValue
  )
  [int]$parsed = 0
  if (-not [int]::TryParse([string]$Value, [ref]$parsed)) {
    return $DefaultValue
  }
  if ($parsed -lt $MinValue) { return $MinValue }
  if ($parsed -gt $MaxValue) { return $MaxValue }
  return $parsed
}

function Get-StatusCodeFromException {
  param([Parameter(Mandatory = $false)]$Exception)
  if ($null -eq $Exception) { return 0 }

  $response = $Exception.Response
  if ($null -ne $response) {
    try {
      if ($response.StatusCode) {
        return [int]$response.StatusCode
      }
    } catch {
      try {
        if ($response.StatusCode.value__) {
          return [int]$response.StatusCode.value__
        }
      } catch {}
    }
  }

  $msg = [string]$Exception.Message
  if ($msg -match "\((\d{3})\)") {
    return [int]$matches[1]
  }

  if ($Exception.InnerException) {
    return Get-StatusCodeFromException -Exception $Exception.InnerException
  }

  return 0
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

if (!(Test-Path $resolvedEnvFile) -and !(Test-Path $resolvedFallbackEnvFile)) {
  Write-Host "Env files not found:"
  Write-Host "  primary: $resolvedEnvFile"
  Write-Host "  fallback: $resolvedFallbackEnvFile"
  exit 1
}

$baseUrl = Get-ConfigValue -Key "RUNPOD_BASE_URL"
$token = $ApiKey
if ([string]::IsNullOrWhiteSpace($token)) {
  $token = $env:RUNPOD_API_KEY
}
if ([string]::IsNullOrWhiteSpace($token)) {
  $token = Get-ConfigValue -Key "RUNPOD_API_KEY"
}

if (Test-PlaceholderValue -Value $baseUrl) {
  Write-Host "RUNPOD_BASE_URL is missing or placeholder."
  Write-Host "  primary: $resolvedEnvFile"
  Write-Host "  fallback: $resolvedFallbackEnvFile"
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

$maxAttemptsConfigured = Convert-ToIntOrDefault -Value (Get-ConfigValue -Key "RUNPOD_CONNECTION_TEST_MAX_ATTEMPTS") -DefaultValue 4 -MinValue 1 -MaxValue 20
$retryDelayConfigured = Convert-ToIntOrDefault -Value (Get-ConfigValue -Key "RUNPOD_CONNECTION_TEST_RETRY_DELAY_SEC") -DefaultValue 2 -MinValue 1 -MaxValue 60
$timeoutConfigured = Convert-ToIntOrDefault -Value (Get-ConfigValue -Key "RUNPOD_CONNECTION_TEST_TIMEOUT_SEC") -DefaultValue 8 -MinValue 3 -MaxValue 120

if ($MaxAttempts -le 0) { $MaxAttempts = $maxAttemptsConfigured }
if ($RetryDelaySec -le 0) { $RetryDelaySec = $retryDelayConfigured }
if ($RequestTimeoutSec -le 0) { $RequestTimeoutSec = $timeoutConfigured }

Write-Host "Testing RunPod endpoint: $maskedModelsUrl"
Write-Host "Connection test retry policy: attempts=$MaxAttempts delay=${RetryDelaySec}s timeout=${RequestTimeoutSec}s"

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
  try {
    $resp = Invoke-RestMethod -Uri $modelsUrl -Headers $headers -Method GET -TimeoutSec $RequestTimeoutSec
    if (!$resp.data) {
      throw "Unexpected response shape. .data not found."
    }

    Write-Host "RunPod connection OK ($maskedModelsUrl). Models:"
    $resp.data | ForEach-Object { Write-Host ("- " + $_.id) }
    exit 0
  }
  catch {
    $statusCode = Get-StatusCodeFromException -Exception $_.Exception
    $msg = $_.Exception.Message
    if ($msg) {
      $msg = $msg.Replace($modelsUrl, $maskedModelsUrl)
      $msg = $msg.Replace($baseUrl, (Mask-Url -Url $baseUrl))
    }

    $isTransient = @(
      0,   # transport/DNS/timeout etc.
      408, # request timeout
      425, # too early
      429, # rate limited
      499, # client closed request / proxy edge case
      500, # internal server error
      502, # bad gateway (common during pod warmup)
      503, # service unavailable
      504, # gateway timeout
      520, # unknown error (cloudflare/proxy edge)
      521, # web server down
      522, # connection timed out
      523, # origin unreachable
      524, # timeout occurred
      525, # SSL handshake failed
      526  # invalid SSL certificate
    ) -contains $statusCode

    if ($isTransient -and $attempt -lt $MaxAttempts) {
      Write-Warning "RunPod connection attempt $attempt/$MaxAttempts failed (HTTP $statusCode): $msg"
      Write-Host "Retrying in $RetryDelaySec second(s)..."
      Start-Sleep -Seconds $RetryDelaySec
      continue
    }

    $errorText = "RunPod connection failed after $attempt attempt(s) ($maskedModelsUrl, HTTP $statusCode): $msg"
    if ($SoftFail) {
      Write-Warning "$errorText"
      Write-Warning "Continue startup because connection test is running in soft-fail mode."
      exit 0
    }

    Write-Error $errorText
    exit 1
  }
}
