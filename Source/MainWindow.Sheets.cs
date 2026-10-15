using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using AudionOfficeOcrAi.Core;

namespace AudionOfficeOcrAi;

/// <summary>
/// SETTINGS and ABOUT, the way Audion Disk Tools has them: two buttons at the right of the header,
/// each opens its sheet in place of the sections and their pages; the same button, the cross or
/// Esc brings the sections back. A sheet is cards with a name in two columns. SETTINGS holds what
/// a person sets once and forgets - the colours, the fonts and their sizes - and nothing an
/// operation asks for: that stands on its page.
/// </summary>
public partial class MainWindow
{
    string _sheet = "";

    void ToggleSheet(string key)
    {
        _sheet = _sheet == key ? "" : key;
        SheetSettings.IsChecked = _sheet == "settings";
        SheetAbout.IsChecked = _sheet == "about";
        MarkSections();
        bool open = _sheet.Length > 0;
        SectionRow.IsVisible = Zones.IsVisible = !open;
        SheetHost.IsVisible = open;
        FillSheet();
        if (!open) Shell.Focus();
    }

    /// <summary>The sheet in sight is written again: a setting changed, or the language did.</summary>
    void FillSheet()
    {
        SheetBody.Children.Clear();
        _into = null;
        if (_sheet == "settings") FillSettings();
        else if (_sheet == "about") FillAbout();
        else return;
        if (Lang.Code != "ru") Lang.Walk(SheetBody);
        CentreWords();
    }

    // ------------------------------------------------------------ what a sheet is put together of

    /// <summary>Open starts a card with a name in a column; Add, Note and Pair go into it until the next Open.</summary>
    Panel? _into;

    void Add(Control control) => (_into ?? SheetBody).Children.Add(control);

    void Head(string text) => SheetBody.Children.Add(new TextBlock
    {
        Text = text, FontWeight = FontWeight.SemiBold, FontSize = 16, Margin = new Thickness(0, 0, 0, 8),
    });

    (StackPanel Left, StackPanel Right) Columns()
    {
        var columns = new Grid { ColumnDefinitions = new ColumnDefinitions("*,16,*") };
        var left = new StackPanel { Spacing = 10 };
        var right = new StackPanel { Spacing = 10 };
        Grid.SetColumn(right, 2);
        columns.Children.Add(left);
        columns.Children.Add(right);
        _into = null;
        SheetBody.Children.Add(columns);
        return (left, right);
    }

    StackPanel Below()
    {
        var below = new StackPanel { Margin = new Thickness(0, 10, 0, 0) };
        _into = null;
        SheetBody.Children.Add(below);
        return below;
    }

    void Open(Panel column, string title)
    {
        var body = new StackPanel { Spacing = 2 };
        body.Children.Add(new TextBlock { Text = title, Classes = { "caption" }, Margin = new Thickness(0, 0, 0, 4) });
        column.Children.Add(new Border { Classes = { "subcard" }, Child = body });
        _into = body;
    }

    void Note(string text) => Add(new TextBlock { Text = text, Classes = { "note" } });

    void Pair(string key, string value, int keyWidth = 130)
    {
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions($"{keyWidth},*") };
        row.Children.Add(new TextBlock { Text = key, Classes = { "caption" }, VerticalAlignment = VerticalAlignment.Top, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 10, 0) });
        var shown = new SelectableTextBlock { Text = value, TextWrapping = TextWrapping.Wrap };
        Grid.SetColumn(shown, 1);
        row.Children.Add(shown);
        Add(row);
    }

    static WrapPanel Chips() => new() { Orientation = Orientation.Horizontal, ItemSpacing = 6, LineSpacing = 6, Margin = new Thickness(0, 2, 0, 4) };

    ToggleButton Chip(string label, bool chosen, string tip, Action press)
    {
        var chip = new ToggleButton { Content = label, Classes = { "switch" }, IsChecked = chosen };
        if (tip.Length > 0) ToolTip.SetTip(chip, Lang.T(tip));
        chip.Click += (_, _) => press();
        return chip;
    }

    // ------------------------------------------------------------ SETTINGS

    // Inter and JetBrains Mono ship inside the program; the rest are offered when Windows has them.
    // Only families a list names: a face the program cannot read brought a window down once.
    static readonly string[] WindowFonts = { "Inter", "JetBrains Mono", "Segoe UI", "Segoe UI Variable Text", "Arial", "Tahoma", "Verdana", "Calibri", "Cascadia Mono", "Consolas" };
    static readonly string[] TerminalFonts = { "JetBrains Mono", "Cascadia Mono", "Cascadia Code", "Consolas", "Lucida Console", "Courier New" };

    void FillSettings()
    {
        Head("SETTINGS");
        var (left, right) = Columns();

        Open(left, "ЦВЕТА");
        var themes = Chips();
        foreach (var (look, name) in new[] { ("codedark", "AUDION CODE DARK"), ("vault", "AUDION VAULT DARK"), ("dark", "AUDION DARK"), ("light", "AUDION LIGHT") })
            themes.Children.Add(Chip(name, _settings.Look == look, "", () => SetTheme(look)));
        Add(themes);

        var installed = new HashSet<string>(FontManager.Current.SystemFonts.Select(font => font.Name), StringComparer.OrdinalIgnoreCase) { "Inter", "JetBrains Mono" };
        Open(right, "ШРИФТ ОКНА");
        FontRow(WindowFonts.Where(installed.Contains), _settings.UiFont.Length > 0 ? _settings.UiFont : App.UsualWindowFont, family => _settings.UiFont = family,
            13 + _settings.UiShift, 12, 15, size => _settings.UiShift = size - 13);
        Note("Размер — основного текста; названия, подписи и бейджи идут за ним.");

        Open(right, "ШРИФТ ТЕРМИНАЛА");
        FontRow(TerminalFonts.Where(installed.Contains), _settings.LogFont, family => _settings.LogFont = family,
            _settings.LogSize, 9, 14, size => _settings.LogSize = size);

        var reset = new Button { Content = Lang.T("К УМОЛЧАНИЯМ"), Classes = { "small" }, HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 10, 0, 0) };
        ToolTip.SetTip(reset, Lang.T("Вернуть тему, шрифты и размеры к значениям программы."));
        reset.Click += (_, _) =>
        {
            _settings.UiFont = _settings.LogFont = "";
            _settings.UiShift = 0;
            _settings.LogSize = Settings.UsualLogSize;
            ApplyFonts();
            // Saves the settings and writes the sheet again.
            SetTheme("codedark");
        };
        _into = null;
        SheetBody.Children.Add(reset);
    }

    /// <summary>The families as chips, each written in itself, and "− 13 +": half a point a step.</summary>
    void FontRow(IEnumerable<string> families, string chosen, Action<string> setFamily, double size, double min, double max, Action<double> setSize)
    {
        if (chosen.Length == 0) chosen = "JetBrains Mono";
        var row = Chips();
        foreach (var family in families)
        {
            var chip = new ToggleButton
            {
                Content = family, Classes = { "switch" }, FontFamily = App.Family(family),
                IsChecked = string.Equals(family, chosen, StringComparison.OrdinalIgnoreCase),
            };
            chip.Click += (_, _) => { setFamily(family); FontsChanged(); };
            row.Children.Add(chip);
        }
        var minus = new Button { Content = "−", Classes = { "small" }, Padding = new Thickness(10, 0) };
        var value = new TextBlock { Text = size.ToString("0.#", CultureInfo.InvariantCulture), VerticalAlignment = VerticalAlignment.Center, MinWidth = 34, TextAlignment = TextAlignment.Center };
        var plus = new Button { Content = "+", Classes = { "small" }, Padding = new Thickness(10, 0) };
        void Step(double delta)
        {
            var next = Math.Clamp(Math.Round((size + delta) * 2) / 2, min, max);
            if (next == size) return;
            setSize(next);
            FontsChanged();
        }
        minus.Click += (_, _) => Step(-0.5);
        plus.Click += (_, _) => Step(0.5);
        // One piece of the row: a line that wraps takes the three of them along, never the plus alone.
        row.Children.Add(new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(12, 0, 0, 0), Children = { minus, value, plus } });
        Add(row);
    }

    void FontsChanged()
    {
        _settings.Save();
        ApplyFonts();
        FillSheet();
    }

    /// <summary>The fonts and the sizes of the settings into the window: at its start and at every change.</summary>
    void ApplyFonts()
    {
        App.SetFonts(_settings.UiFont, _settings.LogFont);
        App.SetSizes(_settings.UiShift, _settings.LogSize);
        // Every page was laid out for the font before: the widths of its columns are counted by its words.
        OutdateAll(lists: false);
        CentreWords();
    }

    // ------------------------------------------------------------ ABOUT

    static Avalonia.Media.Imaging.Bitmap Brand(string file) =>
        new(Avalonia.Platform.AssetLoader.Open(new Uri($"avares://AudionOfficeOcrAi/Assets/brand/{file}")));

    /// <summary>Brand pictures are large and shown small: the default scaler turns them soft, the high-quality one keeps the lines clean.</summary>
    static Image Sharp(Image image)
    {
        RenderOptions.SetBitmapInterpolationMode(image, Avalonia.Media.Imaging.BitmapInterpolationMode.HighQuality);
        return image;
    }

    /// <summary>A domain as a link: opens in the default browser.</summary>
    static Button Link(string domain)
    {
        var link = new Button { Content = domain, Classes = { "crumb", "link" }, Padding = new Thickness(0, 1), Margin = new Thickness(0, 0, 16, 0) };
        link.Click += (_, _) =>
        {
            try { Process.Start(new ProcessStartInfo("https://" + domain) { UseShellExecute = true }); }
            catch { }
        };
        return link;
    }

    void FillAbout()
    {
        // Audion is the family of the programs, Tensionix their author. The dark mark carries its own
        // near-black plate; the light theme takes the light one, as the rules of the brand ask.
        SheetBody.Children.Add(Sharp(new Image
        {
            Source = Brand(_settings.Look == "light" ? "Audion_Lockup_Light_1800.png" : "Audion_Lockup_Dark_1800.png"),
            Height = 56, HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 0, 0, 10),
        }));
        Head("Office OCR AI");
        Note("Офисные документы, PDF и сканы - в проверяемый Markdown и обратно в DOCX, XLSX, PDF и PPTX: локальный OCR (Tesseract, Surya), OCR поставщиков по ключу, координатные таблицы, проверка чисел, документация в PDF. Портативная: всё своё хранит рядом с собой.");
        _into = null;

        var (left, right) = Columns();
        Open(left, "ВЕРСИЯ И ПЛАТФОРМА");
        Pair("Версия", Paths.Version ?? "—");
        Pair("Система", RuntimeInformation.OSDescription);
        Pair(".NET", Environment.Version.ToString());
        Pair("Avalonia", typeof(AvaloniaObject).Assembly.GetName().Version?.ToString() ?? "");

        Open(right, "ПАПКИ");
        Pair("Программа", Paths.Root);
        Pair("Настройки окна", Settings.FilePath);
        Pair("Журналы", Paths.ProgramLogs);
        if (_told is not null)
        {
            Pair("input", _told.Paths.Input);
            Pair("output", _told.Paths.Output);
            Pair("report", _told.Paths.Report);
        }

        Open(Below(), "АВТОР");
        // Beside Audion Tensionix takes its amber mark; no amber lockup exists, so the word is set here in the brand face.
        var author = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, Margin = new Thickness(0, 2, 0, 4) };
        author.Children.Add(Sharp(new Image { Source = Brand("Tensionix_Mark_Amber_256.png"), Height = 32, Width = 32 }));
        author.Children.Add(new TextBlock
        {
            Text = "Tensionix", FontFamily = new FontFamily("Cascadia Mono, Consolas, monospace"),
            FontSize = 18, FontWeight = FontWeight.SemiBold, VerticalAlignment = VerticalAlignment.Center,
        });
        Add(author);
        var links = new StackPanel { Orientation = Orientation.Horizontal };
        links.Children.Add(Link("audion.dev"));
        links.Children.Add(Link("tensionix.com"));
        Add(links);
        _into = null;
    }
}
