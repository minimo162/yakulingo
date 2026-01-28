$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

try {
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }

    $useProxy = ($env:USE_PROXY -eq '1')
    $proxy = $null
    $cred = $null
    if ($useProxy) {
        if (-not $env:PROXY_SERVER) { throw 'USE_PROXY=1 but PROXY_SERVER is not set. Rerun packaging\install_deps.bat and select proxy option [1].' }
        if (-not $env:PROXY_USER) { throw 'USE_PROXY=1 but PROXY_USER is not set. Rerun packaging\install_deps.bat and select proxy option [1].' }
        if (-not $env:PROXY_PASS) { throw 'USE_PROXY=1 but PROXY_PASS is not set. Rerun packaging\install_deps.bat and select proxy option [1].' }
        $proxy = 'http://' + $env:PROXY_SERVER
        $secPwd = ConvertTo-SecureString $env:PROXY_PASS -AsPlainText -Force
        $cred = New-Object System.Management.Automation.PSCredential ($env:PROXY_USER, $secPwd)
    }

    $userAgent = 'YakuLingo-Installer'
    $httpHeaders = @{ 'User-Agent' = $userAgent }

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

        $leaf = Split-Path -Leaf $outFile
        if ($timeoutSec -ge 600 -or $leaf -match '\.(gguf|zip)(\.partial)?$') {
            Write-Host "[INFO] Download start: $leaf (timeout=${timeoutSec}s)"
        }

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
                    Write-Host "[INFO] Resuming download with curl: $leaf"
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
                Write-Host "[WARNING] Download failed (attempt $attempt/$attempts): $leaf ($($_.Exception.Message))"
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

    function Stop-LocalLlamaProcesses([string]$llamaBaseDir) {
        $stopped = @()
        $baseFull = $null
        try {
            $baseFull = [System.IO.Path]::GetFullPath($llamaBaseDir)
        } catch {
            return $stopped
        }
        if (-not $baseFull.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
            $baseFull += [System.IO.Path]::DirectorySeparatorChar
        }

        $filter = "Name='llama-server.exe' OR Name='llama-cli.exe' OR Name='llama-bench.exe'"
        $cim = $null
        try {
            $cim = Get-CimInstance Win32_Process -Filter $filter -ErrorAction Stop
        } catch {
            return $stopped
        }

        foreach ($p in $cim) {
            $exe = [string]$p.ExecutablePath
            if ([string]::IsNullOrWhiteSpace($exe)) { continue }
            $exeFull = $null
            try { $exeFull = [System.IO.Path]::GetFullPath($exe) } catch { continue }
            if (-not $exeFull.StartsWith($baseFull, [System.StringComparison]::OrdinalIgnoreCase)) { continue }

            $procId = [int]$p.ProcessId
            Write-Host "[INFO] Stopping local llama.cpp process (pid=$procId): $exeFull"
            try {
                Stop-Process -Id $procId -ErrorAction Stop
            } catch {
                try {
                    Stop-Process -Id $procId -Force -ErrorAction Stop
                } catch {
                    Write-Host "[WARNING] Failed to stop process (pid=$procId): $($_.Exception.Message)"
                    continue
                }
            }
            $stopped += $procId
        }

        if ($stopped.Count -gt 0) {
            Start-Sleep -Milliseconds 800
        }
        return $stopped
    }

    $root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    Set-Location -Path $root
    $localAiDir = Join-Path $root 'local_ai'
    $llamaDir = Join-Path $localAiDir 'llama_cpp'
    $llamaAvx2Dir = Join-Path $llamaDir 'avx2'
    $llamaVulkanDir = Join-Path $llamaDir 'vulkan'
    $modelsDir = Join-Path $localAiDir 'models'
    New-Item -ItemType Directory -Force -Path $localAiDir, $llamaDir, $llamaAvx2Dir, $llamaVulkanDir, $modelsDir | Out-Null

    $manifestPath = Join-Path $localAiDir 'manifest.json'
    $existingManifest = $null
    if (Test-Path $manifestPath) {
        try { $existingManifest = Get-Content -Raw -Path $manifestPath | ConvertFrom-Json } catch { $existingManifest = $null }
    }

    $llamaVariant = 'vulkan'
    if ($existingManifest -and $existingManifest.llama_cpp -and $existingManifest.llama_cpp.variant) {
        $llamaVariant = [string]$existingManifest.llama_cpp.variant
    }
    if ($env:LOCAL_AI_LLAMA_CPP_VARIANT) { $llamaVariant = [string]$env:LOCAL_AI_LLAMA_CPP_VARIANT }
    $llamaVariant = $llamaVariant.ToLowerInvariant()
    if ($llamaVariant -ne 'vulkan') { $llamaVariant = 'cpu' }
    $llamaVariantDir = if ($llamaVariant -eq 'vulkan') { $llamaVulkanDir } else { $llamaAvx2Dir }
    $llamaLabel = if ($llamaVariant -eq 'vulkan') { 'Vulkan(x64)' } else { 'CPU(x64)' }

    Write-Host "[INFO] Local AI install root: $root"
    $proxyLabel = if ($useProxy) { 'enabled' } else { 'disabled' }
    Write-Host "[INFO] Proxy: $proxyLabel"
    if ($useProxy) { Write-Host "[INFO] Proxy server: $proxy" }
    Write-Host "[INFO] Skip model: no"
    Write-Host "[INFO] llama.cpp variant: $llamaVariant ($llamaLabel)"

    function Move-FileWithRetry([string]$src, [string]$dst, [string]$label, [switch]$StopLlama) {
        if (-not (Test-Path $src)) { throw "Source file not found for ${label}: $src" }
        $stoppedOnce = $false
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            try {
                Move-Item -Force -Path $src -Destination $dst -ErrorAction Stop
                return
            } catch {
                if ($StopLlama -and -not $stoppedOnce) {
                    $stoppedOnce = $true
                    $null = Stop-LocalLlamaProcesses $llamaDir
                }
                Start-Sleep -Milliseconds (500 * $attempt)
            }
        }

        try {
            Copy-Item -Force -Path $src -Destination $dst -ErrorAction Stop
            Remove-Item -Force -Path $src -ErrorAction SilentlyContinue
            return
        } catch {
        }

        throw "Failed to move $label to destination (file may be locked): $dst"
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

    function Get-LlamaLatest([string]$repo, [string]$assetSuffix, [string]$label) {
        $result = [ordered]@{
            tag = $null
            url = $null
            name = $null
            licenseUrl = $null
        }
        try {
            $release = Invoke-Json "https://api.github.com/repos/$repo/releases/latest"
            $tag = $release.tag_name
            if (-not $tag) { throw 'Failed to read llama.cpp release tag.' }
            $asset = $release.assets | Where-Object { $_.name -match ($assetSuffix + '$') } | Select-Object -First 1
            if (-not $asset) { throw "llama.cpp Windows $label binary not found in release assets." }

            $result.tag = $tag
            $result.url = $asset.browser_download_url
            $result.name = [System.IO.Path]::GetFileName([string]$asset.name)
            $result.licenseUrl = "https://raw.githubusercontent.com/$repo/$tag/LICENSE"
            return $result
        } catch {
            Write-Host "[WARNING] Failed to query GitHub API for llama.cpp release: $($_.Exception.Message)"
            Write-Host '[INFO] Falling back to parsing GitHub releases page HTML...'

            $latestUrl = "https://github.com/$repo/releases/latest"
            if ($useProxy) {
                $resp = Invoke-WebRequest -Uri $latestUrl -UseBasicParsing -Headers $httpHeaders -Proxy $proxy -ProxyCredential $cred -TimeoutSec 120
            } else {
                $resp = Invoke-WebRequest -Uri $latestUrl -UseBasicParsing -Headers $httpHeaders -TimeoutSec 120
            }
            $html = [string]$resp.Content

            $repoPath = [regex]::Escape("/$repo")
            $pattern = 'href="(?<href>' + $repoPath + '/releases/download/[^"/\s]+/[^"\s]*' + $assetSuffix + ')"'
            $m = [regex]::Match($html, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
            if (-not $m.Success) { throw "llama.cpp Windows $label binary link not found on releases page." }

            $href = $m.Groups['href'].Value
            $result.url = 'https://github.com' + $href
            $result.name = Split-Path -Leaf $href

            $tagMatch = [regex]::Match($href, '/releases/download/(?<tag>[^/]+)/', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
            if ($tagMatch.Success) { $result.tag = $tagMatch.Groups['tag'].Value }
            if (-not $result.tag) { $result.tag = 'master' }
            $result.licenseUrl = "https://raw.githubusercontent.com/$repo/$result.tag/LICENSE"
            return $result
        }
    }

    # Default model (fixed):
    # Always use a prebuilt GGUF downloaded from Hugging Face.
    $defaultModelRepo = 'mradermacher/translategemma-12b-it-i1-GGUF'
    $defaultModelFile = 'translategemma-12b-it.i1-IQ4_XS.gguf'
    $defaultModelRevision = 'main'

    # Model selection is fixed (manifest/env overrides are ignored).
    $modelRepo = $defaultModelRepo
    $modelFile = $defaultModelFile
    $modelRevision = $defaultModelRevision
    $modelKind = 'gguf'

    $modelUrl = "https://huggingface.co/$modelRepo/resolve/$modelRevision/$modelFile"

    $modelPath = Get-ChildPathSafe $modelsDir $modelFile
    $modelTempPath = $null
    if ($modelKind -eq 'gguf') {
        $modelTempPath = $modelPath + '.partial'
    }
    $licenseUrl = "https://huggingface.co/$modelRepo/raw/$modelRevision/LICENSE"
    $readmeUrl = "https://huggingface.co/$modelRepo/resolve/$modelRevision/README.md"

    $llamaRepo = 'ggerganov/llama.cpp'
    $serverExePath = Join-Path $llamaVariantDir 'llama-server.exe'
    $llamaLicenseOut = Join-Path $llamaDir 'LICENSE'

    $llamaAssetSuffix = if ($llamaVariant -eq 'vulkan') { 'bin-win-vulkan-x64\.zip' } else { 'bin-win-cpu-x64\.zip' }
    $tag = $null
    $llamaZipUrl = $null
    $llamaZipName = $null
    $llamaLicenseUrl = $null
    $downloadedLlama = $false
    $serverExists = Test-Path $serverExePath

    $existingVariant = $null
    $existingTag = $null
    $existingZipName = $null
    $existingZipUrl = $null
    $existingHash = $null
    if ($existingManifest -and $existingManifest.llama_cpp) {
        $existingVariant = [string]$existingManifest.llama_cpp.variant
        if ([string]::IsNullOrWhiteSpace($existingVariant)) { $existingVariant = 'cpu' }
        $existingTag = $existingManifest.llama_cpp.release_tag
        $existingZipName = $existingManifest.llama_cpp.asset_name
        $existingZipUrl = $existingManifest.llama_cpp.download_url
        $existingHash = $existingManifest.llama_cpp.server_exe_sha256
    }

    $latestInfo = $null
    $latestError = $null
    try {
        $latestInfo = Get-LlamaLatest $llamaRepo $llamaAssetSuffix $llamaLabel
    } catch {
        $latestError = $_.Exception.Message
    }

    if ($latestInfo) {
        $tag = $latestInfo.tag
        $llamaZipUrl = $latestInfo.url
        $llamaZipName = $latestInfo.name
        $llamaLicenseUrl = $latestInfo.licenseUrl
    } elseif (-not $serverExists) {
        throw "Failed to retrieve latest llama.cpp release: $latestError"
    } else {
        Write-Host "[WARNING] Failed to retrieve latest llama.cpp release: $latestError"
        Write-Host '[INFO] Using existing llama.cpp without updating.'
        $tag = $existingTag
        $llamaZipName = $existingZipName
        $llamaZipUrl = $existingZipUrl
    }

    $currentHash = $null
    if ($serverExists) {
        try {
            $currentHash = (Get-FileHash -Algorithm SHA256 -Path $serverExePath).Hash
        } catch {
            Write-Host "[WARNING] Failed to hash existing llama-server.exe: $($_.Exception.Message)"
        }
    }

    $needsDownload = -not $serverExists
    if (-not $needsDownload -and $latestInfo) {
        $manifestMatches = $false
        if ($existingVariant -and $existingVariant.ToLowerInvariant() -eq $llamaVariant `
            -and $existingTag -and $existingTag -eq $tag `
            -and $existingZipName -and $existingZipName -eq $llamaZipName `
            -and $existingZipUrl -and $existingZipUrl -eq $llamaZipUrl `
            -and $existingHash -and $currentHash -and $existingHash -eq $currentHash) {
            $manifestMatches = $true
        }
        if (-not $manifestMatches) { $needsDownload = $true }
    }

    if ($needsDownload) {
        if (-not $llamaZipUrl -or -not $llamaZipName) { throw "llama.cpp Windows $llamaLabel binary URL not resolved." }
        $llamaZipPath = Join-Path $llamaDir $llamaZipName
        Write-Host "[INFO] Downloading llama.cpp ($tag, $llamaLabel): $llamaZipName"
        Invoke-Download $llamaZipUrl $llamaZipPath 1800

        $tmp = Join-Path $llamaDir '_tmp_extract'
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
        $serverExistedBefore = $serverExists
        try {
            Expand-Archive -Path $llamaZipPath -DestinationPath $tmp -Force

            $candidates = Get-ChildItem -Path $tmp -Recurse -Filter 'llama-server.exe'
            $found = $candidates | Sort-Object { $_.FullName -notmatch '\\avx2\\' } | Select-Object -First 1
            if (-not $found) { throw 'llama-server.exe not found in ZIP.' }
            $srcDir = $found.DirectoryName

            $stagingDir = $llamaVariantDir + '._staging'
            $backupDir = $llamaVariantDir + '._old'
            if (Test-Path $stagingDir) { Remove-Item $stagingDir -Recurse -Force -ErrorAction SilentlyContinue }
            if (Test-Path $backupDir) { Remove-Item $backupDir -Recurse -Force -ErrorAction SilentlyContinue }

            New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null
            Copy-Item -Path (Join-Path $srcDir '*') -Destination $stagingDir -Recurse -Force -ErrorAction Stop

            $swapSucceeded = $false
            $stoppedOnce = $false
            for ($attempt = 1; $attempt -le 3; $attempt++) {
                try {
                    if (Test-Path $backupDir) { Remove-Item $backupDir -Recurse -Force -ErrorAction SilentlyContinue }
                    if (Test-Path $llamaVariantDir) {
                        Rename-Item -Path $llamaVariantDir -NewName (Split-Path -Leaf $backupDir) -ErrorAction Stop
                    }
                    Rename-Item -Path $stagingDir -NewName (Split-Path -Leaf $llamaVariantDir) -ErrorAction Stop
                    if (Test-Path $backupDir) { Remove-Item $backupDir -Recurse -Force -ErrorAction SilentlyContinue }

                    $swapSucceeded = $true
                    break
                } catch {
                    if (-not $stoppedOnce) {
                        $stoppedOnce = $true
                        $null = Stop-LocalLlamaProcesses $llamaDir
                    }
                    Start-Sleep -Milliseconds (500 * $attempt)

                    # Roll back if we renamed the original dir but failed to place the staging dir.
                    if ((-not (Test-Path $llamaVariantDir)) -and (Test-Path $backupDir)) {
                        try { Rename-Item -Path $backupDir -NewName (Split-Path -Leaf $llamaVariantDir) -ErrorAction Stop } catch { }
                    }
                }
            }

            if (-not $swapSucceeded) {
                if (Test-Path $stagingDir) { Remove-Item $stagingDir -Recurse -Force -ErrorAction SilentlyContinue }

                if (-not $serverExistedBefore) {
                    throw "Failed to install llama.cpp binaries (files locked). Close YakuLingo/llama-server and retry: powershell -NoProfile -ExecutionPolicy Bypass -File packaging\\install_local_ai.ps1"
                }

                Write-Host "[WARNING] Failed to update llama.cpp binaries (files locked). Keeping existing runtime."
                Write-Host "[INFO] Close YakuLingo/llama-server and retry: powershell -NoProfile -ExecutionPolicy Bypass -File packaging\\install_local_ai.ps1"

                if ($existingTag) { $tag = $existingTag }
                if ($existingZipName) { $llamaZipName = $existingZipName }
                if ($existingZipUrl) { $llamaZipUrl = $existingZipUrl }
            } else {
                $downloadedLlama = $true
                $serverExists = $true
                $currentHash = (Get-FileHash -Algorithm SHA256 -Path $serverExePath).Hash
            }
        } finally {
            Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item $llamaZipPath -Force -ErrorAction SilentlyContinue
        }
    }

    if (-not $llamaLicenseUrl -and $tag) {
        $llamaLicenseUrl = "https://raw.githubusercontent.com/$llamaRepo/$tag/LICENSE"
    }
    if (-not $llamaLicenseUrl -and -not (Test-Path $llamaLicenseOut)) {
        $fallbackTag = if ($tag) { $tag } else { 'master' }
        $llamaLicenseUrl = "https://raw.githubusercontent.com/$llamaRepo/$fallbackTag/LICENSE"
    }
    if ($llamaLicenseUrl -and (-not (Test-Path $llamaLicenseOut) -or $downloadedLlama)) {
        try { Invoke-Download $llamaLicenseUrl $llamaLicenseOut 120 } catch { Write-Host "[WARNING] Failed to download llama.cpp LICENSE: $($_.Exception.Message)" }
    }

    $downloadedModel = $false

    if ((Test-Path $modelPath) -and ((Get-Item $modelPath).Length -gt 0) -and (Test-Path $modelTempPath)) {
        Write-Host "[WARNING] Found stale partial file next to existing model; removing: $(Split-Path -Leaf $modelTempPath)"
        Remove-Item -Force -Path $modelTempPath -ErrorAction SilentlyContinue
    }

    if (Test-Path $modelTempPath) {
        Write-Host "[INFO] Resuming partial model download: $(Split-Path -Leaf $modelTempPath)"
        Invoke-Download $modelUrl $modelTempPath 14400
        if (-not (Test-Path $modelTempPath) -or ((Get-Item $modelTempPath).Length -le 0)) {
            throw "Model download did not produce a valid file: $modelTempPath"
        }
        Move-FileWithRetry -src $modelTempPath -dst $modelPath -label 'model' -StopLlama
        $downloadedModel = $true
    } else {
        $hasModel = (Test-Path $modelPath) -and ((Get-Item $modelPath).Length -gt 0)
        if ($hasModel) {
            Write-Host "[INFO] Model already exists: $(Split-Path -Leaf $modelPath)"
            $existingModelSha = $null
            if ($existingManifest -and $existingManifest.model -and $existingManifest.model.sha256) {
                $existingModelSha = $existingManifest.model.sha256
            } elseif ($existingManifest -and $existingManifest.model -and $existingManifest.model.output -and $existingManifest.model.output.sha256) {
                $existingModelSha = $existingManifest.model.output.sha256
            }
            if (-not $existingModelSha -and (-not $useProxy) -and (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
                Write-Host '[INFO] Verifying/resuming model download (no existing SHA256 in manifest)...'
                Invoke-Download $modelUrl $modelPath 14400
                $downloadedModel = $true
            }
        } else {
            Write-Host "[INFO] Downloading model: $modelRepo/$modelFile"
            Invoke-Download $modelUrl $modelTempPath 14400
            if (-not (Test-Path $modelTempPath) -or ((Get-Item $modelTempPath).Length -le 0)) {
                throw "Model download did not produce a valid file: $modelTempPath"
            }
            Move-FileWithRetry -src $modelTempPath -dst $modelPath -label 'model' -StopLlama
            $downloadedModel = $true
        }
    }

    try { Invoke-Download $licenseUrl (Join-Path $modelsDir 'LICENSE') 120 } catch { Write-Host "[WARNING] Failed to download model LICENSE: $($_.Exception.Message)" }
    try { Invoke-Download $readmeUrl (Join-Path $modelsDir 'README.md') 120 } catch { Write-Host "[WARNING] Failed to download model README: $($_.Exception.Message)" }

    $serverHash = $currentHash
    if (-not $serverHash -and $existingHash -and -not $downloadedLlama) {
        if ($existingVariant -and $existingVariant.ToLowerInvariant() -eq $llamaVariant) {
            $serverHash = $existingHash
        }
    }
    if (-not $serverHash -and (Test-Path $serverExePath)) {
        $serverHash = (Get-FileHash -Algorithm SHA256 -Path $serverExePath).Hash
    }

    $modelHash = $null
    $existingModelHash = $null
    if ($existingManifest -and $existingManifest.model -and $existingManifest.model.sha256) {
        $existingModelHash = $existingManifest.model.sha256
    } elseif ($existingManifest -and $existingManifest.model -and $existingManifest.model.output -and $existingManifest.model.output.sha256) {
        $existingModelHash = $existingManifest.model.output.sha256
    }
    if ((Test-Path $modelPath) -and ((Get-Item $modelPath).Length -gt 0)) {
        if ($downloadedModel -or -not $existingModelHash) {
            $modelHash = (Get-FileHash -Algorithm SHA256 -Path $modelPath).Hash
        } else {
            $modelHash = $existingModelHash
        }
    } else {
        $modelHash = $existingModelHash
    }

    $modelRelPath = 'local_ai/models/' + ([string]$modelFile).Replace('\', '/')

    $manifest = [ordered]@{
        generated_at = (Get-Date).ToString('o')
        llama_cpp = [ordered]@{
            repo = $llamaRepo
            release_tag = $tag
            asset_name = $llamaZipName
            download_url = $llamaZipUrl
            server_exe_sha256 = $serverHash
            variant = $llamaVariant
        }
        model = [ordered]@{
            repo = $modelRepo
            revision = $modelRevision
            file = $modelFile
            download_url = $modelUrl
            sha256 = $modelHash
            skipped = $false
            source = [ordered]@{
                kind = $modelKind
                repo = $modelRepo
                revision = $modelRevision
                file = $modelFile
                download_url = $modelUrl
            }
            output = [ordered]@{
                kind = 'gguf'
                path = $modelRelPath
                path_resolved = $modelPath
                sha256 = $modelHash
            }
        }
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding UTF8

    Write-Host '[DONE] Local AI runtime is ready.'
    exit 0
} catch {
    Write-Host "[ERROR] Local AI runtime installation failed: $($_.Exception.Message)"
    Write-Host "[INFO] Recovery hints:"
    Write-Host "[INFO] - The model is fixed and cannot be skipped. Verify network/proxy settings and retry."
    Write-Host "[INFO] - If you see file lock errors, close YakuLingo/llama-server and retry: powershell -NoProfile -ExecutionPolicy Bypass -File packaging\\install_local_ai.ps1"
    Write-Host "[INFO] - If you are behind a corporate proxy, rerun packaging\\install_deps.bat and select proxy option [1]."
    if ($_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace }
    exit 1
}

