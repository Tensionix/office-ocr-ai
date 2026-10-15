#if DEBUG
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Interactivity;
using Avalonia.VisualTree;
using AudionOfficeOcrAi.Core;
using AudionOfficeOcrAi.Views;

namespace AudionOfficeOcrAi;

/// <summary>
/// A walk of the window without a mouse: AUDION_SHOT_STEPS names steps, ";" between them, and the
/// window started with -Shot "folder" takes them one after another and writes what it saw into
/// "folder"\steps.txt. A step presses the control itself, found by its automation id - the click
/// a person makes, not the method behind it. Only a Debug build has this.
///
///   page=SECTION/PAGE   the page is opened by the switch of its section and its own
///   idle                waits until the page in sight asks the door for no list and nothing runs
///   wait=MS             waits
///   click=ID            presses the control of that automation id: a button, a switch, a tick
///   menu=ID:ITEM        opens the menu of the button ID and chooses its item ITEM; "menu=ID" names the items
///   tick=FIELD:N        ticks the first N cards of a list that are not ticked yet
///   say=FIELD           the value the page in sight holds for a field
///   on=ID               whether the switch of that id is on
///   count=PREFIX        how many controls in sight have an id that begins so, and how many of them are on
///   ids=PREFIX          the ids in sight that begin so, the first sixteen
///   asked               how many lists the page in sight has asked of the door since the window opened
///   source=FOLDER       types a folder into the row SOURCE and takes it, as Enter does; "source=" - the row is cleared
///   type=ID:TEXT        types a text into the box of that automation id; "type=ID:" clears it
///   target=FOLDER       types a folder into the row DOWNLOADS and takes it, as Enter does
///   lang=ru|en          the language, by its button in the header
///   sheet=settings|about the sheet is opened by its button; the same step again closes it
///   answer=yes|no|off   how the questions of the window are answered from here on (off - they are shown)
///   promptshot=NAME     the next dialog of a value is shown, pictured as NAME.png and closed with CANCEL
///   askshot=NAME        the next question of the window is shown, pictured as NAME.png and answered CANCEL
///   shot=NAME           the window as a picture, NAME.png
/// </summary>
public partial class MainWindow
{
    async Task WalkSteps(string folder, string steps)
    {
        var said = new List<string>();
        void Say(string line) => said.Add(line);
        try
        {
            foreach (var raw in steps.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            {
                int at = raw.IndexOf('=');
                string name = at < 0 ? raw : raw[..at], value = at < 0 ? "" : raw[(at + 1)..];
                try { await Step(name, value, folder, Say); }
                catch (Exception problem) { Say($"ERROR {raw}: {problem.Message}"); }
            }
        }
        finally
        {
            AskDialog.DevAnswer = null;
            File.WriteAllLines(Path.Combine(folder, "steps.txt"), said, new UTF8Encoding(false));
        }
    }

    /// <summary>The controls of the window that carry an automation id and are in sight.</summary>
    IEnumerable<(Control Control, string Id)> Named() =>
        this.GetVisualDescendants().OfType<Control>().Where(control => control.IsEffectivelyVisible)
            .Select(control => (control, AutomationProperties.GetAutomationId(control) ?? "")).Where(pair => pair.Item2.Length > 0);

    /// <summary>A press of a control: a switch turns over and tells of it, as it does under a pointer; a button tells.</summary>
    static void PressControl(Control control)
    {
        if (control is ToggleButton toggle) toggle.IsChecked = toggle.IsChecked != true;
        // A button with a list under it opens the list at a press - the press of a pointer does it before it tells.
        if (control is Button { Flyout: { } under } and not ToggleButton) under.ShowAt(control);
        control.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
    }

    async Task Step(string name, string value, string folder, Action<string> say)
    {
        switch (name)
        {
            case "page":
            {
                var parts = value.Split('/');
                var page = _told?.Layout.Sections.FirstOrDefault(section => section.Id == parts[0])?.Pages.FirstOrDefault(one => one.Id == parts.ElementAtOrDefault(1));
                if (page?.Section is not { } section) { say($"page {value}: no such page"); break; }
                // The switches themselves: the section, then the page of its row.
                if (Named().FirstOrDefault(pair => pair.Id == "section_" + section.Id).Control is { } tab) PressControl(tab);
                await Task.Delay(150);
                if (Named().FirstOrDefault(pair => pair.Id == $"page_{section.Id}_{page.Id}").Control is { } own) PressControl(own);
                await Task.Delay(300);
                say($"page {value}: in sight {(_page is { } now ? ValueStore.KeyOf(now) : "-")}");
                break;
            }
            case "idle":
            {
                var clock = System.Diagnostics.Stopwatch.StartNew();
                await Task.Delay(300);
                while ((_runner.Running || _asking || (_view?.Form.Asking ?? false) || _rebuildPosted) && clock.Elapsed.TotalSeconds < 180) await Task.Delay(100);
                await Task.Delay(400);
                say(string.Create(CultureInfo.InvariantCulture, $"idle after {clock.Elapsed.TotalSeconds:0.0} s"));
                break;
            }
            case "wait": await Task.Delay(int.Parse(value, CultureInfo.InvariantCulture)); break;
            case "click":
            {
                var found = Named().FirstOrDefault(pair => pair.Id == value).Control;
                if (found is null) { say($"click {value}: no such control in sight"); break; }
                if (!found.IsEffectivelyEnabled) { say($"click {value}: disabled"); break; }
                PressControl(found);
                await Task.Delay(250);
                say($"click {value}" + (found is ToggleButton pressed ? $": now {(pressed.IsChecked == true ? "on" : "off")}" : ""));
                break;
            }
            case "menu":
            {
                // menu=BUTTON:ITEM - the menu of a button opens, and its item of that automation id is chosen.
                int colon = value.IndexOf(':');
                string id = colon < 0 ? value : value[..colon], wanted = colon < 0 ? "" : value[(colon + 1)..];
                if (Named().FirstOrDefault(pair => pair.Id == id).Control is not Button { Flyout: MenuFlyout menu } owner) { say($"menu {id}: no button with a menu in sight"); break; }
                menu.ShowAt(owner);
                await Task.Delay(300);
                var items = menu.Items.OfType<MenuItem>().ToList();
                say($"menu {id}: {string.Join(" | ", items.Select(item => AutomationProperties.GetAutomationId(item) + " = " + item.Header))}");
                if (items.FirstOrDefault(item => AutomationProperties.GetAutomationId(item) == wanted) is not { } chosen) { menu.Hide(); if (wanted.Length > 0) say($"menu {id}: no item {wanted}"); break; }
                chosen.RaiseEvent(new RoutedEventArgs(MenuItem.ClickEvent));
                await Task.Delay(250);
                say($"menu {id}: chose {wanted}");
                break;
            }
            case "tick":
            {
                var parts = value.Split(':');
                int wanted = int.Parse(parts.ElementAtOrDefault(1) ?? "1", CultureInfo.InvariantCulture);
                var cards = Named().Where(pair => pair.Id.StartsWith($"field_{parts[0]}_", StringComparison.Ordinal)).Select(pair => pair.Control).OfType<ToggleButton>()
                    .Where(card => card.IsChecked != true).Take(wanted).ToList();
                foreach (var card in cards) { PressControl(card); await Task.Delay(80); }
                say($"tick {value}: {cards.Count} ticked - {string.Join(", ", cards.Select(card => AutomationProperties.GetAutomationId(card)))}");
                break;
            }
            case "scroll":
            {
                // scroll=end | home | <pixels>: the page in sight is scrolled, as a wheel does it - the scroller of
                // the page host that has the most to scroll.
                var scroller = PageHost.GetVisualDescendants().OfType<ScrollViewer>().Where(one => one.IsEffectivelyVisible)
                    .OrderByDescending(one => one.Extent.Height - one.Viewport.Height).FirstOrDefault();
                if (scroller is null) { say($"scroll {value}: nothing to scroll"); break; }
                if (value == "end") scroller.ScrollToEnd();
                else if (value == "home") scroller.ScrollToHome();
                else if (double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var down)) scroller.Offset = new Avalonia.Vector(0, down);
                await Task.Delay(200);
                say($"scroll {value}: at {scroller.Offset.Y:0} of {Math.Max(0, scroller.Extent.Height - scroller.Viewport.Height):0}");
                break;
            }
            case "log":
            {
                // log=<N>: the last N lines of the terminal, as a person reads them.
                int count = int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var lastLines) && lastLines > 0 ? lastLines : 6;
                var read = _logAll.ToString().Split('\n').Select(line => line.TrimEnd('\r')).Where(line => line.Length > 0).ToList();
                foreach (var line in read.Skip(Math.Max(0, read.Count - count))) say("log | " + line);
                break;
            }
            case "say":
                say($"say {value}: <{(_page is { } shown ? _store.Of(shown).Get(value) : "").Replace('\n', ',')}>");
                break;
            case "on":
                say($"on {value}: {(Named().FirstOrDefault(pair => pair.Id == value).Control is ToggleButton asked ? (asked.IsChecked == true ? "on" : "off") : "no such switch in sight")}");
                break;
            case "count":
            {
                var counted = Named().Where(pair => pair.Id.StartsWith(value, StringComparison.Ordinal)).Select(pair => pair.Control).ToList();
                say($"count {value}: {counted.Count} in sight, {counted.OfType<ToggleButton>().Count(one => one.IsChecked == true)} on");
                break;
            }
            case "ids":
                say($"ids {value}: {string.Join(" | ", Named().Where(pair => pair.Id.StartsWith(value, StringComparison.Ordinal)).Take(16).Select(pair => pair.Id))}");
                break;
            case "asked":
                say($"asked: {_view?.Form.Asked ?? 0}");
                break;
            case "type":
            {
                int colon = value.IndexOf(':');
                string id = colon < 0 ? value : value[..colon], typed = colon < 0 ? "" : value[(colon + 1)..];
                if (Named().FirstOrDefault(pair => pair.Id == id).Control is not TextBox box) { say($"type {id}: no such box in sight"); break; }
                box.Text = typed;
                await Task.Delay(250);
                say($"type {id}: <{typed}>");
                break;
            }
            case "target":
                TargetBox.Text = value;
                TakeTyped(source: false);
                await Task.Delay(200);
                say($"target {value}: the results go to <{_target}>, the box reads <{TargetBox.Text}>");
                break;
            case "source":
                SourceBox.Text = value;
                TakeTyped(source: true);
                await Task.Delay(300);
                say($"source {value}: the files come from <{_source}>, the box reads <{SourceBox.Text}>");
                break;
            case "answer":
                AskDialog.DevAnswer = value == "off" ? null : (title, message, yesNo) =>
                {
                    say($"ASK [{title}] {(yesNo ? "yes/no" : "ok")} -> {value}");
                    foreach (var line in message.Replace("\r\n", "\n").Split('\n')) say("    | " + line);
                    return value == "yes";
                };
                break;
            case "lang":
                // The button of the language is pressed, as a person presses it.
                PressControl(value == "en" ? LangEn : LangRu);
                await Task.Delay(500);
                say($"lang {value}: the window speaks {Lang.Code}");
                break;
            case "sheet":
                PressControl(value == "about" ? SheetAbout : SheetSettings);
                await Task.Delay(500);
                say($"sheet {value}: {(SheetHost.IsVisible ? "open" : "closed")}");
                break;
            case "askshot":
                AskDialog.DevAnswer = null;
                AskDialog.DevShow = (700, false, dialog =>
                {
                    Save(dialog, Path.Combine(folder, value + ".png"));
                    say($"askshot {value}: [{dialog.Title}] answered CANCEL");
                });
                break;
            case "promptshot":
                PromptDialog.DevShow = (700, null, dialog =>
                {
                    Save(dialog, Path.Combine(folder, value + ".png"));
                    say($"promptshot {value}: [{dialog.Title}] closed with CANCEL");
                });
                break;
            case "shot":
                await Task.Delay(350);
                Save(Path.Combine(folder, value + ".png"));
                say($"shot {value}");
                break;
            default: say($"unknown step: {name}"); break;
        }
    }
}
#endif
