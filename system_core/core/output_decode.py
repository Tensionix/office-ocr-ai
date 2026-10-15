from __future__ import annotations

from dataclasses import dataclass
import codecs
import locale


MOJIBAKE_MARKERS = {
    "\ufffd",
    "Ð",
    "Ñ",
    "Ћ",
    "Ў",
    "Є",
    "Ґ",
    "¤",
    "©",
    "«",
    "»",
    "╨",
    "╤",
    "╬",
    "├",
    "┬",
}
UTF8_CYRILLIC_AS_CP866_MARKERS = {"╨", "╤"}

MOJIBAKE_SEQUENCES = (
    "Р°",
    "Р±",
    "РІ",
    "Рі",
    "Рґ",
    "Рµ",
    "Рё",
    "Р№",
    "Рє",
    "Р»",
    "Рј",
    "РЅ",
    "Рѕ",
    "Рї",
    "СЂ",
    "СЃ",
    "С‚",
    "Сѓ",
    "С„",
    "С…",
    "С†",
    "С‡",
    "С€",
    "С‰",
    "С‹",
    "СЊ",
    "СЌ",
    "СЋ",
    "СЏ",
    "С‘",
    "Р”",
    "Рџ",
    "РЎ",
    "Рњ",
    "Рќ",
    "Рћ",
    "Р­",
    "â€¦",
    "â€",
    "â„",
    "â€“",
    "â€”",
    "тА",
    "тВ",
    "тГ",
    "тД",
    "тЕ",
    "тЖ",
    "тЗ",
    "тИ",
    "тК",
    "тЛ",
    "тМ",
    "тН",
    "тО",
    "тП",
    "тР",
    "тС",
    "тТ",
    "тУ",
    "тФ",
    "тХ",
    "тЦ",
    "тЧ",
    "тШ",
    "тЩ",
    "тЪ",
    "тЫ",
    "тЬ",
    "тЭ",
    "тЮ",
    "тЯ",
)

COMMON_RUSSIAN = set("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя")


@dataclass(frozen=True)
class DecodeCandidate:
    text: str
    encoding: str
    score: int


def _candidate_encodings(data: bytes) -> list[str]:
    encodings: list[str] = []

    def add(encoding: str | None) -> None:
        if not encoding:
            return
        normalized = encoding.lower().replace("_", "-")
        if normalized not in encodings:
            encodings.append(normalized)

    add("utf-8")
    if _looks_utf16(data):
        add("utf-16")
        add("utf-16-le")
        add("utf-16-be")
    add("cp866")
    add(locale.getpreferredencoding(False))
    add(locale.getencoding() if hasattr(locale, "getencoding") else None)
    add("mbcs")
    add("cp1251")
    return encodings


def _looks_utf16(data: bytes) -> bool:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True
    if len(data) < 4:
        return False
    sample = data[: min(len(data), 200)]
    even_nuls = sample[0::2].count(0)
    odd_nuls = sample[1::2].count(0)
    return max(even_nuls, odd_nuls) >= max(2, len(sample) // 5)


def _score_text(text: str, encoding: str) -> int:
    score = 0
    if encoding == "utf-8":
        score += 20
    for char in text:
        code = ord(char)
        if char in COMMON_RUSSIAN:
            score += 8
        elif char.isascii() and (char.isprintable() or char in "\r\n\t"):
            score += 2
        elif _is_terminal_graphic(char):
            score += 30 if char not in MOJIBAKE_MARKERS else 0
        elif char.isprintable():
            score += 1
        if char in MOJIBAKE_MARKERS:
            score -= 60 if char in UTF8_CYRILLIC_AS_CP866_MARKERS else 20
        if code < 32 and char not in "\r\n\t":
            score -= 30
    score -= text.count("\x00") * 40
    score -= text.count("����") * 80
    for sequence in MOJIBAKE_SEQUENCES:
        score -= text.count(sequence) * 120
    return score


def _is_terminal_graphic(char: str) -> bool:
    code = ord(char)
    return (
        0x2500 <= code <= 0x257F
        or 0x2580 <= code <= 0x259F
        or 0x2800 <= code <= 0x28FF
    )


def decode_process_bytes(data: bytes) -> str:
    if not data:
        return ""

    candidates: list[DecodeCandidate] = []
    for encoding in _candidate_encodings(data):
        try:
            text = data.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
        candidates.append(DecodeCandidate(text, encoding, _score_text(text, encoding)))

    if candidates:
        return max(candidates, key=lambda candidate: candidate.score).text
    return data.decode("utf-8", errors="replace")


def _high_bytes(part: bytes) -> int:
    # The high byte of a character of UTF-16: NUL for a Latin letter, a space or a line end, 0x04 for Cyrillic.
    return part.count(0) + part.count(4)


def _looks_utf16(chunk: bytes) -> bool:
    """No single-byte text and no UTF-8 holds NUL, nor the byte 0x04 at every other place."""
    if b"\x00" in chunk:
        return True
    odd = chunk[1::2]
    return len(odd) >= 2 and odd.count(4) * 2 >= len(odd)


def _utf16_codec(chunk: bytes) -> str:
    """The UTF-16 a chunk is written in: by its byte order mark, else by where its high bytes stand."""
    if chunk.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    return "utf-16-le" if _high_bytes(chunk[1::2]) >= _high_bytes(chunk[0::2]) else "utf-16-be"


class ProcessText:
    """The text of a child process from the chunks a pipe gives, each ending at the byte \\n.

    A chunk with a NUL byte, or with 0x04 at every other place (the high byte of Cyrillic), is
    UTF-16: no single-byte text and no UTF-8 holds them. From it on the
    bytes go to one UTF-16 decoder - a cut at the byte \\n splits a character of two bytes, and
    decoded chunk by chunk every line after the first came out as rubbish. A chunk without NUL
    that does not finish a character of UTF-16 ends that stretch: a script may run one program
    after another, and the next one writes its own way. Any other chunk is decoded by itself, by
    its best encoding (decode_process_bytes): UTF-8, the OEM page (cp866), the ANSI one (cp1251).
    A byte order mark of UTF-8 or UTF-16 is not text and is dropped.
    """

    def __init__(self) -> None:
        self._utf16: codecs.IncrementalDecoder | None = None

    def feed(self, chunk: bytes) -> str:
        if not chunk:
            return ""
        text = ""
        if self._utf16 is not None:
            # Half a character waits from the last chunk: the line end of UTF-16 is two bytes, and
            # the pipe cut after the first.
            if len(self._utf16.getstate()[0]) % 2:
                text += self._utf16.decode(chunk[:1])
                chunk = chunk[1:]
            if not chunk:
                return text
            if _looks_utf16(chunk) or self._utf16.getstate()[0]:
                return text + self._utf16.decode(chunk)
            text += self._utf16.decode(b"", final=True)
            self._utf16 = None
        if _looks_utf16(chunk):
            self._utf16 = codecs.getincrementaldecoder(_utf16_codec(chunk))(errors="replace")
            return text + self._utf16.decode(chunk).lstrip("﻿")
        return text + decode_process_bytes(chunk).lstrip("﻿")

    def close(self) -> str:
        """What the decoder still holds once the stream has ended."""
        if self._utf16 is None:
            return ""
        rest, self._utf16 = self._utf16.decode(b"", final=True), None
        return rest
