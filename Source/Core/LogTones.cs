using System.Text.RegularExpressions;

namespace AudionOfficeOcrAi.Core;

public enum LogTone { Plain, Muted, Head, Good, Warn, Bad }

/// <summary>
/// What colour a line of the terminal is written in. The lines are the runners' own, shown as a
/// console shows them; the colours follow the ones the runners give them there (Write-Host
/// -ForegroundColor): red is what broke, yellow what was passed by or asks for a look, green what
/// went, grey what a command says of itself. A word is looked for where the runners put it - at
/// the start of a line - not anywhere in it: a project may be called "Failed Tests".
/// </summary>
public static class LogTones
{
    static readonly Regex Bad = new(
        @"^\[ERROR\]|^\[ERR\] |^\[GUI ERROR\]|^\[[A-Z0-9 ]+ ERROR\]|^FAILED\b|^STOPPED: |^ERROR[: ]|^\[[^\]]+\] missing selector" +
        @"|^Log audit: issue candidates|^GitHub API report failed|^GPU\s+: NO NVIDIA CARD|^\[LOG CLEAN\] Partial",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);
    static readonly Regex Warn = new(
        @"^\[WARN|^WARNING\b|^\[SKIP|^\[API WAIT\]|^PARTIAL FAILURE|^GitHub: anonymous|^\[DRY|^Build finished with log issue|^\[GUI\] Process killed",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);
    static readonly Regex Good = new(
        @"^\[OK\]|^OK\b|^\[API GREEN\]|^Log audit: no error|^GitHub: authenticated|^\[DONE\]",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);
    static readonly Regex Head = new(
        @"^={10,}$|^-{10,}$|^\[\d+/\d+\] |^AUDION [A-Z0-9 -]+$",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);
    // What a command says of itself and of its way: read when something went wrong, quiet otherwise.
    static readonly Regex Muted = new(
        @"^\[GUI\]|^\[API (START|COUNT)\]|^(Map|Projects|Root|On error|API mode|Logs|API report|GPU|Scan root|Steps|API plan|GitHub API report)\s*:" +
        @"|^""[^""]+\\AudionPs\.exe"" |^Press Enter",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    public static LogTone Of(string line)
    {
        var text = line.TrimEnd();
        if (text.Trim().Length == 0) return LogTone.Plain;
        // The lines of the window around a command: its title, and how it ended.
        if (text.StartsWith("===== ", System.StringComparison.Ordinal))
        {
            if (text.StartsWith("===== OK:", System.StringComparison.Ordinal)) return LogTone.Good;
            if (text.StartsWith("===== FAILED:", System.StringComparison.Ordinal)) return LogTone.Bad;
            if (text.StartsWith("===== PARTIAL FAILURE:", System.StringComparison.Ordinal) || text.StartsWith("===== STOPPED:", System.StringComparison.Ordinal)) return LogTone.Warn;
            return LogTone.Head;
        }
        if (Bad.IsMatch(text)) return LogTone.Bad;
        if (Warn.IsMatch(text)) return LogTone.Warn;
        if (Good.IsMatch(text)) return LogTone.Good;
        if (Head.IsMatch(text)) return LogTone.Head;
        if (Muted.IsMatch(text)) return LogTone.Muted;
        return LogTone.Plain;
    }

    public static string Key(LogTone tone) => tone switch
    {
        LogTone.Muted => "LogMuted", LogTone.Head => "LogHead", LogTone.Good => "LogGood",
        LogTone.Warn => "LogWarn", LogTone.Bad => "LogBad", _ => "LogPlain",
    };
}
