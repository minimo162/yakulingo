param(
  [string]$ApiKey
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Convert-SecureToPlainText {
  param([Parameter(Mandatory = $true)][Security.SecureString]$SecureValue)
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
  try {
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  }
  finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}

$userDir = Join-Path $env:LOCALAPPDATA "YakuLingoRunpodHtmx"
$keyFile = Join-Path $userDir "runpod_api_key.dpapi"

if (!(Test-Path $userDir)) {
  New-Item -ItemType Directory -Path $userDir | Out-Null
}

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
  Write-Host "Enter token from /workspace/.auth_token (input hidden):"
  $secureInput = Read-Host "RUNPOD_API_KEY" -AsSecureString
  $ApiKey = Convert-SecureToPlainText -SecureValue $secureInput
}

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
  Write-Host "Empty key. Aborted."
  exit 1
}

$secure = ConvertTo-SecureString -String $ApiKey -AsPlainText -Force
$encrypted = $secure | ConvertFrom-SecureString
Set-Content -Path $keyFile -Value $encrypted -Encoding UTF8
try { cmd /c "attrib +h `"$keyFile`"" | Out-Null } catch {}

Write-Host "RunPod API key stored in local DPAPI file:"
Write-Host "  $keyFile"
