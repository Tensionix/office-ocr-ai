# engines/tesseract.py
# Milestone-1 adapter. Returns normalized word boxes from Tesseract.
# Uses the tesseract binary via list-based subprocess (TSV output) so we do not
# depend on a specific Python binding. Binary path is passed in, not assumed.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

import subprocess
from pathlib import Path

from .base import EngineAdapter, OcrResult, Word


class TesseractAdapter:
    kind = "ocr"

    def __init__(self, tesseract_exe: str | Path = "tesseract") -> None:
        # Default relies on PATH; the project should pass a portable path.
        self.exe = str(tesseract_exe)

    def recognize(self, clean_png_path: str, params: dict) -> OcrResult:
        lang = params.get("lang", "rus")
        psm = str(params.get("psm", 6))
        # TSV to stdout: tesseract <img> stdout -l rus --psm 6 tsv
        cmd = [self.exe, clean_png_path, "stdout", "-l", lang, "--psm", psm, "tsv"]
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
        words, text = self._parse_tsv(proc.stdout)
        return OcrResult(kind="ocr", text=text, words=words, engine="tesseract")

    @staticmethod
    def _parse_tsv(tsv: str) -> tuple[list[Word], str]:
        out: list[Word] = []
        line_words: dict[tuple[int, int, int], list[str]] = {}
        line_order: list[tuple[int, int, int]] = []
        for raw in tsv.splitlines()[1:]:
            cols = raw.split("\t", 11)
            if len(cols) < 12:
                continue
            (
                level,
                _page_num,
                block_num,
                par_num,
                line_num,
                _word_num,
                left,
                top,
                width,
                height,
                conf_raw,
                text,
            ) = cols
            if level != "5":
                continue
            txt = TesseractAdapter._clean_word_text(text)
            if not txt:
                continue
            try:
                conf = float(conf_raw)
                if conf < 0:
                    continue
                box = (int(left), int(top), int(width), int(height))
                key = (int(block_num), int(par_num), int(line_num))
            except ValueError:
                continue
            out.append(Word(text=txt, box=box, confidence=conf / 100.0))
            if key not in line_words:
                line_words[key] = []
                line_order.append(key)
            line_words[key].append(txt)
        text = "\n".join(" ".join(line_words[key]) for key in line_order if line_words.get(key))
        return out, text

    @staticmethod
    def _clean_word_text(text: str) -> str:
        # Tesseract TSV is tab-separated, not CSV; a recognized bare quote may
        # appear as `"2` and must not consume the following rows.
        txt = text.strip()
        if txt.startswith('"') and not txt.endswith('"'):
            txt = txt[1:].strip()
        if txt.endswith('"') and not txt.startswith('"'):
            txt = txt[:-1].strip()
        return txt


# static type check: adapter satisfies the protocol
_check: EngineAdapter = TesseractAdapter()
