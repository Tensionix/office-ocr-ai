from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from system_core.cli_operation import default_parameters, operation_catalog
from system_core.core.jobs import JobContext
from system_core.core.manifest import Operation, load_manifest
from system_core.core.paths import ensure_project_dirs, get_project_paths
from system_core.dev_markdown_pdf_engine import DEFAULT_LAYOUT
from system_core.services import office_service
from system_core.ui_nicegui import window


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_context(tmp_path: Path, source: Path, target: Path, **parameters: object) -> JobContext:
    project_root = tmp_path / "managed_project"
    paths = get_project_paths(project_root)
    ensure_project_dirs(paths)
    operation = Operation(
        id="ocr_brick_run",
        title="OCR Brick",
        description="",
        service="system_core.services.office_service:ocr_brick_run",
        parameters={
            "_workbench_source_path": str(source),
            "_workbench_target_path": str(target),
            **parameters,
        },
    )
    return JobContext(
        paths=paths,
        operation=operation,
        log_file=paths.logs / "test.log",
        report_dir=paths.report / "test",
    )


def test_cli_catalog_uses_the_same_manifest_services_as_gui() -> None:
    manifest = load_manifest(PROJECT_ROOT / "config" / "tool_manifest.yaml")
    catalog = operation_catalog(manifest)

    assert catalog["ocr_brick_run"].service == "system_core.services.office_service:ocr_brick_run"
    assert catalog["workbench_review"].service == "system_core.services.office_service:workbench_review"
    assert catalog["build_docx"].service == "system_core.services.office_service:build_docx"
    parameters = default_parameters(catalog["ocr_brick_run"])
    assert parameters["ocr_engine"] == "tesseract"
    assert parameters["ocr_output_formats"] == ["docx"]


def test_dev_markdown_pdf_defaults_to_one_point_five_line_height(tmp_path: Path) -> None:
    manifest = load_manifest(PROJECT_ROOT / "config" / "tool_manifest.yaml")
    operation = next(item for item in manifest.operation_groups if item.id == "dev_markdown_pdf")
    field = next(item for item in operation.fields if item.get("id") == "dev_pdf_line_height")
    context = make_context(tmp_path, tmp_path / "source.md", tmp_path / "target")

    args = office_service._dev_markdown_pdf_args(
        context,
        tmp_path / "pdf",
        tmp_path / "sources.txt",
        tmp_path,
    )
    line_height_index = args.index("--line-height")

    assert field["default"] == 1.5
    assert DEFAULT_LAYOUT.line_height == 1.5
    assert args[line_height_index + 1] == "1.5"


def test_gui_window_rejects_remote_bindings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUDION_ALLOW_REMOTE_GUI", raising=False)
    window.assert_gui_host_allowed("127.0.0.1")
    window.assert_gui_host_allowed("::1")
    with pytest.raises(SystemExit):
        window.assert_gui_host_allowed("0.0.0.0")


def test_single_file_workbench_route_is_mirrored_without_touching_source(tmp_path: Path) -> None:
    source = tmp_path / "outside" / "source.png"
    target = tmp_path / "target"
    source.parent.mkdir()
    source.write_bytes(b"source-bytes")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    context = make_context(tmp_path, source, target)

    mirror = office_service._prepare_mirror_context(context)

    assert mirror.staged_files == 1
    assert (context.paths.input / source.name).read_bytes() == b"source-bytes"
    (context.paths.output / "result.txt").write_text("ok", encoding="utf-8")
    office_service._sync_destination(context, mirror)
    assert (target / "result.txt").read_text(encoding="utf-8") == "ok"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_unpinned_cached_source_reaches_operation_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from system_core.ui_nicegui import app as gui_app

    source = tmp_path / "external source"
    source.mkdir()
    target = tmp_path / "external target"
    target.mkdir()
    captured: dict[str, object] = {}
    remembered: list[tuple[str, str]] = []
    original_state = dict(gui_app.state)

    async def inline_io_bound(callback, *args, **kwargs):
        return callback(*args, **kwargs)

    def save_path(role: str, value: object) -> None:
        text = str(value)
        if role == "target":
            gui_app.state["destination_path"] = text
        else:
            gui_app.state["source_path"] = text

    def execute_probe(_paths, operation, *_args):
        captured["parameters"] = dict(operation.parameters)
        return SimpleNamespace(ok=True, message="ok")

    monkeypatch.setattr(gui_app.run, "io_bound", inline_io_bound)
    monkeypatch.setattr(
        gui_app,
        "WORKBENCH_ADAPTER",
        SimpleNamespace(remember_path=lambda role, value: remembered.append((role, str(value)))),
    )
    monkeypatch.setattr(gui_app, "save_workspace_path", save_path)
    monkeypatch.setattr(gui_app, "mark_workspace_feedback", lambda *_args: None)
    monkeypatch.setattr(gui_app, "add_log", lambda *_args: None)
    monkeypatch.setattr(gui_app, "reload_ui", lambda *_args: None)
    monkeypatch.setattr(gui_app, "safe_notify", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gui_app, "execute_operation", execute_probe)

    gui_app.state.update(
        {
            "running": False,
            "source_path": str(gui_app.paths.input),
            "destination_path": str(gui_app.paths.output),
        }
    )

    async def scenario() -> None:
        await gui_app.workspace_path_select_handler("source")(SimpleNamespace(value=str(source)))
        await gui_app.workspace_path_select_handler("target")(SimpleNamespace(value=str(target)))
        operation = Operation(
            id="cached_source_probe",
            title="Cached source probe",
            description="",
            service="tests:probe",
            kind="safe",
        )
        await gui_app.start_operation(operation)

    try:
        asyncio.run(scenario())
    finally:
        gui_app.state.clear()
        gui_app.state.update(original_state)

    parameters = captured["parameters"]
    assert isinstance(parameters, dict)
    assert parameters["_workbench_source_path"] == str(source)
    assert parameters["_workbench_target_path"] == str(target)
    assert remembered == [("source", str(source)), ("target", str(target))]


def test_workspace_delete_helpers_leave_the_folder_empty(tmp_path: Path) -> None:
    """A cleared input or output folder must be genuinely empty.

    .gitkeep used to survive a clear. It no longer does: the user opens these two
    folders and should not have to wonder what the leftover file is, or whether it
    is safe to delete. The folders themselves come from install/init_folders.cmd.
    """
    from system_core.ui_nicegui import app as gui_app

    folder = tmp_path / "managed"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    (folder / ".gitkeep").write_text("", encoding="utf-8")
    (folder / "remove.txt").write_text("remove", encoding="utf-8")
    (nested / "remove.txt").write_text("remove", encoding="utf-8")

    result = gui_app.delete_workspace_path_contents(folder)

    assert result["kind"] == "folder"
    assert result["removed"] == 3
    assert not (folder / ".gitkeep").exists()
    assert list(folder.iterdir()) == []


def test_cli_launchers_keep_identical_backend_dispatch() -> None:
    english = (PROJECT_ROOT / "launcher_project.cmd").read_text(encoding="utf-8")
    russian = (PROJECT_ROOT / "launcher_project_ru.cmd").read_text(encoding="utf-8")

    def dispatch_lines(text: str) -> list[str]:
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip().lower().startswith(("call :runpy", '"%python_cmd%"'))
        ]

    assert dispatch_lines(english) == dispatch_lines(russian)
    english_gotos = [line.strip() for line in english.splitlines() if line.strip().lower().startswith("if ") and " goto " in line.lower()]
    russian_gotos = [line.strip() for line in russian.splitlines() if line.strip().lower().startswith("if ") and " goto " in line.lower()]
    assert english_gotos == russian_gotos
    assert "cli_operation.py\" ocr_brick_run" in english
    assert "cli_operation.py\" ocr_brick_run" in russian


def test_cleanup_and_release_keep_repository_and_private_workspace_out_of_zip() -> None:
    cleanup = (PROJECT_ROOT / "cleanup_project.cmd").read_text(encoding="utf-8").lower()
    release = (PROJECT_ROOT / "install" / "make_release_archive.cmd").read_text(encoding="utf-8").lower()

    assert 'call :removedir "%base_dir%\\.git"' not in cleanup
    for protected in ("input", "output", "report", "workspace", "cache", "tmp", "._runtime"):
        assert f'"%root%\\{protected}"' in release
    for private_file in ("path_history.json", "yandex_key_id.txt", "yandex_folder.txt"):
        assert f'"{private_file}"' in release
    assert 'call "%stage_project%\\install\\init_folders.cmd"' in release


@pytest.mark.integration
def test_tesseract_documentmodel_smoke_from_external_workbench_file(tmp_path: Path) -> None:
    runtime = office_service._tesseract_exe(
        make_context(tmp_path, tmp_path / "placeholder.png", tmp_path / "placeholder-target")
    )
    if runtime == "tesseract" or not Path(runtime).is_file():
        pytest.skip("Portable Tesseract is not available")

    source = tmp_path / "external" / "short.png"
    target = tmp_path / "deliverables"
    source.parent.mkdir()
    image = Image.new("RGB", (1000, 220), "white")
    ImageDraw.Draw(image).text((40, 80), "AUDION OCR TEST 12345", fill="black")
    image.save(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    context = make_context(
        tmp_path,
        source,
        target,
        ocr_engine="tesseract",
        ocr_preprocess_profile="raw",
        ocr_output_contract="text",
        ocr_output_formats=["docx", "json", "markdown"],
        ocr_tesseract_lang="eng",
        ocr_tesseract_psm=6,
    )

    result = office_service.ocr_brick_run(context)

    assert result["exit_code"] == 0
    assert result["files"] == 1
    assert (context.paths.output / "short.document").is_dir()
    assert (context.paths.output / "short.docx").is_file()
    assert (context.paths.output / "short.document.json").is_file()
    assert (context.paths.output / "short.md").is_file()
    assert (target / "short.docx").is_file()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
