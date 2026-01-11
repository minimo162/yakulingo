$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

try {
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

    $useProxy = ($env:USE_PROXY -eq '1')
    $proxy = $null
    $cred = $null
    if ($useProxy) {
        if (-not $env:PROXY_SERVER) { throw 'USE_PROXY=1 but PROXY_SERVER is not set.' }
        if (-not $env:PROXY_USER) { throw 'USE_PROXY=1 but PROXY_USER is not set.' }
        if (-not $env:PROXY_PASS) { throw 'USE_PROXY=1 but PROXY_PASS is not set.' }
        $proxy = 'http://' + $env:PROXY_SERVER
        $secPwd = ConvertTo-SecureString $env:PROXY_PASS -AsPlainText -Force
        $cred = New-Object System.Management.Automation.PSCredential ($env:PROXY_USER, $secPwd)
    }

    $userAgent = 'YakuLingo-Installer'
    $httpHeaders = @{ 'User-Agent' = $userAgent }

    $skipModel = ($env:LOCAL_AI_SKIP_MODEL -eq '1')

    function Invoke-Json([string]$url) {
        if ($useProxy) {
            return Invoke-RestMethod -Uri $url -Headers $httpHeaders -Proxy $proxy -ProxyCredential $cred -TimeoutSec 120
        }
        return Invoke-RestMethod -Uri $url -Headers $httpHeaders -TimeoutSec 120
    }

    function Get-RemoteContentLengthCurl([string]$url) {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if (-not $curl) { return $null }
        try {
            $headers = & $curl.Source '--location' '--head' '--silent' '--show-error' '--fail' '--user-agent' $userAgent $url 2>$null
            if ($LASTEXITCODE -ne 0) { return $null }
            $length = $null
            foreach ($line in $headers) {
                if ($line -match '^\s*content-length:\s*(\d+)\s*$') {
                    $length = [long]$matches[1]
                }
            }
            return $length
        } catch {
            return $null
        }
    }

    function Invoke-Download([string]$url, [string]$outFile, [int]$timeoutSec) {
        $outDir = Split-Path -Parent $outFile
        if ($outDir) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

        if (-not $useProxy) {
            $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
            if ($curl) {
                $remoteLength = $null
                if (Test-Path $outFile) {
                    $localLength = (Get-Item $outFile).Length
                    if ($localLength -gt 0) {
                        $remoteLength = Get-RemoteContentLengthCurl $url
                        if ($remoteLength -and $remoteLength -gt 0 -and $localLength -ge $remoteLength) {
                            return
                        }
                    }
                }
                $args = @(
                    '--location',
                    '--fail',
                    '--user-agent', $userAgent,
                    '--retry', '10',
                    '--retry-delay', '5',
                    '--connect-timeout', '30',
                    '--max-time', "$timeoutSec"
                )
                if (Test-Path $outFile) {
                    $args += @('--continue-at', '-')
                }
                $args += @('--output', $outFile, $url)
                & $curl.Source @args
                if ($LASTEXITCODE -eq 0) {
                    return
                }

                if ((Test-Path $outFile) -and ($remoteLength -eq $null)) {
                    $remoteLength = Get-RemoteContentLengthCurl $url
                }
                if ($remoteLength -and $remoteLength -gt 0 -and (Test-Path $outFile) -and ((Get-Item $outFile).Length -eq $remoteLength)) {
                    return
                }

                Write-Host "[WARNING] curl.exe failed (exit=$LASTEXITCODE). Falling back to Invoke-WebRequest/BITS: $url"
            }
        }

        $attempts = 3
        $lastError = $null
        for ($attempt = 1; $attempt -le $attempts; $attempt++) {
            try {
                if ($useProxy) {
                    Invoke-WebRequest -Uri $url -OutFile $outFile -UseBasicParsing -Headers $httpHeaders -Proxy $proxy -ProxyCredential $cred -TimeoutSec $timeoutSec | Out-Null
                } else {
                    Invoke-WebRequest -Uri $url -OutFile $outFile -UseBasicParsing -Headers $httpHeaders -TimeoutSec $timeoutSec | Out-Null
                }
                return
            } catch {
                $lastError = $_
                if ($attempt -ge $attempts) { break }
                Start-Sleep -Seconds ([Math]::Min(30, 2 * $attempt))
            }
        }

        $bits = Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue
        if ($bits) {
            try {
                $bitsParams = @{
                    Source = $url
                    Destination = $outFile
                    DisplayName = 'YakuLingo Installer Download'
                    ErrorAction = 'Stop'
                }
                if ($useProxy) {
                    $bitsParams.ProxyUsage = 'Override'
                    $bitsParams.ProxyList = @([uri]$proxy)
                    if ($cred) { $bitsParams.ProxyCredential = $cred }
                }
                Start-BitsTransfer @bitsParams | Out-Null
                return
            } catch {
                $lastError = $_
            }
        }

        if ($lastError) { throw $lastError }
        throw "Download failed: $url"
    }

    $root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    Set-Location -Path $root
    $localAiDir = Join-Path $root 'local_ai'
    $llamaDir = Join-Path $localAiDir 'llama_cpp'
    $llamaAvx2Dir = Join-Path $llamaDir 'avx2'
    $modelsDir = Join-Path $localAiDir 'models'
    New-Item -ItemType Directory -Force -Path $localAiDir, $llamaDir, $llamaAvx2Dir, $modelsDir | Out-Null

    $manifestPath = Join-Path $localAiDir 'manifest.json'
    $existingManifest = $null
    if (Test-Path $manifestPath) {
        try { $existingManifest = Get-Content -Raw -Path $manifestPath | ConvertFrom-Json } catch { $existingManifest = $null }
    }

    function Get-ChildPathSafe([string]$baseDir, [string]$relativePath) {
        if ([string]::IsNullOrWhiteSpace($relativePath)) { throw 'Path must not be empty.' }
        if ([System.IO.Path]::IsPathRooted($relativePath)) { throw "Absolute path is not allowed: $relativePath" }
        $baseFull = [System.IO.Path]::GetFullPath($baseDir)
        $basePrefix = $baseFull
        if (-not $basePrefix.EndsWith([System.IO.Path]::DirectorySeparatorChar)) { $basePrefix += [System.IO.Path]::DirectorySeparatorChar }
        $childFull = [System.IO.Path]::GetFullPath((Join-Path $baseDir $relativePath))
        if (-not $childFull.StartsWith($basePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Path traversal is not allowed: $relativePath"
        }
        return $childFull
    }

    $defaultModelRepo = 'dahara1/shisa-v2.1-llama3.2-3b-UD-japanese-imatrix'
    $defaultModelFile = 'Llama-3.2-3B-Instruct-UD-Q4_K_XL.gguf'
    $manifestModelRepo = $null
    $manifestModelFile = $null
    if ($existingManifest -and $existingManifest.model) {
        $manifestModelRepo = $existingManifest.model.repo
        $manifestModelFile = $existingManifest.model.file
    }

    $modelRepo = $defaultModelRepo
    if (-not [string]::IsNullOrWhiteSpace($manifestModelRepo)) { $modelRepo = $manifestModelRepo }
    $modelFile = $defaultModelFile
    if (-not [string]::IsNullOrWhiteSpace($manifestModelFile)) { $modelFile = $manifestModelFile }

    if ($env:LOCAL_AI_MODEL_REPO) { $modelRepo = $env:LOCAL_AI_MODEL_REPO }
    if ($env:LOCAL_AI_MODEL_FILE) { $modelFile = $env:LOCAL_AI_MODEL_FILE }
    $modelUrl = "https://huggingface.co/$modelRepo/resolve/main/$modelFile"
    $modelPath = Get-ChildPathSafe $modelsDir $modelFile
    $modelTempPath = $modelPath + '.partial'
    $licenseUrl = 'https://www.apache.org/licenses/LICENSE-2.0.txt'
    $readmeUrl = "https://huggingface.co/$modelRepo/resolve/main/README.md"

    $llamaRepo = 'ggerganov/llama.cpp'
    $serverExePath = Join-Path $llamaAvx2Dir 'llama-server.exe'
    $llamaLicenseOut = Join-Path $llamaDir 'LICENSE'

    $tag = $null
    $llamaZipUrl = $null
    $llamaZipName = $null
    $downloadedLlama = $false
    if (-not (Test-Path $serverExePath)) {
        $llamaZipPath = $null
        $llamaLicenseUrl = $null

        try {
            $release = Invoke-Json "https://api.github.com/repos/$llamaRepo/releases/latest"
            $tag = $release.tag_name
            if (-not $tag) { throw 'Failed to read llama.cpp release tag.' }
            $asset = $release.assets | Where-Object { $_.name -match 'bin-win-cpu-x64\.zip$' } | Select-Object -First 1
            if (-not $asset) { throw 'llama.cpp Windows CPU(x64) binary not found in release assets.' }

            $llamaZipUrl = $asset.browser_download_url
            $llamaZipName = [System.IO.Path]::GetFileName([string]$asset.name)
            $llamaZipPath = Join-Path $llamaDir $llamaZipName
            $llamaLicenseUrl = "https://raw.githubusercontent.com/$llamaRepo/$tag/LICENSE"
        } catch {
            Write-Host "[WARNING] Failed to query GitHub API for llama.cpp release: $($_.Exception.Message)"
            Write-Host '[INFO] Falling back to parsing GitHub releases page HTML...'

            $latestUrl = "https://github.com/$llamaRepo/releases/latest"
            if ($useProxy) {
                $resp = Invoke-WebRequest -Uri $latestUrl -UseBasicParsing -Headers $httpHeaders -Proxy $proxy -ProxyCredential $cred -TimeoutSec 120
            } else {
                $resp = Invoke-WebRequest -Uri $latestUrl -UseBasicParsing -Headers $httpHeaders -TimeoutSec 120
            }
            $html = [string]$resp.Content

            $repoPath = [regex]::Escape("/$llamaRepo")
            $pattern = 'href="(?<href>' + $repoPath + '/releases/download/[^"/\s]+/[^"\s]*bin-win-cpu-x64\.zip)"'
            $m = [regex]::Match($html, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
            if (-not $m.Success) { throw 'llama.cpp Windows CPU(x64) binary link not found on releases page.' }

            $href = $m.Groups['href'].Value
            $llamaZipUrl = 'https://github.com' + $href
            $llamaZipName = Split-Path -Leaf $href
            $llamaZipPath = Join-Path $llamaDir $llamaZipName

            $tagMatch = [regex]::Match($href, '/releases/download/(?<tag>[^/]+)/', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
            if ($tagMatch.Success) { $tag = $tagMatch.Groups['tag'].Value }
            if (-not $tag) { $tag = 'master' }
            $llamaLicenseUrl = "https://raw.githubusercontent.com/$llamaRepo/$tag/LICENSE"
        }

        Write-Host "[INFO] Downloading llama.cpp ($tag): $llamaZipName"
        Invoke-Download $llamaZipUrl $llamaZipPath 1800

        $tmp = Join-Path $llamaDir '_tmp_extract'
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
        Expand-Archive -Path $llamaZipPath -DestinationPath $tmp -Force

        $candidates = Get-ChildItem -Path $tmp -Recurse -Filter 'llama-server.exe'
        $found = $candidates | Sort-Object { $_.FullName -notmatch '\\avx2\\' } | Select-Object -First 1
        if (-not $found) { throw 'llama-server.exe not found in ZIP.' }
        $srcDir = $found.DirectoryName

        if (Test-Path $llamaAvx2Dir) { Remove-Item $llamaAvx2Dir -Recurse -Force -ErrorAction SilentlyContinue }
        New-Item -ItemType Directory -Force -Path $llamaAvx2Dir | Out-Null
        Copy-Item -Path (Join-Path $srcDir '*') -Destination $llamaAvx2Dir -Recurse -Force

        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item $llamaZipPath -Force -ErrorAction SilentlyContinue

        $downloadedLlama = $true
        try { Invoke-Download $llamaLicenseUrl $llamaLicenseOut 120 } catch { Write-Host "[WARNING] Failed to download llama.cpp LICENSE: $($_.Exception.Message)" }
    } else {
        if ($existingManifest -and $existingManifest.llama_cpp) {
            $tag = $existingManifest.llama_cpp.release_tag
            $llamaZipName = $existingManifest.llama_cpp.asset_name
            $llamaZipUrl = $existingManifest.llama_cpp.download_url
        }
        if (-not (Test-Path $llamaLicenseOut)) {
            $fallbackTag = $tag
            if (-not $fallbackTag) { $fallbackTag = 'master' }
            $fallbackLicenseUrl = "https://raw.githubusercontent.com/$llamaRepo/$fallbackTag/LICENSE"
            try { Invoke-Download $fallbackLicenseUrl $llamaLicenseOut 120 } catch { Write-Host "[WARNING] Failed to download llama.cpp LICENSE: $($_.Exception.Message)" }
        }
    }

    if ($skipModel) {
        Write-Host '[INFO] Skipping model download (LOCAL_AI_SKIP_MODEL=1).'
    } else {
        $downloadedModel = $false
        if (Test-Path $modelTempPath) {
            Write-Host "[INFO] Resuming partial model download: $(Split-Path -Leaf $modelTempPath)"
            Invoke-Download $modelUrl $modelTempPath 14400
            Move-Item -Force -Path $modelTempPath -Destination $modelPath
            $downloadedModel = $true
        } else {
            $hasModel = (Test-Path $modelPath) -and ((Get-Item $modelPath).Length -gt 0)
            if ($hasModel) {
                Write-Host "[INFO] Model already exists: $(Split-Path -Leaf $modelPath)"
                $existingModelSha = $null
                if ($existingManifest -and $existingManifest.model -and $existingManifest.model.sha256) {
                    $existingModelSha = $existingManifest.model.sha256
                }
                if (-not $existingModelSha -and (-not $useProxy) -and (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
                    Write-Host '[INFO] Verifying/resuming model download (no existing SHA256 in manifest)...'
                    Invoke-Download $modelUrl $modelPath 14400
                    $downloadedModel = $true
                }
            } else {
                Write-Host "[INFO] Downloading model: $modelRepo/$modelFile"
                Invoke-Download $modelUrl $modelTempPath 14400
                Move-Item -Force -Path $modelTempPath -Destination $modelPath
                $downloadedModel = $true
            }
        }
    }

    try { Invoke-Download $licenseUrl (Join-Path $modelsDir 'LICENSE') 120 } catch { Write-Host "[WARNING] Failed to download model LICENSE: $($_.Exception.Message)" }
    try { Invoke-Download $readmeUrl (Join-Path $modelsDir 'README.md') 120 } catch { Write-Host "[WARNING] Failed to download model README: $($_.Exception.Message)" }

    $serverHash = $null
    if ($existingManifest -and $existingManifest.llama_cpp -and $existingManifest.llama_cpp.server_exe_sha256 -and -not $downloadedLlama) {
        $serverHash = $existingManifest.llama_cpp.server_exe_sha256
    } elseif (Test-Path $serverExePath) {
        $serverHash = (Get-FileHash -Algorithm SHA256 -Path $serverExePath).Hash
    }

    $modelHash = $null
    $existingModelHash = $null
    if ($existingManifest -and $existingManifest.model -and $existingManifest.model.sha256) { $existingModelHash = $existingManifest.model.sha256 }
    if ($skipModel) {
        $modelHash = $existingModelHash
    } elseif ($downloadedModel -and (Test-Path $modelPath) -and ((Get-Item $modelPath).Length -gt 0)) {
        $modelHash = (Get-FileHash -Algorithm SHA256 -Path $modelPath).Hash
    } else {
        $modelHash = $existingModelHash
    }

    $manifest = [ordered]@{
        generated_at = (Get-Date).ToString('o')
        llama_cpp = [ordered]@{
            repo = $llamaRepo
            release_tag = $tag
            asset_name = $llamaZipName
            download_url = $llamaZipUrl
            server_exe_sha256 = $serverHash
        }
        model = [ordered]@{
            repo = $modelRepo
            file = $modelFile
            download_url = $modelUrl
            sha256 = $modelHash
            skipped = $skipModel
        }
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding UTF8

    Write-Host '[DONE] Local AI runtime is ready.'
    exit 0
} catch {
    Write-Host "[ERROR] Local AI runtime installation failed: $($_.Exception.Message)"
    if ($_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace }
    exit 1
}

