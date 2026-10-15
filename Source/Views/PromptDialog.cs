using System;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using AudionOfficeOcrAi.Core;

namespace AudionOfficeOcrAi.Views;

/// <summary>
/// The question an operation asks before it runs: one value - the GitHub token - typed into a
/// dialog in the look of the window. Its title, the line of explanation, the name of the value
/// and the word of its button are the manifest's (`prompt` of the operation), in the language of
/// the window; a secret is typed unseen. CANCEL and an empty value are two answers: an empty
/// token means "remove the stored one", so the dialog hands back null for CANCEL and the cross,
/// and "" for an empty box sent with its button.
/// The value goes from here to the door by its standard input and is kept nowhere.
/// </summary>
public sealed class PromptDialog : Window
{
#if DEBUG
    /// <summary>A check of the window answers itself: the title comes, the value goes back - null for CANCEL.</summary>
    public static Func<string, string?>? DevAnswer;
    /// <summary>A check that wants the dialog on the screen: it is shown, and closed with that answer after so many milliseconds.</summary>
    public static (int Milliseconds, string? Answer, Action<PromptDialog>? Shown)? DevShow;
#endif

    PromptDialog(Window owner, Asked asked)
    {
        Title = asked.Title;
        Width = 580;
        SizeToContent = SizeToContent.Height;
        CanResize = false;
        CanMinimize = false;
        CanMaximize = false;
        ShowInTaskbar = false;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        // A walk by UI Automation: the question stands where its window does, off the screen, and takes
        // no focus. Placed once it is open: a place set before is not kept (MainWindow.OffScreen).
        if (Program.Walk)
        {
            ShowActivated = false;
            Opened += (_, _) => Position = new PixelPoint(owner.Position.X + 40, owner.Position.Y + 40);
        }
        Icon = owner.Icon;
        this.Ink(BackgroundProperty, "AppBg").Ink(ForegroundProperty, "TextMain").Ink(FontFamilyProperty, "FontUi");
        FontSize = 13;
        Classes.Set("vault", owner.Classes.Contains("vault"));

        var head = new TextBlock { Text = asked.Title, FontSize = 15, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 12) };
        var body = new StackPanel { Children = { head } };
        if (asked.Hint.Length > 0) body.Children.Add(new TextBlock { Classes = { "plain" }, Text = asked.Hint, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 12) });
        if (asked.Label.Length > 0) body.Children.Add(new TextBlock { Text = asked.Label, Margin = new Thickness(1, 0, 0, 5) }.Ink(TextBlock.ForegroundProperty, "TextMuted"));
        var box = new TextBox
        {
            Name = "PromptBox", Classes = { "masks" }, MinHeight = 26, Padding = new Thickness(8, 2), VerticalContentAlignment = VerticalAlignment.Center,
            // A secret is typed unseen, and the box offers neither to show it nor to copy it.
            PasswordChar = asked.Secret ? '•' : default,
        };
        body.Children.Add(box);

        var row = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 18, 0, 0) };
        var cancel = new Button { Name = "PromptCancel", Content = Lang.T("ОТМЕНА"), MinWidth = 118, MinHeight = 30, Margin = new Thickness(0, 0, 9, 0), IsCancel = true };
        cancel.Click += (_, _) => Close(null);
        var ok = new Button { Name = "PromptOk", Content = (asked.Ok.Length > 0 ? asked.Ok : Lang.T("ГОТОВО")).ToUpper(System.Globalization.CultureInfo.CurrentCulture), MinWidth = 118, MinHeight = 30 };
        ok.Click += (_, _) => Close(box.Text ?? "");
        row.Children.Add(cancel);
        row.Children.Add(ok);
        body.Children.Add(row);
        // Enter sends a value that was typed. An empty box is sent by its button alone: an empty
        // token removes the stored one, and that must not be what a stray Enter does.
        box.KeyDown += (_, e) =>
        {
            if (e.Key != Key.Enter || string.IsNullOrEmpty(box.Text)) return;
            e.Handled = true;
            Close(box.Text);
        };
        Opened += (_, _) => box.Focus();

        Content = new Border
        {
            BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8), Margin = new Thickness(10), Padding = new Thickness(18, 15),
            Child = body,
        }.Ink(Border.BackgroundProperty, "PanelBg").Ink(Border.BorderBrushProperty, "BorderSoft");
    }

    /// <summary>The value typed; "" for an empty box sent with its button; null for CANCEL and the cross.</summary>
    public static async Task<string?> Ask(Window owner, Asked asked)
    {
#if DEBUG
        if (DevShow is { } show)
        {
            DevShow = null;
            var shown = new PromptDialog(owner, asked);
            shown.Opened += async (_, _) =>
            {
                await Task.Delay(show.Milliseconds);
                show.Shown?.Invoke(shown);
                shown.Close(show.Answer);
            };
            return await shown.ShowDialog<string?>(owner);
        }
        if (DevAnswer is { } answer) return answer(asked.Title);
#endif
        return await new PromptDialog(owner, asked).ShowDialog<string?>(owner);
    }
}
