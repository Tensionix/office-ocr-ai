using System;
using System.Collections.Generic;
using System.Linq;

namespace AudionOfficeOcrAi.Core;

/// <summary>
/// The search of a list of cards. A card is in sight when its name and its value together hold
/// every word typed, whatever the case - the window on NiceGUI looked for the whole query as one
/// piece (filter_checkbox_options); word by word finds "nvidia whql" in "WHQL ... NVIDIA" too.
/// A value that is an address - the file of a driver - is not searched: nobody sees it on the
/// card, and "exe" or "whql" would find every card of the list.
/// A heading of a list is in sight while a card under it is; a line of explanation over the list
/// always. A search hides cards and changes no choice: what is ticked stays ticked, in sight or not.
/// </summary>
public static class Search
{
    /// <summary>The words of a query.</summary>
    public static string[] Words(string? query) =>
        (query ?? "").Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    /// <summary>The card holds every word: in its name, in either language, or in its value - the id of a package, not the address of a file.</summary>
    public static bool Matches(Option option, IReadOnlyCollection<string> words)
    {
        if (words.Count == 0) return true;
        var key = option.Key;
        var where = option.Label + " " + option.LabelRu + (key.Contains('/') ? "" : " " + key);
        return words.All(word => where.Contains(word, StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>Which options of a list are in sight for a query, one answer an option, in the order of the list.</summary>
    public static List<bool> Shown(IReadOnlyList<Option> options, string? query)
    {
        var words = Words(query);
        var shown = new List<bool>(options.Count);
        int heading = -1;
        for (int i = 0; i < options.Count; i++)
        {
            var option = options[i];
            if (option.Header && option.Note) { shown.Add(true); continue; }
            if (option.Header) { heading = i; shown.Add(false); continue; }
            bool match = Matches(option, words);
            shown.Add(match);
            if (match && heading >= 0) shown[heading] = true;
        }
        return shown;
    }
}
