# engines/yandex.py
# Yandex Vision OCR adapter. Two modes, selected by params["mode"]:
#   "sync"  -> recognizeText, one page per POST. Fits the standard recognize()
#              contract and returns {text, box, confidence}.
#   "batch" -> async pipeline via Object Storage + operation polling, for
#              thousands of pages. Exposed as a separate flow (run_batch), since
#              it is not a single-image call.
# Auth supports both api_key and IAM token (see yandex_creds).
# Endpoints/fields marked [VERIFY] against current Yandex Cloud docs at impl time.
# No globals; creds and HTTP client are injected/built from explicit paths.
# EN comments only. UTF-8 without BOM.  Requires: requests.

from __future__ import annotations

import base64
from pathlib import Path

import requests

from .base import OcrResult, Word
from .yandex_creds import YandexCreds

# [VERIFY] current endpoints. recognizeText is the sync OCR API.
_SYNC_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"
# batch uses vision batchAnalyze + Object Storage; wired in run_batch() stub.


class YandexAdapter:
    kind = "yandex"

    def __init__(self, creds: YandexCreds, timeout: float = 30.0) -> None:
        self.creds = creds
        self.timeout = timeout

    # -- standard single-image contract (sync mode) --

    def recognize(self, clean_png_path: str, params: dict) -> OcrResult:
        mode = params.get("mode", "sync")
        if mode != "sync":
            raise ValueError("YandexAdapter.recognize() is sync-only; "
                             "use run_batch() for batch mode")
        model = params.get("model", "page")          # page | handwritten | <specialized>
        langs = params.get("languageCodes", ["ru", "en"])
        content = base64.b64encode(Path(clean_png_path).read_bytes()).decode("ascii")

        body = {
            "mimeType": "PNG",
            "languageCodes": langs,
            "model": model,
            "content": content,
        }
        resp = requests.post(_SYNC_URL, headers=self.creds.headers(),
                             json=body, timeout=self.timeout)
        resp.raise_for_status()
        return self._parse_sync(resp.json())

    @staticmethod
    def _parse_sync(payload: dict) -> OcrResult:
        # Response groups text into blocks -> lines -> words, each with a
        # boundingBox of vertices. We flatten to words with (x, y, w, h).
        # [VERIFY] exact JSON path; current shape: result.textAnnotation.blocks[]
        words: list[Word] = []
        full_lines: list[str] = []
        ann = payload.get("textAnnotation") or (payload.get("result", {}) or {}).get("textAnnotation", {}) or {}
        for block in ann.get("blocks", []) or []:
            for line in block.get("lines", []) or []:
                full_lines.append(line.get("text", ""))
                for w in line.get("words", []) or []:
                    box = _verts_to_box(w.get("boundingBox", {}).get("vertices", []))
                    if box is None:
                        continue
                    # Yandex sync OCR does not always return per-word confidence;
                    # default to 1.0 unless present. [VERIFY]
                    conf = float(w.get("confidence", 1.0))
                    words.append(Word(text=w.get("text", ""), box=box, confidence=conf))
        text = ann.get("markdown") or ("\n".join(full_lines) if full_lines else ann.get("fullText", ""))
        return OcrResult(kind="yandex", text=text, words=words, engine="yandex")

    # -- batch mode (thousands of pages) --

    def run_batch(self, source_keys: list[str], bucket: str, params: dict) -> str:
        """Kick off async batch recognition over files already in Object Storage.
        Returns an operation/job id to poll. STUB: wire batchAnalyze + polling +
        result fetch from the bucket. See the Yandex 'yc-vision-ocr-recognizer'
        example (Object Storage in/out + timer-driven polling).
        TODO(codex): implement upload -> batchAnalyze -> poll operation_id ->
        download JSON results -> normalize to OcrResult per page."""
        raise NotImplementedError(
            "TODO(codex): implement Yandex async batch via Object Storage + "
            "batchAnalyze + operation polling for large jobs")


def _verts_to_box(vertices: list[dict]) -> tuple[int, int, int, int] | None:
    if not vertices:
        return None
    xs = [int(v.get("x", 0)) for v in vertices]
    ys = [int(v.get("y", 0)) for v in vertices]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return (x0, y0, x1 - x0, y1 - y0)
