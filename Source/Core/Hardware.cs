using System.Collections.Generic;
using System.Linq;
using System.Text.Json;

namespace AudionOfficeOcrAi.Core;

/// <summary>
/// What this machine has for OCR, as the door tells it (ocr_cli.cmd hardware): the video card and
/// what to install for it, Tesseract and its languages, the layout service of Surya, how many keys
/// each provider has. The window reads it once at the start and after every run that installs.
/// </summary>
public sealed class Hardware
{
    public string Gpu = "", GpuDriver = "", Cpu = "", Generation = "", Tone = "";
    public string Headline = "", HeadlineRu = "", Short = "", ShortRu = "", Details = "", DetailsRu = "";
    public List<string> Recommended = new(), Optional = new();
    public bool TesseractFound;
    public string TesseractVersion = "", TesseractWhere = "";
    public List<string> TesseractLanguages = new();
    public int LayoutPort;
    public bool LayoutUp;
    public Dictionary<string, int> Keys = new();

    public static Hardware Parse(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        static string Text(JsonElement owner, string name) =>
            owner.ValueKind == JsonValueKind.Object && owner.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
        static List<string> Texts(JsonElement owner, string name) =>
            owner.ValueKind == JsonValueKind.Object && owner.TryGetProperty(name, out var list) && list.ValueKind == JsonValueKind.Array
                ? list.EnumerateArray().Where(item => item.ValueKind == JsonValueKind.String).Select(item => item.GetString() ?? "").ToList() : new List<string>();
        var told = new Hardware
        {
            Gpu = Text(root, "gpu"), GpuDriver = Text(root, "gpu_driver"), Cpu = Text(root, "cpu"),
            Generation = Text(root, "generation"), Tone = Text(root, "tone"),
            Headline = Text(root, "headline"), HeadlineRu = Text(root, "headline_ru"),
            Short = Text(root, "short"), ShortRu = Text(root, "short_ru"),
            Details = Text(root, "details"), DetailsRu = Text(root, "details_ru"),
            Recommended = Texts(root, "recommended_install_ids"), Optional = Texts(root, "optional_install_ids"),
        };
        if (root.TryGetProperty("tesseract", out var tesseract) && tesseract.ValueKind == JsonValueKind.Object)
        {
            told.TesseractFound = tesseract.TryGetProperty("found", out var found) && found.ValueKind == JsonValueKind.True;
            told.TesseractVersion = Text(tesseract, "version");
            told.TesseractWhere = Text(tesseract, "where");
            told.TesseractLanguages = Texts(tesseract, "languages");
        }
        if (root.TryGetProperty("layout_service", out var layout) && layout.ValueKind == JsonValueKind.Object)
        {
            told.LayoutUp = layout.TryGetProperty("up", out var up) && up.ValueKind == JsonValueKind.True;
            if (layout.TryGetProperty("port", out var port) && port.ValueKind == JsonValueKind.Number) told.LayoutPort = port.GetInt32();
        }
        if (root.TryGetProperty("keys", out var keys) && keys.ValueKind == JsonValueKind.Object)
            foreach (var key in keys.EnumerateObject())
                if (key.Value.ValueKind == JsonValueKind.Number) told.Keys[key.Name] = key.Value.GetInt32();
        return told;
    }
}
