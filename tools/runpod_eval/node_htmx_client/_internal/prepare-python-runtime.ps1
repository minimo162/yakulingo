param(
  [string]$PythonSpec = "3.11",
  [string]$UvTarget = ""
)

$ErrorActionPreference = "Stop"

function Resolve-UvTarget {
  param([string]$RequestedTarget)
  if (-not [string]::IsNullOrWhiteSpace($RequestedTarget)) {
    return $RequestedTarget.Trim()
  }
  $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
  switch ("$arch") {
    "X64" { return "x86_64-pc-windows-msvc" }
    "Arm64" { return "aarch64-pc-windows-msvc" }
    "X86" { return "i686-pc-windows-msvc" }
    default {
      throw "Unsupported architecture for uv binary: $arch"
    }
  }
}

function Normalize-PathForCompare {
  param([string]$PathValue)
  if ([string]::IsNullOrWhiteSpace($PathValue)) { return "" }
  try {
    return (Resolve-Path $PathValue).Path.ToLowerInvariant()
  } catch {
    return $PathValue.ToLowerInvariant()
  }
}

function Test-PathPrefix {
  param(
    [string]$PathValue,
    [string]$PrefixPath
  )
  $pathNorm = Normalize-PathForCompare -PathValue $PathValue
  $prefixNorm = Normalize-PathForCompare -PathValue $PrefixPath
  if ([string]::IsNullOrWhiteSpace($pathNorm) -or [string]::IsNullOrWhiteSpace($prefixNorm)) {
    return $false
  }
  return $pathNorm -eq $prefixNorm -or $pathNorm.StartsWith("$prefixNorm\")
}

$baseDir = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $baseDir ".runtime"
$uvDir = Join-Path $runtimeRoot "uv"
$uvExe = Join-Path $uvDir "uv.exe"
$pythonManagedDir = Join-Path $runtimeRoot "python-managed"
$pythonVenvDir = Join-Path $runtimeRoot "python-venv"
$pythonBinFile = Join-Path $runtimeRoot "python-bin.txt"
$stampFile = Join-Path $runtimeRoot "python-runtime.stamp"

$requirements = @(
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.30.0",
  "httpx>=0.27.0",
  "mcp>=1.14.1",
  "jinja2>=3.1.0",
  "python-multipart>=0.0.9",
  "pymupdf>=1.24.0",
  "openpyxl>=3.1.0",
  "python-docx>=1.1.0",
  "python-pptx>=0.6.23"
)

$stamp = @(
  "python_spec=$PythonSpec",
  "install_mode=uv_venv",
  "requirements=$($requirements -join ';')"
) -join "`n"

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
New-Item -ItemType Directory -Force -Path $uvDir | Out-Null

if (!(Test-Path $uvExe)) {
  $target = Resolve-UvTarget -RequestedTarget $UvTarget
  $zipName = "uv-$target.zip"
  $url = "https://github.com/astral-sh/uv/releases/latest/download/$zipName"
  $tmpZip = Join-Path $env:TEMP ("uv-" + [Guid]::NewGuid().ToString("N") + ".zip")
  $tmpExtract = Join-Path $env:TEMP ("uv-extract-" + [Guid]::NewGuid().ToString("N"))

  Write-Host "Downloading bundled uv runtime:"
  Write-Host "  $url"
  Invoke-WebRequest -Uri $url -OutFile $tmpZip
  Expand-Archive -Path $tmpZip -DestinationPath $tmpExtract -Force

  $foundUvExe = Get-ChildItem -Path $tmpExtract -Recurse -Filter "uv.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $foundUvExe) {
    throw "uv.exe was not found in downloaded archive."
  }
  Copy-Item -Path $foundUvExe.FullName -Destination $uvExe -Force

  $foundUvxExe = Get-ChildItem -Path $tmpExtract -Recurse -Filter "uvx.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($foundUvxExe) {
    Copy-Item -Path $foundUvxExe.FullName -Destination (Join-Path $uvDir "uvx.exe") -Force
  }

  Remove-Item -Force $tmpZip -ErrorAction SilentlyContinue
  Remove-Item -Recurse -Force $tmpExtract -ErrorAction SilentlyContinue
}

if (!(Test-Path $uvExe)) {
  throw "Bundled uv runtime is not available: $uvExe"
}

$cachedPython = $null
if ((Test-Path $pythonBinFile) -and (Test-Path $stampFile)) {
  $cachedPython = (Get-Content -Raw $pythonBinFile).Trim()
  $cachedStamp = (Get-Content -Raw $stampFile)
  if ((-not [string]::IsNullOrWhiteSpace($cachedPython)) -and (Test-Path $cachedPython) -and ($cachedStamp -eq $stamp)) {
    Write-Host "Bundled Python runtime already exists:"
    Write-Host "  $cachedPython"
    & $cachedPython -V
    exit 0
  }
}

$cacheDir = Join-Path $env:LOCALAPPDATA "YakuLingoRunpodHtmx\uv-cache"
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
New-Item -ItemType Directory -Force -Path $pythonManagedDir | Out-Null

$savedEnv = @{
  UV_PYTHON_INSTALL_DIR = $env:UV_PYTHON_INSTALL_DIR
  UV_CACHE_DIR = $env:UV_CACHE_DIR
  UV_PYTHON_PREFERENCE = $env:UV_PYTHON_PREFERENCE
}

try {
  $env:UV_PYTHON_INSTALL_DIR = $pythonManagedDir
  $env:UV_CACHE_DIR = $cacheDir
  $env:UV_PYTHON_PREFERENCE = "only-managed"

  Write-Host "Preparing bundled Python runtime (managed by uv):"
  Write-Host "  python spec: $PythonSpec"
  & $uvExe python install $PythonSpec
  if ($LASTEXITCODE -ne 0) {
    throw "uv python install failed (exit=$LASTEXITCODE)."
  }

  $pythonPathRaw = (& $uvExe python find $PythonSpec | Select-Object -First 1)
  $pythonPath = (("$pythonPathRaw").Trim())
  if ([string]::IsNullOrWhiteSpace($pythonPath) -or !(Test-Path $pythonPath)) {
    throw "Failed to resolve managed Python path from uv."
  }
  if (-not (Test-PathPrefix -PathValue $pythonPath -PrefixPath $runtimeRoot)) {
    throw "Resolved Python path is outside runtime root: $pythonPath"
  }

  if (Test-Path $pythonVenvDir) {
    Remove-Item -Recurse -Force $pythonVenvDir -ErrorAction SilentlyContinue
  }

  Write-Host "Creating runtime virtual environment (managed by uv):"
  Write-Host "  venv: $pythonVenvDir"
  & $uvExe venv --python $pythonPath $pythonVenvDir
  if ($LASTEXITCODE -ne 0) {
    throw "uv venv failed (exit=$LASTEXITCODE)."
  }

  $venvPython = Join-Path $pythonVenvDir "Scripts\python.exe"
  if (!(Test-Path $venvPython)) {
    throw "Virtual environment python was not found: $venvPython"
  }
  if (-not (Test-PathPrefix -PathValue $venvPython -PrefixPath $runtimeRoot)) {
    throw "Resolved venv Python path is outside runtime root: $venvPython"
  }

  Write-Host "Installing runtime Python packages:"
  Write-Host "  $($requirements -join ', ')"
  & $uvExe pip install --python $venvPython @requirements
  if ($LASTEXITCODE -ne 0) {
    throw "uv pip install failed (exit=$LASTEXITCODE)."
  }

  Set-Content -Path $pythonBinFile -Value $venvPython -Encoding ASCII
  Set-Content -Path $stampFile -Value $stamp -Encoding UTF8

  Write-Host "Bundled Python runtime prepared:"
  Write-Host "  uv: $uvExe"
  Write-Host "  python: $venvPython"
  & $venvPython -V
} finally {
  foreach ($key in $savedEnv.Keys) {
    if ($null -eq $savedEnv[$key]) {
      Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
    } else {
      Set-Item -Path "Env:$key" -Value $savedEnv[$key]
    }
  }
}
