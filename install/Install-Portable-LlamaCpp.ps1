param(
    [ValidateSet("vulkan", "cpu", "cuda124", "cuda133")]
    [string]$Variant = "vulkan",
    [string]$Version = "latest",
    [string]$TargetDir = "",
    [switch]$Force,
    [switch]$OfflineCacheOnly
)

$ErrorActionPreference = "Stop"

$installDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $installDir
$downloadDir = Join-Path $installDir "download"
$cacheDir = Join-Path $downloadDir "llama.cpp"
$toolsDir = Join-Path $rootDir "tools"
if (-not $TargetDir) {
    $TargetDir = Join-Path $toolsDir "llama.cpp"
}
$stageDir = Join-Path $toolsDir "_llama.cpp_stage"
$repo = "ggml-org/llama.cpp"
$repoApi = "https://api.github.com/repos/$repo"
$licenseUrl = "https://raw.githubusercontent.com/ggml-org/llama.cpp/master/LICENSE"
$headers = @{ "User-Agent" = "AudionOfficeOCRAI-LlamaCpp-Installer" }

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
    $pattern = switch ($Variant) {
        "cpu" { '^llama-.+-bin-win-cpu-x64\.zip$' }
        "cuda124" { '^llama-.+-bin-win-cuda-12\.4-x64\.zip$' }
        "cuda133" { '^llama-.+-bin-win-cuda-13\.3-x64\.zip$' }
        default { '^llama-.+-bin-win-vulkan-x64\.zip$' }
    }
    return @($Release.assets | Where-Object { $_.name -match $pattern } | Select-Object -First 1)
}

function Resolve-Release {
    if ($Version -and $Version -ne "latest") {
        $tag = $Version
        Write-Host "Resolving llama.cpp release $tag..."
        $release = Invoke-RestMethod -Headers $headers -Uri "$repoApi/releases/tags/$tag"
        $asset = Find-WindowsAsset -Release $release
        if (-not $asset) {
            throw "Release $tag does not contain a Windows $Variant llama.cpp zip asset."
        }
        return [pscustomobject]@{ Release = $release; Asset = $asset }
    }

    Write-Host "Resolving latest llama.cpp release with Windows $Variant asset..."
    $release = Invoke-RestMethod -Headers $headers -Uri "$repoApi/releases/latest"
    $asset = Find-WindowsAsset -Release $release
    if (-not $asset) {
        throw "Latest llama.cpp release does not contain a Windows $Variant zip asset."
    }
    return [pscustomobject]@{ Release = $release; Asset = $asset }
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
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $ExePath "--version" 2>&1 | Select-Object -First 6
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
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
$manifestPath = Join-Path $resolvedTarget "llama-cpp-tool.json"
$installed = Read-Manifest -Path $manifestPath
$exePath = Join-Path $resolvedTarget "llama-server.exe"

if (
    -not $Force -and
    (Test-Path -LiteralPath $exePath) -and
    $installed -and
    $installed.release_tag -eq $release.tag_name -and
    $installed.asset_name -eq $asset.name -and
    $installed.variant -eq $Variant
) {
    Write-Host "llama.cpp is already installed: $resolvedTarget"
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
    $exeEntry = $zip.Entries | Where-Object { $_.FullName -match '(^|/)llama-server\.exe$' } | Select-Object -First 1
    if (-not $exeEntry) {
        throw "Zip does not contain llama-server.exe: $zipPath"
    }
} finally {
    $zip.Dispose()
}

Remove-OwnedDirectory -Path $stageDir -Parent $toolsDir -Label "llama.cpp stage"
New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
Write-Host "Extracting: $zipPath"
Expand-Archive -LiteralPath $zipPath -DestinationPath $stageDir -Force

$stageExe = Get-ChildItem -LiteralPath $stageDir -Recurse -Filter "llama-server.exe" -File |
    Select-Object -First 1
if (-not $stageExe) {
    throw "Extracted payload does not contain llama-server.exe."
}
$payloadRoot = $stageExe.Directory.FullName

Remove-OwnedDirectory -Path $resolvedTarget -Parent $toolsDir -Label "llama.cpp target"
New-Item -ItemType Directory -Force -Path $resolvedTarget | Out-Null
Write-Host "Installing to: $resolvedTarget"
Get-ChildItem -LiteralPath $payloadRoot -Force | Copy-Item -Destination $resolvedTarget -Recurse -Force
Remove-OwnedDirectory -Path $stageDir -Parent $toolsDir -Label "llama.cpp stage"

$licensePath = Join-Path $resolvedTarget "LICENSE-llama.cpp.txt"
try {
    Invoke-WebRequest -Headers $headers -Uri $licenseUrl -OutFile $licensePath -UseBasicParsing
} catch {
    "llama.cpp license: https://github.com/ggml-org/llama.cpp/blob/master/LICENSE" |
        Set-Content -LiteralPath $licensePath -Encoding UTF8
}

$manifest = [ordered]@{
    repo = $repo
    release_tag = $release.tag_name
    asset_name = $asset.name
    asset_url = $asset.browser_download_url
    variant = $Variant
    installed_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    exe = "llama-server.exe"
}
($manifest | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Test-Executable -ExePath $exePath
Write-Host "Portable llama.cpp installed."
