using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Avalonia.Threading;

namespace AudionOfficeOcrAi.Core;

/// <summary>One start of a command: the program, its arguments, and the line the terminal shows for it.</summary>
public sealed class Launch
{
    public string Exe { get; init; } = "";

    /// <summary>The arguments one by one: .NET quotes each for the program that reads them.</summary>
    public List<string> Args { get; init; } = new();

    /// <summary>
    /// The arguments as one ready line - for cmd.exe alone, which reads its line by rules of its
    /// own; used instead of Args when it is not empty.
    /// </summary>
    public string CommandLine { get; init; } = "";

    /// <summary>The same command as a person would type it: written into the terminal at the start.</summary>
    public string Shown { get; init; } = "";

    /// <summary>
    /// One line for the standard input of the command, written at its start - the value an
    /// operation asked for, a secret among them: it is in no argument and in no file. Null - the
    /// command is given nothing to read.
    /// </summary>
    public string? Input { get; init; }
}

/// <summary>
/// Runs a command as a child process, one at a time: its lines go to the window in batches, the
/// lines of its error stream marked [ERR] as the window on WPF marked them. The command, failing,
/// does not take the window with it; STOP ends the process with everything it started - the
/// PowerShell of the runner, the cmd of a project's builder, and whatever runs under that, also
/// what outlived its own parent: the job the command was put into holds them all (ChildJob).
/// The runner of Audion Sync Tools without its queue, by way of Audion Build Publisher.
/// </summary>
public sealed class Runner
{
    Process? _current;
    bool _stopped;

    // A process speaks on its reader threads; the window hears it in batches, at most ten times
    // a second. A line per file from tens of thousands of files once froze the window of Disk
    // Tools (24.09.2026).
    readonly object _gate = new();
    readonly List<string> _batch = new();
    int _flushPosted;
    long _lastFlush;

    public bool Running { get; private set; }

    /// <summary>Windows refused to tie the last command to the window: if the window falls, the command stays.</summary>
    public bool Loose { get; private set; }

    /// <summary>The lines of the command, in batches, on the window's thread.</summary>
    public event Action<IReadOnlyList<string>>? Output;
    /// <summary>The run ended: its exit code and whether STOP ended it.</summary>
    public event Action<int, bool>? Finished;

    /// <summary>Starts a run. Null when it started; otherwise why it did not - nothing is raised then.</summary>
    public string? Start(Launch launch)
    {
        if (Running) return "a command is running already";
        var info = new ProcessStartInfo(launch.Exe)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            // A command that asks (pause, input) with nobody to answer must end, not wait for ever.
            RedirectStandardInput = true,
            // What the command reads is UTF-8 with no mark before it: the first line is the value itself.
            StandardInputEncoding = new UTF8Encoding(false),
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            WorkingDirectory = Paths.Root,
        };
        if (launch.CommandLine.Length > 0) info.Arguments = launch.CommandLine;
        else foreach (var arg in launch.Args) info.ArgumentList.Add(arg);

        Process process;
        try
        {
            process = Process.Start(info) ?? throw new InvalidOperationException("the process was not created");
        }
        catch (Exception ex)
        {
            return ex.Message;
        }
        // The value the command was started to read, then the input is closed. Either on its own:
        // a write or a close that failed is not a start that failed - the command runs, and the
        // window must go on watching it.
        try { if (launch.Input is { } input) process.StandardInput.WriteLine(input); } catch { }
        try { process.StandardInput.Close(); } catch { }

        // A window that falls must not leave a build behind it (ChildJob).
        Loose = !ChildJob.Hold(process);
        _current = process;
        _stopped = false;
        Running = true;

        // A stream ends with the last process that holds it; its reader then hands over a null.
        var outputEnd = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var errorEnd = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        bool over = false;

        void OnLine(string? line, bool error)
        {
            if (line is null)
            {
                (error ? errorEnd : outputEnd).TrySetResult();
                return;
            }
            // The verdict is out: a line of something the command left behind is nobody's line.
            if (Volatile.Read(ref over)) return;
            lock (_gate) _batch.Add(error ? ErrorLine(line) : line);
            // One flush waits in the window's queue at a time, and not sooner than 100 ms after
            // the last: whatever arrives meanwhile rides along.
            if (Interlocked.Exchange(ref _flushPosted, 1) != 0) return;
            if (DateTime.UtcNow.Ticks - Interlocked.Read(ref _lastFlush) >= TimeSpan.TicksPerMillisecond * 100)
                Dispatcher.UIThread.Post(Flush, DispatcherPriority.Background);
            // Too soon after the last flush: the line waits out the 100 ms, not the next line - or a
            // command that said what it does and then worked for a minute would show its words
            // only after the minute.
            else
                Task.Delay(100).ContinueWith(_ => Dispatcher.UIThread.Post(Flush, DispatcherPriority.Background));
        }
        process.OutputDataReceived += (_, e) => OnLine(e.Data, false);
        process.ErrorDataReceived += (_, e) => OnLine(e.Data, true);
        // Subscribed before the events are switched on: a process that ended in between would
        // never be told of, and the window would stay "running".
        process.Exited += (_, _) =>
        {
            // Every line is in before the last flush and the verdict: the readers are waited
            // for. Not for ever - a command may leave a process behind that holds its output
            // open (a helper, a server it started), and a wait without a limit once kept the
            // window "running" for good, with STOP unable to find a process whose parent was gone.
            bool whole = false;
            try { whole = Task.WhenAll(outputEnd.Task, errorEnd.Task).Wait(EndOfOutput); } catch { }
            Dispatcher.UIThread.Post(() =>
            {
                // The verdict comes whatever the last lines do to the window.
                try { Flush(); }
                finally
                {
                    Volatile.Write(ref over, true);
                    Done(process, whole);
                }
            }, DispatcherPriority.Background);
        };
        process.EnableRaisingEvents = true;
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        return null;
    }

    /// <summary>
    /// A line of the error stream as the terminal shows it: marked [ERR]. A line that names itself
    /// so already - the door writes its refusals that way - is not marked a second time.
    /// </summary>
    public static string ErrorLine(string line) => line.StartsWith("[ERR]", StringComparison.Ordinal) ? line : "[ERR] " + line;

    /// <summary>How long the last lines of a command are waited for once it has ended.</summary>
    static readonly TimeSpan EndOfOutput = TimeSpan.FromSeconds(3);

    void Flush()
    {
        string[] lines;
        lock (_gate)
        {
            lines = _batch.ToArray();
            _batch.Clear();
            Interlocked.Exchange(ref _lastFlush, DateTime.UtcNow.Ticks);
            Interlocked.Exchange(ref _flushPosted, 0);
        }
        if (lines.Length > 0) Output?.Invoke(lines);
    }

    void Done(Process process, bool whole)
    {
        int code;
        try { code = process.ExitCode; } catch { code = -1; }
        process.Dispose();
        _current = null;
        Running = false;
        if (!whole) Output?.Invoke(new[] { "[GUI] The command has ended and left a process behind that holds its output open; its lines are no longer read." });
        Finished?.Invoke(code, _stopped);
    }

    /// <summary>
    /// STOP: ends the running command with its children. True - a command that was still at work
    /// was ended by this press. False - there was nothing to stop: no run, a press that came
    /// after the first, or a command that had ended by itself and only its last lines were waited
    /// for - its own exit code stands then, and what it left behind is ended all the same.
    /// </summary>
    public bool Stop()
    {
        if (_current is not { } process) return false;
        bool alive;
        try { alive = !process.HasExited; } catch { alive = false; }
        bool first = alive && !_stopped;
        if (alive) _stopped = true;
        // The job first: it holds everything the command started, also a process whose parent
        // has ended and whom the walk down the tree does not find. The walk stays for a command
        // Windows refused to put into the job.
        if (!Loose) ChildJob.EndAll();
        try { process.Kill(entireProcessTree: true); } catch { }
        return first;
    }

    /// <summary>The window is closing: STOP, and the process is waited for - it must not outlive the window.</summary>
    public void StopForClose()
    {
        if (_current is not { } process) return;
        Stop();
        try { process.WaitForExit(3000); } catch { }
    }
}
