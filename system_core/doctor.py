from __future__ import annotations

from pathlib import Path
from typing import Any
import importlib
import os
import platform
import shutil
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from project_paths import BASE_DIR, OUTPUT_DIR
from system_core.core.tesseract_runtime import runtime_summary


REQUIRED_MODULES = [
    ("requests", "requests"),
    ("tqdm", "tqdm"),
    ("rich", "rich"),
    ("pydantic", "pydantic"),
    ("yaml", "pyyaml"),
    ("nicegui", "nicegui"),
    ("webview", "pywebview"),
    ("docx", "python-docx"),
    ("markitdown", "markitdown[all]"),
    ("markdown_it", "markdown-it-py"),
    ("openpyxl", "openpyxl"),
    ("numpy", "numpy"),
    ("PIL", "Pillow"),
    ("fitz", "pymupdf"),
    ("pptx", "python-pptx"),
]

OPTIONAL_MODULES = [
    ("google.genai", "google-genai"),
    ("openai", "openai"),
    ("win32com.client", "pywin32"),
    ("pytesseract", "pytesseract"),
    ("lxml", "lxml"),
]


ANSI_ENABLED = bool(
    os.environ.get("AUDION_GUI_TERMINAL")
    or os.environ.get("FORCE_COLOR")
    or os.environ.get("CLICOLOR_FORCE")
)


def ansi(text: str, sgr: str) -> str:
    if not ANSI_ENABLED:
        return text
    return f"\x1b[{sgr}m{text}\x1b[0m"


def section(text: str) -> str:
    return ansi(text, "1;36")


def status_marker(status: str, width: int = 4) -> str:
    normalized = status.upper()
    if normalized == "OK":
        color = "32"
    elif normalized == "MISS":
        color = "33"
    else:
        color = "31"
    return ansi(status.ljust(width), color)


def check_module(import_name: str) -> tuple[bool, str]:
    try:
        mod = importlib.import_module(import_name)
        version = getattr(mod, "__version__", "unknown")
        return True, str(version)
    except Exception as exc:
        return False, exc.__class__.__name__


def detect_python_mode(root: Path) -> str:
    if (root / "runtime" / "python.exe").exists():
        return "portable-runtime"
    if (root / "runtime" / "python" / "python.exe").exists():
        return "portable-runtime"
    if (root / "._runtime" / "python.exe").exists():
        return "template-portable-runtime"
    if (root / "._runtime" / "python" / "python.exe").exists():
        return "template-portable-runtime"
    return "system-python"


def check_picker_powershell(root: Path) -> tuple[bool, list[tuple[str, bool, str]]]:
    candidates = [
        ("portable pwsh", root / "system_core" / "powershell" / "pwsh.exe"),
        ("PATH pwsh", "pwsh.exe"),
        ("Windows PowerShell", "powershell.exe"),
    ]
    rows: list[tuple[str, bool, str]] = []
    any_ok = False
    for label, candidate in candidates:
        if isinstance(candidate, Path):
            ok = candidate.exists()
            detail = str(candidate)
        else:
            resolved = shutil.which(candidate)
            ok = bool(resolved)
            detail = resolved or "not found"
        rows.append((label, ok, detail))
        any_ok = any_ok or ok
    return any_ok, rows


def check_tesseract() -> tuple[bool, str]:
    return runtime_summary()


def check_manifest_operations(root: Path) -> tuple[bool, list[tuple[str, str, str]]]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from system_core.core.manifest import load_manifest  # noqa: WPS433
    except Exception as exc:
        return False, [("(loader)", "MANIFEST_FAIL", f"{exc.__class__.__name__}: {exc}")]

    manifest_path = root / "config" / "tool_manifest.yaml"
    if not manifest_path.exists():
        return False, [("(loader)", "MANIFEST_FAIL", f"Not found: {manifest_path}")]

    try:
        manifest = load_manifest(manifest_path)
    except Exception as exc:
        return False, [("(loader)", "MANIFEST_FAIL", f"{exc.__class__.__name__}: {exc}")]

    rows: list[tuple[str, str, str]] = []
    all_ok = True

    def collect_group_operations(nodes: list[Any]) -> list[Any]:
        operations: list[Any] = []
        for node in nodes:
            children = list(getattr(node, "children", ()) or ())
            if children:
                operations.extend(collect_group_operations(children))
            else:
                operations.append(node.to_operation(dict(getattr(node, "parameters", {}) or {})))
        return operations

    every_operation = [
        *manifest.operations,
        *collect_group_operations(manifest.operation_groups),
        *manifest.maintenance_operations,
    ]
    for op in every_operation:
        if ":" not in op.service:
            rows.append((op.id, "BAD_SYNTAX", op.service))
            all_ok = False
            continue

        module_name, function_name = op.service.split(":", 1)
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            rows.append((op.id, "IMPORT_FAIL", f"{module_name} ({exc.__class__.__name__}: {exc})"))
            all_ok = False
            continue

        if not hasattr(mod, function_name):
            rows.append((op.id, "MISSING_FUNC", f"{module_name}:{function_name}"))
            all_ok = False
            continue

        if not callable(getattr(mod, function_name)):
            rows.append((op.id, "NOT_CALLABLE", f"{module_name}:{function_name}"))
            all_ok = False
            continue

        rows.append((op.id, "OK", op.service))

    return all_ok, rows


def check_cmd_encoding(root: Path) -> tuple[bool, list[tuple[str, bool, str]]]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from system_core.core.cmd_encoding import check_cmd_files  # noqa: WPS433
    except Exception as exc:
        return False, [("(loader)", False, f"{exc.__class__.__name__}: {exc}")]

    rows: list[tuple[str, bool, str]] = []
    all_ok = True
    for result in check_cmd_files(root):
        try:
            relative = str(result.path.resolve().relative_to(root.resolve()))
        except ValueError:
            relative = str(result.path)

        detail = result.summary()
        if result.error:
            detail = f"{detail} {result.error}"
        rows.append((relative, result.ok, detail))
        if not result.ok:
            all_ok = False

    return all_ok, rows


def check_sh_lf(root: Path) -> tuple[bool, list[tuple[str, bool, str]]]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from system_core.core.sh_lf import check_sh_files  # noqa: WPS433
    except Exception as exc:
        return False, [("(loader)", False, f"{exc.__class__.__name__}: {exc}")]

    rows: list[tuple[str, bool, str]] = []
    all_ok = True
    for result in check_sh_files(root):
        try:
            relative = str(result.path.resolve().relative_to(root.resolve()))
        except ValueError:
            relative = str(result.path)

        detail = result.summary()
        if result.error:
            detail = f"{detail} {result.error}"
        rows.append((relative, result.ok, detail))
        if not result.ok:
            all_ok = False

    return all_ok, rows


def check_gui_theme_catalog(root: Path) -> tuple[bool, list[tuple[str, bool, str]]]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from system_core.core.config import load_yaml_or_json  # noqa: WPS433
        from system_core.core.ui_theme_catalog import validate_theme_catalog  # noqa: WPS433
    except Exception as exc:
        return False, [("(loader)", False, f"{exc.__class__.__name__}: {exc}")]

    try:
        data = load_yaml_or_json(root / "config" / "ui_colors.yaml")
    except Exception as exc:
        return False, [("catalog", False, f"{exc.__class__.__name__}: {exc}")]

    result = validate_theme_catalog(data)
    if not result.ok:
        return False, [("catalog", False, error) for error in result.errors]

    rows = [
        ("theme order", True, f"core prefix OK; {len(result.theme_ids)} theme(s)"),
        ("extension themes", True, ", ".join(result.extra_theme_ids) or "none"),
    ]
    return True, rows


def main() -> int:
    root = BASE_DIR

    print("======================================================================")
    print("AUDION OFFICE OCR AI - DOCTOR")
    print("======================================================================")
    print(f"Project root : {root}")
    print(f"Executable   : {sys.executable}")
    print(f"Python       : {sys.version.split()[0]}")
    print(f"Python mode  : {detect_python_mode(root)}")
    print(f"Platform     : {platform.platform()}")
    print()

    failed = False

    print(section("[Terminal encoding]"))
    print(f"  - {'UTF-8/Cyrillic':<18} : {status_marker('OK')} Кириллица")
    print(f"  - {'ANSI colors':<18} : {status_marker('OK' if ANSI_ENABLED else 'MISS')} {'enabled' if ANSI_ENABLED else 'plain text mode'}")
    print()

    print(section("[Required modules]"))
    for import_name, package_name in REQUIRED_MODULES:
        ok, detail = check_module(import_name)
        status = "OK" if ok else "FAIL"
        print(f"  - {package_name:<18} : {status_marker(status)} {detail}")
        if not ok:
            failed = True

    print()
    print(section("[Optional modules]"))
    for import_name, package_name in OPTIONAL_MODULES:
        ok, detail = check_module(import_name)
        status = "OK" if ok else "MISS"
        print(f"  - {package_name:<18} : {status_marker(status)} {detail}")

    tess_ok, tess_detail = check_tesseract()
    print(f"  - {'tesseract.exe':<18} : {status_marker('OK' if tess_ok else 'MISS')} {tess_detail}")

    print()
    print(section("[Project folders]"))
    for folder in (
        root / "input",
        OUTPUT_DIR,
        root / "report",
        root / "logs",
        root / "workspace",
        root / "data",
    ):
        exists = "OK" if folder.exists() else "MISS"
        print(f"  - {folder.relative_to(root)!s:<18} : {status_marker(exists)}")

    print()
    print(section("[GUI portability]"))
    picker_ok, picker_rows = check_picker_powershell(root)
    for label, ok, detail in picker_rows:
        status = "OK" if ok else "MISS"
        print(f"  - {label:<18} : {status_marker(status)} {detail}")
    if not picker_ok:
        print(f"  - picker dialogs     : {status_marker('FAIL')} PowerShell was not found")
        failed = True
    else:
        print(f"  - picker dialogs     : {status_marker('OK')} PowerShell-backed Windows dialogs available")

    print()
    print(section("[GUI themes]"))
    themes_ok, theme_rows = check_gui_theme_catalog(root)
    for label, ok, detail in theme_rows:
        status = "OK" if ok else "FAIL"
        print(f"  - {label:<18} : {status_marker(status)} {detail}")
    if not themes_ok:
        failed = True

    print()
    print(section("[Manifest operations]"))
    manifest_ok, rows = check_manifest_operations(root)
    if not rows:
        print("  (no operations found)")
    else:
        for op_id, status, detail in rows:
            print(f"  - {op_id:<28} : {status_marker(status, 13)} {detail}")
    if not manifest_ok:
        failed = True

    print()
    print(section("[CMD encoding]"))
    cmd_ok, cmd_rows = check_cmd_encoding(root)
    if not cmd_rows:
        print("  (no CMD files found)")
    else:
        for relative, result_ok, detail in cmd_rows:
            status = "OK" if result_ok else "FAIL"
            print(f"  - {relative:<58} : {status_marker(status)} {detail}")
    if not cmd_ok:
        failed = True

    print()
    print(section("[SH LF]"))
    sh_ok, sh_rows = check_sh_lf(root)
    if not sh_rows:
        print("  (no SH files found)")
    else:
        for relative, result_ok, detail in sh_rows:
            status = "OK" if result_ok else "FAIL"
            print(f"  - {relative:<58} : {status_marker(status)} {detail}")
    if not sh_ok:
        failed = True

    print()
    if failed:
        print(ansi("[RESULT] One or more checks failed.", "1;31"))
        return 1

    print(ansi("[RESULT] Required environment looks good.", "1;32"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
