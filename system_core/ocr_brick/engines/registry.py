# engines/registry.py
# Resolve an engine name -> adapter instance, using ocr.engines.json for the
# family (kind) and config/llm-settings.yaml for cloud/vision creds & models.
# Milestone 1 wires Tesseract; other engines raise a clear NotImplementedError
# so Codex sees exactly where to plug each adapter.
# No globals, no magic paths: manifest path is passed in.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import EngineAdapter
from .tesseract import TesseractAdapter


def load_engines(manifest_path: str | Path) -> dict[str, Any]:
    p = Path(manifest_path)
    if not p.is_file():
        raise FileNotFoundError(f"engines manifest not found: {p}")
    return json.loads(p.read_text(encoding="utf-8")).get("engines", {})


def build_adapter(name: str, manifest: dict[str, Any], project_root: Path,
                  tesseract_exe: str = "tesseract") -> EngineAdapter:
    """Return an adapter for `name`. Credentials/models for cloud/vision come from
    config/llm-settings.yaml (pointed to by the manifest 'creds'); not read here."""
    spec = manifest.get(name)
    if spec is None:
        raise KeyError(f"unknown engine '{name}'")
    kind = spec.get("kind")

    if name == "tesseract":
        return TesseractAdapter(tesseract_exe)

    if kind == "ocr":
        if name == "surya":
            from .surya import SuryaAdapter
            return SuryaAdapter(project_root=project_root)
        raise NotImplementedError(
            f"TODO(codex): wire local OCR adapter for '{name}' (warm GPU service)")
    if kind == "yandex":
        from .yandex import YandexAdapter
        from .yandex_creds import load_creds
        creds_spec = spec.get("creds")
        if not isinstance(creds_spec, dict):
            raise ValueError(
                "yandex 'creds' must be an object with auth_type/secret_file/"
                "folder_id_file (secret lives in a config/*.txt file)")
        return YandexAdapter(load_creds(creds_spec, project_root))
    if kind == "mistral":
        from .mistral import MistralOCRAdapter
        creds = spec.get("creds") or "config/api_key_mistral.txt"
        if not isinstance(creds, str):
            raise ValueError("mistral 'creds' must be a config/*.txt path")
        return MistralOCRAdapter(project_root / creds)
    if kind == "vision":
        if name == "xai":
            from .xai import XAIAdapter
            creds = spec.get("creds") or "config/api_key_xai.txt"
            if not isinstance(creds, str):
                raise ValueError("xai 'creds' must be a config/*.txt path")
            return XAIAdapter(project_root / creds)
        if name == "chatgpt":
            from .vision_llm import OpenAIVisionAdapter
            return OpenAIVisionAdapter()
        if name == "gemini":
            from .vision_llm import GeminiVisionAdapter
            return GeminiVisionAdapter()
        raise NotImplementedError(
            f"TODO(codex): wire vision adapter for '{name}'; read key/model from "
            f"{spec.get('creds')}; output free text + may_rewrite=True")
    raise ValueError(f"unknown kind '{kind}' for engine '{name}'")


def engine_profile(name: str, manifest: dict[str, Any]) -> str:
    """The preprocess profile this engine wants (e.g. 'vision', 'tesseract')."""
    return manifest.get(name, {}).get("profile", name)


def provides_layout(adapter: object) -> bool:
    """True if the adapter can emit structured LayoutResult regions (Surya)."""
    return bool(getattr(adapter, "provides_layout", False)) and hasattr(adapter, "analyze_layout")
