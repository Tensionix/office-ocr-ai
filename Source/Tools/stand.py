"""The stand of the window: a Debug window without a screen and a door that only pretends.

    runtime\\python.exe Source\\Tools\\stand.py

It starts `Source\\bin\\Debug\\net10.0\\AudionOfficeOcrAi.exe -Stand <folder>` (build it first:
`dotnet build Source\\AudionOfficeOcrAi.csproj -c Debug`), waits for it and prints what the window
saw - a run, STOP by the signal, a forced STOP after its term, a command that left a process
behind, a tool left running on purpose (Source\\MainWindow.Stand.cs). Then it looks at the one
thing the window cannot see: whether the tool left on its own is alive once the window is gone.
Everything the stand left running is ended here, by the ids the processes wrote themselves.

The folder of the stand is a temporary one outside the program; nothing of the program is
written to. The exit code is 0 when every check passed, 1 otherwise.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WINDOW = ROOT / "Source" / "bin" / "Debug" / "net10.0" / "AudionOfficeOcrAi.exe"
STOP_WAIT = 3  # seconds the window waits for an operation asked to stop before it ends it

kernel32 = ctypes.windll.kernel32 if os.name == "nt" else None


def alive(pid: int) -> bool:
    """Whether a process of that id runs now."""
    if pid <= 0 or kernel32 is None:
        return False
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def left(folder: Path) -> dict[str, int]:
    """The processes the stand left behind, by the ids they wrote themselves."""
    found: dict[str, int] = {}
    for file in folder.glob("left-*.pid"):
        try:
            found[file.stem.removeprefix("left-")] = int(file.read_text(encoding="utf-8").strip())
        except ValueError:
            pass
    return found


def main() -> int:
    if not WINDOW.is_file():
        print(f"the Debug window is not built: {WINDOW}")
        return 1
    folder = Path(tempfile.mkdtemp(prefix="audion-get-stand-"))
    lines: list[str] = []
    try:
        environment = dict(os.environ, AUDION_STOP_WAIT=str(STOP_WAIT))
        started = time.monotonic()
        try:
            window = subprocess.run([str(WINDOW), "-Stand", str(folder)], cwd=ROOT, env=environment, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=300)
            code, errors = window.returncode, window.stderr.strip()
        except subprocess.TimeoutExpired:
            code, errors = -1, "the window did not end in 300 s"
        report = folder / "stand.txt"
        lines = report.read_text(encoding="utf-8").splitlines() if report.is_file() else ["FAIL the window wrote no report"]
        if errors:
            lines.append("FAIL the window said on its error stream: " + errors.replace("\n", " | ")[:600])
        if code != 0 and not any(line.startswith("FAIL") for line in lines):
            lines.append(f"FAIL the window ended with {code}")

        # The window is gone, and its job with it: what asked to leave the job lives on, the rest does not.
        time.sleep(1.5)
        pids = left(folder)
        leaver = pids.get("leaver", 0)
        lines.append(("ok   " if alive(leaver) else "FAIL ") + f"tool on its own: it is alive after the window is gone (pid {leaver})")
        for name in ("orphan", "deaf"):
            if name in pids:
                lines.append(("FAIL " if alive(pids[name]) else "ok   ") + f"the window is gone: nothing of '{name}' is left running (pid {pids[name]})")
        for line in lines:
            print(line)
        failed = sum(1 for line in lines if line.startswith("FAIL"))
        print(f"{len(lines) - failed} of {len(lines)} checks passed, {time.monotonic() - started:.0f} s")
        return 1 if failed else 0
    finally:
        for pid in left(folder).values():
            if alive(pid):
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
