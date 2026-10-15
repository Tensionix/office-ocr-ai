using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace AudionOfficeOcrAi.Core;

/// <summary>What a short call of the door answered.</summary>
public sealed record Reply(int Code, string Out, string Err)
{
    public bool Ok => Code == 0;
}

/// <summary>A service line of a run ("::get::{...}"): the start, how far the work is, the one live line, the end.</summary>
public sealed class DoorEvent
{
    /// <summary>started, progress, activity or finished; "" for a line of a kind this window does not know.</summary>
    public string Kind { get; init; } = "";
    /// <summary>The share of the work done, 0..1.</summary>
    public double Progress { get; init; } = -1;
    /// <summary>The live line under the journal: what goes on right now; "" clears it.</summary>
    public string Activity { get; init; } = "";
    /// <summary>done, failed or stopped.</summary>
    public string Outcome { get; init; } = "";
    public string Message { get; init; } = "";
}

/// <summary>
/// The door of the engine. A button of the window does nothing a console cannot: it runs
/// ocr_cli.cmd with the words a person would type, and that line is written into the journal.
/// The window starts the Python of the project itself, the way the wrapper does - so a path is
/// quoted once, by the system, and not a second time by the rules of cmd. Which fields an
/// operation has, what their defaults are, which parameters a service gets - the door alone
/// knows (system_core\cli.py).
/// </summary>
public static class Door
{
    public const string Control = "::ocr::";
    public const int ExitDone = 0, ExitFailed = 1, ExitUsage = 2, ExitStopped = 130;

    /// <summary>Why the door cannot be called, in the words of the window; "" when it can.</summary>
    public static string Trouble =>
        !File.Exists(Paths.DoorScript) ? Lang.F("нет файла: {0}", Paths.DoorScript)
        : Paths.Python.Length == 0 ? Lang.F("нет Python программы ({0}): сначала соберите окружение - builder_main.cmd", Path.Combine(Paths.Root, @"runtime\python.exe"))
        : "";

    public static bool Ready => Trouble.Length == 0;

    // What ocr_cli.cmd does before it calls Python: UTF-8 everywhere (-X utf8 is PYTHONUTF8=1),
    // lines at once (-u), the door started as a file.
    static IEnumerable<string> Head => new[] { "-X", "utf8", "-u", Paths.DoorScript, "--language", Lang.Code == "ru" ? "ru" : "en" };

    public static string ParamsFile => Path.Combine(Paths.Session, "params.json");
    public static string ResultFile => Path.Combine(Paths.Session, "result.json");
    /// <summary>The stop signal: the file appears - the operation stops at its next safe point.</summary>
    public static string StopFile => Path.Combine(Paths.Session, "stop.flag");

    /// <summary>
    /// A word of a line as a console reads it back: quoted when it holds a space or a sign a
    /// console treats as its own; a backslash before a quote is doubled, or a path that ends in
    /// one would swallow the closing quote.
    /// </summary>
    static string Quote(string value)
    {
        if (value.Length > 0 && value.IndexOfAny(new[] { ' ', '\t', '"', '&', '(', ')', '^', '=', ';', ',', '%', '!', '<', '>', '|' }) < 0) return value;
        var text = new StringBuilder("\"");
        int slashes = 0;
        foreach (var ch in value)
        {
            if (ch == '\\') { slashes++; continue; }
            if (ch == '"') text.Append('\\', slashes * 2 + 1).Append('"');
            else text.Append('\\', slashes).Append(ch);
            slashes = 0;
        }
        return text.Append('\\', slashes * 2).Append('"').ToString();
    }

    /// <summary>The same run as a person would type it: written into the journal at every start.</summary>
    public static string RunLine(string operation, string source, string target, IReadOnlyDictionary<string, string> changed, string secret = "")
    {
        var words = new List<string> { Paths.DoorName, "run", "--operation", operation };
        if (source.Length > 0) { words.Add("--source"); words.Add(Paths.Short(source)); }
        if (target.Length > 0) { words.Add("--target"); words.Add(Paths.Short(target)); }
        // A value the operation asks for is named, never written: the door reads it from its standard input.
        if (secret.Length > 0) { words.Add("--secret-stdin"); words.Add(secret); }
        foreach (var (name, value) in changed) { words.Add("--set"); words.Add(name + "=" + value); }
        return string.Join(" ", words.Select(Quote));
    }

    /// <summary>
    /// A run: the values of the fields go by a file - a text with quotes is not for a command
    /// line. The value an operation asks for before it runs (`secret` - its name) goes by the
    /// standard input of the door, in no argument and in no file.
    /// </summary>
    public static Launch Run(string operation, string source, string target, string secret = "", string? value = null)
    {
        var args = Head.Concat(new[] { "run", "--operation", operation }).ToList();
        args.AddRange(Folders(source, target));
        if (secret.Length > 0) { args.Add("--secret-stdin"); args.Add(secret); }
        // The colours the services write their lines in come as they are: the terminal shows them (Core\Ansi.cs).
        args.AddRange(new[] { "--params", ParamsFile, "--result", ResultFile, "--cancel-file", StopFile, "--colours" });
        return new Launch { Exe = Paths.Python, Args = args, Input = secret.Length > 0 ? value ?? "" : null };
    }

    /// <summary>The files of the last run are cleared away and the values of the new one written; the reason when that did not work.</summary>
    public static string Prepare(string valuesJson)
    {
        try
        {
            foreach (var file in new[] { ResultFile, StopFile })
                if (File.Exists(file)) File.Delete(file);
            File.WriteAllText(ParamsFile, valuesJson, new UTF8Encoding(false));
            return "";
        }
        catch (Exception ex) { return ex.Message; }
    }

    /// <summary>Asks the running operation to stop. "" when the signal is written; the reason when it could not be.</summary>
    public static string AskToStop()
    {
        try { File.WriteAllText(StopFile, DateTime.Now.ToString("O")); return ""; }
        catch (Exception ex) { return ex.Message.Length > 0 ? ex.Message : ex.GetType().Name; }
    }

    /// <summary>The service line of a run read; null when the line is an ordinary one.</summary>
    public static DoorEvent? Read(string line)
    {
        if (!line.StartsWith(Control, StringComparison.Ordinal)) return null;
        try
        {
            using var doc = JsonDocument.Parse(line[Control.Length..]);
            var root = doc.RootElement;
            static string Text(JsonElement owner, string name) => owner.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";
            if (root.TryGetProperty("started", out _)) return new DoorEvent { Kind = "started" };
            if (root.TryGetProperty("finished", out var finished))
                return new DoorEvent { Kind = "finished", Outcome = Text(finished, "outcome"), Message = Text(finished, "message") };
            if (root.TryGetProperty("progress", out var share) && share.ValueKind == JsonValueKind.Number)
                return new DoorEvent { Kind = "progress", Progress = share.GetDouble() };
            if (root.TryGetProperty("activity", out var activity) && activity.ValueKind == JsonValueKind.String)
                return new DoorEvent { Kind = "activity", Activity = activity.GetString() ?? "" };
            // A service line of a kind this window does not know yet: not for the journal either way.
            return new DoorEvent { Kind = "" };
        }
        catch { return new DoorEvent { Kind = "" }; }
    }

    /// <summary>The two folders as words of a call: each only when it is named.</summary>
    static IEnumerable<string> Folders(string source, string target)
    {
        if (source.Length > 0) { yield return "--source"; yield return source; }
        if (target.Length > 0) { yield return "--target"; yield return target; }
    }

    // ------------------------------------------------------------ short calls

    /// <summary>
    /// A call that answers and ends - the description, a list of options, a gate: the door is
    /// run and its output read whole. Never throws: a door that could not be started answers
    /// with the code -1 and the reason.
    /// </summary>
    public static async Task<Reply> Call(IEnumerable<string> words, int timeoutMs = 180_000, string? input = null)
    {
        if (!Ready) return new Reply(-1, "", Trouble);
        var info = new ProcessStartInfo(Paths.Python)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            RedirectStandardInput = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            WorkingDirectory = Paths.Root,
        };
        foreach (var word in Head.Concat(words)) info.ArgumentList.Add(word);
        try
        {
            using var process = Process.Start(info) ?? throw new InvalidOperationException("the process was not created");
            // A value for the door alone - a key - goes by its standard input, in no argument and in no file.
            try
            {
                if (input is not null) { await process.StandardInput.WriteLineAsync(input); await process.StandardInput.FlushAsync(); }
                process.StandardInput.Close();
            }
            catch { }
            var output = process.StandardOutput.ReadToEndAsync();
            var errors = process.StandardError.ReadToEndAsync();
            var exited = process.WaitForExitAsync();
            if (await Task.WhenAny(exited, Task.Delay(timeoutMs)) != exited)
            {
                try { process.Kill(entireProcessTree: true); } catch { }
                return new Reply(-1, "", Lang.F("консольная команда не ответила за {0} с", timeoutMs / 1000));
            }
            // The door has ended. What it wrote is read to its end, but not for ever: a program it
            // started and left running - WinUtil, the console of an image build - may hold the pipe.
            var said = Task.WhenAll(output, errors);
            if (await Task.WhenAny(said, Task.Delay(5_000)) != said)
                return new Reply(process.ExitCode, output.IsCompletedSuccessfully ? output.Result : "", errors.IsCompletedSuccessfully ? errors.Result : "");
            return new Reply(process.ExitCode, await output, await errors);
        }
        catch (Exception ex) { return new Reply(-1, "", ex.Message); }
    }

    static string Lines(string text) => string.Join(" ", text.Split('\n').Select(line => line.Trim()).Where(line => line.Length > 0));

    /// <summary>The last line of an answer that is JSON: the door prints one, and a service may have printed before it.</summary>
    static string LastJson(string output) =>
        output.Split('\n').Select(line => line.Trim()).LastOrDefault(line => line.StartsWith('{')) ?? "";

    /// <summary>What the program is made of, or the reason it could not be told.</summary>
    public static async Task<(Described? Told, string Trouble)> Describe()
    {
        var reply = await Call(new[] { "describe" });
        if (!reply.Ok) return (null, Lines(reply.Err.Length > 0 ? reply.Err : reply.Out));
        try { return (Described.Parse(LastJson(reply.Out)), ""); }
        catch (Exception ex) { return (null, ex.Message); }
    }

    static int _asked;

    /// <summary>
    /// The list of a field, asked of its provider with the values of the form and the folders of
    /// the page - a list that shows what lies in the source looks where the run will read; the
    /// reason when there is no list.
    /// </summary>
    public static async Task<(List<Option> Options, string Trouble)> Options(string node, string field, string valuesJson, string source = "", string target = "", bool refresh = false)
    {
        var file = Path.Combine(Paths.Session, $"options-{System.Threading.Interlocked.Increment(ref _asked)}.json");
        try
        {
            File.WriteAllText(file, valuesJson, new UTF8Encoding(false));
            // A list of models is asked of its provider only by REFRESH: every other answer is what the program keeps.
            var words = new[] { "options", "--operation", node, "--field", field }.Concat(Folders(source, target)).Concat(new[] { "--params", file });
            if (refresh) words = words.Append("--refresh");
            var reply = await Call(words);
            var json = LastJson(reply.Out);
            if (json.Length == 0) return (new List<Option>(), Lines(reply.Err.Length > 0 ? reply.Err : Lang.T("консольная команда не ответила")));
            using var doc = JsonDocument.Parse(json);
            var trouble = doc.RootElement.TryGetProperty("error", out var error) ? error.GetString() ?? "" : "";
            var options = doc.RootElement.TryGetProperty("options", out var list) ? Described.ParseOptions(list) : new List<Option>();
            return (options, trouble);
        }
        catch (Exception ex) { return (new List<Option>(), ex.Message); }
        finally { try { File.Delete(file); } catch { } }
    }

    /// <summary>An option of a list is pinned to its head, or the pin is taken off: "" when done, else the reason.</summary>
    public static async Task<string> Pin(string node, string field, string value, bool on)
    {
        var words = new List<string> { "pin", "--operation", node, "--field", field, "--value", value };
        if (!on) words.Add("--off");
        var reply = await Call(words, 30_000);
        try
        {
            using var doc = JsonDocument.Parse(LastJson(reply.Out));
            if (doc.RootElement.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.True) return "";
            return doc.RootElement.TryGetProperty("error", out var error) ? error.GetString() ?? "" : reply.Err.Trim();
        }
        catch { return reply.Err.Trim().Length > 0 ? reply.Err.Trim() : Lang.T("консольная команда не ответила"); }
    }

    /// <summary>Whether an operation may run now: "" when it may, else the words of why not.</summary>
    public static async Task<string> Gate(string node, string valuesJson, string source = "", string target = "")
    {
        var file = Path.Combine(Paths.Session, $"gate-{System.Threading.Interlocked.Increment(ref _asked)}.json");
        try
        {
            File.WriteAllText(file, valuesJson, new UTF8Encoding(false));
            var reply = await Call(new[] { "gate", "--operation", node }.Concat(Folders(source, target)).Concat(new[] { "--params", file }), 30_000);
            using var doc = JsonDocument.Parse(LastJson(reply.Out));
            return doc.RootElement.TryGetProperty("blocked", out var blocked) && blocked.ValueKind == JsonValueKind.True
                ? doc.RootElement.GetProperty("text").GetString() ?? "" : "";
        }
        catch { return ""; }
        finally { try { File.Delete(file); } catch { } }
    }

    /// <summary>
    /// A key of a provider. "add": the key goes by the standard input of the door and is written into a
    /// file of config the door names; "remove": the file the field names is set aside (config\deleted_keys).
    /// The file written or set aside, or the reason it was not.
    /// </summary>
    public static async Task<(string File, string Trouble)> Key(string action, string provider, string name, string secret)
    {
        var words = new List<string> { "key", action, "--provider", provider };
        if (action == "add") { if (name.Length > 0) { words.Add("--name"); words.Add(name); } }
        else { words.Add("--file"); words.Add(name); }
        var reply = await Call(words, 30_000, action == "add" ? secret : null);
        try
        {
            using var doc = JsonDocument.Parse(LastJson(reply.Out));
            var root = doc.RootElement;
            if (root.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.True)
                return ((root.TryGetProperty("file", out var file) ? file : root.GetProperty("archived")).GetString() ?? "", "");
            return ("", root.TryGetProperty("error", out var error) ? error.GetString() ?? "" : Lines(reply.Err));
        }
        catch { return ("", Lines(reply.Err).Length > 0 ? Lines(reply.Err) : Lang.T("консольная команда не ответила")); }
    }

    /// <summary>What this machine has for OCR - the video card, Tesseract, the layout service of Surya - as the door tells it; null when it did not.</summary>
    public static async Task<Hardware?> Hardware()
    {
        var reply = await Call(new[] { "hardware" }, 60_000);
        try { return Core.Hardware.Parse(LastJson(reply.Out)); }
        catch { return null; }
    }
}
