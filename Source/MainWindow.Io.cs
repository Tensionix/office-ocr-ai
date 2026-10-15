using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Platform.Storage;
using AudionOfficeOcrAi.Core;
using AudionOfficeOcrAi.Views;

namespace AudionOfficeOcrAi;

/// <summary>
/// The working area: where the files come from (SOURCE - a folder or one file) and where the results
/// go (TARGET). Carried over from Audion Browsers Portable (its MainWindow.Io.cs) onto this shell.
/// Every start begins with input and output of the program - the last choice is not remembered:
/// an external source is copied into input, and input and output are cleared, by every run that
/// reads it. The history of paths and its pins are the file the window on NiceGUI kept
/// (config\path_history.json). The disk is not asked on the thread of the window where a folder
/// may be slow to answer - a flash drive that has gone, a share that is down.
/// </summary>
public partial class MainWindow
{
    /// <summary>The source, as a full path: a folder or one file.</summary>
    string _source = "";
    /// <summary>The target folder, as a full path.</summary>
    string _target = "";

    PathHistory? _history;

    /// <summary>The folders are being cleared: nothing starts and no path changes until that has ended.</summary>
    bool _clearing, _closeAfterClearing;

    /// <summary>When a typed path was last refused, and which one: a run pressed at that very moment is not started.</summary>
    DateTime _pathRefusedAt;
    string _pathRefused = "";

    string DefaultSource => _told?.Paths.Input is { Length: > 0 } input ? input : Path.Combine(Paths.Root, "input");
    string DefaultTarget => _told?.Paths.Output is { Length: > 0 } output ? output : Path.Combine(Paths.Root, "output");

    /// <summary>The folders of the program that are there to be cleared.</summary>
    string[] WorkingFolders => new[] { DefaultSource, DefaultTarget };

    /// <summary>A run, a question or a clearing is going on: no path changes.</summary>
    bool Busy => _runner.Running || _asking || _clearing;

    static Task<bool> FolderExists(string path) => Task.Run(() => { try { return Directory.Exists(path); } catch { return false; } });
    static Task<bool> PathExists(string path) => Task.Run(() => { try { return Directory.Exists(path) || File.Exists(path); } catch { return false; } });

    /// <summary>
    /// What the working area says: in the status line, and - when something was refused - in the
    /// terminal too, where it stays to be read.
    /// </summary>
    void Say(string text, bool refused = false)
    {
        SetStatus(text);
        if (refused) AppendLines(new[] { "[GUI] " + Lang.T(text) });
    }

    void WireIo()
    {
        PickFolderButton.Click += (_, _) => PickFolder(source: true);
        PickFileButton.Click += (_, _) => PickFile();
        PickTargetButton.Click += (_, _) => PickFolder(source: false);
        ResetPathsButton.Click += (_, _) => ResetPaths(quiet: false);
        ListFilesButton.Click += (_, _) => ListSource();
        SourceOpenButton.Click += (_, _) => Reveal(_source);
        TargetOpenButton.Click += (_, _) => Reveal(_target);
        SourcePinButton.Click += (_, _) => TogglePin(source: true);
        TargetPinButton.Click += (_, _) => TogglePin(source: false);
        WireHistory(SourceHistoryButton, source: true);
        WireHistory(TargetHistoryButton, source: false);

        // The one clearing of the working area: what to clear is asked first, then the question names the
        // paths. The operations of the working folders that remove (`folders` of the layout, tone "burn")
        // stand in the same menu, under a rule - one sign for every clearing, not one beside another.
        // The items are made once the program is described (BuildClearMenu) and again when the language
        // changes - not at every opening: a menu made anew as it opens is not seen by UI Automation.
        var clear = new MenuFlyout { Placement = PlacementMode.BottomEdgeAlignedLeft };
        // A path typed and refused at the very press that opened this menu must not be what the menu then clears.
        clear.Opened += (_, _) =>
        {
            if (!PathJustRefused()) return;
            clear.Hide();
            Say(Lang.F("очистка отменена - введённый путь не принят: {0}", _pathRefused), refused: true);
        };
        ClearFoldersButton.Flyout = _clearMenu = clear;

        // A path typed by hand is taken when the box is left or Enter is pressed.
        SourceBox.LostFocus += (_, _) => TakeTyped(source: true);
        TargetBox.LostFocus += (_, _) => TakeTyped(source: false);
        SourceBox.KeyDown += (_, e) => { if (e.Key == Key.Enter) { TakeTyped(source: true); e.Handled = true; } };
        TargetBox.KeyDown += (_, e) => { if (e.Key == Key.Enter) { TakeTyped(source: false); e.Handled = true; } };

        // A folder or a file dropped on the window becomes the source.
        DragDrop.SetAllowDrop(this, true);
        AddHandler(DragDrop.DragOverEvent, (_, e) =>
        {
            e.DragEffects = !Busy && e.DataTransfer.Contains(DataFormat.File) ? DragDropEffects.Link : DragDropEffects.None;
            e.Handled = true;
        });
        AddHandler(DragDrop.DropEvent, (_, e) =>
        {
            if (Busy) return;
            var path = (e.DataTransfer.TryGetFiles() ?? Array.Empty<IStorageItem>()).Select(item => item.TryGetLocalPath()).FirstOrDefault(item => item is not null);
            if (path is null) return;
            e.Handled = true;
            Dropped(path);
        });
    }

    /// <summary>What was dropped on the window: a folder or a file - the source.</summary>
    async void Dropped(string path)
    {
        bool there = await PathExists(path);
        if (Busy) return;
        if (!there) { Say(Lang.F("источника нет на диске: {0}", path), refused: true); return; }
        Choose(source: true, path);
    }

    MenuFlyout? _clearMenu;

    /// <summary>The items of the clearing: the three folders, then the operations of the working folders that remove.</summary>
    void BuildClearMenu()
    {
        if (_clearMenu is not { } clear) return;
        clear.Items.Clear();
        clear.Items.Add(ClearItem("clear_source", "ИСТОЧНИК: удалить содержимое", source: true, target: false));
        clear.Items.Add(ClearItem("clear_target", "НАЗНАЧЕНИЕ: удалить содержимое", source: false, target: true));
        clear.Items.Add(ClearItem("clear_both", "ИСТОЧНИК и НАЗНАЧЕНИЕ: удалить содержимое обоих", source: true, target: true));
        var removing = _told?.Layout.Folders.Where(node => node.Tone == "burn").ToList() ?? new List<Node>();
        if (removing.Count > 0) clear.Items.Add(new Separator());
        foreach (var node in removing)
        {
            var item = new MenuItem { Header = node.Name };
            Avalonia.Automation.AutomationProperties.SetAutomationId(item, "run_" + node.Id);
            ToolTip.SetTip(item, TipOf(node) + "\n" + FolderLines());
            item.Click += (_, _) =>
            {
                clear.Hide();
                Press(node);
            };
            clear.Items.Add(item);
        }
    }

    MenuItem ClearItem(string id, string text, bool source, bool target)
    {
        var item = new MenuItem { Header = Lang.T(text) };
        Avalonia.Automation.AutomationProperties.SetAutomationId(item, id);
        item.Click += (_, _) =>
        {
            _clearMenu?.Hide();
            ClearFolders(source, target);
        };
        return item;
    }

    bool PathJustRefused()
    {
        if (DateTime.UtcNow - _pathRefusedAt >= TimeSpan.FromSeconds(2)) return false;
        _pathRefusedAt = default;
        return true;
    }

    /// <summary>The folders every project has and the history of paths: made at the start, as the window on NiceGUI made them.</summary>
    void EnsureFolders()
    {
        if (_told is null) return;
        foreach (var folder in new[] { _told.Paths.Input, _told.Paths.Output, _told.Paths.Logs, _told.Paths.Report })
        {
            if (string.IsNullOrEmpty(folder)) continue;
            try { Directory.CreateDirectory(folder); }
            catch (Exception ex) { AppendLines(new[] { Lang.F("[GUI] папка не создана: {0} - {1}", folder, ex.Message) }); }
        }
        var file = Path.Combine(Paths.ProjectConfig, "path_history.json");
#if DEBUG
        // A check keeps a history of its own: the paths it tries are not the owner's.
        if (Environment.GetEnvironmentVariable("AUDION_DEV_HISTORY") is { Length: > 0 } own) file = own;
#endif
        _history = new PathHistory(file);
        _history.EnsureInitial(DefaultSource, DefaultTarget);
    }

    // ------------------------------------------------------------ the two paths

    void SetSource(string path)
    {
        var full = Paths.Full(path);
        bool changed = !string.Equals(full, _source, StringComparison.OrdinalIgnoreCase);
        _source = full;
        ShowPath(SourceBox, _source);
        ShowPins();
        // A list that shows what lies in the source - the Markdown files found - is another list now.
        if (changed) OutdateAll(lists: false);
    }

    void SetTarget(string path)
    {
        _target = Paths.Full(path);
        ShowPath(TargetBox, _target);
        ShowPins();
        ShowDrives();
    }

    /// <summary>A path in its box, scrolled to its end: of a long path the last folder says more than the drive.</summary>
    static void ShowPath(TextBox box, string full)
    {
        box.Text = Paths.Short(full);
        box.CaretIndex = box.Text?.Length ?? 0;
    }

    /// <summary>A path a person chose - picked, typed, dropped or taken from the history: it is set and remembered.</summary>
    void Choose(bool source, string path)
    {
        if (source) SetSource(path); else SetTarget(path);
        _history?.Remember(source, source ? _source : _target);
        ShowPins();
        Say(Lang.F(source ? "источник: {0}" : "назначение: {0}", Paths.Short(source ? _source : _target)));
    }

    /// <summary>Both paths back to input and output of the program; the history is emptied, the pins stay.</summary>
    void ResetPaths(bool quiet)
    {
        if (Busy) { Say("идёт операция: пути не меняются", refused: true); return; }
        SetSource(DefaultSource);
        SetTarget(DefaultTarget);
        if (quiet) return;
        int pins = _history?.ClearKeepPins() ?? 0;
        ShowPins();
        Say(Lang.F("источник и назначение - input и output программы · закреплений осталось {0}", pins));
    }

    /// <summary>
    /// What was typed into a path box. A source that is neither a folder nor a file on the disk is
    /// not taken: the box goes back, and the refusal is remembered for a moment - the press that
    /// took the focus off the box may have been a press of a run button, and that run must not go
    /// to the path that stood there before.
    /// </summary>
    void TakeTyped(bool source)
    {
        var box = source ? SourceBox : TargetBox;
        var typed = Paths.Full(box.Text ?? "");
        var held = source ? _source : _target;
        if (typed.Length == 0 || string.Equals(typed, held, StringComparison.OrdinalIgnoreCase)) { ShowPath(box, held); return; }
        void Refuse(string why)
        {
            ShowPath(box, held);
            _pathRefused = typed;
            _pathRefusedAt = DateTime.UtcNow;
            Say(why, refused: true);
        }
        if (Busy) { Refuse(Lang.T("идёт операция: пути не меняются")); return; }
        if (source && !Directory.Exists(typed) && !File.Exists(typed)) { Refuse(Lang.F("источника нет на диске: {0}", typed)); return; }
        if (!source && File.Exists(typed)) { Refuse(Lang.F("назначение - папка, а это файл: {0}", typed)); return; }
        Choose(source, typed);
    }

    async Task<IStorageFolder?> StartFolder(string held)
    {
        try
        {
            var start = await FolderExists(held) ? held : Path.GetDirectoryName(held);
            if (!string.IsNullOrEmpty(start) && await FolderExists(start)) return await StorageProvider.TryGetFolderFromPathAsync(start);
        }
        catch { }
        return null;
    }

    async void PickFolder(bool source)
    {
        if (Busy) { Say("идёт операция: пути не меняются", refused: true); return; }
        var from = await StartFolder(source ? _source : _target);
        var picked = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
        {
            Title = Lang.T(source ? "Папка-источник" : "Папка назначения"), AllowMultiple = false, SuggestedStartLocation = from,
        });
        // A run that started while the picker stood open keeps the folders it began with.
        if (Busy) return;
        if (picked.Count == 0 || picked[0].TryGetLocalPath() is not { } path) { Say("выбор отменён"); return; }
        Choose(source, path);
    }

    /// <summary>One file as the source - a scan, a PDF, an office document: the run copies it alone into input.</summary>
    async void PickFile()
    {
        if (Busy) { Say("идёт операция: пути не меняются", refused: true); return; }
        var from = await StartFolder(_source);
        var picked = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = Lang.T("Файл-источник"), AllowMultiple = false, SuggestedStartLocation = from,
        });
        if (Busy) return;
        if (picked.Count == 0 || picked[0].TryGetLocalPath() is not { } path) { Say("выбор отменён"); return; }
        Choose(source: true, path);
    }

    /// <summary>A path in Explorer: a folder opened, a file shown in its folder. Nothing is made when it is not there.</summary>
    async void Reveal(string path)
    {
        bool folder = await FolderExists(path);
        bool file = !folder && await Task.Run(() => { try { return File.Exists(path); } catch { return false; } });
        if (!folder && !file) { Say(Lang.F("на диске нет: {0}", path), refused: true); return; }
        try
        {
            var explorer = new System.Diagnostics.ProcessStartInfo("explorer.exe") { UseShellExecute = false };
            if (file) explorer.ArgumentList.Add("/select," + path); else explorer.ArgumentList.Add(path);
            System.Diagnostics.Process.Start(explorer);
        }
        catch (Exception ex) { Say(Lang.F("Папка не открылась: {0}", ex.Message), refused: true); }
    }

    // ------------------------------------------------------------ the history and the pins

    void WireHistory(Button button, bool source)
    {
        var flyout = new Flyout { Placement = PlacementMode.BottomEdgeAlignedRight };
        // Built when it opens: the file may have been changed by another window of the program.
        flyout.Opening += (_, _) => flyout.Content = HistoryList(source, flyout);
        button.Flyout = flyout;
    }

    Control HistoryList(bool source, Flyout flyout)
    {
        var rows = new StackPanel { MinWidth = 420, MaxWidth = 760 };
        var entries = _history?.Entries(source) ?? new List<HistoryEntry>();
        var held = source ? _source : _target;
        var shown = new List<(Button Row, string Path)>();
        foreach (var entry in entries)
        {
            var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 7 };
            var pin = Icons.Sign("pin");
            pin.Opacity = entry.Pinned ? 1 : 0;
            if (entry.Pinned) pin.Stroke = Tones.Of("gold").Ink;
            face.Children.Add(pin);
            face.Children.Add(new TextBlock { Text = Paths.Short(entry.Path), TextTrimming = Avalonia.Media.TextTrimming.CharacterEllipsis });
            var row = new Button { Classes = { "dropdownrow" }, Content = face, HorizontalAlignment = HorizontalAlignment.Stretch };
            row.Classes.Set("on", string.Equals(entry.Path, held, StringComparison.OrdinalIgnoreCase));
            ToolTip.SetTip(row, entry.Path);
            var path = entry.Path;
            row.Click += async (_, _) =>
            {
                flyout.Hide();
                if (Busy) { Say("идёт операция: пути не меняются", refused: true); return; }
                if (source && !await PathExists(path)) { Say(Lang.F("источника нет на диске: {0}", path), refused: true); return; }
                if (Busy) return;
                Choose(source, path);
            };
            rows.Children.Add(row);
            shown.Add((row, path));
        }
        if (entries.Count == 0) rows.Children.Add(new TextBlock { Classes = { "note" }, Text = Lang.T("история пуста"), Margin = new Thickness(8, 4) });
        // Which of them are still on the disk is found out off the thread of the window and painted when the answer comes.
        _ = MarkGone(shown);
        return new ScrollViewer { MaxHeight = 420, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, Content = rows };
    }

    static async Task MarkGone(List<(Button Row, string Path)> shown)
    {
        var gone = await Task.Run(() => shown.Select(item => { try { return !Directory.Exists(item.Path) && !File.Exists(item.Path); } catch { return true; } }).ToList());
        for (int i = 0; i < shown.Count; i++)
        {
            if (!gone[i]) continue;
            shown[i].Row.Opacity = 0.45;
            ToolTip.SetTip(shown[i].Row, Lang.F("нет на диске: {0}", shown[i].Path));
        }
    }

    void TogglePin(bool source)
    {
        if (_history is null) return;
        var path = source ? _source : _target;
        bool pinned = !_history.IsPinned(source, path);
        _history.SetPinned(source, path, pinned);
        ShowPins();
        Say(Lang.T(pinned ? "путь закреплён" : "закрепление снято"));
    }

    /// <summary>The pin of a line is lit while its path is pinned.</summary>
    void ShowPins()
    {
        if (_history is null) return;
        SourcePinButton.Classes.Set("on", _history.IsPinned(true, _source));
        TargetPinButton.Classes.Set("on", _history.IsPinned(false, _target));
    }

    // ------------------------------------------------------------ what lies in the source

    /// <summary>What lies in the source, into the terminal: its folders and files of the first level, by the alphabet.</summary>
    async void ListSource()
    {
        var source = _source;
        ListFilesButton.IsEnabled = false;
        try
        {
            var found = await Task.Run(() =>
            {
                if (File.Exists(source)) return ((List<string> Folders, List<string> Files)?)(new List<string>(), new List<string> { Path.GetFileName(source) });
                var info = new DirectoryInfo(source);
                if (!info.Exists) return null;
                return (info.EnumerateDirectories().Select(item => item.Name).OrderBy(name => name, StringComparer.CurrentCultureIgnoreCase).ToList(),
                        info.EnumerateFiles().Select(item => item.Name).OrderBy(name => name, StringComparer.CurrentCultureIgnoreCase).ToList());
            });
            if (found is not { } lists) { Say(Lang.F("источника нет на диске: {0}", source), refused: true); return; }
            var (folders, files) = lists;
            var lines = new List<string> { "", Lang.F("[GUI] в источнике {0}: папок {1}, файлов {2}", Paths.Short(source), folders.Count, files.Count) };
            lines.AddRange(folders.Select((name, index) => $"{index + 1,4}  [{name}]"));
            lines.AddRange(files.Select((name, index) => $"{folders.Count + index + 1,4}  {name}"));
            AppendLines(lines);
            Say(Lang.F("в источнике: папок {0}, файлов {1}", folders.Count, files.Count));
        }
        catch (Exception ex) { Say(Lang.F("источник не прочитан: {0}", ex.Message), refused: true); }
        finally { ListFilesButton.IsEnabled = true; }
    }

    // ------------------------------------------------------------ clearing

    /// <summary>
    /// Clearing. Everything is taken before the questions. A folder outside the program is asked
    /// about on its own - another copy of what it holds may not exist. The guards refuse the root
    /// of a drive, the program and its own folders, a link. While the clearing goes nothing else
    /// starts, no path changes and the window does not close. What is deleted goes to the Recycle
    /// Bin where the drive has one - the question says which it is.
    /// </summary>
    async void ClearFolders(bool source, bool target)
    {
        if (_runner.Running) { Say("идёт другая операция", refused: true); return; }
        if (_clearing) { Say("очистка уже идёт", refused: true); return; }
        var from = _source;
        var to = _target;
        bool same = string.Equals(from, to, StringComparison.OrdinalIgnoreCase);
        var paths = new List<(bool Source, string Path)>();
        if (source) paths.Add((true, from));
        if (target && !(source && same)) paths.Add((false, to));
        var working = WorkingFolders;
        foreach (var (_, path) in paths)
        {
            if (File.Exists(path)) { Say(Lang.F("источник - один файл, а очищается папка: {0}", path), refused: true); return; }
            if (FolderCleaner.Refusal(path, working) is { Length: > 0 } refusal) { Say(refusal, refused: true); return; }
        }

        string Fate(string path) => Lang.T(FolderCleaner.HasBin(path)
            ? "Удалённое уйдёт в Корзину; о том, чего Корзина не вместит, Windows спросит отдельно."
            : "У этого диска нет Корзины: удалённое не вернуть.");

        var outside = paths.Where(item => !working.Any(folder => IsWithin(item.Path, folder))).ToList();
        if (outside.Count > 0)
        {
            var warning = new List<string> { Lang.T("Будут удалены все файлы и вложенные папки - исходные сканы и документы вместе с готовыми результатами.") };
            foreach (var (_, path) in outside) { warning.Add(""); warning.Add(path); warning.Add(Fate(path)); }
            _asking = true;
            ApplyBusy();
            bool sure;
            try { sure = await AskDialog.YesNo(this, Lang.T("Очистить папку вне программы?"), string.Join("\n", warning), "burn"); }
            finally { _asking = false; ApplyBusy(); }
            if (!sure) return;
        }
        var lines = new List<string>();
        foreach (var (isSource, path) in paths) lines.Add(Lang.F(isSource ? "ИСТОЧНИК: {0}" : "НАЗНАЧЕНИЕ: {0}", path));
        lines.Add("");
        lines.Add(Lang.T("Сами папки остаются."));
        foreach (var fate in paths.Select(item => Fate(item.Path)).Distinct()) lines.Add(fate);
        _asking = true;
        ApplyBusy();
        bool go;
        try { go = await AskDialog.YesNo(this, Lang.T("Удалить содержимое?"), string.Join("\n", lines), "burn"); }
        finally { _asking = false; ApplyBusy(); }
        if (!go) return;
        if (_runner.Running || !IsVisible) { Say("идёт другая операция", refused: true); return; }
        if (!string.Equals(from, _source, StringComparison.OrdinalIgnoreCase) || !string.Equals(to, _target, StringComparison.OrdinalIgnoreCase))
        {
            Say("пути изменились, пока стоял вопрос: ничего не удалено", refused: true);
            return;
        }

        _clearing = true;
        ApplyBusy();
        Say("очищаю…");
        var window = TryGetPlatformHandle()?.Handle ?? IntPtr.Zero;
        int cleared = 0, absent = 0;
        try
        {
            foreach (var (isSource, path) in paths)
            {
                var done = await Task.Run(() => FolderCleaner.Clear(path, working, window));
                if (done.Kind == "missing")
                {
                    absent++;
                    AppendLines(new[] { Lang.F(isSource ? "[GUI] ИСТОЧНИКА нет на диске, очищать нечего: {0}" : "[GUI] НАЗНАЧЕНИЯ нет на диске, очищать нечего: {0}", done.Path) });
                    continue;
                }
                cleared++;
                AppendLines(new[] { Lang.F(isSource ? "[GUI] очищен ИСТОЧНИК: {0} · удалено {1}" : "[GUI] очищено НАЗНАЧЕНИЕ: {0} · удалено {1}", done.Path, done.Removed) });
            }
            if (absent == 0) Say("очищено");
            else if (cleared == 0) Say("папки нет на диске: очищать нечего", refused: true);
            else Say("очищено не всё: одной из папок нет на диске - что именно, сказано в терминале", refused: true);
        }
        catch (OperationCanceledException) { Say("очистка остановлена в вопросе Windows: удалено не всё", refused: true); }
        catch (InvalidOperationException ex) { Say(ex.Message, refused: true); }
        catch (Exception ex) { Say(Lang.F("очистка не вышла: {0} - часть содержимого могла уже уйти", ex.Message), refused: true); }
        finally
        {
            _clearing = false;
            ApplyBusy();
            OutdateAll(lists: false);
            if (_closeAfterClearing) Close();
        }
    }

    static bool IsWithin(string path, string folder)
    {
        try
        {
            var full = Path.GetFullPath(path).TrimEnd('\\', '/');
            var home = Path.GetFullPath(folder).TrimEnd('\\', '/');
            return string.Equals(full, home, StringComparison.OrdinalIgnoreCase) || full.StartsWith(home + "\\", StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    // ------------------------------------------------------------ before a run

    /// <summary>
    /// What a run will do to the folders of the program, said before it starts (the inventory of the
    /// window on NiceGUI, findings 5-7: it did all of it silently). An external source is copied into
    /// input, and input and output are cleared first - what the last run left in output is gone, a
    /// paid OCR included. A source inside output would be cleared together with it; a folder inside
    /// input is refused by the engine. Null - the run may start; "" - the person said no; a text -
    /// the reason it may not.
    /// </summary>
    async Task<string?> MirrorAllowed(string source)
    {
        var input = DefaultSource;
        var output = DefaultTarget;
        if (string.Equals(Paths.Full(source), Paths.Full(input), StringComparison.OrdinalIgnoreCase)) return null;
        if (IsWithin(source, output)) return Lang.F("источник лежит внутри output программы, а output перед запуском очищается - источник пропал бы вместе с ним: {0}", source);
        if (IsWithin(source, input)) return Lang.F("папка внутри input не может быть отдельным источником: выберите сам input или папку вне программы: {0}", source);
        static int Count(string folder)
        {
            try { return Directory.Exists(folder) ? Directory.EnumerateFileSystemEntries(folder).Count(entry => !entry.EndsWith(".gitkeep", StringComparison.OrdinalIgnoreCase)) : 0; }
            catch { return 0; }
        }
        var (held, left) = await Task.Run(() => (Count(input), Count(output)));
        if (held == 0 && left == 0) return null;
        // The engine clears both folders for good, past the Recycle Bin: the question says it before.
        var lines = new List<string>
        {
            Lang.T("Источник вне программы: перед запуском он копируется в input, а input и output программы очищаются - безвозвратно, мимо Корзины."),
            "",
            Lang.F("ИСТОЧНИК: {0}", source),
        };
        if (held > 0) lines.Add(Lang.F("input: {0} - элементов: {1}", input, held));
        if (left > 0) lines.Add(Lang.F("output: {0} - элементов: {1}; прошлые результаты пропадут, если их не перенести", output, left));
        bool go = await AskDialog.YesNo(this, Lang.T("Очистить input и output перед запуском?"), string.Join("\n", lines), "burn");
        return go ? null : "";
    }
}
