using System.Collections.Generic;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Media;
using Avalonia.Styling;
using Avalonia.VisualTree;

namespace AudionOfficeOcrAi;

/// <summary>
/// The shell of Audion Build Publisher (and through it of Audion Sync Tools and Audion Disk
/// Tools): the themes, the sizes and the styles of App.axaml, the tooltips and the signs. What
/// those programs paint for their file lists alone - grain, glass, zebra - is switched off here
/// by plain values of the same resources.
/// </summary>
public partial class App : Application
{
    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
        // Tooltips come after 1500 ms, as in every Audion program, and the neighbour gets no quick
        // show: moving along a row of buttons must not pop them all.
        ToolTip.TipProperty.Changed.AddClassHandler<Control>((control, _) =>
        {
            control.SetValue(ToolTip.ShowDelayProperty, 1500);
            control.SetValue(ToolTip.BetweenShowDelayProperty, 0);
        });
        // No sign is drawn by hand: the markup names a sign of the owner's set (Tag="hammer") and
        // gets its geometry here, from Icons.cs. Then every sign, now and later, is centred and
        // scaled the same way.
        Control.LoadedEvent.AddClassHandler<Avalonia.Controls.Shapes.Path>((path, _) =>
        {
            if (path.Data is null && path.Tag is string name && path.Classes.Contains("icon") && Icons.Glyph(name) is { } sign) path.Data = sign;
            CenterIcon(path);
            if (path.Classes.Contains("icon") && !Settled.TryGetValue(path, out var known))
            {
                Settled.Add(path, new Place());
                path.LayoutUpdated += (_, _) => SettleIcon(path);
            }
        });
        Avalonia.Controls.Shapes.Path.DataProperty.Changed.AddClassHandler<Avalonia.Controls.Shapes.Path>((path, _) => CenterIcon(path));
        // The mark of the chosen line of a menu is tangerine, as in Disk Tools and Sync Tools.
        Control.LoadedEvent.AddClassHandler<Avalonia.Controls.Shapes.Ellipse>((dot, _) =>
        {
            if (dot.Parent is ContentControl { Name: "PART_ToggleIconPresenter" } && Current?.TryGetResource("Tangerine", Current.ActualThemeVariant, out var ink) == true && ink is IBrush brush)
                dot.Fill = brush;
        });
    }

    /// <summary>How much larger than its 10 grid a sign is shown.</summary>
    const double IconScale = 1.26;

    /// <summary>
    /// A sign drawn off the middle of its 10 box is moved by the exact bounds of its drawing to
    /// the middle, then scaled around it.
    /// </summary>
    static void CenterIcon(Avalonia.Controls.Shapes.Path path)
    {
        if (!path.Classes.Contains("icon") || path.Data is not { } data) return;
        var bounds = data.Bounds;
        var dx = 5 - (bounds.X + bounds.Width / 2);
        var dy = 5 - (bounds.Y + bounds.Height / 2);
        path.RenderTransformOrigin = new RelativePoint(0.5, 0.5, RelativeUnit.Relative);
        // The third step is the half pixel the layout could not give (SettleIcon); it outlives a new drawing.
        var settle = path.RenderTransform is TransformGroup { Children.Count: 3 } old ? old.Children[2] : new TranslateTransform();
        path.RenderTransform = new TransformGroup
        {
            Children = { new TranslateTransform(dx, dy), new ScaleTransform(IconScale, IconScale), settle },
        };
    }

    sealed class Place { public string At = ""; }

    static readonly System.Runtime.CompilerServices.ConditionalWeakTable<Avalonia.Controls.Shapes.Path, Place> Settled = new();

    /// <summary>
    /// A button that holds a sign alone has it in its very middle, on the pixels of the screen.
    /// The layout puts the box of a sign on a whole pixel: at 150% a button is 36 pixels and the
    /// box 15, so the box stood half a pixel to the left and up. The half pixel is given back as a
    /// render offset; nothing is a constant - the sizes and the scale are read as they are.
    /// </summary>
    static void SettleIcon(Avalonia.Controls.Shapes.Path path)
    {
        if (!Settled.TryGetValue(path, out var place) || path.RenderTransform is not TransformGroup { Children.Count: 3 } group
            || group.Children[2] is not TranslateTransform settle || !path.IsEffectivelyVisible) return;
        if (path.FindAncestorOfType<Button>() is not { } host || TopLevel.GetTopLevel(path) is not { } top) return;
        double scale = top.RenderScaling, x = 0, y = 0;
        for (Visual? v = path; v != null && v != host; v = v.GetVisualParent()) { x += v.Bounds.X; y += v.Bounds.Y; }
        var key = $"{scale}|{host.Bounds.Size}|{x}|{y}|{path.Bounds.Size}";
        if (key == place.At) return;
        place.At = key;
        // A sign beside a word keeps the place the layout gave it: the word is its neighbour, not the button.
        bool alone = !host.GetVisualDescendants().OfType<TextBlock>().Any(text => text.IsVisible && !string.IsNullOrEmpty(text.Text));
        settle.X = alone ? host.Bounds.Width / 2 - (x + path.Bounds.Width / 2) : 0;
        settle.Y = alone ? host.Bounds.Height / 2 - (y + path.Bounds.Height / 2) : 0;
    }

    public override void OnFrameworkInitializationCompleted()
    {
        Resources["Grain"] = Brushes.Transparent;
        Resources["Zebra"] = Brushes.Transparent;
        Resources["ListOpacity"] = 1.0;
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            // Before the window: an error in its own constructor is written down too.
            Core.Guard.Install();
            desktop.MainWindow = new MainWindow();
        }
        base.OnFrameworkInitializationCompleted();
    }

    /// <summary>Audion Code Dark: the "CodeDark" dictionary of App.axaml, the rest from Dark.</summary>
    public static ThemeVariant CodeDark { get; } = new("CodeDark", ThemeVariant.Dark);

    /// <summary>Audion Vault Dark: the "VaultDark" dictionary of App.axaml, the rest from Dark.</summary>
    public static ThemeVariant VaultDark { get; } = new("VaultDark", ThemeVariant.Dark);

    /// <summary>The variant of a theme of the settings: "dark", "codedark", "vault", "light".</summary>
    public static ThemeVariant Variant(string theme) => theme switch
    {
        "light" => ThemeVariant.Light, "codedark" => CodeDark, "vault" => VaultDark, _ => ThemeVariant.Dark,
    };

    // ------------------------------------------------------------ fonts and sizes (SETTINGS)

    /// <summary>The sizes of the window's texts: SETTINGS moves them all by the same step. The terminal has a size of its own.</summary>
    static readonly string[] SizeKeys =
    {
        "FontBase", "FontPanel", "FontHeader", "FontButton", "FontHint", "FontSwitch", "FontCaption", "FontCrumb", "FontCount",
        "FontTitle", "FontBlock", "FontSection", "FontTip", "FontCard", "FontField", "FontFine", "FontBadge",
    };

    /// <summary>The sizes as App.axaml gives them, read once: a step is counted from them, not from the step before.</summary>
    static Dictionary<string, double>? _usual;

    public static void SetSizes(double shift, double terminal)
    {
        if (Current is not { } app) return;
        _usual ??= SizeKeys.Where(key => app.Resources.TryGetResource(key, null, out var value) && value is double)
            .ToDictionary(key => key, key => (double)app.Resources[key]!);
        foreach (var (key, usual) in _usual) app.Resources[key] = usual + shift;
        app.Resources["FontLog"] = terminal;
    }

    /// <summary>A size of the scale as it is now.</summary>
    public static double SizeOf(string key, double usual) =>
        Current is { } app && app.Resources.TryGetResource(key, null, out var value) && value is double size ? size : usual;

    /// <summary>JetBrains Mono and Inter are the fonts inside the program; any other name is a font of Windows.</summary>
    public static FontFamily Family(string name) => name switch
    {
        "" or "JetBrains Mono" => new FontFamily("fonts:JetBrainsMono#JetBrains Mono"),
        "Inter" => new FontFamily("fonts:Inter#Inter"),
        _ => new FontFamily(name),
    };

    /// <summary>The font of the window when SETTINGS name none: Inter; the terminal keeps JetBrains Mono.</summary>
    public const string UsualWindowFont = "Inter";

    public static void SetFonts(string window, string terminal)
    {
        if (Current is not { } app) return;
        app.Resources["FontUi"] = Family(window.Length > 0 ? window : UsualWindowFont);
        app.Resources["FontGrid"] = Family(terminal);
    }

    /// <summary>A brush of the current theme by its key; a neutral grey when the key is unknown.</summary>
    public static IBrush Ink(string key) =>
        Current is { } app && app.TryGetResource(key, app.ActualThemeVariant, out var value) && value is IBrush brush ? brush : Brushes.Gray;
}
