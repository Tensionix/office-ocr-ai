using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AudionOfficeOcrAi.Core;

/// <summary>
/// The values of the fields of one page, by the id of a field and not by the operation: the
/// packages ticked for an install are the ones ticked for an update, and a button placed beside
/// another reads the fields of that one. A value belongs to its page: the same form stands on
/// many pages, and what is set on one - "portable builds only" - is not seen on another, where
/// there may be no button to take it back (the audit of 10.10.2026). The few fields the layout
/// names `shared` are kept by the window instead, one value for every page (<see cref="ValueStore"/>).
/// The values live as long as the window and are not written to the disk - every start begins
/// with the defaults of the manifest.
/// A value is kept as text: a flag as "true" or "false", a number without a tail of zeros, a
/// group of ticks as its values joined by a line break.
/// </summary>
public sealed class Values
{
    /// <summary>The store of the window, for the fields named in <see cref="_shared"/>; null - this is that store.</summary>
    readonly Values? _window;
    readonly HashSet<string> _shared;

    readonly Dictionary<string, string> _held = new();
    /// <summary>
    /// The fields the person has changed. Kept apart from the value: a tick taken off leaves the
    /// value at its default, and is a choice all the same - a list must not tick it again.
    /// </summary>
    readonly HashSet<string> _touched = new();
    /// <summary>Every field the page has met, by its id: a condition or a page may name a field that is not drawn.</summary>
    readonly Dictionary<string, Field> _known = new();
    /// <summary>Field id - the fields whose lists depend on it.</summary>
    readonly Dictionary<string, List<Field>> _dependents = new();

    /// <summary>A value was changed: the id of its field.</summary>
    public event Action<string>? Changed;

    public const char ListSeparator = '\n';

    /// <summary>The values of the window itself: the fields that are one for every page, and the operations of the header.</summary>
    public Values() => _shared = new HashSet<string>();

    /// <summary>The values of a page; the fields named in <paramref name="shared"/> are kept by the window.</summary>
    public Values(Values window, IEnumerable<string> shared)
    {
        _window = window;
        _shared = new HashSet<string>(shared);
        // A shared field changed, on whichever page: this page hears it as a change of its own.
        window.Changed += id => { if (_shared.Contains(id)) Told(id); };
    }

    /// <summary>Who keeps the value of a field: the window for a shared one, this page for every other.</summary>
    Values Home(string id) => _window is not null && _shared.Contains(id) ? _window : this;

    public static bool IsList(Field field) => field.Kind == "checkboxes";

    public void Learn(IEnumerable<Field> fields)
    {
        foreach (var field in fields)
        {
            if (_known.ContainsKey(field.Id)) continue;
            _known[field.Id] = field;
            foreach (var name in field.DependsOn)
            {
                if (!_dependents.TryGetValue(name, out var list)) _dependents[name] = list = new List<Field>();
                list.Add(field);
            }
        }
    }

    /// <summary>A field the page has met, by its id; null for one it has not.</summary>
    public Field? Find(string id) => _known.TryGetValue(id, out var field) ? field : null;

    /// <summary>The person has set this field: what a list ticks by itself must not overwrite the choice.</summary>
    public bool IsTouched(Field field) => Home(field.Id)._touched.Contains(field.Id);

    /// <summary>A value of the manifest as the text this class keeps: a list as its items joined by a line break.</summary>
    public static string TextOf(JsonElement value) => value.ValueKind == JsonValueKind.Array
        ? string.Join(ListSeparator, value.EnumerateArray().Select(FieldKinds.Text)) : FieldKinds.Text(value);

    /// <summary>The default of a field as the text this class keeps.</summary>
    public static string DefaultOf(Field field)
    {
        var value = field.DefaultInUse;
        if (IsList(field))
            return value.ValueKind == JsonValueKind.Array ? string.Join(ListSeparator, value.EnumerateArray().Select(FieldKinds.Text)) : "";
        if (value.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
        {
            // No default written: a flag is off, a choice stands on its first option, a text is empty.
            if (field.Kind == "checkbox") return "false";
            if (field.Kind is "radio" or "tabs" or "select" && field.Options.Count > 0) return field.Options[0].Key;
            return "";
        }
        return FieldKinds.Text(value);
    }

    public string Get(Field field) => Home(field.Id)._held.TryGetValue(field.Id, out var value) ? value : DefaultOf(field);

    /// <summary>The value of a field by its id alone: what a condition asks. "" for a field the page has not met.</summary>
    public string Get(string id) =>
        Home(id)._held.TryGetValue(id, out var value) ? value : _known.TryGetValue(id, out var field) ? DefaultOf(field) : "";

    public bool IsOn(Field field) => Get(field) == "true";

    public HashSet<string> Picked(Field field) =>
        Get(field).Split(ListSeparator, StringSplitOptions.RemoveEmptyEntries).ToHashSet();

    public bool IsChanged(Field field) => Get(field) != DefaultOf(field);

    /// <summary>The person sets a field.</summary>
    public void Set(Field field, string value)
    {
        Learn(new[] { field });
        Put(field.Id, value, DefaultOf(field), byPerson: true);
    }

    /// <summary>
    /// A choice of the person that may be what the field holds already - "none of these" among
    /// them: the field counts as chosen all the same, and a list does not tick its own over it.
    /// </summary>
    public void Choose(Field field, string value)
    {
        Learn(new[] { field });
        Home(field.Id)._touched.Add(field.Id);
        Put(field.Id, value, DefaultOf(field), byPerson: true);
    }

    /// <summary>
    /// A list ticks what it ticks by itself - the driver this PC needs - every time it is shown,
    /// until the person has changed the field: a tick taken off by hand does not come back.
    /// </summary>
    public void Offer(Field field, string value)
    {
        Learn(new[] { field });
        if (IsTouched(field)) return;
        Put(field.Id, value, DefaultOf(field), byPerson: false);
    }

    /// <summary>A value a page sets by itself, for a field it does not draw.</summary>
    public void Fix(string id, string value) => Put(id, value, _known.TryGetValue(id, out var field) ? DefaultOf(field) : null, byPerson: false);

    void Put(string id, string value, string? fallback, bool byPerson)
    {
        var home = Home(id);
        if (Get(id) == value && (home._held.ContainsKey(id) || _known.ContainsKey(id))) return;
        if (byPerson) home._touched.Add(id);
        // A value equal to the default is not held.
        if (value == fallback) home._held.Remove(id);
        else home._held[id] = value;
        home.Told(id);
    }

    /// <summary>
    /// A field this store keeps has changed - or, for a page, a shared one has, anywhere in the
    /// window: the store of the window tells every page that shares the field, this one too.
    /// </summary>
    void Told(string id)
    {
        // A list that depends on this field is another list now: what was ticked in the old one goes,
        // and with it the mark that the person chose - the new list may tick its own.
        if (_dependents.TryGetValue(id, out var dependents))
            foreach (var dependent in dependents)
            {
                var home = Home(dependent.Id);
                bool held = home._held.Remove(dependent.Id), touched = home._touched.Remove(dependent.Id);
                if (!held && !touched) continue;
                if (ReferenceEquals(home, this)) Changed?.Invoke(dependent.Id);
                else home.Changed?.Invoke(dependent.Id);
            }
        Changed?.Invoke(id);
    }

    /// <summary>Back to the defaults of the manifest: the values go, and the marks that the person chose them.</summary>
    public void Reset(IEnumerable<Field> fields)
    {
        foreach (var field in fields)
        {
            var home = Home(field.Id);
            bool held = home._held.Remove(field.Id), touched = home._touched.Remove(field.Id);
            if (held || touched) home.Told(field.Id);
        }
    }

    /// <summary>
    /// The first list in sight with fewer ticks than its field asks for (`min_selected`); null
    /// when every list has enough - or the operation reads none of them (Node.ValidatesFields).
    /// </summary>
    public Field? TooFew(Node node, Func<Field, bool> inSight) =>
        !node.ValidatesFields ? null
        : node.Fields.FirstOrDefault(field => IsList(field) && field.MinSelected > 0 && inSight(field) && Picked(field).Count < field.MinSelected);

    /// <summary>
    /// The values of an operation as the door reads them (--params): every field of its form by
    /// its id, in the type the field has, and over them what the page sets by itself.
    /// </summary>
    public string ForDoor(Node node) => ForDoor(node, "", "");

    /// <summary>
    /// The values of an operation run for one card of a list: as the form holds them, with the
    /// list of that card holding its one id. Nothing the form holds is changed - what is ticked
    /// stays ticked.
    /// </summary>
    public string ForDoor(Node node, string list, string only)
    {
        var payload = new JsonObject();
        foreach (var field in node.Fields)
        {
            if (field.Kind is "profile_buttons" or "toggle_buttons") continue;   // rows of buttons: they hold no value of their own
            payload[field.Id] = field.Id == list && list.Length > 0 ? new JsonArray(JsonValue.Create(only)) : Json(field);
        }
        if (node.Page is { } page)
            foreach (var (id, value) in page.Fixed) payload[id] = JsonNode.Parse(value.GetRawText());
        return payload.ToJsonString(new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        });
    }

    JsonNode? Json(Field field)
    {
        if (!IsChanged(field))
        {
            var raw = field.DefaultInUse;
            if (raw.ValueKind is not (JsonValueKind.Undefined or JsonValueKind.Null)) return JsonNode.Parse(raw.GetRawText());
        }
        var text = Get(field);
        return field.Kind switch
        {
            "checkbox" => JsonValue.Create(text == "true"),
            "number" => Number(text),
            "checkboxes" => new JsonArray(text.Split(ListSeparator, StringSplitOptions.RemoveEmptyEntries).Select(item => (JsonNode?)JsonValue.Create(item)).ToArray()),
            // A choice goes as the manifest wrote its value: a number stays a number.
            "radio" or "tabs" or "select" => field.Options.FirstOrDefault(option => option.Key == text) is { } option
                ? JsonNode.Parse(option.Value.GetRawText()) : JsonValue.Create(text),
            _ => JsonValue.Create(text),
        };
    }

    static JsonNode Number(string text)
    {
        if (!double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) return JsonValue.Create(text);
        return number == Math.Floor(number) && Math.Abs(number) < 1e15 ? JsonValue.Create((long)number) : JsonValue.Create(number);
    }

    /// <summary>The fields of an operation that are not at their defaults, as "--set" would name them.</summary>
    public Dictionary<string, string> ChangedOf(Node node) => ChangedOf(node, "", "");

    /// <summary>The same for a run of one card of a list: the list is named with its one id.</summary>
    public Dictionary<string, string> ChangedOf(Node node, string list, string only)
    {
        var changed = new Dictionary<string, string>();
        if (node.Page is { } page)
            foreach (var (id, value) in page.Fixed) changed[id] = FieldKinds.Text(value);
        foreach (var field in node.Fields)
        {
            if (field.Kind is "profile_buttons" or "toggle_buttons") continue;
            if (field.Id == list && list.Length > 0) changed[field.Id] = only;
            else if (IsChanged(field)) changed[field.Id] = Get(field).Replace(ListSeparator, ',');
        }
        return changed;
    }
}

/// <summary>
/// The values of the whole window: a store for every page, and one of the window itself for the
/// fields the layout names `shared` (config\window_layout.yaml) and for the operations of the
/// header, which stand on no page.
/// </summary>
public sealed class ValueStore
{
    readonly HashSet<string> _shared;
    readonly Dictionary<string, Values> _pages = new();

    public ValueStore(IEnumerable<string>? shared = null) => _shared = new HashSet<string>(shared ?? Array.Empty<string>());

    /// <summary>The values of the window itself.</summary>
    public Values Window { get; } = new();

    /// <summary>A page by its section and its own id: the ids of pages repeat across sections.</summary>
    public static string KeyOf(Page page) => (page.Section?.Id ?? "") + "/" + page.Id;

    /// <summary>The values of a page; of the window, for an operation that stands on none.</summary>
    public Values Of(Page? page)
    {
        if (page is null) return Window;
        if (!_pages.TryGetValue(KeyOf(page), out var values)) _pages[KeyOf(page)] = values = new Values(Window, _shared);
        return values;
    }

    /// <summary>
    /// A page comes into sight: its fields are known before its own values are set - a list that
    /// depends on one of them is another list from then on. What the page fixes goes into the
    /// values of that page alone.
    /// </summary>
    public Values Open(Page page)
    {
        var values = Of(page);
        foreach (var node in page.Operations) values.Learn(node.Fields);
        foreach (var (id, value) in page.Fixed) values.Fix(id, Values.TextOf(value));
        return values;
    }
}
