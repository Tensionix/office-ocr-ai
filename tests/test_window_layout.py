"""The layout of the window and the console command that hands it over.

config/window_layout.yaml places every operation of the manifest, or names it as set aside; the
console command describes the layout so that the window can draw it, and runs an operation as a
button of the window does - on a stand, never on the input and output of this project.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from engine_golden_lib import build_stand, remove_stand
from system_core.core import operation_model as model
from system_core.core import window_layout
from system_core.core.manifest import load_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = load_manifest(PROJECT_ROOT / "config" / "tool_manifest.yaml")
LAYOUT = window_layout.load(PROJECT_ROOT / "config")
PYTHON = PROJECT_ROOT / "runtime" / "python.exe"
CLI = PROJECT_ROOT / "system_core" / "cli.py"


def door(*args: str, root: Path | None = None, stdin: str = "") -> subprocess.CompletedProcess:
    command = [str(PYTHON), "-u", str(CLI)]
    if root is not None:
        command += ["--root", str(root)]
    return subprocess.run([*command, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          input=stdin, timeout=300, check=False)


def test_the_layout_has_no_problems() -> None:
    assert window_layout.problems(LAYOUT, MANIFEST) == []


def test_setup_stands_in_the_header_and_the_ribbon_has_no_markdown_section() -> None:
    described = window_layout.describe(LAYOUT, MANIFEST)
    header = [section["id"] for section in described["sections"] if section["place"] == "header"]
    ribbon = [section["id"] for section in described["sections"] if section["place"] == ""]
    assert header == ["setup"]
    assert ribbon[0] == "local_ocr" and "markdown" not in ribbon
    tools = next(section for section in described["sections"] if section["id"] == "tools")
    assert tools["pages"][0]["id"] == "convert"
    # A place the window does not know is a problem of the layout, not a section that silently vanishes.
    wrong = {**LAYOUT, "sections": [{**LAYOUT["sections"][0], "place": "footer"}, *LAYOUT["sections"][1:]]}
    assert any("place the window does not know" in problem for problem in window_layout.problems(wrong, MANIFEST))


def test_every_operation_of_the_former_window_has_a_place() -> None:
    record = json.loads((PROJECT_ROOT / "tests" / "former_window_parameters.json").read_text(encoding="utf-8"))
    placed = set(window_layout.placed(LAYOUT)) | set(LAYOUT.get("retired") or [])
    # An operation the program no longer has needs no place (tests	est_cli_door.py, LEFT).
    from test_cli_door import LEFT
    assert {entry["operation"] for entry in record["operations"]} - placed - LEFT == set()


def test_describe_is_one_line_of_json_with_every_place() -> None:
    done = door("describe")
    assert done.returncode == 0, done.stderr
    told = json.loads(done.stdout)
    described = {place["id"] for place in window_layout.places(told["layout"])}
    assert described == set(window_layout.placed(LAYOUT))
    for place in window_layout.places(told["layout"]):
        assert place["form"] == "" or place["form"] in told["forms"]
    assert "ocr_engine" in next(place for place in window_layout.places(told["layout"]) if place["id"] == "ocr_local_run")["dropped"]


@pytest.fixture(scope="module")
def stand(tmp_path_factory: pytest.TempPathFactory):
    place = build_stand(tmp_path_factory.mktemp("door") / "stand")
    yield place
    remove_stand(place)


def test_run_reports_its_start_and_end_and_writes_the_outcome(stand: Path, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("Заметка 2026\n", encoding="utf-8")
    target = tmp_path / "target"
    result = tmp_path / "result.json"
    done = door("run", "--operation", "extract_local", "--source", str(source), "--target", str(target),
                "--result", str(result), root=stand)
    assert done.returncode == 0, done.stdout + done.stderr
    controls = [json.loads(line[len("::ocr::"):]) for line in done.stdout.splitlines() if line.startswith("::ocr::")]
    assert "started" in controls[0] and controls[-1]["finished"]["outcome"] == "done"
    assert json.loads(result.read_text(encoding="utf-8"))["outcome"] == "done"
    assert (target / "note.md").read_text(encoding="utf-8").startswith("Заметка 2026")


def test_a_maintenance_operation_runs_through_the_door(stand: Path) -> None:
    # An operation of the maintenance list is no node of a page: the door builds it another way
    # (dataclasses.replace in cli.py), and only a run of one goes through that line.
    (stand / "output").mkdir(exist_ok=True)
    (stand / "output" / "walk.md").write_text("# Проба\n", encoding="utf-8")
    done = door("run", "--operation", "copy_output_markdown_to_input", root=stand)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (stand / "input" / "walk.md").read_text(encoding="utf-8") == "# Проба\n"


def test_a_wrong_call_runs_nothing(stand: Path) -> None:
    assert door("run", "--operation", "no_such_operation", root=stand).returncode == 2
    assert door("run", "--operation", "ocr_local_run", "--set", "no_such_field=1", root=stand).returncode == 2
    assert door("run", "--operation", "ocr_local_run", "--set", "ocr_preprocess_profile=nonsense", root=stand).returncode == 2


def test_a_stop_signal_stops_the_run(stand: Path, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.txt").write_text("x\n", encoding="utf-8")
    signal = tmp_path / "stop"
    signal.write_text("", encoding="utf-8")
    done = door("run", "--operation", "extract_local", "--source", str(source), "--target", str(tmp_path / "t"),
                "--cancel-file", str(signal), root=stand)
    assert done.returncode == 130, done.stdout + done.stderr


def test_keys_are_added_and_set_aside_for_every_provider(stand: Path) -> None:
    for provider in ("openai", "gemini", "yandex", "xai", "mistral"):
        added = door("key", "add", "--provider", provider, "--name", "work", root=stand, stdin="SECRET-VALUE\n")
        told = json.loads(added.stdout)
        assert added.returncode == 0 and told["ok"], added.stdout + added.stderr
        assert provider in told["file"] and "SECRET-VALUE" not in added.stdout
        assert (stand / told["file"]).read_text(encoding="utf-8").strip() == "SECRET-VALUE"
        removed = door("key", "remove", "--provider", provider, "--file", told["file"], root=stand)
        assert removed.returncode == 0, removed.stdout
        assert not (stand / told["file"]).exists()
        assert (stand / json.loads(removed.stdout)["archived"]).is_file()


def test_lists_are_given_without_asking_a_provider(stand: Path) -> None:
    done = door("options", "--operation", "ocr_api_run", "--field", "xai_model", root=stand)
    told = json.loads(done.stdout)
    assert done.returncode == 0 and told["options"], done.stdout + done.stderr
    assert not any((stand / "data").glob("available_models_*.md"))
