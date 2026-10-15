using System.Text.RegularExpressions;
using Avalonia.Controls;
using Avalonia.Controls.Documents;

namespace AudionOfficeOcrAi.Views;

/// <summary>
/// The live line of the terminal in its colours:
///
///     [DOWNLOAD] Vivaldi 8.2.4133.84: 88% · 132.0 / 148.9 MB · 8.6 MB/s
///
/// how much is there - green, how much there will be - orange, the speed - blue, what parts them -
/// quiet, the rest as a line of the terminal. The line is the operation's own
/// (system_core\core\live_line.py says how a download writes it); the window reads sizes and a
/// speed in it wherever they stand and knows no service by its words.
/// </summary>
public static class LiveLine
{
    static readonly Regex Parts = new(
        @"(?<![\w.,])(?<done>\d+(?:[.,]\d+)?(?:\s*[KMGT]?i?B)?)(?<slash>\s*/\s*)(?<total>\d+(?:[.,]\d+)?\s*[KMGT]?i?B)(?![\w/])" +
        @"|(?<![\w.,])(?<speed>\d+(?:[.,]\d+)?\s*[KMGT]?i?B/s)(?!\w)" +
        @"|(?<![\w.,])(?<size>\d+(?:[.,]\d+)?\s*[KMGT]?i?B)(?![\w/])" +
        @"|(?<dot> · )",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    public static void Paint(TextBlock block, string text)
    {
        var inlines = block.Inlines ??= new InlineCollection();
        inlines.Clear();
        void Add(string piece, string key)
        {
            if (piece.Length > 0) inlines.Add(new Run(piece) { Foreground = App.Ink(key) });
        }
        int at = 0;
        foreach (Match match in Parts.Matches(text))
        {
            Add(text[at..match.Index], "LogPlain");
            if (match.Groups["total"].Success)
            {
                Add(match.Groups["done"].Value, "LiveDone");
                Add(match.Groups["slash"].Value, "LogMuted");
                Add(match.Groups["total"].Value, "LiveTotal");
            }
            else if (match.Groups["speed"].Success) Add(match.Value, "LiveSpeed");
            else if (match.Groups["size"].Success) Add(match.Value, "LiveDone");
            else Add(match.Value, "LogMuted");
            at = match.Index + match.Length;
        }
        Add(text[at..], "LogPlain");
    }

    /// <summary>The line while the operation has nothing to say of itself: its name, quiet.</summary>
    public static void Quiet(TextBlock block, string text)
    {
        var inlines = block.Inlines ??= new InlineCollection();
        inlines.Clear();
        inlines.Add(new Run(text) { Foreground = App.Ink("LogMuted") });
    }
}
