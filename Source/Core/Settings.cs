using System;
using System.IO;
using System.Text;
using System.Text.Json;

namespace AudionOfficeOcrAi.Core;

/// <summary>
/// config\window_settings.json: the look of this window alone - its theme, its language, its size,
/// its fonts. Where the files
/// come from and go to is not kept here - every start begins with input and output of the program,
/// and the history of paths is config\path_history.json. A Debug copy keeps the file beside
/// itself: a check of the window must not change the look of the window the owner works in.
/// </summary>
public sealed class Settings
{
    /// <summary>The theme, one of the shell's: "codedark" (the default here, as in the window on NiceGUI), "vault", "dark", "light".</summary>
    public string Look { get; set; } = "codedark";

    /// <summary>"" - none chosen yet: the language of the system is used. "ru" or "en" once a button was pressed.</summary>
    public string Lang { get; set; } = "";

    public double Width { get; set; }
    public double Height { get; set; }

    /// <summary>The fonts of the window and of the terminal by the names of their families; "" - the window in Inter, the terminal in JetBrains Mono, both inside the program.</summary>
    public string UiFont { get; set; } = "";
    public string LogFont { get; set; } = "";

    /// <summary>How much larger (or smaller) than usual every text of the window is, in points; the size of the terminal's text.</summary>
    public double UiShift { get; set; }
    public double LogSize { get; set; } = UsualLogSize;
    public const double UsualLogSize = 10.5;

    /// <summary>The language of the window: the chosen one; with none chosen, Russian when the system speaks it, English otherwise.</summary>
    [System.Text.Json.Serialization.JsonIgnore]
    public string LanguageInUse => Lang switch
    {
        "ru" => "ru",
        "en" => "en",
        _ => string.Equals(System.Globalization.CultureInfo.CurrentUICulture.TwoLetterISOLanguageName, "ru", StringComparison.OrdinalIgnoreCase) ? "ru" : "en",
    };

    static readonly JsonSerializerOptions Json = new() { WriteIndented = true, PropertyNameCaseInsensitive = true };

    /// <summary>Where the settings are kept: ABOUT shows it.</summary>
    public static string FilePath => Paths.Released ? Path.Combine(Paths.Config, "window_settings.json") : Path.Combine(AppContext.BaseDirectory, "window_settings.json");

    /// <summary>A file that does not read is no settings, not an error: the window opens with its usual look.</summary>
    public static Settings Load()
    {
        Settings? found = null;
        try
        {
            if (File.Exists(FilePath)) found = JsonSerializer.Deserialize<Settings>(File.ReadAllText(FilePath, Encoding.UTF8), Json);
        }
        catch { }
        found ??= new Settings();
        if (found.Look is not ("vault" or "dark" or "codedark" or "light")) found.Look = "codedark";
        found.Lang ??= "";
        found.UiFont ??= "";
        found.LogFont ??= "";
        found.UiShift = Math.Clamp(Math.Round(found.UiShift * 2) / 2, -1, 2);
        if (!(found.LogSize >= 9 && found.LogSize <= 14)) found.LogSize = UsualLogSize;
        return found;
    }

    /// <summary>
    /// Written whole or not at all: the new text goes beside the file and takes its place in one
    /// step. A look that could not be saved is nobody's loss - nothing is said of it.
    /// </summary>
    public void Save()
    {
        var temp = FilePath + ".tmp";
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(FilePath)!);
            File.WriteAllText(temp, JsonSerializer.Serialize(this, Json), new UTF8Encoding(false));
            File.Move(temp, FilePath, overwrite: true);
        }
        catch
        {
            try { if (File.Exists(temp)) File.Delete(temp); } catch { }
        }
    }
}
