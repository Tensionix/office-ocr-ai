# engines/service_client.py
# Client for the warm layout service (Surya hosted once over 127.0.0.1).
# Duck-types the adapter interface (recognize / analyze_layout / provides_layout)
# so the controller treats local adapters and remote heavy engines uniformly.
# No globals; base_url + engine passed in. EN comments only. UTF-8 without BOM.
# Requires: requests.

from __future__ import annotations

import base64
from pathlib import Path

import requests

from .base import OcrResult
from .regions import LayoutResult, layout_from_dict


class HeavyEngineClient:
    """Talks to layout_service for a heavy engine (e.g. 'surya')."""
    provides_layout = True
    kind = "ocr"

    def __init__(self, base_url: str, engine: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.engine = engine
        self.timeout = timeout

    def _post(self, path: str, png_path: str, extra: dict) -> dict:
        b64 = base64.b64encode(Path(png_path).read_bytes()).decode("ascii")
        body = {"engine": self.engine, "image_b64": b64, **extra}
        r = requests.post(f"{self.base_url}{path}", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def recognize(self, clean_png_path: str, params: dict) -> OcrResult:
        return OcrResult.from_dict(self._post("/ocr", clean_png_path, {"params": params}))

    def analyze_layout(self, clean_png_path: str, page: int = 0) -> LayoutResult:
        return layout_from_dict(self._post("/layout", clean_png_path, {"page": page}))
