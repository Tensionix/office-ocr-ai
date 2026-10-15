using System;
using System.Collections.Generic;
using System.Linq;

namespace AudionOfficeOcrAi.Core;

/// <summary>
/// The lists the door has given a form, each with the term the manifest names for it
/// (`cache_seconds` of its field): 20 s for what WinGet says of this machine, five minutes for the
/// drivers of the machine, an hour for the versions a vendor has. A list older than its term is
/// asked anew when its page comes into sight. After a run that ended well the lists about the
/// machine are another answer - those with a term under an hour, and those with none - while the
/// catalogue of a vendor is what it was: to download one driver must not send the page to
/// NVIDIA's service again, which may keep silent for a minute (the audit of 10.10.2026).
/// </summary>
public sealed class ListMemory
{
    sealed record Kept(List<Option> Options, string Trouble, DateTime At, double Seconds);

    /// <summary>A term from which a list is a catalogue, not a state of the machine: it outlives a run.</summary>
    public const double LongLived = 3600;

    readonly Dictionary<string, Kept> _kept = new();

    /// <summary>The clock; a check sets its own.</summary>
    public Func<DateTime> Now { get; set; } = () => DateTime.UtcNow;

    public int Count => _kept.Count;

    public bool TryGet(string key, out (List<Option> Options, string Trouble) known)
    {
        if (_kept.TryGetValue(key, out var kept)) { known = (kept.Options, kept.Trouble); return true; }
        known = (new List<Option>(), "");
        return false;
    }

    public void Put(string key, List<Option> options, string trouble, double seconds) =>
        _kept[key] = new Kept(options, trouble, Now(), Math.Max(0, seconds));

    public bool Remove(string key) => _kept.Remove(key);

    public void Clear() => _kept.Clear();

    bool Drop(Func<Kept, bool> gone)
    {
        var keys = _kept.Where(pair => gone(pair.Value)).Select(pair => pair.Key).ToList();
        foreach (var key in keys) _kept.Remove(key);
        return keys.Count > 0;
    }

    /// <summary>The page comes into sight: the lists older than their term go. True when one went. A list without a term does not age.</summary>
    public bool DropExpired()
    {
        var now = Now();
        return Drop(kept => kept.Seconds > 0 && (now - kept.At).TotalSeconds > kept.Seconds);
    }

    /// <summary>A run ended well: the lists with a term under an hour go, and those with none. True when one went.</summary>
    public bool DropAfterRun() => Drop(kept => kept.Seconds < LongLived);
}
