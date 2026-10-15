"""The door of a stand: it answers the window in place of system_core\\cli.py.

A Debug window started with `-Stand <folder>` calls this script instead of the door of the
program (Source\\Core\\Paths.cs, StandDoor). It describes a program of one page whose operations
install and download nothing - each behaves in one way a window has to cope with:

    stand_quick     says a few lines, on both streams, and ends well
    stand_secret    asks for a value before it runs (`prompt`, a secret) and reads it from its
                    standard input; it says how long the value is, never the value
    stand_obedient  waits for the stop file and leaves by itself - STOP by the signal
    stand_deaf      never looks at the stop file - STOP has to end it after its term
    stand_orphan    ends well and leaves a process behind that holds its output open
    stand_leaver    ends well and leaves a tool running on purpose, started the way the engine
                    starts WinUtil (external_tools_service.start_on_its_own)

A process left behind writes its id into `<folder>\\left-<name>.pid` and ends by itself after two
minutes: nothing of a stand outlives it for long, whoever forgets to clear up.

The words are the door's own: `describe`, `run --operation ... --params ... --result ...
--cancel-file ...`, and the service lines of a run (`::get::{...}`).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL = "::ocr::"
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_STOPPED = 0, 1, 2, 130
LEFT_LIVES = 120  # seconds a process left behind lives when nobody ends it

OPERATIONS = {
    "stand_quick": ("Quick run", "Быстрый запуск"),
    "stand_secret": ("Asks for a value", "Спрашивает значение"),
    "stand_obedient": ("Stops by the signal", "Останавливается по сигналу"),
    "stand_deaf": ("Does not hear STOP", "Не слышит СТОП"),
    "stand_orphan": ("Leaves a process behind", "Оставляет процесс"),
    "stand_leaver": ("Leaves a tool on its own", "Оставляет программу на воле"),
}


def stand() -> Path:
    """The folder of the stand: the window names it to everything it starts."""
    folder = Path(os.environ.get("AUDION_STAND_FOLDER") or (Path(__file__).resolve().parent / "._stand"))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def say(line: str) -> None:
    print(line, flush=True)


def control(payload: dict) -> None:
    say(CONTROL + json.dumps(payload, ensure_ascii=False))


def describe() -> int:
    folder = stand()
    places = [{
        "id": name, "title": title, "title_ru": title_ru, "description": "", "description_ru": "", "tooltip": "", "tooltip_ru": "",
        "kind": "safe", "icon": "", "tone": "", "block": "Stand", "block_ru": "Стенд", "beside": "", "runs": True, "direct": True,
        "prompt": "", "parameters": {}, "fields": [],
    } for name, (title, title_ru) in OPERATIONS.items()]
    asking = next(place for place in places if place["id"] == "stand_secret")
    asking["prompt"] = "stand_token"
    asking["parameters"] = {"prompt": {
        "field": "stand_token", "secret": True, "title": "Stand token", "title_ru": "Токен стенда",
        "label": "A value nobody else must see", "label_ru": "Значение, которое никто не должен видеть",
        "hint": "Leave the field empty to remove the stored one.", "hint_ru": "Пустое поле удаляет сохранённое.",
        "ok": "Save", "ok_ru": "Сохранить",
    }}
    told = {
        "version": "stand",
        "paths": {key: str(folder / key) for key in ("input", "output", "logs", "report", "config")} | {"root": str(folder)},
        "layout": {
            "sections": [{
                "id": "stand", "title": "Stand", "title_ru": "Стенд", "icon": "", "about": "", "about_ru": "",
                "pages": [{"id": "runs", "title": "Runs", "title_ru": "Запуски", "icon": "", "about": "", "about_ru": "", "fixed": {}, "operations": places}],
            }],
            "service": [],
        },
        "card_operations": [],
    }
    say(json.dumps(told, ensure_ascii=False))
    return EXIT_OK


def pid_file(name: str) -> Path:
    return stand() / f"left-{name}.pid"


def left(name: str) -> int:
    """A process left behind: it names itself and waits to be ended, not for ever."""
    pid_file(name).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(LEFT_LIVES)
    return EXIT_OK


def wait_for(file: Path, seconds: float) -> bool:
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if file.exists() and file.read_text(encoding="utf-8").strip():
            return True
        time.sleep(0.05)
    return False


def finish(outcome: str, message: str, code: int) -> int:
    control({"finished": {"outcome": outcome, "message": message, "seconds": 0}})
    return code


def run(operation: str, cancel_file: Path | None, secret: str = "", params: str = "") -> int:
    if operation not in OPERATIONS:
        print(f"unknown operation: {operation}", file=sys.stderr, flush=True)
        return EXIT_USAGE
    control({"started": {"operation": operation, "source": "", "target": ""}})
    control({"progress": 0})
    name = operation.removeprefix("stand_")
    myself = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "left", name]

    if name == "quick":
        for number in (1, 2, 3):
            say(f"quick: line {number}")
            control({"progress": number / 3})
        control({"activity": "quick: at work"})
        # The error stream: a line that names itself an error already, and a plain word.
        print("[ERR] quick: an error line of the operation itself", file=sys.stderr, flush=True)
        print("quick: a plain word on the error stream", file=sys.stderr, flush=True)
        say("\x1b[32m[OK] quick: a line in its writer's colour\x1b[0m")
        return finish("done", "", EXIT_OK)

    if name == "secret":
        if secret != "stand_token":
            print(f"secret: the value was to come by the standard input under the name stand_token, got {secret!r}", file=sys.stderr, flush=True)
            return finish("failed", "no value named", EXIT_FAILED)
        value = sys.stdin.readline().rstrip("\r\n")
        say(f"secret: got {len(value)} characters")
        # The file of the values of the run must not hold it.
        held = bool(value) and bool(params) and value in Path(params).read_text(encoding="utf-8-sig", errors="replace")
        say(f"secret: the file of the values holds it: {held}")
        return finish("done", "", EXIT_OK)

    if name == "obedient":
        say("obedient: waiting for the stop file")
        until = time.monotonic() + 60
        while time.monotonic() < until:
            if cancel_file is not None and cancel_file.exists():
                say("obedient: saw the stop file, leaving")
                return finish("stopped", "", EXIT_STOPPED)
            time.sleep(0.1)
        return finish("failed", "nobody asked to stop", EXIT_FAILED)

    if name == "deaf":
        pid_file("deaf").write_text(str(os.getpid()), encoding="utf-8")
        say("deaf: working, and not looking at the stop file")
        time.sleep(LEFT_LIVES)
        return finish("failed", "nobody ended it", EXIT_FAILED)

    if name == "orphan":
        # The child takes the streams of this process: they stay open after it has ended.
        subprocess.Popen(myself, stdout=sys.stdout, stderr=sys.stderr, cwd=str(ROOT))
        say("orphan: started a process that holds this output open" if wait_for(pid_file("orphan"), 10) else "orphan: the process did not come up")
        return finish("done", "", EXIT_OK)

    # leaver: the engine's own way of leaving a tool running (WinUtil is started so).
    sys.path.insert(0, str(ROOT))
    from system_core.services import external_tools_service as tools

    class Log:
        def log(self, message: str) -> None:
            say(message)

    tools.start_on_its_own(Log(), myself, cwd=ROOT, console=False)
    say("leaver: started a tool on its own" if wait_for(pid_file("leaver"), 10) else "leaver: the tool did not come up")
    return finish("done", "", EXIT_OK)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="stand_door")
    parser.add_argument("--language", default="en")
    words = parser.add_subparsers(dest="word", required=True)
    words.add_parser("describe")
    started = words.add_parser("run")
    started.add_argument("--operation", required=True)
    started.add_argument("--target", default="")
    started.add_argument("--source", default="")
    started.add_argument("--params", default="")
    started.add_argument("--result", default="")
    started.add_argument("--cancel-file", default="")
    started.add_argument("--colours", action="store_true")
    started.add_argument("--secret-stdin", default="")
    kept = words.add_parser("left")
    kept.add_argument("name")
    args = parser.parse_args(argv)
    if args.word == "describe":
        return describe()
    if args.word == "left":
        return left(args.name)
    return run(args.operation, Path(args.cancel_file) if args.cancel_file else None, args.secret_stdin, args.params)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
