using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using AudionOfficeOcrAi.Core;

namespace AudionOfficeOcrAi.Views;

/// <summary>
/// The form of an operation, drawn by the keys of the manifest. A field is in sight while its
/// conditions hold (`hidden`, `hidden_when`, `visible_when`); the fields stand in the blocks the
/// manifest names (`section`). A choice is a row of switches, never a drop-down list. A list the
/// manifest does not write - the versions a vendor has, what is installed - is asked of the door
/// when the field is shown, and asked again when a field it depends on changes.
/// The form keeps nothing itself: every control reads and writes the <see cref="Values"/> of its
/// page by the id of its field - the operations of one page share a field, two pages do not.
/// </summary>
public sealed class Form
{
    readonly Values _values;
    /// <summary>What a change of a field that decides the shape of the form asks for: the cards are built again.</summary>
    readonly Action _rebuild;

    /// <summary>What repaints the controls of a field, by the id of the field: a form built now, gone at the next build.</summary>
    readonly Dictionary<string, List<Action>> _cells = new();
    /// <summary>The fields whose change alters what is in sight or which list is shown.</summary>
    readonly HashSet<string> _shaping = new();

    /// <summary>The lists the door has given, each with its term: by operation, field, the values the list depends on and the source of the page.</summary>
    readonly ListMemory _lists = new();
    readonly HashSet<string> _asking = new();
    /// <summary>Lists are asked two at a time: each is a process of its own, and a page may want a dozen.</summary>
    readonly SemaphoreSlim _lane = new(2);

    /// <summary>Field id - the ticks to set when its next list is shown: carried over by a set that turned a flag (Presets.Carried).</summary>
    readonly Dictionary<string, List<string>> _carried = new();

    /// <summary>Kinds of field met while building that the form cannot draw.</summary>
    public HashSet<string> Unknown { get; } = new();

    /// <summary>The names of the blocks of the forms, by the id the manifest gives them: what the door told.</summary>
    public static Dictionary<string, Block> Blocks { get; set; } = new();

    /// <summary>
    /// The lists the program keeps - the cache of models, the key files - as the door read them at
    /// the start, each with the values it was read for. A form shows one at once while its
    /// values are those; a run that ended or a key added or set aside makes them stale, and they
    /// are forgotten (Forget All).
    /// </summary>
    public static Dictionary<string, List<Kept>> Kept { get; set; } = new();

    /// <summary>A small button of a key field: "add" or "remove", and the field.</summary>
    public Action<string, Field>? KeyPressed { get; set; }

    /// <summary>The keys of the lists REFRESH asked for: the door asks the provider for these, not the files of the program.</summary>
    readonly HashSet<string> _fresh = new();

    /// <summary>The ids of the operations whose block ADDITIONAL is open: a page built again keeps it so.</summary>
    static readonly HashSet<string> OpenMore = new();

    public Form(Values values, Action rebuild)
    {
        _values = values;
        _rebuild = rebuild;
        _values.Changed += _heard = id =>
        {
            if (_shaping.Contains(id)) { _rebuild(); return; }
            if (!_cells.TryGetValue(id, out var repaint)) return;
            foreach (var action in repaint.ToArray()) action();
        };
    }

    readonly Action<string> _heard;

    /// <summary>
    /// The page is thrown away - the language changed. Its values live on for the page built anew,
    /// so this form stops hearing them: it would go on repainting controls nobody sees.
    /// </summary>
    public void Detach() => _values.Changed -= _heard;

    /// <summary>A new build of the cards begins: the controls of the last one are forgotten.</summary>
    public void Forget()
    {
        _cells.Clear();
        _shaping.Clear();
        _sifters.Clear();
        _build++;
    }

    /// <summary>What a list was searched for, by the id of its field: a page built again keeps the search.</summary>
    readonly Dictionary<string, string> _queries = new();
    /// <summary>What shows and hides the cards of each list of the build in hand.</summary>
    readonly List<Action> _sifters = new();
    string _pageQuery = "";

    /// <summary>
    /// The search of the whole page - a catalogue: every list of the form shows the cards that
    /// hold every word, and a list with none of them steps aside. Cards are hidden, nothing is
    /// built again (Core\Search.cs).
    /// </summary>
    public string PageQuery
    {
        get => _pageQuery;
        set
        {
            if (_pageQuery == value) return;
            _pageQuery = value;
            foreach (var sift in _sifters.ToArray()) sift();
        }
    }

    /// <summary>The number of the build of the cards in hand: rows left to build for an older one are dropped.</summary>
    int _build;

    /// <summary>
    /// The rows of a long list below the first screen are built a row at a time, while nothing else
    /// goes on. False - the whole form at once: a form built again in place must be as tall as it
    /// was, or the page would jump.
    /// </summary>
    public bool Lazy { get; set; } = true;

    /// <summary>Raised when a row built later has joined the form: its words want centring too.</summary>
    public Action? Grown { get; set; }

    /// <summary>
    /// The folders of the page: where its operations read from ("" - the page reads no folder) and
    /// where the downloads go. A list is asked with them, and one asked in another source is
    /// another list.
    /// </summary>
    public Func<(string Source, string Target)>? Folders { get; set; }

    /// <summary>A list of the form is being asked of the door right now.</summary>
    public bool Asking => _asking.Count > 0;

    /// <summary>How many lists the form has asked of the door so far: a check reads it.</summary>
    public int Asked { get; private set; }

    /// <summary>The lists are asked anew at the next build: the language changed, or the person asked.</summary>
    public void DropLists() => _lists.Clear();

    /// <summary>The page comes into sight: the lists older than their term are forgotten. True when one was - the page is to be built again.</summary>
    public bool DropExpiredLists() => _lists.DropExpired();

    /// <summary>A run ended well: the lists about the machine are forgotten, the catalogues of vendors stay. True when one was forgotten.</summary>
    public bool DropListsAfterRun() => _lists.DropAfterRun();

    void Watch(Field field, Action repaint)
    {
        if (!_cells.TryGetValue(field.Id, out var list)) _cells[field.Id] = list = new List<Action>();
        list.Add(repaint);
        repaint();
    }

    static string Upper(string text) => text.ToUpper(CultureInfo.CurrentCulture);

    public bool InSight(Field field) =>
        !field.Hidden && !FieldKinds.Matches(field.HiddenWhen, _values.Get)
        && (field.VisibleWhen is not { Count: > 0 } || FieldKinds.Matches(field.VisibleWhen, _values.Get));

    public bool InSight(Dictionary<string, JsonElement>? condition) =>
        condition is not { Count: > 0 } || FieldKinds.Matches(condition, _values.Get);

    /// <summary>The conditions of a card name these fields: when one of them changes, the card is another card.</summary>
    public void Shapes(IEnumerable<string> ids)
    {
        foreach (var id in ids) _shaping.Add(id);
    }

    // ------------------------------------------------------------ the form

    /// <summary>
    /// The fields of an operation in sight, block by block in the order the manifest first names
    /// each block. A field that is the pages of the form (`tabs`) is no field of a block: it is a
    /// band of large switches, handed back apart - the window keeps it over the form, where it
    /// does not scroll away.
    /// </summary>
    public Control Build(Node node, out Control? bands)
    {
        _values.Learn(node.Fields);
        foreach (var field in node.Fields)
        {
            if (field.VisibleWhen is not null) Shapes(field.VisibleWhen.Keys);
            if (field.HiddenWhen is not null) Shapes(field.HiddenWhen.Keys);
            if (field.Dynamic) Shapes(field.DependsOn);
            foreach (var preset in field.Presets)
                if (preset.VisibleWhen is not null) Shapes(preset.VisibleWhen.Keys);
        }
        var host = new StackPanel { Spacing = 6 };
        // The names of the fields of every block take one width: the controls begin on one line.
        Grid.SetIsSharedSizeScope(host, true);
        var seen = node.Fields.Where(InSight).ToList();
        var pages = seen.Where(field => field.Kind == "tabs").ToList();
        bands = pages.Count == 0 ? null : new StackPanel { Spacing = 6 };
        foreach (var field in pages) ((StackPanel)bands!).Children.Add(Band(node, field));
        var shown = seen.Where(field => field.Kind != "tabs").ToList();
        foreach (var group in InOrder(shown.Where(field => !field.Advanced).GroupBy(field => field.Group), node.Groups))
            if (Block(node, GroupName(group.Key), group.ToList()) is { } block) host.Children.Add(block);
        // What is rarely needed stands under ADDITIONAL, after every block, closed until it is opened.
        var more = shown.Where(field => field.Advanced).ToList();
        if (more.Count > 0) host.Children.Add(More(node, more));
        return host;
    }

    /// <summary>One block of a form: its name, its fields laid out by their kinds; null when nothing of it is drawn.</summary>
    Control? Block(Node node, string name, List<Field> group)
    {
        var body = new StackPanel();
        // The names of the first choices of the block took the line of its name: the block is not named a second time.
        bool headed = false;
        WrapPanel? flags = null;
        var lists = new List<Field>();
        var lines = new List<Field>();
        void Lists()
        {
            if (lists.Count > 0) body.Children.Add(Groups(node, lists));
            lists.Clear();
        }
        void Lines()
        {
            if (lines.Count == 0) return;
            // Only the fields a named block begins with: there the line of the name is theirs.
            body.Children.Add(TwoColumns(node, lines, name.Length > 0 && body.Children.Count == 0, out bool took));
            headed |= took;
            lines.Clear();
        }
        foreach (var field in group)
        {
            if (!FieldKinds.Known.Contains(field.Kind)) { Unknown.Add($"{field.Id}: {field.Kind}"); continue; }
            if (field.Kind == "checkboxes") { flags = null; Lines(); lists.Add(field); continue; }
            Lists();
            if (field.Kind == "checkbox")
            {
                Lines();
                // Flags that follow one another stand in one row.
                if (flags is null) body.Children.Add(flags = new WrapPanel { Orientation = Orientation.Horizontal });
                flags.Children.Add(Flag(field));
                continue;
            }
            flags = null;
            // A text of many lines takes the whole width; the fields of one line share it by two.
            if (field.Kind is "textarea" or "markdown_editor") { Lines(); body.Children.Add(Cell(node, field)); }
            else lines.Add(field);
        }
        Lists();
        Lines();
        if (body.Children.Count == 0) return null;
        if (name.Length > 0 && !headed) body.Children.Insert(0, new TextBlock { Classes = { "grp" }, Text = Upper(name) });
        // A block that is nothing but groups of ticks needs no frame around their frames.
        bool onlyLists = group.All(field => field.Kind == "checkboxes");
        var framed = onlyLists && name.Length == 0 ? (Control)body : new Border { Classes = { "grp" }, Child = body };
        // The stripe at the left of a block says what kind of settings it holds (П1-П7 of the window on NiceGUI).
        if (framed is Border border && group.Count > 0 && Stripes.TryGetValue(group[0].Group, out var stripe)) Stripe(border, stripe);
        return framed;
    }

    /// <summary>The colour of the stripe of a block by its id, as the window on NiceGUI had them; a block not named has none.</summary>
    static readonly Dictionary<string, string> Stripes = new()
    {
        ["encoding"] = "#5ad7ff", ["deliverables"] = "#d97757", ["filters"] = "#29d17d", ["local_access"] = "#f59e0b",
        ["output"] = "#60a5fa", ["model"] = "#8b5cf6", ["access"] = "#8b5cf6", ["cloud_access"] = "#8b5cf6", ["parameters"] = "#ec4899",
    };

    /// <summary>
    /// A stripe 3 px wide down the left of a block, the rest of its rim as the theme draws it: one brush
    /// that is the colour up to 3 px from the left edge and the rim after it.
    /// </summary>
    static void Stripe(Border border, string colour)
    {
        var rim = App.Ink("SepInk") is ISolidColorBrush solid ? solid.Color : Colors.Gray;
        var tone = Color.Parse(colour);
        border.BorderThickness = new Thickness(3, 1, 1, 1);
        border.BorderBrush = new LinearGradientBrush
        {
            StartPoint = new RelativePoint(0, 0, RelativeUnit.Absolute),
            EndPoint = new RelativePoint(3, 0, RelativeUnit.Absolute),
            SpreadMethod = GradientSpreadMethod.Pad,
            GradientStops = { new GradientStop(tone, 0), new GradientStop(tone, 0.999), new GradientStop(rim, 1) },
        };
    }

    /// <summary>
    /// ADDITIONAL: the fields the manifest marks as rarely needed, under a head that opens and
    /// closes them - each in the block it belongs to, inside.
    /// </summary>
    Control More(Node node, List<Field> fields)
    {
        bool open = OpenMore.Contains(node.Id);
        var body = new StackPanel { Spacing = 6, Margin = new Thickness(0, 6, 0, 0), IsVisible = open };
        foreach (var group in InOrder(fields.GroupBy(field => field.Group), node.Groups))
            if (Block(node, GroupName(group.Key), group.ToList()) is { } block) body.Children.Add(block);
        var arrow = Icons.Sign(open ? "chevron-down" : "chevron-right");
        var head = new ToggleButton
        {
            Classes = { "switch" }, IsChecked = open, HorizontalAlignment = HorizontalAlignment.Left,
            Content = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, Children = { arrow, new TextBlock { Text = Lang.F("ДОПОЛНИТЕЛЬНО · {0}", fields.Count) } } },
        };
        Avalonia.Automation.AutomationProperties.SetAutomationId(head, "more_" + node.Id);
        ToolTip.SetTip(head, Lang.T("Настройки, которые нужны редко: значения программы подходят для большинства документов."));
        head.Click += (_, _) =>
        {
            open = head.IsChecked == true;
            if (open) OpenMore.Add(node.Id); else OpenMore.Remove(node.Id);
            body.IsVisible = open;
            arrow.Data = Icons.Glyph(open ? "chevron-down" : "chevron-right");
            Grown?.Invoke();
        };
        return new StackPanel { Margin = new Thickness(0, 2, 0, 0), Children = { head, body } };
    }

    /// <summary>
    /// Fields of one line that follow one another, in two columns with a rule between them: the
    /// first half at the left, the rest at the right (the owner, 10.10.2026: "look how much room
    /// there is at the right ... in two columns, parted by a stick"). One field, or a block too
    /// narrow for two rows of switches side by side, stays one column.
    ///
    /// With <paramref name="heads"/> the first field of each column gives its name to the line
    /// where the name of the block stood, and its row of switches takes the whole width of the
    /// column (the owner, 11.10.2026, of "Product" and "Chip generation": "they take VERY much
    /// room. They should simply stand at the top in place of the name of the block, on the same
    /// line: the chips get more room, and there is no gaping emptiness") - a name at the left of
    /// a row three lines tall held a column of nothing. Only when every column begins with a
    /// choice that has a name: the names then stand on one line.
    ///
    /// The row under such a name stands at the indent of the rows under it (the owner, the same
    /// day, of the image page, where the product began at the rim and the platform and the edition
    /// after their names: "the upper rows of buttons must be at the same indent as the lower
    /// ones"): in the column of the values when its column has rows with names at their left, at
    /// the rim when it has none.
    /// </summary>
    Control TwoColumns(Node node, List<Field> fields, bool heads, out bool took)
    {
        int half = fields.Count < 2 ? fields.Count : (fields.Count + 1) / 2;
        static bool Heads(Field field) => field.Kind is "radio" or "select" && field.View != "dropdown" && field.Name.Length > 0;
        bool second = half < fields.Count;
        took = heads && Heads(fields[0]) && (!second || Heads(fields[half]));
        var lines = new List<Control>();
        for (int i = 0; i < fields.Count; i++)
        {
            var field = fields[i];
            if (!took || (i != 0 && i != half)) { lines.Add(Cell(node, field)); continue; }
            var head = new TextBlock { Classes = { "grp" }, Text = Upper(field.Name) };
            if (field.Tip.Length > 0) ToolTip.SetTip(head, field.Tip);
            Control row = Choice(node, field);
            // The rows under it in its column that carry a name at their left: this row lines up with their switches.
            var under = i == 0 ? fields.Skip(1).Take(half - 1) : fields.Skip(half + 1);
            if (under.Any(other => other.Name.Length > 0))
            {
                var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
                line.ColumnDefinitions[0].SharedSizeGroup = "FieldName";
                Grid.SetColumn(row, 1);
                line.Children.Add(row);
                row = line;
            }
            row.Margin = new Thickness(0, 0, 0, 2);
            lines.Add(new StackPanel { Children = { head, row } });
        }
        var left = new StackPanel();
        if (lines.Count < 2)
        {
            foreach (var line in lines) left.Children.Add(line);
            return left;
        }
        var right = new StackPanel();
        for (int i = 0; i < lines.Count; i++) (i < half ? left : right).Children.Add(lines[i]);
        var rule = new Border { Width = 1, Margin = new Thickness(0, 1, 0, 5), HorizontalAlignment = HorizontalAlignment.Center }.Ink(Border.BackgroundProperty, "SepInk");
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,21,*"), RowDefinitions = new RowDefinitions("Auto,Auto") };
        Grid.SetColumn(rule, 1);
        grid.Children.Add(left);
        grid.Children.Add(rule);
        grid.Children.Add(right);
        bool? wide = null;
        void Fit(double width)
        {
            bool now = width >= TwoColumnsFrom;
            if (wide == now) return;
            wide = now;
            rule.IsVisible = now;
            Grid.SetColumn(right, now ? 2 : 0);
            Grid.SetRow(right, now ? 0 : 1);
            Grid.SetColumnSpan(left, now ? 1 : 3);
            Grid.SetColumnSpan(right, now ? 1 : 3);
        }
        Fit(TwoColumnsFrom);
        grid.SizeChanged += (_, e) => Fit(e.NewSize.Width);
        return grid;
    }

    /// <summary>The width from which a block holds two columns of fields: a name and its row of switches, twice.</summary>
    const double TwoColumnsFrom = 760;

    /// <summary>
    /// The cards of a list on columns of equal width, row by row; a row is as tall as the tallest
    /// card in it - a line that wrapped makes its own row taller, not every card of the list.
    /// </summary>
    static void Lay(Grid grid, int columns)
    {
        columns = Math.Max(1, columns);
        // Only the cards in sight take a place: a search hides cards, and what is left closes up.
        var shown = grid.Children.Where(card => card.IsVisible).ToList();
        int rows = Math.Max(1, (shown.Count + columns - 1) / columns);
        // A hidden card is given the first cell: a grid measured with a child in a row it no longer
        // has fails in its layout ("Index was out of range", the walk of 10.10.2026).
        foreach (var card in grid.Children)
        {
            if (card.IsVisible) continue;
            Grid.SetColumn(card, 0);
            Grid.SetRow(card, 0);
        }
        if (grid.ColumnDefinitions.Count != columns)
        {
            grid.ColumnDefinitions.Clear();
            for (int c = 0; c < columns; c++) grid.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        }
        if (grid.RowDefinitions.Count != rows)
        {
            grid.RowDefinitions.Clear();
            for (int r = 0; r < rows; r++) grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        }
        for (int i = 0; i < shown.Count; i++)
        {
            Grid.SetColumn(shown[i], i % columns);
            Grid.SetRow(shown[i], i / columns);
        }
    }

    /// <summary>The gap between two columns of cards with a rule in its middle: eight, the rule, eight.</summary>
    const double RuledGap = 17;

    /// <summary>
    /// The pages of a form - the field of kind `tabs` - as a band of large switches, the way the
    /// sections of the window stand over it, without a line under the name (the owner, 10.10.2026:
    /// "these are the sections of the window: the same as the upper ones, only at the left and
    /// without descriptions").
    /// </summary>
    Control Band(Node node, Field field)
    {
        var band = new Grid();
        var (options, _) = OptionsOf(node, field);
        var buttons = new List<(ToggleButton Button, string Key)>();
        foreach (var option in options.Where(option => !option.Header))
        {
            var button = new ToggleButton
            {
                Classes = { "switch", "section" }, HorizontalAlignment = HorizontalAlignment.Stretch,
                Content = new TextBlock { Classes = { "sectionname" }, Text = Upper(option.Name), HorizontalAlignment = HorizontalAlignment.Center },
            };
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, $"field_{field.Id}_{option.Key}");
            var tip = option.Tip.Length > 0 ? option.Name + "\n" + option.Tip : field.Tip;
            if (tip.Length > 0) ToolTip.SetTip(button, tip);
            var key = option.Key;
            button.Click += (_, _) =>
            {
                _values.Set(field, key);
                button.IsChecked = _values.Get(field) == key;
            };
            if (band.ColumnDefinitions.Count > 0) band.ColumnDefinitions.Add(new ColumnDefinition(new GridLength(6)));
            band.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            Grid.SetColumn(button, band.ColumnDefinitions.Count - 1);
            band.Children.Add(button);
            buttons.Add((button, key));
        }
        Watch(field, () =>
        {
            var current = _values.Get(field);
            foreach (var (button, key) in buttons) button.IsChecked = key == current;
        });
        return band;
    }

    /// <summary>What a field is called to the person: its own name, or - for a list the manifest gives none - the name of its block.</summary>
    public static string NameOf(Field field) => field.Name.Length > 0 ? field.Name : GroupName(field.Group);

    /// <summary>The name of a block of the form, in the language of the window, as the door named it; "" - the block needs none.</summary>
    static string GroupName(string group) =>
        Blocks.TryGetValue(group, out var block) && block.Name.Length > 0 ? block.Name
        : group.Length == 0 || group == "parameters" ? ""
        : char.ToUpperInvariant(group[0]) + group[1..].Replace('_', ' ');

    Control Cell(Node node, Field field)
    {
        Control control = field.Kind switch
        {
            "radio" or "tabs" or "select" => field.View == "dropdown" ? Dropdown(node, field) : Choice(node, field),
            "number" => NumberBox(field),
            // As tall as the manifest says; five lines where it says nothing. The box grows as it is typed in.
            "textarea" or "markdown_editor" => TextBox(field, lines: field.Rows > 0 ? field.Rows : 5),
            "profile_buttons" => Sets(node, field),
            "toggle_buttons" => GroupButtons(field),
            _ => TextBox(field, lines: 1),
        };
        if (field.KeyProvider.Length > 0) control = WithKeyButtons(field, control);
        if (field.Name.Length == 0) return control;
        var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), Margin = new Thickness(0, 0, 0, 2) };
        line.ColumnDefinitions[0].SharedSizeGroup = "FieldName";
        var label = new TextBlock { Classes = { "fieldname" }, Text = field.Name, Margin = new Thickness(1, 0, 14, 4), VerticalAlignment = VerticalAlignment.Center, MaxWidth = 210, TextWrapping = TextWrapping.Wrap };
        if (field.Tip.Length > 0) ToolTip.SetTip(label, field.Tip);
        line.Children.Add(label);
        Grid.SetColumn(control, 1);
        line.Children.Add(control);
        return line;
    }

    /// <summary>
    /// The list of the key files of a provider with two small buttons at its right: ADD a key -
    /// it is typed into a dialog and written into a file of config by the door; SET ASIDE the file
    /// chosen - it goes to config\deleted_keys. The key itself is never shown.
    /// </summary>
    Control WithKeyButtons(Field field, Control list)
    {
        Button Small(string sign, string kind, string tip, bool burn)
        {
            var button = new Button { Classes = { "tool" }, Content = Icons.Sign(sign), Margin = new Thickness(4, 0, 0, 4), VerticalAlignment = VerticalAlignment.Top };
            button.Classes.Set("burn", burn);
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, $"key_{kind}_{field.KeyProvider}");
            ToolTip.SetTip(button, Lang.T(tip));
            button.Click += (_, _) => KeyPressed?.Invoke(kind, field);
            return button;
        }
        var add = Small("plus", "add", "Добавить ключ: вставить его в окно, программа запишет файл в config. Ключ нигде не показывается.", false);
        var remove = Small("trash-2", "remove", "Убрать выбранный файл ключа: он переносится в config\\deleted_keys, не удаляется.", true);
        // The line of the current key - its value is empty - is no file to set aside.
        Watch(field, () => remove.IsEnabled = _values.Get(field).Length > 0);
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto") };
        row.Children.Add(list);
        Grid.SetColumn(add, 1);
        row.Children.Add(add);
        Grid.SetColumn(remove, 2);
        row.Children.Add(remove);
        return row;
    }

    // ------------------------------------------------------------ controls

    static readonly Geometry Tick = Geometry.Parse("M 1.5,5 L 4,7.5 L 8.5,2.5");

    /// <summary>
    /// A name that carries the star of the chosen ones, and the name without it. The star is drawn
    /// as a sign before the words: a letter of a font sits where its font puts it, and "★" sat off
    /// the middle of its line (the owner, 10.10.2026: "the star is not centred").
    /// </summary>
    static (bool Star, string Words) Starred(string name) =>
        name.Contains('★') ? (true, Regex.Replace(name, @"\s*★\s*", " ").Trim()) : (false, name);

    static Avalonia.Controls.Shapes.Path Star(IBrush ink)
    {
        var star = Icons.Sign("star");
        star.Stroke = ink;
        star.Fill = ink;
        return star;
    }

    static Border TickBox() => new()
    {
        Classes = { "tickbox" },
        Child = new Avalonia.Controls.Shapes.Path { Classes = { "tick" }, Data = Tick },
    };

    static Control Faced(string text) => new StackPanel
    {
        Orientation = Orientation.Horizontal, Spacing = 7,
        Children = { TickBox(), new TextBlock { Text = text, VerticalAlignment = VerticalAlignment.Center } },
    };

    ToggleButton Flag(Field field)
    {
        var flag = new ToggleButton { Classes = { "switch" }, Content = Faced(field.Name), Margin = new Thickness(0, 0, 6, 6) };
        Avalonia.Automation.AutomationProperties.SetAutomationId(flag, "field_" + field.Id);
        if (field.Tip.Length > 0) ToolTip.SetTip(flag, field.Tip);
        flag.Click += (_, _) => _values.Set(field, flag.IsChecked == true ? "true" : "false");
        Watch(field, () => flag.IsChecked = _values.IsOn(field));
        return flag;
    }

    /// <summary>A choice of a few: a row of switches, one of them on.</summary>
    Control Choice(Node node, Field field)
    {
        var row = new WrapPanel { Orientation = Orientation.Horizontal };
        var (options, note) = OptionsOf(node, field);
        if (note is not null) { row.Children.Add(note); return row; }
        var buttons = new List<(ToggleButton Button, string Key)>();
        foreach (var option in options.Where(option => !option.Header))
        {
            var button = new ToggleButton { Classes = { "switch" }, Content = option.Name, Margin = new Thickness(0, 0, 4, 4) };
            // The tone the manifest gives the option (App.axaml, tone-*): the engines, the risky choices in red.
            if (option.Tone.Length > 0) button.Classes.Add("tone-" + option.Tone);
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, $"field_{field.Id}_{option.Key}");
            var tip = option.Tip.Length > 0 ? option.Tip : field.Tip;
            if (tip.Length > 0) ToolTip.SetTip(button, tip);
            var key = option.Key;
            button.Click += (_, _) =>
            {
                _values.Set(field, key);
                // A press on the chosen one must not switch it off: one of the row is always on.
                button.IsChecked = _values.Get(field) == key;
            };
            buttons.Add((button, key));
            row.Children.Add(button);
        }
        Watch(field, () =>
        {
            var current = _values.Get(field);
            foreach (var (button, key) in buttons) button.IsChecked = key == current;
        });
        return row;
    }

    /// <summary>
    /// The blocks of a form in the order the layout names (`groups` of the card): those named first,
    /// as named; a block not named stands after them, as its fields come.
    /// </summary>
    public static List<T> InOrder<T>(IEnumerable<T> blocks, IReadOnlyList<string> order) where T : IGrouping<string, Field>
    {
        var listed = blocks.ToList();
        if (order.Count == 0) return listed;
        int At(T block)
        {
            for (int i = 0; i < order.Count; i++)
                if (order[i] == block.Key) return i;
            return int.MaxValue;
        }
        // A stable sort: blocks of one rank keep the order of their fields.
        return listed.OrderBy(At).ToList();
    }

    /// <summary>
    /// The lines of a drop-down in order: the line of the default (its value is empty), the pinned
    /// options, then the rest - each group as the list has it. A word of trouble (its value begins
    /// with "__") is no line to choose: it is said over the list.
    /// </summary>
    public static List<Option> DropdownOrder(IEnumerable<Option> options)
    {
        var real = options.Where(option => !option.Header && !option.Key.StartsWith("__", StringComparison.Ordinal)).ToList();
        return real.Where(option => option.Key.Length == 0)
            .Concat(real.Where(option => option.Key.Length > 0 && option.Pinned))
            .Concat(real.Where(option => option.Key.Length > 0 && !option.Pinned)).ToList();
    }

    /// <summary>
    /// A choice of many - a hundred models and more: a field that opens its list under itself.
    /// The list has a search; the pinned options stand first; a line carries its pin - a press
    /// pins the option to the head of the list or takes the pin off; a button asks the list anew.
    /// (The owner, 11.10.2026: "the list of models has to be a select. With pins and unpins,
    /// refreshed by the keys." A choice of a few stays a row of buttons.) The list follows the
    /// fields it depends on - the key - as every list of the door does.
    /// </summary>
    Control Dropdown(Node node, Field field)
    {
        var (options, note) = OptionsOf(node, field);
        if (note is not null) return new WrapPanel { Orientation = Orientation.Horizontal, Children = { note } };

        string NameOf(string key) => options.FirstOrDefault(option => !option.Header && option.Key == key)?.Name ?? key;
        var face = new TextBlock { TextTrimming = TextTrimming.CharacterEllipsis, VerticalAlignment = VerticalAlignment.Center };
        var arrow = Icons.Sign("chevron-down");
        arrow.Margin = new Thickness(8, 0, 0, 0);
        Grid.SetColumn(arrow, 1);
        var button = new Button
        {
            Classes = { "dropdown" }, HorizontalAlignment = HorizontalAlignment.Stretch, Margin = new Thickness(0, 0, 0, 4),
            Content = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), Children = { face, arrow } },
        };
        Avalonia.Automation.AutomationProperties.SetAutomationId(button, "field_" + field.Id);
        if (field.Tip.Length > 0) ToolTip.SetTip(button, field.Tip);

        var search = new TextBox { Classes = { "masks" }, PlaceholderText = Lang.T("поиск по списку"), MinHeight = 24, Height = 24, Padding = new Thickness(8, 0), VerticalContentAlignment = VerticalAlignment.Center };
        PixelGrid.Field(search);
        Avalonia.Automation.AutomationProperties.SetAutomationId(search, "find_" + field.Id);
        var refresh = Refresh(node, field);
        refresh.Margin = new Thickness(10, 0, 2, 0);
        Grid.SetColumn(refresh, 1);
        var said = new TextBlock { Classes = { "note", "warn" }, TextWrapping = TextWrapping.Wrap, IsVisible = false, Margin = new Thickness(1, 6, 0, 0) };
        var lines = new StackPanel();
        var panel = new StackPanel
        {
            Children =
            {
                new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), Children = { search, refresh } },
                said,
                new ScrollViewer { Content = lines, MaxHeight = 380, Margin = new Thickness(0, 6, 0, 0), HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled },
            },
        };
        var flyout = new Flyout { Content = panel, Placement = PlacementMode.BottomEdgeAlignedLeft };
        flyout.FlyoutPresenterClasses.Add("dropdown");
        button.Flyout = flyout;

        // What the list could not say as options - no key, a request that failed - is said over it.
        var trouble = string.Join("\n", options.Where(option => !option.Header && option.Key.StartsWith("__", StringComparison.Ordinal)).Select(option => option.Name));

        void Say(string text)
        {
            said.Text = text;
            said.IsVisible = text.Length > 0;
        }

        void Fill()
        {
            lines.Children.Clear();
            var words = Search.Words(search.Text);
            var current = _values.Get(field);
            foreach (var option in DropdownOrder(options).Where(option => Search.Matches(option, words)))
            {
                var line = new Grid { Classes = { "dropline" }, ColumnDefinitions = new ColumnDefinitions("Auto,*") };
                if (field.Pins.Length > 0 && option.Key.Length > 0)
                {
                    var sign = Icons.Sign("pin");
                    var pin = new Button { Classes = { "cardicon" }, Content = sign };
                    if (option.Pinned)
                    {
                        sign.Stroke = Tones.Of("gold").Ink;
                        pin.Opacity = 1;
                    }
                    // A line that is not pinned shows no pin, only its indent (the owner: "the grey pins are
                    // not needed, just the indent"); the pin comes when the pointer is on the line.
                    else pin.Classes.Add("ghost");
                    ToolTip.SetTip(pin, Lang.T(option.Pinned ? "Открепить: строка вернётся в общий список." : "Закрепить: строка встанет в начало списка."));
                    Avalonia.Automation.AutomationProperties.SetAutomationId(pin, $"pin_{field.Id}_{option.Key}");
                    pin.Click += (_, _) => Pin(option);
                    line.Children.Add(pin);
                }
                else line.Children.Add(new Border { Width = 22 });
                var pick = new Button { Classes = { "dropdownrow" }, Content = option.Name };
                pick.Classes.Set("on", option.Key == current);
                if (option.Tip.Length > 0) ToolTip.SetTip(pick, option.Tip);
                Avalonia.Automation.AutomationProperties.SetAutomationId(pick, $"field_{field.Id}_{option.Key}");
                var key = option.Key;
                pick.Click += (_, _) =>
                {
                    _values.Set(field, key);
                    flyout.Hide();
                };
                Grid.SetColumn(pick, 1);
                line.Children.Add(pick);
                lines.Children.Add(line);
            }
            if (lines.Children.Count == 0) lines.Children.Add(new TextBlock { Classes = { "note" }, Text = Lang.T("ничего не найдено"), Margin = new Thickness(4, 2) });
        }

        async void Pin(Option option)
        {
            bool on = !option.Pinned;
            option.Pinned = on;
            // A line just pinned stands first among the pinned, as the door will put it.
            if (on && options.Remove(option)) options.Insert(Math.Max(0, options.FindIndex(other => !other.Header && other.Key.Length > 0)), option);
            Say(trouble);
            Fill();
            var failed = await Door.Pin(node.Id, field.Id, option.Key, on);
            if (failed.Length == 0) return;
            option.Pinned = !on;
            Say(Lang.F("не закреплено: {0}", failed));
            Fill();
        }

        search.TextChanged += (_, _) => Fill();
        flyout.Opening += (_, _) =>
        {
            // As wide as its field, and no narrower than a model's name wants.
            panel.Width = Math.Max(button.Bounds.Width - 18, 420);
            Say(trouble);
            Fill();
        };
        flyout.Opened += (_, _) => search.Focus();
        Watch(field, () => face.Text = NameOf(_values.Get(field)));
        return button;
    }

    /// <summary>
    /// Lists of ticks that follow one another, as framed groups in rows - the way Audion Disk Tools
    /// lays out its masks: a long group takes a row to itself, short ones share a row by two.
    /// </summary>
    Control Groups(Node node, List<Field> fields)
    {
        var host = new StackPanel();
        var known = fields.Select(field => (Field: field, Options: OptionsOf(node, field))).ToList();
        // How many groups share a row: one that is long or has long names stands alone.
        bool Wide(int at) => known[at].Options.Note is not null || Real(known[at].Options.Options).Count > 12
            || Longest(known[at].Options.Options) > 30 || known[at].Options.Options.Any(option => option.Header);
        var rows = new List<(int First, int Count)>();
        for (int i = 0; i < known.Count;)
        {
            int perRow = Wide(i) || i + 1 >= known.Count || Wide(i + 1) ? 1 : 2;
            rows.Add((i, perRow));
            i += perRow;
        }
        Control Row((int First, int Count) at)
        {
            var row = new Grid();
            for (int c = 0; c < at.Count; c++)
            {
                row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
                var block = Ticks(node, known[at.First + c].Field, known[at.First + c].Options.Options, known[at.First + c].Options.Note);
                Grid.SetColumn(block, c);
                row.Children.Add(block);
            }
            return row;
        }
        // The first screen at once - some forty cards; the rows under it one by one, each when the
        // window has nothing else to do. A build that came after drops what is left of this one.
        int build = _build, next = 0, cards = 0;
        for (; next < rows.Count && (!Lazy || cards < 40); next++)
        {
            host.Children.Add(Row(rows[next]));
            for (int c = 0; c < rows[next].Count; c++) cards += Real(known[rows[next].First + c].Options.Options).Count;
        }
        void Later()
        {
            if (build != _build || next >= rows.Count) return;
            host.Children.Add(Row(rows[next++]));
            Grown?.Invoke();
            Dispatcher.UIThread.Post(Later, DispatcherPriority.Background);
        }
        if (next < rows.Count) Dispatcher.UIThread.Post(Later, DispatcherPriority.Background);
        return host;
    }

    /// <summary>
    /// The badge of versions over a list of drivers, as Audion Setup Tools has it: the driver this
    /// PC's device runs against the newest release of the list. Behind - "INSTALLED 6.0.9764 ·
    /// LATEST 6.0.10029", the installed one orange; not behind - "LATEST INSTALLED 6.0.10029" in
    /// green (the owner, 11.10.2026). The two colours are those of the cards under it: of a preview
    /// and of the newest release. Null - the list says nothing of this PC's driver.
    /// </summary>
    static Control? Standing(Option option)
    {
        var parts = StandingWords(option);
        if (parts.Count == 0) return null;
        var line = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(8, 1, 8, 7) };
        foreach (var (text, kind, tone) in parts)
        {
            var part = new TextBlock { Text = kind == "word" ? Lang.T(text) : text, Classes = { kind == "word" ? "badge" : kind == "number" ? "badgenumber" : "count" } };
            if (tone.Length > 0) part.Foreground = Tones.Of(tone).Ink;
            line.Children.Add(part);
        }
        ToolTip.SetTip(line, Lang.T("Драйвер, на котором устройство этого ПК работает сейчас, и новейший выпуск в списке."));
        Avalonia.Automation.AutomationProperties.SetAutomationId(line, "standing");
        return line;
    }

    /// <summary>The parts of the badge of versions in order: the text, what it is - "word", "number", "dot" - and its tone ("" - none, it is faint).</summary>
    public static List<(string Text, string Kind, string Tone)> StandingWords(Option option)
    {
        var parts = new List<(string Text, string Kind, string Tone)>();
        if (option.Running.Length == 0) return parts;
        if (!option.Behind)
        {
            parts.Add(("УСТАНОВЛЕНА ПОСЛЕДНЯЯ", "word", "latest"));
            parts.Add((option.Running, "number", "latest"));
            return parts;
        }
        parts.Add(("УСТАНОВЛЕНА", "word", "beta"));
        parts.Add((option.Running, "number", "beta"));
        if (option.Newest.Length == 0) return parts;
        parts.Add(("·", "dot", ""));
        parts.Add(("ПОСЛЕДНЯЯ", "word", ""));
        parts.Add((option.Newest, "number", ""));
        return parts;
    }

    static List<Option> Real(List<Option> options) => options.Where(option => !option.Header).ToList();

    static int Longest(List<Option> options) => Real(options).Select(option => option.Name.Length).DefaultIfEmpty(0).Max();

    /// <summary>
    /// A group of ticks: a framed block with its name, how many of it are ticked, ALL and NONE,
    /// and its ticks as cards - how they are laid out is told where it is decided, below. The
    /// value is the list of those that are on.
    /// </summary>
    Control Ticks(Node node, Field field, List<Option> options, Control? note)
    {
        var column = new StackPanel();
        // A long name wraps, and the count with ALL and NONE goes under it: on one line it pushed them past the rim.
        var title = new TextBlock { Classes = { "blockname" }, Text = field.Name, TextWrapping = TextWrapping.Wrap };
        if (field.Tip.Length > 0) ToolTip.SetTip(title, field.Tip);
        var head = new WrapPanel { Orientation = Orientation.Horizontal, ItemSpacing = 8, LineSpacing = 2, Margin = new Thickness(0, 0, 0, 6), MinHeight = 20 };
        // A list the manifest gives no name is named by its block: its head begins with the count.
        if (field.Name.Length > 0) head.Children.Add(title);
        column.Children.Add(head);
        var block = new Border { Classes = { "block", "ticks" }, Child = column };
        if (note is not null) { column.Children.Add(note); return block; }
        var real = Real(options);
        // An empty list the door gave may be asked again - the files it looks for may be there now.
        if (real.Count == 0 && field.Dynamic) head.Children.Add(Refresh(node, field));
        if (real.Count == 0)
        {
            column.Children.Add(new TextBlock { Classes = { "note" }, Text = Lang.T("список пуст") });
            return block;
        }
        // A list that answers with words in place of items - "No builds for this platform" - has
        // nothing to tick: its words are said as they are, not drawn as a card with a tick.
        if (real.All(option => option.Key.Length == 0))
        {
            foreach (var said in real) column.Children.Add(new TextBlock { Classes = { "note" }, Text = said.Name, TextWrapping = TextWrapping.Wrap });
            return block;
        }
        // The layout - known once the block has its width. The room a card needs is its tick, its
        // words in the font of the cards, its small buttons and the gap after it.
        //   Names - the packages of a catalogue: as many columns as hold the longest name whole,
        //   four at most. A name is never cut to fit.
        //   Lines of data without headings - the versions a vendor has: two columns of cards with a
        //   rule between them.
        //   A list under headings - the builds of Windows by generation, the drivers of a machine by
        //   kind: every heading is a block of its own, and the blocks stand in two stacks by turns -
        //   the first at the left, the second at the right, the third under the first (the owner,
        //   10.10.2026: "at the left 26H2, at the right 25H2, at the left 24H2 ... or an odd count
        //   leaves empty rows"). Inside a block the cards stand one under another.
        //   A line too long for its place is set a point smaller when that is what it takes, and
        //   wraps inside its card when even that is not enough. Nothing is cut.
        // The cards of this program carry no small buttons of their own.
        const bool versions = false;
        const int signs = 0;
        int longest = Longest(options);
        bool lines = longest > 30, grouped = options.Any(option => option.Header && !option.Note);
        double usual = App.SizeOf("FontCard", 11.5);
        // A letter of the font of the window is 0.61 of its size wide; the names of packages keep the
        // measure their columns were laid out by (6.4 at the usual size).
        // A version is letters and figures of the window's font whatever its length: measured as a line. With the
        // measure of a package name its card came out too narrow for its two signs, and "latest" ran under them.
        double Need(double points) => 20 + longest * (lines || versions ? points * 0.612 : 6.4 * points / 11.5) + signs * 22 + 26;
        var sheets = new List<(Panel Host, Grid Grid, Border Rule)>();
        var cards = new List<(Border Card, ToggleButton Tick, TextBlock Name)>();
        var blocks = new List<Border>();
        // Every card with its option and the block of the heading it stands under: what a search shows and hides,
        // and what the two columns are balanced by.
        var faces = new List<(Border Card, Option Option, Border? Under)>();
        StackPanel leftStack = new(), rightStack = new();
        Grid.SetColumn(rightStack, 2);
        var stacks = new Grid { ColumnDefinitions = new ColumnDefinitions("*,4,*"), Children = { leftStack, rightStack } };
        int columns = 1;
        bool smaller = false, wraps = false, pair = false;
        bool? stacked = null;
        int stackedBy = 0;
        void Stack()
        {
            if (stacked == pair && stackedBy == columns) return;
            (stacked, stackedBy) = (pair, columns);
            leftStack.Children.Clear();
            rightStack.Children.Clear();
            // The blocks in sight, each to the column that is shorter so far (Core\Columns.cs): counted by the cards
            // in sight under each heading, so a search that thins a block moves the balance with it, and one it has
            // emptied leaves no gap in its stack.
            var seen = blocks.Where(one => one.IsVisible).ToList();
            var right = Columns.Right(seen.Select(one => Columns.Height(faces.Count(face => face.Under == one && face.Card.IsVisible), columns)).ToList());
            for (int i = 0; i < seen.Count; i++) (pair && right[i] ? rightStack : leftStack).Children.Add(seen[i]);
            Grid.SetColumnSpan(leftStack, pair ? 1 : 3);
            rightStack.IsVisible = pair;
        }
        void Dress()
        {
            bool ruled = lines && !grouped && columns == 2;
            foreach (var (host, sheet, rule) in sheets)
            {
                Lay(sheet, columns);
                rule.IsVisible = ruled && sheet.Children.Count(card => card.IsVisible) > 1;
                // The gap after the last column is as wide as the gap between the columns: taken back, so both edges of the list stand alike.
                host.Margin = ruled ? new Thickness(0, 0, 8 - RuledGap, 0) : default;
            }
            foreach (var (card, tick, name) in cards)
            {
                if (ruled) card.Margin = new Thickness(0, 0, RuledGap, 8);
                else card.ClearValue(Layoutable.MarginProperty);
                if (smaller) tick.FontSize = usual - 1;
                else tick.ClearValue(TemplatedControl.FontSizeProperty);
                name.TextWrapping = wraps ? TextWrapping.Wrap : TextWrapping.NoWrap;
                // Two lines of words fill a card to its rims: they are given room over and under them.
                name.Margin = wraps ? new Thickness(7, 4, 0, 4) : new Thickness(7, 0, 0, 0);
            }
            if (grouped) Stack();
        }
        void Fit(double width)
        {
            if (width <= 0) return;
            double room = width - 16;
            int fit;
            bool small = false, wrap = false, two = false;
            if (grouped)
            {
                two = blocks.Count > 1 && room >= TwoColumnsFrom - 100;
                double inside = (two ? (room - 4) / 2 : room) - 14;
                if (!lines) fit = Math.Clamp((int)(inside / Need(usual)), 1, 4);
                else
                {
                    fit = 1;
                    small = inside < Need(usual);
                    wrap = inside < Need(usual - 1);
                }
            }
            else if (!lines) fit = Math.Clamp((int)(room / Need(usual)), 1, 4);
            else if (room >= 2 * Need(usual)) fit = 2;
            else if (room >= 2 * Need(usual - 1)) { fit = 2; small = true; }
            else if (room >= TwoColumnsFrom - 100) { fit = 2; small = true; wrap = true; }
            else fit = 1;
            fit = Math.Min(fit, real.Count);
            if (fit == columns && small == smaller && wrap == wraps && two == pair) return;
            (columns, smaller, wraps, pair) = (fit, small, wrap, two);
            Dress();
        }
        block.SizeChanged += (_, e) => Fit(e.NewSize.Width);
        var ticks = new List<(ToggleButton Tick, string Key)>();
        // A heading opens a block of its own - the drivers of one kind, the builds of one generation
        // (the owner: "the kinds of devices are set apart as blocks"); cards before any heading stand in the list itself.
        Panel into = column;
        Grid? grid = null;
        Border? under = null;
        foreach (var option in options)
        {
            if (option.Header && option.Note)
            {
                // What the list is and whose it is, in words, across the whole of it; at its right the badge of the driver this PC runs.
                var said = new TextBlock { Classes = { "note" }, Text = option.Name, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(1, 0, 8, 7) };
                if (Standing(option) is not { } badge)
                {
                    column.Children.Add(said);
                    continue;
                }
                var over = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
                Grid.SetColumn(badge, 1);
                over.Children.Add(said);
                over.Children.Add(badge);
                column.Children.Add(over);
                continue;
            }
            if (option.Header)
            {
                var body = new StackPanel();
                body.Children.Add(new TextBlock { Classes = { "grp" }, Text = Upper(option.Name) });
                if (blocks.Count == 0) column.Children.Add(stacks);
                blocks.Add(under = new Border { Classes = { "grp", "inner" }, Child = body });
                into = body;
                grid = null;
                continue;
            }
            if (grid is null)
            {
                grid = new Grid();
                // The rule between two columns of lines: in the middle of the gap the cards leave.
                var rule = new Border { Width = 1, HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 1, RuledGap, 9), IsVisible = false }
                    .Ink(Border.BackgroundProperty, "SepInk");
                var sheet = new Panel { Children = { grid, rule } };
                into.Children.Add(sheet);
                sheets.Add((sheet, grid, rule));
            }
            // The tone of the card as plain brushes on its parts; what the pointer and the tick change is changed here.
            var look = Tones.Of(option.Tone.Length > 0 ? option.Tone : "plain");
            var box = TickBox();
            box.BorderBrush = look.BoxRim;
            box.Background = look.Box;
            var (starred, name) = Starred(option.Name);
            var words = new TextBlock { Text = name, Foreground = look.Ink, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(7, 0, 0, 0) };
            Grid.SetColumn(words, 2);
            // A grid, not a row: the words are told how wide they may be, so a line too long for its card can wrap.
            var face = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*"), Children = { box, words } };
            if (starred)
            {
                var star = Star(look.Ink);
                star.Margin = new Thickness(7, 0, 0, 0);
                Grid.SetColumn(star, 1);
                face.Children.Add(star);
            }
            var tick = new ToggleButton { Classes = { "ptick" }, Content = face };
            Avalonia.Automation.AutomationProperties.SetAutomationId(tick, $"field_{field.Id}_{option.Key}");
            var tip = option.Tip.Length > 0 ? option.Tip : field.Tip;
            if (tip.Length > 0) ToolTip.SetTip(tick, tip);
            ticks.Add((tick, option.Key));
            // The card: its rim and its ground in the tone the door names, the tick and the name,
            // and at the right the small buttons of a package - outside the tick, so a press on
            // one of them never changes the choice.
            var inside = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            inside.Children.Add(tick);
            var card = new Border { Classes = { "ptile" }, Child = inside, BorderBrush = look.Rim, Background = look.Wash };
            void Wear()
            {
                bool on = tick.IsChecked == true, over = card.IsPointerOver;
                card.BorderBrush = on ? look.RimOn : over ? look.RimOver : look.Rim;
                card.Background = on ? look.WashOn : over ? look.WashOver : look.Wash;
                box.BorderBrush = on ? look.FillRim : look.BoxRim;
                box.Background = on ? look.Fill : look.Box;
            }
            tick.IsCheckedChanged += (_, _) => Wear();
            card.PointerEntered += (_, _) => Wear();
            card.PointerExited += (_, _) => Wear();
            cards.Add((card, tick, words));
            faces.Add((card, option, under));
            grid.Children.Add(card);
        }
        Dress();
        // The search: of this list, when its field asks for one, and of the whole page. A card is
        // in sight when it holds every word of both; a heading - while a card under it is. Nothing
        // is built again, and no tick changes: the value is every tick, in sight or not.
        void Sift()
        {
            var (own, whole) = (Search.Words(_queries.GetValueOrDefault(field.Id, "")), Search.Words(_pageQuery));
            var alive = new HashSet<Border>();
            bool any = false;
            foreach (var (card, option, heading) in faces)
            {
                bool shown = Search.Matches(option, own) && Search.Matches(option, whole);
                card.IsVisible = shown;
                if (!shown) continue;
                any = true;
                if (heading is not null) alive.Add(heading);
            }
            foreach (var one in blocks) one.IsVisible = alive.Contains(one);
            stacked = null;
            Dress();
            // While the page is searched, a list with nothing to show steps aside; its own search never hides it - the box is in its head.
            block.IsVisible = any || whole.Length == 0;
        }
        _sifters.Add(Sift);
        if (_pageQuery.Length > 0 || _queries.GetValueOrDefault(field.Id, "").Length > 0) Sift();
        void Take() => _values.Set(field, string.Join(Values.ListSeparator, ticks.Where(item => item.Tick.IsChecked == true).Select(item => item.Key)));
        foreach (var (tick, _) in ticks) tick.Click += (_, _) => Take();
        Watch(field, () =>
        {
            var picked = _values.Picked(field);
            foreach (var (tick, key) in ticks) tick.IsChecked = picked.Contains(key);
        });

        var count = new TextBlock { Classes = { "count" } };
        Watch(field, () => count.Text = Lang.F("{0} из {1}", _values.Picked(field).Count(key => ticks.Any(item => item.Key == key)), ticks.Count));
        head.Children.Add(count);
        if (ticks.Count > 3)
        {
            Button Mini(string word, string tip, bool on)
            {
                // A button like the others of the page (the owner, 11.10.2026: "ALL, NONE - must be buttons everywhere. Not just little blue words").
                var mini = new Button { Classes = { "small" }, Content = Lang.T(word), VerticalAlignment = VerticalAlignment.Center };
                ToolTip.SetTip(mini, Lang.T(tip));
                // The cards in sight: under a search ALL ticks what was found, NONE takes the ticks off what was found.
                mini.Click += (_, _) =>
                {
                    var seen = faces.Where(face => face.Card.IsVisible).Select(face => face.Option.Key).ToHashSet();
                    var picked = _values.Picked(field);
                    if (on) picked.UnionWith(seen);
                    else picked.ExceptWith(seen);
                    _values.Set(field, string.Join(Values.ListSeparator, ticks.Select(item => item.Key).Where(picked.Contains)));
                };
                return mini;
            }
            head.Children.Add(Mini("ВСЕ", "Отметить все, что в списке на виду.", true));
            head.Children.Add(Mini("СНЯТЬ", "Снять отметки со всего, что в списке на виду.", false));
        }
        // A list the door gave is kept for its term; this asks for it anew now.
        if (field.Dynamic) head.Children.Add(Refresh(node, field));
        if (field.Filter)
        {
            var search = new TextBox
            {
                Classes = { "masks" }, Width = 190, Height = 22, MinHeight = 22, Padding = new Thickness(7, 0), VerticalContentAlignment = VerticalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center, PlaceholderText = Lang.T("поиск по списку"), Text = _queries.GetValueOrDefault(field.Id, ""),
            };
            PixelGrid.Field(search);
            Avalonia.Automation.AutomationProperties.SetAutomationId(search, "search_" + field.Id);
            ToolTip.SetTip(search, Lang.T("Показать карточки, в названии которых есть каждое набранное слово. Отметки спрятанных карточек остаются."));
            search.TextChanged += (_, _) =>
            {
                _queries[field.Id] = search.Text ?? "";
                Sift();
            };
            head.Children.Add(search);
        }
        return block;
    }

    /// <summary>
    /// A row of sets: a press puts values into fields - a profile of packages, the newest versions,
    /// the stable ones. A set that names values or turns a flag over is a switch, lit while its
    /// fields hold what it sets (Core\Presets.cs): which set is in force is seen on the page, not
    /// remembered. A set that picks by a rule stays a plain button.
    /// </summary>
    Control Sets(Node node, Field field)
    {
        var row = new WrapPanel { Orientation = Orientation.Horizontal };
        foreach (var preset in field.Presets.Where(preset => InSight(preset.VisibleWhen)))
        {
            var (starred, name) = Starred(preset.Name);
            object face = Upper(name);
            if (starred)
            {
                var star = Icons.Sign("star");
                star.Ink(Avalonia.Controls.Shapes.Shape.StrokeProperty, "AmberInk").Ink(Avalonia.Controls.Shapes.Shape.FillProperty, "AmberInk");
                face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, Children = { star, new TextBlock { Text = Upper(name) } } };
            }
            void Press()
            {
                // The ticks that follow their versions to the other file are read off the list as it is now:
                // once the flag is turned, the list is another one and has not come yet.
                var carried = Presets.Carried(preset, _values, node.Fields, target => ListOf(node, target));
                Presets.Press(preset, _values, target => ListOf(node, target));
                foreach (var (id, ticks) in carried) _carried[id] = ticks;
            }
            Button button;
            if (Presets.HasState(preset))
            {
                // The weight of the buttons it stands among: one row of sets, some of them with a state.
                var toggle = new ToggleButton { Classes = { "switch" }, Content = face, Margin = new Thickness(0, 0, 4, 4), FontWeight = FontWeight.SemiBold };
                void Light() => toggle.IsChecked = Presets.IsActive(preset, _values);
                // A press turns a switch over by itself: this one shows what the fields hold, not how often it was pressed.
                toggle.Click += (_, _) => { Press(); Light(); };
                foreach (var id in Presets.Watched(preset))
                    if (_values.Find(id) is { } watched) Watch(watched, Light);
                Light();
                button = toggle;
            }
            else
            {
                button = new Button { Classes = { "small" }, Content = face, Margin = new Thickness(0, 0, 4, 4) };
                button.Click += (_, _) => Press();
            }
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, $"set_{field.Id}_{preset.Id}");
            if (preset.Tip.Length > 0) ToolTip.SetTip(button, preset.Tip);
            row.Children.Add(button);
        }
        return row;
    }

    /// <summary>The options of a field as the page has them now: those of the manifest, or the list the door gave.</summary>
    IEnumerable<Option> ListOf(Node node, Field field) =>
        !field.Dynamic ? field.Options : _lists.TryGet(ListKey(node, field), out var known) ? known.Options : new List<Option>();

    /// <summary>"REFRESH THE LIST" of a list the door gave: the list is forgotten and asked again at once; what is ticked stays.</summary>
    Button Refresh(Node node, Field field)
    {
        var refresh = new Button { Classes = { "small" }, Content = Lang.T("ОБНОВИТЬ СПИСОК"), VerticalAlignment = VerticalAlignment.Center };
        ToolTip.SetTip(refresh, Lang.T("Спросить список заново: модели - у поставщика по ключу, остальное - у файлов программы. Выбор остаётся."));
        Avalonia.Automation.AutomationProperties.SetAutomationId(refresh, "refresh_" + field.Id);
        refresh.Click += (_, _) =>
        {
            var key = ListKey(node, field);
            _lists.Remove(key);
            _fresh.Add(key);
            _rebuild();
        };
        return refresh;
    }

    /// <summary>A row of group buttons over a list of ticks: a button is on while its whole group is ticked; a press ticks the group or takes it off.</summary>
    Control GroupButtons(Field field)
    {
        var row = new WrapPanel { Orientation = Orientation.Horizontal };
        if (_values.Find(field.Target) is not { } target) return row;
        var buttons = new List<(ToggleButton Button, List<string> Apps)>();
        foreach (var option in field.Options.Where(option => option.Apps.Count > 0))
        {
            var button = new ToggleButton { Classes = { "switch" }, Content = $"{option.Name} ({option.Apps.Count})", Margin = new Thickness(0, 0, 4, 4) };
            if (option.Tip.Length > 0) ToolTip.SetTip(button, option.Tip);
            var apps = option.Apps;
            button.Click += (_, _) =>
            {
                var picked = _values.Picked(target);
                if (apps.All(picked.Contains)) picked.ExceptWith(apps);
                else picked.UnionWith(apps);
                // In the order of the list itself, as a person would have ticked it.
                var order = target.Options.Select(item => item.Key).Where(picked.Contains).Concat(picked.Except(target.Options.Select(item => item.Key)));
                _values.Set(target, string.Join(Values.ListSeparator, order));
            };
            buttons.Add((button, apps));
            row.Children.Add(button);
        }
        void Light()
        {
            var picked = _values.Picked(target);
            foreach (var (button, apps) in buttons) button.IsChecked = apps.All(picked.Contains);
        }
        Watch(target, Light);
        return row;
    }

    TextBox TextBox(Field field, int lines)
    {
        var box = new TextBox { PlaceholderText = field.Placeholder, Classes = { "masks" }, MinHeight = 24, Padding = new Thickness(8, 2), VerticalContentAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 0, 4) };
        if (lines == 1) PixelGrid.Field(box);
        if (lines > 1)
        {
            box.AcceptsReturn = true;
            box.TextWrapping = TextWrapping.Wrap;
            box.MinHeight = 18 * lines;
            box.MaxHeight = 320;
        }
        Avalonia.Automation.AutomationProperties.SetAutomationId(box, "field_" + field.Id);
        if (field.Tip.Length > 0) ToolTip.SetTip(box, field.Tip);
        box.TextChanged += (_, _) => _values.Set(field, box.Text ?? "");
        // The box a person types in is not rewritten under the cursor: only a value that came from elsewhere is put in.
        Watch(field, () => { if ((box.Text ?? "") != _values.Get(field)) box.Text = _values.Get(field); });
        return box;
    }

    /// <summary>A number: typed, or stepped with the arrow keys; kept inside min and max of the manifest.</summary>
    TextBox NumberBox(Field field)
    {
        var box = new TextBox { Width = 120, HorizontalAlignment = HorizontalAlignment.Left, Classes = { "masks" }, Height = 24, MinHeight = 24, Padding = new Thickness(8, 0), VerticalContentAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 0, 4) };
        Avalonia.Automation.AutomationProperties.SetAutomationId(box, "field_" + field.Id);
        if (field.Tip.Length > 0) ToolTip.SetTip(box, field.Tip);
        PixelGrid.Field(box);
        double step = field.Step is { } given && given > 0 ? given : 1;
        string Fit(double number)
        {
            if (field.Min is { } min && number < min) number = min;
            if (field.Max is { } max && number > max) number = max;
            return number.ToString("0.######", CultureInfo.InvariantCulture);
        }
        void Take()
        {
            var typed = (box.Text ?? "").Trim().Replace(',', '.');
            if (double.TryParse(typed, NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) _values.Set(field, Fit(number));
            box.Text = _values.Get(field);
        }
        void Move(int direction)
        {
            if (!double.TryParse(_values.Get(field), NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) number = 0;
            _values.Set(field, Fit(Math.Round(number + direction * step, 6)));
        }
        box.LostFocus += (_, _) => Take();
        box.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter) { Take(); e.Handled = true; }
            else if (e.Key == Key.Up) { Take(); Move(1); e.Handled = true; }
            else if (e.Key == Key.Down) { Take(); Move(-1); e.Handled = true; }
        };
        Watch(field, () => { if (!box.IsFocused || (box.Text ?? "") != _values.Get(field)) box.Text = _values.Get(field); });
        return box;
    }

    // ------------------------------------------------------------ lists asked of the door

    string ListKey(Node node, Field field) =>
        node.Id + "|" + field.Id + "|" + string.Join("|", field.DependsOn.Select(DependsValue))
        + (field.ReadsFolders ? "|" + (Folders?.Invoke().Source ?? "") + "|" + (Folders?.Invoke().Target ?? "") : "");

    /// <summary>The value a list depends on: a field of the form, or one of the two folders of the window.</summary>
    string DependsValue(string name) => name switch
    {
        "input_path" => Folders?.Invoke().Source ?? "",
        "output_path" => Folders?.Invoke().Target ?? "",
        _ => _values.Get(name),
    };

    /// <summary>The list the program kept for these values, read at the start; null when it read none for them.</summary>
    Kept? Prelisted(Node node, Field field)
    {
        if (!Kept.TryGetValue(node.Id + ":" + field.Id, out var entries)) return null;
        static string Plain(string text) => text.Replace("\r", "").Trim();
        string Told(JsonElement value) => value.ValueKind == JsonValueKind.Array
            ? string.Join(Values.ListSeparator, value.EnumerateArray().Select(FieldKinds.Text))
            : FieldKinds.Text(value);
        return entries.FirstOrDefault(entry => entry.Depends.All(pair =>
            string.Equals(Plain(DependsValue(pair.Key)), Plain(Told(pair.Value)), StringComparison.OrdinalIgnoreCase)));
    }

    /// <summary>
    /// The options of a field, and when there are none to show - the line that stands in their
    /// place: the list is being read, or the reason it did not come.
    /// </summary>
    (List<Option> Options, Control? Note) OptionsOf(Node node, Field field)
    {
        if (!field.Dynamic) return (field.Options, null);
        var key = ListKey(node, field);
        if (_lists.TryGet(key, out var known))
        {
            if (known.Trouble.Length == 0)
            {
                Offer(field, known.Options);
                return (known.Options, null);
            }
            var again = new Button { Classes = { "small" }, Content = Upper(Lang.T("Спросить ещё раз")), Margin = new Thickness(8, 0, 0, 0) };
            again.Click += (_, _) => { _lists.Remove(key); _rebuild(); };
            return (known.Options, new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Children =
                {
                    new TextBlock { Classes = { "note", "warn" }, Text = Lang.F("список не получен: {0}", known.Trouble), TextWrapping = TextWrapping.Wrap, MaxWidth = 620, VerticalAlignment = VerticalAlignment.Center },
                    again,
                },
            });
        }
        // What the program kept for these values is shown at once; the door is not asked.
        if (!_fresh.Contains(key) && Prelisted(node, field) is { } kept)
        {
            _lists.Put(key, kept.Options, kept.Error, field.CacheSeconds);
            return OptionsOf(node, field);
        }
        if (_asking.Add(key)) _ = Ask(node, field, key);
        return (new List<Option>(), new TextBlock { Classes = { "note" }, Text = Lang.T("читаю список…") });
    }

    /// <summary>
    /// What a list ticks by itself - the driver this PC needs - is ticked whenever the list is
    /// shown, as it arrives and from the memory of the window alike, until the person has changed
    /// the field (Values.Offer). Once only on arrival, the tick was gone with the first change of
    /// the page (the audit of 10.10.2026).
    /// </summary>
    void Offer(Field field, List<Option> options)
    {
        // The ticks a set carried over from the list before come first: they are the person's.
        if (_carried.Remove(field.Id, out var carried))
        {
            Presets.Land(_values, field, carried, options);
            return;
        }
        var ticked = options.Where(option => option.Default && !option.Header).Select(option => option.Key).ToList();
        if (ticked.Count > 0) _values.Offer(field, string.Join(Values.ListSeparator, ticked));
    }

    async Task Ask(Node node, Field field, string key)
    {
        var values = _values.ForDoor(node);
        var (source, target) = Folders?.Invoke() ?? ("", "");
        Asked++;
        await _lane.WaitAsync();
        (List<Option> Options, string Trouble) answer;
        bool refresh = _fresh.Remove(key);
        try { answer = await Door.Options(node.Id, field.Id, values, source, target, refresh); }
        finally { _lane.Release(); }
        await Dispatcher.UIThread.InvokeAsync(() =>
        {
            _asking.Remove(key);
            _lists.Put(key, answer.Options, answer.Trouble, field.CacheSeconds);
            // The answer to a question that is still the one asked: a field it depends on may have changed meanwhile.
            if (ListKey(node, field) == key) Offer(field, answer.Options);
            _rebuild();
        });
    }
}
