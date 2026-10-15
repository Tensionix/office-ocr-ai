using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AudionOfficeOcrAi.Core;

/// <summary>
/// What the door tells of the program (ocr_cli.cmd describe): the sections of the window, their
/// pages, the operations of every page with their fields. The window draws by it and knows no
/// section and no operation by its name: what stands where is config\window_layout.yaml, what an
/// operation is - config\tool_manifest.yaml.
/// </summary>
public sealed class Described
{
    public string Version { get; set; } = "";
    public ProjectPaths Paths { get; set; } = new();
    public Layout Layout { get; set; } = new();
    /// <summary>The operations behind the small buttons of a package card: they stand on no page.</summary>
    public List<Node> CardOperations { get; set; } = new();
    /// <summary>
    /// The forms, each told once: a name and its fields. The same form stands under dozens of
    /// buttons - the downloads on fifteen pages - and an operation names its form instead of
    /// carrying it (operation_model.share_forms of the door); they are put together in Parse.
    /// </summary>
    public Dictionary<string, List<Field>> Forms { get; set; } = new();

    /// <summary>The names of the blocks of a form by the id the manifest gives them (`group` of a field).</summary>
    public Dictionary<string, Block> Blocks { get; set; } = new();

    /// <summary>
    /// The lists a form opens with, by "operation:field": what the program keeps - the cache of
    /// models in data\, the key files in config\ - asked of no provider, one for every set of
    /// values the pages begin with (the models of each provider). A press of REFRESH THE LIST asks
    /// the provider (ocr_cli.cmd options --refresh).
    /// </summary>
    public Dictionary<string, List<Kept>> Lists { get; set; } = new();

    static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        NumberHandling = JsonNumberHandling.AllowReadingFromString,
    };

    /// <summary>The answer of "describe" read; an answer that is no description throws.</summary>
    public static Described Parse(string json)
    {
        var told = JsonSerializer.Deserialize<Described>(json, Json) ?? throw new JsonException("the door gave no description");
        foreach (var section in told.Layout.Sections)
            foreach (var page in section.Pages)
            {
                page.Section = section;
                foreach (var node in page.Operations) node.Page = page;
                // A page with choices opens on the one the door named - the maker this PC has a device of - else on its first.
                if (page.Choices.Count > 0 && !page.Choose(page.Chosen)) page.Choose(page.Choices[0].Id);
            }
        // The fields of an operation: those of the form it names, without the ones its page sets by
        // itself. The fields are the same objects wherever the form stands; the list is the operation's own.
        foreach (var node in told.Operations().Concat(told.CardOperations))
        {
            if (node.Fields.Count > 0 || node.Form.Length == 0) continue;
            if (!told.Forms.TryGetValue(node.Form, out var form)) throw new JsonException($"the operation {node.Id} names a form the description does not have: {node.Form}");
            node.Fields = form.Where(field => !node.Dropped.Contains(field.Id)).ToList();
        }
        return told;
    }

    public static List<Option> ParseOptions(JsonElement list) =>
        JsonSerializer.Deserialize<List<Option>>(list.GetRawText(), Json) ?? new List<Option>();

    /// <summary>Everything that has a button: the operations of the pages, then those of the header, then those beside the row of the downloads.</summary>
    public IEnumerable<Node> Operations() =>
        Layout.Sections.SelectMany(section => section.Pages).SelectMany(page => page.Operations).Concat(Layout.Service).Concat(Layout.Folders);
}

/// <summary>The name of a block of a form.</summary>
public sealed class Block
{
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    [JsonIgnore] public string Name => Words.Pick(TitleRu, Title);
}

/// <summary>A list as the program keeps it, and why it is not there when it is not.</summary>
public sealed class Kept
{
    /// <summary>The values the list was read for: the fields it depends on, the folders of the window.</summary>
    public Dictionary<string, JsonElement> Depends { get; set; } = new();
    public List<Option> Options { get; set; } = new();
    public string Error { get; set; } = "";
}

/// <summary>The folders of the project, as the door resolves them.</summary>
public sealed class ProjectPaths
{
    public string Root { get; set; } = "";
    public string Input { get; set; } = "";
    public string Output { get; set; } = "";
    public string Logs { get; set; } = "";
    public string Report { get; set; } = "";
    public string Config { get; set; } = "";
}

public sealed class Layout
{
    public List<Section> Sections { get; set; } = new();
    /// <summary>The operations of the program itself: the small buttons of the header.</summary>
    public List<Node> Service { get; set; } = new();
    /// <summary>
    /// The operations of the working folders of the program: buttons beside the row DOWNLOADS.
    /// They run on `input` and `output` of the program itself - no source and no target is named
    /// to the door - and the question before one names both folders.
    /// </summary>
    public List<Node> Folders { get; set; } = new();
    /// <summary>The fields whose value is one for the whole window; every other field belongs to its page.</summary>
    public List<string> Shared { get; set; } = new();
}

/// <summary>A section of the window: a large button of the row under the header, or a button of the header itself.</summary>
public sealed class Section
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    public string Icon { get; set; } = "";
    public string About { get; set; } = "";
    public string AboutRu { get; set; } = "";
    /// <summary>"header" - a button of the header, before SETTINGS (SETUP); "" - a button of the row under the header.</summary>
    public string Place { get; set; } = "";
    public List<Page> Pages { get; set; } = new();

    [JsonIgnore] public bool InHeader => Place == "header";

    [JsonIgnore] public string Name => Words.Pick(TitleRu, Title);
    [JsonIgnore] public string Line => Words.Pick(AboutRu, About);
}

/// <summary>A choice of a page: a switch of the row over its form, and the values the page fixes while it is on.</summary>
public sealed class Choice
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    public string About { get; set; } = "";
    public string AboutRu { get; set; } = "";
    public Dictionary<string, JsonElement> Values { get; set; } = new();
    /// <summary>The sign of the switch, and its tone - the colour of the engine or of the provider it chooses.</summary>
    public string Icon { get; set; } = "";
    public string Tone { get; set; } = "";

    [JsonIgnore] public string Name => Words.Pick(TitleRu, Title);
    [JsonIgnore] public string Tip => Words.Pick(AboutRu, About);
}

/// <summary>A page of a section: one of the row under the sections, with its cards.</summary>
public sealed class Page
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    public string Icon { get; set; } = "";
    public string About { get; set; } = "";
    public string AboutRu { get; set; } = "";
    /// <summary>The values the page sets by itself: the fields named are not drawn, and every list, condition and run of the page sees them.</summary>
    public Dictionary<string, JsonElement> Fixed { get; set; } = new();
    /// <summary>
    /// A row of switches over the form of the page, one of them on - the makers of a kind of
    /// device: each names values the page fixes while it is on, as <see cref="Fixed"/> does for good.
    /// </summary>
    public List<Choice> Choices { get; set; } = new();
    /// <summary>The choice that is on; as the door told it - the one the page opens on.</summary>
    public string Chosen { get; set; } = "";

    /// <summary>
    /// A choice comes on: what it names is what the page fixes from now on, in place of what the
    /// choice before it named. False - the page has no such choice.
    /// </summary>
    public bool Choose(string id)
    {
        if (Choices.FirstOrDefault(choice => choice.Id == id) is not { } on) return false;
        foreach (var choice in Choices)
            foreach (var key in choice.Values.Keys) Fixed.Remove(key);
        foreach (var (key, value) in on.Values) Fixed[key] = value;
        Chosen = id;
        return true;
    }

    /// <summary>The operations of the page read a folder the person may choose: the page shows the row SOURCE, and the door is told the folder.</summary>
    public bool Source { get; set; }
    /// <summary>The page has one search for all its lists, in the bar over the cards.</summary>
    public bool Filter { get; set; }
    public List<Node> Operations { get; set; } = new();

    [JsonIgnore] public Section? Section { get; set; }
    [JsonIgnore] public string Name => Words.Pick(TitleRu, Title);
    [JsonIgnore] public string Line => Words.Pick(AboutRu, About);

    /// <summary>
    /// The operations of the page as its cards: an operation with a form is a card, and the
    /// operations the layout places beside it stand in that card as buttons that read the same
    /// fields.
    /// </summary>
    public List<(Node Host, List<Node> Guests)> Cards() =>
        Operations.Where(node => node.Beside.Length == 0)
            .Select(host => (host, Operations.Where(guest => guest.Beside == host.Id).ToList())).ToList();
}

/// <summary>An operation as it stands on a page: what a button runs.</summary>
public sealed class Node
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    public string Description { get; set; } = "";
    public string DescriptionRu { get; set; } = "";
    public string Tooltip { get; set; } = "";
    public string TooltipRu { get; set; } = "";
    /// <summary>The words of its button when they are not its name (`run_label` of the layout): "RUN OCR".</summary>
    public string RunLabel { get; set; } = "";
    public string RunLabelRu { get; set; } = "";
    [JsonIgnore] public string ButtonName => Words.Pick(RunLabelRu, RunLabel) is { Length: > 0 } label ? label : Name;
    /// <summary>"safe" or "dangerous": a dangerous one is asked about.</summary>
    public string Kind { get; set; } = "";
    public string Icon { get; set; } = "";
    /// <summary>What its button wears: "run" - the main action of a card, "burn" - it removes; "" - a plain one.</summary>
    public string Tone { get; set; } = "";
    /// <summary>The logical block of its page an operation without a form stands in.</summary>
    public string Block { get; set; } = "";
    public string BlockRu { get; set; } = "";
    /// <summary>The blocks of the form in the order the layout wants them (`groups` of the card); empty - as the fields come.</summary>
    public List<string> Groups { get; set; } = new();
    /// <summary>The operation whose card this one shares; "" - a card of its own.</summary>
    public string Beside { get; set; } = "";
    public bool Runs { get; set; }
    /// <summary>A run copies an external SOURCE into input, clearing input and output first: the window asks before it.</summary>
    public bool Mirrors { get; set; }
    /// <summary>Runs and has no field to draw: a button is all it needs.</summary>
    public bool Direct { get; set; }
    /// <summary>The name of the value the operation asks for in a pop-up before it runs; "" - none.</summary>
    public string Prompt { get; set; } = "";
    public Dictionary<string, JsonElement> Parameters { get; set; } = new();
    /// <summary>The name of the form of the operation among <see cref="Described.Forms"/>; "" - it has no field.</summary>
    public string Form { get; set; } = "";
    /// <summary>The fields of the form its page sets by itself: they are not drawn.</summary>
    public List<string> Dropped { get; set; } = new();
    /// <summary>The fields of the operation as it stands on its page: put together when the description is read.</summary>
    public List<Field> Fields { get; set; } = new();

    [JsonIgnore] public Page? Page { get; set; }
    [JsonIgnore] public string Name => Words.Pick(TitleRu, Title);
    [JsonIgnore] public string About => Words.Pick(DescriptionRu, Description);
    [JsonIgnore] public string Tip => Words.Pick(TooltipRu, Tooltip);
    [JsonIgnore] public string BlockName => Words.Pick(BlockRu, Block);
    [JsonIgnore] public bool Dangerous => Kind == "dangerous";

    /// <summary>The button of the operation is in sight only while the values of the form match (`visible_when` of its parameters).</summary>
    [JsonIgnore]
    public Dictionary<string, JsonElement>? VisibleWhen =>
        Parameters.TryGetValue("visible_when", out var condition) && condition.ValueKind == JsonValueKind.Object
            ? condition.EnumerateObject().ToDictionary(item => item.Name, item => item.Value) : null;

    /// <summary>The operation asks the door whether it may run (`gate` of its parameters).</summary>
    [JsonIgnore] public bool Gated => Parameters.TryGetValue("gate", out var gate) && gate.ValueKind == JsonValueKind.String;

    /// <summary>
    /// The operation reads the lists of the form it stands in (`validate_fields` of its
    /// parameters; no key - it does). One that does not - it installs a tool, it exports what
    /// another list names - is not held back by a list with too few ticks. The door counts the
    /// same way (operation_model.short_selections).
    /// </summary>
    [JsonIgnore] public bool ValidatesFields => !(Parameters.TryGetValue("validate_fields", out var flag) && flag.ValueKind == JsonValueKind.False);

    /// <summary>What the dialog of the value says (`prompt` of the parameters), in the language of the window; the name of the operation where the manifest gives no title.</summary>
    [JsonIgnore]
    public Asked Asks
    {
        get
        {
            if (!Parameters.TryGetValue("prompt", out var prompt) || prompt.ValueKind != JsonValueKind.Object) return new Asked(Prompt, false, Name, "", "", "");
            string Text(string key) => prompt.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
            string Both(string key) => Words.Pick(Text(key + "_ru"), Text(key));
            return new Asked(Prompt, prompt.TryGetProperty("secret", out var secret) && secret.ValueKind == JsonValueKind.True,
                Both("title") is { Length: > 0 } title ? title : Name, Both("label"), Both("hint"), Both("ok"));
        }
    }

    /// <summary>The main action of its card (`primary` of its parameters).</summary>
    [JsonIgnore] public bool Primary => Parameters.TryGetValue("primary", out var primary) && primary.ValueKind == JsonValueKind.True;
}

/// <summary>
/// The value an operation asks for before it runs: the name the door takes it by, whether it is a
/// secret, and the words of the dialog - its title, the name of the value, the line of
/// explanation, the word of its button.
/// </summary>
public sealed record Asked(string Field, bool Secret, string Title, string Label, string Hint, string Ok);

public sealed class Field
{
    public string Id { get; set; } = "";
    /// <summary>The kind as the manifest names it: one of <see cref="FieldKinds.Known"/>.</summary>
    public string Kind { get; set; } = "";
    public JsonElement Default { get; set; }
    public JsonElement DefaultRu { get; set; }
    public JsonElement DefaultEn { get; set; }
    /// <summary>The block of the form the field stands in: `section` of the manifest.</summary>
    public string Group { get; set; } = "";
    public string Label { get; set; } = "";
    public string LabelRu { get; set; } = "";
    public string Hint { get; set; } = "";
    public string HintRu { get; set; } = "";
    public string Tooltip { get; set; } = "";
    public string TooltipRu { get; set; } = "";
    public string Placeholder { get; set; } = "";
    public double? Min { get; set; }
    public double? Max { get; set; }
    public double? Step { get; set; }
    public int MinSelected { get; set; }
    public int Rows { get; set; }
    /// <summary>In the values of the form, never drawn: another control owns it on the screen.</summary>
    public bool Hidden { get; set; }
    /// <summary>Rarely needed: it stands under ADDITIONAL, after the blocks of the form (`advanced` of the manifest).</summary>
    public bool Advanced { get; set; }
    /// <summary>A field of a key file of a provider: its list carries ADD and SET ASIDE (ocr_cli.cmd key).</summary>
    public string KeyProvider { get; set; } = "";
    /// <summary>The name of the field is not drawn: the block it stands in says what it is (`hide_label`).</summary>
    public bool HideLabel { get; set; }
    public Dictionary<string, JsonElement>? VisibleWhen { get; set; }
    public Dictionary<string, JsonElement>? HiddenWhen { get; set; }
    public List<Option> Options { get; set; } = new();
    /// <summary>Where the options come from when the manifest does not list them; the door is asked (options).</summary>
    public string OptionsSource { get; set; } = "";
    /// <summary>The fields the list of options depends on: a change of one of them asks for the list anew.</summary>
    public List<string> DependsOn { get; set; } = new();
    /// <summary>The list looks into the two folders of the window: another SOURCE is another list.</summary>
    public bool ReadsFolders { get; set; }
    /// <summary>"dropdown" - a choice of many is a field that opens its list under itself, not a row of buttons: the models of an AI provider.</summary>
    public string View { get; set; } = "";
    /// <summary>Not empty - an option of the list may be pinned to its head: the door does it (`pin`).</summary>
    public string Pins { get; set; } = "";
    /// <summary>The list has a search of its own in its head (`filter` of the manifest): the versions of a vendor, the drivers for the image.</summary>
    public bool Filter { get; set; }
    /// <summary>How long a list the door gave stays good, in seconds; 0 - the manifest names no term (Core\ListMemory.cs).</summary>
    public double CacheSeconds { get; set; }
    /// <summary>The sets of a row of set buttons (profile_buttons).</summary>
    public List<Preset> Presets { get; set; } = new();
    /// <summary>The list a row of group buttons acts on (toggle_buttons).</summary>
    public string Target { get; set; } = "";

    [JsonIgnore] public string Name => Words.Pick(LabelRu, Label);
    [JsonIgnore] public string Note => Words.Pick(HintRu, Hint);
    [JsonIgnore] public bool Dynamic => OptionsSource.Length > 0;

    /// <summary>The tooltip: the short line of the manifest, then the full explanation.</summary>
    [JsonIgnore]
    public string Tip
    {
        get
        {
            var more = Words.Pick(TooltipRu, Tooltip);
            return Note.Length > 0 && more.Length > 0 ? Note + "\n\n" + more : Note.Length > 0 ? Note : more;
        }
    }

    /// <summary>The default in the language of the window (`default_ru` over `default`), as the manifest wrote it.</summary>
    [JsonIgnore]
    public JsonElement DefaultInUse
    {
        get
        {
            var local = Lang.Code == "ru" ? DefaultRu : DefaultEn;
            return local.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null ? Default : local;
        }
    }
}

public sealed class Option
{
    public JsonElement Value { get; set; }
    public string Label { get; set; } = "";
    public string LabelRu { get; set; } = "";
    public string Tooltip { get; set; } = "";
    public string TooltipRu { get; set; } = "";
    /// <summary>A heading inside a long list, not a choice: it has no value.</summary>
    public bool Header { get; set; }
    /// <summary>A heading that is a line of explanation over the list - where it comes from, which device of this PC it is for - and opens no block.</summary>
    public bool Note { get; set; }
    /// <summary>Ticked when its list arrives, unless the person has chosen already.</summary>
    public bool Default { get; set; }
    /// <summary>A preview, whatever its card says: "the latest stable" passes it by.</summary>
    public bool Beta { get; set; }
    public string Tone { get; set; } = "";
    /// <summary>The packages a group button adds to its list or takes off it.</summary>
    public List<string> Apps { get; set; } = new();
    /// <summary>A package card carries small buttons: download its installer, its archive or portable build, open its page.</summary>
    public bool Installer { get; set; }
    public bool Archive { get; set; }
    public bool Page { get; set; }
    /// <summary>A version of a vendor with two files: the ids of its installer and of its portable build.</summary>
    public string InstallerId { get; set; } = "";
    public string PortableId { get; set; } = "";
    /// <summary>
    /// The line over a list of drivers: the driver this PC's device runs ("" - the list says nothing
    /// of it), the newest release of the list, and whether the PC is behind it.
    /// </summary>
    public string Running { get; set; } = "";
    public string Newest { get; set; } = "";
    public bool Behind { get; set; }
    /// <summary>Pinned to the head of its list by a person.</summary>
    public bool Pinned { get; set; }

    [JsonIgnore] public string Name => Words.Pick(LabelRu, Label);
    [JsonIgnore] public string Tip => Words.Pick(TooltipRu, Tooltip);
    /// <summary>The value as the text the form keeps and compares.</summary>
    [JsonIgnore] public string Key => FieldKinds.Text(Value);
}

/// <summary>A button of a row of sets: at a press it puts values into fields.</summary>
public sealed class Preset
{
    public string Id { get; set; } = "";
    public string Label { get; set; } = "";
    public string LabelRu { get; set; } = "";
    public string Tooltip { get; set; } = "";
    public string TooltipRu { get; set; } = "";
    public string Hint { get; set; } = "";
    public string HintRu { get; set; } = "";
    /// <summary>Field id - the value it gets.</summary>
    public Dictionary<string, JsonElement> Values { get; set; } = new();
    /// <summary>Field id - a rule that picks among its options: latest, latest_stable, golden, all, none.</summary>
    public Dictionary<string, string> Pick { get; set; } = new();
    /// <summary>Field id - a flag the button turns over.</summary>
    public Dictionary<string, JsonElement> Toggle { get; set; } = new();
    public Dictionary<string, JsonElement>? VisibleWhen { get; set; }

    [JsonIgnore] public string Name => Words.Pick(LabelRu, Label);
    [JsonIgnore] public string Tip => Words.Pick(TooltipRu, Tooltip) is { Length: > 0 } tip ? tip : Words.Pick(HintRu, Hint);
}

public static class Words
{
    /// <summary>The Russian text in the Russian window; the English one otherwise, and wherever the Russian is missing.</summary>
    public static string Pick(string ru, string en) => Lang.Code == "ru" && ru.Length > 0 ? ru : en;
}

public static class FieldKinds
{
    /// <summary>The kinds of field the window can draw. Anything else is said in the journal, not left as an empty place.</summary>
    public static readonly string[] Known =
    {
        "checkbox", "checkboxes", "radio", "tabs", "select", "number", "text", "textarea", "markdown_editor",
        "profile_buttons", "toggle_buttons",
    };

    /// <summary>A value of the manifest as text: a number without a tail of zeros, a flag as true or false.</summary>
    public static string Text(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.String => value.GetString() ?? "",
        JsonValueKind.Number => value.GetDouble().ToString("0.############", CultureInfo.InvariantCulture),
        JsonValueKind.True => "true",
        JsonValueKind.False => "false",
        JsonValueKind.Null or JsonValueKind.Undefined => "",
        _ => value.GetRawText(),
    };

    /// <summary>
    /// `{field: value | [values]}`: every field named has one of its values. The rules are those of
    /// `show_if` in the window on NiceGUI (system_core\core\operation_model.py value_matches_condition):
    /// a list of ticks matches when one of its ticks does; a flag is compared as a flag; text is
    /// compared without regard to case; `not`, `in`, `equals` and `empty` are understood.
    /// </summary>
    public static bool Matches(Dictionary<string, JsonElement>? condition, Func<string, string> valueOf)
    {
        if (condition is null || condition.Count == 0) return false;
        foreach (var (key, wanted) in condition)
            if (!Matches(valueOf(key), wanted)) return false;
        return true;
    }

    static bool Matches(string current, JsonElement wanted)
    {
        switch (wanted.ValueKind)
        {
            case JsonValueKind.Array:
                return wanted.EnumerateArray().Any(item => Matches(current, item));
            case JsonValueKind.Object:
                if (wanted.TryGetProperty("not", out var not)) return !Matches(current, not);
                if (wanted.TryGetProperty("in", out var any)) return Matches(current, any);
                if (wanted.TryGetProperty("equals", out var equals)) return Matches(current, equals);
                if (wanted.TryGetProperty("empty", out var empty)) return (current.Length == 0) == (empty.ValueKind == JsonValueKind.True);
                return false;
        }
        // A list of ticks is kept as its values joined by a line break: one of them is enough.
        if (current.Contains(Values.ListSeparator))
            return current.Split(Values.ListSeparator, StringSplitOptions.RemoveEmptyEntries).Any(item => Matches(item, wanted));
        if (wanted.ValueKind is JsonValueKind.True or JsonValueKind.False)
            return !(current.Length == 0 || current == "false" || current == "0") == (wanted.ValueKind == JsonValueKind.True);
        if (current is "true" or "false")
            return (current == "true") == !(Text(wanted) is "" or "false" or "0");
        return string.Equals(current.Trim(), Text(wanted).Trim(), StringComparison.OrdinalIgnoreCase);
    }
}
