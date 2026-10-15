using System.Collections.Generic;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using AudionOfficeOcrAi.Core;
using AudionOfficeOcrAi.Views;
using Page = AudionOfficeOcrAi.Core.Page;

namespace AudionOfficeOcrAi;

/// <summary>
/// The pages of the window. A page is built when it is first opened and then stays in the window,
/// hidden while another is in sight: to put a hundred cards into the window takes a quarter of a
/// second and to take them out as long (measured 10.10.2026), to show what is already there takes
/// nothing. A page whose form has to change - a field its shape depends on was set, a list it holds
/// is to be asked anew - is built again when it is next in sight, not before.
/// </summary>
public partial class MainWindow
{
    sealed class PageView
    {
        public required Page Page;
        public required Form Form;
        public required ScrollViewer Root;
        public required StackPanel Cards;
        /// <summary>The buttons of the page that run something.</summary>
        public readonly List<Button> RunButtons = new();
        /// <summary>A page with one form keeps its name, its buttons and "back to the defaults" in the bar over the cards.</summary>
        public bool HasBar;
        public string BarTitle = "";
        public readonly List<Button> BarButtons = new();
        public List<Field> ResetFields = new();
        /// <summary>The pages of the one form of the page, as a band of switches: it stands under the pages of the section, over the form.</summary>
        public Control? Bands;
        /// <summary>The page is to be built before it is shown: never built yet, or what it shows is out of date.</summary>
        public bool Stale = true;
    }

    readonly Dictionary<string, PageView> _views = new();
    PageView? _view;

    static string KeyOf(Page page) => ValueStore.KeyOf(page);

    PageView ViewOf(Page page)
    {
        if (_views.TryGetValue(KeyOf(page), out var known)) return known;
        var cards = new StackPanel { Margin = new Thickness(10, 10, 10, 4), Spacing = 8 };
        var root = new ScrollViewer
        {
            Content = cards, IsVisible = false,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
        };
        PageView? view = null;
        var form = new Form(_store.Of(page), () => Outdated(view!))
        {
            Grown = CentreWords, KeyPressed = PressKey,
            Folders = () => (_source, _target),
        };
        view = new PageView { Page = page, Form = form, Root = root, Cards = cards };
        PageHost.Children.Add(root);
        return _views[KeyOf(page)] = view;
    }

    /// <summary>
    /// The choices of a page - the engines of LOCAL OCR, the providers of API OCR - as a band of
    /// switches over its form, the way the pages of a form stand there; the bands of the form
    /// itself go under it. A switch wears its sign and the tone of its engine (App.axaml, tone-*).
    /// A page with one choice, or none, has no such band.
    /// </summary>
    Control? WithChoices(PageView view, Control? bands)
    {
        var page = view.Page;
        if (page.Choices.Count < 2) return bands;
        var row = new Grid();
        foreach (var choice in page.Choices)
        {
            var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 7, HorizontalAlignment = HorizontalAlignment.Center };
            if (Icons.Face(choice.Icon) is { } sign) face.Children.Add(sign);
            face.Children.Add(new TextBlock { Classes = { "sectionname" }, Text = Upper(choice.Name), TextTrimming = TextTrimming.CharacterEllipsis });
            var button = new ToggleButton
            {
                Classes = { "switch", "section" }, HorizontalAlignment = HorizontalAlignment.Stretch, IsChecked = choice.Id == page.Chosen, Content = face,
            };
            if (choice.Tone.Length > 0) button.Classes.Add("tone-" + choice.Tone);
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, $"choice_{page.Section?.Id}_{page.Id}_{choice.Id}");
            if (choice.Tip.Length > 0) ToolTip.SetTip(button, choice.Name + "\n" + choice.Tip);
            var id = choice.Id;
            button.Click += (_, _) =>
            {
                // A press on the one that is on must not switch it off: one of the row is always on.
                if (page.Chosen == id) { button.IsChecked = true; return; }
                if (!page.Choose(id)) return;
                // What the page fixes is another set now: its values are set, the lists that hang on them are other lists.
                _store.Open(page);
                Outdated(view);
            };
            if (row.ColumnDefinitions.Count > 0) row.ColumnDefinitions.Add(new ColumnDefinition(new GridLength(6)));
            row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            Grid.SetColumn(button, row.ColumnDefinitions.Count - 1);
            row.Children.Add(button);
        }
        if (bands is null) return row;
        return new StackPanel { Spacing = 6, Children = { row, bands } };
    }

    void Outdated(PageView view)
    {
        view.Stale = true;
        if (ReferenceEquals(view, _view)) RebuildSoon();
    }

    void SelectPage(Page page)
    {
        _page = page;
        if (page.Section is { } section) _lastPage[section.Id] = page.Id;
        foreach (var child in PageRow.Children)
            if (child is ToggleButton tab) tab.IsChecked = (string?)tab.Tag == page.Id;
        var view = ViewOf(page);
        _view = view;
        // The values of the page: its fields are known, and what the page fixes is set - in its
        // own values, so nothing another page holds is touched (Core\Values.cs, ValueStore.Open).
        _store.Open(page);
        // A list older than the term the manifest names for it is asked anew when its page comes into sight.
        if (view.Form.DropExpiredLists()) view.Stale = true;
        if (view.Stale) Build(view, whole: false);
        Show(view);
    }

    /// <summary>The page comes into sight: the others hide, the bar over the cards takes its name and its buttons.</summary>
    void Show(PageView view)
    {
        CardsNote.IsVisible = false;
        foreach (var other in _views.Values) other.Root.IsVisible = ReferenceEquals(other, view);
        ActionButtons.Children.Clear();
        foreach (var button in view.BarButtons) ActionButtons.Children.Add(button);
        ActionTitle.Text = view.BarTitle;
        ActionReset.IsVisible = view.ResetFields.Count > 0;
        ActionBar.IsVisible = view.HasBar;
        PageSearchBox.IsVisible = view.Page.Filter;
        if (view.Page.Filter && (PageSearchBox.Text ?? "") != view.Form.PageQuery) PageSearchBox.Text = view.Form.PageQuery;
        BandHost.Content = view.Bands;
        BandHost.IsVisible = view.Bands is not null;
        PageBar.IsVisible = PageRow.IsVisible || BandHost.IsVisible;
        ShowLayoutService();
        ApplyBusy();
        CentreWords();
    }

    bool _rebuildPosted;

    /// <summary>The page in sight is built again after the press that asked for it has been handled, once for any number of changes.</summary>
    void RebuildSoon()
    {
        if (_rebuildPosted) return;
        _rebuildPosted = true;
        Dispatcher.UIThread.Post(() =>
        {
            _rebuildPosted = false;
            if (_view is not { } view) return;
            var offset = view.Root.Offset;
            // Built again in place: whole at once when the person has scrolled, so the place he was at is still there.
            Build(view, whole: offset.Y >= 1);
            Show(view);
            Dispatcher.UIThread.Post(() => view.Root.Offset = offset, DispatcherPriority.Loaded);
        });
    }

    /// <summary>
    /// "Back to the defaults": the fields of the page go back to the values of the program, and the
    /// page is built again - a list ticks what it ticks by itself when it is shown.
    /// </summary>
    void ResetFields(PageView view, List<Field> fields)
    {
        _store.Of(view.Page).Reset(fields);
        Outdated(view);
    }

    /// <summary>Every page is out of date: the theme changed, or the lists are to be asked anew. The one in sight is built again now.</summary>
    void OutdateAll(bool lists)
    {
        foreach (var view in _views.Values)
        {
            if (lists) view.Form.DropLists();
            view.Stale = true;
        }
        if (_view is not null) RebuildSoon();
    }

    /// <summary>Every page is thrown away: the language changed, and with it every word a page was built of.</summary>
    void ForgetPages()
    {
        foreach (var view in _views.Values) view.Form.Detach();
        _views.Clear();
        _view = null;
        PageHost.Children.Clear();
        ActionButtons.Children.Clear();
    }

    // ------------------------------------------------------------ the cards of a page

    void Build(PageView view, bool whole)
    {
        var page = view.Page;
        view.Form.Forget();
        view.Form.Lazy = !whole;
        view.Cards.Children.Clear();
        view.RunButtons.Clear();
        view.BarButtons.Clear();
        view.ResetFields = new List<Field>();
        view.HasBar = false;
        view.BarTitle = "";
        view.Bands = null;

        // A page with one form: its buttons stand over the form and stay in sight while it scrolls.
        var forms = page.Cards().Where(card => card.Host.Fields.Count > 0 || card.Guests.Count > 0).ToList();
        var alone = forms.Count == 1 ? forms[0].Host : null;

        // An operation with a form is a card of its own; operations that need nothing but a
        // press stand together in the block the layout names, button beside button.
        var blocks = new Dictionary<string, WrapPanel>();
        foreach (var (host, guests) in page.Cards())
        {
            if (host.Fields.Count > 0 || guests.Count > 0) { view.Cards.Children.Add(Card(view, host, guests, ReferenceEquals(host, alone))); continue; }
            var name = host.BlockName.Length > 0 ? host.BlockName : page.Name;
            if (!blocks.TryGetValue(name, out var row))
            {
                blocks[name] = row = new WrapPanel { Orientation = Orientation.Horizontal };
                view.Cards.Children.Add(new Border
                {
                    Classes = { "card" }, Padding = new Thickness(10, 8, 8, 4),
                    Child = new StackPanel { Children = { new TextBlock { Classes = { "blockname" }, Text = name, Margin = new Thickness(0, 0, 0, 8) }, row } },
                });
            }
            row.Children.Add(RunButton(view, host, inBlock: true));
        }
        if (view.Form.Unknown.Count > 0)
        {
            AppendLines(new[] { Lang.F("[GUI] поля неизвестного вида не показаны: {0}", string.Join("; ", view.Form.Unknown)) });
            view.Form.Unknown.Clear();
        }
        if (Lang.Code != "ru") Lang.Walk(view.Cards);
        view.Stale = false;
        view.Form.Lazy = true;
    }

    /// <summary>
    /// Every word of a button, a chip and a badge to the vertical middle of its control, on whole
    /// pixels (Views\PixelGrid.cs): asked once the part just built is in the window.
    /// </summary>
    void CentreWords() => Dispatcher.UIThread.Post(() => PixelGrid.Adopt(this), DispatcherPriority.Loaded);

    /// <summary>
    /// The card of an operation with fields: its name, its buttons - the operations the layout
    /// places beside it, then its own - and "back to the defaults" on one line, the form under
    /// them. The one form of its page hands that line to the bar over the cards.
    /// </summary>
    Control Card(PageView view, Node host, List<Node> guests, bool alone)
    {
        var fields = host.Fields.Where(field => field.Kind is not ("profile_buttons" or "toggle_buttons")).ToList();
        // The one form of its page is named by the page; one of several - by its operation, or they would all read alike.
        var name = host.BlockName.Length > 0 ? host.BlockName : alone ? view.Page.Name : host.Name;
        var buttons = new List<Button>();
        foreach (var node in guests.Append(host))
        {
            // A button may be in sight only for some values of the form.
            if (node.VisibleWhen is { } condition)
            {
                view.Form.Shapes(condition.Keys);
                if (!view.Form.InSight(condition)) continue;
            }
            buttons.Add(RunButton(view, node, inBlock: false));
        }
        // The filled one - the main action - stands last, at the right edge, the others before it.
        buttons = buttons.OrderBy(button => button.Classes.Contains("fill") ? 1 : 0).ToList();
        Control? bands = null;
        var form = host.Fields.Count > 0 ? view.Form.Build(host, out bands) : null;

        if (alone)
        {
            view.Bands = WithChoices(view, bands);
            view.HasBar = true;
            view.BarTitle = Upper(name);
            view.BarButtons.AddRange(buttons);
            view.ResetFields = fields;
            return form ?? new Border();
        }

        var reset = new Button { Classes = { "tool" }, Content = Icons.Sign("undo-2"), Margin = new Thickness(6, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
        ToolTip.SetTip(reset, Lang.T("К умолчаниям: вернуть поля этой карточки к значениям программы."));
        reset.Click += (_, _) => ResetFields(view, fields);
        reset.IsVisible = fields.Count > 0;
        var row = new WrapPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Center };
        foreach (var button in buttons) row.Children.Add(button);
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), Margin = new Thickness(0, 0, 0, form is null ? 0 : 7) };
        head.Children.Add(new TextBlock { Classes = { "blockname" }, Text = name });
        Grid.SetColumn(row, 1);
        head.Children.Add(row);
        Grid.SetColumn(reset, 2);
        head.Children.Add(reset);
        var body = new StackPanel { Children = { head } };
        // One of several forms of a page keeps the band of its pages to itself, over its fields.
        if (bands is not null) { bands.Margin = new Thickness(0, 0, 0, 7); body.Children.Add(bands); }
        if (form is not null) body.Children.Add(form);
        return new Border { Classes = { "card" }, Padding = new Thickness(10, 8, 8, 6), Child = body };
    }

    /// <summary>
    /// The button that runs an operation: its sign and its name, nothing more - what it does is
    /// in its tooltip (the owner, 10.10.2026: a line of description stands on the sections alone).
    /// The main action of a card is filled with the accent; what removes - with Burn Orange.
    /// </summary>
    Button RunButton(PageView view, Node node, bool inBlock)
    {
        var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
        if (Icons.Face(node.Icon) is { } sign) face.Children.Add(sign);
        face.Children.Add(new TextBlock { Text = Upper(node.ButtonName) });
        var button = new Button
        {
            Tag = node, Classes = { "step" }, Content = face, Height = 30, MinHeight = 30,
            Margin = inBlock ? new Thickness(0, 0, 4, 4) : new Thickness(4, 0, 0, 0),
        };
        button.Classes.Set("fill", node.Tone is "run" or "burn" || node.Primary);
        button.Classes.Set("burn", node.Tone == "burn");
        Avalonia.Automation.AutomationProperties.SetAutomationId(button, "run_" + node.Id);
        ToolTip.SetTip(button, TipOf(node));
        button.Click += (_, _) => Press(node);
        view.RunButtons.Add(button);
        return button;
    }
}
