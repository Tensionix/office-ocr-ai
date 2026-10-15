using System;
using System.IO;
using System.Text.RegularExpressions;

namespace AudionOfficeOcrAi.Core;

/// <summary>
/// Where the program lies and what it reads. The window is App\AudionOfficeOcrAi.exe of a release; a
/// Debug build lies deep under Source\ and finds the project by the door it must call. Nothing
/// here names a drive.
/// </summary>
public static class Paths
{
    /// <summary>The root of the program: the folder that holds system_core\, config\ and App\.</summary>
    public static string Root { get; } = FindRoot();

    /// <summary>True when the window runs from App\ of the program - a release, or the working copy after a build of the window.</summary>
    public static bool Released { get; } =
        string.Equals(Path.GetFullPath(AppContext.BaseDirectory).TrimEnd('\\'), Path.Combine(Root, "App"), StringComparison.OrdinalIgnoreCase);

    static string FindRoot()
    {
        var folder = new DirectoryInfo(AppContext.BaseDirectory);
        for (var at = folder; at is not null; at = at.Parent)
            if (File.Exists(Path.Combine(at.FullName, "system_core", "cli.py"))) return at.FullName;
        return folder.Parent?.FullName ?? folder.FullName;
    }

    public static string Config => Path.Combine(Root, "config");

    /// <summary>The config of the project: where the history of paths lies (config\path_history.json).</summary>
    public static string ProjectConfig => Config;

    /// <summary>A path as the program keeps it: whole, from the root of the program when it was given from there.</summary>
    public static string Full(string path)
    {
        var typed = path.Trim().Trim('"');
        if (typed.Length == 0) return "";
        try { return Path.GetFullPath(Path.IsPathRooted(typed) ? typed : Path.Combine(Root, typed)); }
        catch { return typed; }
    }

    /// <summary>The console door: the wrapper a person types, and the script the window starts itself.</summary>
    public static string DoorName => "ocr_cli.cmd";
    public static string Door => Path.Combine(Root, DoorName);
    public static string DoorScript =>
#if DEBUG
        StandDoor.Length > 0 ? StandDoor :
#endif
        Path.Combine(Root, "system_core", "cli.py");

#if DEBUG
    /// <summary>A stand of the window: the script that answers in place of the door (Source\Tools\stand_door.py); "" - the door itself.</summary>
    public static string StandDoor { get; set; } = "";
#endif

    /// <summary>The Python of the project; "" when the environment is not built.</summary>
    public static string Python
    {
        get
        {
            foreach (var candidate in new[] { @"runtime\python.exe", @"runtime\python\python.exe" })
            {
                var path = Path.Combine(Root, candidate);
                if (File.Exists(path)) return path;
            }
            return "";
        }
    }

    /// <summary>
    /// What the window keeps for itself between a press and a run - the values of a run, its
    /// outcome, the stop signal - and its own logs. A release keeps them in ._runtime and logs of
    /// the program. A Debug copy keeps them beside itself: a check of the window must not write
    /// over the files a window at work is using.
    /// </summary>
    public static string Runtime => Released ? Path.Combine(Root, "._runtime") : Path.Combine(AppContext.BaseDirectory, "._runtime");
    public static string Logs => Released ? Path.Combine(Root, "logs") : Path.Combine(AppContext.BaseDirectory, "logs");

    /// <summary>The files of this window alone: two windows of two copies never share a run.</summary>
    public static string Session
    {
        get
        {
            var folder = Path.Combine(Runtime, "window-" + Environment.ProcessId);
            Directory.CreateDirectory(folder);
            return folder;
        }
    }

    /// <summary>The window is going: its files of a run go with it.</summary>
    public static void DropSession()
    {
        try { Directory.Delete(Path.Combine(Runtime, "window-" + Environment.ProcessId), recursive: true); } catch { }
    }

    /// <summary>
    /// The folders of windows that are no more. A window that fell left its own behind, and in it
    /// the values of its last run - what a person typed for a download among them. A folder goes
    /// when no process carries its number, or the process that does is another program; a process
    /// that cannot be asked is taken for a window at work, and its folder is left alone.
    /// </summary>
    public static void DropDeadSessions()
    {
        try
        {
            if (!Directory.Exists(Runtime)) return;
            using var me = System.Diagnostics.Process.GetCurrentProcess();
            foreach (var folder in Directory.GetDirectories(Runtime, "window-*"))
            {
                if (!int.TryParse(Path.GetFileName(folder).AsSpan("window-".Length), out int id) || id == Environment.ProcessId) continue;
                bool alive;
                try
                {
                    using var other = System.Diagnostics.Process.GetProcessById(id);
                    alive = string.Equals(other.ProcessName, me.ProcessName, StringComparison.OrdinalIgnoreCase);
                }
                catch (ArgumentException) { alive = false; }
                catch { alive = true; }
                if (!alive) try { Directory.Delete(folder, recursive: true); } catch { }
            }
        }
        catch { }
    }

    /// <summary>The logs folder the buttons open is the program's own, in a release and in a check alike.</summary>
    public static string ProgramLogs => Path.Combine(Root, "logs");

    /// <summary>
    /// The PowerShell the window starts a script of the program with: its own (App\AudionPs.exe),
    /// or Windows PowerShell while the window is a Debug build that has none beside it.
    /// </summary>
    public static string PowerShell
    {
        get
        {
            var own = Path.Combine(Root, "App", "AudionPs.exe");
            if (File.Exists(own)) return own;
            return Path.Combine(Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe");
        }
    }

    /// <summary>A path inside the program as a person reads it: from the root of the program.</summary>
    public static string Short(string path)
    {
        try
        {
            var full = Path.GetFullPath(path);
            var root = Root.TrimEnd('\\') + "\\";
            return full.StartsWith(root, StringComparison.OrdinalIgnoreCase) ? full[root.Length..] : full;
        }
        catch { return path; }
    }

    /// <summary>The version of config\version.json, or null when it does not read as one.</summary>
    public static string? Version
    {
        get
        {
            try
            {
                var match = Regex.Match(File.ReadAllText(Path.Combine(Config, "version.json")), "\"version\"\\s*:\\s*\"([^\"]+)\"");
                var candidate = match.Success ? match.Groups[1].Value : "";
                return Regex.IsMatch(candidate, @"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$") ? candidate : null;
            }
            catch { return null; }
        }
    }
}
