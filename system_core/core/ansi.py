"""Escape sequences out of a line of a child process: what the journal and the result keep is text.

The window draws the colours itself (Source\\Core\\Ansi.cs) from the lines the console command passes on
with --colours; here they are only taken away.
"""

from __future__ import annotations

import re

# A pipe can swallow the escape and leave the rest of an SGR sequence behind.
# "[36m" is noise; "[OK]" is text, and the final "m" is what tells them apart.
ORPHAN_SGR = re.compile(r"\[[0-9;]*m")


def _consume_escape(text: str, index: int) -> tuple[int, tuple[str, str, str] | None]:
    end = len(text)
    if index + 1 >= end:
        return index + 1, None

    marker = text[index + 1]
    if marker == "[":
        cursor = index + 2
        while cursor < end and not ("@" <= text[cursor] <= "~"):
            cursor += 1
        if cursor >= end:
            return end, None
        return cursor + 1, ("csi", text[index + 2 : cursor], text[cursor])

    if marker == "]":
        cursor = index + 2
        while cursor < end:
            if text[cursor] == "\x07":
                return cursor + 1, None
            if text[cursor] == "\x1b" and cursor + 1 < end and text[cursor + 1] == "\\":
                return cursor + 2, None
            cursor += 1
        return end, None

    return min(index + 2, end), None


def _is_control_char(char: str) -> bool:
    code = ord(char)
    if char in "\n\t":
        return False
    return code < 32 or code == 127 or 128 <= code <= 159


def strip_ansi(text: str) -> str:
    """Remove ANSI/OSC/control escapes while keeping printable Unicode text."""
    source = str(text)
    result: list[str] = []
    cursor = 0
    length = len(source)

    while cursor < length:
        char = source[cursor]
        if char == "\x1b":
            cursor, _event = _consume_escape(source, cursor)
            continue
        if _is_control_char(char):
            cursor += 1
            continue
        result.append(char)
        cursor += 1

    return ORPHAN_SGR.sub("", "".join(result))
