param(
    [string]$Version = "latest",
    [string]$InstallerUrl = "",
    [ValidateSet("fast", "best", "standard")]
    [string]$TessdataSet = "fast",
    [string[]]$Languages = @("eng", "rus", "deu", "osd"),
    [switch]$PreferInstaller,
    [switch]$UseSystemSourceFirst,
    [switch]$AllowSystemInstallFallback,
    [switch]$ElevatedRetry,
    [switch]$OfflineCacheOnly
)

$ErrorActionPreference = "Stop"

$installDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $installDir
$downloadDir = Join-Path $installDir "download"
$runtimeDir = Join-Path $rootDir "runtime"
$targetDir = Join-Path $runtimeDir "tesseract"
$installerStageDir = Join-Path $runtimeDir "_tesseract_installer_stage"
$payloadStageDir = Join-Path $runtimeDir "_tesseract_payload_stage"
$targetTessdataDir = Join-Path $targetDir "tessdata"
$payloadTessdataDir = Join-Path $payloadStageDir "tessdata"
$payloadCacheDir = Join-Path $downloadDir "tesseract_payload"

$ubMannheimBaseUrl = "https://digi.bib.uni-mannheim.de/tesseract/"
$fallbackVersion = "5.4.0.20240606"
$headers = @{ "User-Agent" = "Audion-Office-OCR-AI-Installer" }

$tessdataRepo = switch ($TessdataSet) {
    "fast" { "tessdata_fast" }
    "best" { "tessdata_best" }
    default { "tessdata" }
}
$tesseractCacheDir = Join-Path $downloadDir "tesseract"
$tessdataCacheRoot = Join-Path $downloadDir "tessdata"
$tessdataSetCacheDir = Join-Path $tessdataCacheRoot $tessdataRepo
$installerCacheDirs = @($tesseractCacheDir, $downloadDir)

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-UnderDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent
    )
    $fullPath = Resolve-FullPath $Path
    $fullParent = (Resolve-FullPath $Parent).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $prefix = $fullParent + [System.IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe path outside expected directory: $fullPath"
    }
}

function Remove-OwnedDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Label
    )
    Assert-UnderDirectory -Path $Path -Parent $Parent
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force
    } catch {
        throw "Could not remove $Label at $Path. Close Audion Office OCR AI, Workbench and any running tesseract.exe processes, then run the installer again. $($_.Exception.Message)"
    }
}

function Reset-OwnedDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Label
    )
    Remove-OwnedDirectory -Path $Path -Parent $Parent -Label $Label
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Get-InstallerUrlForVersion {
    param([Parameter(Mandatory = $true)][string]$InstallerVersion)
    return "$ubMannheimBaseUrl" + "tesseract-ocr-w64-setup-$InstallerVersion.exe"
}

function Get-InstallerInfoFromPath {
    param([Parameter(Mandatory = $true)][string]$FilePath)
    $name = [System.IO.Path]::GetFileName($FilePath)
    if ($name -notmatch '^tesseract-ocr-w64-setup-(?:v)?(?<version>.+)\.exe$') {
        return $null
    }
    if ($name -match '(?i)(alpha|beta|rc|dev)') {
        return $null
    }
    $versionToken = $Matches["version"]
    $numbers = @([regex]::Matches($name, '\d+') | ForEach-Object { [int]$_.Value })
    if ($numbers.Count -lt 3) {
        return $null
    }
    $build = 0
    $revision = 0
    if ($numbers.Count -ge 4) { $build = $numbers[3] }
    if ($numbers.Count -ge 5) { $revision = $numbers[4] }
    return [pscustomobject]@{
        Path = (Resolve-FullPath $FilePath)
        Name = $name
        Version = $versionToken
        Major = $numbers[0]
        Minor = $numbers[1]
        Patch = $numbers[2]
        Build = $build
        Revision = $revision
    }
}

function Find-CachedInstaller {
    $candidates = @()
    foreach ($dir in ($installerCacheDirs | Sort-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $dir)) {
            continue
        }
        Get-ChildItem -LiteralPath $dir -Filter "tesseract-ocr-w64-setup-*.exe" -Force |
            Where-Object { -not $_.PSIsContainer } |
            ForEach-Object {
                $info = Get-InstallerInfoFromPath -FilePath $_.FullName
                if ($info) {
                    $candidates += $info
                }
            }
    }
    return $candidates |
        Sort-Object -Property Major, Minor, Patch, Build, Revision -Descending |
        Select-Object -First 1
}

function Get-InstallerCachePathForName {
    param([Parameter(Mandatory = $true)][string]$InstallerName)
    foreach ($dir in ($installerCacheDirs | Sort-Object -Unique)) {
        $candidate = Join-Path $dir $InstallerName
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return (Join-Path $tesseractCacheDir $InstallerName)
}

function Resolve-LatestInstaller {
    Write-Host "      Resolving latest UB Mannheim x64 installer..."
    $response = Invoke-WebRequest -Headers $headers -Uri $ubMannheimBaseUrl -UseBasicParsing
    $hrefs = @()
    if ($response.Links) {
        $hrefs += @($response.Links | ForEach-Object { $_.href })
    }
    $hrefs += @([regex]::Matches($response.Content, 'href="([^"]*tesseract-ocr-w64-setup-[^"]+\.exe)"') |
        ForEach-Object { $_.Groups[1].Value })

    $baseUri = [System.Uri]$ubMannheimBaseUrl
    $candidates = @()
    foreach ($href in ($hrefs | Where-Object { $_ } | Sort-Object -Unique)) {
        $name = [System.IO.Path]::GetFileName(([System.Uri]::UnescapeDataString($href)))
        if ($name -match '^tesseract-ocr-w64-setup-(?:v)?(?<version>.+)\.exe$') {
            $versionToken = $Matches["version"]
        } else {
            continue
        }
        if ($name -match '(?i)(alpha|beta|rc|dev)') {
            continue
        }
        $numbers = @([regex]::Matches($name, '\d+') | ForEach-Object { [int]$_.Value })
        if ($numbers.Count -lt 3) {
            continue
        }
        $major = $numbers[0]
        $minor = $numbers[1]
        $patch = $numbers[2]
        $build = 0
        $revision = 0
        if ($numbers.Count -ge 4) { $build = $numbers[3] }
        if ($numbers.Count -ge 5) { $revision = $numbers[4] }
        $uri = ([System.Uri]::new($baseUri, $href)).AbsoluteUri
        $candidates += [pscustomobject]@{
            Name = $name
            Uri = $uri
            Version = $versionToken
            Major = $major
            Minor = $minor
            Patch = $patch
            Build = $build
            Revision = $revision
        }
    }

    $latest = $candidates |
        Sort-Object -Property Major, Minor, Patch, Build, Revision -Descending |
        Select-Object -First 1
    if (-not $latest) {
        throw "No stable x64 Tesseract installer was found at $ubMannheimBaseUrl"
    }
    return $latest
}

function Invoke-Download {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$OutFile
    )
    if ($OfflineCacheOnly) {
        throw "Offline cache mode is enabled and this file is not cached: $Uri"
    }
    Write-Host "  GET $Uri"
    Invoke-WebRequest -Headers $headers -Uri $Uri -OutFile $OutFile -UseBasicParsing
}

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "$Label failed with exit code $($process.ExitCode)"
    }
}

function Invoke-ElevatedInstaller {
    param([Parameter(Mandatory = $true)][string]$FilePath)
    Write-Host "      Requesting UAC elevation for default system install..."
    $args = "/S"
    $process = Start-Process -FilePath $FilePath -ArgumentList $args -Verb RunAs -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Elevated Tesseract installer failed with exit code $($process.ExitCode)"
    }
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-ElevatedSelf {
    $scriptPath = $PSCommandPath
    if (-not $scriptPath) {
        throw "Cannot resolve current script path for UAC retry"
    }
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -Version `"$Version`" -TessdataSet `"$TessdataSet`" -ElevatedRetry"
    if ($InstallerUrl) {
        $args += " -InstallerUrl `"$InstallerUrl`""
    }
    if ($UseSystemSourceFirst) {
        $args += " -UseSystemSourceFirst"
    }
    if ($PreferInstaller) {
        $args += " -PreferInstaller"
    }
    if ($AllowSystemInstallFallback) {
        $args += " -AllowSystemInstallFallback"
    }
    if ($OfflineCacheOnly) {
        $args += " -OfflineCacheOnly"
    }
    if ($Languages.Count -gt 0) {
        $args += " -Languages " + (($Languages | ForEach-Object { "`"$_`"" }) -join " ")
    }
    Write-Host "      Requesting UAC elevation for copying from protected system folders..."
    $process = Start-Process -FilePath "powershell.exe" -ArgumentList $args -Verb RunAs -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Elevated Tesseract copy failed with exit code $($process.ExitCode)"
    }
}

function Find-TesseractSourceDir {
    $candidates = @()
    $candidates += $payloadCacheDir
    if ($env:AUDION_TESSERACT_SOURCE_DIR) {
        $candidates += $env:AUDION_TESSERACT_SOURCE_DIR
    }
    $candidates += @(
        "C:\Program Files\Tesseract-OCR",
        "C:\Program Files (x86)\Tesseract-OCR"
    )

    $targetFullPath = $null
    if (Test-Path -LiteralPath $targetDir) {
        $targetFullPath = Resolve-FullPath $targetDir
    }

    foreach ($candidate in $candidates) {
        $exe = Join-Path $candidate "tesseract.exe"
        if (-not (Test-Path -LiteralPath $exe)) {
            continue
        }
        $fullCandidate = Resolve-FullPath $candidate
        if ($targetFullPath -and $fullCandidate.Equals($targetFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        return $fullCandidate
    }
    return $null
}

function Copy-TesseractPayload {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDir,
        [Parameter(Mandatory = $true)][string]$DestinationDir
    )

    if (-not (Test-Path -LiteralPath (Join-Path $SourceDir "tesseract.exe"))) {
        throw "Tesseract source does not contain tesseract.exe: $SourceDir"
    }

    Reset-OwnedDirectory -Path $DestinationDir -Parent $runtimeDir -Label "Tesseract payload staging folder"

    Get-ChildItem -LiteralPath $SourceDir -Force |
        Where-Object { -not $_.PSIsContainer -and ($_.Name -eq "tesseract.exe" -or $_.Extension -eq ".dll") } |
        Copy-Item -Destination $DestinationDir -Force

    $sourceTessdata = Join-Path $SourceDir "tessdata"
    $destinationTessdata = Join-Path $DestinationDir "tessdata"
    New-Item -ItemType Directory -Force -Path $destinationTessdata | Out-Null
    if (Test-Path -LiteralPath $sourceTessdata) {
        Get-ChildItem -LiteralPath $sourceTessdata -Force |
            Where-Object { $_.Name -in @("configs", "tessconfigs", "pdf.ttf") } |
            Copy-Item -Destination $destinationTessdata -Recurse -Force
    }

    Get-ChildItem -LiteralPath $DestinationDir -Filter "unins*" -Force -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

function Copy-TesseractPayloadWithRetry {
    param([Parameter(Mandatory = $true)][string]$SourceDir)
    try {
        Copy-TesseractPayload -SourceDir $SourceDir -DestinationDir $payloadStageDir
    } catch {
        if ((-not $ElevatedRetry) -and (-not (Test-IsAdministrator))) {
            Write-Warning "Copy from the system Tesseract folder failed: $($_.Exception.Message)"
            Invoke-ElevatedSelf
            exit 0
        }
        throw
    }
}

function Save-LicenseFile {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$OutFile
    )
    try {
        Invoke-Download -Uri $Uri -OutFile $OutFile
    } catch {
        Write-Warning "Could not download license file: $Uri"
        "License file download failed. Source: $Uri" | Set-Content -Path $OutFile -Encoding UTF8
    }
}

function Find-LocalTessdataFile {
    param(
        [Parameter(Mandatory = $true)][string]$Language,
        [string[]]$ExtraDirs = @()
    )
    $candidateDirs = @($tessdataSetCacheDir, $tessdataCacheRoot, $downloadDir)
    $candidateDirs += @($ExtraDirs | Where-Object { $_ })
    foreach ($dir in ($candidateDirs | Sort-Object -Unique)) {
        $candidate = Join-Path $dir "$Language.traineddata"
        if (-not (Test-Path -LiteralPath $candidate)) {
            continue
        }
        $item = Get-Item -LiteralPath $candidate
        if ($item.Length -gt 0) {
            return $item.FullName
        }
    }
    return $null
}

function Install-TessdataFile {
    param(
        [Parameter(Mandatory = $true)][string]$Language,
        [string[]]$ExtraDirs = @()
    )
    $file = Join-Path $payloadTessdataDir "$Language.traineddata"
    $cacheFile = Join-Path $tessdataSetCacheDir "$Language.traineddata"
    $localFile = Find-LocalTessdataFile -Language $Language -ExtraDirs $ExtraDirs
    if ($localFile) {
        Write-Host "  CACHE $localFile"
        Copy-Item -LiteralPath $localFile -Destination $file -Force
        if (-not (Resolve-FullPath $localFile).Equals((Resolve-FullPath $cacheFile), [System.StringComparison]::OrdinalIgnoreCase)) {
            New-Item -ItemType Directory -Force -Path $tessdataSetCacheDir | Out-Null
            Copy-Item -LiteralPath $localFile -Destination $cacheFile -Force
        }
        return
    }

    $url = "https://raw.githubusercontent.com/tesseract-ocr/$tessdataRepo/main/$Language.traineddata"
    try {
        Invoke-Download -Uri $url -OutFile $file
        New-Item -ItemType Directory -Force -Path $tessdataSetCacheDir | Out-Null
        Copy-Item -LiteralPath $file -Destination $cacheFile -Force
    } catch {
        Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
        throw "Could not get $Language.traineddata. Put it into $tessdataSetCacheDir and rerun. Source URL: $url. $($_.Exception.Message)"
    }
}

Write-Host "======================================================================"
Write-Host "AUDION OFFICE OCR AI - INSTALL PORTABLE TESSERACT"
Write-Host "======================================================================"
Write-Host "Root:        $rootDir"
Write-Host "Runtime:     $runtimeDir"
Write-Host "Target:      $targetDir"
Write-Host "Version:     $Version"
Write-Host "Tessdata:    $TessdataSet ($tessdataRepo)"
Write-Host "Languages:   $($Languages -join ', ')"
Write-Host "Cache:       $tesseractCacheDir"
Write-Host "Payload:     $payloadCacheDir"
if ($OfflineCacheOnly) {
    Write-Host "Network:     disabled, local cache only"
}
if ($PreferInstaller) {
    Write-Host "Source mode: prefer installer staging"
} else {
    Write-Host "Source mode: local payload/source first, installer only when needed"
}
Write-Host ""

New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
New-Item -ItemType Directory -Force -Path $tesseractCacheDir | Out-Null
New-Item -ItemType Directory -Force -Path $tessdataSetCacheDir | Out-Null
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

Assert-UnderDirectory -Path $targetDir -Parent $runtimeDir
Assert-UnderDirectory -Path $installerStageDir -Parent $runtimeDir
Assert-UnderDirectory -Path $payloadStageDir -Parent $runtimeDir

Remove-OwnedDirectory -Path $installerStageDir -Parent $runtimeDir -Label "stale Tesseract installer staging folder"
Remove-OwnedDirectory -Path $payloadStageDir -Parent $runtimeDir -Label "stale Tesseract payload staging folder"

Write-Host "[1/6] Resolving installer/source..."
$sourceDir = $null
$preferSystemSource = $UseSystemSourceFirst -or (-not $PreferInstaller)
if ($preferSystemSource) {
    $sourceDir = Find-TesseractSourceDir
}

$installerPath = $null
$installerIsLocalFile = $false
if (-not $sourceDir) {
    if ($InstallerUrl -and (Test-Path -LiteralPath $InstallerUrl -PathType Leaf)) {
        $installerPath = Resolve-FullPath $InstallerUrl
        $installerIsLocalFile = $true
        $cachedInfo = Get-InstallerInfoFromPath -FilePath $installerPath
        if ($cachedInfo) {
            $Version = $cachedInfo.Version
        }
    } elseif (-not $InstallerUrl) {
        if ($Version.Trim().ToLowerInvariant() -in @("latest", "current")) {
            if ($OfflineCacheOnly) {
                $cachedInstaller = Find-CachedInstaller
                if (-not $cachedInstaller) {
                    throw "Offline cache mode requires a cached installer in $tesseractCacheDir or $downloadDir."
                }
                $Version = $cachedInstaller.Version
                $installerPath = $cachedInstaller.Path
                $installerIsLocalFile = $true
                Write-Host "      Cached latest: $($cachedInstaller.Name)"
            } else {
                try {
                    $latestInstaller = Resolve-LatestInstaller
                    $Version = $latestInstaller.Version
                    $InstallerUrl = $latestInstaller.Uri
                    Write-Host "      Latest: $($latestInstaller.Name)"
                } catch {
                    $cachedInstaller = Find-CachedInstaller
                    if ($cachedInstaller) {
                        Write-Warning "Could not resolve latest Tesseract installer. Reusing cached $($cachedInstaller.Name). $($_.Exception.Message)"
                        $Version = $cachedInstaller.Version
                        $installerPath = $cachedInstaller.Path
                        $installerIsLocalFile = $true
                    } else {
                        Write-Warning "Could not resolve latest Tesseract installer. Falling back to $fallbackVersion. $($_.Exception.Message)"
                        $Version = $fallbackVersion
                        $InstallerUrl = Get-InstallerUrlForVersion -InstallerVersion $Version
                    }
                }
            }
        } else {
            $InstallerUrl = Get-InstallerUrlForVersion -InstallerVersion $Version
        }
    }

    if (-not $installerIsLocalFile) {
        $installerName = Split-Path -Leaf ([System.Uri]$InstallerUrl).AbsolutePath
        if (-not $installerName) {
            $installerName = "tesseract-ocr-w64-setup-$Version.exe"
        }
        $installerPath = Get-InstallerCachePathForName -InstallerName $installerName
        Write-Host "      Installer: $InstallerUrl"
        Write-Host "      Installer cache: $installerPath"
    } else {
        Write-Host "      Installer: $installerPath"
    }
} else {
    Write-Host "      Installer: not needed; local source found"
}

if ($sourceDir) {
    Write-Host "[2/6] Using local Tesseract source:"
    Write-Host "      $sourceDir"
    Copy-TesseractPayloadWithRetry -SourceDir $sourceDir
}

if (-not (Test-Path -LiteralPath (Join-Path $payloadStageDir "tesseract.exe"))) {
    try {
        if (-not (Test-Path -LiteralPath $installerPath)) {
            Write-Host "[2/6] Downloading Tesseract installer..."
            Invoke-Download -Uri $InstallerUrl -OutFile $installerPath
        } else {
            Write-Host "[2/6] Reusing downloaded installer: $installerPath"
        }

        Write-Host "      Running NSIS installer silently into project staging..."
        Reset-OwnedDirectory -Path $installerStageDir -Parent $runtimeDir -Label "Tesseract installer staging folder"
        $installerArgs = "/S /D=$installerStageDir"
        Invoke-CheckedProcess -FilePath $installerPath -ArgumentList $installerArgs -Label "Tesseract installer"

        $stageExe = Join-Path $installerStageDir "tesseract.exe"
        if (-not (Test-Path -LiteralPath $stageExe)) {
            throw "Installer did not create tesseract.exe in $installerStageDir"
        }

        Write-Host "      Copying installer payload into clean project staging..."
        Copy-TesseractPayload -SourceDir $installerStageDir -DestinationDir $payloadStageDir
    } catch {
        Write-Warning "Installer-based staging failed: $($_.Exception.Message)"
        $sourceDir = Find-TesseractSourceDir
        if ((-not $sourceDir) -and $AllowSystemInstallFallback) {
            Invoke-ElevatedInstaller -FilePath $installerPath
            $sourceDir = Find-TesseractSourceDir
        }
        if (-not $sourceDir) {
            throw "Project-local Tesseract staging failed and no local source was found. A system install is not required; fix the installer error and rerun, or pass -AllowSystemInstallFallback only if you explicitly want a normal Windows install as a fallback."
        }
        Write-Host "      Falling back to installed Tesseract source:"
        Write-Host "      $sourceDir"
        Copy-TesseractPayloadWithRetry -SourceDir $sourceDir
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $payloadStageDir "tesseract.exe"))) {
    throw "Tesseract payload staging did not produce tesseract.exe"
}

Write-Host "[3/6] Installing selected traineddata files..."
New-Item -ItemType Directory -Force -Path $payloadTessdataDir | Out-Null
$tessdataExtraDirs = @()
if ($sourceDir) {
    $tessdataExtraDirs += (Join-Path $sourceDir "tessdata")
}
$installerStageTessdataDir = Join-Path $installerStageDir "tessdata"
if (Test-Path -LiteralPath $installerStageTessdataDir) {
    $tessdataExtraDirs += $installerStageTessdataDir
}
if (Test-Path -LiteralPath $targetTessdataDir) {
    $tessdataExtraDirs += $targetTessdataDir
}
foreach ($lang in $Languages) {
    Install-TessdataFile -Language $lang -ExtraDirs $tessdataExtraDirs
}

Write-Host "[4/6] Saving license files..."
Save-LicenseFile -Uri "https://raw.githubusercontent.com/tesseract-ocr/tesseract/main/LICENSE" -OutFile (Join-Path $payloadStageDir "LICENSE-Tesseract-OCR.txt")
Save-LicenseFile -Uri "https://raw.githubusercontent.com/tesseract-ocr/$tessdataRepo/main/LICENSE" -OutFile (Join-Path $payloadStageDir "LICENSE-$tessdataRepo.txt")

Write-Host "[5/6] Replacing project-local portable Tesseract..."
if (Test-Path -LiteralPath $targetDir) {
    Write-Host "      Removing previous copy: $targetDir"
    Remove-OwnedDirectory -Path $targetDir -Parent $runtimeDir -Label "previous portable Tesseract"
}
Move-Item -LiteralPath $payloadStageDir -Destination $targetDir

if (Test-Path -LiteralPath $installerStageDir) {
    Remove-OwnedDirectory -Path $installerStageDir -Parent $runtimeDir -Label "Tesseract installer staging folder"
}

Write-Host "[6/6] Verifying portable Tesseract..."
$tesseractExe = Join-Path $targetDir "tesseract.exe"
$env:TESSDATA_PREFIX = $targetTessdataDir
$versionOutput = & $tesseractExe --version 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "tesseract --version failed"
}
$langOutput = & $tesseractExe --list-langs --tessdata-dir $targetTessdataDir 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "tesseract --list-langs failed"
}

$available = @($langOutput | Where-Object { $_ -and ($_ -notmatch '^List of available languages') })
foreach ($lang in $Languages) {
    if ($available -notcontains $lang) {
        throw "Tesseract language is missing after install: $lang"
    }
}

Write-Host ""
Write-Host "[OK] Portable Tesseract installed."
Write-Host "     $tesseractExe"
Write-Host "     $($versionOutput | Select-Object -First 1)"
Write-Host "     Languages: $($available -join ', ')"
if ($installerPath) {
    Write-Host "     Installer cache: $installerPath"
}
