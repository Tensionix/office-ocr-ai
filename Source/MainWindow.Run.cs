using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using AudionOfficeOcrAi.Core;
using AudionOfficeOcrAi.Views;

namespace AudionOfficeOcrAi;

/// <summary>
/// A run: one operation at a time, started through the door with what the form holds at the
/// moment of the press. Its course is read from the service lines of the door. STOP asks the
/// operation to stop - it stops itself where nothing is left half done; only an operation that
/// does not answer is ended.
/// </summary>
public partial class MainWindow
{
    string _runName = "";
    DateTime _started;
    readonly DispatcherTimer _clock = new() { Interval = TimeSpan.FromSeconds(1) };
    /// <summary>What the door said of the end of the run in its service line.</summary>
    DoorEvent? _finish;
    bool _stopAsked, _stopAgain, _asking;
    DispatcherTimer? _killTimer, _againTimer;
    /// <summary>How long an operation asked to stop is waited for before it is ended.</summary>
#if DEBUG
    // A stand names its own term (AUDION_STOP_WAIT, seconds): a check does not wait a minute.
    static readonly int StopWaitSeconds = int.TryParse(Environment.GetEnvironmentVariable("AUDION_STOP_WAIT"), out var seconds) && seconds > 0 ? seconds : 60;
#else
    const int StopWaitSeconds = 60;
#endif

    /// <summary>One thing at a time: while it goes, nothing else starts.</summary>
    void ApplyBusy()
    {
        bool free = !_runner.Running && !_asking && _told is not null && Door.Ready;
        if (_view is { } view)
            foreach (var button in view.RunButtons) button.IsEnabled = free;
        foreach (var child in ServiceRow.Children.Concat(FolderTools.Children)) if (child is Button button) button.IsEnabled = free;
        StopButton.IsVisible = _runner.Running;
        StopButton.IsEnabled = _runner.Running && (!_stopAsked || _stopAgain);
    }

    /// <summary>The name of an operation with its place: "ТАБЛИЦЫ → Таблицы → Сборка XLSX". Names repeat across pages.</summary>
    static string PathName(Node node) =>
        node.Page is { Section: { } section } page ? $"{section.Name} → {page.Name} → {node.Name}" : node.Name;

    /// <summary>
    /// A press of a button that runs an operation. Everything the run needs is taken from the
    /// window here, before any question: the answer may come a minute later, and what is started
    /// is what was asked about.
    /// </summary>
    async void Press(Node node)
    {
        if (!node.Runs || _asking) return;
        if (_runner.Running) { SetStatus("Идёт другая операция."); return; }
        if (_clearing) { SetStatus("Идёт очистка папок."); return; }
        if (_told is null || !Door.Ready) return;
        // A value being typed is taken first: its box gives up the focus.
        Shell.Focus();
        // A path typed and refused by this very press: the run does not go to the path that stood before it.
        if (PathJustRefused()) { Say(Lang.F("запуск отменён - введённый путь не принят: {0}", _pathRefused), refused: true); return; }

        // An operation of the working folders of the program is named no source and no target: it acts
        // on `input` and `output` of the program itself, whatever SOURCE and TARGET say.
        bool own = _told.Layout.Folders.Contains(node);
        var target = own ? "" : _target;
        var source = own ? "" : _source;
        // The values of the page the button stands on; of the window, for a button of the header.
        var held = _store.Of(node.Page);
        var values = held.ForDoor(node);
        var changed = held.ChangedOf(node);
        if (held.TooFew(node, field => _view?.Form.InSight(field) ?? true) is { } few)
        {
            SetStatus(Lang.F("«{0}»: отметьте не меньше {1}.", Form.NameOf(few), few.MinSelected));
            return;
        }

        if (!await MayRun(node, values, source, target, own ? FolderLines() : "")) return;
        // The value the operation asks for: typed into a dialog now, handed to the door by its standard
        // input at the start, and kept nowhere - not in the values of the run, not in the line of the terminal.
        string? secret = null;
        if (node.Prompt.Length > 0)
        {
            secret = await PromptDialog.Ask(this, node.Asks);
            if (secret is null) { SetStatus("Отменено."); return; }
            if (_runner.Running) return;
        }
        Begin(node, target, values, changed, source: source, secret: secret);
    }

    /// <summary>A stand walks the window without showing it: what a press starts is started all the same.</summary>
    bool _standing;

    /// <summary>
    /// What stands between a press and a run: the gate of the operation, asked of the door; the
    /// question before a run that copies an external source into input and clears input and output
    /// (MainWindow.Io.cs, MirrorAllowed); the question a dangerous one is asked about - with
    /// <paramref name="more"/> under it, the lines that name what it acts on. True - it may run now.
    /// </summary>
    async Task<bool> MayRun(Node node, string values, string source, string target, string more = "")
    {
        _asking = true;
        ApplyBusy();
        try
        {
            if (node.Gated)
            {
                SetStatus("Проверяю, можно ли запускать…");
                var why = await Door.Gate(node.Id, values, source, target);
                if (why.Length > 0) { SetStatus(why); await AskDialog.Ok(this, PathName(node), why); return false; }
            }
            if (node.Mirrors && source.Length > 0 && await MirrorAllowed(source) is { } refused)
            {
                if (refused.Length == 0) { SetStatus("Отменено."); return false; }
                Say(refused, refused: true);
                await AskDialog.Ok(this, PathName(node), refused);
                return false;
            }
            if (node.Dangerous)
            {
                var about = node.Tip.Length > 0 ? node.Tip : node.About;
                if (more.Length > 0) about += "\n" + more;
                if (!await AskDialog.YesNo(this, Lang.F("Выполнить «{0}»?", PathName(node)), about, node.Tone == "burn" ? "burn" : "")) { SetStatus("Отменено."); return false; }
            }
            return !_runner.Running && !_clearing && (IsVisible || _standing);
        }
        finally
        {
            _asking = false;
            ApplyBusy();
        }
    }

    void Begin(Node node, string target, string values, Dictionary<string, string> changed, string? name = null, string source = "", string? secret = null)
    {
        // What the operation says is read in the terminal: a sheet over it steps aside.
        if (_sheet.Length > 0) ToggleSheet(_sheet);
        _runName = name ?? PathName(node);
        _started = DateTime.Now;
        _finish = null;
        _stopAsked = false;
        _stopAgain = false;
        _ansi.Reset();

        AppendLines(new[] { "", $"===== {_runName} =====" });
        AppendLines(new[] { "[GUI] " + Door.RunLine(node.Id, source, target, changed, secret is null ? "" : node.Prompt) });
        if (Door.Prepare(values) is { Length: > 0 } trouble)
        {
            AppendLines(new[] { "[ERR] " + Lang.F("запуск не подготовлен: {0}", trouble) });
            SetStatus("Не запустилось: причина в терминале.");
            return;
        }
        if (_runner.Start(Door.Run(node.Id, source, target, secret is null ? "" : node.Prompt, secret)) is { } failed)
        {
            AppendLines(new[] { "[ERR] " + Lang.F("не запустилось: {0}", failed) });
            SetStatus("Не запустилось: причина в терминале.");
            return;
        }

        RunNameText.Text = Upper(name ?? node.ButtonName);
        RunNameText.Classes.Set("idle", false);
        OutcomeText.Text = Upper(Lang.T("идёт"));
        SetTone(OutcomeText, "quiet");
        SetStatus(_runName);
        // Until the operation says how far it is, the bar only shows that it goes.
        ProgressBar.IsVisible = true;
        ProgressBar.IsIndeterminate = true;
        ShowClock();
        _clock.Start();
        ShowActivity("");
        ApplyBusy();
    }

    string _activity = "";

    /// <summary>
    /// The live line of the terminal, its last line while an operation goes: what the operation
    /// says it is at - a download in its colours (Views\LiveLine.cs) - or, while it says nothing,
    /// its name. The dot before it breathes as long as the operation goes. The line stays for the
    /// whole run: one that came and went with every file made the journal over it jump.
    /// </summary>
    void ShowActivity(string text, bool? shown = null)
    {
        _activity = text.Trim();
        bool runs = shown ?? _runner.Running;
        if (runs)
        {
            if (_activity.Length > 0) LiveLine.Paint(ActivityText, _activity);
            else LiveLine.Quiet(ActivityText, _runName + "…");
        }
        ActivityDot.Classes.Set("pulse", runs);
        ActivityRow.IsVisible = runs;
    }

    static void SetTone(TextBlock number, string tone)
    {
        foreach (var name in new[] { "idle", "good", "bad", "warn", "quiet" }) number.Classes.Set(name, name == tone);
    }

    // ------------------------------------------------------------ the course

    void OnOutput(IReadOnlyList<string> lines)
    {
        var plain = new List<string>(lines.Count);
        foreach (var line in lines)
        {
            if (Door.Read(line) is not { } said) { plain.Add(line); continue; }
            switch (said.Kind)
            {
                case "progress":
                    // A share of zero is "started", not a measure: most operations say 0 and then 1.
                    ProgressBar.IsIndeterminate = said.Progress <= 0;
                    if (said.Progress > 0) ProgressBar.Value = Math.Max(2, Math.Min(100, said.Progress * 100));
                    break;
                case "activity":
                    ShowActivity(said.Activity);
                    break;
                case "finished":
                    _finish = said;
                    break;
            }
        }
        AppendLines(plain, told: true);
    }

    void ShowClock()
    {
        var span = DateTime.Now - _started;
        ClockText.Text = span.TotalHours >= 1 ? span.ToString(@"h\:mm\:ss") : span.ToString(@"mm\:ss");
        ClockText.Classes.Set("idle", false);
    }

    // ------------------------------------------------------------ STOP

    /// <summary>
    /// STOP. The operation is asked by the signal file: it sees the file itself at its next safe
    /// point. An operation that has not ended in a minute is ended from here, with everything it
    /// started - or at once, by a second press: the button comes back a few seconds after the
    /// first, so a double click does not end what was only asked to stop.
    /// </summary>
    void StopRun()
    {
        if (!_runner.Running) return;
        if (_stopAsked)
        {
            if (!_stopAgain) return;
            _stopAgain = false;
            _killTimer?.Stop();
            ApplyBusy();
            AppendLines(new[] { "[GUI] " + Lang.T("СТОП нажат повторно: операция завершена принудительно") });
            _runner.Stop();
            return;
        }
        _stopAsked = true;
        ApplyBusy();
        AppendLines(new[] { "[GUI] " + Lang.T("остановлено кнопкой СТОП: операция останавливается сама") });
        SetStatus(Lang.F("{0}: останавливается…", _runName));
        if (Door.AskToStop() is { Length: > 0 } trouble)
        {
            AppendLines(new[] { "[GUI] " + Lang.F("сигнал остановки не записан ({0}): операция завершена принудительно", trouble) });
            _runner.Stop();
            return;
        }
        _killTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(StopWaitSeconds) };
        _killTimer.Tick += (_, _) =>
        {
            _killTimer?.Stop();
            if (!_runner.Running) return;
            AppendLines(new[] { "[GUI] " + Lang.F("операция не остановилась за {0} с: завершена принудительно", StopWaitSeconds) });
            _runner.Stop();
        };
        _killTimer.Start();
        _againTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(3) };
        _againTimer.Tick += (_, _) =>
        {
            _againTimer?.Stop();
            if (!_runner.Running || !_stopAsked) return;
            _stopAgain = true;
            ApplyBusy();
        };
        _againTimer.Start();
    }

    // ------------------------------------------------------------ the end of a run

    void OnFinished(int code, bool stopped)
    {
        _clock.Stop();
        _killTimer?.Stop();
        _againTimer?.Stop();
        ShowClock();
        // What the door said comes first; a door that did not get to say it is read by its exit code.
        string outcome = stopped ? "stopped"
            : _finish is { Outcome.Length: > 0 } said ? said.Outcome
            : code == Door.ExitStopped ? "stopped"
            : code == Door.ExitUsage ? "refused"
            : code == Door.ExitDone ? "done" : "failed";
        var (word, tone) = outcome switch
        {
            "done" => ("готово", "good"),
            "stopped" => ("остановлено", "warn"),
            "refused" => ("отказ", "bad"),
            _ => ("ошибка", "bad"),
        };
        _ansi.Reset();
        AppendLines(new[] { $"===== {(outcome == "done" ? "OK" : outcome == "stopped" ? "STOPPED" : "FAILED")}: {_runName} · {ClockText.Text} =====" });
        if (_finish?.Message is { Length: > 0 } message && outcome is "failed" or "refused")
            AppendLines(new[] { "[ERR] " + message });

        OutcomeText.Text = Upper(Lang.T(word));
        SetTone(OutcomeText, tone);
        ProgressBar.IsVisible = false;
        ShowActivity("", false);
        // A run took room on a drive; an installation may have brought Tesseract or a key a check found.
        ShowDrives();
        _ = AskHardware();
        SetStatus(outcome switch
        {
            "done" => Lang.F("Готово: {0}", _runName),
            "stopped" => Lang.F("Остановлено: {0}", _runName),
            "refused" => Lang.F("{0}: отказ до начала - причина в терминале.", _runName),
            _ => Lang.F("{0}: ошибка - подробности в терминале.", _runName),
        });
        // What is installed and what has an update is another answer after a run: the lists about the
        // machine are asked anew when their page is next in sight. The catalogue of a vendor is what it
        // was and stays (Core\ListMemory.cs). A page is built again only when it lost a list - to build
        // a whole catalogue for nothing left the left side empty for a second.
        // What the program keeps - the cache of models, the key files - may be another after a run: read
        // again at once, in one call of the door, and the pages take it when it has come.
        if (outcome == "done") _ = RefreshKept();
        ApplyBusy();
        if (_closeAfterRun) Close();
    }

    // ------------------------------------------------------------ the end of the window

    bool _closeAfterRun, _closeAsking;

    /// <summary>
    /// The window closes. A running operation is asked about - closing stops it, and that has to
    /// be a decision; on a "yes" it is stopped the way STOP stops it, and the window closes when
    /// the operation has ended. Windows shutting down is not asked.
    /// </summary>
    void OnClosing(object? sender, WindowClosingEventArgs e)
    {
        // A clearing is not cut in the middle: the window closes when it has ended.
        if (_clearing && e.CloseReason == WindowCloseReason.WindowClosing)
        {
            e.Cancel = true;
            _closeAfterClearing = true;
            SetStatus("Окно закроется, когда очистка закончится.");
            return;
        }
        if (_runner.Running && e.CloseReason == WindowCloseReason.WindowClosing)
        {
            e.Cancel = true;
            if (!_closeAfterRun) AskToClose();
            return;
        }
        if (_runner.Running)
        {
            Door.AskToStop();
            _runner.StopForClose();
        }
        SaveWindow();
        if (!_runner.Running) Paths.DropSession();
    }

    async void AskToClose()
    {
        if (_closeAsking) return;
        _closeAsking = true;
        try
        {
            var go = await AskDialog.YesNo(this, "Закрыть окно и остановить операцию?",
                Lang.F("Идёт «{0}».", _runName) + "\n" + Lang.T("Операция остановится сама в ближайшей безопасной точке. Окно закроется, когда она остановится."), "burn");
            if (!go) return;
            if (!_runner.Running) { Close(); return; }
            _closeAfterRun = true;
            StopRun();
        }
        finally { _closeAsking = false; }
    }

#if DEBUG
    // ------------------------------------------------------------ a check without a mouse

    /// <summary>
    /// The pictures of the window, page by page, into a folder: what a person is shown before any
    /// button is pressed. Nothing is run; the lists a page asks of the door are waited for.
    /// </summary>
    async Task TakeShots(string folder)
    {
        Directory.CreateDirectory(folder);
        if (_told is null) { Save(Path.Combine(folder, "00-no-door.png")); Close(); return; }
        int number = 0;
        bool pages = Environment.GetEnvironmentVariable("AUDION_SHOT_PAGES") != "0";
        // The badges of the header with what their tooltips say: a picture shows the words alone.
        File.WriteAllLines(Path.Combine(folder, "badges.txt"), MachineRow.Children.OfType<Border>().Where(badge => badge.IsVisible)
            .Select(badge => "[" + ((badge.Child as TextBlock)?.Text ?? "") + "]" + (badge.Classes.Contains("warn") ? " (warn)" : "") + "\n    "
                + (ToolTip.GetTip(badge)?.ToString() ?? "").Replace("\n", "\n    ")));
        // AUDION_SHOT_ONLY: the pages to picture, by their ids - a list a vendor serves is not fetched for a
        // page nobody looks at. AUDION_SHOT_SET: "field=value;field=value" - each is set on a page that
        // has the field, and the page is pictured once more as it stands after it.
        var only = (Environment.GetEnvironmentVariable("AUDION_SHOT_ONLY") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var sets = (Environment.GetEnvironmentVariable("AUDION_SHOT_SET") ?? "").Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(pair => pair.Split('=', 2)).Where(pair => pair.Length == 2).ToList();
        int pause = Environment.GetEnvironmentVariable("AUDION_SHOT_WAIT") is { } wait && int.TryParse(wait, out var ms) ? ms : 900;
        foreach (var section in _told.Layout.Sections)
            foreach (var page in section.Pages)
            {
                if (!pages) break;
                number++;
                if (only.Length > 0 && !only.Contains(page.Id)) continue;
                SelectSection(section);
                SelectPage(page);
                await Task.Delay(pause);
                Save(Path.Combine(folder, $"{number:00}-{section.Id}-{page.Id}.png"));
                foreach (var pair in sets)
                {
                    if (page.Operations.SelectMany(node => node.Fields).FirstOrDefault(one => one.Id == pair[0]) is not { } field) continue;
                    var held = _store.Of(page);
                    var was = held.Get(field);
                    held.Set(field, pair[1]);
                    await Task.Delay(pause);
                    Save(Path.Combine(folder, $"{number:00}-{section.Id}-{page.Id}-{pair[0]}-{pair[1]}.png"));
                    // AUDION_SHOT_PROBE: the word that begins so, and every control over it up to the page - what
                    // each was given and what it took. A picture shows that a line is cut; this shows by whom.
                    if (Environment.GetEnvironmentVariable("AUDION_SHOT_PROBE") is { Length: > 0 } probe
                        && Avalonia.VisualTree.VisualExtensions.GetVisualDescendants(this).OfType<TextBlock>().FirstOrDefault(word => (word.Text ?? "").StartsWith(probe, StringComparison.OrdinalIgnoreCase)) is { } found)
                    {
                        var report = new List<string> { $"{found.Text}  wrap={found.TextWrapping} size={found.FontSize}" };
                        for (Avalonia.Visual? at = found; at is Control one && at is not ScrollViewer; at = Avalonia.VisualTree.VisualExtensions.GetVisualParent(at))
                            report.Add($"{one.GetType().Name,-18} {string.Join('.', one.Classes),-14} bounds {one.Bounds.Width:0.#}x{one.Bounds.Height:0.#}  desired {one.DesiredSize.Width:0.#}x{one.DesiredSize.Height:0.#}  margin {one.Margin}");
                        File.WriteAllLines(Path.Combine(folder, $"probe-{pair[1]}.txt"), report);
                    }
                    held.Set(field, was);
                    await Task.Delay(300);
                }
            }
        // A walk by steps: the controls themselves are pressed, one after another (MainWindow.Steps.cs).
        if (Environment.GetEnvironmentVariable("AUDION_SHOT_STEPS") is { Length: > 0 } steps) await WalkSteps(folder, steps);
        // One operation pressed by its own button and waited for: the whole way from a press to the verdict.
        if (Environment.GetEnvironmentVariable("AUDION_SHOT_RUN") is { Length: > 0 } id)
        {
            var button = ServiceRow.Children.OfType<Button>().Concat(_view?.RunButtons ?? new List<Button>())
                .FirstOrDefault(one => Avalonia.Automation.AutomationProperties.GetAutomationId(one) == "run_" + id);
            if (button is not null)
            {
                button.RaiseEvent(new Avalonia.Interactivity.RoutedEventArgs(Button.ClickEvent));
                for (int i = 0; i < 50 && !_runner.Running; i++) await Task.Delay(100);
                for (int i = 0; i < 600 && _runner.Running; i++) await Task.Delay(200);
                await Task.Delay(700);
            }
            Save(Path.Combine(folder, "90-run-" + id + ".png"));
        }
        // The terminal with nothing run: lines in the colours their writer gave them, and the live line of
        // a download - two pictures half a breath of its dot apart.
        if (Environment.GetEnvironmentVariable("AUDION_SHOT_LIVE") is { Length: > 0 } live)
        {
            // The lines --self-test reads into their pieces (Core\SelfTest.cs): here they are looked at.
            AppendLines(SelfTest.ColouredLines, told: true);
            ShowActivity(live, true);
            await Task.Delay(350);
            Save(Path.Combine(folder, "91-live-a.png"));
            await Task.Delay(600);
            Save(Path.Combine(folder, "92-live-b.png"));
            ShowActivity("", true);
            await Task.Delay(300);
            Save(Path.Combine(folder, "93-live-quiet.png"));
            ShowActivity("", false);
        }
        // SETTINGS and ABOUT as a person opens them.
        if (Environment.GetEnvironmentVariable("AUDION_SHOT_SHEETS") == "1")
        {
            ToggleSheet("settings");
            await Task.Delay(700);
            Save(Path.Combine(folder, "95-settings.png"));
            ToggleSheet("about");
            await Task.Delay(700);
            Save(Path.Combine(folder, "96-about.png"));
            ToggleSheet("about");
            await Task.Delay(300);
            // Another font and a larger size set while the window is open, as SETTINGS sets them - nothing is
            // saved - then back: the pages must follow both ways.
            var (font, terminal, shift, size) = (_settings.UiFont, _settings.LogFont, _settings.UiShift, _settings.LogSize);
            (_settings.UiFont, _settings.LogFont, _settings.UiShift, _settings.LogSize) = ("Segoe UI", "Consolas", 2, 13);
            ApplyFonts();
            AppendLines(new[] { "[GUI] the terminal in Consolas 13", "[OK] a line of an operation" });
            await Task.Delay(1500);
            Save(Path.Combine(folder, "97-fonts-larger.png"));
            (_settings.UiFont, _settings.LogFont, _settings.UiShift, _settings.LogSize) = (font, terminal, shift, size);
            ApplyFonts();
            await Task.Delay(1500);
            Save(Path.Combine(folder, "98-fonts-back.png"));
        }
        // How long the heaviest page takes to come up: the first time - built and laid out - and every time after.
        if (Environment.GetEnvironmentVariable("AUDION_SHOT_TIME") is { Length: > 0 } heavy
            && _told.Layout.Sections.SelectMany(section => section.Pages).FirstOrDefault(page => page.Id == heavy) is { } timed
            && _told.Layout.Sections.SelectMany(section => section.Pages).FirstOrDefault(page => page.Id != heavy) is { } other)
        {
            var report = new List<string>();
            for (int round = 0; round < 3; round++)
            {
                SelectSection(other.Section!);
                SelectPage(other);
                UpdateLayout();
                await Task.Delay(400);
                var clock = System.Diagnostics.Stopwatch.StartNew();
                SelectSection(timed.Section!);
                SelectPage(timed);
                var chosen = clock.Elapsed.TotalMilliseconds;
                UpdateLayout();
                report.Add($"round {round}: the page chosen in {chosen:0} ms, chosen and laid out in {clock.Elapsed.TotalMilliseconds:0} ms");
                await Task.Delay(1500);
            }
            File.WriteAllLines(Path.Combine(folder, "timing.txt"), report);
        }
        Close();
    }

    void Save(string file)
    {
        Save(this, file);
        Glued(file);
    }

    /// <summary>
    /// Buttons that stand glued to each other (the owner, 15.10.2026: "we watch for buttons that stick
    /// together"): two buttons in sight, side by side on one line, with less than 3 px between them -
    /// or one over another with less than 3 px. Every picture of a pass adds what it shows to
    /// glued.txt beside it; an empty file is the answer wanted.
    /// </summary>
    void Glued(string file)
    {
        var report = Path.Combine(Path.GetDirectoryName(file) ?? ".", "glued.txt");
        // A switch (ToggleButton) is a Button too.
        var buttons = Avalonia.VisualTree.VisualExtensions.GetVisualDescendants(this).OfType<Button>().Cast<Control>()
            // The arrows and the track of a scroll bar are parts of one control, not buttons a person sees as such.
            .Where(one => one.IsEffectivelyVisible && one.Bounds.Width > 0 && one.TemplatedParent is not Avalonia.Controls.Primitives.ScrollBar)
            .Select(one => (Control: one, At: Avalonia.VisualExtensions.TranslatePoint(one, new Avalonia.Point(0, 0), this) is { } at ? new Avalonia.Rect(at, one.Bounds.Size) : default))
            .Where(one => one.At.Width > 0 && one.At.Right > 0 && one.At.Bottom > 0 && one.At.X < Bounds.Width && one.At.Y < Bounds.Height)
            .ToList();
        static string Name(Control control)
        {
            var id = Avalonia.Automation.AutomationProperties.GetAutomationId(control);
            if (!string.IsNullOrEmpty(id)) return id;
            if (control.Name is { Length: > 0 } name) return name;
            var words = Avalonia.VisualTree.VisualExtensions.GetVisualDescendants(control).OfType<TextBlock>().Select(text => text.Text).FirstOrDefault(text => !string.IsNullOrEmpty(text));
            return words ?? control.GetType().Name;
        }
        var found = new List<string>();
        for (int i = 0; i < buttons.Count; i++)
            for (int j = i + 1; j < buttons.Count; j++)
            {
                var (a, b) = (buttons[i].At, buttons[j].At);
                // A button inside another is no neighbour of it.
                if (a.Contains(b) || b.Contains(a)) continue;
                double side = Math.Min(a.Bottom, b.Bottom) - Math.Max(a.Y, b.Y), across = Math.Min(a.Right, b.Right) - Math.Max(a.X, b.X);
                double gapX = Math.Max(a.X, b.X) - Math.Min(a.Right, b.Right), gapY = Math.Max(a.Y, b.Y) - Math.Min(a.Bottom, b.Bottom);
                bool row = side > 0.6 * Math.Min(a.Height, b.Height) && gapX < 3, column = across > 0.6 * Math.Min(a.Width, b.Width) && gapY < 3;
                if (row || column)
                    found.Add($"{Path.GetFileName(file)}: {Name(buttons[i].Control)} | {Name(buttons[j].Control)} - {(row ? $"side by side, {gapX:0.#} px" : $"one over another, {gapY:0.#} px")}");
            }
        File.AppendAllLines(report, found);
    }

    /// <summary>A window - this one, or a dialog of it - as a picture, at the scale of its screen.</summary>
    static void Save(Window window, string file)
    {
        double scale = window.RenderScaling;
        var size = new Avalonia.PixelSize((int)(window.Bounds.Width * scale), (int)(window.Bounds.Height * scale));
        using var bitmap = new RenderTargetBitmap(size, new Avalonia.Vector(96 * scale, 96 * scale));
        bitmap.Render(window);
        using var picture = File.Create(file);
        bitmap.Save(picture, new PngBitmapEncoderOptions());
    }
#endif
}
