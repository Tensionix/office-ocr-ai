param(
    [ValidateSet("surya")]
    [string]$Engine = "surya",
    [ValidateSet("cpu", "cuda", "cuda40", "cuda50")]
    [string]$Mode = "cpu",
    [string]$TorchIndexUrl = "",
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$installDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $installDir
$baseRuntimeDir = Join-Path $rootDir "runtime"
$requirementsFile = Join-Path $installDir "requirements_full.in"
$toolsDir = Join-Path $rootDir "tools"
$optionalRoot = Join-Path $toolsDir "optional-ocr-engines"
$noticePath = Join-Path $optionalRoot "INSTALL-NOTES.txt"

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
        if ($DryRun) {
            Write-Host "[DRY-RUN] remove $Label`: $Path"
            return
        }
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Get-BasePython {
    $python = Join-Path $baseRuntimeDir "python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Portable runtime was not found: $python. Build it from install\requirements_full.in first."
    }
    return (Resolve-Path -LiteralPath $python).Path
}

function Invoke-Pip {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string[]]$Args
    )
    $display = "$Python -m pip " + ($Args -join " ")
    if ($DryRun) {
        Write-Host "[DRY-RUN] $display"
        return
    }
    Write-Host "[PIP] $display"
    & $Python -m pip @Args
    if ($LASTEXITCODE -ne 0) {
        throw "pip failed with exit code $LASTEXITCODE"
    }
}

function Get-ResolvedTorchIndexUrl {
    if ($TorchIndexUrl) {
        return $TorchIndexUrl
    }
    switch ($Mode) {
        "cuda" { return "https://download.pytorch.org/whl/cu128" }
        "cuda40" { return "https://download.pytorch.org/whl/cu128" }
        "cuda50" { return "https://download.pytorch.org/whl/cu128" }
        default { return "" }
    }
}

function Copy-PortableRuntime {
    param([Parameter(Mandatory = $true)][string]$Name)

    Get-BasePython | Out-Null
    if (-not (Test-Path -LiteralPath $requirementsFile)) {
        throw "Missing base requirements file: $requirementsFile"
    }

    New-Item -ItemType Directory -Force -Path $optionalRoot | Out-Null
    Assert-UnderDirectory -Path $optionalRoot -Parent $toolsDir

    $componentDir = Join-Path $optionalRoot $Name
    $runtimeDir = Join-Path $componentDir "runtime"
    $stageDir = Join-Path $optionalRoot "_${Name}_stage"
    Assert-UnderDirectory -Path $componentDir -Parent $optionalRoot
    Assert-UnderDirectory -Path $stageDir -Parent $optionalRoot

    if ((Test-Path -LiteralPath $runtimeDir) -and -not $Force) {
        Write-Host "Using existing optional runtime: $runtimeDir"
        return $runtimeDir
    }

    Write-Host "Creating portable optional runtime: $runtimeDir"
    Remove-OwnedDirectory -Path $stageDir -Parent $optionalRoot -Label "$Name stage"
    Remove-OwnedDirectory -Path $componentDir -Parent $optionalRoot -Label "$Name target"

    if ($DryRun) {
        Write-Host "[DRY-RUN] copy $baseRuntimeDir -> $runtimeDir"
        return $runtimeDir
    }

    New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
    $stageRuntime = Join-Path $stageDir "runtime"
    New-Item -ItemType Directory -Force -Path $stageRuntime | Out-Null

    $excludedTopLevel = @(".playwright", "tesseract", "testing")
    Get-ChildItem -LiteralPath $baseRuntimeDir -Force | ForEach-Object {
        if ($excludedTopLevel -contains $_.Name) {
            return
        }
        Copy-Item -LiteralPath $_.FullName -Destination $stageRuntime -Recurse -Force
    }

    New-Item -ItemType Directory -Force -Path $componentDir | Out-Null
    Move-Item -LiteralPath $stageRuntime -Destination $runtimeDir
    Remove-OwnedDirectory -Path $stageDir -Parent $optionalRoot -Label "$Name stage"
    Copy-Item -LiteralPath $requirementsFile -Destination (Join-Path $componentDir "BASE-requirements_full.in") -Force
    return $runtimeDir
}

function Get-OptionalPython {
    param([Parameter(Mandatory = $true)][string]$RuntimeDir)
    $python = Join-Path $RuntimeDir "python.exe"
    if ($DryRun) {
        return $python
    }
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Optional portable Python was not created: $python"
    }
    return (Resolve-Path -LiteralPath $python).Path
}

function Write-Manifest {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$RuntimeDir,
        [Parameter(Mandatory = $true)][string[]]$Packages,
        [Parameter(Mandatory = $true)][string[]]$Notes
    )
    if ($DryRun) { return }
    $componentDir = Split-Path -Parent $RuntimeDir
    $manifestPath = Join-Path $componentDir "optional-runtime.json"
    $manifest = [ordered]@{
        name = $Name
        mode = $Mode
        runtime = "runtime"
        base_requirements = "BASE-requirements_full.in"
        packages = $Packages
        notes = $Notes
        installed_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    }
    ($manifest | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $manifestPath -Encoding UTF8
}

function Install-Surya {
    Write-Host "Installing optional portable Surya OCR/layout runtime..."
    $runtimeDir = Copy-PortableRuntime -Name "surya"
    $python = Get-OptionalPython -RuntimeDir $runtimeDir

    Invoke-Pip -Python $python -Args @("install", "--disable-pip-version-check", "--upgrade", "pip", "setuptools", "wheel", "packaging")
    $resolvedTorchIndexUrl = Get-ResolvedTorchIndexUrl
    if ($Mode -in @("cuda", "cuda40", "cuda50") -and $resolvedTorchIndexUrl) {
        Write-Host "Installing PyTorch CUDA wheels for $Mode from $resolvedTorchIndexUrl"
        Invoke-Pip -Python $python -Args @("install", "--disable-pip-version-check", "--upgrade", "torch", "torchvision", "--index-url", $resolvedTorchIndexUrl)
    }
    Invoke-Pip -Python $python -Args @("install", "--disable-pip-version-check", "--upgrade", "surya-ocr")
    $packages = @("surya-ocr")
    if ($resolvedTorchIndexUrl) {
        $packages += "torch"
        $packages += "torchvision"
    }
    Write-Manifest -Name "surya" -RuntimeDir $runtimeDir -Packages $packages -Notes @(
        "Surya 0.20+ uses an inference backend: llama.cpp for CPU or vLLM/Docker for NVIDIA GPU.",
        "CPU mode needs llama-server available to the optional runtime via LLAMA_CPP_BINARY or PATH.",
        "CUDA modes install PyTorch CUDA wheels only inside this optional runtime.",
        "The core project runtime is not modified by this optional payload."
    )
}

$basePython = Get-BasePython
Write-Host "Base portable Python: $basePython"
Write-Host "Base requirements: $requirementsFile"
Write-Host "Optional root: $optionalRoot"
Write-Host "Engine: $Engine"
Write-Host "Mode: $Mode"

if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $optionalRoot | Out-Null
    @"
Optional OCR Engines

This folder contains explicit optional portable payloads for heavy OCR/layout
engines. Each engine owns its own copied embedded Python runtime under:

  tools\optional-ocr-engines\<engine>\runtime

The core runtime is built from install\requirements_full.in and must not be
mutated by Surya installs.

Installed/checked at: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Requested engine: $Engine
Requested mode: $Mode
"@ | Set-Content -LiteralPath $noticePath -Encoding UTF8
}

Install-Surya

Write-Host "Optional OCR engine install command completed."
Write-Host "Run Project tools -> OCR Brick status to verify optional runtimes."
