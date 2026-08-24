from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import importlib
import json
import locale
import os
import subprocess
import time
import traceback

from .ansi import strip_ansi
from .logging_utils import append_log, timestamp
from .manifest import Operation
from .output_decode import decode_process_bytes
from .paths import ProjectPaths


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[float], None]
CancelCallback = Callable[[], bool]


@dataclass
class JobContext:
    paths: ProjectPaths
    operation: Operation
    log_file: Path
    report_dir: Path
    log_callback: LogCallback | None = None
    progress_callback: ProgressCallback | None = None
    cancel_callback: CancelCallback | None = None

    def log(self, message: str) -> None:
        append_log(self.log_file, strip_ansi(message))
        if self.log_callback:
            self.log_callback(message)

    def progress(self, value: float) -> None:
        if self.progress_callback:
            self.progress_callback(max(0.0, min(1.0, float(value))))

    def cancelled(self) -> bool:
        return bool(self.cancel_callback and self.cancel_callback())


@dataclass
class JobResult:
    ok: bool
    message: str
    data: dict[str, Any]


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    lines: tuple[str, ...]


SENSITIVE_PARAMETER_PARTS = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "apikey",
    "api_key",
    "access_key",
    "private_key",
    "credential",
)


def redact_parameters(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(part in lowered for part in SENSITIVE_PARAMETER_PARTS):
                result[key_text] = "***REDACTED***" if item not in {"", None} else item
                continue
            result[key_text] = redact_parameters(item)
        return result
    if isinstance(value, list):
        return [redact_parameters(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_parameters(item) for item in value)
    return value


def utf8_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("TERM", "xterm-256color")
    if extra:
        env.update(extra)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("NO_COLOR", None)
    env["CLICOLOR"] = "1"
    env["CLICOLOR_FORCE"] = "1"
    env["FORCE_COLOR"] = "1"
    env["AUDION_GUI_TERMINAL"] = "1"
    return env


def hidden_subprocess_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def hidden_subprocess_creationflags() -> int:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return int(subprocess.CREATE_NO_WINDOW)
    return 0


def hidden_subprocess_kwargs() -> dict[str, Any]:
    return {
        "startupinfo": hidden_subprocess_startupinfo(),
        "creationflags": hidden_subprocess_creationflags(),
    }


def format_command(command: list[str]) -> str:
    return " ".join(f'"{item}"' if " " in item else item for item in command)


def unbuffer_python_command(command: list[str]) -> list[str]:
    if not command:
        return command
    executable = Path(command[0]).name.lower()
    if executable not in {"python.exe", "pythonw.exe", "python", "python3", "py.exe", "py"}:
        return command
    if len(command) > 1 and command[1] == "-u":
        return command
    return [command[0], "-u", *command[1:]]


def is_python_command(command: list[str]) -> bool:
    if not command:
        return False
    return Path(command[0]).name.lower() in {"python.exe", "pythonw.exe", "python", "python3", "py.exe", "py"}


def _windows_codepage(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        value = int(getattr(ctypes.windll.kernel32, name)())
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    return f"cp{value}" if value > 0 else None


def _fallback_output_encodings() -> list[str]:
    candidates = [
        _windows_codepage("GetOEMCP"),
        "cp866",
        locale.getpreferredencoding(False),
        "mbcs" if os.name == "nt" else None,
        _windows_codepage("GetACP"),
        "cp1251",
    ]
    result: list[str] = []
    for encoding in candidates:
        if encoding and encoding.lower() not in {item.lower() for item in result}:
            result.append(encoding)
    return result


def _looks_utf16ish(data: bytes) -> bool:
    if len(data) < 4:
        return False
    sample = data[: min(len(data), 200)]
    even_nuls = sum(1 for index in range(0, len(sample), 2) if sample[index] == 0)
    odd_nuls = sum(1 for index in range(1, len(sample), 2) if sample[index] == 0)
    pairs = max(1, len(sample) // 2)
    return even_nuls / pairs > 0.35 or odd_nuls / pairs > 0.35


def _decode_score(text: str) -> int:
    score = 0
    for char in text:
        code = ord(char)
        if char in "\r\n\t":
            score += 1
        elif 32 <= code < 127:
            score += 1
        elif "А" <= char <= "я" or char in "Ёё":
            score += 8
        elif code == 0xFFFD:
            score -= 100
        elif code == 0:
            score -= 80
        elif code < 32:
            score -= 25
        elif 0x2500 <= code <= 0x257F:
            score -= 12
        elif 0x2E80 <= code <= 0x9FFF:
            score -= 20
    for marker in ("����", "㤠", "䠩", "Ð", "Ñ", "╨", "╤"):
        if marker in text:
            score -= 60
    return score


def _decode_with_candidates(data: bytes) -> list[str]:
    candidates: list[str] = []

    def add_candidate(encoding: str, *, errors: str = "strict") -> None:
        try:
            text = data.decode(encoding, errors=errors)
        except (LookupError, UnicodeDecodeError):
            return
        if text not in candidates:
            candidates.append(text)

    if data.startswith(b"\xef\xbb\xbf"):
        add_candidate("utf-8-sig")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        add_candidate("utf-16")
    add_candidate("utf-8")
    if _looks_utf16ish(data):
        add_candidate("utf-16")
        add_candidate("utf-16-le")
        add_candidate("utf-16-be")
    for encoding in _fallback_output_encodings():
        add_candidate(encoding)
    if not candidates:
        add_candidate("utf-8", errors="replace")
    return candidates


def decode_process_output(data: bytes) -> str:
    """Decode one bytes chunk from a non-Python Windows tool without mojibake."""
    return decode_process_bytes(data)


SPINNER_FRAME_CHARS = set("-\\|/ \t")


def _is_spinner_only_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and all(char in SPINNER_FRAME_CHARS for char in line)


def decoded_process_lines(raw_line: bytes | str) -> list[str]:
    text = str(raw_line) if isinstance(raw_line, str) else decode_process_bytes(raw_line)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for part in text.split("\n"):
        line = part.rstrip()
        if not line or _is_spinner_only_line(line):
            continue
        lines.append(line)
    return lines


def run_process(
    context: JobContext,
    command: list[str],
    *,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
    input_text: str | None = None,
    check: bool = True,
    progress_seconds: float = 600.0,
) -> ProcessResult:
    """Run a child process hidden, stream stdout/stderr into the GUI log."""
    if not command:
        raise ValueError("Command is empty.")
    command = unbuffer_python_command(command)
    python_command = is_python_command(command)

    working_dir = cwd or context.paths.root
    context.log(f"[CWD] {working_dir}")
    context.log(f"[CMD] {format_command(command)}")

    popen_kwargs: dict[str, Any] = {
        "cwd": str(working_dir),
        "stdin": subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "env": utf8_subprocess_env(extra_env),
        **hidden_subprocess_kwargs(),
    }
    if python_command:
        popen_kwargs.update({"text": True, "encoding": "utf-8", "errors": "replace"})
    process = subprocess.Popen(command, **popen_kwargs)
    if input_text is not None:
        assert process.stdin is not None
        if python_command:
            process.stdin.write(input_text)
        else:
            process.stdin.write(input_text.encode("utf-8"))
        process.stdin.close()

    lines: list[str] = []
    start = time.monotonic()
    last_progress = start

    assert process.stdout is not None
    for raw_line in process.stdout:
        if context.cancelled():
            context.log("[CANCEL] Terminating child process...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise RuntimeError("Operation cancelled by user.")

        for line in decoded_process_lines(raw_line):
            lines.append(line)
            context.log(line)

        now = time.monotonic()
        if now - last_progress >= 0.5:
            elapsed = max(0.0, now - start)
            context.progress(min(0.95, 0.08 + elapsed / max(1.0, float(progress_seconds))))
            last_progress = now

    exit_code = process.wait()
    context.log(f"[EXIT] {exit_code}")
    if check and exit_code != 0:
        raise RuntimeError(f"Command failed with exit code {exit_code}.")
    return ProcessResult(exit_code=exit_code, lines=tuple(lines))


def resolve_project_path(context: JobContext, raw_path: str) -> Path:
    path_text = raw_path.strip().strip('"')
    if not path_text:
        raise RuntimeError("Path field is empty.")
    path = Path(os.path.expandvars(path_text)).expanduser()
    if not path.is_absolute():
        path = context.paths.root / path
    return path


def run_cmd_script(
    context: JobContext,
    script: str,
    args: list[str] | None = None,
    *,
    check: bool = True,
) -> ProcessResult:
    script_path = resolve_project_path(context, script)
    if not script_path.exists():
        raise RuntimeError(f"Script was not found: {script_path}")
    command = ["cmd.exe", "/d", "/c", "call", str(script_path), *(args or [])]
    return run_process(context, command, cwd=context.paths.root, check=check)


def _load_callable(service: str) -> Callable[[JobContext], Any]:
    module_name, function_name = service.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def _write_result_report(context: JobContext, *, ok: bool, message: str, data: dict[str, Any]) -> None:
    payload = {
        "ok": ok,
        "message": message,
        "operation": {
            "id": context.operation.id,
            "title": context.operation.title,
            "parameters": redact_parameters(context.operation.parameters),
        },
        "log_file": str(context.log_file),
        "report_dir": str(context.report_dir),
        "data": redact_parameters(data),
    }
    try:
        context.report_dir.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        (context.report_dir / "result.json").write_text(text, encoding="utf-8")
        (context.paths.report / "latest_result.json").write_text(text, encoding="utf-8")
    except Exception as exc:
        context.log(f"[WARN] Failed to write report/result.json: {exc}")


def execute_operation(
    paths: ProjectPaths,
    operation: Operation,
    log_callback: LogCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> JobResult:
    run_stamp = timestamp().replace(":", "-")
    log_file = paths.logs / f"{run_stamp}_{operation.id}.log"
    report_dir = paths.report / f"{run_stamp}_{operation.id}"
    report_dir.mkdir(parents=True, exist_ok=True)
    context = JobContext(paths, operation, log_file, report_dir, log_callback, progress_callback, cancel_callback)

    try:
        context.log(f"Starting operation: {operation.id}")
        if operation.parameters:
            safe_parameters = redact_parameters(operation.parameters)
            context.log(f"Parameters: {json.dumps(safe_parameters, ensure_ascii=False, sort_keys=True)}")
        context.progress(0.0)
        result = _load_callable(operation.service)(context)
        context.progress(1.0)
        context.log(f"Finished operation: {operation.id}")

        if isinstance(result, dict):
            _write_result_report(context, ok=True, message="Operation finished.", data=result)
            return JobResult(True, "Operation finished.", result)
        message = str(result or "Operation finished.")
        _write_result_report(context, ok=True, message=message, data={})
        return JobResult(True, message, {})

    except Exception as exc:
        context.log(traceback.format_exc())
        message = f"{exc.__class__.__name__}: {exc}"
        _write_result_report(context, ok=False, message=message, data={})
        return JobResult(False, message, {})
