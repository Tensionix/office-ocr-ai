using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using AudionOfficeOcrAi.Core;
using AudionOfficeOcrAi.Views;

namespace AudionOfficeOcrAi;

/// <summary>
/// What this machine has for OCR, in the header after the machine itself: what the video card
/// asks to install, Tesseract and its languages, the layout service of Surya, the keys of the
/// providers. The door is asked off the thread of the window (ocr_cli.cmd hardware) - it reads
/// the video card through Windows and starts Tesseract once - at the start and after every run.
/// </summary>
public partial class MainWindow
{
    Hardware? _hardware;
    readonly Border[] _ocrBadges = new Border[4];
    bool _hardwareAsked;
    /// <summary>The window has just started and no one has chosen a section yet: the first answer about the machine may still choose one.</summary>
    bool _startOpen;

    /// <summary>The badges of OCR into the row of the machine: empty until the door answers.</summary>
    void ShowOcr()
    {
        for (int i = 0; i < _ocrBadges.Length; i++) MachineRow.Children.Add(_ocrBadges[i] = Spec(null));
        FillOcr();
    }

    static readonly (string Id, string Name)[] Providers =
        { ("openai", "OpenAI"), ("gemini", "Gemini"), ("mistral", "Mistral"), ("yandex", "Yandex"), ("xai", "xAI") };

    void FillOcr()
    {
        if (_hardware is not { } told || _ocrBadges[0] is null) return;
        bool ru = Lang.Code == "ru";
        // The video card: what it is and what to install for Surya on it. Its words come from the door in both languages.
        var short_ = ru ? told.ShortRu : told.Short;
        var gpu = told.Gpu.Length > 0 ? told.Gpu : Lang.T("видеокарта не найдена");
        var tip = new List<string> { ru ? told.HeadlineRu : told.Headline, gpu };
        if (told.GpuDriver.Length > 0) tip.Add(Lang.F("Драйвер: {0}", told.GpuDriver));
        if ((ru ? told.DetailsRu : told.Details) is { Length: > 0 } details) tip.Add(details);
        if (told.Recommended.Count > 0) tip.Add(Lang.F("Поставить: {0}", string.Join(", ", told.Recommended)));
        if (told.Optional.Count > 0) tip.Add(Lang.F("По желанию: {0}", string.Join(", ", told.Optional)));
        Tell(_ocrBadges[0], new Badge(short_.Length > 0 ? short_ : gpu, string.Join("\n", tip.Where(line => line.Length > 0))));

        // Tesseract: the local OCR of Workbench and of LOCAL OCR.
        if (told.TesseractFound)
        {
            var languages = told.TesseractLanguages.Where(code => code != "osd").ToList();
            var version = told.TesseractVersion.Split(' ', StringSplitOptions.RemoveEmptyEntries).LastOrDefault() ?? "";
            var shown = string.Join("+", languages.Take(3)) + (languages.Count > 3 ? "…" : "");
            Tell(_ocrBadges[1], new Badge($"Tesseract {version}".Trim() + (shown.Length > 0 ? " · " + shown : ""),
                Lang.F("Tesseract найден: {0}", told.TesseractWhere) + "\n" + Lang.F("Языки: {0}", string.Join(", ", languages))));
        }
        else
            Tell(_ocrBadges[1], new Badge(Lang.T("Tesseract не найден"),
                Lang.T("Локальный OCR ограничен. ИНСТРУМЕНТЫ → Установка → Tesseract ставит его в runtime\\tesseract программы."), Warn: true));

        // The layout service of Surya: started from its switch on LOCAL OCR, it keeps the model in memory between runs.
        Tell(_ocrBadges[2], new Badge(Lang.T(told.LayoutUp ? "Сервис Surya: работает" : "Сервис Surya: остановлен"),
            Lang.F("Сервис разметки Surya на 127.0.0.1:{0}: держит модель разметки в памяти между запусками. Запускается и останавливается на странице SURYA раздела ЛОКАЛЬНЫЙ OCR.", told.LayoutPort)));

        // The keys: how many files of each provider hold a key - never a key itself.
        var held = Providers.Where(provider => told.Keys.TryGetValue(provider.Id, out var count) && count > 0).ToList();
        var lines = Providers.Select(provider => $"{provider.Name}: {(told.Keys.TryGetValue(provider.Id, out var count) ? count : 0)}");
        Tell(_ocrBadges[3], new Badge(
            held.Count == 0 ? Lang.T("Ключей API нет") : Lang.F("Ключи: {0}", string.Join(" · ", held.Select(provider => provider.Name))),
            Lang.T("Файлы ключей в config, в которых есть ключ:") + "\n" + string.Join("\n", lines) + "\n"
            + Lang.T("Ключ добавляется и убирается кнопками у поля ключа на странице поставщика в разделе API OCR."),
            Warn: held.Count == 0));
        CentreWords();
    }

    // ------------------------------------------------------------ the layout service of Surya

    bool _serviceBusy;
    static readonly System.Net.Http.HttpClient Local = new() { Timeout = TimeSpan.FromSeconds(2) };

    /// <summary>
    /// The line of SURYA under its switch: whether the layout service runs, and the button that
    /// starts or stops it (system_core\ocr_brick\Layout.Service.ps1). The service keeps the model
    /// of the layout in memory, so a run does not load it again; a run of SURYA without it says so.
    /// </summary>
    void ShowLayoutService()
    {
        bool surya = _sheet.Length == 0 && _view is { } view && view.Page.Choices.Count > 0 && view.Page.Chosen == "surya";
        NoteBar.IsVisible = surya;
        if (!surya) return;
        bool? up = _hardware?.LayoutUp;
        int port = _hardware is { LayoutPort: > 0 } machine ? machine.LayoutPort : 8771;
        var state = _serviceBusy ? Lang.T("сервис разметки Surya: жду ответа…")
            : up is null ? Lang.T("сервис разметки Surya: ещё не спрошен")
            : up.Value ? Lang.F("сервис разметки Surya работает на 127.0.0.1:{0}: модель разметки уже в памяти", port)
            : Lang.T("сервис разметки Surya остановлен: запуск SURYA его требует");
        var line = new TextBlock { Classes = { "note" }, Text = state, TextWrapping = Avalonia.Media.TextWrapping.Wrap, VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center };
        line.Classes.Set("warn", up == false && !_serviceBusy);
        bool start = up != true;
        var face = new StackPanel { Orientation = Avalonia.Layout.Orientation.Horizontal, Spacing = 6 };
        face.Children.Add(Icons.Sign(start ? "play" : "square"));
        face.Children.Add(new TextBlock { Text = Lang.T(start ? "ЗАПУСТИТЬ СЕРВИС" : "ОСТАНОВИТЬ СЕРВИС") });
        var button = new Button { Classes = { "small" }, Content = face, Margin = new Avalonia.Thickness(10, 0, 0, 0), VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center, IsEnabled = !_serviceBusy };
        Avalonia.Automation.AutomationProperties.SetAutomationId(button, "layout_service");
        ToolTip.SetTip(button, Lang.T("Сервис разметки Surya держит модель разметки в памяти между запусками. Он работает в фоне, пока его не остановят или машина не выключится."));
        button.Click += (_, _) => ToggleLayoutService(start);
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        row.Children.Add(line);
        Grid.SetColumn(button, 1);
        row.Children.Add(button);
        NoteBar.Child = row;
        CentreWords();
    }

    /// <summary>Whether the layout service answers on its port, asked by the window itself: no Python, two seconds at most.</summary>
    async Task<bool> LayoutUp(int port)
    {
        try
        {
            var text = await Local.GetStringAsync($"http://127.0.0.1:{port}/health");
            using var doc = System.Text.Json.JsonDocument.Parse(text);
            return doc.RootElement.TryGetProperty("ok", out var ok) && ok.ValueKind == System.Text.Json.JsonValueKind.True;
        }
        catch { return false; }
    }

    async void ToggleLayoutService(bool start)
    {
        if (_serviceBusy) return;
        _serviceBusy = true;
        ShowLayoutService();
        var script = System.IO.Path.Combine(Paths.Root, "system_core", "ocr_brick", "Layout.Service.ps1");
        int port = _hardware is { LayoutPort: > 0 } machine ? machine.LayoutPort : 8771;
        AppendLines(new[] { "", "[GUI] " + Lang.T(start ? "запускаю сервис разметки Surya" : "останавливаю сервис разметки Surya") + ": " + Paths.Short(script) });
        try
        {
            var info = new System.Diagnostics.ProcessStartInfo(Paths.PowerShell)
            {
                UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Paths.Root,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = System.Text.Encoding.UTF8, StandardErrorEncoding = System.Text.Encoding.UTF8,
            };
            // Started by the window, PowerShell has no console and writes into the pipe in the OEM
            // page (cp866): read as UTF-8, a Russian word of the script came out as "????". So the
            // script is run by -Command, with UTF-8 set first - as system_core\core\hardware.py does.
            var command = "try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }; & "
                + PowerShellLiteral(script) + (start ? " -Enable" : " -Disable") + "; exit $LASTEXITCODE";
            foreach (var word in new[] { "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command }) info.ArgumentList.Add(word);
            using var process = System.Diagnostics.Process.Start(info) ?? throw new InvalidOperationException("the process was not created");
            var output = process.StandardOutput.ReadToEndAsync();
            var errors = process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync();
            // The service it started may hold the pipes: what the script said is read for a moment, not to its end.
            await Task.WhenAny(Task.WhenAll(output, errors), Task.Delay(3000));
            var said = (output.IsCompletedSuccessfully ? output.Result : "") + (errors.IsCompletedSuccessfully ? errors.Result : "");
            AppendLines(said.Split('\n').Select(text => text.TrimEnd('\r')).Where(text => text.Trim().Length > 0).ToList(), told: true);
            // The service loads its model before it answers: it is waited for, a minute at most.
            bool up = await LayoutUp(port);
            for (int i = 0; i < (start ? 60 : 10) && up != start; i++)
            {
                await Task.Delay(1000);
                up = await LayoutUp(port);
            }
            if (_hardware is { } told) told.LayoutUp = up;
            AppendLines(new[] { "[GUI] " + Lang.T(up == start
                ? (up ? "сервис разметки Surya работает" : "сервис разметки Surya остановлен")
                : (start ? "сервис разметки Surya не ответил за минуту - подробности в logs" : "сервис разметки Surya всё ещё отвечает")) });
        }
        catch (Exception ex) { AppendLines(new[] { "[ERR] " + Lang.F("сервис разметки Surya: {0}", ex.Message) }); }
        finally
        {
            _serviceBusy = false;
            FillOcr();
            ShowLayoutService();
        }
    }

    /// <summary>
    /// A path as a PowerShell literal in single quotes. Every sign PowerShell takes for a single
    /// quote is doubled, the typographic ones too: a folder named O’Brien would end the literal
    /// otherwise, and the rest of the name would be read as code.
    /// </summary>
    static string PowerShellLiteral(string value)
    {
        var text = new System.Text.StringBuilder(value.Length + 2).Append('\'');
        foreach (var sign in value)
        {
            text.Append(sign);
            if ("'‘’‚‛".Contains(sign)) text.Append(sign);
        }
        return text.Append('\'').ToString();
    }

    // ------------------------------------------------------------ the keys of the providers

    /// <summary>
    /// A small button of a key field. ADD: the key is typed into a dialog, unseen, and goes to the
    /// door by its standard input; the door writes it into a file of config and the field takes
    /// that file. SET ASIDE: the file chosen goes to config\deleted_keys after a question. Every
    /// list of keys and models is asked anew afterwards - what the program kept is stale.
    /// </summary>
    async void PressKey(string kind, Field field)
    {
        if (_asking || _view is not { } view || field.KeyProvider.Length == 0) return;
        var provider = Providers.FirstOrDefault(one => one.Id == field.KeyProvider);
        var name = provider.Name ?? field.KeyProvider;
        var held = _store.Of(view.Page);
        _asking = true;
        ApplyBusy();
        try
        {
            if (kind == "add")
            {
                var secret = await Views.PromptDialog.Ask(this, new Asked("key", true, Lang.F("Ключ {0}", name), Lang.T("Ключ API"),
                    Lang.F("Ключ запишется в новый файл в папке config программы и станет ключом этого поля. В окне и в журнале он не показывается; уходит только поставщику {0} вместе с запросом.", name), Lang.T("ДОБАВИТЬ")));
                if (string.IsNullOrWhiteSpace(secret)) { SetStatus("Ключ не добавлен."); return; }
                var (file, trouble) = await Door.Key("add", field.KeyProvider, "", secret.Trim());
                if (trouble.Length > 0) { Say(Lang.F("ключ {0} не добавлен: {1}", name, trouble), refused: true); return; }
                AppendLines(new[] { "[GUI] " + Lang.F("ключ {0} добавлен: {1}", name, file) });
                KeysChanged();
                held.Set(field, file);
                SetStatus(Lang.F("Ключ {0} добавлен: {1}", name, file));
            }
            else
            {
                var file = held.Get(field);
                if (file.Length == 0) return;
                if (!await Views.AskDialog.YesNo(this, Lang.F("Убрать ключ {0}?", name),
                        Lang.F("Файл ключа переносится в config\\deleted_keys\\{0} - оттуда его можно вернуть.", field.KeyProvider) + "\n\n" + file, "burn")) return;
                var (archived, trouble) = await Door.Key("remove", field.KeyProvider, file, "");
                if (trouble.Length > 0) { Say(Lang.F("ключ {0} не убран: {1}", name, trouble), refused: true); return; }
                AppendLines(new[] { "[GUI] " + Lang.F("ключ {0} убран: {1} → {2}", name, file, archived) });
                KeysChanged();
                held.Set(field, "");
                SetStatus(Lang.F("Ключ {0} убран в {1}", name, archived));
            }
        }
        finally
        {
            _asking = false;
            ApplyBusy();
        }
    }

    /// <summary>The key files changed: the lists the program keeps are read again, the badge counts again.</summary>
    void KeysChanged()
    {
        _ = RefreshKept();
        _ = AskHardware();
    }

    /// <summary>
    /// The lists the program keeps - the cache of models, the key files - read again by one call of
    /// the door (describe), not by a call for every list of every page. Until the answer comes the
    /// pages show what they had; then every page that holds a list is built again from the new ones.
    /// A door that did not answer leaves no kept list: each page asks its own.
    /// </summary>
    async Task RefreshKept()
    {
        var (told, _) = await Door.Describe();
        Form.Kept = told?.Lists ?? new Dictionary<string, List<Kept>>();
        bool here = false;
        foreach (var view in _views.Values)
        {
            if (!view.Form.DropListsAfterRun()) continue;
            view.Stale = true;
            here |= ReferenceEquals(view, _view);
        }
        if (here) RebuildSoon();
    }

    /// <summary>The door is asked what this machine has for OCR; one question at a time.</summary>
    async Task AskHardware()
    {
        if (_hardwareAsked || !Door.Ready) return;
        _hardwareAsked = true;
        try
        {
            if (await Door.Hardware() is { } told)
            {
                _hardware = told;
                FillOcr();
                ShowLayoutService();
                // At the start, a machine without Tesseract has nothing to read a scan with here: the
                // window opens on the first section of the header (SETUP) - unless the person has
                // already gone somewhere or opened a sheet while the machine was being asked.
                if (_startOpen && !told.TesseractFound && _sheet.Length == 0
                    && _told?.Layout.Sections.FirstOrDefault(section => section.InHeader) is { } setup)
                    SelectSection(setup);
            }
        }
        finally
        {
            _hardwareAsked = false;
            _startOpen = false;
        }
    }
}
