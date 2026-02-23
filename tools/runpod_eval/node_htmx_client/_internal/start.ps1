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

function Get-ConfigValue {
  param(
    [Parameter(Mandatory = $true)] [string]$Key,
    [Parameter(Mandatory = $true)] [string[]]$FilePaths
  )
  foreach ($file in $FilePaths) {
    if ([string]::IsNullOrWhiteSpace($file)) { continue }
    $value = Get-EnvValue -Key $Key -FilePath $file
    if (-not [string]::IsNullOrWhiteSpace($value)) {
      return $value
    }
  }
  return $null
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
$apiKeyStoreFile = Join-Path $userDir "runpod_api_key.dpapi"
$pidFile = Join-Path $userDir "runpod-htmx-$userSlug.pid"
$logDir = Join-Path $userDir "logs"
$outLog = Join-Path $logDir "runpod-htmx-$userSlug.out.log"
$errLog = Join-Path $logDir "runpod-htmx-$userSlug.err.log"
$configEnvFile = Join-Path $PSScriptRoot ".env.example"
$localEnvFile = Join-Path $PSScriptRoot ".env.local"
$localEnvTemplateFile = Join-Path $PSScriptRoot ".env.local.example"
$sharedObfFile = Join-Path $PSScriptRoot "runpod_api_key.obf"

New-Item -ItemType Directory -Force -Path $userDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (!(Test-Path $configEnvFile)) {
  Write-Host "Config env file not found:"
  Write-Host "  $configEnvFile"
  exit 1
}

$configFiles = @($localEnvFile, $configEnvFile)

$baseUrl = Get-ConfigValue -Key "RUNPOD_BASE_URL" -FilePaths $configFiles
if (Test-PlaceholderValue -Value $baseUrl) {
  if (!(Test-Path $localEnvFile)) {
    if (Test-Path $localEnvTemplateFile) {
      Copy-Item -Path $localEnvTemplateFile -Destination $localEnvFile -Force
    } else {
      Set-Content -Path $localEnvFile -Value @(
        "RUNPOD_BASE_URL=https://<pod-id>-11434.proxy.runpod.net/v1"
        "RUNPOD_API_KEY=__USE_DPAPI__"
      ) -Encoding UTF8
    }
  }
  Write-Host "Please update these values in:"
  Write-Host "  $localEnvFile"
  Write-Host ""
  Write-Host "Required:"
  Write-Host "  RUNPOD_BASE_URL=https://<pod-id>-11434.proxy.runpod.net/v1"
  Write-Host "  RUNPOD_API_KEY=__USE_DPAPI__   (keep this marker)"
  Write-Host ""
  Start-Process notepad.exe $localEnvFile | Out-Null
  exit 1
}

$keyInEnv = Get-ConfigValue -Key "RUNPOD_API_KEY" -FilePaths $configFiles
if (-not (Test-PlaceholderValue -Value $keyInEnv)) {
  Save-RunPodApiKey -ApiKey $keyInEnv -FilePath $apiKeyStoreFile
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
  & (Join-Path $PSScriptRoot "test-runpod-connection.ps1") -EnvFile $localEnvFile -FallbackEnvFile $configEnvFile -ApiKey $runPodApiKey
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
      $existingPort = Get-ConfigValue -Key "APP_PORT" -FilePaths $configFiles
      if ($PSBoundParameters.ContainsKey("Port") -and $Port -gt 0) {
        $existingPort = "$Port"
      }
      if ([string]::IsNullOrWhiteSpace($existingPort)) { $existingPort = "3030" }
      Write-Host "RunPod HTMX client already running (PID=$existingPid)."
      if (-not $NoOpenBrowser) { Start-Process "http://localhost:$existingPort/" | Out-Null }
      exit 0
    }
  }
  Remove-Item -Force $pidFile -ErrorAction SilentlyContinue
}

$defaultModel = Get-ConfigValue -Key "DEFAULT_MODEL" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($defaultModel)) {
  $defaultModel = "gpt-oss-swallow-120b-iq4xs"
}

$appPort = Get-ConfigValue -Key "APP_PORT" -FilePaths $configFiles
if ($PSBoundParameters.ContainsKey("Port") -and $Port -gt 0) { $appPort = "$Port" }
if ([string]::IsNullOrWhiteSpace($appPort)) { $appPort = "3030" }
[int]$parsedAppPort = 0
[void][int]::TryParse($appPort, [ref]$parsedAppPort)
if ($parsedAppPort -le 0) { $appPort = "3030" }

$appBind = Get-ConfigValue -Key "APP_BIND" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($appBind)) { $appBind = "127.0.0.1" }

$timeoutMs = Get-ConfigValue -Key "RUNPOD_REQUEST_TIMEOUT_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($timeoutMs)) { $timeoutMs = "90000" }

$workspaceRoot = Get-ConfigValue -Key "WORKSPACE_ROOT" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($workspaceRoot)) {
  $fallbackWorkspace = Join-Path $BaseDir "..\..\.."
  if (Test-Path $fallbackWorkspace) {
    $workspaceRoot = (Resolve-Path $fallbackWorkspace).Path
  }
  else {
    $workspaceRoot = $BaseDir
  }
}
elseif (!(Split-Path -Path $workspaceRoot -IsAbsolute)) {
  $workspaceRoot = Join-Path $BaseDir $workspaceRoot
}

$localShellTimeout = Get-ConfigValue -Key "LOCAL_SHELL_TIMEOUT_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($localShellTimeout)) { $localShellTimeout = "20000" }

$localShellAllowlist = Get-ConfigValue -Key "LOCAL_SHELL_ALLOWLIST" -FilePaths $configFiles

$autoLoopMaxIters = Get-ConfigValue -Key "AUTONOMOUS_LOOP_MAX_ITERS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($autoLoopMaxIters)) { $autoLoopMaxIters = "3" }

$autoMaxFiles = Get-ConfigValue -Key "AUTONOMOUS_MAX_FILES_PER_ITER" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($autoMaxFiles)) { $autoMaxFiles = "4" }

$autoMaxContextChars = Get-ConfigValue -Key "AUTONOMOUS_MAX_FILE_CONTEXT_CHARS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($autoMaxContextChars)) { $autoMaxContextChars = "12000" }

$autoMaxValidationCommands = Get-ConfigValue -Key "AUTONOMOUS_MAX_VALIDATION_COMMANDS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($autoMaxValidationCommands)) { $autoMaxValidationCommands = "4" }

$autoModelMaxTokens = Get-ConfigValue -Key "AUTONOMOUS_MODEL_MAX_TOKENS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($autoModelMaxTokens)) { $autoModelMaxTokens = "4000" }

$envVars = @{
  "RUNPOD_BASE_URL"         = $baseUrl
  "RUNPOD_API_KEY"          = $runPodApiKey
  "DEFAULT_MODEL"           = $defaultModel
  "APP_PORT"                = $appPort
  "APP_BIND"                = $appBind
  "RUNPOD_REQUEST_TIMEOUT_MS" = $timeoutMs
  "WORKSPACE_ROOT"          = $workspaceRoot
  "LOCAL_SHELL_TIMEOUT_MS"  = $localShellTimeout
  "LOCAL_SHELL_ALLOWLIST"   = $localShellAllowlist
  "AUTONOMOUS_LOOP_MAX_ITERS" = $autoLoopMaxIters
  "AUTONOMOUS_MAX_FILES_PER_ITER" = $autoMaxFiles
  "AUTONOMOUS_MAX_FILE_CONTEXT_CHARS" = $autoMaxContextChars
  "AUTONOMOUS_MAX_VALIDATION_COMMANDS" = $autoMaxValidationCommands
  "AUTONOMOUS_MODEL_MAX_TOKENS" = $autoModelMaxTokens
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
Write-Host "Config files:"
Write-Host "  local: $localEnvFile"
Write-Host "  shared: $configEnvFile"
Write-Host "Secure key store: $apiKeyStoreFile"
Write-Host "Workspace root: $workspaceRoot"
Write-Host "Endpoint: $(Mask-Url -Url $baseUrl)"
Write-Host "URL: $url"
Write-Host "Out log: $outLog"
Write-Host "Err log: $errLog"
