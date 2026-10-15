# The built program walked through without a mouse: its own buttons are pressed by UI Automation.
#
#   Source\Tools\release-walk.ps1 -Stand C:\Temp\ocr_stand
#
# A release build has no steps of a check inside, so the stand is a copy of the program: App\, the
# console command, the engine and config\ without the files of the owner - the keys of the
# providers, the history of paths, the look of the window. The Python of the project is the
# program's own runtime\, reached by a link (1.4 GB is not copied). The input, output, logs and
# report of the stand are its own - nothing of the owner's is read or written. The files it works
# on are made by its own Python (Source\Tools\walk_fixtures.py). The window is started with
# AUDION_WALK=1: it and its questions stand off every screen and take no focus. It is found by the
# id of its process, never by its name or title; the pointer is not moved.
#
# What is pressed - free operations only, no provider is asked and no key is used:
#   SETUP in the header (the page comes up, nothing is installed); TOOLS, To Markdown (an office
#   document into Markdown); LOCAL OCR with Tesseract; Workbench - the local
#   review and the coordinates; the rebuild of Markdown into DOCX, LLM-DOCX and PPTX; TABLES - XLSX,
#   the check of the tables, the coordinate tables; a key added and set aside (a made-up
#   key, into the config of the stand); the operation of the folders and the clearing of the
#   DocumentModel artifacts; CLEAR with its menu and its question; STOP while OCR goes; the window
#   closed while OCR goes. Not pressed: the resolvers of Workbench and Gemini Batch (they send pages
#   to a provider and cost money), "Build PDF" (it drives Microsoft Word).
#
# Exit code 0 - every check held; 1 - one did not, and the line says which. A check that fails for a
# fault the engine is known to have says [KNOWN] and does not fail the walk.
#
# Needs a PowerShell with the WindowsDesktop assemblies (an installed PowerShell 7).
# -Keep leaves the stand in place for a look; otherwise it is removed at the end.
# -Only markdown,ocr,workbench,rebuild,tables,key,folders,clear,stop,close - the parts to walk; all by default.
param(
    [Parameter(Mandatory)][string]$Stand,
    # The built window to walk: App\ of the program, or another build of it.
    [string]$App = '',
    [switch]$Keep,
    [string[]]$Only = @()
)
function Part([string]$name) { return $Only.Count -eq 0 -or $Only -contains $name }
$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $PSScriptRoot
$project = Split-Path -Parent $source
$window = 'AudionOfficeOcrAi.exe'
if (-not $App) { $App = Join-Path $project 'App' }

if (Test-Path -LiteralPath $Stand) { "the stand must not exist yet: $Stand"; exit 2 }
if (-not (Test-Path -LiteralPath (Join-Path $App $window))) { "no built window in $App`: install\Build-App.cmd"; exit 2 }
if (-not (Test-Path -LiteralPath (Join-Path $project 'runtime\python.exe'))) { "no Python of the project: builder_main.cmd"; exit 2 }
[void](New-Item -ItemType Directory -Force -Path $Stand)
$Stand = (Resolve-Path -LiteralPath $Stand).Path
# The files of the owner stay home: the keys of the providers, the history of paths, the look of the window.
$private = @('window_settings.json*', 'path_history.json*', 'api_key_*.txt', 'api_*.txt', 'yandex_*.txt')
$copies = @(
    @($App, 'App', @()),
    @((Join-Path $project 'system_core'), 'system_core', @('__pycache__', 'powershell')),
    @((Join-Path $project 'config'), 'config', @('keys', 'deleted_keys'))
)
foreach ($copy in $copies) {
    $skip = @('/XD') + $copy[2] + @('/XF') + $private
    $null = robocopy $copy[0] (Join-Path $Stand $copy[1]) /E @skip /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { "the copy of $($copy[1]) failed"; exit 2 }
}
Copy-Item -LiteralPath (Join-Path $project 'ocr_cli.cmd') -Destination $Stand
$runtime = Join-Path $Stand 'runtime'
[void](New-Item -ItemType Junction -Path $runtime -Target (Join-Path $project 'runtime'))
$in = Join-Path $Stand 'input'; $out = Join-Path $Stand 'output'; $report = Join-Path $Stand 'report'
foreach ($name in 'input', 'output', 'logs', 'report', 'workspace', 'data') { [void](New-Item -ItemType Directory -Force -Path (Join-Path $Stand $name)) }
$exe = Join-Path $Stand "App\$window"
$python = Join-Path $runtime 'python.exe'
$fixtures = Join-Path $PSScriptRoot 'walk_fixtures.py'

function Fixture([string]$kind, [int]$count = 1, [string]$folder = $in) {
    & $python -I $fixtures $folder $kind $count
    if ($LASTEXITCODE -ne 0) { throw "the files of the stand were not made: $kind" }
}
function FilesIn([string]$folder, [string]$filter = '*') { @(Get-ChildItem -LiteralPath $folder -Recurse -File -Force -Filter $filter -ErrorAction SilentlyContinue) }
function Fresh {
    # Each step begins with its own files: input and output of the stand are emptied by the walk itself.
    foreach ($folder in $in, $out) { Get-ChildItem -LiteralPath $folder -Force | Remove-Item -Recurse -Force }
}

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$auto = [System.Windows.Automation.AutomationElement]
$failed = 0
function Say([bool]$ok, [string]$what) {
    '{0} {1}' -f $(if ($ok) { '[OK]  ' } else { '[FAIL]' }), $what
    if (-not $ok) { $script:failed++ }
}
function Known([bool]$ok, [string]$what) {
    '{0} {1}' -f $(if ($ok) { '[OK]  ' } else { '[KNOWN]' }), $what
}
function Find($root, [string]$id, [int]$seconds = 20) {
    $condition = [System.Windows.Automation.PropertyCondition]::new($auto::AutomationIdProperty, $id)
    $until = (Get-Date).AddSeconds($seconds)
    do {
        # The tree may be rebuilt under the search - a section was just pressed - and the search
        # then breaks instead of finding nothing: asked again like any other "not yet".
        $found = $null
        try { $found = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition) } catch { }
        if ($found) { return $found }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $until)
    return $null
}
function Press($element) {
    if ($null -eq $element) { throw 'nothing to press' }
    $pattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) { $pattern.Invoke(); return }
    if ($element.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) { $pattern.Toggle(); return }
    if ($element.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$pattern)) { $pattern.Expand(); return }
    throw 'the element can be neither invoked nor toggled'
}
function IsOn($element) {
    $pattern = $null
    if (-not $element.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) { return $false }
    return $pattern.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On
}
function TextOf($root, [string]$id) {
    $found = Find $root $id 5
    if (-not $found) { return '' }
    $value = $null
    if ($found.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$value)) { return $value.Current.Value }
    return $found.Current.Name
}
function Ids($root, [string]$part) {
    # The automation ids in the window that hold a word: what a walk saw when a control it looked for was not there.
    try {
        $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
        return (@($all | ForEach-Object { $_.Current.AutomationId } | Where-Object { $_ -and $_ -like "*$part*" }) | Select-Object -Unique) -join ' '
    }
    catch { return "(the tree was not read: $($_.Exception.Message))" }
}
function Shown($root, [string]$id) {
    # One look, no waiting: a control that is hidden is not in the tree at all.
    try { return $null -ne $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.PropertyCondition]::new($auto::AutomationIdProperty, $id)) }
    catch { return $false }
}
function Outcome($root) {
    # How a run ended is read from the status line, in either language; a run that goes - from STOP, in sight only then.
    $line = TextOf $root 'StatusText'
    if ($line -match '^(Готово|Done): ') { return 'done' }
    if ($line -match '^(Остановлено|Stopped): ') { return 'stopped' }
    if ($line -match ': (отказ до начала|refused before it began)') { return 'refused' }
    if ($line -match ': (ошибка|failed) - ') { return 'failed' }
    if (Shown $root 'stop') { return 'running' }
    return ''
}
function WaitOutcome($root, [string[]]$wanted, [int]$seconds, [string]$before = '') {
    # $before: the status line before the press - an outcome of the run before is not this run's.
    $until = (Get-Date).AddSeconds($seconds)
    do {
        $now = Outcome $root
        if ($wanted -contains $now -and ($now -eq 'running' -or (TextOf $root 'StatusText') -ne $before)) { return $now }
        Start-Sleep -Milliseconds 400
    } while ((Get-Date) -lt $until)
    return "$(Outcome $root) <$(TextOf $root 'StatusText')>"
}
function FindInProcess([int]$id, [string]$name, [int]$seconds = 15) {
    # A question is a window of its own: looked for among the windows of the process, not inside the main one.
    $mine = [System.Windows.Automation.PropertyCondition]::new($auto::ProcessIdProperty, $id)
    $named = [System.Windows.Automation.PropertyCondition]::new($auto::AutomationIdProperty, $name)
    $until = (Get-Date).AddSeconds($seconds)
    do {
        try {
            foreach ($top in $auto::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $mine)) {
                $found = $top.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $named)
                if ($found) { return $found }
            }
        }
        catch { }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $until)
    return $null
}
function AnswerYes([int]$id, [int]$seconds = 30) {
    # "Yes" of a question that cannot be taken back comes alive a moment after it opens.
    $yes = FindInProcess $id 'AskYes' $seconds
    if (-not $yes) { return $false }
    $until = (Get-Date).AddSeconds(5)
    while (-not $yes.Current.IsEnabled -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 100 }
    Press $yes
    Start-Sleep -Milliseconds 500
    return $true
}
function StartWindow {
    $env:AUDION_WALK = '1'
    try { $process = Start-Process -FilePath $exe -PassThru }
    finally { Remove-Item Env:\AUDION_WALK -ErrorAction SilentlyContinue }
    # A window with no button on the taskbar is no "main window" to .NET: it is looked for among the
    # windows of the desktop by the id of its process.
    $mine = [System.Windows.Automation.PropertyCondition]::new($auto::ProcessIdProperty, $process.Id)
    $until = (Get-Date).AddSeconds(40)
    do {
        $found = $null
        try { $found = $auto::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $mine) } catch { }
        if ($found) { $script:root = $found; return $process }
        Start-Sleep -Milliseconds 300
    } while (-not $process.HasExited -and (Get-Date) -lt $until)
    throw $(if ($process.HasExited) { "the window ended at its start, exit code $($process.ExitCode)" } else { 'the window did not open' })
}
function CloseWindow($root) {
    $close = $null
    [void]$root.TryGetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern, [ref]$close)
    $close.Close()
}
function Open([string]$section, [string]$page = '', [string]$choice = '') {
    # A section, then a page of it, then a switch over its form - each pressed only when it is not on yet.
    $tab = Find $root "section_$section"
    if (-not (IsOn $tab)) { Press $tab; Start-Sleep -Milliseconds 700 }
    if ($page) {
        $switch = Find $root "page_${section}_$page" 5
        if ($switch -and -not (IsOn $switch)) { Press $switch; Start-Sleep -Milliseconds 700 }
    }
    if ($choice) {
        $switch = Find $root "choice_$choice" 10
        if ($switch -and -not (IsOn $switch)) { Press $switch; Start-Sleep -Milliseconds 900 }
    }
}
function Run([string]$operation, [int]$seconds) {
    # A run pressed by its own button and waited for to its end; what the status line said of it.
    # The page is built again after a run ends: a button found before may be gone - it is looked for afresh until it takes the press.
    $before = TextOf $root 'StatusText'
    $until = (Get-Date).AddSeconds(20)
    $pressed = $false
    while (-not $pressed -and (Get-Date) -lt $until) {
        $button = Find $root "run_$operation" 5
        try {
            if ($button -and $button.Current.IsEnabled) { Press $button; $pressed = $true }
        }
        catch { }
        if (-not $pressed) { Start-Sleep -Milliseconds 400 }
    }
    if (-not $pressed) { return 'no button to press' }
    return WaitOutcome $root @('done', 'stopped', 'refused', 'failed') $seconds $before
}

try {
    $process = StartWindow
    $bounds = $root.Current.BoundingRectangle
    Say ($bounds.Right -le 0 -or $bounds.Bottom -le 0) ("the window of the walk stands off the screen: {0},{1}" -f $bounds.Left, $bounds.Top)
    Say ($null -ne (Find $root 'section_local_ocr' 60)) 'the layout is read: the section LOCAL OCR is in the window'
    # The stand has the Tesseract of the program (runtime is linked): once the machine has answered, the
    # window stays on LOCAL OCR. Without Tesseract it would open on SETUP - a stand without it is another check.
    Start-Sleep -Seconds 8
    Say ((IsOn (Find $root 'section_local_ocr' 5)) -and -not (IsOn (Find $root 'section_setup' 5))) 'with Tesseract the window opens on LOCAL OCR, not on SETUP'

    # SETUP: a button of the header, before SETTINGS - the page of the installations comes up. Nothing is installed.
    Open 'setup'
    Say ($null -ne (Find $root 'run_install_tesseract' 10)) 'SETUP in the header opens the installations: the button of Tesseract is in sight'

    # TOOLS, To Markdown: an office document into Markdown, without OCR.
    if (Part 'markdown') {
    Fresh; Fixture 'docx'
    Open 'tools' 'convert'
    $state = Run 'extract_local' 180
    Say ($state -eq 'done' -and (FilesIn $out '*.md').Count -ge 1) "TOOLS, To Markdown: $state, Markdown in output: $((FilesIn $out '*.md').Count)"
    $log = @(Get-ChildItem -LiteralPath (Join-Path $Stand 'logs') -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*extract_local*' })
    Say ($log.Count -ge 1) "the operation ran through the console command: its journal lies in the logs of the stand ($($log.Count))"
    }

    # LOCAL OCR with Tesseract: one page of a scan into DOCX, the format the form has ticked.
    if (Part 'ocr') {
    Fresh; Fixture 'scan' 1
    Open 'local_ocr' 'local' 'local_ocr_local_tesseract'
    $state = Run 'ocr_local_run' 300
    Say ($state -eq 'done' -and (FilesIn $out '*.docx').Count -ge 1) "LOCAL OCR, Tesseract: $state, DOCX in output: $((FilesIn $out '*.docx').Count)"
    }

    # Workbench: the local review of weak OCR, then the coordinates.
    if (Part 'workbench') {
    Fresh; Fixture 'scan' 1
    Open 'tools' 'workbench'
    $state = Run 'workbench_review' 300
    $made = (FilesIn $report 'manual_review.xlsx').Count + (FilesIn $report 'review_items.json').Count
    Say ($state -eq 'done' -and $made -ge 1) "Workbench, local review: $state, review files in report: $made"
    $state = Run 'workbench_coordinates' 300
    Say ($state -eq 'done' -and (FilesIn $out 'workbench_coordinates.xlsx').Count -ge 1) "Workbench, coordinates: $state, workbench_coordinates.xlsx: $((FilesIn $out 'workbench_coordinates.xlsx').Count)"
    }

    # The rebuild of Markdown: DOCX, LLM-DOCX, PPTX.
    if (Part 'rebuild') {
    Fresh; Fixture 'md'
    Open 'tools' 'rebuild'
    $state = Run 'build_docx' 180
    Say ($state -eq 'done' -and (FilesIn $out '*.docx').Count -ge 1) "rebuild, DOCX: $state, DOCX in output: $((FilesIn $out '*.docx').Count)"
    $was = (FilesIn $out '*.docx').Count
    $state = Run 'build_docx_llm' 180
    Say ($state -eq 'done' -and (FilesIn $out '*.docx').Count -ge 1) "rebuild, LLM-DOCX: $state, DOCX in output: $was -> $((FilesIn $out '*.docx').Count)"
    $state = Run 'build_pptx' 180
    # The engine of 1.8.2 cannot build PPTX (tests\engine_golden_cases.py, build_pptx: the case that fails by design).
    Known ($state -eq 'done' -and (FilesIn $out '*.pptx').Count -ge 1) "rebuild, PPTX: $state, PPTX in output: $((FilesIn $out '*.pptx').Count)"
    }

    # TABLES: Markdown tables into XLSX and their check; the coordinate tables of a scan.
    if (Part 'tables') {
    Fresh; Fixture 'md'
    Open 'tables' 'tables'
    $state = Run 'build_xlsx' 180
    Say ($state -eq 'done' -and (FilesIn $out '*.xlsx').Count -ge 1) "TABLES, XLSX: $state, XLSX in output: $((FilesIn $out '*.xlsx').Count)"
    $state = Run 'inspect_tables' 180
    Say ($state -eq 'done') "TABLES, the check of the Markdown tables: $state"
    Fresh; Fixture 'scan' 1
    $state = Run 'coordinate_tables' 300
    Say ($state -eq 'done') "TABLES, the coordinate tables of a scan: $state, files in output: $((FilesIn $out).Count)"
    }

    # A key: added by its button - a made-up key typed into the dialog, a file of the config of the stand - and set aside.
    if (Part 'key') {
    Open 'api_ocr' 'api' 'api_ocr_api_chatgpt'
    $config = Join-Path $Stand 'config'
    $before = @(Get-ChildItem -LiteralPath $config -Recurse -File -Filter 'api_key_openai*.txt' -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike '*deleted_keys*' })
    Press (Find $root 'key_add_openai' 15)
    $box = FindInProcess $process.Id 'PromptBox' 15
    $value = $null
    if ($box -and $box.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$value)) { $value.SetValue('sk-walk-made-up-0000') }
    Press (FindInProcess $process.Id 'PromptOk' 5)
    Start-Sleep -Seconds 3
    $after = @(Get-ChildItem -LiteralPath $config -Recurse -File -Filter 'api_key_openai*.txt' -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike '*deleted_keys*' })
    Say ($after.Count -eq $before.Count + 1) "the key added: key files of OpenAI in the config of the stand $($before.Count) -> $($after.Count)"
    $remove = Find $root 'key_remove_openai' 15
    $until = (Get-Date).AddSeconds(20)
    while ($remove -and -not $remove.Current.IsEnabled -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 400; $remove = Find $root 'key_remove_openai' 5 }
    if ($remove) { Press $remove } else { "        the ids of keys in sight: $(Ids $root 'key_')" }
    Say (AnswerYes $process.Id) 'setting the key aside asks first'
    Start-Sleep -Seconds 3
    $aside = @(Get-ChildItem -LiteralPath (Join-Path $config 'deleted_keys\openai') -File -ErrorAction SilentlyContinue)
    Say ($aside.Count -ge 1) "the key set aside: config\deleted_keys\openai holds $($aside.Count)"
    }

    # The operation of the folders: the Markdown of output back into input.
    if (Part 'folders') {
    Fresh; Fixture 'md' 1 $out
    $state = Run 'copy_output_markdown_to_input' 120
    Say ($state -eq 'done' -and (FilesIn $in '*.md').Count -ge 1) "the Markdown of output into input: $state, Markdown in input: $((FilesIn $in '*.md').Count)"
    }

    # CLEAR: its menu - the DocumentModel artifacts, then both folders - each with its question.
    if (Part 'clear') {
    Fixture 'md'
    Set-Content -LiteralPath (Join-Path $out 'walk.document.json') -Value '{}' -Encoding utf8
    Set-Content -LiteralPath (Join-Path $out 'walk-result.docx.txt') -Value 'a result that stays' -Encoding utf8
    Press (Find $root 'clear_folders' 15)
    $item = Find $root 'run_cleanup_document_model_artifacts' 15
    Say ($null -ne $item) 'the button CLEAR opens its menu: the clearing of DocumentModel is in it'
    if (-not $item) { "        the ids of the menu in sight: $(Ids $root 'clear')  $(Ids $root 'run_cleanup')" }
    if ($item) {
        $before = TextOf $root 'StatusText'
        Press $item
        Say (AnswerYes $process.Id) 'the clearing of DocumentModel asks first'
        $state = WaitOutcome $root @('done', 'failed', 'refused') 120 $before
        Say ($state -eq 'done' -and -not (Test-Path -LiteralPath (Join-Path $out 'walk.document.json')) -and (Test-Path -LiteralPath (Join-Path $out 'walk-result.docx.txt'))) "DocumentModel cleared: $state, the artifact gone, the result kept"
    }
    Press (Find $root 'clear_folders' 15)
    $both = Find $root 'clear_both' 15
    Say ($null -ne $both) 'the menu of CLEAR has "both"'
    if ($both) {
        Press $both
        Say (AnswerYes $process.Id) 'CLEAR asks first'
        $until = (Get-Date).AddSeconds(20)
        do { Start-Sleep -Milliseconds 300; $left = (FilesIn $in).Count + (FilesIn $out).Count } while ($left -gt 0 -and (Get-Date) -lt $until)
        Say ($left -eq 0 -and (Test-Path -LiteralPath $in) -and (Test-Path -LiteralPath $out)) "CLEAR: the contents of input and output are gone, the folders stay ($left left)"
    }
    }

    # STOP while OCR of many pages goes.
    if (Part 'stop') {
    Fresh; Fixture 'scan' 30
    Open 'local_ocr' 'local' 'local_ocr_local_tesseract'
    $button = Find $root 'run_ocr_local_run'
    Start-Sleep -Milliseconds 600
    Say ($button.Current.IsEnabled) 'after the clearing the button of OCR can be pressed again'
    Press $button
    $state = WaitOutcome $root @('running') 30
    Say ($state -eq 'running') "OCR of 30 pages: the operation goes ($state)"
    Start-Sleep -Seconds 6
    $stop = Find $root 'stop' 5
    Say ($null -ne $stop -and $stop.Current.IsEnabled) 'STOP is in sight and can be pressed while the operation goes'
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    Press $stop
    $state = WaitOutcome $root @('stopped') 90
    $took = [Math]::Round($clock.Elapsed.TotalSeconds, 1)
    Say ($state -eq 'stopped' -and $took -lt 70) "STOP pressed: $state in $took s"
    Start-Sleep -Milliseconds 800
    Say ($button.Current.IsEnabled) 'after the stop the button of OCR can be pressed again'
    }

    # The window closed while OCR goes: it asks, stops the operation and then closes.
    if (Part 'close') {
    if ((FilesIn $in '*.png').Count -lt 10) { Fresh; Fixture 'scan' 30 }
    Open 'local_ocr' 'local' 'local_ocr_local_tesseract'
    $button = Find $root 'run_ocr_local_run'
    Press $button
    $null = WaitOutcome $root @('running') 30
    Start-Sleep -Seconds 4
    CloseWindow $root
    Say (AnswerYes $process.Id 15) 'closing during an operation asks first'
    Say ($process.WaitForExit(120000)) 'answered: the operation stopped and the window closed'
    }
    else { CloseWindow $root; [void]$process.WaitForExit(30000) }

    # What an operation started ends with it: asked for ten seconds, not at one look. The walk itself is
    # not one of them, though its command line names the stand.
    $until = (Get-Date).AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 500
        $left = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID } | Where-Object { ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Stand, [StringComparison]::OrdinalIgnoreCase)) -or ($_.CommandLine -and $_.CommandLine.Contains($Stand)) })
    } while ($left.Count -gt 0 -and (Get-Date) -lt $until)
    Say ($left.Count -eq 0) ("no process of the stand is left: {0}" -f $left.Count)
    foreach ($one in $left) { "        left: {0} {1}  {2}" -f $one.ProcessId, $one.Name, ($one.CommandLine -replace '\s+', ' ').Substring(0, [Math]::Min(160, ($one.CommandLine -replace '\s+', ' ').Length)) }
    $crash = @(Get-ChildItem -LiteralPath (Join-Path $Stand 'logs') -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'gui-crash-*' -or ($_.Name -eq 'gui-event-errors.log' -and $_.Length -gt 0) })
    Say ($crash.Count -eq 0) ("the window wrote no report of its own errors: {0}" -f (($crash | ForEach-Object Name) -join ', '))
}
catch {
    Say $false ("the walk broke: " + $_.Exception.Message)
}
finally {
    Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($Stand, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { try { $_.Kill($true) } catch { } }
    if ($Keep) { "the stand is kept: $Stand" }
    else {
        Start-Sleep -Milliseconds 800
        # The link to runtime\ goes first, alone: the Python of the program behind it is not the stand's.
        if (Test-Path -LiteralPath $runtime) { [System.IO.Directory]::Delete($runtime, $false) }
        [System.IO.Directory]::Delete($Stand, $true)
        'the stand is removed'
    }
}
"failed checks: $failed"
exit $(if ($failed) { 1 } else { 0 })
