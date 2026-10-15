"""The watchman of the dictionary of the window: every Russian text the window shows has its English pair.

    runtime\\python.exe Source\\Tools\\check_i18n.py            the check: exit code 1 when a pair is missing
    runtime\\python.exe Source\\Tools\\check_i18n.py --list     every Russian text found, one a line

The window is written in Russian and speaks English by `Source\\config\\i18n.json` (Core\\Lang.cs):
a text is looked up where it is shown. So a text with no pair is shown in Russian in the English
window, and nothing fails - this script is what fails. It reads the sources themselves:

  - every string of the C# files of the window that holds a Cyrillic letter - the texts of
    `Lang.T`, `Lang.F`, `SetStatus`, of the questions, of the sheets SETTINGS and ABOUT;
  - every attribute of the markup (`*.axaml`) that holds one - names, tooltips, placeholders.

A text is paired when the dictionary has it word for word, or one of its templates (`... {0} ...`)
matches it - the way Lang.T looks it up. A text of several lines is paired line by line.

Not read: comments; `Core\\SystemInfo.cs`, whose badges of the machine carry both languages their
own way; `Core\\SelfTest.cs`, whose Russian words are data of the checks, never shown;
`Views\\PixelGrid.cs`, whose two Russian strings are the letters a font is measured by, drawn on a
picture nobody sees.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
DICTIONARY = SOURCE / "config" / "i18n.json"
SKIPPED = {Path("Core") / "SystemInfo.cs", Path("Core") / "SelfTest.cs", Path("Views") / "PixelGrid.cs"}
CYRILLIC = re.compile("[А-Яа-яЁё]")

# A C# string: raw (three quotes), verbatim (@"..."), or usual with its escapes; an interpolated one keeps its $.
STRING = re.compile(r'(?P<raw>\$?"""(?P<rawtext>.*?)""")|(?P<verbatim>\$?@"(?P<verbatimtext>(?:[^"]|"")*)")|(?P<usual>\$?"(?P<usualtext>(?:[^"\\\n]|\\.)*)")', re.DOTALL)
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "0": "\0", "'": "'"}


def strip_comments(code: str) -> str:
    """The code without its comments: a `//` inside a string is no comment."""
    out: list[str] = []
    at = 0
    while at < len(code):
        match = STRING.match(code, at)
        if match:
            out.append(match.group(0))
            at = match.end()
        elif code.startswith("//", at):
            end = code.find("\n", at)
            at = len(code) if end < 0 else end
        elif code.startswith("/*", at):
            end = code.find("*/", at)
            at = len(code) if end < 0 else end + 2
        else:
            out.append(code[at])
            at += 1
    return "".join(out)


def unescape(text: str) -> str:
    def swap(match: re.Match[str]) -> str:
        code = match.group(1)
        if code[0] == "u":
            return chr(int(code[1:], 16))
        return ESCAPES.get(code, code)

    return re.sub(r"\\(u[0-9a-fA-F]{4}|.)", swap, text)


def csharp_texts(file: Path) -> list[str]:
    found: list[str] = []
    for match in STRING.finditer(strip_comments(file.read_text(encoding="utf-8-sig"))):
        whole = match.group(0)
        if match.group("raw"):
            text = match.group("rawtext")
        elif match.group("verbatim"):
            text = match.group("verbatimtext").replace('""', '"')
        else:
            text = unescape(match.group("usualtext"))
        if whole.startswith("$"):
            # An interpolated string is its template: each hole is a place of a value.
            holes = iter(range(100))
            text = re.sub(r"\{[^{}]*\}", lambda _hole: "{" + str(next(holes)) + "}", text)
        if CYRILLIC.search(text):
            found.append(text)
    return found


def markup_texts(file: Path) -> list[str]:
    text = re.sub(r"<!--.*?-->", "", file.read_text(encoding="utf-8-sig"), flags=re.DOTALL)
    values = re.findall(r'[\w.:]+="([^"]*)"', text)
    unescaped = [value.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#x0a;", "\n").replace("&#10;", "\n") for value in values]
    return [value for value in unescaped if CYRILLIC.search(value)]


def shown() -> dict[str, list[str]]:
    """Every Russian text of the window - where it stands."""
    texts: dict[str, list[str]] = {}
    for file in sorted(SOURCE.rglob("*")):
        relative = file.relative_to(SOURCE)
        if not file.is_file() or relative.parts[0] in {"bin", "obj", "Tools", "Ps"} or relative in SKIPPED:
            continue
        if file.suffix == ".cs":
            found = csharp_texts(file)
        elif file.suffix == ".axaml":
            found = markup_texts(file)
        else:
            continue
        for text in found:
            texts.setdefault(text, []).append(str(relative))
    return texts


class Pairs:
    """The dictionary as Lang.T reads it: texts word for word, and templates with holes."""

    def __init__(self, entries: dict[str, dict[str, str]]) -> None:
        self.exact = {key for key in entries if not re.search(r"\{\d+\}", key)}
        self.templates = []
        for key in entries:
            if key in self.exact:
                continue
            parts = [re.escape(part) for part in re.split(r"\{\d+\}", key)]
            pattern = "^" + parts[0] + "".join(("(.+)" if index == 0 else "(.+?)") + part for index, part in enumerate(parts[1:])) + "$"
            self.templates.append(re.compile(pattern, re.DOTALL))

    def has(self, text: str, depth: int = 0) -> bool:
        if not CYRILLIC.search(text) or text in self.exact:
            return True
        if any(template.match(text) for template in self.templates):
            return True
        # Several lines - a tooltip: each line on its own.
        return depth < 3 and "\n" in text and all(self.has(line, depth + 1) for line in text.split("\n"))


def problems() -> list[str]:
    try:
        entries = json.loads(DICTIONARY.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        return [f"the dictionary does not read: {error}"]
    found: list[str] = []
    for key, pair in entries.items():
        english = pair.get("en") if isinstance(pair, dict) else None
        if not isinstance(english, str) or not english.strip():
            found.append(f"no English text for: {key!r}")
        elif CYRILLIC.search(english):
            found.append(f"the English text holds Russian letters: {key!r}")
        elif sorted(re.findall(r"\{\d+\}", key)) != sorted(re.findall(r"\{\d+\}", english)):
            found.append(f"the holes of the pair differ: {key!r}")
    pairs = Pairs(entries)
    for text, places in shown().items():
        if not pairs.has(text):
            found.append(f"no pair: {text!r}  ({', '.join(sorted(set(places)))})")
    return found


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for text, places in shown().items():
            print(json.dumps(text, ensure_ascii=False) + "  " + ", ".join(sorted(set(places))))
        return 0
    found = problems()
    for line in found:
        print(line)
    print(f"{len(shown())} Russian texts of the window, without a pair or wrong: {len(found)}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
