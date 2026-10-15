#if DEBUG
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using AudionOfficeOcrAi.Core;

namespace AudionOfficeOcrAi;

/// <summary>
/// The stand of the window: -Stand "folder" puts the window together without showing it, gives it
/// a door that only pretends (Source\Tools\stand_door.py) and walks what a run can come to - an
/// operation that ends by itself, one that stops at the signal, one that has to be ended after
/// its term, one that leaves a process behind and one that leaves a tool running on purpose.
/// What it saw goes into "folder"\stand.txt, a line a check. Only a Debug build has this; the
/// term of a forced end is AUDION_STOP_WAIT (seconds), so that a check does not wait a minute.
/// Source\Tools\stand.py starts it and looks at what is left once the window is gone.
/// </summary>
public partial class MainWindow
{
    public async Task<bool> WalkStand(string folder)
    {
        var said = new List<string>();
        bool all = true;
        void Check(string name, bool good, string found = "")
        {
            // A check is one line of the report, whatever it found.
            said.Add((good ? "ok   " : "FAIL ") + name + (good || found.Length == 0 ? "" : ": " + found.Trim().Replace("\r\n", " | ").Replace("\n", " | ")));
            all &= good;
        }
        try
        {
            await StartUp();
            Check("the stand door described the program", _told is not null, CardsNote.Text ?? "");
            if (_told is null) return false;
            _target = Path.Combine(folder, "downloads");

            Node Place(string id) => _told.Operations().First(node => node.Id == id);
            string Since(int mark) => _logAll.ToString(mark, _logAll.Length - mark);
            async Task<bool> Until(Func<bool> met, double seconds)
            {
                var clock = Stopwatch.StartNew();
                while (!met())
                {
                    if (clock.Elapsed.TotalSeconds > seconds) return false;
                    await Task.Delay(50);
                }
                return true;
            }
            int Mark(string id)
            {
                int mark = _logAll.Length;
                var node = Place(id);
                var held = _store.Of(node.Page);
                Begin(node, _target, held.ForDoor(node), held.ChangedOf(node));
                return mark;
            }
            int Left(string name) =>
                File.Exists(Path.Combine(folder, $"left-{name}.pid")) && int.TryParse(File.ReadAllText(Path.Combine(folder, $"left-{name}.pid")).Trim(), out var pid) ? pid : 0;
            static bool Alive(int pid)
            {
                if (pid <= 0) return false;
                try { using var process = Process.GetProcessById(pid); return !process.HasExited; }
                catch { return false; }
            }

            // ---- a run that ends by itself
            int at = Mark("stand_quick");
            bool ended = await Until(() => !_runner.Running, 30);
            var text = Since(at);
            Check("run: the operation ended by itself", ended);
            Check("run: the line a person would type is in the terminal", text.Contains("[GUI] " + Paths.DoorName + " run --operation stand_quick"), text);
            Check("run: the lines of the operation are in the terminal", text.Contains("quick: line 1") && text.Contains("quick: line 3"));
            Check("run: a line in its writer's colour is read as its text", text.Contains("[OK] quick: a line in its writer's colour") && !text.Contains('\u001b'));
            Check("run: the service lines of the door stay out of the terminal", !text.Contains(Door.Control));
            Check("run: a plain line of the error stream is marked [ERR]", text.Contains("[ERR] quick: a plain word on the error stream"), text);
            Check("run: a line that names itself [ERR] is not marked twice", text.Contains("[ERR] quick: an error line of the operation itself") && !text.Contains("[ERR] [ERR]"), text);
            Check("run: the verdict is OK", text.Contains("===== OK: "), text);
            Check("run: the command was put into the job of the window", !_runner.Loose);

            // ---- a value asked for before the run: it reaches the operation by its standard input and is kept nowhere
            _standing = true;
            const string mark = "STAND-VALUE-7f3a9c";
            async Task<string> Asked(string? answer)
            {
                int from = _logAll.Length;
                Views.PromptDialog.DevAnswer = _ => answer;
                Press(Place("stand_secret"));
                // A press that was answered CANCEL starts nothing: half a second is given to see that.
                if (!await Until(() => _runner.Running || Since(from).Contains("===== OK"), 1.5)) return Since(from);
                await Until(() => !_runner.Running, 30);
                return Since(from);
            }
            text = await Asked(mark);
            Check("value: the operation got it by its standard input", text.Contains($"secret: got {mark.Length} characters"), text);
            Check("value: the file of the values of the run does not hold it", text.Contains("the file of the values holds it: False"), text);
            Check("value: the terminal names the value and does not show it", text.Contains("--secret-stdin stand_token") && !text.Contains(mark), text);
            var keeping = Directory.Exists(Paths.Runtime)
                ? Directory.EnumerateFiles(Paths.Runtime, "*", SearchOption.AllDirectories).Where(file => { try { return File.ReadAllText(file).Contains(mark); } catch { return false; } }).ToList()
                : new List<string>();
            Check("value: no file the window keeps holds it", keeping.Count == 0, string.Join(", ", keeping));
            text = await Asked("");
            Check("value: an empty value is a value - the operation runs and gets it", text.Contains("secret: got 0 characters") && text.Contains("===== OK: "), text);
            text = await Asked(null);
            Check("value: CANCEL runs nothing", !text.Contains("=====") && !_runner.Running, text);
            Views.PromptDialog.DevAnswer = null;

            // ---- STOP by the signal
            at = Mark("stand_obedient");
            Check("STOP by the signal: the operation is at work", await Until(() => Since(at).Contains("obedient: waiting"), 20));
            var clock = Stopwatch.StartNew();
            StopRun();
            Check("STOP by the signal: the stop file is written", File.Exists(Door.StopFile));
            ended = await Until(() => !_runner.Running, StopWaitSeconds + 20);
            text = Since(at);
            Check("STOP by the signal: the operation saw the file and left by itself", ended && text.Contains("obedient: saw the stop file"), text);
            Check("STOP by the signal: before the term of a forced end", clock.Elapsed.TotalSeconds < StopWaitSeconds, $"{clock.Elapsed.TotalSeconds:0.0} s of {StopWaitSeconds}");
            Check("STOP by the signal: the verdict is STOPPED", text.Contains("===== STOPPED: "), text);

            // ---- a command that leaves a process behind which holds its output open
            at = Mark("stand_orphan");
            clock.Restart();
            ended = await Until(() => !_runner.Running, 30);
            text = Since(at);
            int orphan = Left("orphan");
            Check("left process: the verdict came although the output is still held open", ended && text.Contains("===== OK: "), $"{clock.Elapsed.TotalSeconds:0.0} s; " + text);
            Check("left process: the window says its lines are no longer read", text.Contains("left a process behind"), text);
            Check("left process: it is alive after the verdict", Alive(orphan), "pid " + orphan);

            // ---- a tool left running on purpose: it asked to leave the job of the window
            at = Mark("stand_leaver");
            ended = await Until(() => !_runner.Running, 30);
            text = Since(at);
            int leaver = Left("leaver");
            Check("tool on its own: the operation ended, the verdict is OK", ended && text.Contains("===== OK: "), text);
            Check("tool on its own: Windows let it leave the job", text.Contains("leaver: started a tool on its own") && !text.Contains("[WARN]"), text);
            Check("tool on its own: it is alive after the verdict", Alive(leaver), "pid " + leaver);

            // ---- STOP of an operation that does not answer: ended after the term, with what the job holds
            at = Mark("stand_deaf");
            Check("forced STOP: the operation is at work", await Until(() => Since(at).Contains("deaf: working"), 20));
            int deaf = Left("deaf");
            clock.Restart();
            StopRun();
            ended = await Until(() => !_runner.Running, StopWaitSeconds + 20);
            double took = clock.Elapsed.TotalSeconds;
            text = Since(at);
            Check("forced STOP: ended after the term and not before", ended && took >= StopWaitSeconds - 0.5 && took < StopWaitSeconds + 10, $"{took:0.0} s, the term is {StopWaitSeconds}");
            Check("forced STOP: the verdict is STOPPED", text.Contains("===== STOPPED: "), text);
            await Until(() => !Alive(deaf) && !Alive(orphan), 5);
            Check("forced STOP: the process of the operation is gone", deaf > 0 && !Alive(deaf), "pid " + deaf);
            Check("forced STOP: the process an earlier run left in the job is gone", orphan > 0 && !Alive(orphan), "pid " + orphan);
            Check("forced STOP: the tool on its own is still alive", Alive(leaver), "pid " + leaver);
            return all;
        }
        catch (Exception error)
        {
            Check("the stand walked to its end", false, error.ToString());
            return false;
        }
        finally
        {
            // Whatever a check left in the job goes; the tool on its own is looked at by whoever started the stand.
            try { _runner.Stop(); } catch { }
            try { ChildJob.EndAll(); } catch { }
            try { File.WriteAllLines(Path.Combine(folder, "stand.txt"), said, new UTF8Encoding(false)); } catch { }
            Paths.DropSession();
        }
    }
}
#endif
