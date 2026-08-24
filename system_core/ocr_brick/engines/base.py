# engines/base.py
# Engine adapter contract. Two output shapes, one dispatcher.
#   kind="ocr"/"yandex" -> word boxes (usable for searchable-PDF layer)
#   kind="vision"       -> free text, no boxes, may_rewrite flag
# Keep these separate; do NOT force vision into the box-bearing shape.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Protocol, runtime_checkable


@dataclass
class Word:
    text: str
    box: tuple[int, int, int, int]  # x, y, w, h
    confidence: float


@dataclass
class OcrResult:
    kind: str                       # "ocr" | "yandex" | "vision"
    text: str                       # full plain text (all engines provide this)
    words: list[Word] = field(default_factory=list)   # empty for vision
    may_rewrite: bool = False       # True for vision: text is not verbatim
    engine: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["words"] = [asdict(w) for w in self.words]
        return d

    @staticmethod
    def from_dict(d: dict) -> "OcrResult":
        words = [Word(text=w.get("text", ""),
                      box=tuple(int(x) for x in w["box"]),
                      confidence=float(w.get("confidence", 1.0)))
                 for w in d.get("words", []) if w.get("box")]
        return OcrResult(kind=d.get("kind", "ocr"), text=d.get("text", ""),
                         words=words, may_rewrite=bool(d.get("may_rewrite", False)),
                         engine=d.get("engine", ""))


@runtime_checkable
class EngineAdapter(Protocol):
    """Implementations receive a path to the CLEANED png and engine params."""
    kind: str

    def recognize(self, clean_png_path: str, params: dict) -> OcrResult: ...
