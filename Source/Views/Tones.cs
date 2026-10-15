using System.Collections.Generic;
using Avalonia;
using Avalonia.Media;

namespace AudionOfficeOcrAi.Views;

/// <summary>
/// The colours a card of a list of ticks wears, as the window on NiceGUI had them - the output
/// formats of OCR: amber for the office files, teal for Markdown and the machine files (Ч1, Ч2); a package
/// in the colour of what it is, a version of a vendor in the colour of its mark. The door names the
/// tone (system_core\core\package_tones.py); the colour of a tone and how much of it goes into the
/// rim, the ground and the tick box are here - they are looks.
/// </summary>
public static class Tones
{
    static readonly Dictionary<string, string> Accents = new()
    {
        ["runtime"] = "#8ca2ba", ["archive"] = "#a58bd4", ["browser"] = "#47b3df", ["vpn"] = "#788df0",
        ["messenger"] = "#62a5dc", ["security"] = "#7d9cc7", ["cloud"] = "#6ebdcc", ["ai"] = "#b681d5",
        ["pkms"] = "#a7b96a", ["office"] = "#f59e0b", ["creator"] = "#d28a66", ["audio"] = "#c7a45e",
        ["video"] = "#c87891", ["dev"] = "#2dd4bf", ["terminal"] = "#50a2b8", ["disk"] = "#88a966",
        ["benchmark"] = "#c28d55", ["hardware"] = "#92aa66", ["utility"] = "#9fa36e", ["network"] = "#6fa9c6",
        ["default"] = "#7f91a5", ["plain"] = "#7f91a5",
        ["gold"] = "#e6bf4f", ["latest"] = "#4fb36a", ["beta"] = "#c98a3e",
    };

    /// <summary>The three small buttons of a package card: green takes the installer, crimson the archive or portable build, blue opens the page.</summary>
    public static readonly IBrush Installer = new SolidColorBrush(Color.Parse("#7cba75"));
    public static readonly IBrush Archive = new SolidColorBrush(Color.Parse("#c25a72"));
    public static readonly IBrush PageLink = new SolidColorBrush(Color.Parse("#5fa8d8"));

    static Color Mix(Color a, double share, Color b) => Color.FromRgb(
        (byte)(a.R * share + b.R * (1 - share)), (byte)(a.G * share + b.G * (1 - share)), (byte)(a.B * share + b.B * (1 - share)));

    /// <summary>A colour with a veil of its own laid over a ground: what the eye sees there.</summary>
    static Color Over(Color veil, Color ground) => Mix(Color.FromRgb(veil.R, veil.G, veil.B), veil.A / 255.0, ground);

    static Color Theme(string key, string fallback) =>
        Application.Current is { } app && app.TryGetResource(key, app.ActualThemeVariant, out var value) && value is ISolidColorBrush brush
            ? brush.Color : Color.Parse(fallback);

    /// <summary>The brushes of a tone: the rim and the ground of a card at rest, under the pointer and ticked; its tick box empty and ticked; its name.</summary>
    public sealed record Look(IBrush Rim, IBrush RimOver, IBrush RimOn, IBrush Wash, IBrush WashOver, IBrush WashOn,
        IBrush BoxRim, IBrush Box, IBrush Fill, IBrush FillRim, IBrush Ink);

    /// <summary>
    /// The brushes of a tone, made once for the theme in use and shared by every card of that tone.
    /// They are set on a card as plain brushes: a resource set on a control is told to everything
    /// under it, and a catalogue is a hundred cards and more.
    /// </summary>
    public static Look Of(string tone)
    {
        var theme = Application.Current?.ActualThemeVariant;
        if (!ReferenceEquals(theme, _madeFor)) { Made.Clear(); _madeFor = theme; }
        if (!Made.TryGetValue(tone, out var brushes)) Made[tone] = brushes = Make(tone);
        return new Look(brushes["ToneRim"], brushes["ToneRimOver"], brushes["ToneRimOn"], brushes["ToneWash"], brushes["ToneWashOver"],
            brushes["ToneWashOn"], brushes["ToneBoxRim"], brushes["ToneBox"], brushes["ToneFill"], brushes["ToneFillRim"], brushes["ToneInk"]);
    }

    static readonly Dictionary<string, Dictionary<string, IBrush>> Made = new();
    static Avalonia.Styling.ThemeVariant? _madeFor;

    static Dictionary<string, IBrush> Make(string tone)
    {
        var resources = new Dictionary<string, IBrush>();
        var accent = Color.Parse(Accents.TryGetValue(tone, out var hex) ? hex : Accents["default"]);
        var ground = Theme("PanelBg", "#0e1114");
        // A rule of a theme may be a veil - white at an eighth: it is laid over the ground first, or
        // mixed as it is it would turn every rim white.
        // The rim of a card at rest is all but gone (the owner: "press the rims of the chips down by
        // eighty per cent" - many of them side by side flickered): a fifth of the rule of the theme,
        // a fifth of the tone. The ground and the tick box carry the tone; a ticked card keeps its rim.
        var rim = Mix(Over(Theme("SepInk", "#2a343a"), ground), 0.2, ground);
        bool plain = tone == "plain";
        // An ordinary version stays quiet - no colour in its rim, none in its ground; ticked, it wears the accent of a choice.
        var choice = Theme("Quasar", "#58a6ff");
        bool strong = tone is "gold" or "latest";
        resources["ToneRim"] = new SolidColorBrush(plain ? rim : Mix(accent, tone == "gold" ? 0.45 : strong ? 0.30 : 0.07, rim));
        resources["ToneRimOver"] = new SolidColorBrush(plain ? Mix(choice, 0.30, rim) : Mix(accent, strong ? 0.70 : 0.32, rim));
        resources["ToneRimOn"] = new SolidColorBrush(plain ? Mix(choice, 0.92, Colors.White) : Mix(accent, strong ? 0.95 : 0.70, rim));
        resources["ToneWash"] = new SolidColorBrush(plain ? ground : Mix(accent, tone == "gold" ? 0.22 : tone == "latest" ? 0.14 : 0.07, ground));
        resources["ToneWashOver"] = new SolidColorBrush(plain ? ground : Mix(accent, tone == "gold" ? 0.26 : 0.10, ground));
        resources["ToneWashOn"] = new SolidColorBrush(plain ? Mix(choice, 0.38, ground) : Mix(accent, tone == "gold" ? 0.30 : 0.13, ground));
        var box = plain ? choice : accent;
        resources["ToneBoxRim"] = new SolidColorBrush(Mix(box, 0.80, rim));
        resources["ToneBox"] = new SolidColorBrush(Mix(box, 0.12, ground));
        resources["ToneFill"] = new SolidColorBrush(Mix(box, 0.74, ground));
        resources["ToneFillRim"] = new SolidColorBrush(Mix(box, 0.88, Colors.White));
        resources["ToneInk"] = new SolidColorBrush(tone switch
        {
            "gold" => Color.Parse("#f2d98a"),
            "latest" => Color.Parse("#b9e8c4"),
            _ => Theme("TextMain", "#edf2f4"),
        });
        return resources;
    }
}
