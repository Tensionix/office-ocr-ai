# engines/xai.py
# xAI vision adapter for OCR Brick. It returns free text/Markdown without word
# boxes, so it is useful for transcription but not for searchable-PDF layering.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

import base64
import json
import mimetypes
import random
import time
from pathlib import Path
from typing import Any

import requests

from .base import OcrResult


_CHAT_COMPLETIONS_URL = "https://api.x.ai/v1/chat/completions"
_DEFAULT_PROMPT = (
    "Transcribe this document image to clean Markdown. Preserve visible line "
    "order, numbers, dates, names, tables, stamps, and handwritten notes. "
    "Use Markdown only for real structure such as tables or headings. Do not "
    "add bold, italic, bullets, or emphasis unless they are visible in the "
    "document. Return only recognized content, with no explanation."
)


class XAIAdapter:
    kind = "vision"

    def __init__(self, api_key_file: str | Path, *, timeout: float = 120.0, max_attempts: int = 4) -> None:
        self.api_key_file = Path(api_key_file)
        self.timeout = timeout
        self.max_attempts = max(1, int(max_attempts))
        self.last_usage: dict[str, Any] = {}

    def recognize(self, clean_png_path: str, params: dict) -> OcrResult:
        key_file = Path(str(params.get("api_key_file") or self.api_key_file))
        api_key = self._read_key(key_file)
        if not api_key:
            raise RuntimeError(f"xAI API key is empty or missing: {key_file}")

        model = str(params.get("model") or "grok-4.20-non-reasoning-latest").strip()
        prompt = str(params.get("prompt") or _DEFAULT_PROMPT).strip()
        image_path = Path(clean_png_path)
        data_url = self._data_url(image_path)
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                    ],
                }
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        transient_statuses = {408, 429, 500, 502, 503, 504, 520, 522, 524}
        response = None
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = requests.post(
                    _CHAT_COMPLETIONS_URL,
                    headers=headers,
                    json=payload,
                    timeout=(min(20.0, self.timeout), self.timeout),
                )
                if response.status_code in transient_statuses and attempt < self.max_attempts:
                    retry_after = response.headers.get("Retry-After", "")
                    delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else min(20.0, 1.5 * (2 ** (attempt - 1)))
                    time.sleep(delay + random.uniform(0.0, 0.35))
                    continue
                if response.status_code >= 400:
                    detail = response.text[:1000].replace(api_key, "[redacted]")
                    raise RuntimeError(f"xAI OCR failed with HTTP {response.status_code}: {detail}")
                decoded = response.content.decode("utf-8", "strict")
                loaded = json.loads(decoded)
                if not isinstance(loaded, dict):
                    raise ValueError("xAI OCR returned a non-object JSON response")
                self._validate_text(self._extract_text(loaded))
                payload = loaded
                break
            except (requests.ConnectionError, requests.Timeout, UnicodeError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    raise RuntimeError(f"xAI OCR failed after {self.max_attempts} attempts: {exc}") from exc
                time.sleep(min(20.0, 1.5 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.35))
        if response is None:
            raise RuntimeError(f"xAI OCR failed after {self.max_attempts} attempts: {last_error}")
        self.last_usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        text = self._extract_text(payload).strip()
        return OcrResult(kind="vision", text=text, words=[], may_rewrite=True, engine="xai")

    @staticmethod
    def _validate_text(text: str) -> None:
        if "\ufffd" in text:
            raise UnicodeError("xAI OCR response contains Unicode replacement characters")
        markers = ("Рџ", "Рё", "Рµ", "Р°", "РЅ", "С‚", "СЂ", "СЏ")
        if sum(text.count(marker) for marker in markers) >= 3:
            raise UnicodeError("xAI OCR response looks like UTF-8 mojibake")

    @staticmethod
    def _read_key(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="ignore").strip()

    @staticmethod
    def _data_url(path: Path) -> str:
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    @classmethod
    def _extract_text(cls, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        texts: list[str] = []
        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, dict):
                    cls._collect_text(choice.get("message"), texts)
        cls._collect_text(payload.get("output"), texts)
        return "\n".join(text for text in texts if text.strip())

    @classmethod
    def _collect_text(cls, node: Any, texts: list[str]) -> None:
        if isinstance(node, str):
            if node.strip():
                texts.append(node)
            return
        if isinstance(node, list):
            for item in node:
                cls._collect_text(item, texts)
            return
        if not isinstance(node, dict):
            return
        node_type = str(node.get("type") or "").lower()
        for key in ("text", "output_text"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value)
        if node_type in {"message", "output_text", "text"}:
            cls._collect_text(node.get("content"), texts)
        message = node.get("message")
        if isinstance(message, dict):
            cls._collect_text(message.get("content"), texts)
        content = node.get("content")
        if node_type not in {"message", "output_text", "text"}:
            cls._collect_text(content, texts)
