using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.VisualTree;

namespace AudionOfficeOcrAi.Views;

/// <summary>
/// Everything a line of the window holds - a word, an icon, a dot - on whole pixels of the screen, with as many empty rows above it as under it.
///
/// Why: at 125% (at any scale but 100% and 200%) a point of the layout is not a whole number of pixels. The layout puts every control on a
/// whole pixel, but not what is inside a line: a word is drawn from its baseline, which Skia puts on a whole pixel of its own, and an icon of
/// 13 points is a picture of 16.25 pixels. A word does not fill its line either: the capitals of JetBrains Mono take ten rows of a line of
/// seventeen. So "centred" by the layout meant a row up in one control and a row down in another, and the icon and the word of one button apart.
///
/// What is done, for the scale of the screen and the font size as they are now (both are read, nothing is a constant):
/// 1. The rows the letters really take are found by drawing them once (<see cref="Rows"/>): the capitals of a caption, or the body of small
///    letters (the height of "х", without the tops of "б" and the tails of "р") for a caption of small letters only.
/// 2. One-line controls get heights in whole pixels such that the rows left around their capitals are an even number (<see cref="Apply"/>:
///    the resources LineButton, LineSmall, LineChip, LineField of the styles) - so a word can stand exactly in the middle.
/// 3. A word is moved by whole pixels to the middle of its control, or, in a row of a card, to the middle of the first control of the row
///    (a row is taller than its chips by the margin they keep for wrapping) (<see cref="Word"/>, <see cref="Field"/>).
/// 4. An icon or a dot gets a side of whole pixels of the same parity as the word next to it and is moved to the middle of that word; with no
///    word beside it, to the middle of its control or row (<see cref="Marker"/>).
/// Only render offsets and sizes of pictures change: the layout of the pages stays as it was.
/// </summary>
public static class PixelGrid
{
    // ------------------------------------------------------------ the heights of one-line controls

    /// <summary>The scale of the screen the window is on (1.25 at 125%).</summary>
    public static double Scale { get; private set; } = 1;

    /// <summary>
    /// Chooses the heights of one-line controls in whole pixels of this screen, so that the rows left around their capitals are even. Called
    /// when the window is made, when it goes to a screen of another scale and after the step of the font.
    /// </summary>
    public static void Apply(double scale)
    {
        if (Application.Current is not { } app || scale <= 0) return;
        Scale = scale;
        var family = app.TryGetResource("FontUi", null, out var f) && f is FontFamily ff ? ff : FontFamily.Default;
        double Size(string key, double fallback) => app.TryGetResource(key, null, out var v) && v is double d ? d : fallback;
        app.Resources["LineButton"] = Height(26, new Font(family, FontWeight.SemiBold, Size("FontButton", 10.5)), scale);
        app.Resources["LineSmall"] = Height(24, new Font(family, FontWeight.SemiBold, Size("FontSwitch", 10.5)), scale);
        app.Resources["LineChip"] = Height(24, new Font(family, FontWeight.Normal, Size("FontSwitch", 10.5)), scale);
        app.Resources["LineField"] = Height(24, new Font(family, FontWeight.Normal, Size("FontPanel", 12)), scale);
        app.Resources["LineKey"] = Height(22, new Font(family, FontWeight.SemiBold, Size("FontBase", 13)), scale);
    }

    /// <summary>The height closest above the design one, in whole pixels, with an even number of rows left around the capitals.</summary>
    static double Height(double points, Font font, double scale)
    {
        var caps = Rows(font, scale, Band.Capitals);
        var pixels = (int)Math.Round(points * scale, MidpointRounding.AwayFromZero);
        if ((pixels - caps.Count) % 2 != 0) pixels++;
        return pixels / scale;
    }

    // ------------------------------------------------------------ the rows letters take

    enum Band { Capitals, Small }

    readonly record struct Font(FontFamily Family, FontWeight Weight, double Size, FontStyle Style = FontStyle.Normal, FontStretch Stretch = FontStretch.Normal);

    /// <summary>A run of rows, from the top one to the bottom one.</summary>
    readonly record struct Span(int Top, int Bottom)
    {
        public int Count => Bottom - Top + 1;
    }

    static readonly Dictionary<(string, FontWeight, double, FontStyle, FontStretch, double, Band), Span> Probes = new();

    /// <summary>
    /// The rows the letters take when a line of this font is drawn with its top on a whole pixel: capitals ("НН") or the body of small
    /// letters ("хх"). Found on a picture drawn once for a font and a scale; a row counts when it is at least a third lit.
    /// </summary>
    static Span Rows(Font font, double scale, Band band)
    {
        var key = (font.Family.Name, font.Weight, font.Size, font.Style, font.Stretch, scale, band);
        if (Probes.TryGetValue(key, out var known)) return known;
        var found = new Span(0, 0);
        try
        {
            var sample = new TextBlock
            {
                Text = band == Band.Capitals ? "НН" : "хх", FontFamily = font.Family, FontWeight = font.Weight, FontSize = font.Size,
                FontStyle = font.Style, FontStretch = font.Stretch, Foreground = Brushes.White,
            };
            var root = new Border { Background = Brushes.Black, Child = sample };
            root.Measure(Size.Infinity);
            root.Arrange(new Rect(root.DesiredSize));
            var w = Math.Max(1, (int)Math.Ceiling(root.DesiredSize.Width * scale));
            var h = Math.Max(1, (int)Math.Ceiling(root.DesiredSize.Height * scale));
            using var bitmap = new RenderTargetBitmap(new PixelSize(w, h), new Vector(96 * scale, 96 * scale));
            bitmap.Render(root);
            var stride = w * 4;
            var buffer = Marshal.AllocHGlobal(stride * h);
            try
            {
                bitmap.CopyPixels(new PixelRect(0, 0, w, h), buffer, stride * h, stride);
                var pixels = new byte[stride * h];
                Marshal.Copy(buffer, pixels, 0, pixels.Length);
                int top = -1, bottom = -1;
                for (var y = 0; y < h; y++)
                {
                    var lit = false;
                    for (var x = 0; x < w && !lit; x++) lit = pixels[y * stride + x * 4 + 1] >= 85;   // the green channel: white on black
                    if (!lit) continue;
                    if (top < 0) top = y;
                    bottom = y;
                }
                if (top >= 0) found = new Span(top, bottom);
            }
            finally { Marshal.FreeHGlobal(buffer); }
        }
        catch { }
        return Probes[key] = found;
    }

    static Font FontOf(Control c) => new(
        c.GetValue(TextBlock.FontFamilyProperty), c.GetValue(TextBlock.FontWeightProperty), c.GetValue(TextBlock.FontSizeProperty),
        c.GetValue(TextBlock.FontStyleProperty), c.GetValue(TextBlock.FontStretchProperty));

    /// <summary>A caption of small letters only ("a", a placeholder) is centred by their body; anything with a capital or a digit, by the capitals.</summary>
    static Band BandOf(string? text)
    {
        bool upper = false, lower = false;
        foreach (var c in text ?? "") { if (char.IsUpper(c) || char.IsDigit(c)) upper = true; else if (char.IsLower(c)) lower = true; }
        return lower && !upper ? Band.Small : Band.Capitals;
    }

    // ------------------------------------------------------------ what is registered

    sealed class Item
    {
        public bool IsMarker;
        public double Points;       // the design side of a marker
        public Watch? Owner;        // the watch that places it
    }

    static readonly ConditionalWeakTable<Control, Item> Items = new();

    /// <summary>A word of a button, a chip or a row of a card. Its place is found when it is put into the window.</summary>
    public static void Word(TextBlock word)
    {
        if (Items.TryGetValue(word, out _)) return;
        Items.Add(word, new Item());
        word.AttachedToVisualTree += (_, _) => AttachWord(word);
    }

    /// <summary>
    /// Every word that stands in a button, a chip or a badge under this root, taken in at once: the words written in markup and
    /// those a control made of its caption. Called after a part of the window was built; a word taken in before is left alone.
    /// </summary>
    public static void Adopt(Visual root)
    {
        foreach (var visual in root.GetVisualDescendants())
        {
            if (visual is not TextBlock word || Items.TryGetValue(word, out _) || ButtonOf(word) is null) continue;
            var item = new Item();
            Items.Add(word, item);
            AttachWord(word);
            // The layout has passed already and may not pass again soon: the word is placed now.
            item.Owner?.Kick();
        }
    }

    /// <summary>An icon or a dot: it gets a side of whole pixels and stands in the middle of the word beside it (or of its control, or row).</summary>
    public static void Marker(Control marker, double points)
    {
        if (Items.TryGetValue(marker, out _)) return;
        Items.Add(marker, new Item { IsMarker = true, Points = points });
        marker.AttachedToVisualTree += (_, _) => AttachMarker(marker);
    }

    /// <summary>A one-line text field: its text and its placeholder stand in the middle of the field.</summary>
    public static void Field(TextBox box) =>
        box.TemplateApplied += (_, e) =>
        {
            foreach (var part in new[] { "PART_TextPresenter", "PART_Watermark" })
                if (e.NameScope.Find<Control>(part) is { } text)
                    new Watch(box, text, Mode.Box, () => string.IsNullOrEmpty(box.PlaceholderText) ? Band.Capitals : BandOf(box.PlaceholderText));
        };

    /// <summary>A control of two lines (a name over its hint): its word stays where the layout put it, the icons beside it follow the word.</summary>
    static bool TwoLine(Control host) =>
        host.Classes.Contains("section") || host.Classes.Contains("twoline");

    /// <summary>The row of a card the control stands in: a panel of the class hrow, directly or through the cell of its caption.</summary>
    static Panel? RowOf(Control c)
    {
        var parent = c.GetVisualParent();
        if (parent is Grid { Classes: var cell } && cell.Contains("hcell")) parent = parent.GetVisualParent();
        return parent is Panel p && p.Classes.Contains("hrow") ? p : null;
    }

    /// <summary>The control a word or an icon is centred in: a button, a chip, or a box of the class pxbox (the key caps of ABOUT).</summary>
    static Control? ButtonOf(Control c)
    {
        for (var v = c.GetVisualParent(); v != null; v = v.GetVisualParent())
            if (v is Button or ToggleButton || (v is Border { Classes: var classes } && (classes.Contains("pxbox") || classes.Contains("spec")))) return (Control)v;
        return null;
    }

    /// <summary>The line an icon shares with a word: a horizontal panel (not a row of a card) with a registered word among its children.</summary>
    static StackPanel? LineOf(Control c) =>
        c.GetVisualParent() is StackPanel { Orientation: Orientation.Horizontal } p && !p.Classes.Contains("hrow") ? p : null;

    static void AttachWord(TextBlock word)
    {
        if (!Items.TryGetValue(word, out var item) || item.Owner != null) return;
        Watch watch;
        if (ButtonOf(word) is { } button)
            watch = new Watch(button, word, TwoLine(button) ? Mode.Anchor : Mode.Box, () => BandOf(word.Text));
        else if (RowOf(word) is { } row)
            watch = new Watch(row, word, Mode.Row, () => Band.Capitals);
        else return;
        item.Owner = watch;
        // the icons and dots of the same line follow this word
        if (LineOf(word) is { } line)
            foreach (var child in line.Children)
                if (child != word && Items.TryGetValue(child, out var m) && m.IsMarker)
                {
                    m.Owner = watch;
                    watch.Markers.Add(child);
                }
    }

    static void AttachMarker(Control marker)
    {
        if (!Items.TryGetValue(marker, out var item) || item.Owner != null) return;
        // a word beside it takes it when that word is put into the window
        if (LineOf(marker) is { } line)
            foreach (var child in line.Children)
                if (child is TextBlock && Items.TryGetValue(child, out var w) && !w.IsMarker) return;
        Watch watch;
        if (ButtonOf(marker) is { } button && !TwoLine(button)) watch = new Watch(button, null, Mode.Box, () => Band.Capitals);
        else if (RowOf(marker) is { } row) watch = new Watch(row, null, Mode.Row, () => Band.Capitals);
        else return;
        item.Owner = watch;
        watch.Markers.Add(marker);
    }

    // ------------------------------------------------------------ placing

    enum Mode { Box, Row, Anchor }   // in the middle of the control; in the middle of the row; where the layout put it (two lines)

    static readonly List<WeakReference<Watch>> Live = new();

    /// <summary>How many times the places were looked at and how long it took, in all: for the check of the window.</summary>
    public static long Updates { get; private set; }
    public static double UpdateMilliseconds { get; private set; }
    static readonly System.Diagnostics.Stopwatch Clock = new();

    /// <summary>What was placed and where, in whole pixels of the host: for the check of the window on the real screen.</summary>
    public sealed record Placed(Control Host, Control? Word, string Mode, int HostPixels, int RefTop, int RefPixels, int BandTop, int BandCount,
        int TextTop, IReadOnlyList<(Control Marker, int Top, int Size)> Markers);

    public static List<Placed> Report()
    {
        var list = new List<Placed>();
        foreach (var weak in Live)
            if (weak.TryGetTarget(out var w) && w.Last is { } last) list.Add(last);
        return list;
    }

    sealed class Watch
    {
        readonly Control _host;
        readonly Control? _word;
        readonly Mode _mode;
        readonly Func<Band> _band;
        public readonly List<Control> Markers = new();
        public Placed? Last;

        public Watch(Control host, Control? word, Mode mode, Func<Band> band)
        {
            _host = host; _word = word; _mode = mode; _band = band;
            host.LayoutUpdated += (_, _) => Update();
            lock (Live) Live.Add(new WeakReference<Watch>(this));
        }

        public void Kick() => Update();

        void Update()
        {
            if (!_host.IsEffectivelyVisible) return;
            Updates++;
            var start = Clock.Elapsed;
            if (!Clock.IsRunning) Clock.Start();
            try { Place(); }
            finally { UpdateMilliseconds += (Clock.Elapsed - start).TotalMilliseconds; }
        }

        void Place()
        {
            if (TopLevel.GetTopLevel(_host) is not { } top) return;
            var scale = top.RenderScaling;
            var hostPixels = (int)Math.Round(_host.Bounds.Height * scale);
            if (hostPixels <= 0) return;
            // what the word is centred on: its control; in a row of a card, the first control of the row (a chip, a button, a field) - the
            // row itself is taller by the margin its chips keep under them for wrapping; a row of texts only, the row
            int refTop = 0, refPixels = hostPixels;
            if (_mode == Mode.Row && FirstControl(_host) is { } first && TopIn(first, _host) is var ft && !double.IsNaN(ft))
            {
                refTop = (int)Math.Round(ft * scale);
                refPixels = (int)Math.Round(first.Bounds.Height * scale);
            }

            // the band the markers are centred on: the word's, or the reference when there is no word
            int bandTop = refTop, bandCount = refPixels, textTop = -1;
            if (_word != null)
            {
                if (!_word.IsVisible || _word.Bounds.Height <= 0) return;
                var y = TopIn(_word, _host);
                if (double.IsNaN(y)) return;
                var font = FontOf(_word);
                var band = Rows(font, scale, _band());
                var origin = (int)Math.Round(y * scale);
                var shift = 0;
                // A word of one line alone: one that wrapped stands where the layout put it - centred by its
                // first line it went down by half a line, and its second line was cut by its card.
                if ((_mode == Mode.Box || _mode == Mode.Row) && OneLine(_word, font))
                {
                    var above = origin + band.Top - refTop;
                    var under = refTop + refPixels - 1 - (origin + band.Bottom);
                    // when the rows cannot be shared evenly the spare one stays above: a word a row low is less seen than one a row high
                    shift = (int)Math.Ceiling((under - above) / 2.0);
                }
                Shift(_word, shift, scale);
                bandTop = origin + band.Top + shift;
                bandCount = band.Count;
                textTop = origin + shift;
            }

            var placed = new List<(Control, int, int)>();
            foreach (var marker in Markers)
            {
                if (!marker.IsVisible || !Items.TryGetValue(marker, out var item)) continue;
                // a side of whole pixels, of the parity of the band: then the marker has as many rows above as under inside it
                var side = (int)Math.Round(item.Points * scale);
                if ((side - bandCount) % 2 != 0) side += item.Points * scale >= side ? 1 : -1;
                var points = side / scale;
                if (Math.Abs(marker.Width - points) > 1e-6 || Math.Abs(marker.Height - points) > 1e-6) { marker.Width = points; marker.Height = points; }
                var my = TopIn(marker, _host);
                if (double.IsNaN(my)) continue;
                var target = bandTop + (bandCount - side) / 2;
                Shift(marker, target - (int)Math.Round(my * scale), scale);
                placed.Add((marker, target, side));
            }
            Last = new Placed(_host, _word, _mode.ToString(), hostPixels, refTop, refPixels, bandTop, bandCount, textTop, placed);
        }

        /// <summary>The first control of a row, in the order of its children: a button, a chip or a field that is shown.</summary>
        static Control? FirstControl(Control row)
        {
            foreach (var v in row.GetVisualDescendants())
                if (v is Button or ToggleButton or TextBox && v is Control { IsVisible: true } c && c.Bounds.Height > 0) return c;
            return null;
        }

        /// <summary>A word of one line: a row of a card may hold a text that wraps, and such a text is left as it is.</summary>
        static bool OneLine(Control word, Font font) => word is not TextBlock tb || tb.TextWrapping == TextWrapping.NoWrap || tb.Bounds.Height < font.Size * 2;

        /// <summary>The top of a control inside the host by the layout alone (the offsets set here are render offsets and are not in it).</summary>
        static double TopIn(Control c, Control host)
        {
            double y = 0;
            for (Visual? v = c; v != null && v != host; v = v.GetVisualParent())
            {
                if (v is not Control control) return double.NaN;
                y += control.Bounds.Y;
                if (v.GetVisualParent() == null) return double.NaN;
            }
            return y;
        }

        static void Shift(Control c, int pixels, double scale)
        {
            if (pixels == 0) { if (c.RenderTransform != null) c.RenderTransform = null; return; }
            var points = pixels / scale;
            if (c.RenderTransform is TranslateTransform t && Math.Abs(t.Y - points) < 1e-6 && t.X == 0) return;
            c.RenderTransform = new TranslateTransform(0, points);
        }
    }
}
