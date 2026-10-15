"""The reference runs: which operation, on which source, with which values.

Every case starts from the parameters the former window sent for its node with nothing touched
(tests\\former_window_parameters.json) and changes only what the case is about. Providers answer
from canned replies (engine_golden_lib.network_stubs); what would have been sent is recorded.

Not covered here, on purpose: operations that need Word (build_pdf), a paid language model in a
child process (build_docx_llm, the Workbench resolvers, Gemini Batch), an installer or the state of
this machine (installs, project status, environment doctor, OCR Brick status, model lists).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from engine_golden_lib import digest_tree, network_stubs, normalize_json, reset_work_folders, window_defaults

ALL_FORMATS = ["docx", "xlsx", "searchable_pdf", "odt", "markdown", "json", "html", "verification"]


@dataclass
class Case:
    id: str
    node: str  # path of the node in tests\former_window_parameters.json
    source: str  # name from make_fixtures()
    set: dict[str, Any] = field(default_factory=dict)
    # A state of the form recorded from the window (its "set"), applied before `set`: switching a
    # choice brings the fields it shows, as the window did - not only the value itself.
    state: dict[str, Any] = field(default_factory=dict)
    prepare: Callable[[Path, dict[str, Path]], None] | None = None
    watch: tuple[str, ...] = ("output",)


def _markdown_into_output(stand: Path, fixtures: dict[str, Path]) -> None:
    shutil.copytree(fixtures["markdown"], stand / "output", dirs_exist_ok=True)
    (stand / "output" / "nested").mkdir(exist_ok=True)
    shutil.copy2(fixtures["markdown"] / "note.md", stand / "output" / "nested" / "second.md")


def _scan_into_input(stand: Path, fixtures: dict[str, Path]) -> None:
    shutil.copy2(fixtures["scan"], stand / "input" / "page.png")


def _artifacts_into_output(stand: Path, fixtures: dict[str, Path]) -> None:
    output = stand / "output"
    package = output / "page.document"
    (package / "pages").mkdir(parents=True)
    (package / "document.json").write_text("{}", encoding="utf-8")
    (package / "pages" / "page-0001.ocr.png").write_bytes(b"png")
    (output / "page.document.json").write_text("{}", encoding="utf-8")
    (output / "page.verification.json").write_text("[]", encoding="utf-8")
    (output / "page.docx").write_bytes(b"docx")
    (output / "page.md").write_text("# page\n", encoding="utf-8")


TESSERACT = {"ocr_tesseract_lang": "rus+eng", "ocr_tesseract_psm": 6}
SHORT_FORMATS = {"ocr_output_formats": ["markdown", "json"]}

CASES: list[Case] = [
    Case("extract_local", "extract_local", "office"),
    Case("tesseract_raw_all_formats", "ocr_local/ocr_local_run", "scan", {"ocr_preprocess_profile": "raw", "ocr_output_formats": ALL_FORMATS, **TESSERACT}),
    Case("tesseract_auto", "ocr_local/ocr_local_run", "scan", {"ocr_preprocess_profile": "auto", **SHORT_FORMATS, **TESSERACT}),
    Case("tesseract_heavy", "ocr_local/ocr_local_run", "scan", {"ocr_preprocess_profile": "heavy", **SHORT_FORMATS, **TESSERACT}),
    Case("tesseract_numbers", "ocr_local/ocr_local_run", "scan", {"ocr_preprocess_profile": "numbers", **SHORT_FORMATS, **TESSERACT}),
    Case(
        "tesseract_manual",
        "ocr_local/ocr_local_run",
        "scan",
        {
            "ocr_preprocess_profile": "manual",
            "preprocess_enabled": True,
            "ocr_sr_scale": 0,
            "ocr_denoise": "strong",
            "ocr_contrast": "high",
            "ocr_unsharp": "strong",
            "ocr_binarize": "on",
            "ocr_intent": "text",
            "ocr_strip_vlines": True,
            "ocr_deskew": True,
            **SHORT_FORMATS,
            **TESSERACT,
        },
    ),
    Case("tesseract_structured", "ocr_local/ocr_local_run", "scan", {"ocr_preprocess_profile": "raw", "ocr_output_contract": "structured", "ocr_output_formats": ["docx", "xlsx", "markdown", "json"], **TESSERACT}),
    Case("api_yandex", "ocr_api/ocr_api_run", "scan", {"ocr_engine": "yandex", "ocr_preprocess_profile": "raw", "ocr_output_formats": ["markdown", "json", "docx"]}),
    Case("api_mistral", "ocr_api/ocr_api_run", "scan", state={"ocr_engine": "mistral"}, set={"ocr_preprocess_profile": "raw", "ocr_mistral_second_pass": "none", "ocr_output_formats": ["markdown", "json", "docx"]}),
    Case("api_xai", "ocr_api/ocr_api_run", "scan", state={"ocr_engine": "xai"}, set={"ocr_preprocess_profile": "raw", "ocr_output_formats": ["markdown", "json", "docx"]}),
    Case("api_xai_tesseract_2pass", "ocr_api/ocr_api_run", "scan", state={"ocr_engine": "xai", "ocr_tesseract_2pass": True, "ocr_tesseract_2pass_hint": False}, set={"ocr_preprocess_profile": "raw", "ocr_tesseract_2pass_lang": "rus+eng", "ocr_output_formats": ["markdown", "json"]}),
    Case("api_gemini", "ocr_api/ocr_api_run", "scan", state={"ocr_engine": "gemini"}, set={"ocr_preprocess_profile": "raw", "gemini_use_stream": False, "ocr_output_formats": ["markdown", "json", "docx"]}),
    Case("api_chatgpt", "ocr_api/ocr_api_run", "scan", state={"ocr_engine": "chatgpt"}, set={"ocr_preprocess_profile": "raw", "ocr_output_formats": ["markdown", "json", "docx"]}),
    Case("coordinate_tables", "table_workflow/coordinate_tables", "coords", watch=("output", "report")),
    Case("inspect_tables", "table_workflow/inspect_tables", "markdown"),
    Case("build_xlsx", "table_workflow/build_xlsx", "markdown"),
    Case("build_docx", "project_tools/build/build_docx", "markdown"),
    Case("build_pptx", "project_tools/build/build_pptx", "markdown"),
    Case("quality_benchmark_local", "ocr_quality_benchmark", "scan", {"benchmark_source": "input/page.png", "benchmark_local_engines": ["tesseract"], "benchmark_include_api": False, "ocr_tesseract_lang": "rus+eng"}, prepare=_scan_into_input, watch=("workspace", "report")),
    Case("numeric_check", "numeric_check_pass", "scan", {"numeric_source": "input/page.png", "numeric_locator": "tesseract", "ocr_tesseract_lang": "rus+eng"}, prepare=_scan_into_input, watch=("workspace", "report")),
    Case("workbench_review", "manifest/hybrid_workbench/workbench_review", "scans", watch=("output", "report")),
    Case("copy_output_markdown_to_input", "maintenance/copy_output_markdown_to_input", "markdown", prepare=_markdown_into_output, watch=("input", "output")),
    Case("cleanup_document_model_artifacts", "maintenance/cleanup_document_model_artifacts", "markdown", prepare=_artifacts_into_output, watch=("output",)),
]


def build_operation(case: Case, stand: Path, fixtures: dict[str, Path]):
    from system_core.core.manifest import Operation

    record = json.loads((Path(__file__).parent / "former_window_parameters.json").read_text(encoding="utf-8"))
    node = next(item for item in record["operations"] if item["path"] == case.node)
    parameters = window_defaults(case.node)
    deliverables = stand / "deliverables" / case.id
    for key, value in list(parameters.items()):
        if value == record["source_placeholder"]:
            parameters[key] = str(fixtures[case.source])
        elif value == record["target_placeholder"]:
            parameters[key] = str(deliverables)
    if case.state:
        recorded = next((item for item in node["states"] if item["set"] == case.state), None)
        if recorded is None:
            raise KeyError(f"{case.id}: no recorded state {case.state}")
        parameters.update(recorded.get("parameters", {}))
        for key in recorded.get("removed", []):
            parameters.pop(key, None)
    parameters.update(case.set)
    return Operation(
        id=node["operation"],
        title=case.id,
        description="",
        service=node["service"],
        kind=node["kind"],
        parameters=parameters,
    ), deliverables


def run_case(case: Case, stand: Path, fixtures: dict[str, Path]) -> dict[str, Any]:
    from system_core.core.jobs import execute_operation
    from system_core.core.paths import get_project_paths

    reset_work_folders(stand)
    deliverables_root = stand / "deliverables"
    if deliverables_root.exists():
        shutil.rmtree(deliverables_root)
    if case.prepare is not None:
        case.prepare(stand, fixtures)
    operation, deliverables = build_operation(case, stand, fixtures)
    lines: list[str] = []
    with network_stubs() as sent:
        result = execute_operation(get_project_paths(stand), operation, lines.append, lambda _value: None, lambda: False)
    outcome: dict[str, Any] = {
        "ok": result.ok,
        "message": normalize_json(result.message, stand),
        "result": normalize_json(result.data, stand),
        "requests": sent,
    }
    for folder in case.watch:
        outcome[folder] = digest_tree(deliverables if folder == "deliverables" else stand / folder, stand)
    outcome["deliverables"] = sorted(p.relative_to(deliverables).as_posix() for p in deliverables.rglob("*") if p.is_file()) if deliverables.exists() else []
    if os.environ.get("AUDION_GOLDEN_LOG") == "1":
        outcome["log"] = [normalize_json(line, stand) for line in lines]
    elif not result.ok:
        outcome["log_tail"] = [normalize_json(line, stand) for line in lines[-12:]]
    return outcome
