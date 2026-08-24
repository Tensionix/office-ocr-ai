param(
    [string]$Version = "latest",
    [string]$TargetDir = "",
    [switch]$Force,
    [switch]$OfflineCacheOnly
)

$ErrorActionPreference = "Stop"

$installDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $installDir
$downloadDir = Join-Path $installDir "download"
$cacheDir = Join-Path $downloadDir "realesrgan-ncnn-vulkan"
$toolsDir = Join-Path $rootDir "tools"
if (-not $TargetDir) {
    $TargetDir = Join-Path $toolsDir "realesrgan-ncnn-vulkan"
}
$stageDir = Join-Path $toolsDir "_realesrgan-ncnn-vulkan_stage"
$repo = "xinntao/Real-ESRGAN"
$repoApi = "https://api.github.com/repos/$repo"
$licenseUrl = "https://raw.githubusercontent.com/xinntao/Real-ESRGAN/master/LICENSE"
$headers = @{ "User-Agent" = "AudionOfficeOCRAI-RealESRGAN-Installer" }

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
    if ($fullPath -ne $fullParent -and -not $fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
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
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
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

function Find-WindowsAsset {
    param([Parameter(Mandatory = $true)]$Release)
    return @($Release.assets | Where-Object {
        $_.name -match '^realesrgan-ncnn-vulkan-.+-windows\.zip$'
    } | Select-Object -First 1)
}

function Resolve-Release {
    if ($Version -and $Version -ne "latest") {
        $tag = $Version
        if (-not $tag.StartsWith("v")) {
            $tag = "v$tag"
        }
        Write-Host "Resolving Real-ESRGAN release $tag..."
        $release = Invoke-RestMethod -Headers $headers -Uri "$repoApi/releases/tags/$tag"
        $asset = Find-WindowsAsset -Release $release
        if (-not $asset) {
            throw "Release $tag does not contain a Windows realesrgan-ncnn-vulkan zip asset."
        }
        return [pscustomobject]@{ Release = $release; Asset = $asset }
    }

    Write-Host "Resolving latest Real-ESRGAN release with Windows ncnn-vulkan asset..."
    $releases = Invoke-RestMethod -Headers $headers -Uri "$repoApi/releases"
    foreach ($release in $releases) {
        $asset = Find-WindowsAsset -Release $release
        if ($asset) {
            return [pscustomobject]@{ Release = $release; Asset = $asset }
        }
    }
    throw "No Windows realesrgan-ncnn-vulkan zip asset was found in $repo releases."
}

function Read-Manifest {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Test-Executable {
    param([Parameter(Mandatory = $true)][string]$ExePath)
    Write-Host "Checking executable..."
    $output = & $ExePath "-h" 2>&1 | Select-Object -First 8
    foreach ($line in $output) {
        Write-Host "  $line"
    }
}

New-Item -ItemType Directory -Force -Path $cacheDir, $toolsDir | Out-Null
$resolvedTarget = Resolve-FullPath $TargetDir
Assert-UnderDirectory -Path $resolvedTarget -Parent $toolsDir

$selection = Resolve-Release
$release = $selection.Release
$asset = $selection.Asset
$zipPath = Join-Path $cacheDir $asset.name
$manifestPath = Join-Path $resolvedTarget "realesrgan-tool.json"
$installed = Read-Manifest -Path $manifestPath
$exePath = Join-Path $resolvedTarget "realesrgan-ncnn-vulkan.exe"

if (
    -not $Force -and
    (Test-Path -LiteralPath $exePath) -and
    $installed -and
    $installed.release_tag -eq $release.tag_name -and
    $installed.asset_name -eq $asset.name
) {
    Write-Host "Real-ESRGAN ncnn-vulkan is already installed: $resolvedTarget"
    Write-Host "Version: $($installed.release_tag), asset: $($installed.asset_name)"
    Test-Executable -ExePath $exePath
    exit 0
}

if (Test-Path -LiteralPath $zipPath) {
    Write-Host "Using cached asset: $zipPath"
} else {
    Invoke-Download -Uri $asset.browser_download_url -OutFile $zipPath
}

Write-Host "Validating zip asset..."
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $exeEntry = $zip.Entries | Where-Object { $_.FullName -match '(^|/)realesrgan-ncnn-vulkan\.exe$' } | Select-Object -First 1
    if (-not $exeEntry) {
        throw "Zip does not contain realesrgan-ncnn-vulkan.exe: $zipPath"
    }
} finally {
    $zip.Dispose()
}

Remove-OwnedDirectory -Path $stageDir -Parent $toolsDir -Label "Real-ESRGAN stage"
New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
Write-Host "Extracting: $zipPath"
Expand-Archive -LiteralPath $zipPath -DestinationPath $stageDir -Force

$stageExe = Get-ChildItem -LiteralPath $stageDir -Recurse -Filter "realesrgan-ncnn-vulkan.exe" -File |
    Select-Object -First 1
if (-not $stageExe) {
    throw "Extracted payload does not contain realesrgan-ncnn-vulkan.exe."
}
$payloadRoot = $stageExe.Directory.FullName

Remove-OwnedDirectory -Path $resolvedTarget -Parent $toolsDir -Label "Real-ESRGAN target"
New-Item -ItemType Directory -Force -Path $resolvedTarget | Out-Null
Write-Host "Installing to: $resolvedTarget"
Get-ChildItem -LiteralPath $payloadRoot -Force | Copy-Item -Destination $resolvedTarget -Recurse -Force

$licensePath = Join-Path $resolvedTarget "LICENSE-Real-ESRGAN.txt"
try {
    Invoke-Download -Uri $licenseUrl -OutFile $licensePath
} catch {
    $licensePath = Join-Path $resolvedTarget "LICENSE-AGREEMENT.txt"
    @"
Real-ESRGAN ncnn-vulkan third-party license notice

The installer could not download the upstream LICENSE file automatically.
Please review the official license before using this tool:
https://github.com/xinntao/Real-ESRGAN/blob/master/LICENSE

Source repository:
https://github.com/xinntao/Real-ESRGAN
"@ | Set-Content -LiteralPath $licensePath -Encoding UTF8
}

$agreementPath = Join-Path $resolvedTarget "LICENSE-AGREEMENT.txt"
@"
Real-ESRGAN ncnn-vulkan portable binary

Source repository: https://github.com/xinntao/Real-ESRGAN
Release: $($release.tag_name)
Asset: $($asset.name)

This is a third-party portable tool used by Audion Office OCR AI for optional
image super-resolution preprocessing. Review LICENSE-Real-ESRGAN.txt before
redistributing or using the binary outside this local installation.
"@ | Set-Content -LiteralPath $agreementPath -Encoding UTF8

$installedExe = Join-Path $resolvedTarget "realesrgan-ncnn-vulkan.exe"
if (-not (Test-Path -LiteralPath $installedExe)) {
    throw "Install failed: executable not found at $installedExe"
}
Test-Executable -ExePath $installedExe

$manifest = [ordered]@{
    tool = "realesrgan-ncnn-vulkan"
    source_repository = "https://github.com/$repo"
    release_tag = $release.tag_name
    release_name = $release.name
    published_at = $release.published_at
    asset_name = $asset.name
    asset_url = $asset.browser_download_url
    asset_size = $asset.size
    installed_at = (Get-Date).ToString("s")
    install_dir = $resolvedTarget
    executable = $installedExe
    license_file = $licensePath
    agreement_file = $agreementPath
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Remove-OwnedDirectory -Path $stageDir -Parent $toolsDir -Label "Real-ESRGAN stage"

Write-Host ""
Write-Host "[OK] Real-ESRGAN ncnn-vulkan installed."
Write-Host "     Version: $($release.tag_name)"
Write-Host "     Exe: $installedExe"
Write-Host "     License: $licensePath"
Write-Host "     Manifest: $manifestPath"
