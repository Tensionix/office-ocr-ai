# Layout.Service.ps1
# Lifecycle wrapper for the warm layout service (Surya hosted once).
# Holy trinity. EN output only; portable python; paths from $PSScriptRoot.

param(
    [switch]$Status,
    [switch]$Enable,
    [switch]$Disable
)

$ErrorActionPreference = "Stop"
$Root        = $PSScriptRoot
$ProjectRoot = Split-Path (Split-Path $Root -Parent) -Parent
$Port        = 8771
$Module      = "system_core.ocr_brick.layout_service"

function Find-Python {
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
    if (Test-Up) {
        $h = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2
        "RUNNING on $Port; warm engines: " + ($h.warm_engines -join ", ")
    } else { "STOPPED" }
    return
}

if ($Enable) {
    $py = Find-Python
    if (-not $py)                 { "ERROR: no python runtime found (portable or PATH)"; exit 1 }
    $bootstrap = "import runpy, sys; sys.path.insert(0, r'$ProjectRoot'); runpy.run_module('$Module', run_name='__main__')"
    Start-Process -FilePath $py -ArgumentList @("-c", $bootstrap, "--port", $Port, "--root", $ProjectRoot) -WorkingDirectory $ProjectRoot -WindowStyle Hidden
    "ENABLED (port $Port)"
    return
}

if ($Disable) {
    Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%system_core.ocr_brick.layout_service%'" |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    "DISABLED"
    return
}

"Usage: -Status | -Enable | -Disable"
