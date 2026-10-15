"""The record of the former window's parameters: complete, and true to the window it was taken from.

tests/former_window_parameters.json is what the NiceGUI window (1.8.2) handed to the service for
every operation and many states of its form. The window on Avalonia and the console command are
checked against it; this module checks the record itself:

- every runnable operation of the manifest is in it;
- its counts are those of its body.
"""

from __future__ import annotations

import json
from pathlib import Path


from system_core.core.manifest import load_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECORD = PROJECT_ROOT / "tests" / "former_window_parameters.json"


def load_record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def runnable_ids(nodes) -> set[str]:
    found: set[str] = set()
    for node in nodes:
        if node.children:
            found |= runnable_ids(node.children)
        elif node.service:
            found.add(node.id)
    return found


def test_record_covers_every_runnable_operation() -> None:
    manifest = load_manifest(PROJECT_ROOT / "config" / "tool_manifest.yaml")
    expected = runnable_ids(manifest.operation_groups) | {op.id for op in manifest.maintenance_operations}
    recorded = {item["operation"] for item in load_record()["operations"]}
    assert expected - recorded == set()


def test_record_counts_match_its_body() -> None:
    record = load_record()
    assert record["operations_count"] == len(record["operations"])
    assert record["states_count"] == sum(1 + len(item["states"]) for item in record["operations"])


