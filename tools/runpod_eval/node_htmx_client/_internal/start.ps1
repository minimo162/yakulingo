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

function Resolve-BundledCodexExe {
  param([Parameter(Mandatory = $true)][string]$BaseDir)
  $runtimeRoot = Join-Path $BaseDir ".runtime"
  $binHint = Join-Path $runtimeRoot "codex-bin.txt"
  if (Test-Path $binHint) {
    $hintPath = (Get-Content -Raw $binHint).Trim()
    if (-not [string]::IsNullOrWhiteSpace($hintPath) -and (Test-Path $hintPath)) {
      try { return (Resolve-Path $hintPath).Path } catch { return $hintPath }
    }
  }

  $candidates = @(
    (Join-Path $runtimeRoot "codex\node_modules\.bin\codex.cmd"),
    (Join-Path $runtimeRoot "codex\node_modules\.bin\codex.ps1"),
    (Join-Path $runtimeRoot "codex\node_modules\.bin\codex")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      try { return (Resolve-Path $candidate).Path } catch { return $candidate }
    }
  }
  return $null
}

function Resolve-UvExe {
  param([Parameter(Mandatory = $true)][string]$BaseDir)
  $runtimeUv = Join-Path $BaseDir ".runtime\uv\uv.exe"
  if (Test-Path $runtimeUv) {
    return $runtimeUv
  }
  return $null
}

function Resolve-PythonExe {
  param([Parameter(Mandatory = $true)][string]$BaseDir)
  $runtimeRoot = Join-Path $BaseDir ".runtime"
  $binFile = Join-Path $runtimeRoot "python-bin.txt"
  $stampFile = Join-Path $runtimeRoot "python-runtime.stamp"
  if (Test-Path $binFile) {
    $candidate = (Get-Content -Raw $binFile).Trim()
    if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
      try {
        return (Resolve-Path $candidate).Path
      } catch {
        return $candidate
      }
    }
  }

  if (-not (Test-Path $stampFile)) {
    return $null
  }

  $venvPython = Join-Path $runtimeRoot "python-venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    return $venvPython
  }

  $managedRoot = Join-Path $runtimeRoot "python-managed"
  if (Test-Path $managedRoot) {
    $candidates = Get-ChildItem -Path $managedRoot -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue |
      Sort-Object LastWriteTime -Descending
    if ($candidates -and $candidates.Count -gt 0) {
      return $candidates[0].FullName
    }
  }
  return $null
}

function Normalize-PathForMatch {
  param([string]$Value)
  if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
  return ($Value.ToLower() -replace "\\", "/")
}

function Test-IsLocaLingoServerCommandLine {
  param(
    [string]$CommandLine,
    [string]$ServerScriptPath
  )
  if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
  $normalizedCmd = Normalize-PathForMatch -Value $CommandLine
  $normalizedServer = Normalize-PathForMatch -Value $ServerScriptPath
  if ([string]::IsNullOrWhiteSpace($normalizedServer)) { return $false }
  return $normalizedCmd.Contains($normalizedServer)
}

function Get-LocaLingoServerProcessIds {
  param([string]$ServerScriptPath)
  $rows = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match "^node(\.exe)?$" -and (Test-IsLocaLingoServerCommandLine -CommandLine $_.CommandLine -ServerScriptPath $ServerScriptPath)
  }
  return @($rows | ForEach-Object { [int]$_.ProcessId } | Sort-Object -Unique)
}

function Test-IsLocaLingoServerProcessId {
  param(
    [int]$ProcessId,
    [string]$ServerScriptPath
  )
  if ($ProcessId -le 0) { return $false }
  $rows = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
  if (-not $rows) { return $false }
  $cmd = $rows | Select-Object -ExpandProperty CommandLine -First 1
  return Test-IsLocaLingoServerCommandLine -CommandLine $cmd -ServerScriptPath $ServerScriptPath
}

function Test-IsLocaLingoFastApiCommandLine {
  param(
    [string]$CommandLine,
    [string]$Marker
  )
  if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
  if ([string]::IsNullOrWhiteSpace($Marker)) { return $false }
  $normalizedCmd = Normalize-PathForMatch -Value $CommandLine
  $normalizedMarker = Normalize-PathForMatch -Value $Marker
  return $normalizedCmd.Contains($normalizedMarker)
}

function Get-LocaLingoFastApiProcessIds {
  param([string]$Marker)
  $rows = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match "^python(\.exe)?$" -and (Test-IsLocaLingoFastApiCommandLine -CommandLine $_.CommandLine -Marker $Marker)
  }
  return @($rows | ForEach-Object { [int]$_.ProcessId } | Sort-Object -Unique)
}

function Test-IsLocaLingoFastApiProcessId {
  param(
    [int]$ProcessId,
    [string]$Marker
  )
  if ($ProcessId -le 0) { return $false }
  $rows = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
  if (-not $rows) { return $false }
  $cmd = $rows | Select-Object -ExpandProperty CommandLine -First 1
  return Test-IsLocaLingoFastApiCommandLine -CommandLine $cmd -Marker $Marker
}

function Stop-ProcessByIdSafe {
  param([int]$ProcessId)
  if ($ProcessId -le 0) { return $false }
  if ($ProcessId -eq $PID) {
    Write-Warning "Skip stopping current PowerShell process PID=$ProcessId"
    return $false
  }
  $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if (-not $proc) { return $false }

  $stopSucceeded = $false
  try {
    # taskkill is generally more robust for hidden/child process trees on Windows.
    & cmd /c "taskkill /PID $ProcessId /T /F" | Out-Null
    $stopSucceeded = $true
  } catch {
    try {
      Stop-Process -Id $ProcessId -Force -ErrorAction Stop
      $stopSucceeded = $true
    } catch {
      Write-Warning "Failed to stop PID=$ProcessId : $($_.Exception.Message)"
      $stopSucceeded = $false
    }
  }

  for ($i = 0; $i -lt 15; $i++) {
    if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
      return $stopSucceeded
    }
    Start-Sleep -Milliseconds 200
  }

  if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
    Write-Warning "PID=$ProcessId is still alive after forced stop attempts."
    return $false
  }
  return $stopSucceeded
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

$connectionTestMode = Get-ConfigValue -Key "RUNPOD_CONNECTION_TEST_MODE" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($connectionTestMode)) {
  $connectionTestMode = "strict"
}
$connectionTestModeNormalized = $connectionTestMode.Trim().ToLowerInvariant()
if ($connectionTestModeNormalized -ne "strict") {
  $connectionTestModeNormalized = "soft"
}

if (-not $SkipConnectionTest) {
  $connectionArgs = @{
    EnvFile         = $localEnvFile
    FallbackEnvFile = $configEnvFile
    ApiKey          = $runPodApiKey
  }
  if ($connectionTestModeNormalized -ne "strict") {
    $connectionArgs["SoftFail"] = $true
  }
  & (Join-Path $PSScriptRoot "test-runpod-connection.ps1") @connectionArgs
}

$codexBundledPackage = Get-ConfigValue -Key "CODEX_BUNDLED_PACKAGE" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexBundledPackage)) { $codexBundledPackage = "@openai/codex@latest" }

$codexRequireBundled = Get-ConfigValue -Key "CODEX_REQUIRE_BUNDLED" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexRequireBundled)) { $codexRequireBundled = "1" }

$nodeExe = Resolve-NodeExe -BaseDir $BaseDir
$bundledCodexExe = Resolve-BundledCodexExe -BaseDir $BaseDir
if ([string]::IsNullOrWhiteSpace($nodeExe) -or [string]::IsNullOrWhiteSpace($bundledCodexExe)) {
  $prepareScript = Join-Path $PSScriptRoot "prepare-node-runtime.ps1"
  if (!(Test-Path $prepareScript)) {
    Write-Host "Bundled runtime (Node/Codex) is missing and prepare script is not found:"
    Write-Host "  $prepareScript"
    exit 1
  }

  if ([string]::IsNullOrWhiteSpace($nodeExe)) {
    Write-Host "Bundled Node.js runtime not found. Preparing now..."
  } else {
    Write-Host "Bundled Codex CLI not found. Preparing now..."
  }
  & $prepareScript -CodexPackage $codexBundledPackage
  $nodeExe = Resolve-NodeExe -BaseDir $BaseDir
  $bundledCodexExe = Resolve-BundledCodexExe -BaseDir $BaseDir
  if ([string]::IsNullOrWhiteSpace($nodeExe) -or [string]::IsNullOrWhiteSpace($bundledCodexExe)) {
    Write-Host "Failed to prepare bundled Node.js/Codex runtime."
    exit 1
  }
}

$serverScript = Join-Path $PSScriptRoot "server.mjs"
if (!(Test-Path $serverScript)) {
  Write-Host "Server script not found: $serverScript"
  exit 1
}
$fastApiAppDir = Join-Path $PSScriptRoot "fastapi_app"
if (!(Test-Path $fastApiAppDir)) {
  Write-Host "FastAPI app directory not found: $fastApiAppDir"
  exit 1
}
$fastApiAppMarker = "fastapi_app.main:app"

if (Test-Path $pidFile) {
  $existingPidRaw = (Get-Content -Raw $pidFile).Trim()
  [int]$existingPid = 0
  [void][int]::TryParse($existingPidRaw, [ref]$existingPid)
  if ($existingPid -gt 0) {
    # PID file will be validated against actual command-line match below.
  }
}

$pythonRuntimeSpec = Get-ConfigValue -Key "PYTHON_RUNTIME_SPEC" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($pythonRuntimeSpec)) { $pythonRuntimeSpec = "3.11" }

$pythonRuntimeUvTarget = Get-ConfigValue -Key "PYTHON_RUNTIME_UV_TARGET" -FilePaths $configFiles

$uvExe = Resolve-UvExe -BaseDir $BaseDir
$pythonExe = Resolve-PythonExe -BaseDir $BaseDir
if ([string]::IsNullOrWhiteSpace($uvExe) -or [string]::IsNullOrWhiteSpace($pythonExe)) {
  $preparePyScript = Join-Path $PSScriptRoot "prepare-python-runtime.ps1"
  if (!(Test-Path $preparePyScript)) {
    Write-Host "Bundled Python runtime is missing and prepare script is not found:"
    Write-Host "  $preparePyScript"
    exit 1
  }

  Write-Host "Bundled Python runtime not found. Preparing now..."
  $prepareArgs = @{}
  $prepareArgs["PythonSpec"] = $pythonRuntimeSpec
  if (-not [string]::IsNullOrWhiteSpace($pythonRuntimeUvTarget)) {
    $prepareArgs["UvTarget"] = $pythonRuntimeUvTarget
  }
  & $preparePyScript @prepareArgs

  $uvExe = Resolve-UvExe -BaseDir $BaseDir
  $pythonExe = Resolve-PythonExe -BaseDir $BaseDir
  if ([string]::IsNullOrWhiteSpace($uvExe) -or [string]::IsNullOrWhiteSpace($pythonExe)) {
    Write-Host "Failed to prepare bundled Python runtime."
    exit 1
  }
}

$restartTargets = @()
if (Test-Path $pidFile) {
  $existingPidRaw = (Get-Content -Raw $pidFile).Trim()
  [int]$pidFromFile = 0
  [void][int]::TryParse($existingPidRaw, [ref]$pidFromFile)
  if (
    $pidFromFile -gt 0 -and (
      (Test-IsLocaLingoServerProcessId -ProcessId $pidFromFile -ServerScriptPath $serverScript) -or
      (Test-IsLocaLingoFastApiProcessId -ProcessId $pidFromFile -Marker $fastApiAppMarker)
    )
  ) {
    $restartTargets += $pidFromFile
  }
}
$restartTargets += Get-LocaLingoServerProcessIds -ServerScriptPath $serverScript
$restartTargets += Get-LocaLingoFastApiProcessIds -Marker $fastApiAppMarker
$restartTargets = @($restartTargets | Where-Object { $_ -gt 0 -and $_ -ne $PID } | Sort-Object -Unique)

if ($restartTargets.Count -gt 0) {
  Write-Host "Restarting LocaLingo. Stopping previous process(es): $($restartTargets -join ', ')"
  foreach ($procId in $restartTargets) {
    Write-Host "Stopping PID=$procId ..."
    [void](Stop-ProcessByIdSafe -ProcessId $procId)
  }
  for ($i = 0; $i -lt 20; $i++) {
    $alive = @($restartTargets | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    if ($alive.Count -eq 0) { break }
    Start-Sleep -Milliseconds 200
  }
}

Remove-Item -Force $pidFile -ErrorAction SilentlyContinue

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
$engineBind = Get-ConfigValue -Key "ENGINE_BIND" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($engineBind)) { $engineBind = "127.0.0.1" }
$enginePort = Get-ConfigValue -Key "ENGINE_PORT" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($enginePort)) { $enginePort = "3031" }
[int]$parsedEnginePort = 0
[void][int]::TryParse($enginePort, [ref]$parsedEnginePort)
if ($parsedEnginePort -le 0) { $enginePort = "3031" }
if ($enginePort -eq $appPort) {
  try {
    $enginePort = ([int]$appPort + 1).ToString()
  } catch {
    $enginePort = "3031"
  }
}

$appTimeZone = Get-ConfigValue -Key "APP_TIME_ZONE" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($appTimeZone)) { $appTimeZone = "Asia/Tokyo" }

$timeoutMs = Get-ConfigValue -Key "RUNPOD_REQUEST_TIMEOUT_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($timeoutMs)) { $timeoutMs = "120000" }

$runPodRetryMaxAttempts = Get-ConfigValue -Key "RUNPOD_HTTP_RETRY_MAX_ATTEMPTS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodRetryMaxAttempts)) { $runPodRetryMaxAttempts = "5" }

$runPodRetryDelayMs = Get-ConfigValue -Key "RUNPOD_HTTP_RETRY_DELAY_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodRetryDelayMs)) { $runPodRetryDelayMs = "1200" }

$runPodRetryMaxDelayMs = Get-ConfigValue -Key "RUNPOD_HTTP_RETRY_MAX_DELAY_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodRetryMaxDelayMs)) { $runPodRetryMaxDelayMs = "10000" }

$runPodModelsTimeoutMs = Get-ConfigValue -Key "RUNPOD_MODELS_TIMEOUT_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodModelsTimeoutMs)) { $runPodModelsTimeoutMs = "30000" }

$runPodChatTimeoutMs = Get-ConfigValue -Key "RUNPOD_CHAT_TIMEOUT_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodChatTimeoutMs)) { $runPodChatTimeoutMs = "120000" }

$runPodHealthcheckOnChat = Get-ConfigValue -Key "RUNPOD_HEALTHCHECK_ON_CHAT" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodHealthcheckOnChat)) { $runPodHealthcheckOnChat = "1" }

$runPodHealthcheckTtlMs = Get-ConfigValue -Key "RUNPOD_HEALTHCHECK_TTL_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodHealthcheckTtlMs)) { $runPodHealthcheckTtlMs = "20000" }

$workspaceRoot = Join-Path $BaseDir "workspace"
if (!(Test-Path $workspaceRoot)) {
  New-Item -ItemType Directory -Path $workspaceRoot -Force | Out-Null
}
$workspaceRoot = (Resolve-Path $workspaceRoot).Path
$workspaceStateFile = Join-Path $userDir "workspace-state.json"

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

$playwrightMcpEnabled = Get-ConfigValue -Key "PLAYWRIGHT_MCP_ENABLED" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($playwrightMcpEnabled)) { $playwrightMcpEnabled = "1" }

$playwrightMcpBrowser = Get-ConfigValue -Key "PLAYWRIGHT_MCP_BROWSER" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($playwrightMcpBrowser)) { $playwrightMcpBrowser = "chromium" }

$playwrightMcpHeadless = Get-ConfigValue -Key "PLAYWRIGHT_MCP_HEADLESS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($playwrightMcpHeadless)) { $playwrightMcpHeadless = "1" }

$playwrightMcpTimeoutMs = Get-ConfigValue -Key "PLAYWRIGHT_MCP_TIMEOUT_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($playwrightMcpTimeoutMs)) { $playwrightMcpTimeoutMs = "300000" }

$playwrightMcpMaxResults = Get-ConfigValue -Key "PLAYWRIGHT_MCP_MAX_RESULTS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($playwrightMcpMaxResults)) { $playwrightMcpMaxResults = "5" }

$clientAutostopEnabled = Get-ConfigValue -Key "CLIENT_AUTOSTOP_ENABLED" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($clientAutostopEnabled)) { $clientAutostopEnabled = "1" }

$clientHeartbeatIntervalMs = Get-ConfigValue -Key "CLIENT_HEARTBEAT_INTERVAL_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($clientHeartbeatIntervalMs)) { $clientHeartbeatIntervalMs = "15000" }

$clientHeartbeatStaleMs = Get-ConfigValue -Key "CLIENT_HEARTBEAT_STALE_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($clientHeartbeatStaleMs)) { $clientHeartbeatStaleMs = "45000" }

$clientAutostopIdleMs = Get-ConfigValue -Key "CLIENT_AUTOSTOP_IDLE_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($clientAutostopIdleMs)) { $clientAutostopIdleMs = "30000" }

$clientHeartbeatSweepMs = Get-ConfigValue -Key "CLIENT_HEARTBEAT_SWEEP_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($clientHeartbeatSweepMs)) { $clientHeartbeatSweepMs = "5000" }

$clientAutostopRequestGraceMs = Get-ConfigValue -Key "CLIENT_AUTOSTOP_REQUEST_GRACE_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($clientAutostopRequestGraceMs)) { $clientAutostopRequestGraceMs = "30000" }

$streamKeepaliveIntervalMs = Get-ConfigValue -Key "STREAM_KEEPALIVE_INTERVAL_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($streamKeepaliveIntervalMs)) { $streamKeepaliveIntervalMs = "10000" }

$assistantStreamEnabled = Get-ConfigValue -Key "ASSISTANT_STREAM_ENABLED" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($assistantStreamEnabled)) { $assistantStreamEnabled = "1" }

$assistantStreamChunkChars = Get-ConfigValue -Key "ASSISTANT_STREAM_CHUNK_CHARS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($assistantStreamChunkChars)) { $assistantStreamChunkChars = "48" }

$assistantStreamChunkDelayMs = Get-ConfigValue -Key "ASSISTANT_STREAM_CHUNK_DELAY_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($assistantStreamChunkDelayMs)) { $assistantStreamChunkDelayMs = "12" }

$generationTemperature = Get-ConfigValue -Key "GENERATION_TEMPERATURE" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($generationTemperature)) { $generationTemperature = "0.6" }

$generationTopP = Get-ConfigValue -Key "GENERATION_TOP_P" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($generationTopP)) { $generationTopP = "0.95" }

$generationTopK = Get-ConfigValue -Key "GENERATION_TOP_K" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($generationTopK)) { $generationTopK = "20" }

$generationMinP = Get-ConfigValue -Key "GENERATION_MIN_P" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($generationMinP)) { $generationMinP = "0" }

$generationMaxContextTokens = Get-ConfigValue -Key "GENERATION_MAX_CONTEXT_TOKENS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($generationMaxContextTokens)) { $generationMaxContextTokens = "32768" }

$generationContextReserveTokens = Get-ConfigValue -Key "GENERATION_CONTEXT_RESERVE_TOKENS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($generationContextReserveTokens)) { $generationContextReserveTokens = "512" }

$autoToolTemperature = Get-ConfigValue -Key "AUTO_TOOL_TEMPERATURE" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($autoToolTemperature)) { $autoToolTemperature = $generationTemperature }

$agentBackend = Get-ConfigValue -Key "AGENT_BACKEND" -FilePaths $configFiles
$agentBackendNormalized = "codex_cli"
if (-not [string]::IsNullOrWhiteSpace($agentBackend)) {
  $requestedBackend = $agentBackend.Trim().ToLowerInvariant()
  if ($requestedBackend -ne "codex_cli") {
    Write-Host "AGENT_BACKEND=$requestedBackend is ignored. Forcing codex_cli."
  }
}

$configuredCodexBin = Get-ConfigValue -Key "CODEX_BIN" -FilePaths $configFiles
$codexBin = $bundledCodexExe
if (-not [string]::IsNullOrWhiteSpace($configuredCodexBin)) {
  $normalizedConfigured = (Normalize-PathForMatch -Value $configuredCodexBin)
  $normalizedBundled = (Normalize-PathForMatch -Value $bundledCodexExe)
  if ($normalizedConfigured -ne $normalizedBundled) {
    Write-Host "CODEX_BIN in env is ignored. Using bundled codex:"
    Write-Host "  $bundledCodexExe"
  }
}
$codexHome = Get-ConfigValue -Key "CODEX_HOME" -FilePaths $configFiles
$codexExecTimeoutSec = Get-ConfigValue -Key "CODEX_EXEC_TIMEOUT_SEC" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexExecTimeoutSec)) { $codexExecTimeoutSec = "900" }

$codexNativeMode = Get-ConfigValue -Key "CODEX_NATIVE_MODE" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexNativeMode)) { $codexNativeMode = "1" }

$codexFullAuto = Get-ConfigValue -Key "CODEX_FULL_AUTO" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexFullAuto)) { $codexFullAuto = "1" }

$codexSkipGitRepoCheck = Get-ConfigValue -Key "CODEX_SKIP_GIT_REPO_CHECK" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexSkipGitRepoCheck)) { $codexSkipGitRepoCheck = "1" }

$codexDangerousBypass = Get-ConfigValue -Key "CODEX_DANGEROUS_BYPASS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexDangerousBypass)) { $codexDangerousBypass = "0" }

$codexExtraArgs = Get-ConfigValue -Key "CODEX_EXTRA_ARGS" -FilePaths $configFiles

$codexProviderRequestMaxRetries = Get-ConfigValue -Key "CODEX_PROVIDER_REQUEST_MAX_RETRIES" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexProviderRequestMaxRetries)) { $codexProviderRequestMaxRetries = "1" }

$codexProviderStreamMaxRetries = Get-ConfigValue -Key "CODEX_PROVIDER_STREAM_MAX_RETRIES" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexProviderStreamMaxRetries)) { $codexProviderStreamMaxRetries = "1" }

$codexProviderStreamIdleTimeoutMs = Get-ConfigValue -Key "CODEX_PROVIDER_STREAM_IDLE_TIMEOUT_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexProviderStreamIdleTimeoutMs)) { $codexProviderStreamIdleTimeoutMs = "45000" }

$codexModelContextWindow = Get-ConfigValue -Key "CODEX_MODEL_CONTEXT_WINDOW" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexModelContextWindow)) { $codexModelContextWindow = "32768" }

$codexMinimalModelInstructions = Get-ConfigValue -Key "CODEX_MINIMAL_MODEL_INSTRUCTIONS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexMinimalModelInstructions)) { $codexMinimalModelInstructions = "0" }

$codexMinimalModelInstructionsFile = Get-ConfigValue -Key "CODEX_MINIMAL_MODEL_INSTRUCTIONS_FILE" -FilePaths $configFiles

$codexModelReasoningEffort = Get-ConfigValue -Key "CODEX_MODEL_REASONING_EFFORT" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexModelReasoningEffort)) { $codexModelReasoningEffort = "minimal" }

$codexModelReasoningSummary = Get-ConfigValue -Key "CODEX_MODEL_REASONING_SUMMARY" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexModelReasoningSummary)) { $codexModelReasoningSummary = "auto" }

$codexModelVerbosity = Get-ConfigValue -Key "CODEX_MODEL_VERBOSITY" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexModelVerbosity)) { $codexModelVerbosity = "low" }

$codexExecModel = Get-ConfigValue -Key "CODEX_EXEC_MODEL" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexExecModel)) { $codexExecModel = $defaultModel }

$codexLmstudioProviderId = Get-ConfigValue -Key "CODEX_LMSTUDIO_PROVIDER_ID" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexLmstudioProviderId)) { $codexLmstudioProviderId = "lmstudio-runpod" }

$codexProjectDocMaxBytes = Get-ConfigValue -Key "CODEX_PROJECT_DOC_MAX_BYTES" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexProjectDocMaxBytes)) { $codexProjectDocMaxBytes = "0" }

$codexPromptMaxChars = Get-ConfigValue -Key "CODEX_PROMPT_MAX_CHARS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexPromptMaxChars)) { $codexPromptMaxChars = "12000" }

$codexPromptCompressionEnabled = Get-ConfigValue -Key "CODEX_PROMPT_COMPRESSION_ENABLED" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexPromptCompressionEnabled)) { $codexPromptCompressionEnabled = "1" }

$codexPromptCompressionTriggerChars = Get-ConfigValue -Key "CODEX_PROMPT_COMPRESSION_TRIGGER_CHARS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexPromptCompressionTriggerChars)) { $codexPromptCompressionTriggerChars = "9000" }

$codexPromptCompressionTargetChars = Get-ConfigValue -Key "CODEX_PROMPT_COMPRESSION_TARGET_CHARS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexPromptCompressionTargetChars)) { $codexPromptCompressionTargetChars = "7600" }

$codexPromptKeepHeadChars = Get-ConfigValue -Key "CODEX_PROMPT_KEEP_HEAD_CHARS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexPromptKeepHeadChars)) { $codexPromptKeepHeadChars = "2400" }

$codexPromptKeepTailChars = Get-ConfigValue -Key "CODEX_PROMPT_KEEP_TAIL_CHARS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexPromptKeepTailChars)) { $codexPromptKeepTailChars = "3200" }

$codexPromptKeyLinesLimit = Get-ConfigValue -Key "CODEX_PROMPT_KEY_LINES_LIMIT" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexPromptKeyLinesLimit)) { $codexPromptKeyLinesLimit = "40" }

$codexExecProgressPingIntervalMs = Get-ConfigValue -Key "CODEX_EXEC_PROGRESS_PING_INTERVAL_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexExecProgressPingIntervalMs)) { $codexExecProgressPingIntervalMs = "8000" }

$codexExecRetryMaxAttempts = Get-ConfigValue -Key "CODEX_EXEC_RETRY_MAX_ATTEMPTS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexExecRetryMaxAttempts)) { $codexExecRetryMaxAttempts = "3" }

$codexExecRetryBaseDelayMs = Get-ConfigValue -Key "CODEX_EXEC_RETRY_BASE_DELAY_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexExecRetryBaseDelayMs)) { $codexExecRetryBaseDelayMs = "800" }

$codexExecRetryMaxDelayMs = Get-ConfigValue -Key "CODEX_EXEC_RETRY_MAX_DELAY_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexExecRetryMaxDelayMs)) { $codexExecRetryMaxDelayMs = "4000" }

$codexStreamRecoveryFallbackEnabled = Get-ConfigValue -Key "CODEX_STREAM_RECOVERY_FALLBACK_ENABLED" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexStreamRecoveryFallbackEnabled)) { $codexStreamRecoveryFallbackEnabled = "1" }

$codexStreamRecoveryTimeoutMs = Get-ConfigValue -Key "CODEX_STREAM_RECOVERY_TIMEOUT_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexStreamRecoveryTimeoutMs)) { $codexStreamRecoveryTimeoutMs = "90000" }

$codexWebSearchMode = Get-ConfigValue -Key "CODEX_WEB_SEARCH_MODE" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexWebSearchMode)) { $codexWebSearchMode = "live" }

$codexToolFallbackToEngine = Get-ConfigValue -Key "CODEX_TOOL_FALLBACK_TO_ENGINE" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexToolFallbackToEngine)) { $codexToolFallbackToEngine = "0" }

$codexToolFallbackForceForLiveWeb = Get-ConfigValue -Key "CODEX_TOOL_FALLBACK_FORCE_FOR_LIVE_WEB" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($codexToolFallbackForceForLiveWeb)) { $codexToolFallbackForceForLiveWeb = "0" }

$runPodBaseUrlCandidates = Get-ConfigValue -Key "RUNPOD_BASE_URL_CANDIDATES" -FilePaths $configFiles
$runPodRouteProbeEnabled = Get-ConfigValue -Key "RUNPOD_ROUTE_PROBE_ENABLED" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodRouteProbeEnabled)) { $runPodRouteProbeEnabled = "1" }

$runPodRouteProbeTimeoutMs = Get-ConfigValue -Key "RUNPOD_ROUTE_PROBE_TIMEOUT_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodRouteProbeTimeoutMs)) { $runPodRouteProbeTimeoutMs = "6000" }

$runPodRouteCooldownSec = Get-ConfigValue -Key "RUNPOD_ROUTE_COOLDOWN_SEC" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodRouteCooldownSec)) { $runPodRouteCooldownSec = "90" }

$runPodResponsesBackgroundEnabled = Get-ConfigValue -Key "RUNPOD_RESPONSES_BACKGROUND_ENABLED" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodResponsesBackgroundEnabled)) { $runPodResponsesBackgroundEnabled = "1" }

$runPodResponsesPollIntervalMs = Get-ConfigValue -Key "RUNPOD_RESPONSES_POLL_INTERVAL_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodResponsesPollIntervalMs)) { $runPodResponsesPollIntervalMs = "1500" }

$runPodResponsesPollTimeoutMs = Get-ConfigValue -Key "RUNPOD_RESPONSES_POLL_TIMEOUT_MS" -FilePaths $configFiles
if ([string]::IsNullOrWhiteSpace($runPodResponsesPollTimeoutMs)) { $runPodResponsesPollTimeoutMs = "90000" }

$envVars = @{
  "RUNPOD_BASE_URL"         = $baseUrl
  "RUNPOD_BASE_URL_CANDIDATES" = $runPodBaseUrlCandidates
  "RUNPOD_ROUTE_PROBE_ENABLED" = $runPodRouteProbeEnabled
  "RUNPOD_ROUTE_PROBE_TIMEOUT_MS" = $runPodRouteProbeTimeoutMs
  "RUNPOD_ROUTE_COOLDOWN_SEC" = $runPodRouteCooldownSec
  "RUNPOD_API_KEY"          = $runPodApiKey
  "DEFAULT_MODEL"           = $defaultModel
  "UV_BIN"                  = $uvExe
  "PYTHON_BIN"              = $pythonExe
  "APP_PORT"                = $appPort
  "APP_BIND"                = $appBind
  "APP_TIME_ZONE"           = $appTimeZone
  "RUNPOD_REQUEST_TIMEOUT_MS" = $timeoutMs
  "RUNPOD_HTTP_RETRY_MAX_ATTEMPTS" = $runPodRetryMaxAttempts
  "RUNPOD_HTTP_RETRY_DELAY_MS" = $runPodRetryDelayMs
  "RUNPOD_HTTP_RETRY_MAX_DELAY_MS" = $runPodRetryMaxDelayMs
  "RUNPOD_MODELS_TIMEOUT_MS" = $runPodModelsTimeoutMs
  "RUNPOD_CHAT_TIMEOUT_MS" = $runPodChatTimeoutMs
  "RUNPOD_HEALTHCHECK_ON_CHAT" = $runPodHealthcheckOnChat
  "RUNPOD_HEALTHCHECK_TTL_MS" = $runPodHealthcheckTtlMs
  "WORKSPACE_ROOT"          = $workspaceRoot
  "WORKSPACE_STATE_FILE"    = $workspaceStateFile
  "LOCAL_SHELL_TIMEOUT_MS"  = $localShellTimeout
  "LOCAL_SHELL_ALLOWLIST"   = $localShellAllowlist
  "AUTONOMOUS_LOOP_MAX_ITERS" = $autoLoopMaxIters
  "AUTONOMOUS_MAX_FILES_PER_ITER" = $autoMaxFiles
  "AUTONOMOUS_MAX_FILE_CONTEXT_CHARS" = $autoMaxContextChars
  "AUTONOMOUS_MAX_VALIDATION_COMMANDS" = $autoMaxValidationCommands
  "AUTONOMOUS_MODEL_MAX_TOKENS" = $autoModelMaxTokens
  "PLAYWRIGHT_MCP_ENABLED" = $playwrightMcpEnabled
  "PLAYWRIGHT_MCP_BROWSER" = $playwrightMcpBrowser
  "PLAYWRIGHT_MCP_HEADLESS" = $playwrightMcpHeadless
  "PLAYWRIGHT_MCP_TIMEOUT_MS" = $playwrightMcpTimeoutMs
  "PLAYWRIGHT_MCP_MAX_RESULTS" = $playwrightMcpMaxResults
  "CLIENT_AUTOSTOP_ENABLED" = $clientAutostopEnabled
  "CLIENT_HEARTBEAT_INTERVAL_MS" = $clientHeartbeatIntervalMs
  "CLIENT_HEARTBEAT_STALE_MS" = $clientHeartbeatStaleMs
  "CLIENT_AUTOSTOP_IDLE_MS" = $clientAutostopIdleMs
  "CLIENT_HEARTBEAT_SWEEP_MS" = $clientHeartbeatSweepMs
  "CLIENT_AUTOSTOP_REQUEST_GRACE_MS" = $clientAutostopRequestGraceMs
  "STREAM_KEEPALIVE_INTERVAL_MS" = $streamKeepaliveIntervalMs
  "ASSISTANT_STREAM_ENABLED" = $assistantStreamEnabled
  "ASSISTANT_STREAM_CHUNK_CHARS" = $assistantStreamChunkChars
  "ASSISTANT_STREAM_CHUNK_DELAY_MS" = $assistantStreamChunkDelayMs
  "GENERATION_TEMPERATURE" = $generationTemperature
  "GENERATION_TOP_P" = $generationTopP
  "GENERATION_TOP_K" = $generationTopK
  "GENERATION_MIN_P" = $generationMinP
  "GENERATION_MAX_CONTEXT_TOKENS" = $generationMaxContextTokens
  "GENERATION_CONTEXT_RESERVE_TOKENS" = $generationContextReserveTokens
  "AUTO_TOOL_TEMPERATURE" = $autoToolTemperature
  "AGENT_BACKEND" = $agentBackendNormalized
  "CODEX_BIN" = $codexBin
  "BUNDLED_CODEX_BIN" = $bundledCodexExe
  "CODEX_REQUIRE_BUNDLED" = $codexRequireBundled
  "CODEX_BUNDLED_PACKAGE" = $codexBundledPackage
  "CODEX_HOME" = $codexHome
  "CODEX_EXEC_TIMEOUT_SEC" = $codexExecTimeoutSec
  "CODEX_NATIVE_MODE" = $codexNativeMode
  "CODEX_FULL_AUTO" = $codexFullAuto
  "CODEX_SKIP_GIT_REPO_CHECK" = $codexSkipGitRepoCheck
  "CODEX_DANGEROUS_BYPASS" = $codexDangerousBypass
  "CODEX_EXTRA_ARGS" = $codexExtraArgs
  "CODEX_PROVIDER_REQUEST_MAX_RETRIES" = $codexProviderRequestMaxRetries
  "CODEX_PROVIDER_STREAM_MAX_RETRIES" = $codexProviderStreamMaxRetries
  "CODEX_PROVIDER_STREAM_IDLE_TIMEOUT_MS" = $codexProviderStreamIdleTimeoutMs
  "CODEX_MODEL_CONTEXT_WINDOW" = $codexModelContextWindow
  "CODEX_MINIMAL_MODEL_INSTRUCTIONS" = $codexMinimalModelInstructions
  "CODEX_MINIMAL_MODEL_INSTRUCTIONS_FILE" = $codexMinimalModelInstructionsFile
  "CODEX_MODEL_REASONING_EFFORT" = $codexModelReasoningEffort
  "CODEX_MODEL_REASONING_SUMMARY" = $codexModelReasoningSummary
  "CODEX_MODEL_VERBOSITY" = $codexModelVerbosity
  "CODEX_EXEC_MODEL" = $codexExecModel
  "CODEX_LMSTUDIO_PROVIDER_ID" = $codexLmstudioProviderId
  "CODEX_PROJECT_DOC_MAX_BYTES" = $codexProjectDocMaxBytes
  "CODEX_PROMPT_MAX_CHARS" = $codexPromptMaxChars
  "CODEX_PROMPT_COMPRESSION_ENABLED" = $codexPromptCompressionEnabled
  "CODEX_PROMPT_COMPRESSION_TRIGGER_CHARS" = $codexPromptCompressionTriggerChars
  "CODEX_PROMPT_COMPRESSION_TARGET_CHARS" = $codexPromptCompressionTargetChars
  "CODEX_PROMPT_KEEP_HEAD_CHARS" = $codexPromptKeepHeadChars
  "CODEX_PROMPT_KEEP_TAIL_CHARS" = $codexPromptKeepTailChars
  "CODEX_PROMPT_KEY_LINES_LIMIT" = $codexPromptKeyLinesLimit
  "CODEX_EXEC_PROGRESS_PING_INTERVAL_MS" = $codexExecProgressPingIntervalMs
  "CODEX_EXEC_RETRY_MAX_ATTEMPTS" = $codexExecRetryMaxAttempts
  "CODEX_EXEC_RETRY_BASE_DELAY_MS" = $codexExecRetryBaseDelayMs
  "CODEX_EXEC_RETRY_MAX_DELAY_MS" = $codexExecRetryMaxDelayMs
  "CODEX_STREAM_RECOVERY_FALLBACK_ENABLED" = $codexStreamRecoveryFallbackEnabled
  "CODEX_STREAM_RECOVERY_TIMEOUT_MS" = $codexStreamRecoveryTimeoutMs
  "CODEX_WEB_SEARCH_MODE" = $codexWebSearchMode
  "CODEX_TOOL_FALLBACK_TO_ENGINE" = $codexToolFallbackToEngine
  "CODEX_TOOL_FALLBACK_FORCE_FOR_LIVE_WEB" = $codexToolFallbackForceForLiveWeb
  "RUNPOD_RESPONSES_BACKGROUND_ENABLED" = $runPodResponsesBackgroundEnabled
  "RUNPOD_RESPONSES_POLL_INTERVAL_MS" = $runPodResponsesPollIntervalMs
  "RUNPOD_RESPONSES_POLL_TIMEOUT_MS" = $runPodResponsesPollTimeoutMs
  "NODE_BIN" = $nodeExe
  "ENGINE_BIND" = $engineBind
  "ENGINE_PORT" = $enginePort
}

$saved = @{}
foreach ($k in $envVars.Keys) {
  $saved[$k] = [Environment]::GetEnvironmentVariable($k, "Process")
  [Environment]::SetEnvironmentVariable($k, $envVars[$k], "Process")
}

try {
  $proc = Start-Process -FilePath $pythonExe `
    -ArgumentList @("-m", "uvicorn", "fastapi_app.main:app", "--host", $appBind, "--port", $appPort) `
    -PassThru `
    -WindowStyle Hidden `
    -WorkingDirectory $PSScriptRoot `
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

Write-Host "LocaLingo started."
Write-Host "PID: $($proc.Id)"
Write-Host "FastAPI: $pythonExe -m uvicorn fastapi_app.main:app"
Write-Host "Node (engine): $nodeExe"
Write-Host "Codex (bundled): $bundledCodexExe"
Write-Host "UV: $uvExe"
Write-Host "Python: $pythonExe"
Write-Host "Config files:"
Write-Host "  local: $localEnvFile"
Write-Host "  shared: $configEnvFile"
Write-Host "Secure key store: $apiKeyStoreFile"
Write-Host "Workspace root: $workspaceRoot"
Write-Host "Workspace state file: $workspaceStateFile"
Write-Host "Agent backend: $agentBackendNormalized"
Write-Host "Endpoint: $(Mask-Url -Url $baseUrl)"
Write-Host "Connection test mode: $connectionTestModeNormalized"
Write-Host "URL: $url"
Write-Host "Out log: $outLog"
Write-Host "Err log: $errLog"
