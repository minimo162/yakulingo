param(
  [string]$ApiKey,
  [string]$OutFile = ""
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

function Get-ObfuscationMask {
  return [byte[]](0xA3, 0x5C, 0x91, 0x17, 0x4E, 0xD2, 0x68, 0x2B, 0xF0, 0x3D, 0x86, 0x1A)
}

function Encode-SharedObfuscatedApiKey {
  param([Parameter(Mandatory = $true)][string]$Key)
  $bytes = [Text.Encoding]::UTF8.GetBytes($Key)
  $mask = Get-ObfuscationMask
  for ($i = 0; $i -lt $bytes.Length; $i++) {
    $bytes[$i] = $bytes[$i] -bxor $mask[$i % $mask.Length]
  }
  return "YKOBF1:" + [Convert]::ToBase64String($bytes)
}

if ([string]::IsNullOrWhiteSpace($OutFile)) {
  $OutFile = Join-Path $PSScriptRoot "runpod_api_key.obf"
}

if (!(Split-Path -Path $OutFile -IsAbsolute)) {
  $OutFile = Join-Path $PSScriptRoot $OutFile
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

$dir = Split-Path -Path $OutFile -Parent
if ($dir -and !(Test-Path $dir)) {
  New-Item -ItemType Directory -Path $dir | Out-Null
}

$obf = Encode-SharedObfuscatedApiKey -Key $ApiKey
Set-Content -Path $OutFile -Value $obf -Encoding ASCII

Write-Host "Shared obfuscated key file generated:"
Write-Host "  $OutFile"
Write-Host "Note: this is obfuscation, not strong encryption."
