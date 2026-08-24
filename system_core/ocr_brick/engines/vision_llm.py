# engines/vision_llm.py
# Existing OpenAI/Gemini providers adapted to OCR Brick's vision contract.
# Output is free text/Markdown without word boxes.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import OcrResult


_DEFAULT_PROMPT = (
    "Transcribe this document image to clean Markdown. Preserve visible line "
    "order, numbers, dates, names, tables, stamps, and handwritten notes. "
    "Use Markdown only for real structure such as tables or headings. Do not "
    "add bold, italic, bullets, or emphasis unless they are visible in the "
    "document. Return only recognized content, with no explanation."
)


class OpenAIVisionAdapter:
    kind = "vision"

    def __init__(self) -> None:
        self.last_usage: dict[str, Any] = {}

    def recognize(self, clean_png_path: str, params: dict) -> OcrResult:
        from openai import OpenAI
        from system_core.providers.openai_provider import call_markdown_vision

        key_file = Path(str(params.get("api_key_file") or ""))
        api_key = _read_key(key_file)
        if not api_key:
            raise RuntimeError(f"OpenAI API key is empty or missing: {key_file}")

        model = str(params.get("model") or "gpt-4.1").strip()
        prompt = str(params.get("prompt") or _DEFAULT_PROMPT).strip()
        client = OpenAI(api_key=api_key)
        text, usage, route = call_markdown_vision(
            client,
            model=model,
            instructions="You are a careful OCR transcription engine. Do not summarize.",
            user_prompt=prompt,
            image_paths=[clean_png_path],
            reasoning_effort=str(params.get("reasoning_effort") or "minimal"),
            max_output_tokens=int(params.get("max_output_tokens") or 12000),
            timeout_sec=float(params.get("timeout_sec") or 180),
            max_retries=int(params.get("max_retries") or 3),
            service_tier=str(params.get("service_tier") or "auto"),
            use_idempotency=False,
            doc_hash=str(params.get("doc_hash") or "ocr-brick"),
            chunk_index=int(params.get("chunk_index") or 0),
            verbosity=str(params.get("verbosity") or "medium"),
        )
        self.last_usage = usage if isinstance(usage, dict) else {}
        return OcrResult(kind="vision", text=text, words=[], may_rewrite=True, engine=f"chatgpt:{route}:{usage}")


class GeminiVisionAdapter:
    kind = "vision"

    def __init__(self) -> None:
        self.last_usage: dict[str, Any] = {}

    def recognize(self, clean_png_path: str, params: dict) -> OcrResult:
        from google import genai
        from system_core.providers.gemini_provider import call_markdown_vision

        key_file = Path(str(params.get("api_key_file") or ""))
        api_key = _read_key(key_file)
        if not api_key:
            raise RuntimeError(f"Gemini API key is empty or missing: {key_file}")

        model = str(params.get("model") or "gemini-3.5-flash").strip()
        prompt = str(params.get("prompt") or _DEFAULT_PROMPT).strip()
        client = genai.Client(api_key=api_key)
        text, usage, route = call_markdown_vision(
            client,
            model=model,
            system_instruction="You are a careful OCR transcription engine. Do not summarize.",
            user_prompt=prompt,
            image_paths=[clean_png_path],
            temperature=0.0,
            timeout_sec=float(params.get("timeout_sec") or 180),
            max_retries=int(params.get("max_retries") or 3),
            use_stream=_optional_bool(params.get("use_stream")),
            service_tier=str(params.get("service_tier") or "standard"),
        )
        self.last_usage = usage if isinstance(usage, dict) else {}
        return OcrResult(kind="vision", text=text, words=[], may_rewrite=True, engine=f"gemini:{route}:{usage}")


def _read_key(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None
