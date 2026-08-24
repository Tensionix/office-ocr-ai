from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system_core.core.jobs import execute_operation, redact_parameters
from system_core.core.manifest import CommandNode, Operation, ToolManifest, load_manifest
from system_core.core.paths import ensure_project_dirs, get_project_paths


def iter_command_nodes(nodes: Iterable[CommandNode]) -> Iterable[CommandNode]:
    for node in nodes:
        yield node
        yield from iter_command_nodes(node.children)


def operation_catalog(manifest: ToolManifest) -> dict[str, Operation]:
    catalog = {operation.id: operation for operation in [*manifest.operations, *manifest.maintenance_operations]}
    for node in iter_command_nodes(manifest.operation_groups):
        if node.service:
            catalog[node.id] = node.to_operation()
    return catalog


def default_parameters(operation: Operation) -> dict[str, Any]:
    parameters = dict(operation.parameters)
    for field in operation.fields:
        key = str(field.get("id") or "").strip()
        if key and key not in parameters and "default" in field:
            parameters[key] = field.get("default")
    return parameters


def parse_scalar(text: str, default: Any = None) -> Any:
    value = str(text).strip()
    if isinstance(default, bool):
        return value.lower() in {"1", "true", "yes", "on", "enabled"}
    if isinstance(default, int) and not isinstance(default, bool):
        return int(value)
    if isinstance(default, float):
        return float(value)
    if isinstance(default, (list, tuple, set)):
        if value.startswith("["):
            decoded = json.loads(value)
            if not isinstance(decoded, list):
                raise ValueError("List parameter JSON must decode to an array.")
            return decoded
        return [item.strip() for item in value.split(",") if item.strip()]
    if value.lower() in {"null", "none"}:
        return None
    if value.startswith(("{", "[", '"')):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value


def apply_overrides(parameters: dict[str, Any], assignments: list[str]) -> dict[str, Any]:
    result = dict(parameters)
    for assignment in assignments:
        key, separator, raw = str(assignment).partition("=")
        key = key.strip()
        if not separator or not key:
            raise ValueError(f"Expected KEY=VALUE, got: {assignment}")
        result[key] = parse_scalar(raw, result.get(key))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the same manifest/service operation used by the NiceGUI layer.",
    )
    parser.add_argument("operation", nargs="?", help="Manifest operation or command-node id.")
    parser.add_argument("--list", action="store_true", help="List runnable manifest operation ids.")
    parser.add_argument("--set", dest="assignments", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--source", default="", help="Workbench Source file/folder for this run.")
    parser.add_argument("--target", default="", help="Workbench Target folder for this run.")
    parser.add_argument("--engine", default="", help="Shortcut for ocr_engine.")
    parser.add_argument("--preprocess", default="", help="Shortcut for ocr_preprocess_profile.")
    parser.add_argument("--format", dest="formats", action="append", default=[], help="OCR output format; repeatable.")
    parser.add_argument("--contract", choices=("text", "structured"), default="", help="OCR output contract.")
    parser.add_argument("--show-parameters", action="store_true", help="Print resolved parameters without secrets.")
    parser.add_argument("--dry-run", action="store_true", help="Resolve the operation without executing it.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = load_manifest(ROOT / "config" / "tool_manifest.yaml")
    catalog = operation_catalog(manifest)

    if args.list:
        for operation_id in sorted(catalog):
            print(operation_id)
        return 0
    if not args.operation:
        build_parser().error("operation is required unless --list is used")
    if args.operation not in catalog:
        print(f"Unknown operation: {args.operation}", file=sys.stderr)
        print("Use --list to show available ids.", file=sys.stderr)
        return 2

    operation = catalog[args.operation]
    parameters = apply_overrides(default_parameters(operation), args.assignments)
    if args.source:
        parameters["_workbench_source_path"] = args.source
    if args.target:
        parameters["_workbench_target_path"] = args.target
    if args.engine:
        parameters["ocr_engine"] = args.engine
    if args.preprocess:
        parameters["ocr_preprocess_profile"] = args.preprocess
    if args.formats:
        parameters["ocr_output_formats"] = args.formats
    if args.contract:
        parameters["ocr_output_contract"] = args.contract
    operation = replace(operation, parameters=parameters)

    if args.show_parameters or args.dry_run:
        print(json.dumps(redact_parameters(parameters), ensure_ascii=False, indent=2, sort_keys=True))
    if args.dry_run:
        print(f"DRY RUN: {operation.id} -> {operation.service}")
        return 0

    paths = get_project_paths(ROOT)
    ensure_project_dirs(paths)
    last_progress = {"bucket": -1}

    def progress(value: float) -> None:
        bucket = min(4, max(0, int(float(value) * 4)))
        if bucket != last_progress["bucket"]:
            last_progress["bucket"] = bucket
            print(f"[PROGRESS] {bucket * 25}%")

    result = execute_operation(paths, operation, print, progress, lambda: False)
    if result.ok:
        print(result.message)
        return 0
    print(result.message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
