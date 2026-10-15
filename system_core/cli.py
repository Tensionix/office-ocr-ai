"""The console command of Audion Office OCR AI.

A button of the window and the command line run the same thing: an operation of the manifest, by the
same runner (`execute_operation`), with the parameters the window on NiceGUI gave it - the rules of
that window live in system_core/core/operation_model.py and are checked against its record
(tests/test_cli_door.py).

  ocr_cli.cmd describe
  ocr_cli.cmd run --operation ocr_local_run --source "D:\\Scans" --set ocr_preprocess_profile=raw
  ocr_cli.cmd run --operation extract_local --params values.json --result result.json
  ocr_cli.cmd options --operation ocr_api_run --field yandex_model [--refresh]
  ocr_cli.cmd key add --provider mistral --name work        (the key itself: one line on the standard input)
  ocr_cli.cmd key remove --provider xai --file config/api_key_xai.txt
  ocr_cli.cmd hardware
  ocr_cli.cmd version

The output of `run`: a plain line is a line of the operation's log; a line that starts with
`::ocr::` is a service line and carries JSON - the start, the share of the work done, the end. The
outcome goes to the file of `--result`. `describe`, `options`, `key` and `hardware` answer with one
line of JSON.

Lists of options: `describe` and `options` give what the program keeps (the cache of models in
data\\, the key files in config\\) and ask no provider. Only `options --refresh` asks the provider -
the window does it at the button "refresh the list". The window on NiceGUI asked the providers
whenever a form was drawn; AGENTS.md wanted it "only by an explicit action of the user".

Outcomes and exit codes: done 0; failed 1; stopped 130; a wrong call - 2, and nothing is run.

Paths: a relative `--source` or `--target` is counted from the project folder; a relative
`--params`, `--result` or `--cancel-file` - from the folder of the caller.

Stopping: the caller creates the file of `--cancel-file`; the runner sees it at the next line of a
child process and stops it. The window also holds the whole tree of processes in a job of Windows
and closes it - a child that prints nothing is stopped too.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core import operation_model as model  # noqa: E402
from system_core.core import window_layout  # noqa: E402
from system_core.core.ansi import strip_ansi  # noqa: E402
from system_core.core.jobs import execute_operation  # noqa: E402
from system_core.core.manifest import load_manifest  # noqa: E402
from system_core.core.paths import ensure_project_dirs, get_project_paths  # noqa: E402

CONTROL = "::ocr::"
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_STOPPED = 0, 1, 2, 130

_nobody_listens = False
_colours = False


def say(line: str) -> None:
    global _nobody_listens
    if _nobody_listens:
        return
    try:
        print(line, flush=True)
    except (OSError, ValueError):
        _nobody_listens = True


def control(payload: dict[str, Any]) -> None:
    say(CONTROL + json.dumps(payload, ensure_ascii=False, default=str))


def tell(line: str) -> None:
    """A line of the operation's log; a pipe gets it without colour codes unless it asked for them (`--colours`)."""
    for part in str(line).splitlines() or [""]:
        say(part if _colours or sys.stdout.isatty() else strip_ansi(part))


def usage_error(message: str) -> int:
    try:
        print("[ERR] " + message, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass
    return EXIT_USAGE


def project(root: str | None):
    paths = get_project_paths(Path(root).resolve() if root else ROOT)
    manifest = paths.config / "tool_manifest.yaml"
    if not manifest.is_file():
        raise ValueError(f"not a project folder, no manifest: {manifest}")
    try:
        return paths, load_manifest(manifest)
    except Exception as error:  # noqa: BLE001 - whatever the manifest stumbles over, nothing was run
        raise ValueError(f"the manifest does not read: {manifest}: {error}") from error


def project_version(paths) -> str:
    try:
        return str(json.loads((paths.config / "version.json").read_text(encoding="utf-8-sig")).get("version", ""))
    except (OSError, ValueError):
        return ""


def workbench_path(text: str, fallback: Path, root: Path) -> Path:
    """Source or Target as named by the caller; a relative one is counted from the project folder."""
    if not text:
        return fallback
    cleaned = text.strip().strip('"').strip()
    if '"' in cleaned:
        raise ValueError(f"a quotation mark inside a path - was the path quoted with a backslash at its end? {text!r}")
    path = Path(os.path.expandvars(cleaned)).expanduser()
    return path if path.is_absolute() else root / path


def own_file(text: str) -> str:
    return str(Path(text).expanduser().resolve()) if text else ""


def read_values(args: argparse.Namespace, node) -> dict[str, Any]:
    """The values of the fields: the file of `--params`, over it every `--set name=value`."""
    values: dict[str, Any] = {}
    if getattr(args, "params", ""):
        loaded = json.loads(Path(args.params).read_text(encoding="utf-8-sig"))
        if not isinstance(loaded, dict):
            raise ValueError("--params: a JSON object \"field name: value\" is expected")
        values.update(loaded)
    fields = {model.field_id(field): field for field in node.fields if model.field_id(field)}
    for item in getattr(args, "set", None) or []:
        name, separator, text = item.partition("=")
        name = name.strip()
        if not separator or not name:
            raise ValueError(f"--set: name=value is expected, got {item!r}")
        if name not in fields:
            raise ValueError(f"--set: the operation has no field {name!r}")
        try:
            values[name] = model.coerce(fields[name], text)
        except ValueError as error:
            raise ValueError(f"--set {name}: {error}") from error
    return values


def write_result(path: str, payload: dict[str, Any]) -> str:
    if not path:
        return ""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        draft = target.with_name(target.name + ".tmp")
        draft.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        draft.replace(target)
        return ""
    except OSError as error:
        return str(error)


@contextlib.contextmanager
def offline_lists() -> Iterator[None]:
    """The lists of models as the program keeps them: the providers are not asked.

    The functions of the lists (services/office_service.py) read the cache and then ask the provider
    whenever a key is there, and fall back to what they have when asking fails. Asking fails here.
    """
    from system_core.services import office_service

    def refuse(*_args, **_kwargs):
        raise RuntimeError("offline: the provider is asked only by an explicit refresh")

    names = ("_yandex_models", "_xai_models", "_online_models", "_openai_models", "_gemini_models")
    saved = {name: getattr(office_service, name) for name in names if hasattr(office_service, name)}
    for name in saved:
        setattr(office_service, name, refuse)
    try:
        yield
    finally:
        for name, function in saved.items():
            setattr(office_service, name, function)


def list_of(field: dict[str, Any], node, paths, values: dict[str, Any], source: Path, target: Path, refresh: bool) -> dict[str, Any]:
    """The options of one field: as the manifest lists them, or as its function gives them."""
    origin = model.option_source(field)
    if not origin:
        options = field.get("options", [])
        return {"field": model.field_id(field), "source": "", "options": model.describe_options(options if isinstance(options, list) else [])}
    state = model.form_state(node, values, str(source), str(target))
    try:
        if refresh:
            options = model.resolve_options(origin, paths.root, state)
        else:
            with offline_lists():
                options = model.resolve_options(origin, paths.root, state)
    except Exception as error:  # noqa: BLE001 - the reason is the answer: a window shows it in place of the list
        return {"field": model.field_id(field), "source": origin, "options": [], "error": f"{error.__class__.__name__}: {error}"}
    return {"field": model.field_id(field), "source": origin, "options": model.describe_options(options)}


def command_describe(args: argparse.Namespace) -> int:
    paths, manifest = project(args.root)
    os.chdir(ROOT)
    payload = model.describe(manifest)
    payload["version"] = project_version(paths)
    payload["layout"] = window_layout.describe(window_layout.load(paths.config), manifest)
    payload["paths"] = {"root": str(paths.root), "input": str(paths.input), "output": str(paths.output),
                        "logs": str(paths.logs), "report": str(paths.report), "config": str(paths.config),
                        "workspace": str(paths.workspace)}
    # The lists a form opens with: what the program keeps, nothing asked of a provider - for every
    # choice of the page (the models of each provider), each with the values it was read for.
    lists: dict[str, list[dict[str, Any]]] = {}

    def keep(place_id: str, values: dict[str, Any]) -> None:
        node = model.find_node(manifest, place_id)
        if node is None:
            return
        state = model.form_state(node, values, str(paths.input), str(paths.output))
        for field in node.fields:
            if not model.option_source(field):
                continue
            told = list_of(field, node, paths, values, paths.input, paths.output, refresh=False)
            entry = {"depends": {name: state.get(name) for name in model.depends_on(field)},
                     "options": told["options"], "error": told.get("error", "")}
            kept = lists.setdefault(f"{place_id}:{model.field_id(field)}", [])
            if entry not in kept:
                kept.append(entry)

    for section in payload["layout"].get("sections") or []:
        for page in section.get("pages") or []:
            for choice in page.get("choices") or [{}]:
                values = {**(page.get("fixed") or {}), **(choice.get("values") or {})}
                for place in page.get("operations") or []:
                    keep(place["id"], values)
    for place in list(payload["layout"].get("service") or []) + list(payload["layout"].get("folders") or []):
        keep(place["id"], {})
    payload["lists"] = lists
    say(json.dumps(model.share_forms(payload), ensure_ascii=False, default=str))
    return EXIT_OK


def command_run(args: argparse.Namespace) -> int:
    global _colours
    _colours = bool(args.colours)
    paths, manifest = project(args.root)
    node = model.find_node(manifest, args.operation)
    if node is None:
        return usage_error(f"the manifest has no operation {args.operation!r}")
    args.params, args.result, args.cancel_file = own_file(args.params), own_file(args.result), own_file(args.cancel_file)
    try:
        values = read_values(args, node)
        source = workbench_path(args.source, paths.input, paths.root)
        target = workbench_path(args.target, paths.output, paths.root)
    except (OSError, ValueError) as error:
        return usage_error(str(error))
    unknown = model.unknown_values(node, values)
    if unknown:
        return usage_error("the operation has no fields: " + ", ".join(unknown))
    wrong = model.wrong_choices(node, values)
    if wrong:
        return usage_error("not one of the options of the field: " + ", ".join(wrong))
    short = model.short_selections(node, values, str(source), str(target))
    if short:
        return usage_error("fewer ticks than the field asks for: " + ", ".join(short))

    ensure_project_dirs(paths)
    os.chdir(ROOT)
    cancel_file = Path(args.cancel_file) if args.cancel_file else None
    operation = node.to_operation(model.build_parameters(node, values, source, target)) if hasattr(node, "to_operation") \
        else replace(node, parameters=model.build_parameters(node, values, source, target))

    control({"started": {"operation": operation.id, "source": str(source), "target": str(target)}})
    began = time.monotonic()
    result = execute_operation(paths, operation, tell,
                               lambda value: control({"progress": round(float(value), 4)}),
                               (lambda: cancel_file.exists()) if cancel_file is not None else None)
    stopped = (not result.ok) and cancel_file is not None and cancel_file.exists()
    outcome = "stopped" if stopped else "done" if result.ok else "failed"
    seconds = round(time.monotonic() - began, 1)
    trouble = write_result(args.result, {"operation": operation.id, "outcome": outcome, "ok": result.ok,
                                         "message": result.message, "data": result.data,
                                         "source": str(source), "target": str(target), "seconds": seconds})
    if trouble:
        say(f"[WARN] The outcome could not be written to {args.result}: {trouble}")
    control({"finished": {"outcome": outcome, "message": result.message, "seconds": seconds}})
    return EXIT_STOPPED if stopped else EXIT_OK if result.ok else EXIT_FAILED


def command_options(args: argparse.Namespace) -> int:
    paths, manifest = project(args.root)
    node = model.find_node(manifest, args.operation)
    if node is None:
        return usage_error(f"the manifest has no operation {args.operation!r}")
    field = next((item for item in node.fields if model.field_id(item) == args.field), None)
    if field is None:
        return usage_error(f"the operation {node.id!r} has no field {args.field!r}")
    args.params = own_file(args.params)
    try:
        values = read_values(args, node)
        source = workbench_path(args.source, paths.input, paths.root)
        target = workbench_path(args.target, paths.output, paths.root)
    except (OSError, ValueError) as error:
        return usage_error(str(error))
    os.chdir(ROOT)
    told = list_of(field, node, paths, values, source, target, refresh=bool(args.refresh))
    say(json.dumps(told, ensure_ascii=False, default=str))
    return EXIT_FAILED if told.get("error") else EXIT_OK


def command_key(args: argparse.Namespace) -> int:
    from system_core.core import api_keys

    paths, _manifest = project(args.root)
    os.chdir(ROOT)
    try:
        if args.action == "add":
            secret = sys.stdin.readline().rstrip("\r\n")
            written = api_keys.add(paths.root, args.provider, args.name, secret)
            say(json.dumps({"ok": True, "provider": args.provider, "file": written}, ensure_ascii=False))
        else:
            moved = api_keys.remove(paths.root, args.provider, args.file)
            say(json.dumps({"ok": True, "provider": args.provider, "archived": moved}, ensure_ascii=False))
    except (OSError, ValueError) as error:
        say(json.dumps({"ok": False, "provider": args.provider, "error": str(error)}, ensure_ascii=False))
        return EXIT_FAILED
    return EXIT_OK


def command_hardware(args: argparse.Namespace) -> int:
    from system_core.core import hardware

    from system_core.core import api_keys
    from system_core.services import office_service

    paths, _manifest = project(args.root)
    os.chdir(ROOT)
    told = hardware.describe()
    # How many key files of each provider hold a key: a count, never a key.
    keys: dict[str, int] = {}
    for provider in api_keys.PROVIDERS:
        try:
            keys[provider] = sum(1 for path in office_service._key_file_candidates(paths.root, provider)
                                 if path.is_file() and office_service._read_key(path))
        except OSError:
            keys[provider] = 0
    told["keys"] = keys
    say(json.dumps(told, ensure_ascii=False, default=str))
    return EXIT_OK


def command_version(args: argparse.Namespace) -> int:
    paths, _manifest = project(args.root)
    say(project_version(paths))
    return EXIT_OK


def add_workbench_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", default="", help="Source: a folder or a file; input by default")
    parser.add_argument("--target", default="", help="Target: where the results go; output by default")


def add_form_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--params", default="", help="A JSON file with the values of the fields by their names")
    parser.add_argument("--set", action="append", metavar="NAME=VALUE", help="The value of one field; may be repeated")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ocr_cli", description="Audion Office OCR AI: the console command.")
    parser.add_argument("--root", default="", help="The project folder, when it is not the one the command lies in")
    # The window names the language it speaks; the texts of the manifest carry both, so nothing here depends on it.
    parser.add_argument("--language", default="", choices=["", "en", "ru"], help="The language of the window that calls")
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("describe", help="The manifest and the layout of the window as JSON").set_defaults(func=command_describe)

    run = commands.add_parser("run", help="Run an operation")
    run.add_argument("--operation", required=True, help="The id of the operation")
    add_workbench_arguments(run)
    add_form_arguments(run)
    run.add_argument("--result", default="", help="Where to write the outcome (JSON)")
    run.add_argument("--cancel-file", default="", help="The stop signal: once the file appears, the operation stops")
    run.add_argument("--colours", action="store_true", help="Leave the colour codes of the services in the lines")
    run.set_defaults(func=command_run)

    options = commands.add_parser("options", help="The list of options of one field")
    options.add_argument("--operation", required=True)
    options.add_argument("--field", required=True)
    options.add_argument("--refresh", action="store_true", help="Ask the provider (models): the only way to the network")
    add_workbench_arguments(options)
    add_form_arguments(options)
    options.set_defaults(func=command_options)

    key = commands.add_parser("key", help="Add a key file (the key on the standard input) or set one aside")
    key.add_argument("action", choices=("add", "remove"))
    key.add_argument("--provider", required=True, choices=("openai", "gemini", "yandex", "xai", "mistral"))
    key.add_argument("--name", default="", help="add: the name of the file; the provider is put into it when missing")
    key.add_argument("--file", default="", help="remove: the key file as the field names it (config/...)")
    key.set_defaults(func=command_key)

    commands.add_parser("hardware", help="The video card, Tesseract, the layout service of Surya").set_defaults(func=command_hardware)
    commands.add_parser("version", help="The version number").set_defaults(func=command_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        return EXIT_USAGE if stop.code not in (0, None) else EXIT_OK
    if not getattr(args, "func", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        return int(args.func(args))
    except (OSError, ValueError) as error:
        return usage_error(f"{error.__class__.__name__}: {error}")


if __name__ == "__main__":
    raise SystemExit(main())
