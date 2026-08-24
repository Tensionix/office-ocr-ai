from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

try:
    from system_core.project_paths import BASE_DIR, TESSDATA_DIR, TESSERACT_DIR, TESSERACT_EXE
except Exception:  # pragma: no cover - direct script fallback
    from project_paths import BASE_DIR, TESSDATA_DIR, TESSERACT_DIR, TESSERACT_EXE  # type: ignore


ENV_TESSERACT_EXE = "AUDION_TESSERACT_EXE"
OPTIONAL_INSTALL_COMMAND = r"install\Install-Portable-Tesseract.cmd"
DEFAULT_LANGUAGES = ("eng", "rus", "deu", "osd")


@dataclass(frozen=True)
class TesseractRuntime:
    available: bool
    source: str
    exe: Path | None
    tessdata_dir: Path | None
    note: str


def _existing_file(path: Path | None) -> Path | None:
    if path and path.exists() and path.is_file():
        return path.resolve()
    return None


def _tessdata_from_env() -> Path | None:
    raw = os.environ.get("TESSDATA_PREFIX", "").strip()
    if not raw:
        return None
    path = Path(raw)
    candidates = [path]
    if path.name.lower() != "tessdata":
        candidates.insert(0, path / "tessdata")
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()
    return None


def tessdata_dir_for(exe: Path | None) -> Path | None:
    if exe:
        candidate = exe.parent / "tessdata"
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()
    return _tessdata_from_env()


def resolve_tesseract_runtime() -> TesseractRuntime:
    candidates: list[tuple[str, Path | None, str]] = [
        ("portable", _existing_file(TESSERACT_EXE), str(TESSERACT_EXE)),
        ("env", _existing_file(Path(os.environ.get(ENV_TESSERACT_EXE, ""))), ENV_TESSERACT_EXE),
    ]

    path_exe = shutil.which("tesseract")
    candidates.append(("PATH", Path(path_exe).resolve() if path_exe else None, "PATH"))

    missing: list[str] = []
    for source, exe, label in candidates:
        if not exe:
            missing.append(label)
            continue
        tessdata_dir = tessdata_dir_for(exe)
        return TesseractRuntime(
            available=True,
            source=source,
            exe=exe,
            tessdata_dir=tessdata_dir,
            note=f"{source}: {exe}",
        )

    return TesseractRuntime(
        available=False,
        source="missing",
        exe=None,
        tessdata_dir=None,
        note=(
            "Tesseract not found; local Workbench OCR is limited. "
            f"Install optional portable component with {OPTIONAL_INSTALL_COMMAND}. "
            "Checked " + ", ".join(missing)
        ),
    )


def tesseract_env(runtime: TesseractRuntime | None = None, base_env: dict[str, str] | None = None) -> dict[str, str]:
    runtime = runtime or resolve_tesseract_runtime()
    env = dict(base_env or os.environ)
    if runtime.exe:
        env[ENV_TESSERACT_EXE] = str(runtime.exe)
        env["PATH"] = str(runtime.exe.parent) + os.pathsep + env.get("PATH", "")
    if runtime.tessdata_dir:
        env["TESSDATA_PREFIX"] = str(runtime.tessdata_dir)
    return env


def configure_pytesseract(runtime: TesseractRuntime | None = None) -> TesseractRuntime:
    runtime = runtime or resolve_tesseract_runtime()
    if not runtime.available or not runtime.exe:
        raise RuntimeError(runtime.note)
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = str(runtime.exe)
    if runtime.tessdata_dir:
        os.environ["TESSDATA_PREFIX"] = str(runtime.tessdata_dir)
    return runtime


def pytesseract_config(*, psm: int, oem: int) -> str:
    runtime = resolve_tesseract_runtime()
    parts: list[str] = []
    parts.extend([f"--psm {int(psm)}", f"--oem {int(oem)}", "-c preserve_interword_spaces=1"])
    return " ".join(parts)


def _hidden_subprocess_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {"startupinfo": startupinfo, "creationflags": subprocess.CREATE_NO_WINDOW}


def _decode_output(data: bytes) -> list[str]:
    for encoding in ("utf-8", "cp866", "cp1251", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def tesseract_version(runtime: TesseractRuntime | None = None) -> str:
    runtime = runtime or resolve_tesseract_runtime()
    if not runtime.available or not runtime.exe:
        return runtime.note
    try:
        result = subprocess.run(
            [str(runtime.exe), "--version"],
            capture_output=True,
            timeout=10,
            check=False,
            env=tesseract_env(runtime),
            **_hidden_subprocess_kwargs(),
        )
        lines = _decode_output(result.stdout or result.stderr)
        return lines[0] if lines else f"exit code {result.returncode}"
    except Exception as exc:
        return f"{exc.__class__.__name__}: {exc}"


def tesseract_languages(runtime: TesseractRuntime | None = None) -> list[str]:
    runtime = runtime or resolve_tesseract_runtime()
    if not runtime.available or not runtime.exe:
        return []
    try:
        command = [str(runtime.exe), "--list-langs"]
        if runtime.tessdata_dir:
            command.extend(["--tessdata-dir", str(runtime.tessdata_dir)])
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=10,
            check=False,
            env=tesseract_env(runtime),
            **_hidden_subprocess_kwargs(),
        )
        lines = _decode_output(result.stdout or result.stderr)
    except Exception:
        return []
    languages: list[str] = []
    for line in lines:
        if not line or line.lower().startswith("list of available languages"):
            continue
        if line.lower().startswith("tessdata/"):
            line = line.split("/", 1)[1]
        languages.append(line)
    return sorted(languages)


def missing_default_languages(runtime: TesseractRuntime | None = None) -> list[str]:
    available = set(tesseract_languages(runtime))
    return [lang for lang in DEFAULT_LANGUAGES if lang not in available]


def runtime_summary() -> tuple[bool, str]:
    runtime = resolve_tesseract_runtime()
    if not runtime.available:
        return False, runtime.note
    version = tesseract_version(runtime)
    languages = tesseract_languages(runtime)
    missing = missing_default_languages(runtime)
    language_note = ",".join(languages) if languages else "languages unavailable"
    if missing:
        language_note += f" (missing default: {','.join(missing)})"
    tessdata_note = f", tessdata={runtime.tessdata_dir}" if runtime.tessdata_dir else ""
    return True, f"{runtime.source}: {runtime.exe} ({version}; {language_note}{tessdata_note})"
