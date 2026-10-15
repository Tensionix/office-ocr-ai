using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Avalonia.Threading;

namespace AudionOfficeOcrAi.Core;

/// <summary>
/// The guard of the window, as the window on WPF kept it. An error nobody caught in the handler
/// of a button is written into logs\gui-event-errors.log, told by one line of the terminal and
/// by the status line, and the window stays. A start that fails before there is a window leaves
/// logs\gui-startup-TIME.log and a message of Windows that names it.
/// </summary>
public static class Guard
{
    /// <summary>The terminal and the status line of the window, when it is there to hear.</summary>
    public static Action<string>? Told;

    static string EventLog => Path.Combine(Paths.Logs, "gui-event-errors.log");

    public static void Install()
    {
        try { Directory.CreateDirectory(Paths.Logs); } catch { }
        Dispatcher.UIThread.UnhandledException += (_, e) =>
        {
            Caught(e.Exception);
            e.Handled = true;
        };
        // An error of a background task nobody waited for closes nothing; it is written down all the same.
        System.Threading.Tasks.TaskScheduler.UnobservedTaskException += (_, e) =>
        {
            try { e.SetObserved(); Write(e.Exception); } catch { }
        };
    }

    /// <summary>
    /// An error of the handler of a button, caught by the guard or handed to it by a handler that
    /// has no better word for it: written into the file, told in the terminal and the status line.
    /// The guard itself must never throw - nobody catches a guard.
    /// </summary>
    public static void Caught(Exception error)
    {
        try { Write(error); } catch { }
        try { Told?.Invoke(error.Message); } catch { }
    }

    static readonly object Gate = new();

    static void Write(Exception error)
    {
        var text = string.Format("[{0}]\r\n{1}\r\n", DateTime.Now.ToString("s"), error);
        lock (Gate) File.AppendAllText(EventLog, text, new UTF8Encoding(false));
    }

    /// <summary>The start itself failed: the reason goes into a file of its own and into a message of Windows.</summary>
    public static void StartFailed(Exception error)
    {
        var file = Path.Combine(Paths.Logs, $"gui-startup-{DateTime.Now:yyyyMMdd-HHmmss}.log");
        try
        {
            Directory.CreateDirectory(Paths.Logs);
            File.WriteAllText(file, error.ToString(), new UTF8Encoding(true));
        }
        catch { }
        try { MessageBoxW(IntPtr.Zero, Lang.T("GUI не запустился.") + "\n" + error.Message + "\n\n" + Lang.F("Лог: {0}", file), "Audion Office OCR AI", 0x10); }
        catch { }
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int MessageBoxW(IntPtr owner, string text, string caption, uint type);
}
