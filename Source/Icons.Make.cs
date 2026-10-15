using Avalonia;
using Avalonia.Controls.Shapes;
using Avalonia.Media;

namespace AudionOfficeOcrAi;

/// <summary>
/// How the signs of Icons.cs get onto the screen. A Lucide sign is strokes on a 24 grid, shown on
/// the 10 grid of the style "Path.icon" (the shell of Audion Disk Tools: centred by App.CenterIcon,
/// the line as thick as there); a brand mark - the providers of API OCR - is one filled path in the
/// same box (Audion Browsers Portable).
/// </summary>
public static partial class Icons
{
    /// <summary>The geometry of a Lucide sign on the 10 grid; null when the set has no such name.</summary>
    public static Geometry? Glyph(string name)
    {
        if (Made.TryGetValue(name, out var made)) return made;
        if (!Lucide.TryGetValue(name, out var data)) return null;
        var geometry = Geometry.Parse(data);
        // Scaled in the geometry, not by a Viewbox: the pen keeps the thickness of the style.
        geometry.Transform = new ScaleTransform(10 / 24.0, 10 / 24.0);
        // A sign is drawn hundreds of times on a page of cards: its drawing is read once and shared.
        return Made[name] = geometry;
    }

    static readonly System.Collections.Generic.Dictionary<string, Geometry> Made = new();

    /// <summary>A Lucide sign ready for a button.</summary>
    public static Path Sign(string name) => new() { Classes = { "icon" }, Data = Glyph(name) };

    /// <summary>
    /// A brand mark, in the ink of the text around it; <paramref name="ink"/> gives it a colour of
    /// its own. The mark is fitted into a square of <paramref name="size"/> by the bounds of its own
    /// drawing and stands in the middle of it: the sets draw their marks on boxes of 24, of 600,
    /// and one mark here is a single letter cut out of a word - the box says nothing reliable.
    /// </summary>
    public static Path? Mark(string name, IBrush? ink = null, double size = 10)
    {
        if (!Brand.TryGetValue(name, out var brand)) return null;
        var geometry = Geometry.Parse(brand.Path);
        var bounds = geometry.Bounds;
        double side = System.Math.Max(bounds.Width, bounds.Height);
        if (side <= 0) return null;
        double scale = size / side;
        geometry.Transform = new MatrixTransform(
            Matrix.CreateTranslation(-bounds.X - bounds.Width / 2, -bounds.Y - bounds.Height / 2)
            * Matrix.CreateScale(scale, scale)
            * Matrix.CreateTranslation(size / 2, size / 2));
        var path = new Path { Classes = { "iconfill" }, Data = geometry, Width = size, Height = size };
        // A mark wears the colour of its brand (the owner: "accent the signs with the colours of the brands");
        // one with no colour of its own - xAI - the ink of the text around it.
        if (ink is not null) path.Fill = ink;
        else if (brand.Hex.Length > 0) path.Fill = SolidColorBrush.Parse(brand.Hex);
        return path;
    }

    /// <summary>
    /// The sign the layout names for a section, a page, a switch or an operation: a brand mark when
    /// the name is one, a Lucide sign otherwise; null when the name is empty or the set does not have it.
    /// </summary>
    public static Path? Face(string name, IBrush? ink = null, double size = 10)
    {
        if (string.IsNullOrEmpty(name)) return null;
        if (Mark(name, ink, size) is { } mark) return mark;
        if (Glyph(name) is not { } glyph) return null;
        var sign = new Path { Classes = { "icon" }, Data = glyph };
        if (ink is not null) sign.Stroke = ink;
        return sign;
    }
}
