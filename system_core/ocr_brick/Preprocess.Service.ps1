# Preprocess.Service.ps1
# Lifecycle wrapper for the warm preprocess service. Holy trinity + -Clear.
# Conventions: EN output only; find portable python (do not hardcode);
# all paths from $PSScriptRoot (never CWD); list-based invocation.
# 15-point .cmd checklist applies to any launcher that wraps this.

param(
    [switch]$Status,
    [switch]$Enable,
    [switch]$Disable,
    [switch]$Clear
)

$ErrorActionPreference = "Stop"
$Root        = $PSScriptRoot
$ProjectRoot = Split-Path (Split-Path $Root -Parent) -Parent
$Port        = 8770
$Module      = "system_core.ocr_brick.preprocess_service"
$Cache       = Join-Path $Root "cache"

function Find-Python {
    # Prefer a portable runtime shipped with the brick; fall back to PATH.
    $candidates = @(
        (Join-Path $ProjectRoot "runtime\python.exe"),
        (Join-Path $ProjectRoot "runtime\python\python.exe")
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return (Resolve-Path $c).Path } }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Test-Up {
    try { return (Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2).ok }
    catch { return $false }
}

if ($Status) {
    if (Test-Up) { "RUNNING on $Port" } else { "STOPPED" }
    if (Test-Path $Cache) {
        $files = Get-ChildItem $Cache -Recurse -File -ErrorAction SilentlyContinue
        $bytes = ($files | Measure-Object Length -Sum).Sum
        "CACHE: {0:N0} files, {1:N2} GB" -f $files.Count, ($bytes / 1GB)
    } else {
        "CACHE: empty"
    }
    return
}

if ($Enable) {
    $py = Find-Python
    if (-not $py)            { "ERROR: no python runtime found (portable or PATH)"; exit 1 }
    $bootstrap = "import runpy, sys; sys.path.insert(0, r'$ProjectRoot'); runpy.run_module('$Module', run_name='__main__')"
    Start-Process -FilePath $py -ArgumentList @("-c", $bootstrap, "--port", $Port) -WorkingDirectory $ProjectRoot -WindowStyle Hidden
    "ENABLED (port $Port)"
    return
}

if ($Disable) {
    Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%system_core.ocr_brick.preprocess_service%'" |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    "DISABLED"
    return
}

if ($Clear) {
    if (Test-Path $Cache) {
        Remove-Item (Join-Path $Cache "*") -Recurse -Force -ErrorAction SilentlyContinue
    }
    "CACHE cleared"
    return
}

"Usage: -Status | -Enable | -Disable | -Clear"
