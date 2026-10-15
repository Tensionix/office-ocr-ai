using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Threading;
using AudionOfficeOcrAi.Core;

namespace AudionOfficeOcrAi.Views;

/// <summary>
/// The amber notice of a run that ended with some projects failed: over the window, in its lower
/// right corner (24 from the right edge, 48 from the lower), seven seconds, and it does not take
/// the focus. Show-AboWarningToast of the old window, in the colours of the shell (Border.toast).
/// </summary>
public sealed class Toast : Window
{
#if DEBUG
    /// <summary>The last notice shown, for a check to look at.</summary>
    public static Toast? Last;
#endif

    Toast(string message)
    {
        WindowDecorations = WindowDecorations.None;
        CanResize = false;
        SizeToContent = SizeToContent.WidthAndHeight;
        ShowInTaskbar = false;
        ShowActivated = false;
        Topmost = true;
        Background = Brushes.Transparent;
        TransparencyLevelHint = new[] { WindowTransparencyLevel.Transparent };
        this.Ink(FontFamilyProperty, "FontUi");

        Content = new Border
        {
            Classes = { "toast" },
            Child = new TextBlock { Text = message, TextWrapping = TextWrapping.Wrap, MaxWidth = 430 },
        };
    }

    public static void Show(Window owner, string message)
    {
        var toast = new Toast(Lang.T(message));
#if DEBUG
        Last = toast;
#endif
        // The notice is as large as its text, and takes that size after it has opened: at the
        // moment it opens it still has the size Windows gives a new window, and a corner counted
        // from that size is a place in the middle of the screen (seen 10.10.2026). So it is put
        // into the corner each time its size changes.
        void Place()
        {
            // The corner is counted from the outer edge of the window, as the old one counted it.
            double scale = owner.RenderScaling;
            var outer = owner.FrameSize ?? owner.ClientSize;
            int x = owner.Position.X + (int)Math.Round((outer.Width - toast.Bounds.Width - 24) * scale);
            int y = owner.Position.Y + (int)Math.Round((outer.Height - toast.Bounds.Height - 48) * scale);
            // Kept on the screen the window is on. The old window held it at zero and above: on a
            // screen to the left of the main one, or over it, that put the notice on another screen.
            if (owner.Screens.ScreenFromWindow(owner)?.WorkingArea is { } area)
            {
                int width = (int)Math.Ceiling(toast.Bounds.Width * scale), height = (int)Math.Ceiling(toast.Bounds.Height * scale);
                x = Math.Clamp(x, area.X, Math.Max(area.X, area.Right - width));
                y = Math.Clamp(y, area.Y, Math.Max(area.Y, area.Bottom - height));
            }
            toast.Position = new PixelPoint(x, y);
        }
        toast.Opened += (_, _) => Place();
        toast.PropertyChanged += (_, e) =>
        {
            if (e.Property == BoundsProperty && toast.IsVisible) Place();
        };
        var timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(7) };
        timer.Tick += (_, _) =>
        {
            timer.Stop();
            toast.Close();
        };
        timer.Start();
        toast.Show(owner);
    }
}
