"""Where every operation stands in the window on Avalonia: config/window_layout.yaml taken apart.

The manifest says what an operation is; the layout says where it stands - a section, a page of
the section, a card of the page. The console door hands both to the window (`describe`), and the
window knows no section and no operation by its name.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from . import operation_model as model
from .config import load_yaml_or_json
from .manifest import ToolManifest

FILE_NAME = "window_layout.yaml"
LOOKS = ("icon", "block", "block_ru", "tone")


def load(config_folder: Path) -> dict[str, Any]:
    """The layout as written; {} when the project has none - a project without a window on Avalonia."""
    path = config_folder / FILE_NAME
    if not path.is_file():
        return {}
    raw = load_yaml_or_json(path)
    return raw if isinstance(raw, dict) else {}


def _entries(card: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """A card as its operations: the host, then its guests, each with the id of the card it shares."""
    host = str(card.get("op") or "").strip()
    rows = [(card, "")]
    rows.extend((guest, host) for guest in card.get("guests") or [] if isinstance(guest, dict))
    return rows


def placed(layout: dict[str, Any]) -> list[str]:
    """Every id the layout gives a button to: in the cards of the pages, in the header and beside the row of the downloads."""
    ids = []
    for section in layout.get("sections") or []:
        for page in section.get("pages") or []:
            for card in page.get("cards") or []:
                ids.extend(str(entry.get("op") or "").strip() for entry, _host in _entries(card))
    for row in ("service", "folders"):
        ids.extend(str(item.get("op") or "").strip() for item in layout.get(row) or [] if isinstance(item, dict))
    return ids


def _operation(manifest: ToolManifest, entry: dict[str, Any], host: str, fixed: dict[str, Any]) -> dict[str, Any] | None:
    node = model.find_node(manifest, str(entry.get("op") or "").strip())
    if node is None:
        return None
    row = model.describe_node(node)
    row["children"] = []
    if entry.get("run_label"):
        row["run_label"], row["run_label_ru"] = str(entry["run_label"]), str(entry.get("run_label_ru") or entry["run_label"])
    if str(entry.get("form") or "") == "none":
        row["fields"] = []
    # A field the page sets by itself is not drawn; the window still sends its value.
    row["dropped"] = [field["id"] for field in row["fields"] if field["id"] in fixed]
    row["fields"] = [field for field in row["fields"] if field["id"] not in fixed]
    for key in LOOKS:
        if entry.get(key):
            row[key] = str(entry[key])
    # The order of the blocks of the form, where the card names one.
    if isinstance(entry.get("groups"), list):
        row["groups"] = [str(name) for name in entry["groups"]]
    row["beside"] = host
    row["direct"] = bool(row["runs"]) and not row["fields"]
    return row


def page_choices(page: dict[str, Any]) -> list[dict[str, Any]]:
    """The row of switches of a page: what each is called and which values the page fixes while it is on."""
    rows = []
    for choice in page.get("choices") or []:
        if isinstance(choice, dict) and str(choice.get("id") or "").strip():
            rows.append({"id": str(choice["id"]).strip(), "title": str(choice.get("title") or choice["id"]),
                         "icon": str(choice.get("icon") or ""), "tone": str(choice.get("tone") or ""),
                         "title_ru": str(choice.get("title_ru") or choice.get("title") or choice["id"]),
                         "about": str(choice.get("about") or ""), "about_ru": str(choice.get("about_ru") or ""),
                         "values": dict(choice.get("values") or {})})
    return rows


def chosen(page: dict[str, Any], choices: list[dict[str, Any]]) -> str:
    """The choice a page opens on: what the function the page names in `choose` says, else the first.

    The function follows the machine - the maker this PC has a device of - and may fail or name
    nothing: the page then opens on its first choice, as it would without the function.
    """
    if not choices:
        return ""
    source = str(page.get("choose") or "").strip()
    if ":" in source:
        try:
            module_name, function_name = source.split(":", 1)
            named = str(getattr(importlib.import_module(module_name), function_name)(choices) or "")
            if named in {choice["id"] for choice in choices}:
                return named
        except Exception:  # noqa: BLE001 - a machine that cannot be asked is no reason to refuse the window its page
            pass
    return choices[0]["id"]


# Where a section stands: "" - a button of the ribbon under the header, "header" - a button of the
# header, before SETTINGS.
PLACES = ("", "header")


def describe(layout: dict[str, Any], manifest: ToolManifest) -> dict[str, Any]:
    """The layout with every operation described: what the window draws its sections and pages by."""
    sections = []
    for section in layout.get("sections") or []:
        pages = []
        for page in section.get("pages") or []:
            fixed = dict(page.get("fixed") or {})
            choices = page_choices(page)
            # A field a choice of the page sets is not drawn either, whichever choice is on.
            set_by_page = fixed | {key: "" for choice in choices for key in choice["values"]}
            operations = []
            for card in page.get("cards") or []:
                for entry, host in _entries(card):
                    row = _operation(manifest, entry, host, set_by_page)
                    if row is not None:
                        operations.append(row)
            pages.append({key: page.get(key, "") for key in ("id", "title", "title_ru", "icon", "about", "about_ru")}
                         | {"fixed": fixed, "operations": operations, "source": page.get("source") is True,
                            "filter": page.get("filter") is True, "choices": choices, "chosen": chosen(page, choices)})
        sections.append({key: section.get(key, "") for key in ("id", "title", "title_ru", "icon", "about", "about_ru", "place")}
                        | {"pages": pages})
    rows: dict[str, list[dict[str, Any]]] = {"service": [], "folders": []}
    for name, operations in rows.items():
        for entry in layout.get(name) or []:
            row = _operation(manifest, entry, "", {}) if isinstance(entry, dict) else None
            if row is not None:
                operations.append(row)
    return {"sections": sections, "service": rows["service"], "folders": rows["folders"], "shared": shared(layout),
            "pending": dict(layout.get("pending") or {}), "retired": list(layout.get("retired") or [])}


def shared(layout: dict[str, Any]) -> list[str]:
    """The fields whose value is one for the whole window; every other field belongs to its page."""
    return [str(name).strip() for name in layout.get("shared") or [] if str(name).strip()]


def problems(layout: dict[str, Any], manifest: ToolManifest) -> list[str]:
    """What is wrong with the layout, in words; an empty list when nothing is.

    An id the manifest does not have; an operation of the manifest that stands nowhere and is
    named in none of the three lists; a page that fixes a field its operations do not have, or
    fixes it to a value that is none of its options; a shared field no operation has.
    """
    found: list[str] = []
    known = {model.field_id(field) for node in model.all_runnable(manifest) for field in node.fields}
    for name in shared(layout):
        if name not in known:
            found.append(f"`shared` names a field no operation has: {name!r}")
    runs = {node.id for node in model.all_runnable(manifest)}
    stands = placed(layout)
    for name in stands:
        if name not in runs:
            found.append(f"the layout names an operation the manifest does not have: {name!r}")
    aside = set(layout.get("pending") or {}) | set(layout.get("retired") or [])
    for name in sorted(aside - runs):
        found.append(f"`pending` or `retired` names an operation the manifest does not have: {name!r}")
    for name in sorted(runs - set(stands) - aside):
        found.append(f"an operation of the manifest stands nowhere in the window: {name!r}")
    for name in sorted(set(stands) & aside):
        found.append(f"an operation both stands in the window and is set aside: {name!r}")
    for section in layout.get("sections") or []:
        if not section.get("pages"):
            found.append(f"the section {section.get('id')!r} has no pages")
        if str(section.get("place") or "") not in PLACES:
            found.append(f"the section {section.get('id')!r} stands in a place the window does not know: {section.get('place')!r}")
        for page in section.get("pages") or []:
            where = f"{section.get('id')}/{page.get('id')}"
            if not page.get("cards"):
                found.append(f"the page {where} has no cards")
            for card in page.get("cards") or []:
                for entry, _host in _entries(card):
                    node = model.find_node(manifest, str(entry.get("op") or "").strip())
                    if node is None:
                        continue
                    fields = {model.field_id(field): field for field in node.fields}
                    # What the page fixes for good, and what each of its choices fixes while it is on.
                    sets = [("", page.get("fixed") or {})] + [(f" (the choice {choice['id']!r})", choice["values"]) for choice in page_choices(page)]
                    for whose, values in sets:
                        for key, value in values.items():
                            field = fields.get(key)
                            if field is None:
                                found.append(f"the page {where}{whose} fixes {key!r}, which {node.id!r} has no field for")
                                continue
                            options = field.get("options")
                            if isinstance(options, list) and options and \
                                    str(value) not in {str(model.option_value(option)) for option in options}:
                                found.append(f"the page {where}{whose} fixes {key}={value!r}, which is none of its options")
            ids = [choice["id"] for choice in page_choices(page)]
            if len(ids) != len(set(ids)):
                found.append(f"the page {where} names a choice twice")
    return found


def places(described: dict[str, Any]) -> list[dict[str, Any]]:
    """Every operation of a described layout that has a button: the pages, then the header, then the working area."""
    rows = [place for section in described.get("sections") or [] for page in section.get("pages") or []
            for place in page.get("operations") or []]
    return rows + list(described.get("service") or []) + list(described.get("folders") or [])
