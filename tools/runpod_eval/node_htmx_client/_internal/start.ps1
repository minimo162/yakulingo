param(
  [int]$Port = 0,
  [switch]$SkipConnectionTest,
  [switch]$NoOpenBrowser,
  [switch]$NoHealthCheck
)

$ErrorActionPreference = "Stop"
$BaseDir = Split-Path -Parent $PSScriptRoot
Set-Location $BaseDir

function Get-UserSlug {
  $raw = "$env:USERNAME".ToLower()
  $slug = ($raw -replace "[^a-z0-9-]", "")
  if ([string]::IsNullOrWhiteSpace($slug)) { return "user" }
  return $slug
}

function Get-EnvValue {
  param(
    [Parameter(Mandatory = $true)] [string]$Key,
    [Parameter(Mandatory = $true)] [string]$FilePath
  )
  if (!(Test-Path $FilePath)) { return $null }
  $line = Get-Content $FilePath | Where-Object { $_ -match "^\s*$Key=" } | Select-Object -First 1
  if (!$line) { return $null }
  return (($line -split "=", 2)[1]).Trim()
}

function Set-EnvValue {
  param(
    [Parameter(Mandatory = $true)] [string]$Key,
    [Parameter(Mandatory = $true)] [string]$Value,
    [Parameter(Mandatory = $true)] [string]$FilePath
  )
  $lines = @()
  if (Test-Path $FilePath) { $lines = Get-Content $FilePath }
  $updated = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match "^\s*$Key=") {
      $lines[$i] = "$Key=$Value"
      $updated = $true
      break
    }
  }
  if (-not $updated) { $lines += "$Key=$Value" }
  Set-Content -Path $FilePath -Value $lines -Encoding UTF8
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

function Save-RunPodApiKey {
  param(
    [Parameter(Mandatory = $true)][string]$ApiKey,
    [Parameter(Mandatory = $true)][string]$FilePath
  )
  $secure = ConvertTo-SecureString -String $ApiKey -AsPlainText -Force
  $encrypted = $secure | ConvertFrom-SecureString
  Set-Content -Path $FilePath -Value $encrypted -Encoding UTF8
  try { cmd /c "attrib +h `"$FilePath`"" | Out-Null } catch {}
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

function Resolve-NodeExe {
  param([Parameter(Mandatory = $true)][string]$BaseDir)
  $runtimeNode = Join-Path $BaseDir ".runtime\node\node.exe"
  if (Test-Path $runtimeNode) {
    return $runtimeNode
  }
  return $null
}

$userSlug = Get-UserSlug
$userDir = Join-Path $env:LOCALAPPDATA "YakuLingoRunpodHtmx"
$userEnvFile = Join-Path $userDir "runpod-htmx.env"
$apiKeyStoreFile = Join-Path $userDir "runpod_api_key.dpapi"
$pidFile = Join-Path $userDir "runpod-htmx-$userSlug.pid"
$logDir = Join-Path $userDir "logs"
$outLog = Join-Path $logDir "runpod-htmx-$userSlug.out.log"
$errLog = Join-Path $logDir "runpod-htmx-$userSlug.err.log"
$templateEnv = Join-Path $PSScriptRoot ".env.example"
$sharedObfFile = Join-Path $PSScriptRoot "runpod_api_key.obf"
$apiKeyMarker = "__USE_DPAPI__"

New-Item -ItemType Directory -Force -Path $userDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (!(Test-Path $templateEnv)) {
  Write-Host "Template env file not found:"
  Write-Host "  $templateEnv"
  exit 1
}

if (!(Test-Path $userEnvFile)) {
  Copy-Item $templateEnv $userEnvFile
  Write-Host "Created per-user env file:"
  Write-Host "  $userEnvFile"
}

if ($PSBoundParameters.ContainsKey("Port") -and $Port -gt 0) {
  Set-EnvValue -Key "APP_PORT" -Value "$Port" -FilePath $userEnvFile
}

$baseUrl = Get-EnvValue -Key "RUNPOD_BASE_URL" -FilePath $userEnvFile
if (Test-PlaceholderValue -Value $baseUrl) {
  Write-Host "Please update these values in:"
  Write-Host "  $userEnvFile"
  Write-Host ""
  Write-Host "Required:"
  Write-Host "  RUNPOD_BASE_URL=https://<pod-id>-11434.proxy.runpod.net/v1"
  Write-Host "  RUNPOD_API_KEY=__USE_DPAPI__   (keep this marker)"
  Write-Host ""
  Start-Process notepad.exe $userEnvFile | Out-Null
  exit 1
}

$keyInEnv = Get-EnvValue -Key "RUNPOD_API_KEY" -FilePath $userEnvFile
if (-not (Test-PlaceholderValue -Value $keyInEnv)) {
  Save-RunPodApiKey -ApiKey $keyInEnv -FilePath $apiKeyStoreFile
  Set-EnvValue -Key "RUNPOD_API_KEY" -Value $apiKeyMarker -FilePath $userEnvFile
}
elseif ([string]::IsNullOrWhiteSpace($keyInEnv)) {
  Set-EnvValue -Key "RUNPOD_API_KEY" -Value $apiKeyMarker -FilePath $userEnvFile
}

$runPodApiKey = Load-RunPodApiKey -FilePath $apiKeyStoreFile
if ([string]::IsNullOrWhiteSpace($runPodApiKey)) {
  $sharedKey = Load-SharedObfuscatedApiKey -FilePath $sharedObfFile
  if (-not [string]::IsNullOrWhiteSpace($sharedKey)) {
    $runPodApiKey = $sharedKey
    Save-RunPodApiKey -ApiKey $runPodApiKey -FilePath $apiKeyStoreFile
    Write-Host "Imported RunPod API key from shared obfuscated file."
  }
}

if ([string]::IsNullOrWhiteSpace($runPodApiKey)) {
  Write-Host "RunPod API key was not found in local secure store."
  Write-Host "Shared obfuscated key file:"
  Write-Host "  $sharedObfFile"
  Write-Host "Enter token from /workspace/.auth_token (input hidden):"
  $secureInput = Read-Host "RUNPOD_API_KEY" -AsSecureString
  $runPodApiKey = Convert-SecureToPlainText -SecureValue $secureInput
  if ([string]::IsNullOrWhiteSpace($runPodApiKey)) {
    Write-Host "Empty key. Aborted."
    exit 1
  }
  Save-RunPodApiKey -ApiKey $runPodApiKey -FilePath $apiKeyStoreFile
}

if (-not $SkipConnectionTest) {
  & (Join-Path $PSScriptRoot "test-runpod-connection.ps1") -EnvFile $userEnvFile -ApiKey $runPodApiKey
}

$nodeExe = Resolve-NodeExe -BaseDir $BaseDir
if ([string]::IsNullOrWhiteSpace($nodeExe)) {
  $prepareScript = Join-Path $PSScriptRoot "prepare-node-runtime.ps1"
  if (!(Test-Path $prepareScript)) {
    Write-Host "Bundled Node.js runtime is missing and prepare script is not found:"
    Write-Host "  $prepareScript"
    exit 1
  }

  Write-Host "Bundled Node.js runtime not found. Preparing now..."
  & $prepareScript
  $nodeExe = Resolve-NodeExe -BaseDir $BaseDir
  if ([string]::IsNullOrWhiteSpace($nodeExe)) {
    Write-Host "Failed to prepare bundled Node.js runtime."
    exit 1
  }
}

$serverScript = Join-Path $PSScriptRoot "server.mjs"
if (!(Test-Path $serverScript)) {
  Write-Host "Server script not found: $serverScript"
  exit 1
}

if (Test-Path $pidFile) {
  $existingPidRaw = (Get-Content -Raw $pidFile).Trim()
  [int]$existingPid = 0
  [void][int]::TryParse($existingPidRaw, [ref]$existingPid)
  if ($existingPid -gt 0) {
    $p = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
    if ($p) {
      $existingPort = Get-EnvValue -Key "APP_PORT" -FilePath $userEnvFile
      if ([string]::IsNullOrWhiteSpace($existingPort)) { $existingPort = "$Port" }
      Write-Host "RunPod HTMX client already running (PID=$existingPid)."
      if (-not $NoOpenBrowser) { Start-Process "http://localhost:$existingPort/" | Out-Null }
      exit 0
    }
  }
  Remove-Item -Force $pidFile -ErrorAction SilentlyContinue
}

$defaultModel = Get-EnvValue -Key "DEFAULT_MODEL" -FilePath $userEnvFile
if ([string]::IsNullOrWhiteSpace($defaultModel)) {
  $defaultModel = "gpt-oss-swallow-120b-iq4xs"
}

$appPort = Get-EnvValue -Key "APP_PORT" -FilePath $userEnvFile
if ([string]::IsNullOrWhiteSpace($appPort)) { $appPort = "3030" }
[int]$parsedAppPort = 0
[void][int]::TryParse($appPort, [ref]$parsedAppPort)
if ($parsedAppPort -le 0) { $appPort = "3030" }

$appBind = Get-EnvValue -Key "APP_BIND" -FilePath $userEnvFile
if ([string]::IsNullOrWhiteSpace($appBind)) { $appBind = "127.0.0.1" }

$timeoutMs = Get-EnvValue -Key "RUNPOD_REQUEST_TIMEOUT_MS" -FilePath $userEnvFile
if ([string]::IsNullOrWhiteSpace($timeoutMs)) { $timeoutMs = "90000" }

$envVars = @{
  "RUNPOD_BASE_URL"         = $baseUrl
  "RUNPOD_API_KEY"          = $runPodApiKey
  "DEFAULT_MODEL"           = $defaultModel
  "APP_PORT"                = $appPort
  "APP_BIND"                = $appBind
  "RUNPOD_REQUEST_TIMEOUT_MS" = $timeoutMs
}

$saved = @{}
foreach ($k in $envVars.Keys) {
  $saved[$k] = [Environment]::GetEnvironmentVariable($k, "Process")
  [Environment]::SetEnvironmentVariable($k, $envVars[$k], "Process")
}

try {
  $proc = Start-Process -FilePath $nodeExe `
    -ArgumentList @($serverScript) `
    -PassThru `
    -WindowStyle Hidden `
    -WorkingDirectory $BaseDir `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog
}
finally {
  foreach ($k in $saved.Keys) {
    [Environment]::SetEnvironmentVariable($k, $saved[$k], "Process")
  }
}

$proc.Id | Set-Content -Path $pidFile -Encoding ASCII

$url = "http://localhost:$appPort/"
if (-not $NoHealthCheck) {
  $ready = $false
  for ($i = 1; $i -le 30; $i++) {
    try {
      $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$appPort/health" -Method GET -TimeoutSec 3 -UseBasicParsing
      if ($resp.StatusCode -eq 200) {
        $ready = $true
        break
      }
    } catch {
      Start-Sleep -Seconds 1
      continue
    }
    Start-Sleep -Seconds 1
  }
  if (-not $ready) {
    Write-Warning "Client launched but health check timed out."
    Write-Host "Out log: $outLog"
    Write-Host "Err log: $errLog"
  }
}

if (-not $NoOpenBrowser) {
  Start-Process $url | Out-Null
}

Write-Host "RunPod HTMX client started."
Write-Host "PID: $($proc.Id)"
Write-Host "Node: $nodeExe"
Write-Host "Env file: $userEnvFile"
Write-Host "Secure key store: $apiKeyStoreFile"
Write-Host "Endpoint: $(Mask-Url -Url $baseUrl)"
Write-Host "URL: $url"
Write-Host "Out log: $outLog"
Write-Host "Err log: $errLog"
