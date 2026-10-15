"""The console command gives the service what the former window gave it.

tests/former_window_parameters.json was recorded from the window on NiceGUI (1.8.2): for every
operation and many states of its form, the parameters it handed to the service. The rules of that
window now live in system_core/core/operation_model.py, for the console command and for the window
on Avalonia; here they are asked the same questions and must give the same answers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from system_core.core import operation_model as model
from system_core.core.manifest import load_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECORD = json.loads((PROJECT_ROOT / "tests" / "former_window_parameters.json").read_text(encoding="utf-8"))
# Operations of the former window the program no longer has. The record stays as it was taken;
# these entries are not asked. dev_markdown_pdf - Markdown to PDF is Audion Build PDF Render's
# (render_markdown.cmd).
LEFT = {"dev_markdown_pdf"}
MANIFEST = load_manifest(PROJECT_ROOT / "config" / "tool_manifest.yaml")


def expected(entry: dict, state: dict | None) -> tuple[dict, list[str], bool]:
    parameters = dict(entry["defaults"]["parameters"])
    visible = list(entry["defaults"]["visible"])
    refused = bool(entry["defaults"]["refused"])
    if state is not None:
        parameters.update(state.get("parameters", {}))
        for key in state.get("removed", []):
            parameters.pop(key, None)
        visible = [key for key in visible if key not in state.get("visible_lost", [])] + list(state.get("visible_gained", []))
        refused = bool(state.get("refused"))
    return parameters, visible, refused


def cases():
    for entry in RECORD["operations"]:
        if entry["operation"] in LEFT:
            continue
        yield pytest.param(entry, None, id=f"{entry['path']}:defaults")
        for index, state in enumerate(entry["states"]):
            yield pytest.param(entry, state, id=f"{entry['path']}:{index}")


@pytest.mark.parametrize(("entry", "state"), list(cases()))
def test_parameters_are_those_of_the_former_window(entry: dict, state: dict | None) -> None:
    node = model.find_node(MANIFEST, entry["operation"])
    assert node is not None, f"the console command does not know {entry['operation']}"
    assert node.service == entry["service"]
    values = dict(state["set"]) if state else {}
    source, target = RECORD["source_placeholder"], RECORD["target_placeholder"]
    want_parameters, want_visible, want_refused = expected(entry, state)

    parameters = json.loads(json.dumps(model.build_parameters(node, values, source, target), default=str))
    visible = [model.field_id(field) for field in model.visible_fields(node, values, source, target)]

    assert parameters == want_parameters
    assert sorted(visible) == sorted(want_visible)
    assert bool(model.short_selections(node, values, source, target)) == want_refused


def test_every_runnable_operation_is_known_to_the_console_command() -> None:
    known = {node.id for node in model.all_runnable(MANIFEST)}
    recorded = {entry["operation"] for entry in RECORD["operations"]} - LEFT
    assert recorded - known == set()
    assert LEFT & known == set(), "an operation counted as gone is in the manifest again"
