param(
  [string]$OutputDir = "",
  [ValidateSet("chat", "responses")][string]$ContinuityApiMode = "chat",
  [string]$ModelId = "gpt-oss-swallow-120b-iq4xs",
  [string]$BaseUrl = "",
  [string]$ApiKey = "",
  [switch]$SkipStep8,
  [switch]$SkipBenchmark,
  [switch]$SkipContinuity
)

$ErrorActionPreference = "Stop"

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
  param(
    [Parameter(Mandatory = $true)][string]$Key,
    [Parameter(Mandatory = $true)][string]$PrimaryFile,
    [Parameter(Mandatory = $true)][string]$FallbackFile
  )
  $v = Get-EnvValue -Key $Key -FilePath $PrimaryFile
  if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
  return Get-EnvValue -Key $Key -FilePath $FallbackFile
}

function Test-PlaceholderValue {
  param([string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
  if ($Value -match "<pod-id>" -or $Value -match "^replace_with_" -or $Value -eq "__USE_DPAPI__") { return $true }
  return $false
}

function Convert-SecureToPlainText {
  param([Parameter(Mandatory = $true)][Security.SecureString]$SecureValue)
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Load-RunPodApiKey {
  param([Parameter(Mandatory = $true)][string]$FilePath)
  if (!(Test-Path $FilePath)) { return $null }
  $encrypted = (Get-Content -Raw $FilePath).Trim()
  if ([string]::IsNullOrWhiteSpace($encrypted)) { return $null }
  try {
    $secure = ConvertTo-SecureString -String $encrypted
    return Convert-SecureToPlainText -SecureValue $secure
  } catch {
    return $null
  }
}

function Get-ObfuscationMask {
  return [byte[]](0xA3, 0x5C, 0x91, 0x17, 0x4E, 0xD2, 0x68, 0x2B, 0xF0, 0x3D, 0x86, 0x1A)
}

function Load-SharedObfuscatedApiKey {
  param([Parameter(Mandatory = $true)][string]$FilePath)
  if (!(Test-Path $FilePath)) { return $null }
  $raw = (Get-Content -Raw $FilePath).Trim()
  if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
  $prefix = "YKOBF1:"
  if (-not $raw.StartsWith($prefix)) { return $null }
  $b64 = $raw.Substring($prefix.Length)
  try {
    $bytes = [Convert]::FromBase64String($b64)
    $mask = Get-ObfuscationMask
    for ($i = 0; $i -lt $bytes.Length; $i++) {
      $bytes[$i] = $bytes[$i] -bxor $mask[$i % $mask.Length]
    }
    $decoded = [Text.Encoding]::UTF8.GetString($bytes)
    if ([string]::IsNullOrWhiteSpace($decoded)) { return $null }
    return $decoded
  } catch {
    return $null
  }
}

function Normalize-EvalBaseUrl {
  param([Parameter(Mandatory = $true)][string]$RawUrl)
  $url = $RawUrl.Trim().TrimEnd("/")
  if ($url -match "/v1$") {
    $url = $url.Substring(0, $url.Length - 3)
  }
  return $url
}

function Mask-Url {
  param([string]$Url)
  if ([string]::IsNullOrWhiteSpace($Url)) { return "<empty>" }
  try {
    $uri = [Uri]$Url
    $host = $uri.Host
    $maskedHost = $host -replace "^[^.-]+-", "***-"
    return "$($uri.Scheme)://$maskedHost$($uri.PathAndQuery)"
  } catch {
    return "<masked>"
  }
}

function Invoke-PythonScript {
  param(
    [Parameter(Mandatory = $true)][string]$ScriptPath,
    [Parameter(Mandatory = $true)][string[]]$Args
  )
  if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv run python $ScriptPath @Args
  } else {
    & python $ScriptPath @Args
  }
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed (exit=$LASTEXITCODE): $ScriptPath"
  }
}

$runpodEvalDir = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $runpodEvalDir "..\..")).Path
$nodeInternalDir = Join-Path $runpodEvalDir "node_htmx_client\_internal"
$configEnvLocalFile = Join-Path $nodeInternalDir ".env.local"
$configEnvFile = Join-Path $nodeInternalDir ".env.example"
$sharedObfFile = Join-Path $nodeInternalDir "runpod_api_key.obf"
$localStoreDir = Join-Path $env:LOCALAPPDATA "YakuLingoRunpodHtmx"
$apiKeyStoreFile = Join-Path $localStoreDir "runpod_api_key.dpapi"

if (!(Test-Path $configEnvLocalFile) -and !(Test-Path $configEnvFile) -and [string]::IsNullOrWhiteSpace($BaseUrl)) {
  throw "Config files not found: $configEnvLocalFile, $configEnvFile"
}

$resolvedBaseUrl = $null
if (-not [string]::IsNullOrWhiteSpace($BaseUrl)) {
  $resolvedBaseUrl = $BaseUrl
} else {
  $baseUrlRaw = Get-ConfigValue -Key "RUNPOD_BASE_URL" -PrimaryFile $configEnvLocalFile -FallbackFile $configEnvFile
  if (Test-PlaceholderValue -Value $baseUrlRaw) {
    throw "RUNPOD_BASE_URL is not configured in $configEnvLocalFile or $configEnvFile"
  }
  $resolvedBaseUrl = $baseUrlRaw
}
$baseUrl = Normalize-EvalBaseUrl -RawUrl $resolvedBaseUrl

$resolvedApiKey = $null
if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
  $resolvedApiKey = $ApiKey
} else {
  $apiKeyFromEnv = Get-ConfigValue -Key "RUNPOD_API_KEY" -PrimaryFile $configEnvLocalFile -FallbackFile $configEnvFile
  if (-not (Test-PlaceholderValue -Value $apiKeyFromEnv)) {
    $resolvedApiKey = $apiKeyFromEnv
  }
  if ([string]::IsNullOrWhiteSpace($resolvedApiKey)) {
    $resolvedApiKey = Load-RunPodApiKey -FilePath $apiKeyStoreFile
  }
  if ([string]::IsNullOrWhiteSpace($resolvedApiKey)) {
    $resolvedApiKey = Load-SharedObfuscatedApiKey -FilePath $sharedObfFile
  }
}

if ([string]::IsNullOrWhiteSpace($resolvedApiKey)) {
  throw "RunPod API key not found. Use -ApiKey, start node_htmx_client once, or create _internal/runpod_api_key.obf."
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
  $outputDirPath = Join-Path $runpodEvalDir "logs\local_eval_$timestamp"
} else {
  if ([IO.Path]::IsPathRooted($OutputDir)) {
    $outputDirPath = $OutputDir
  } else {
    $outputDirPath = Join-Path $repoRoot $OutputDir
  }
}
New-Item -ItemType Directory -Force -Path $outputDirPath | Out-Null

$step8Script = Join-Path $runpodEvalDir "step8_gate_check.py"
$benchmarkScript = Join-Path $runpodEvalDir "benchmark_step9.py"
$continuityScript = Join-Path $runpodEvalDir "conversation_continuity_check.py"

Write-Host "RunPod Eval Wrapper (node_htmx_client integration)"
Write-Host "Base URL: $(Mask-Url -Url $baseUrl)"
Write-Host "Model: $ModelId"
Write-Host "Output: $outputDirPath"
Write-Host "Continuity API mode: $ContinuityApiMode"

if (-not $SkipStep8) {
  Write-Host ""
  Write-Host "[1/3] Step8 gate check"
  Invoke-PythonScript -ScriptPath $step8Script -Args @(
    "--base-url", $baseUrl,
    "--api-key", $resolvedApiKey,
    "--model-id", $ModelId,
    "--output-dir", $outputDirPath
  )
}

if (-not $SkipBenchmark) {
  Write-Host ""
  Write-Host "[2/3] Step9 benchmark"
  $benchmarkCsv = Join-Path $outputDirPath "benchmark_step9_raw.csv"
  $benchmarkSummary = Join-Path $outputDirPath "benchmark_step9_summary.log"
  Invoke-PythonScript -ScriptPath $benchmarkScript -Args @(
    "--base-url", $baseUrl,
    "--api-key", $resolvedApiKey,
    "--csv-log", $benchmarkCsv,
    "--summary-log", $benchmarkSummary
  )
}

if (-not $SkipContinuity) {
  Write-Host ""
  Write-Host "[3/3] Conversation continuity ($ContinuityApiMode)"
  $continuityCsv = Join-Path $outputDirPath "conversation_continuity_${ContinuityApiMode}.csv"
  $continuitySummary = Join-Path $outputDirPath "conversation_continuity_${ContinuityApiMode}_summary.txt"
  Invoke-PythonScript -ScriptPath $continuityScript -Args @(
    "--base-url", $baseUrl,
    "--api-key", $resolvedApiKey,
    "--api-mode", $ContinuityApiMode,
    "--csv-log", $continuityCsv,
    "--summary-log", $continuitySummary
  )
}

Write-Host ""
Write-Host "Completed. Artifacts:"
Write-Host "  $outputDirPath"
