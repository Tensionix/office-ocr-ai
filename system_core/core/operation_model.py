"""An operation of the manifest as data: its fields, their defaults, the parameters of a run.

What a window knows about an operation without it being a matter of looks: the default of a field,
whether a field is in sight, where a list of options comes from, and which parameters go to the
service. The window on NiceGUI (system_core/ui_nicegui/app.py of 1.8.2) held these rules itself, so
an operation could be run "as in the window" only from the window. Here is one copy of them - for
the console command (system_core/cli.py) and for the window on Avalonia, which calls it.

The rules are carried over from that window unchanged - the conditions of `show_if`, the two
families of OCR built from one operation, the parameters made of the fields in sight. That they give
the same parameters for every operation and every recorded state of its form is checked by
tests/test_cli_door.py against tests/former_window_parameters.json, recorded from that window.
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
from pathlib import Path
from typing import Any

from .manifest import CommandNode, Operation, ToolManifest

ROOT = Path(__file__).resolve().parents[2]

CHECKBOX_GROUP_KINDS = {"checkboxes", "multi_checkbox", "multicheckbox", "multi-select", "multiselect"}
CHECKBOX_KINDS = {"checkbox", "bool", "boolean", "toggle"}
NUMBER_KINDS = {"number", "int", "integer", "float"}
TEXTAREA_KINDS = {"textarea", "multiline"}
SELECT_KINDS = {"select", "choice", "format"}
RADIO_KINDS = {"radio", "radiobuttons", "radio-buttons"}
PATH_KINDS = {"path", "folder", "file"}

# The two families of OCR the window builds from the one operation `ocr_brick`
# (app.py `_root_ocr_nodes`): the free engines of this machine and the paid ones.
LOCAL_OCR_ENGINE_IDS = ("tesseract", "surya")
API_OCR_ENGINE_IDS = ("yandex", "mistral", "xai", "gemini", "chatgpt")
OCR_FAMILIES = (
    {
        "id": "ocr_local", "run": "ocr_local_run", "engines": LOCAL_OCR_ENGINE_IDS, "default": "tesseract",
        "title": "Local OCR", "title_ru": "Локальный OCR",
        "description": "Free/local OCR with preprocessing, Tesseract and Surya modes.",
        "description_ru": "Бесплатный локальный OCR с препроцессингом: Tesseract и Surya.",
    },
    {
        "id": "ocr_api", "run": "ocr_api_run", "engines": API_OCR_ENGINE_IDS, "default": "yandex",
        "title": "Paid API OCR", "title_ru": "Платный API OCR",
        "description": "Paid OCR/vision models through Yandex, Mistral, xAI, Gemini, and ChatGPT.",
        "description_ru": "Платные OCR/vision-модели через Yandex, Mistral, xAI, Gemini и ChatGPT.",
    },
)

# The order of the blocks of an OCR form (app.py `OCR_FIELD_SECTION_ORDER`).
OCR_FIELD_SECTION_ORDER = (
    "encoding", "deliverables", "model", "access", "cloud_access", "filters", "local_access",
    "parameters", "options", "output", "format", "source", "run", "advanced",
)
OCR_RUN_NODE_IDS = {"ocr_local_run", "ocr_api_run", "ocr_brick_run"}

# The names of the blocks of a form (app.py LABELS, `section_*`).
BLOCK_TITLES = {
    "advanced": ("Advanced", "Дополнительно"),
    "access": ("Keys and access", "Ключи и доступ"),
    "cloud_access": ("Paid APIs", "Платные API"),
    "deliverables": ("Deliverables", "Готовые файлы"),
    "encoding": ("Engine", "Движок"),
    "format": ("Format", "Формат"),
    "filters": ("Preprocess", "Препроцессинг"),
    "input_mode": ("Input file mode", "Режим входных файлов"),
    "local_access": ("Local / 2-pass", "Локально / 2-pass"),
    "documents": ("Documents", "Документы"),
    "layout": ("Layout", "Раскладка"),
    "model": ("OCR models", "Модели OCR"),
    "options": ("Postprocess", "Постобработка"),
    "output": ("Output", "Результат"),
    "output_mode": ("Output file mode", "Режим выходных файлов"),
    "parameters": ("Prompt and params", "Промпт и параметры"),
    "preset": ("Profile", "Профиль"),
    "run": ("Run", "Запуск"),
    "source": ("Source", "Источник"),
    "workbench": ("Workbench", "Workbench"),
    "processing": ("Processing", "Обработка"),
}

# Field names that mark a field as rarely needed (app.py ADVANCED_FIELD_SUFFIXES).
ADVANCED_FIELD_SUFFIXES = (
    "_model_override", "_chunk_tokens", "_overlap_tokens", "_min_chunks", "_max_retries",
    "_max_output_tokens", "_timeout_sec", "_resume",
)


# ---------------------------------------------------------------- fields


def field_id(field: dict[str, Any]) -> str:
    return str(field.get("id") or field.get("name") or "").strip()


def raw_kind(field: dict[str, Any]) -> str:
    return str(field.get("type", field.get("kind", "text"))).strip().lower()


def window_kind(field: dict[str, Any]) -> str:
    """The kind of field as the window draws it: a flag of the manifest (`toggle`) is a checkbox there."""
    kind = raw_kind(field)
    if kind in CHECKBOX_KINDS:
        return "checkbox"
    if kind in CHECKBOX_GROUP_KINDS:
        return "checkboxes"
    if kind in NUMBER_KINDS:
        return "number"
    if kind in TEXTAREA_KINDS:
        return "textarea"
    if kind in SELECT_KINDS:
        return "select"
    if kind in RADIO_KINDS:
        return "radio"
    if kind in PATH_KINDS:
        return "path"
    return "text"


def is_checkbox_group(field: dict[str, Any]) -> bool:
    return raw_kind(field) in CHECKBOX_GROUP_KINDS


def is_module_path_field(field: dict[str, Any]) -> bool:
    """`input_path` / `output_path` of the form: the two folders of the working area, never drawn."""
    return field_id(field) in {"input_path", "output_path"} and raw_kind(field) in PATH_KINDS


def is_empty_field_value(value: Any) -> bool:
    return value is None or value == "" or value == []


def option_value(option: Any) -> Any:
    if isinstance(option, dict):
        return option.get("value", option.get("id", option.get("label")))
    return option


def raw_option_values(field: dict[str, Any]) -> list[Any]:
    options = field.get("options", [])
    if not isinstance(options, list):
        return []
    return [option_value(option) for option in options]


def field_default(field: dict[str, Any]) -> Any:
    """The value a field has before anyone touched it (app.py `field_default`)."""
    if "default" in field:
        return field["default"]
    default_file = str(field.get("default_file") or "").strip()
    if default_file:
        path = Path(default_file)
        if not path.is_absolute():
            path = ROOT / path
        try:
            return path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:  # noqa: BLE001 - a missing prompt file leaves the field empty, as it did
            return ""
    options = field.get("options", [])
    if is_checkbox_group(field):
        if not isinstance(options, list):
            return []
        return [option.get("value", option.get("id", option.get("label")))
                for option in options if isinstance(option, dict) and option.get("default", False)]
    if isinstance(options, list) and options:
        first = options[0]
        if isinstance(first, dict):
            return first.get("value", first.get("id", ""))
        return first
    return ""


def is_advanced_field(field: dict[str, Any]) -> bool:
    if bool(field.get("advanced", False)):
        return True
    priority = str(field.get("priority") or field.get("section") or "").strip().lower()
    if priority in {"advanced", "expert", "rare"}:
        return True
    return any(field_id(field).endswith(suffix) for suffix in ADVANCED_FIELD_SUFFIXES)


def field_section_id(field: dict[str, Any]) -> str:
    """The block of the form a field stands in (app.py `field_section_id`)."""
    key = field_id(field)
    kind = raw_kind(field)
    section = str(field.get("section") or "").strip().lower()
    explicit = str(field.get("group") or field.get("ui_group") or field.get("section_group") or "").strip().lower()
    if not explicit and section and section not in {"advanced", "expert", "rare"}:
        explicit = section
    if explicit:
        return explicit
    if kind in {"profile_select", "profile-select", "preset_select", "preset-select", "preset_buttons", "presets", "profile_buttons", "profiles"}:
        return "preset"
    if key.endswith("_api_key") or "api_key" in key:
        return "access"
    if key.endswith("_model") or key in {"model", "openai_model", "gemini_model"}:
        return "access"
    if key.startswith("docx_") or any(part in key for part in ("margin", "font", "orientation", "line_height")):
        return "layout"
    if key.startswith("workbench_") or key.startswith("ai_resolver_"):
        return "workbench"
    if key in {"overwrite", "dry_run", "limit_first_file", "test_first_file"} or key.endswith(("_dry_run", "_overwrite")):
        return "run"
    if any(part in key for part in ("source", "input", "url", "file", "folder", "path")):
        return "source"
    if any(part in key for part in ("format", "container", "profile", "preset", "quality", "dpi", "bitrate", "resolution", "prep", "mode")):
        return "format"
    if any(part in key for part in ("output", "report", "export", "package", "release")):
        return "output"
    if any(part in key for part in ("codec", "encode", "engine")):
        return "encoding"
    if kind in CHECKBOX_KINDS | CHECKBOX_GROUP_KINDS:
        return "options"
    return "parameters"


# ---------------------------------------------------------------- conditions (app.py, unchanged)


def condition_of(field: dict[str, Any]) -> Any:
    return field.get("show_if", field.get("visible_if", field.get("when")))


def condition_items(condition: Any) -> list[tuple[str, Any]]:
    if isinstance(condition, dict):
        return [(str(key), value) for key, value in condition.items()]
    if isinstance(condition, list):
        items: list[tuple[str, Any]] = []
        for entry in condition:
            if isinstance(entry, dict):
                key = str(entry.get("field") or entry.get("id") or entry.get("key") or "").strip()
                if key:
                    items.append((key, entry.get("value", entry.get("equals", entry.get("in")))))
        return items
    return []


def value_matches_condition(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set)):
        return any(value_matches_condition(actual, item) for item in expected)
    if isinstance(expected, dict):
        if "not" in expected:
            return not value_matches_condition(actual, expected.get("not"))
        if "in" in expected:
            return value_matches_condition(actual, expected.get("in"))
        if "equals" in expected:
            return value_matches_condition(actual, expected.get("equals"))
        if "empty" in expected:
            return is_empty_field_value(actual) is bool(expected.get("empty"))
    if isinstance(actual, (list, tuple, set)):
        return any(value_matches_condition(item, expected) for item in actual)
    if isinstance(actual, bool) or isinstance(expected, bool):
        return bool(actual) is bool(expected)
    return str(actual).strip().lower() == str(expected).strip().lower()


def condition_matches(condition: Any, values: dict[str, Any]) -> bool:
    items = condition_items(condition)
    if not items:
        return True
    return all(value_matches_condition(values.get(key), expected) for key, expected in items)


def field_is_visible(field: dict[str, Any], values: dict[str, Any]) -> bool:
    if bool(field.get("hidden", False)):
        return False
    if field.get("visible") is False:
        return False
    show_if = condition_of(field)
    if show_if is not None and not condition_matches(show_if, values):
        return False
    hide_if = field.get("hide_if")
    if hide_if is not None and condition_matches(hide_if, values):
        return False
    return True


# ---------------------------------------------------------------- the values of a form


COERCED_FIELDS = {"ocr_engine"}


def coerce_values(values: dict[str, Any], fields) -> dict[str, Any]:
    """A choice the form cannot have falls back to the default (app.py `_coerce_field_values_for_fields`).

    Only the engine is watched: a family offers only its own engines. The first field that needed
    a correction is corrected; the window corrected one per look and stopped there.
    """
    corrected = dict(values)
    for field in fields or ():
        key = field_id(field)
        if key not in COERCED_FIELDS:
            continue
        options = raw_option_values(field)
        if not options:
            continue
        current = corrected.get(key, field_default(field))
        if any(str(current).strip().lower() == str(option).strip().lower() for option in options):
            continue
        corrected[key] = field_default(field)
        return corrected
    return corrected


def form_state(node: CommandNode | Operation, values: dict[str, Any], source: str = "", target: str = "") -> dict[str, Any]:
    """What the conditions of a form are counted against (app.py `current_option_values` + `command_visible_fields`).

    The parameters of the node, the values of the form over them, the correction of a choice the
    form cannot have, the two folders, and every field still without a value at its default.
    """
    state = dict(node.parameters or {})
    state.update(values)
    state = coerce_values(state, node.fields)
    state["input_path"] = str(source)
    state["output_path"] = str(target)
    provider = str(state.get("provider") or "").strip().lower()
    if provider:
        if state.get(f"{provider}_api_key") is not None:
            state["api_key"] = state[f"{provider}_api_key"]
        if state.get(f"{provider}_model") is not None:
            state["model"] = state[f"{provider}_model"]
    for field in node.fields:
        key = field_id(field)
        if key and key not in state:
            state[key] = field_default(field)
    return state


def visible_fields(node: CommandNode | Operation, values: dict[str, Any], source: str = "", target: str = "") -> list[dict[str, Any]]:
    state = form_state(node, values, source, target)
    return [field for field in node.fields if not is_module_path_field(field) and field_is_visible(field, state)]


def build_parameters(node: CommandNode | Operation, values: dict[str, Any], source: str | Path, target: str | Path) -> dict[str, Any]:
    """The parameters of a run (app.py `operation_from_pending_command` + `start_operation`).

    What the manifest sets, then every field in sight with its value or its default; a field in
    sight with `omit_if_empty` and nothing in it is left out. The two folders of the working area
    go under the names the services read them by. A field out of sight is not sent at all - its
    value stays in the form.
    """
    values = coerce_values(dict(values), node.fields)
    parameters = dict(node.parameters or {})
    for field in visible_fields(node, values, str(source), str(target)):
        key = field_id(field)
        if not key:
            continue
        value = values.get(key, field_default(field))
        if bool(field.get("omit_if_empty", False)) and is_empty_field_value(value):
            continue
        parameters[key] = value
    if any(field_id(field) == "input_path" for field in node.fields):
        parameters["input_path"] = str(source)
    if any(field_id(field) == "output_path" for field in node.fields):
        parameters["output_path"] = str(target)
    parameters["_workbench_source_path"] = str(source)
    parameters["_workbench_target_path"] = str(target)
    return parameters


def short_selections(node: CommandNode | Operation, values: dict[str, Any], source: str = "", target: str = "") -> list[str]:
    """Groups of checkboxes in sight with fewer ticks than `min_selected` (app.py `validate_pending_fields`)."""
    short = []
    for field in visible_fields(node, values, source, target):
        if not is_checkbox_group(field):
            continue
        wanted = int(field.get("min_selected", 0) or 0)
        if wanted <= 0:
            continue
        chosen = values.get(field_id(field), field_default(field))
        if not isinstance(chosen, list) or len(chosen) < wanted:
            short.append(field_id(field))
    return short


def unknown_values(node: CommandNode | Operation, values: dict[str, Any]) -> list[str]:
    known = {field_id(field) for field in node.fields if field_id(field)}
    return sorted(key for key in values if key not in known)


def wrong_choices(node: CommandNode | Operation, values: dict[str, Any]) -> list[str]:
    """Values that are none of the options the manifest lists for their field, as "field=value"."""
    wrong = []
    for field in node.fields:
        key = field_id(field)
        options = field.get("options")
        if key not in values or option_source(field) or not isinstance(options, list) or not options:
            continue
        if raw_kind(field) not in CHECKBOX_GROUP_KINDS | RADIO_KINDS | SELECT_KINDS:
            continue
        known = {str(option_value(option)).lower() for option in options}
        given = values[key] if isinstance(values[key], (list, tuple)) else [values[key]]
        wrong.extend(f"{key}={item}" for item in given if str(item).lower() not in known)
    return wrong


def coerce(field: dict[str, Any], text: str) -> Any:
    """A value of the command line (`--set name=value`) in the shape the field expects."""
    kind = raw_kind(field)
    if kind in CHECKBOX_KINDS:
        lowered = text.strip().lower()
        if lowered in {"1", "true", "yes", "on", "да"}:
            return True
        if lowered in {"0", "false", "no", "off", "нет", ""}:
            return False
        raise ValueError("true or false is expected")
    if kind in NUMBER_KINDS:
        number = float(text.replace(",", "."))
        return int(number) if number.is_integer() else number
    if kind in CHECKBOX_GROUP_KINDS:
        stripped = text.strip()
        if stripped.startswith("["):
            loaded = json.loads(stripped)
            if not isinstance(loaded, list):
                raise ValueError("a JSON list is expected")
            return loaded
        return [item.strip() for item in stripped.split(",") if item.strip()]
    if kind in RADIO_KINDS | SELECT_KINDS:
        # A choice keeps the type its options have: 0, 2, 4 are numbers, not text.
        for option in raw_option_values(field):
            if str(option).lower() == text.strip().lower():
                return option
    return text


# ---------------------------------------------------------------- the nodes the window runs


def _condition_values_for_key(condition: Any, key: str) -> list[Any]:
    if isinstance(condition, dict):
        if key in condition:
            return [condition.get(key)]
        values: list[Any] = []
        for item in condition.values():
            if isinstance(item, (dict, list, tuple)):
                values.extend(_condition_values_for_key(item, key))
        return values
    if isinstance(condition, (list, tuple)):
        values = []
        for item in condition:
            values.extend(_condition_values_for_key(item, key))
        return values
    return []


def _flatten_condition_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        if "in" in value:
            return _flatten_condition_values(value.get("in"))
        if "equals" in value:
            return _flatten_condition_values(value.get("equals"))
        if "not" in value or "empty" in value:
            return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_condition_values(item))
        return out
    if value is None:
        return []
    return [str(value).strip()]


def _field_allowed_for_family(field: dict[str, Any], allowed: tuple[str, ...]) -> bool:
    expected: list[str] = []
    for value in _condition_values_for_key(condition_of(field), "ocr_engine"):
        expected.extend(_flatten_condition_values(value))
    if not expected:
        return True
    return any(item in {str(engine) for engine in allowed} for item in expected)


def _filter_engine_field(field: dict[str, Any], allowed: tuple[str, ...], default: str) -> dict[str, Any]:
    cloned = dict(field)
    if str(cloned.get("id") or "") != "ocr_engine":
        return cloned
    allowed_set = set(allowed)
    cloned["options"] = [dict(option) for option in cloned.get("options", [])
                         if isinstance(option, dict) and str(option.get("value") or "") in allowed_set]
    cloned["default"] = default
    cloned["choice_columns"] = max(2, min(8, len(cloned["options"]) or len(allowed)))
    return cloned


def family_nodes(manifest: ToolManifest) -> list[CommandNode]:
    """Local OCR and Paid API OCR: the operation `ocr_brick` with the fields and engines of each family."""
    base = find_manifest_node(manifest, "ocr_brick")
    if base is None:
        return []
    nodes = []
    for family in OCR_FAMILIES:
        fields = tuple(_filter_engine_field(field, family["engines"], family["default"])
                       for field in base.fields if _field_allowed_for_family(field, family["engines"]))
        parameters = dict(base.parameters)
        parameters["ocr_engine"] = family["default"]
        nodes.append(CommandNode(
            id=family["run"], title="Run OCR", title_ru="Запустить OCR",
            description=family["description"], description_ru=family["description_ru"],
            service=base.service, kind=base.kind, parameters=parameters, fields=fields,
        ))
    return nodes


def find_manifest_node(manifest: ToolManifest, node_id: str) -> CommandNode | None:
    def search(nodes) -> CommandNode | None:
        for node in nodes:
            if node.id == node_id:
                return node
            found = search(node.children)
            if found is not None:
                return found
        return None

    return search(manifest.operation_groups)


def all_runnable(manifest: ToolManifest) -> list[CommandNode | Operation]:
    """Every node with a service: the two families first, then the manifest's groups, operations, maintenance."""
    found: list[CommandNode | Operation] = []
    seen: set[str] = set()

    def add(node) -> None:
        if node.service and node.id not in seen:
            seen.add(node.id)
            found.append(node)

    for node in family_nodes(manifest):
        add(node)

    def walk(nodes) -> None:
        for node in nodes:
            if node.children:
                walk(node.children)
            else:
                add(node)

    walk(manifest.operation_groups)
    for node in [*manifest.operations, *manifest.maintenance_operations]:
        add(node)
    return found


def find_node(manifest: ToolManifest, node_id: str) -> CommandNode | Operation | None:
    return next((node for node in all_runnable(manifest) if node.id == node_id), None)


# ---------------------------------------------------------------- lists of options


def option_source(field: dict[str, Any]) -> str:
    return str(field.get("options_source") or "").strip()


def depends_on(field: dict[str, Any]) -> list[str]:
    """The fields a list depends on: a change of one asks for the list anew.

    The manifest names them in `cache_fields`; a list of models also follows the key it is asked with.
    """
    named = field.get("cache_fields") or field.get("depends_on") or []
    names = [named] if isinstance(named, str) else [str(item) for item in named]
    key = field_id(field)
    if key.endswith("_model"):
        provider_key = key[: -len("_model")] + "_api_key"
        if provider_key not in names:
            names.append(provider_key)
    return names


def resolve_options(source: str, root: Path, values: dict[str, Any]) -> list[Any]:
    if ":" not in source:
        raise RuntimeError(f"Dynamic option source must use module:function syntax: {source}")
    module_name, function_name = source.split(":", 1)
    provider = getattr(importlib.import_module(module_name), function_name)
    try:
        count = len(inspect.signature(provider).parameters)
    except (TypeError, ValueError):
        count = 2
    if count >= 2:
        options = provider(root, dict(values))
    elif count == 1:
        options = provider(root)
    else:
        options = provider()
    if not isinstance(options, list):
        raise RuntimeError(f"Dynamic option source returned {type(options).__name__}, expected list.")
    return options


def describe_option(option: Any) -> dict[str, Any]:
    if not isinstance(option, dict):
        return {"value": option, "label": str(option)}
    row = dict(option)
    row["value"] = option_value(option)
    row["label"] = str(option.get("label") or option.get("title") or row["value"])
    return row


def describe_options(options: list[Any]) -> list[dict[str, Any]]:
    return [describe_option(option) for option in options]


# ---------------------------------------------------------------- the description


FIELD_KEYS = (
    "label", "label_ru", "hint", "hint_ru", "tooltip", "tooltip_ru", "placeholder", "min", "max", "step",
    "rows", "min_selected", "hidden", "span", "choice_style", "choice_columns", "choice_compact", "choice_align",
    "checkbox_layout", "checkbox_group_order", "selection_buttons", "refresh_label", "refresh_label_ru",
    "hide_label", "searchable", "omit_if_empty",
)


def describe_field(field: dict[str, Any]) -> dict[str, Any]:
    """A field as the window draws it.

    `visible_when` is the condition of the manifest (`show_if`) as it stands - the window counts it
    on every change; `advanced` puts the field under ADDITIONAL; `group` is the block of the form.
    Nothing is asked of a provider here: a list that comes from a provider is asked for by
    `options`, and its last answer (the cache of models in `data\\`) is what the provider function
    gives without a key.
    """
    row: dict[str, Any] = {"id": field_id(field), "kind": window_kind(field), "default": field_default(field)}
    for key in FIELD_KEYS:
        if key in field:
            row[key] = field[key]
    row["group"] = field_section_id(field)
    row["advanced"] = is_advanced_field(field)
    condition = condition_of(field)
    if isinstance(condition, dict) and condition:
        row["visible_when"] = condition
    hide_if = field.get("hide_if")
    if isinstance(hide_if, dict) and hide_if:
        row["hidden_when"] = hide_if
    if isinstance(field.get("options"), list):
        row["options"] = describe_options(field["options"])
    source = option_source(field)
    if source:
        row["options_source"] = source
        row["depends_on"] = depends_on(field)
        # The terms of the window on NiceGUI (10 s for the keys, 15 min for the models) were those of its own
        # cache. These lists are read from the files of the program, never from a provider: they stay until a
        # run has ended (it may have checked the models) or REFRESH asks the provider.
        row["cache_seconds"] = 0.0
        # A list that looks into the folders of the window is another list for another SOURCE.
        row["reads_folders"] = reads_folders(source)
    # A list of data - key files, fonts, the Markdown found - opens under its field; a choice of a
    # few, written in the manifest, stays a row of switches (the owner: "I hate selects").
    if raw_kind(field) in SELECT_KINDS and (source or len(field.get("options") or []) > 8):
        row["view"] = "dropdown"
    # A list of models a provider gives opens under its field too, with REFRESH, whatever kind the
    # manifest gave it: the only list the window keeps as a select (the owner: models - a select).
    elif source and field_id(field).endswith("_model") and row["kind"] in {"radio", "select"}:
        row["view"] = "dropdown"
    if field_id(field).endswith("_api_key"):
        row["key_provider"] = {"openai": "openai", "gemini": "gemini", "yandex": "yandex", "xai": "xai",
                               "mistral": "mistral"}.get(field_id(field)[: -len("_api_key")], "")
    if field.get("default_file"):
        row["default_file"] = str(field["default_file"])
    return row


MIRROR_HELPERS = {"_prepare_mirror_context", "_prepare_mirror_context_from_paths", "_run_mirrored_script"}
FOLDER_KEYS = {"input_path", "output_path"}
_modules: dict[str, tuple[dict[str, set[str]], dict[str, set[str]]]] = {}


def _module_functions(module: str) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """The functions of a module: whom each calls by name, and the strings it holds."""
    if module not in _modules:
        import ast

        calls: dict[str, set[str]] = {}
        strings: dict[str, set[str]] = {}
        try:
            spec = importlib.util.find_spec(module)
            tree = ast.parse(Path(spec.origin).read_text(encoding="utf-8")) if spec and spec.origin else None
        except (ImportError, OSError, SyntaxError, ValueError):
            tree = None
        for item in tree.body if tree is not None else ():
            if isinstance(item, ast.FunctionDef):
                calls[item.name] = {call.func.id for call in ast.walk(item) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}
                strings[item.name] = {text.value for text in ast.walk(item) if isinstance(text, ast.Constant) and isinstance(text.value, str)}
        _modules[module] = (calls, strings)
    return _modules[module]


def _reaching(module: str, seeds: set[str]) -> set[str]:
    """The functions of a module that are one of `seeds` or call one of them, directly or through another function of it."""
    calls, _strings = _module_functions(module)
    names = set(seeds)
    grown = True
    while grown:
        grown = False
        for function, called in calls.items():
            if function not in names and called & names:
                names.add(function)
                grown = True
    return names


def mirroring_services(module: str) -> set[str]:
    """The functions of a service module that copy an external source into input - clearing input
    and output first - directly or through a function of the same module that does."""
    return _reaching(module, MIRROR_HELPERS) - MIRROR_HELPERS


def folder_reading_lists(module: str) -> set[str]:
    """The option functions of a module whose list depends on the two folders of the window (`input_path`, `output_path`)."""
    _calls, strings = _module_functions(module)
    return _reaching(module, {function for function, held in strings.items() if held & FOLDER_KEYS})


def mirrors(node: CommandNode | Operation) -> bool:
    """Whether a run of the node copies an external source into input, clearing input and output first."""
    service = str(getattr(node, "service", "") or "")
    module, _, function = service.partition(":")
    return bool(function) and function in mirroring_services(module)


def reads_folders(origin: str) -> bool:
    module, _, function = origin.partition(":")
    return bool(function) and function in folder_reading_lists(module)


def describe_node(node: CommandNode | Operation, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    children = tuple(getattr(node, "children", ()))
    raw_children = {str(item.get("id", "")).strip(): item for item in raw.get("children", []) if isinstance(item, dict)}
    fields = [field for field in node.fields if field_id(field) and not is_module_path_field(field)]
    ocr = node.id in OCR_RUN_NODE_IDS
    return {
        "id": node.id, "title": node.title, "title_ru": node.title_ru,
        "description": node.description, "description_ru": node.description_ru,
        "tooltip": getattr(node, "tooltip", ""), "tooltip_ru": getattr(node, "tooltip_ru", ""),
        "kind": node.kind, "runs": bool(node.service), "parameters": dict(node.parameters or {}),
        # A run copies an external source into input and clears input and output first: the window asks before it.
        "mirrors": mirrors(node),
        "prompt": "",
        # The order of the blocks of an OCR form, as the window on NiceGUI had it.
        "groups": list(OCR_FIELD_SECTION_ORDER) if ocr else [],
        "fields": [describe_field(field) for field in fields],
        "children": [describe_node(child, raw_children.get(child.id)) for child in children],
    }


def share_forms(told: dict[str, Any]) -> dict[str, Any]:
    """Every form told once (Audion Get Tools, operation_model.share_forms): a node names its form."""
    forms: dict[str, list[dict[str, Any]]] = {}
    names: dict[str, str] = {}
    of_node: dict[str, str] = {}

    def name_of(fields: list[dict[str, Any]], asked_by: str) -> str:
        if not fields:
            return ""
        key = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
        if key not in names:
            name = asked_by
            while name in forms:
                name += "+"
            names[key] = name
            forms[name] = fields
        return names[key]

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            of_node[node["id"]] = node["form"] = name_of(node.pop("fields", []), node["id"])
            walk(node.get("children") or [])

    for part in ("nodes", "maintenance", "card_operations"):
        walk(told.get(part) or [])

    layout = told.get("layout") or {}
    places = [place for section in layout.get("sections") or [] for page in section.get("pages") or [] for place in page.get("operations") or []]
    for place in places + list(layout.get("service") or []) + list(layout.get("folders") or []):
        fields = place.pop("fields", [])
        dropped = set(place.get("dropped") or [])
        whole = forms.get(of_node.get(place["id"], ""), [])
        if not fields:
            place["form"], place["dropped"] = "", []
        elif [field for field in whole if field["id"] not in dropped] == fields:
            place["form"] = of_node[place["id"]]
        else:
            place["form"], place["dropped"] = name_of(fields, place["id"]), []
        place.pop("children", None)
    told["forms"] = forms
    return told


def describe(manifest: ToolManifest) -> dict[str, Any]:
    def raw_by_id(key: str) -> dict[str, Any]:
        return {str(item.get("id", "")).strip(): item for item in manifest.raw.get(key, []) if isinstance(item, dict)}

    groups, maintenance = raw_by_id("operation_groups"), raw_by_id("maintenance_operations")
    return {
        "tool": dict(manifest.raw.get("tool", {})),
        "ui": dict(manifest.raw.get("ui", {})),
        "nodes": [describe_node(node) for node in family_nodes(manifest)]
        + [describe_node(node, groups.get(node.id)) for node in manifest.operation_groups],
        "maintenance": [describe_node(node, maintenance.get(node.id)) for node in manifest.maintenance_operations],
        "card_operations": [],
        "blocks": {key: {"title": en, "title_ru": ru} for key, (en, ru) in BLOCK_TITLES.items()},
    }
