using Avalonia;
using Avalonia.Controls;

namespace AudionOfficeOcrAi.Core;

/// <summary>What the code of the window needs of the look: a colour by its name.</summary>
public static class Ui
{
    /// <summary>
    /// A property of a control made in code takes a colour of App.axaml and follows it: when
    /// another theme is switched on, what was built in code changes with the rest.
    /// </summary>
    public static T Ink<T>(this T control, AvaloniaProperty property, string key) where T : Control
    {
        control.Bind(property, control.GetResourceObservable(key));
        return control;
    }
}
