using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace AudionOfficeOcrAi.Core;

/// <summary>
/// The sets of a row of set buttons (`profile_buttons` of the manifest): what a press does to the
/// values, and whether a set is the one in force. A set that names values, or a flag it turns
/// over, has a state to show: it is lit while its fields hold what it sets - the rule of the
/// window on NiceGUI (`preset_is_active`). A set that picks by a rule - the newest, the starred -
/// is a plain button: what it ticks depends on the list in sight.
/// </summary>
public static class Presets
{
    /// <summary>The set shows whether it is in force.</summary>
    public static bool HasState(Preset preset) => preset.Pick.Count == 0 && (preset.Toggle.Count > 0 || preset.Values.Count > 0);

    /// <summary>Every field the set names holds what the set puts there; lists are compared as sets, the order of ticks does not matter.</summary>
    public static bool IsActive(Preset preset, Values values)
    {
        if (!HasState(preset)) return false;
        foreach (var (id, wanted) in preset.Toggle.Concat(preset.Values))
        {
            var held = values.Get(id);
            if (wanted.ValueKind == JsonValueKind.Array)
            {
                var asked = wanted.EnumerateArray().Select(FieldKinds.Text).ToHashSet();
                if (!asked.SetEquals(held.Split(Values.ListSeparator, StringSplitOptions.RemoveEmptyEntries))) return false;
            }
            else if (held != FieldKinds.Text(wanted)) return false;
        }
        return true;
    }

    /// <summary>The fields whose change may light the set or put it out.</summary>
    public static IEnumerable<string> Watched(Preset preset) => preset.Toggle.Keys.Concat(preset.Values.Keys).Distinct();

    /// <summary>
    /// A press of the set. Its values go into their fields; a flag it turns over takes the value
    /// the set names, and at the next press goes back to its default; a rule picks among the
    /// options of its field, as <paramref name="optionsOf"/> has them now.
    /// </summary>
    public static void Press(Preset preset, Values values, Func<Field, IEnumerable<Option>> optionsOf)
    {
        foreach (var (id, value) in preset.Values)
            if (values.Find(id) is { } field) values.Set(field, Values.TextOf(value));
        if (preset.Toggle.Count > 0)
        {
            bool on = preset.Toggle.All(flag => values.Get(flag.Key) == Values.TextOf(flag.Value));
            foreach (var (id, wanted) in preset.Toggle)
                if (values.Find(id) is { } field) values.Set(field, on ? Values.DefaultOf(field) : Values.TextOf(wanted));
        }
        foreach (var (id, rule) in preset.Pick)
        {
            if (values.Find(id) is not { } field) continue;
            var options = optionsOf(field).Where(option => !option.Header).ToList();
            IEnumerable<Option> picked = rule switch
            {
                "all" => options,
                "latest" => options.Take(1),
                "latest_stable" => options.Where(option => !option.Beta && !Unstable.IsMatch(option.Name)).Take(1),
                // The star stands wherever its list writes it: before the name of a build of Windows, after
                // the notes of a driver of NVIDIA ("... - ★ golden"). The window on NiceGUI looked for it
                // anywhere in the name (pick_options); looked for at the start alone, "Golden" ticked no driver.
                "golden" => options.Where(option => option.Label.Contains('★') || option.LabelRu.Contains('★')),
                _ => Enumerable.Empty<Option>(),
            };
            values.Set(field, string.Join(Values.ListSeparator, picked.Select(option => option.Key)));
        }
    }

    /// <summary>
    /// What the ticks of the lists become when the set turns its flag over - asked before the
    /// press. A list of versions whose cards name two files (`installer_id`, `portable_id`) is
    /// another list once "Portable" is turned: a tick moves to the other file of the same
    /// version - to the portable build when the flag goes on, back to the installer when it goes
    /// off; a version without a portable build drops out. As the window on NiceGUI did
    /// (apply_preset). Field id - the ids to tick in the list that comes; only lists that have
    /// ticks to move are named.
    /// </summary>
    public static Dictionary<string, List<string>> Carried(Preset preset, Values values, IEnumerable<Field> fields, Func<Field, IEnumerable<Option>> optionsOf)
    {
        var carried = new Dictionary<string, List<string>>();
        if (preset.Toggle.Count == 0) return carried;
        bool goesOn = !preset.Toggle.All(flag => values.Get(flag.Key) == Values.TextOf(flag.Value));
        foreach (var field in fields.Where(field => Values.IsList(field) && field.DependsOn.Any(preset.Toggle.ContainsKey)))
        {
            var cards = optionsOf(field).Where(option => !option.Header).ToList();
            if (!cards.Any(option => option.PortableId.Length > 0)) continue;
            var picked = values.Picked(field);
            if (picked.Count == 0) continue;
            var moved = new List<string>();
            foreach (var card in cards.Where(option => picked.Contains(option.Key)))
            {
                var other = goesOn ? card.PortableId : card.InstallerId.Length > 0 ? card.InstallerId : card.PortableId;
                if (other.Length > 0 && !moved.Contains(other)) moved.Add(other);
            }
            carried[field.Id] = moved;
        }
        return carried;
    }

    /// <summary>The list has come: the ticks carried over are set - those of them the new list has - as the choice of the person.</summary>
    public static void Land(Values values, Field field, IEnumerable<string> carried, IEnumerable<Option> options)
    {
        var here = options.Where(option => !option.Header).Select(option => option.Key).ToHashSet();
        values.Choose(field, string.Join(Values.ListSeparator, carried.Where(here.Contains)));
    }

    static readonly Regex Unstable = new(@"\b(beta|preview|insider|rc\d*|alpha|dev)\b", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
}
