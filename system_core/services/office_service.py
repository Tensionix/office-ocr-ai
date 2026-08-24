from __future__ import annotations

from argparse import Namespace
import base64
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile

from system_core.core.config import load_yaml_or_json
from system_core.core.jobs import JobContext, run_process


COMMON_FONT_NAMES = (
    "Arial",
    "Calibri",
    "Cambria",
    "Consolas",
    "Courier New",
    "Georgia",
    "Segoe UI",
    "Tahoma",
    "Times New Roman",
    "Trebuchet MS",
    "Verdana",
)

DEFAULT_MODEL_OPTIONS = {
    "openai": ("gpt-4.1", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"),
    "gemini": (
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.1-pro-preview",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
    ),
    "yandex": (
        "page",
        "page-column-sort",
        "table",
        "handwritten",
        "markdown",
        "math-markdown",
        "passport",
        "driver-license-front",
        "driver-license-back",
        "vehicle-registration-front",
        "vehicle-registration-back",
        "license-plates",
    ),
    "xai": (
        "grok-4.3",
        "grok-4.20-non-reasoning-latest",
        "grok-4.20-reasoning-latest",
        "grok-latest",
    ),
    "mistral": ("mistral-ocr-4-0", "mistral-ocr-latest"),
}

MODEL_OPTION_META: dict[str, dict[str, dict[str, str]]] = {
    "openai": {
        "gpt-4.1": {
            "tone": "vision",
            "tooltip": "Project-proven balanced OCR/vision model.",
            "tooltip_ru": "Проверенная в проекте сбалансированная OCR/vision-модель.",
        },
        "gpt-5.4": {
            "tone": "warn",
            "tooltip": "Quality mode for difficult documents.",
            "tooltip_ru": "Режим качества для сложных документов.",
        },
        "gpt-5.4-mini": {
            "tone": "vision",
            "tooltip": "Fast/cost-balanced OCR mode.",
            "tooltip_ru": "Быстрый и умеренный по стоимости OCR-режим.",
        },
        "gpt-5.4-nano": {
            "tone": "vision",
            "tooltip": "Budget OCR/data-extraction mode.",
            "tooltip_ru": "Бюджетный режим OCR/data extraction.",
        },
    },
    "gemini": {
        "gemini-3.5-flash": {
            "tone": "vision",
            "tooltip": "Current fast document/vision default.",
            "tooltip_ru": "Текущий быстрый default для документов и vision.",
        },
        "gemini-3.1-flash-lite": {
            "tone": "vision",
            "tooltip": "Low-latency multimodal model for lightweight extraction.",
            "tooltip_ru": "Быстрая multimodal-модель для лёгкого извлечения.",
        },
        "gemini-3.1-pro-preview": {
            "tone": "warn",
            "tooltip": "Preview quality option for difficult pages.",
            "tooltip_ru": "Preview-вариант качества для сложных страниц.",
        },
        "gemini-2.5-flash": {"tone": "vision"},
        "gemini-2.5-pro": {
            "tone": "warn",
            "tooltip": "Stable quality fallback with image/PDF input.",
            "tooltip_ru": "Стабильный качественный fallback с image/PDF input.",
        },
        "gemini-2.5-flash-lite": {"tone": "vision"},
    },
    "yandex": {
        "page": {"label": "page", "label_ru": "Текст", "tone": "yandex"},
        "page-column-sort": {"label": "columns", "label_ru": "Колонки", "tone": "yandex"},
        "table": {"label": "table", "label_ru": "Таблица", "tone": "yandex"},
        "handwritten": {"label": "handwritten", "label_ru": "Рукописный", "tone": "warn"},
        "markdown": {"label": "Markdown", "label_ru": "Markdown", "tone": "yandex"},
        "math-markdown": {"label": "Math", "label_ru": "Формулы", "tone": "warn"},
        "passport": {"label": "passport", "label_ru": "Паспорт", "tone": "warn"},
        "driver-license-front": {"label": "driver front", "label_ru": "ВУ лицо", "tone": "warn"},
        "driver-license-back": {"label": "driver back", "label_ru": "ВУ оборот", "tone": "warn"},
        "vehicle-registration-front": {"label": "vehicle front", "label_ru": "СТС лицо", "tone": "warn"},
        "vehicle-registration-back": {"label": "vehicle back", "label_ru": "СТС оборот", "tone": "warn"},
        "license-plates": {"label": "plates", "label_ru": "Номера", "tone": "warn"},
    },
    "xai": {
        "grok-4.3": {
            "label": "grok-4.3",
            "label_ru": "grok-4.3",
            "tone": "vision",
            "tooltip": "Official image-understanding example model.",
            "tooltip_ru": "Официальный пример модели для image understanding.",
        },
        "grok-4.20-non-reasoning-latest": {
            "label": "4.20 fast",
            "label_ru": "4.20 fast",
            "tone": "vision",
            "tooltip": "Pinned: grok-4.20-non-reasoning-latest. Best first choice for literal OCR.",
            "tooltip_ru": "Закреплено: grok-4.20-non-reasoning-latest. Первый выбор для буквального OCR.",
        },
        "grok-4.20-reasoning-latest": {
            "label": "4.20 quality",
            "label_ru": "4.20 quality",
            "tone": "warn",
            "tooltip": "Pinned: grok-4.20-reasoning-latest. Try for difficult tables or fragmented scans.",
            "tooltip_ru": "Закреплено: grok-4.20-reasoning-latest. Для сложных таблиц и рваных сканов.",
        },
        "grok-latest": {
            "label": "Latest",
            "label_ru": "Latest",
            "tone": "vision",
            "tooltip": "Floating latest alias; useful for quick checks, less reproducible.",
            "tooltip_ru": "Плавающий latest alias; удобно для проверки, хуже для воспроизводимости.",
        },
    },
}

YANDEX_OCR_MODEL_TONES = {
    "page": "yandex",
    "page-column-sort": "yandex",
    "table": "yandex",
    "handwritten": "warn",
    "markdown": "yandex",
    "math-markdown": "warn",
}

XAI_PINNED_VISION_OPTIONS = (
    {
        "value": "grok-4.3",
        "label": "grok-4.3",
        "label_ru": "grok-4.3",
        "tooltip": "Official image-understanding example model.",
        "tooltip_ru": "Официальный пример модели для image understanding.",
        "tone": "vision",
    },
    {
        "value": "grok-4.20-non-reasoning-latest",
        "label": "4.20 fast",
        "label_ru": "4.20 fast",
        "tooltip": "Pinned: grok-4.20-non-reasoning-latest. Best first choice for literal OCR.",
        "tooltip_ru": "Закреплено: grok-4.20-non-reasoning-latest. Первый выбор для буквального OCR.",
        "tone": "vision",
    },
    {
        "value": "grok-4.20-reasoning-latest",
        "label": "4.20 quality",
        "label_ru": "4.20 quality",
        "tooltip": "Pinned: grok-4.20-reasoning-latest. Try for difficult tables or fragmented scans.",
        "tooltip_ru": "Закреплено: grok-4.20-reasoning-latest. Для сложных таблиц и рваных сканов.",
        "tone": "warn",
    },
    {
        "value": "grok-latest",
        "label": "Latest",
        "label_ru": "Latest",
        "tooltip": "Pinned: grok-latest. Floating latest alias; useful for quick checks, less reproducible.",
        "tooltip_ru": "Закреплено: grok-latest. Плавающий latest alias; удобно для проверки, хуже для воспроизводимости.",
        "tone": "vision",
    },
)


@dataclass
class MirrorContext:
    source: Path
    destination: Path
    source_explicit: bool
    destination_explicit: bool
    staged_files: int = 0
    staged_dirs: int = 0
    synced_files: int = 0
    synced_dirs: int = 0
    skipped: list[str] = field(default_factory=list)


def _python_executable(context: JobContext) -> str:
    """Prefer console python.exe even when the GUI itself runs under pythonw.exe."""
    current = Path(sys.executable)
    if current.name.lower() == "pythonw.exe":
        sibling = current.with_name("python.exe")
        if sibling.exists():
            return str(sibling)

    runtime_python = context.paths.root / "runtime" / "python.exe"
    if runtime_python.exists():
        return str(runtime_python)

    nested_runtime_python = context.paths.root / "runtime" / "python" / "python.exe"
    if nested_runtime_python.exists():
        return str(nested_runtime_python)

    return str(current)


def _script(context: JobContext, name: str) -> Path:
    path = context.paths.system_core / name
    if not path.exists():
        raise RuntimeError(f"Script was not found: {path}")
    return path


def _run_script(
    context: JobContext,
    script_name: str,
    args: list[str] | None = None,
    *,
    progress_seconds: float = 600.0,
    extra_env: dict[str, str] | None = None,
):
    command = [_python_executable(context), str(_script(context, script_name)), *(args or [])]
    return run_process(
        context,
        command,
        cwd=context.paths.root,
        progress_seconds=progress_seconds,
        extra_env=extra_env,
    )


def _run_mirrored_script(
    context: JobContext,
    script_name: str,
    args: list[str] | None = None,
    *,
    progress_seconds: float = 600.0,
    extra_env: dict[str, str] | None = None,
) -> dict[str, object]:
    mirror = _prepare_mirror_context(context)
    result = _run_script(context, script_name, args, progress_seconds=progress_seconds, extra_env=extra_env)
    _sync_destination(context, mirror)
    _write_mirror_report(context, mirror)
    return {
        "exit_code": result.exit_code,
        "source": str(mirror.source),
        "destination": str(mirror.destination),
        "source_explicit": mirror.source_explicit,
        "destination_explicit": mirror.destination_explicit,
        "staged_files": mirror.staged_files,
        "synced_files": mirror.synced_files,
        "skipped": mirror.skipped,
    }


def _parameter(context: JobContext, key: str, default: str = "") -> str:
    value = context.operation.parameters.get(key, default)
    return str(value if value is not None else default).strip()


def _provider_default_key_file(root: Path, provider: str) -> Path:
    if provider == "openai":
        return root / "config" / "api_key_openai.txt"
    if provider == "xai":
        return root / "config" / "api_key_xai.txt"
    if provider == "mistral":
        return root / "config" / "api_key_mistral.txt"
    if provider == "yandex":
        studio_key = root / "config" / "api_key_yandex_studio.txt"
        if studio_key.exists():
            return studio_key
        return root / "config" / "yandex_key.txt"
    return root / "config" / "api_key_gemini.txt"


def _provider_legacy_key_files(root: Path, provider: str) -> list[Path]:
    if provider == "openai":
        return [root / "config" / "api_openai.txt", root / "api_key_openai.txt"]
    if provider == "xai":
        return []
    if provider == "mistral":
        return []
    if provider == "yandex":
        return [
            root / "config" / "api_key_yandex_studio.txt",
            root / "config" / "api_key_yandex.txt",
            root / "config" / "yandex_api_key.txt",
            root / "api_key_yandex.txt",
        ]
    return [root / "config" / "api_gemini.txt", root / "api_key.txt"]


def _key_file_candidates(root: Path, provider: str) -> list[Path]:
    candidates: list[Path] = [
        _provider_default_key_file(root, provider),
        *_provider_legacy_key_files(root, provider),
    ]
    key_dir = root / "config" / "keys" / provider
    if key_dir.exists():
        candidates.extend(sorted(key_dir.glob("*.txt")))

    config_dir = root / "config"
    if config_dir.exists():
        if provider == "openai":
            patterns = ("api_key_openai*.txt", "api_openai*.txt")
        elif provider == "xai":
            patterns = ("api_key_xai.txt",)
        elif provider == "mistral":
            patterns = ("api_key_mistral.txt",)
        elif provider == "yandex":
            patterns = ("yandex_key*.txt", "api_key_yandex*.txt", "yandex_api_key*.txt")
        else:
            patterns = ("api_key_gemini*.txt", "api_gemini*.txt")
        for pattern in patterns:
            candidates.extend(sorted(config_dir.glob(pattern)))

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _safe_key_label(root: Path, path: Path) -> str:
    try:
        label = path.relative_to(root).as_posix()
    except ValueError:
        label = path.name
    return label


def _read_key(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def _selected_provider(values: dict[str, object] | None) -> str:
    provider = str((values or {}).get("provider") or "gemini").strip().lower()
    return provider if provider in {"openai", "gemini", "yandex", "xai", "mistral"} else "gemini"


def _resolve_key_file(root: Path, provider: str, selector: str) -> Path:
    raw = str(selector or "").strip()
    if not raw:
        for candidate in _key_file_candidates(root, provider):
            if _read_key(candidate):
                return candidate.resolve()
        return _provider_default_key_file(root, provider).resolve()
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _key_env(root: Path, provider: str, selector: str) -> tuple[dict[str, str], Path]:
    path = _resolve_key_file(root, provider, selector)
    if provider == "openai":
        return {"AUDION_OPENAI_API_KEY_FILE": str(path)}, path
    if provider == "xai":
        return {"AUDION_XAI_API_KEY_FILE": str(path)}, path
    if provider == "yandex":
        return {
            "AUDION_YANDEX_API_KEY_FILE": str(path),
            "AUDION_YANDEX_FOLDER_FILE": str(root / "config" / "yandex_folder.txt"),
        }, path
    return {"AUDION_GEMINI_API_KEY_FILE": str(path)}, path


def _api_key_options_for_provider(project_root: Path, provider: str) -> list[dict[str, str]]:
    default_path = _provider_default_key_file(project_root, provider)
    options = [
        {
            "value": "",
            "label": f"Current {provider} key ({_safe_key_label(project_root, default_path)})",
            "label_ru": f"Текущий ключ {provider} ({_safe_key_label(project_root, default_path)})",
        }
    ]

    for path in _key_file_candidates(project_root, provider):
        if not path.exists():
            continue
        marker = "OK" if _read_key(path) else "empty"
        label = f"{_safe_key_label(project_root, path)} [{marker}]"
        options.append({"value": _safe_key_label(project_root, path), "label": label, "label_ru": label})

    return options


def api_key_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    return _api_key_options_for_provider(project_root, _selected_provider(values))


def xai_api_key_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    return _api_key_options_for_provider(project_root, "xai")


def mistral_api_key_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    return _api_key_options_for_provider(project_root, "mistral")


def openai_api_key_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    return _api_key_options_for_provider(project_root, "openai")


def gemini_api_key_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    return _api_key_options_for_provider(project_root, "gemini")


def yandex_api_key_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    return _api_key_options_for_provider(project_root, "yandex")


def _cached_model_options(root: Path, provider: str) -> list[dict[str, str]]:
    cache_file = root / "data" / f"available_models_{provider}.md"
    if not cache_file.exists():
        return []
    models: list[dict[str, str]] = []
    for line in cache_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        text = line.strip()
        lowered = text.lower()
        if not text or text.startswith("#") or lowered.startswith("checked at:") or lowered.startswith("checked from "):
            continue
        models.append({"value": text, "label": f"{text} (cached)", "label_ru": f"{text} (кэш)"})
    return models


def _write_models_cache(root: Path, provider: str, models: list[str], title: str | None = None) -> Path:
    cache_file = root / "data" / f"available_models_{provider}.md"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    heading = title or f"{provider.capitalize()} models available for selected key"
    cache_file.write_text(
        f"# {heading}\n\n"
        f"Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        + "\n".join(models)
        + "\n",
        encoding="utf-8",
    )
    return cache_file


def _extend_unique_model_options(options: list[dict[str, str]], provider: str, models: list[dict[str, str]]) -> None:
    seen = {str(option.get("value", "")).strip().lower() for option in options}
    for option in models:
        value = str(option.get("value", "")).strip()
        if not value or value.lower() in seen:
            continue
        options.append(option)
        seen.add(value.lower())


def _model_option(provider: str, model: str) -> dict[str, str]:
    value = str(model or "").strip()
    meta = dict(MODEL_OPTION_META.get(provider, {}).get(value.lower(), {}))
    option = {
        "value": value,
        "label": meta.pop("label", value),
        "label_ru": meta.pop("label_ru", value),
    }
    option.update(meta)
    return option


def _ocr_model_allowlist(provider: str) -> set[str]:
    return {str(model).strip().lower() for model in DEFAULT_MODEL_OPTIONS.get(provider, ()) if str(model).strip()}


def _filter_ocr_model_ids(provider: str, models: list[str]) -> list[str]:
    allowed = _ocr_model_allowlist(provider)
    if not allowed:
        return models
    return [model for model in models if str(model).strip().lower() in allowed]


def _filter_ocr_model_options(provider: str, options: list[dict[str, str]]) -> list[dict[str, str]]:
    allowed = _ocr_model_allowlist(provider)
    if not allowed:
        return options
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for option in options:
        value = str(option.get("value", "")).strip()
        lowered = value.lower()
        if not value or lowered not in allowed or lowered in seen:
            continue
        result.append(_model_option(provider, value))
        seen.add(lowered)
    return result


def _ocr_cache_provider(provider: str) -> str:
    if provider in {"openai", "gemini"}:
        return f"{provider}_ocr"
    if provider == "xai":
        return "xai_vision"
    if provider == "yandex":
        return "yandex_ocr"
    return provider


def _ocr_cache_title(provider: str) -> str:
    if provider == "openai":
        return "OpenAI OCR/vision models available for selected key"
    if provider == "gemini":
        return "Gemini OCR/vision models available for selected key"
    if provider == "xai":
        return "xAI vision models available for selected key"
    if provider == "yandex":
        return "Yandex OCR models available for selected key"
    return f"{provider.capitalize()} OCR/vision models available for selected key"


def _default_model_options(provider: str) -> list[dict[str, str]]:
    return [_model_option(provider, model) for model in DEFAULT_MODEL_OPTIONS.get(provider, ())]


def _openai_models(api_key: str) -> list[str]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    return sorted(
        dict.fromkeys(
            str(item.id).strip()
            for item in client.models.list().data
            if str(getattr(item, "id", "")).strip()
        )
    )


def _gemini_models(api_key: str) -> list[str]:
    from google import genai

    client = genai.Client(api_key=api_key)
    models: list[str] = []
    for model in client.models.list():
        actions = getattr(model, "supported_actions", None)
        if actions and "generateContent" in actions:
            models.append(str(model.name).replace("models/", ""))
    return sorted(dict.fromkeys(models))


def _extract_xai_model_ids(payload: object, *, vision_only: bool = False) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("data") or payload.get("models") or payload.get("items") or []
    if isinstance(raw_items, dict):
        raw_items = list(raw_items.values())
    models: list[str] = []
    if not isinstance(raw_items, list):
        return models
    for item in raw_items:
        if isinstance(item, str):
            if not vision_only:
                models.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        if vision_only:
            input_modalities = {str(value).strip().lower() for value in item.get("input_modalities", [])}
            output_modalities = {str(value).strip().lower() for value in item.get("output_modalities", [])}
            if input_modalities and "image" not in input_modalities:
                continue
            if output_modalities and "text" not in output_modalities:
                continue
        for key in ("id", "name", "model"):
            value = str(item.get(key) or "").strip()
            if value:
                models.append(value)
                break
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            models.extend(str(alias).strip() for alias in aliases if str(alias).strip())
    return sorted(dict.fromkeys(model for model in models if model))


def _xai_models(api_key: str, *, vision_only: bool = False) -> list[str]:
    import requests

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    urls = ("https://api.x.ai/v1/language-models",) if vision_only else (
        "https://api.x.ai/v1/language-models",
        "https://api.x.ai/v1/models",
    )
    models: list[str] = []
    last_error: Exception | None = None
    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            models.extend(_extract_xai_model_ids(response.json(), vision_only=vision_only))
        except Exception as exc:
            last_error = exc
    models = sorted(dict.fromkeys(model for model in models if model))
    if models:
        return models
    if last_error:
        raise last_error
    return []


def _yandex_models(api_key: str, folder_id: str = "") -> list[str]:
    import requests

    url = "https://ai.api.cloud.yandex.net/v1/models"
    base_headers: dict[str, str] = {"Accept": "application/json"}
    if folder_id:
        base_headers["x-folder-id"] = folder_id
        base_headers["OpenAI-Project"] = folder_id

    auth_headers = (
        {"Authorization": f"Api-Key {api_key}"},
        {"Authorization": f"Bearer {api_key}"},
    )
    last_error: Exception | None = None
    for auth in auth_headers:
        headers = dict(base_headers)
        headers.update(auth)
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code in {401, 403}:
                last_error = RuntimeError(f"Yandex model list returned HTTP {response.status_code}")
                continue
            response.raise_for_status()
            payload = response.json()
            models = _extract_yandex_model_ids(payload)
            if models:
                return models
            last_error = RuntimeError("Yandex model list response did not contain model ids")
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def _extract_yandex_model_ids(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("data") or payload.get("models") or payload.get("items") or []
    if isinstance(raw_items, dict):
        raw_items = list(raw_items.values())
    models: list[str] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, str):
                models.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            for key in ("id", "name", "model", "modelUri", "uri"):
                value = str(item.get(key) or "").strip()
                if value:
                    models.append(value.replace("models/", ""))
                    break
    return sorted(dict.fromkeys(model for model in models if model))


def _yandex_folder_id(root: Path) -> str:
    value = _read_key(_yandex_folder_file(root))
    if value:
        return value
    return _infer_yandex_folder_id_from_cache(root)


def _infer_yandex_folder_id_from_models(models: list[str]) -> str:
    for model in models:
        match = re.search(r"^[a-z]+://([^/]+)/", str(model).strip())
        if match:
            return match.group(1)
    return ""


def _infer_yandex_folder_id_from_cache(root: Path) -> str:
    cache_file = root / "data" / "available_models_yandex.md"
    if not cache_file.exists():
        return ""
    models = [
        line.strip()
        for line in cache_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip() and not line.strip().startswith("#") and not line.lower().startswith("checked at:")
    ]
    return _infer_yandex_folder_id_from_models(models)


def _online_models(provider: str, api_key: str, root: Path) -> list[str]:
    if provider == "openai":
        return _openai_models(api_key)
    if provider == "gemini":
        return _gemini_models(api_key)
    if provider == "xai":
        return _xai_models(api_key)
    if provider == "yandex":
        return _yandex_models(api_key, _yandex_folder_id(root))
    return []


def _yandex_ocr_default_options() -> list[dict[str, str]]:
    return [_model_option("yandex", model) for model in DEFAULT_MODEL_OPTIONS.get("yandex", ())]


def yandex_ocr_model_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    options = _yandex_ocr_default_options()
    _extend_unique_model_options(options, "yandex_ocr", _cached_model_options(project_root, "yandex_ocr"))

    key_selector = str((values or {}).get("yandex_api_key") or (values or {}).get("api_key") or "")
    key_file = _resolve_key_file(project_root, "yandex", key_selector)
    api_key = _read_key(key_file)
    if not api_key:
        return options

    try:
        api_models = _yandex_models(api_key, _yandex_folder_id(project_root))
    except Exception:
        return options

    known = {model.lower() for model in DEFAULT_MODEL_OPTIONS.get("yandex", ())}
    ocr_models = [
        model for model in api_models
        if model.lower() in known or "ocr" in model.lower() or "vision" in model.lower()
    ]
    if not ocr_models:
        ocr_models = [str(item["value"]) for item in _yandex_ocr_default_options()]
    _write_models_cache(project_root, "yandex_ocr", ocr_models, "Yandex OCR models available for selected key")
    _extend_unique_model_options(
        options,
        "yandex_ocr",
        [
            {
                "value": model,
                "label": model,
                "label_ru": model,
                "tone": YANDEX_OCR_MODEL_TONES.get(model, "yandex"),
            }
            for model in ocr_models
        ],
    )
    return options


def xai_vision_model_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    options: list[dict[str, str]] = [dict(option) for option in XAI_PINNED_VISION_OPTIONS]
    _extend_unique_model_options(
        options,
        "xai_vision",
        _filter_ocr_model_options("xai", _cached_model_options(project_root, "xai_vision")),
    )

    key_selector = str((values or {}).get("xai_api_key") or (values or {}).get("api_key") or "")
    key_file = _resolve_key_file(project_root, "xai", key_selector)
    api_key = _read_key(key_file)
    if not api_key:
        return options

    try:
        models = _xai_models(api_key, vision_only=True)
    except Exception:
        return options
    models = _filter_ocr_model_ids("xai", models)
    if not models:
        models = list(DEFAULT_MODEL_OPTIONS.get("xai", ()))
    _write_models_cache(project_root, "xai_vision", models, "xAI vision models available for selected key")
    _extend_unique_model_options(
        options,
        "xai_vision",
        [_model_option("xai", model) for model in models],
    )
    return options


def _model_options_for_provider(
    root: Path | str | None,
    values: dict[str, object] | None,
    provider: str,
) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    provider_values = dict(values or {})
    key_value = provider_values.get(f"{provider}_api_key")
    key_file = _resolve_key_file(project_root, provider, str(key_value or ""))

    options = _default_model_options(provider)
    cache_provider = _ocr_cache_provider(provider)
    _extend_unique_model_options(
        options,
        cache_provider,
        _filter_ocr_model_options(provider, _cached_model_options(project_root, cache_provider)),
    )
    # Read legacy diagnostic caches too, but never expose non-OCR models from them.
    _extend_unique_model_options(
        options,
        provider,
        _filter_ocr_model_options(provider, _cached_model_options(project_root, provider)),
    )

    api_key = _read_key(key_file)
    if not api_key:
        return options

    try:
        models = _filter_ocr_model_ids(provider, _online_models(provider, api_key, project_root))
    except Exception:
        return options
    if not models:
        return options

    _write_models_cache(project_root, cache_provider, models, _ocr_cache_title(provider))
    _extend_unique_model_options(options, cache_provider, [_model_option(provider, model) for model in models])
    return options


def openai_model_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, str]]:
    return _model_options_for_provider(root, values, "openai")


def gemini_model_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, str]]:
    return _model_options_for_provider(root, values, "gemini")




def _yandex_folder_file(root: Path) -> Path:
    return root / "config" / "yandex_folder.txt"


def _yandex_key_id_file(root: Path) -> Path:
    return root / "config" / "yandex_key_id.txt"


def yandex_ocr_smoke(context: JobContext) -> dict[str, object]:
    provider = "yandex"
    key_selector = _parameter(context, "yandex_api_key", "")
    key_file = _resolve_key_file(context.paths.root, provider, key_selector)
    folder_file = _yandex_folder_file(context.paths.root)
    api_key = _read_key(key_file)
    folder_id = _yandex_folder_id(context.paths.root)
    if not api_key:
        raise RuntimeError(f"Yandex API key is empty or missing: {_safe_key_label(context.paths.root, key_file)}")
    if not folder_id:
        raise RuntimeError(f"Yandex folder id is empty or missing: {_safe_key_label(context.paths.root, folder_file)}")

    model = _parameter(context, "yandex_model", "page")
    langs = [item.strip() for item in _parameter(context, "yandex_languages", "ru,en").split(",") if item.strip()]
    if not langs:
        langs = ["ru", "en"]

    context.report_dir.mkdir(parents=True, exist_ok=True)
    image_path = context.report_dir / "yandex_ocr_smoke.png"
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise RuntimeError(f"Pillow is required for the Yandex smoke image: {exc}") from exc

    img = Image.new("RGB", (520, 150), "white")
    draw = ImageDraw.Draw(img)
    draw.text((24, 54), "YANDEX OCR TEST", fill="black")
    draw.text((24, 88), "ТЕСТ OCR", fill="black")
    img.save(image_path)

    from system_core.ocr_brick.engines.yandex import YandexAdapter
    from system_core.ocr_brick.engines.yandex_creds import YandexCreds

    context.log(
        "Yandex OCR smoke: "
        f"model={model}, languages={','.join(langs)}, "
        f"key={_safe_key_label(context.paths.root, key_file)}, "
        f"folder={_safe_key_label(context.paths.root, folder_file)}"
    )
    adapter = YandexAdapter(YandexCreds(auth_type="api_key", secret=api_key, folder_id=folder_id), timeout=45.0)
    result = adapter.recognize(str(image_path), {"mode": "sync", "model": model, "languageCodes": langs})
    context.log(f"Yandex OCR smoke text: {result.text.strip() or '[empty response]'}")
    context.progress(1.0)
    return {
        "exit_code": 0,
        "provider": "yandex",
        "model": model,
        "languages": langs,
        "words": len(result.words),
        "text": result.text,
        "image": str(image_path),
    }


def xai_ocr_smoke(context: JobContext) -> dict[str, object]:
    provider = "xai"
    key_selector = _parameter(context, "xai_api_key", "")
    key_file = _resolve_key_file(context.paths.root, provider, key_selector)
    api_key = _read_key(key_file)
    if not api_key:
        raise RuntimeError(f"xAI API key is empty or missing: {_safe_key_label(context.paths.root, key_file)}")

    model = _parameter(context, "xai_model", "grok-4.3")
    context.report_dir.mkdir(parents=True, exist_ok=True)
    image_path = context.report_dir / "xai_ocr_smoke.png"
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise RuntimeError(f"Pillow is required for the xAI smoke image: {exc}") from exc

    img = Image.new("RGB", (560, 160), "white")
    draw = ImageDraw.Draw(img)
    draw.text((24, 50), "xAI OCR TEST", fill="black")
    draw.text((24, 88), "ТЕСТ OCR", fill="black")
    img.save(image_path)

    from system_core.ocr_brick.engines.xai import XAIAdapter

    context.log(f"xAI OCR smoke: model={model}, key={_safe_key_label(context.paths.root, key_file)}")
    adapter = XAIAdapter(key_file, timeout=90.0)
    result = adapter.recognize(
        str(image_path),
        {"model": model, "api_key_file": str(key_file), "prompt": _vision_ocr_prompt(context)},
    )
    context.log(f"xAI OCR smoke text: {result.text.strip() or '[empty response]'}")
    if adapter.last_usage:
        context.log(f"xAI OCR smoke usage: {adapter.last_usage}")
        cost = _usage_cost_usd_estimate(adapter.last_usage)
        if cost is not None:
            context.log(f"xAI OCR smoke cost estimate: ${cost:.8f}")
    context.progress(1.0)
    return {
        "exit_code": 0,
        "provider": provider,
        "model": model,
        "text": result.text,
        "usage": adapter.last_usage,
        "cost_usd_estimate": _usage_cost_usd_estimate(adapter.last_usage),
        "image": str(image_path),
    }


def mistral_ocr_smoke(context: JobContext) -> dict[str, object]:
    provider = "mistral"
    key_selector = _parameter(context, "mistral_api_key", "")
    key_file = _resolve_key_file(context.paths.root, provider, key_selector)
    if not _read_key(key_file):
        raise RuntimeError(f"Mistral API key is empty or missing: {_safe_key_label(context.paths.root, key_file)}")

    model = _parameter(context, "mistral_model", "mistral-ocr-4-0")
    context.report_dir.mkdir(parents=True, exist_ok=True)
    image_path = context.report_dir / "mistral_ocr_smoke.png"
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:
        raise RuntimeError(f"Pillow is required for the Mistral smoke image: {exc}") from exc

    image = Image.new("RGB", (900, 420), "white")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("arial.ttf", 34)
        body_font = ImageFont.truetype("arial.ttf", 27)
    except OSError:
        title_font = ImageFont.load_default()
        body_font = title_font
    draw.text((35, 25), "ТЕСТ MISTRAL OCR 4", fill="black", font=title_font)
    draw.text((35, 85), "Омская область, Иванов Иван Иванович", fill="black", font=body_font)
    draw.rectangle((35, 145, 865, 290), outline="black", width=2)
    draw.line((310, 145, 310, 290), fill="black", width=2)
    draw.line((600, 145, 600, 290), fill="black", width=2)
    draw.line((35, 215, 865, 215), fill="black", width=2)
    draw.text((55, 165), "Точка", fill="black", font=body_font)
    draw.text((340, 165), "X", fill="black", font=body_font)
    draw.text((630, 165), "Y", fill="black", font=body_font)
    draw.text((55, 235), "1", fill="black", font=body_font)
    draw.text((340, 235), "123.456", fill="black", font=body_font)
    draw.text((630, 235), "789.012", fill="black", font=body_font)
    draw.text((35, 330), "Формула: S = a × b / 2", fill="black", font=body_font)
    image.save(image_path)

    from system_core.ocr_brick.engines.mistral import MistralOCRAdapter

    context.log(f"Mistral OCR smoke: model={model}, key={_safe_key_label(context.paths.root, key_file)}")
    adapter = MistralOCRAdapter(key_file, timeout=120.0)
    result = adapter.recognize(
        str(image_path),
        {
            "model": model,
            "api_key_file": str(key_file),
            "include_blocks": True,
            "table_format": "html",
            "confidence_granularity": "word",
        },
    )
    response_path = context.report_dir / "mistral_ocr_smoke_response.json"
    response_path.write_text(
        json.dumps({"model": model, "page": adapter.last_page, "usage_info": adapter.last_usage}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    context.log(f"Mistral OCR smoke text: {result.text.strip() or '[empty response]'}")
    context.log(f"Mistral OCR smoke usage: {adapter.last_usage}")
    context.progress(1.0)
    return {
        "exit_code": 0,
        "provider": provider,
        "model": model,
        "text": result.text,
        "usage": adapter.last_usage,
        "image": str(image_path),
        "response": str(response_path),
    }


def _bool_parameter(context: JobContext, key: str, default: bool = False) -> bool:
    value = context.operation.parameters.get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _int_parameter(context: JobContext, key: str, default: int) -> int:
    try:
        return int(float(_parameter(context, key, str(default))))
    except (TypeError, ValueError):
        return default


def _configured_provider_model(root: Path, provider: str, default: str) -> str:
    try:
        settings = load_yaml_or_json(root / "config" / "llm_settings.yaml")
    except Exception:
        return default
    providers = settings.get("providers", {}) if isinstance(settings, dict) else {}
    cfg = providers.get(provider, {}) if isinstance(providers, dict) else {}
    if isinstance(cfg, dict):
        model = str(cfg.get("model") or "").strip()
        if model:
            return model
    return default


def _provider_model_parameter(context: JobContext, provider: str, key: str, default: str) -> str:
    model = _parameter(context, key, "auto")
    if not model or model.lower() == "auto":
        return _configured_provider_model(context.paths.root, provider, default)
    return model


def _vision_ocr_prompt(context: JobContext) -> str:
    prompt = _parameter(context, "vision_prompt", "")
    if prompt:
        return prompt
    prompt_file = context.paths.root / "config" / "ocr_prompt_vision_ocr.md"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8", errors="ignore").strip()
    return (
        "Transcribe this document image to clean Markdown. Preserve visible line order, numbers, dates, "
        "names, tables, stamps, and handwritten notes. Use Markdown only for real structure. Do not add "
        "bold, italic, bullets, or emphasis unless visible in the document. Return only recognized content."
    )


def _gemini_service_tier_parameter(context: JobContext, key: str = "gemini_service_tier") -> str:
    tier = _parameter(context, key, "standard").lower()
    if tier not in {"standard", "flex"}:
        tier = "standard"
    return tier


def _usage_cost_usd_estimate(usage: dict[str, object]) -> float | None:
    raw_ticks = usage.get("cost_in_usd_ticks") if isinstance(usage, dict) else None
    try:
        ticks = float(raw_ticks)
    except (TypeError, ValueError):
        return None
    if ticks <= 0:
        return None
    return ticks / 10_000_000_000


def _tesseract_exe(context: JobContext) -> str:
    from system_core.core.tesseract_runtime import resolve_tesseract_runtime

    runtime = resolve_tesseract_runtime()
    return str(runtime.exe) if runtime.available and runtime.exe else "tesseract"


def _realesrgan_candidates(root: Path) -> list[Path]:
    return [
        root / "tools" / "realesrgan-ncnn-vulkan" / "realesrgan-ncnn-vulkan.exe",
        root / "runtime" / "realesrgan-ncnn-vulkan" / "realesrgan-ncnn-vulkan.exe",
        root / "runtime" / "realesrgan-ncnn-vulkan.exe",
        root / "system_core" / "ocr_brick" / "bin" / "realesrgan-ncnn-vulkan.exe",
    ]


def _realesrgan_exe(root: Path) -> Path | None:
    for candidate in _realesrgan_candidates(root):
        if candidate.is_file():
            return candidate
    found = shutil.which("realesrgan-ncnn-vulkan") or shutil.which("realesrgan-ncnn-vulkan.exe")
    return Path(found) if found else None


def _ocr_brick_sources(source: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".pdf"}
    if source.is_file():
        return [source] if source.suffix.lower() in exts else []
    return sorted(
        (path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in exts),
        key=lambda item: str(item).lower(),
    )


def _ocr_brick_profile_overrides(profile: str, engine: str) -> dict[str, object]:
    vision_engine = engine in {"xai", "gemini", "chatgpt"}
    if profile == "raw":
        return {
            "enabled": False,
            "sr_scale": 0,
        }
    if profile == "heavy":
        return {
            "enabled": True,
            "sr_scale": 4 if engine == "tesseract" else 2,
            "sr_model": "general",
            "denoise": "strong",
            "contrast": "high",
            "unsharp": "strong",
            "strip_vlines": False,
            "deskew": True,
            "binarize": "on" if engine == "tesseract" else "off",
            "intent": "text",
        }
    if profile == "numbers":
        return {
            "enabled": True,
            "sr_scale": 2,
            "sr_model": "general",
            "denoise": "weak",
            "contrast": "high",
            "unsharp": "strong",
            "strip_vlines": False,
            "deskew": True,
            "binarize": "auto" if engine == "tesseract" else "off",
            "intent": "image" if vision_engine else "text",
        }
    return {}


def _ocr_brick_overrides(context: JobContext, *, allow_sr: bool, engine: str) -> dict[str, object]:
    profile = _parameter(context, "ocr_preprocess_profile", "auto").lower()
    if profile not in {"auto", "raw", "heavy", "numbers", "manual"}:
        profile = "auto"

    if profile == "manual":
        scale = _int_parameter(context, "ocr_sr_scale", 0)
        overrides = {
            "enabled": _bool_parameter(context, "preprocess_enabled", True),
            "sr_scale": scale,
            "sr_model": _parameter(context, "ocr_sr_model", "auto"),
            "denoise": _parameter(context, "ocr_denoise", "weak"),
            "contrast": _parameter(context, "ocr_contrast", "auto"),
            "unsharp": _parameter(context, "ocr_unsharp", "auto"),
            "source_format": _parameter(context, "ocr_source_format", "auto"),
            "strip_vlines": _bool_parameter(context, "ocr_strip_vlines", False),
            "deskew": _bool_parameter(context, "ocr_deskew", True),
            "binarize": _parameter(context, "ocr_binarize", "auto"),
            "intent": _parameter(context, "ocr_intent", "text"),
            "gpu": _parameter(context, "ocr_gpu", "auto"),
        }
    else:
        overrides = _ocr_brick_profile_overrides(profile, engine)

    scale = int(overrides.get("sr_scale") or 0)
    if not allow_sr and scale > 0:
        context.log("[OCR BRICK] Real-ESRGAN binary was not found; forcing Upscale=Off.")
        overrides["sr_scale"] = 0
    if profile == "auto" and not allow_sr:
        context.log("[OCR BRICK] Real-ESRGAN binary was not found; engine profile will run without upscale.")
        overrides["sr_scale"] = 0

    return overrides


def _ocr_engine_params(context: JobContext, engine: str) -> dict[str, object]:
    def with_tesseract_2pass(params: dict[str, object]) -> dict[str, object]:
        if engine not in {"yandex", "mistral", "xai", "gemini", "chatgpt"}:
            return params
        if not _bool_parameter(context, "ocr_tesseract_2pass", False):
            return params
        params.update(
            {
                "tesseract_2pass": True,
                "tesseract_2pass_lang": _parameter(context, "ocr_tesseract_2pass_lang", "rus+eng"),
                "tesseract_2pass_psm": _int_parameter(context, "ocr_tesseract_2pass_psm", 6),
                "tesseract_2pass_hint": _bool_parameter(context, "ocr_tesseract_2pass_hint", True),
                "tesseract_2pass_prompt_chars": _int_parameter(context, "ocr_tesseract_2pass_prompt_chars", 6000),
            }
        )
        return params

    def with_mistral_second_pass(params: dict[str, object]) -> dict[str, object]:
        mode = _parameter(context, "ocr_mistral_second_pass", "tesseract").lower()
        if mode not in {"none", "tesseract", "yandex", "yandex_tesseract"}:
            mode = "tesseract"
        params["secondary_pass"] = mode
        if mode in {"tesseract", "yandex_tesseract"}:
            params.update({
                "tesseract_2pass": True,
                "tesseract_2pass_lang": _parameter(context, "ocr_tesseract_2pass_lang", "rus+eng"),
                "tesseract_2pass_psm": _int_parameter(context, "ocr_tesseract_2pass_psm", 6),
                "tesseract_2pass_hint": False,
            })
        if mode in {"yandex", "yandex_tesseract"}:
            languages = [
                item.strip()
                for item in _parameter(context, "ocr_yandex_2pass_languages", "ru,en").split(",")
                if item.strip()
            ]
            params.update({
                "yandex_2pass_scope": _parameter(context, "ocr_yandex_2pass_scope", "suspicious"),
                "yandex_2pass_model": _parameter(context, "ocr_yandex_2pass_model", "page"),
                "yandex_2pass_languages": languages or ["ru", "en"],
                "yandex_fusion": _bool_parameter(context, "ocr_yandex_fusion", True),
                "yandex_verify_threshold": _parameter(context, "ocr_yandex_verify_threshold", "0.90"),
            })
        return params

    if engine == "tesseract":
        return {
            "lang": _parameter(context, "ocr_tesseract_lang", _parameter(context, "workbench_lang", "rus+eng")),
            "psm": _int_parameter(context, "ocr_tesseract_psm", _int_parameter(context, "workbench_psm", 6)),
        }
    if engine == "surya":
        return {
            "surya_backend": _parameter(context, "surya_backend", "llamacpp"),
        }
    if engine == "yandex":
        langs = [item.strip() for item in _parameter(context, "yandex_languages", "ru,en").split(",") if item.strip()]
        return with_tesseract_2pass({
            "mode": "sync",
            "model": _parameter(context, "yandex_model", "page"),
            "languageCodes": langs or ["ru", "en"],
        })
    if engine == "xai":
        key_selector = _parameter(context, "xai_api_key", "")
        key_file = _resolve_key_file(context.paths.root, "xai", key_selector)
        return with_tesseract_2pass({
            "model": _parameter(context, "xai_model", "grok-4.3"),
            "api_key_file": str(key_file),
            "prompt": _vision_ocr_prompt(context),
            "russian_review_enabled": _bool_parameter(context, "xai_russian_review_enabled", False),
            "russian_review_model": _parameter(context, "xai_russian_review_model", "grok-4.20-reasoning-latest"),
            "russian_review_prompt": _parameter(context, "xai_russian_review_prompt", ""),
        })
    if engine == "mistral":
        key_selector = _parameter(context, "mistral_api_key", "")
        key_file = _resolve_key_file(context.paths.root, "mistral", key_selector)
        return with_mistral_second_pass({
            "adapter_version": 1,
            "model": _parameter(context, "mistral_model", "mistral-ocr-4-0"),
            "api_key_file": str(key_file),
            "include_blocks": _bool_parameter(context, "mistral_include_blocks", True),
            "table_format": _parameter(context, "mistral_table_format", "html"),
            "confidence_granularity": _parameter(context, "mistral_confidence", "word"),
            "extract_header": _bool_parameter(context, "mistral_extract_header", False),
            "extract_footer": _bool_parameter(context, "mistral_extract_footer", False),
            "tesseract_verify": _bool_parameter(context, "ocr_tesseract_verify", True),
            "tesseract_verify_threshold": _parameter(context, "ocr_tesseract_verify_threshold", "0.90"),
        })
    if engine == "gemini":
        key_selector = _parameter(context, "gemini_api_key", "")
        key_file = _resolve_key_file(context.paths.root, "gemini", key_selector)
        tier = _gemini_service_tier_parameter(context)
        return with_tesseract_2pass({
            "model": _provider_model_parameter(context, "gemini", "gemini_model", "gemini-3.5-flash"),
            "api_key_file": str(key_file),
            "prompt": _vision_ocr_prompt(context),
            "timeout_sec": 600 if tier == "flex" else 60,
            "max_retries": 3,
            "use_stream": _bool_parameter(context, "gemini_use_stream", True),
            "service_tier": tier,
        })
    if engine == "chatgpt":
        key_selector = _parameter(context, "openai_api_key", "")
        key_file = _resolve_key_file(context.paths.root, "openai", key_selector)
        return with_tesseract_2pass({
            "model": _provider_model_parameter(context, "openai", "openai_model", "gpt-4.1"),
            "api_key_file": str(key_file),
            "prompt": _vision_ocr_prompt(context),
            "timeout_sec": 180,
            "max_retries": 3,
            "reasoning_effort": "minimal",
            "verbosity": "medium",
        })
    return {}


def _optional_ocr_runtime_names(engine: str) -> tuple[str, ...]:
    return (engine,)


def _optional_ocr_python(root: Path, engine: str) -> Path:
    optional_root = root / "tools" / "optional-ocr-engines"
    candidates = [optional_root / name / "runtime" / "python.exe" for name in _optional_ocr_runtime_names(engine)]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _optional_ocr_import_status(root: Path, engine: str, modules: tuple[str, ...]) -> dict[str, object]:
    python = _optional_ocr_python(root, engine)
    status: dict[str, object] = {
        "path": str(python),
        "exists": python.exists(),
        "runtime_candidates": list(_optional_ocr_runtime_names(engine)),
        "modules": list(modules),
        "ok": False,
        "optional": True,
    }
    if not python.exists():
        status["error"] = "optional portable runtime is not installed"
        return status
    code = (
        "import importlib.util, json, sys; "
        f"mods={list(modules)!r}; "
        "missing=[m for m in mods if importlib.util.find_spec(m) is None]; "
        "print(json.dumps({'missing': missing, 'version': sys.version.split()[0]})); "
        "sys.exit(1 if missing else 0)"
    )
    proc = subprocess.run(
        [str(python), "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    payload: dict[str, object] = {}
    try:
        payload = json.loads((proc.stdout or "{}").strip() or "{}")
    except json.JSONDecodeError:
        payload = {}
    missing = payload.get("missing") if isinstance(payload.get("missing"), list) else []
    status["missing"] = missing
    status["version"] = str(payload.get("version", ""))
    status["ok"] = proc.returncode == 0 and not missing
    if proc.returncode != 0:
        status["error"] = (proc.stderr or proc.stdout or "optional runtime import check failed").strip()
    return status


def _ensure_heavy_engine_ready(context: JobContext, engine: str) -> None:
    import requests

    required = {
        "surya": ("surya", "torch"),
    }.get(engine, ())
    status = _optional_ocr_import_status(context.paths.root, engine, required)
    if not bool(status.get("ok")):
        missing = status.get("missing") or required
        raise RuntimeError(
            f"{engine} optional portable runtime is not ready: {missing}. "
            "Run Project tools -> Install optional OCR engines first."
        )
    try:
        response = requests.get("http://127.0.0.1:8771/health", timeout=2)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(
            f"{engine} requires the warm layout service on 127.0.0.1:8771. "
            "Start system_core/ocr_brick/Layout.Service.ps1 -Enable first."
        ) from exc


def _write_ocr_brick_outputs(
    context: JobContext,
    source: Path,
    results: list[dict[str, object]],
    formats: set[str] | None = None,
) -> None:
    stem = source.stem
    selected = set(formats or {"json", "markdown"})
    if not selected:
        selected = {"json"}
    out_json = context.paths.output / f"{stem}.ocr_brick.json"
    out_md = context.paths.output / f"{stem}.ocr_brick.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    if "json" in selected:
        out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        context.log(f"[OCR BRICK] wrote {out_json.relative_to(context.paths.root)}")
    if "markdown" in selected:
        chunks: list[str] = [f"# OCR Brick: {source.name}", ""]
        for result in results:
            page = result.get("page", 0)
            text = str(result.get("text") or "").strip()
            chunks.extend([f"## Page {int(page) + 1}", "", text, ""])
        out_md.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")
        context.log(f"[OCR BRICK] wrote {out_md.relative_to(context.paths.root)}")
    if "verification" in selected:
        verification_pages = [
            {"page": int(result.get("page", 0)), **dict(result.get("verification") or {})}
            for result in results
            if isinstance(result.get("verification"), dict)
        ]
        if verification_pages:
            verification_json = context.paths.output / f"{stem}.verification.json"
            verification_md = context.paths.output / f"{stem}.verification.md"
            verification_json.write_text(
                json.dumps(verification_pages, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            lines = [f"# OCR verification: {source.name}", ""]
            for item in verification_pages:
                lines.extend([
                    f"## Page {int(item['page']) + 1}",
                    "",
                    f"- Status: `{item.get('status', 'insufficient')}`",
                    f"- Numeric agreement: `{float(item.get('numeric_agreement') or 0):.1%}`",
                    f"- Text Jaccard: `{float(item.get('text_jaccard') or 0):.1%}`",
                    f"- Threshold: `{float(item.get('threshold') or 0):.1%}`",
                    "",
                    "### Missing in Tesseract",
                    "",
                ])
                missing = item.get("missing_in_tesseract") or []
                lines.extend(
                    f"- `{entry.get('token')}` × {entry.get('count')}" for entry in missing if isinstance(entry, dict)
                )
                if not missing:
                    lines.append("- None")
                lines.extend(["", "### Extra in Tesseract", ""])
                extra = item.get("extra_in_tesseract") or []
                lines.extend(
                    f"- `{entry.get('token')}` × {entry.get('count')}" for entry in extra if isinstance(entry, dict)
                )
                if not extra:
                    lines.append("- None")
                lines.append("")
            verification_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            context.log(f"[OCR VERIFY] wrote {verification_json.relative_to(context.paths.root)}")
            context.log(f"[OCR VERIFY] wrote {verification_md.relative_to(context.paths.root)}")


def ocr_brick_status(context: JobContext) -> dict[str, object]:
    checks: dict[str, object] = {}
    for module_name in ("cv2", "numpy", "fitz", "requests", "fastapi", "uvicorn", "PIL"):
        try:
            module = __import__(module_name)
            checks[module_name] = {"ok": True, "version": str(getattr(module, "__version__", ""))}
        except Exception as exc:
            checks[module_name] = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
            if module_name == "cv2":
                checks[module_name]["optional"] = True
                checks[module_name]["fallback"] = "PIL/NumPy basic CPU preprocess"

    checks["surya_runtime"] = _optional_ocr_import_status(
        context.paths.root,
        "surya",
        ("surya", "torch"),
    )
    checks["surya_runtime"]["note"] = "optional portable Surya OCR/layout runtime"

    tesseract = _tesseract_exe(context)
    realesrgan = _realesrgan_exe(context.paths.root)
    llamacpp = context.paths.root / "tools" / "llama.cpp" / "llama-server.exe"
    yandex_key = _provider_default_key_file(context.paths.root, "yandex")
    xai_key = _provider_default_key_file(context.paths.root, "xai")
    mistral_key = _provider_default_key_file(context.paths.root, "mistral")
    yandex_folder = _yandex_folder_file(context.paths.root)
    yandex_key_id = _yandex_key_id_file(context.paths.root)
    checks["tesseract"] = {"path": tesseract, "exists": Path(tesseract).exists() if tesseract != "tesseract" else bool(shutil.which("tesseract"))}
    checks["realesrgan_ncnn_vulkan"] = {"path": str(realesrgan) if realesrgan else "", "exists": bool(realesrgan)}
    checks["llama_server"] = {"path": str(llamacpp), "exists": llamacpp.exists(), "optional": True, "note": "required by Surya CPU/llama.cpp backend"}
    checks["yandex_key"] = {"path": _safe_key_label(context.paths.root, yandex_key), "present": bool(_read_key(yandex_key))}
    checks["yandex_key_id"] = {"path": _safe_key_label(context.paths.root, yandex_key_id), "present": bool(_read_key(yandex_key_id))}
    checks["xai_key"] = {"path": _safe_key_label(context.paths.root, xai_key), "present": bool(_read_key(xai_key))}
    checks["mistral_key"] = {"path": _safe_key_label(context.paths.root, mistral_key), "present": bool(_read_key(mistral_key))}
    folder_file_value = _read_key(yandex_folder)
    checks["yandex_folder"] = {
        "path": _safe_key_label(context.paths.root, yandex_folder),
        "present": bool(folder_file_value),
        "inferred": bool(_yandex_folder_id(context.paths.root)) and not bool(folder_file_value),
    }

    vulkaninfo = shutil.which("vulkaninfo")
    if vulkaninfo:
        proc = subprocess.run([vulkaninfo, "--summary"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        devices = [line.strip() for line in proc.stdout.splitlines() if line.strip().startswith("deviceName")]
        checks["vulkan"] = {"ok": proc.returncode == 0, "devices": devices}
    else:
        checks["vulkan"] = {"ok": False, "devices": []}

    for key, value in checks.items():
        context.log(f"[OCR BRICK STATUS] {key}: {value}")
    context.progress(1.0)
    return checks


def ocr_brick_run(context: JobContext) -> dict[str, object]:
    from system_core.document_exporters import export_document_model
    from system_core.document_model import create_document_model
    from system_core.ocr_brick.pipeline_controller import JobRequest, PipelineController
    from system_core.ocr_brick.sr_client import SRClient

    mirror = _prepare_mirror_context(context)
    engine = _parameter(context, "ocr_engine", "tesseract")
    if engine not in {"tesseract", "surya", "yandex", "mistral", "xai", "gemini", "chatgpt"}:
        raise RuntimeError(f"Unsupported OCR engine: {engine}")
    if engine == "surya":
        _ensure_heavy_engine_ready(context, engine)

    sr_exe = _realesrgan_exe(context.paths.root)
    sr_client = None
    gpu = _parameter(context, "ocr_gpu", "auto")
    if sr_exe:
        try:
            sr_client = SRClient(sr_exe, gpu=gpu)
        except Exception as exc:
            context.log(f"[OCR BRICK] SR unavailable, continuing without upscale: {exc}")

    preprocess_profile = _parameter(context, "ocr_preprocess_profile", "auto").lower()
    if preprocess_profile not in {"auto", "raw", "heavy", "numbers", "manual"}:
        preprocess_profile = "auto"
    overrides = _ocr_brick_overrides(context, allow_sr=sr_client is not None, engine=engine)
    if preprocess_profile == "auto":
        context.log(f"[OCR BRICK] Preprocess profile=auto; using engine defaults for {engine}.")
    else:
        context.log(f"[OCR BRICK] Preprocess profile={preprocess_profile}; overrides={json.dumps(overrides, ensure_ascii=False, sort_keys=True)}")
    params = _ocr_engine_params(context, engine)
    if bool(params.get("tesseract_2pass")):
        context.log(
            "[OCR BRICK] Tesseract 2-pass enabled: "
            f"lang={params.get('tesseract_2pass_lang')}, "
            f"psm={params.get('tesseract_2pass_psm')}, "
            f"hint={'yes' if params.get('tesseract_2pass_hint') else 'no'}"
        )
    if str(params.get("secondary_pass") or "") in {"yandex", "yandex_tesseract"}:
        context.log(
            "[OCR BRICK] Yandex second pass enabled: "
            f"scope={params.get('yandex_2pass_scope')}, "
            f"model={params.get('yandex_2pass_model')}, "
            f"fusion={'yes' if params.get('yandex_fusion') else 'no'}"
        )
    output_mode = _parameter(context, "ocr_output_contract", "text")
    if output_mode not in {"text", "structured"}:
        output_mode = "text"
    if engine == "mistral" and str(params.get("secondary_pass") or "none") != "none" and output_mode == "structured":
        output_mode = "text"
        context.log("[OCR BRICK] Ensemble mode uses the text contract; Mistral layout is restored from its saved raw page.")
    allowed_formats = {
        "docx", "searchable_pdf", "xlsx", "odt", "markdown", "html",
        "json", "verification", "archive",
    }
    output_formats = {
        item
        for item in _list_parameter(context, "ocr_output_formats", ("docx",))
        if item in allowed_formats
    }
    if not output_formats:
        output_formats = {"json"}
    if (
        "searchable_pdf" in output_formats
        and engine in {"yandex", "mistral", "xai", "gemini", "chatgpt"}
        and not bool(params.get("tesseract_2pass"))
        and not (
            engine == "mistral"
            and str(params.get("secondary_pass") or "none") in {"none", "yandex"}
        )
    ):
        params.update({
            "tesseract_2pass": True,
            "tesseract_2pass_lang": _parameter(context, "ocr_tesseract_2pass_lang", "rus+eng"),
            "tesseract_2pass_psm": _int_parameter(context, "ocr_tesseract_2pass_psm", 6),
            "tesseract_2pass_hint": False,
        })
        context.log("[OCR BRICK] Searchable PDF selected: local Tesseract coordinate layer enabled automatically.")

    controller = PipelineController(
        context.paths.root,
        sr=sr_client,
        tesseract_exe=_tesseract_exe(context),
        layout_base_url="http://127.0.0.1:8771",
    )
    sources = _ocr_brick_sources(context.paths.input)
    if not sources:
        context.log("[OCR BRICK] No supported PDF/image files found in input.")
        context.progress(1.0)
        _sync_destination(context, mirror)
        _write_mirror_report(context, mirror)
        return {"exit_code": 0, "files": 0, "pages": 0, "engine": engine}

    pages_total = 0
    for index, source in enumerate(sources, start=1):
        if context.cancelled():
            raise RuntimeError("Operation cancelled by user.")
        context.log(f"[OCR BRICK] {source.relative_to(context.paths.root)} -> engine={engine}")
        package_dir = context.paths.output / f"{source.stem}.document"
        req = JobRequest(
            source_path=str(source),
            engine=engine,
            gui_overrides=overrides,
            engine_params=params,
            output=output_mode,
            asset_dir=str(package_dir / "pages"),
        )
        results = controller.run_job(req, job_id=context.report_dir.name)
        pages_total += len(results)
        for page_result in results:
            fusion = page_result.get("fusion")
            if not isinstance(fusion, dict):
                continue
            for geometry in fusion.get("physical_geometry") or []:
                context.log(
                    "[TABLE GEOMETRY] "
                    f"page={int(page_result.get('page') or 0) + 1}, "
                    f"status={geometry.get('reason')}, "
                    f"rows={geometry.get('rows', geometry.get('physical_rows', 0))}, "
                    f"cols={geometry.get('cols', geometry.get('physical_cols', 0))}, "
                    f"cells={geometry.get('cells', 0)}, "
                    f"numbering_score={geometry.get('numbering_score', 0)}"
                )
            context.log(
                "[OCR FUSION] "
                f"page={int(page_result.get('page') or 0) + 1}, "
                f"replaced={fusion.get('replaced_items', 0)}, "
                f"review={fusion.get('review_items', 0)}, "
                f"tesseract_anchors={fusion.get('coordinate_anchors', 0)}"
            )
        model = create_document_model(
            source,
            results,
            package_dir,
            engine=engine,
            preprocess=overrides,
            engine_params=params,
        )
        produced = export_document_model(
            model,
            package_dir,
            context.paths.output,
            output_formats,
            stem=source.stem,
        )
        context.log(
            f"[DOCUMENT MODEL] {package_dir.relative_to(context.paths.root)}; "
            f"exports={', '.join(sorted(produced)) or 'none'}"
        )
        context.progress(index / max(1, len(sources)))

    _sync_destination(context, mirror)
    _write_mirror_report(context, mirror)
    return {
        "exit_code": 0,
        "files": len(sources),
        "pages": pages_total,
        "engine": engine,
        "output": output_mode,
        "formats": sorted(output_formats),
    }


def _benchmark_source(context: JobContext) -> Path:
    raw = _parameter(context, "benchmark_source", "")
    source, _explicit = _resolve_user_path(context, raw, context.paths.input)
    if source.is_dir():
        sources = _ocr_brick_sources(source)
        if not sources:
            raise RuntimeError(f"No PDF/image files found for one-page OCR check: {source}")
        return sources[0]
    if not source.exists():
        raise RuntimeError(f"One-page OCR check source does not exist: {source}")
    return source


def _csv(items: list[str]) -> str:
    return ",".join(dict.fromkeys(item for item in items if item))


def ocr_quality_benchmark(context: JobContext) -> dict[str, object]:
    from system_core.ocr_brick.benchmark_quality import run_benchmark

    source = _benchmark_source(context)
    local_engines = [
        engine
        for engine in _list_parameter(context, "benchmark_local_engines", ("tesseract", "surya"))
        if engine in {"tesseract", "surya"}
    ]
    include_api = _bool_parameter(context, "benchmark_include_api", False)
    api_engines = []
    if include_api:
        api_engines = [
            engine
            for engine in _list_parameter(context, "benchmark_api_engines", ("yandex", "mistral", "xai", "gemini", "chatgpt"))
            if engine in {"yandex", "mistral", "xai", "gemini", "chatgpt"}
        ]

    engines = [*local_engines, *api_engines]
    if not engines:
        raise RuntimeError("Select at least one local engine, or enable API models and select an API engine.")

    variants = _list_parameter(context, "benchmark_variants", ("raw", "clean"))
    variants = [item for item in variants if item in {"raw", "clean"}] or ["clean"]
    out_dir = context.paths.workspace / "ocr_quality_benchmark" / context.report_dir.name

    context.log(f"[OCR BENCH] source={source}")
    context.log(f"[OCR BENCH] page={_int_parameter(context, 'benchmark_page', 1)}")
    context.log(f"[OCR BENCH] local engines={_csv(local_engines) or '(none)'}")
    context.log(f"[OCR BENCH] API models={'enabled' if include_api else 'disabled'}")
    if include_api:
        context.log(f"[OCR BENCH] API engines={_csv(api_engines) or '(none)'}")
    else:
        context.log("[OCR BENCH] paid API engines are excluded by the checkbox.")

    args = Namespace(
        root=str(context.paths.root),
        source=str(source),
        out=str(out_dir),
        page=_int_parameter(context, "benchmark_page", 1),
        dpi=_int_parameter(context, "benchmark_dpi", 300),
        engines=_csv(engines),
        variants=_csv(variants),
        sr_scale=_int_parameter(context, "ocr_sr_scale", 0),
        sr_model=_parameter(context, "ocr_sr_model", "auto"),
        sr_gpu=_parameter(context, "ocr_gpu", "auto"),
        denoise=_parameter(context, "ocr_denoise", "weak"),
        contrast=_parameter(context, "ocr_contrast", "auto"),
        unsharp=_parameter(context, "ocr_unsharp", "auto"),
        binarize=_parameter(context, "ocr_binarize", "auto"),
        deskew=_bool_parameter(context, "ocr_deskew", True),
        strip_vlines=_bool_parameter(context, "ocr_strip_vlines", False),
        tesseract_lang=_parameter(context, "ocr_tesseract_lang", "rus+eng"),
        tesseract_psm=_int_parameter(context, "ocr_tesseract_psm", 6),
        surya_backend=_parameter(context, "surya_backend", "llamacpp"),
        yandex_model=_parameter(context, "yandex_model", "page"),
        yandex_languages=_parameter(context, "yandex_languages", "ru,en"),
        xai_model=_parameter(context, "xai_model", "grok-4.3"),
        mistral_model=_parameter(context, "mistral_model", "mistral-ocr-4-0"),
        gemini_model=_provider_model_parameter(context, "gemini", "gemini_model", "gemini-3.5-flash"),
        gemini_use_stream=_bool_parameter(context, "gemini_use_stream", True),
        gemini_service_tier=_gemini_service_tier_parameter(context),
        openai_model=_provider_model_parameter(context, "openai", "openai_model", "gpt-4.1"),
        xai_api_key_file=str(_resolve_key_file(context.paths.root, "xai", _parameter(context, "xai_api_key", ""))),
        mistral_api_key_file=str(_resolve_key_file(context.paths.root, "mistral", _parameter(context, "mistral_api_key", ""))),
        gemini_api_key_file=str(_resolve_key_file(context.paths.root, "gemini", _parameter(context, "gemini_api_key", ""))),
        openai_api_key_file=str(_resolve_key_file(context.paths.root, "openai", _parameter(context, "openai_api_key", ""))),
        yandex_api_key_file=str(_resolve_key_file(context.paths.root, "yandex", _parameter(context, "yandex_api_key", ""))),
        yandex_folder_file=str(_yandex_folder_file(context.paths.root)),
        prompt_file=str(context.paths.root / "config" / "ocr_prompt_vision_ocr.md"),
        skip_unavailable=True,
    )
    report = run_benchmark(args)
    context.progress(1.0)
    context.log(f"[OCR BENCH] JSON: {Path(report['json']).relative_to(context.paths.root)}")
    context.log(f"[OCR BENCH] Markdown: {Path(report['markdown']).relative_to(context.paths.root)}")
    context.log(f"[OCR BENCH] results={len(report.get('results', []))}, errors={len(report.get('errors', []))}")
    return {
        "exit_code": 0,
        "source": str(source),
        "page": args.page,
        "include_api": include_api,
        "engines": engines,
        "variants": variants,
        "json": report["json"],
        "markdown": report["markdown"],
        "results": len(report.get("results", [])),
        "errors": len(report.get("errors", [])),
    }


def _parse_page_spec(spec: str, total_pages: int) -> list[int]:
    text = str(spec or "all").strip().lower()
    if not text or text in {"all", "*", "все"}:
        return list(range(total_pages))
    pages: set[int] = set()
    for part in re.split(r"[,;\s]+", text):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start = max(1, int(left.strip()))
            end = min(total_pages, int(right.strip()))
            pages.update(range(start - 1, end))
        else:
            value = int(part)
            if 1 <= value <= total_pages:
                pages.add(value - 1)
    return sorted(pages)


def _safe_batch_key(source: Path, page_index: int) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", source.stem).strip("._-") or "document"
    return f"{stem}_page_{page_index + 1:04d}"


def _model_dump_jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)  # type: ignore[no-any-return]
    if isinstance(value, dict):
        return {str(k): _model_dump_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_model_dump_jsonable(item) for item in value]
    return value


def _gemini_batch_latest_file(root: Path) -> Path:
    return root / "workspace" / "gemini_batch" / "latest.json"


def _gemini_batch_load_manifest(root: Path, manifest_hint: str = "") -> dict[str, object]:
    path = Path(manifest_hint) if manifest_hint else _gemini_batch_latest_file(root)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        raise RuntimeError(f"Gemini Batch manifest was not found: {path}")
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def _gemini_batch_text_from_response(payload: dict[str, object]) -> str:
    response = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(response, dict):
        return ""
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0] if isinstance(candidates[0], dict) else {}
    content = first.get("content") if isinstance(first, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""
    chunks = []
    for part in parts:
        if isinstance(part, dict) and part.get("text"):
            chunks.append(str(part["text"]))
    return "".join(chunks).strip()


def _gemini_batch_result_key(payload: dict[str, object], fallback: str) -> str:
    direct = payload.get("key")
    if direct:
        return str(direct)
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get("key"):
        return str(metadata["key"])
    return fallback


def _write_gemini_batch_outputs(
    context: JobContext,
    manifest: dict[str, object],
    result_lines: list[dict[str, object]],
) -> dict[str, object]:
    output_dir = Path(str(manifest.get("output_dir") or ""))
    if not output_dir.is_absolute():
        output_dir = context.paths.root / output_dir
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    request_map = {
        str(item.get("key")): item
        for item in manifest.get("requests", [])
        if isinstance(item, dict) and item.get("key")
    }
    by_source: dict[str, list[tuple[int, str]]] = {}
    errors: list[dict[str, object]] = []
    written = 0

    for index, item in enumerate(result_lines, start=1):
        key = _gemini_batch_result_key(item, f"response_{index:04d}")
        text = _gemini_batch_text_from_response(item)
        if not text:
            errors.append({"key": key, "error": item.get("error") or "empty response"})
            continue
        page_path = pages_dir / f"{key}.md"
        page_path.write_text(text.rstrip() + "\n", encoding="utf-8")
        written += 1
        request = request_map.get(key, {})
        source = str(request.get("source") or "batch")
        page = int(request.get("page") or index)
        by_source.setdefault(source, []).append((page, text))

    assembled: list[str] = []
    for source, pages in sorted(by_source.items()):
        source_path = Path(source)
        md_path = output_dir / f"{source_path.stem or 'document'}_gemini_batch.md"
        chunks = [f"# Gemini Batch OCR: {source_path.name}", ""]
        for page, text in sorted(pages):
            chunks.extend([f"## Page {page}", "", text.strip(), ""])
        md_path.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")
        assembled.append(str(md_path))

    summary = {
        "output_dir": str(output_dir),
        "pages_written": written,
        "assembled_markdown": assembled,
        "errors": errors,
    }
    (output_dir / "collect_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def gemini_batch_create(context: JobContext) -> dict[str, object]:
    from google import genai
    from google.genai import types
    from system_core.ocr_brick import cleanconfig, preprocess
    from system_core.ocr_brick.cache import Cache
    from system_core.ocr_brick.sr_client import SRClient

    raw_source = _parameter(context, "gemini_batch_source", "input")
    source, _explicit = _resolve_user_path(context, raw_source, context.paths.input)
    sources = _ocr_brick_sources(source)
    if not sources:
        raise RuntimeError(f"No PDF/image files found for Gemini Batch source: {source}")

    key_selector = _parameter(context, "gemini_api_key", "")
    key_file = _resolve_key_file(context.paths.root, "gemini", key_selector)
    api_key = _read_key(key_file)

    model = _provider_model_parameter(context, "gemini", "gemini_model", "gemini-3.5-flash")
    prompt = _vision_ocr_prompt(context)
    dpi = _int_parameter(context, "gemini_batch_dpi", 300)
    page_spec = _parameter(context, "gemini_batch_pages", "all")
    profile = _parameter(context, "gemini_batch_preprocess_profile", "raw").lower()
    if profile not in {"raw", "auto", "heavy", "numbers"}:
        profile = "raw"
    submit = _bool_parameter(context, "gemini_batch_submit", False)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = context.paths.workspace / "gemini_batch" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "requests.jsonl"
    manifest_path = output_dir / "manifest.json"

    profiles = cleanconfig.load_profiles(context.paths.root / "system_core" / "ocr_brick" / "preprocess.profiles.json")
    cache = Cache(context.paths.root / "cache" / "gemini_batch" / run_id, max_bytes=10 * 1024**3)
    sr_client = None
    sr_exe = _realesrgan_exe(context.paths.root)
    if profile != "raw" and sr_exe:
        try:
            sr_client = SRClient(sr_exe, gpu=_parameter(context, "ocr_gpu", "auto"))
        except Exception as exc:
            context.log(f"[GEMINI BATCH] SR unavailable, continuing without upscale: {exc}")

    requests_meta: list[dict[str, object]] = []
    total_selected = 0
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for source_index, item in enumerate(sources, start=1):
            context.log(f"[GEMINI BATCH] rasterize {item}")
            pages = preprocess.rasterize(item, dpi=dpi)
            selected_pages = _parse_page_spec(page_spec, len(pages))
            for page_index in selected_pages:
                page_png = pages[page_index]
                overrides = _ocr_brick_profile_overrides(profile, "gemini")
                cfg = cleanconfig.resolve(profiles, target_engine="vision", gui_overrides=overrides, original_name=str(item))
                clean_png = preprocess.clean_page(page_png, cfg, cache=cache, sr=sr_client)
                key = _safe_batch_key(item, page_index)
                payload = {
                    "key": key,
                    "request": {
                        "contents": [
                            {
                                "role": "user",
                                "parts": [
                                    {"text": prompt},
                                    {
                                        "inline_data": {
                                            "mime_type": "image/png",
                                            "data": base64.b64encode(clean_png).decode("ascii"),
                                        }
                                    },
                                ],
                            }
                        ],
                        "system_instruction": {
                            "parts": [
                                {"text": "You are a careful OCR transcription engine. Do not summarize."}
                            ]
                        },
                        "generation_config": {"temperature": 0.0},
                    },
                }
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                requests_meta.append(
                    {
                        "key": key,
                        "source": str(item),
                        "page": page_index + 1,
                        "profile": profile,
                    }
                )
                total_selected += 1
            context.progress(source_index / max(1, len(sources)))

    manifest: dict[str, object] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "source": str(source),
        "sources": [str(item) for item in sources],
        "page_spec": page_spec,
        "dpi": dpi,
        "preprocess_profile": profile,
        "requests_jsonl": str(jsonl_path),
        "requests": requests_meta,
        "request_count": total_selected,
        "output_dir": str(output_dir),
        "submitted": False,
        "submit_hint": "Set 'Submit to Google' in GUI to create the remote Batch API job.",
    }

    if submit:
        if not api_key:
            raise RuntimeError(f"Gemini key is empty or missing: {_safe_key_label(context.paths.root, key_file)}")
        client = genai.Client(api_key=api_key)
        display_name = f"audion-ocr-{run_id}"
        context.log(f"[GEMINI BATCH] upload JSONL: {jsonl_path.name} ({jsonl_path.stat().st_size} bytes)")
        uploaded = client.files.upload(
            file=str(jsonl_path),
            config=types.UploadFileConfig(display_name=display_name, mime_type="jsonl"),
        )
        context.log(f"[GEMINI BATCH] uploaded file: {uploaded.name}")
        job = client.batches.create(
            model=model,
            src=uploaded.name,
            config={"display_name": display_name},
        )
        manifest.update(
            {
                "submitted": True,
                "uploaded_file": _model_dump_jsonable(uploaded),
                "job": _model_dump_jsonable(job),
                "job_name": getattr(job, "name", ""),
                "state": getattr(getattr(job, "state", None), "name", str(getattr(job, "state", ""))),
            }
        )
        context.log(f"[GEMINI BATCH] created job: {manifest.get('job_name')}")
    else:
        context.log("[GEMINI BATCH] dry prepare only: remote job was not submitted.")

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = _gemini_batch_latest_file(context.paths.root)
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps({"manifest": str(manifest_path), "job_name": manifest.get("job_name", "")}, ensure_ascii=False, indent=2), encoding="utf-8")
    context.progress(1.0)
    context.log(f"[GEMINI BATCH] manifest: {manifest_path.relative_to(context.paths.root)}")
    context.log(f"[GEMINI BATCH] requests: {total_selected}")
    return {
        "exit_code": 0,
        "submitted": submit,
        "request_count": total_selected,
        "manifest": str(manifest_path),
        "job_name": manifest.get("job_name", ""),
    }


def gemini_batch_collect(context: JobContext) -> dict[str, object]:
    from google import genai

    key_selector = _parameter(context, "gemini_api_key", "")
    key_file = _resolve_key_file(context.paths.root, "gemini", key_selector)
    api_key = _read_key(key_file)
    if not api_key:
        raise RuntimeError(f"Gemini key is empty or missing: {_safe_key_label(context.paths.root, key_file)}")

    manifest_hint = _parameter(context, "gemini_batch_manifest", "")
    latest_payload = {}
    if not manifest_hint:
        latest_file = _gemini_batch_latest_file(context.paths.root)
        if latest_file.is_file():
            latest_payload = json.loads(latest_file.read_text(encoding="utf-8", errors="ignore"))
            manifest_hint = str(latest_payload.get("manifest") or "")
    manifest = _gemini_batch_load_manifest(context.paths.root, manifest_hint)
    job_name = _parameter(context, "gemini_batch_job_name", "") or str(manifest.get("job_name") or latest_payload.get("job_name") or "")
    if not job_name:
        raise RuntimeError("Gemini Batch job name is empty. Create a submitted batch job first.")

    client = genai.Client(api_key=api_key)
    job = client.batches.get(name=job_name)
    state = getattr(getattr(job, "state", None), "name", str(getattr(job, "state", "")))
    output_dir = Path(str(manifest.get("output_dir") or context.paths.workspace / "gemini_batch" / "unknown"))
    if not output_dir.is_absolute():
        output_dir = context.paths.root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    status_payload = {
        "job_name": job_name,
        "state": state,
        "job": _model_dump_jsonable(job),
    }
    status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    context.log(f"[GEMINI BATCH] state={state}")
    context.log(f"[GEMINI BATCH] status: {status_path.relative_to(context.paths.root)}")

    terminal = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}
    if state not in terminal:
        context.progress(1.0)
        return {"exit_code": 0, "state": state, "status": str(status_path), "done": False}

    result_lines: list[dict[str, object]] = []
    dest = getattr(job, "dest", None)
    file_name = str(getattr(dest, "file_name", "") or "") if dest is not None else ""
    if state == "JOB_STATE_SUCCEEDED" and file_name:
        context.log(f"[GEMINI BATCH] download results: {file_name}")
        content = client.files.download(file=file_name)
        result_path = output_dir / "results.jsonl"
        result_path.write_bytes(content)
        for line in content.decode("utf-8", errors="replace").splitlines():
            if line.strip():
                result_lines.append(json.loads(line))
        summary = _write_gemini_batch_outputs(context, manifest, result_lines)
        context.progress(1.0)
        return {
            "exit_code": 0,
            "state": state,
            "done": True,
            "status": str(status_path),
            "results_jsonl": str(result_path),
            **summary,
        }

    inline_responses = getattr(dest, "inlined_responses", None) if dest is not None else None
    if state == "JOB_STATE_SUCCEEDED" and inline_responses:
        for index, item in enumerate(inline_responses, start=1):
            dumped = _model_dump_jsonable(item)
            if isinstance(dumped, dict):
                result_lines.append(dumped)
            else:
                result_lines.append({"key": f"response_{index:04d}", "response": {}})
        summary = _write_gemini_batch_outputs(context, manifest, result_lines)
        context.progress(1.0)
        return {"exit_code": 0, "state": state, "done": True, "status": str(status_path), **summary}

    context.progress(1.0)
    return {"exit_code": 0, "state": state, "done": True, "status": str(status_path), "error": str(getattr(job, "error", ""))}


def _numeric_check_source(context: JobContext) -> Path:
    raw = _parameter(context, "numeric_source", "")
    source, _explicit = _resolve_user_path(context, raw, context.paths.input)
    if source.is_dir():
        sources = _ocr_brick_sources(source)
        if not sources:
            raise RuntimeError(f"No PDF/image files found for numeric check: {source}")
        return sources[0]
    if not source.exists():
        raise RuntimeError(f"Numeric check source does not exist: {source}")
    return source


def numeric_check_pass(context: JobContext) -> dict[str, object]:
    from system_core.ocr_brick.numeric_check import run_numeric_check

    source = _numeric_check_source(context)
    out_dir = context.paths.workspace / "numeric_check" / context.report_dir.name
    model = _parameter(context, "xai_model", "grok-4.3")
    key_file = _resolve_key_file(context.paths.root, "xai", _parameter(context, "xai_api_key", ""))

    context.log(f"[NUMERIC CHECK] source={source}")
    context.log(f"[NUMERIC CHECK] page={_int_parameter(context, 'numeric_page', 1)}")
    context.log(f"[NUMERIC CHECK] model={model}")
    context.log(f"[NUMERIC CHECK] locator={_parameter(context, 'numeric_locator', 'auto')}")
    context.log(f"[NUMERIC CHECK] locator hint={'enabled' if _bool_parameter(context, 'numeric_locator_hint', True) else 'disabled'}")

    args = Namespace(
        root=str(context.paths.root),
        source=str(source),
        out=str(out_dir),
        page=_int_parameter(context, "numeric_page", 1),
        dpi=_int_parameter(context, "numeric_dpi", 300),
        provider="xai",
        model=model,
        locator=_parameter(context, "numeric_locator", "auto"),
        xai_api_key_file=str(key_file),
        tesseract_exe=str(context.paths.root / "runtime" / "tesseract" / "tesseract.exe"),
        tesseract_lang=_parameter(context, "ocr_tesseract_lang", "rus+eng"),
        tesseract_psm=_int_parameter(context, "ocr_tesseract_psm", 6),
        surya_backend=_parameter(context, "surya_backend", "llamacpp"),
        surya_timeout_sec=_int_parameter(context, "surya_timeout_sec", 900),
        min_digits=_int_parameter(context, "numeric_min_digits", 8),
        max_candidates=_int_parameter(context, "numeric_max_candidates", 6),
        denoise=_parameter(context, "ocr_denoise", "weak"),
        contrast=_parameter(context, "ocr_contrast", "high"),
        unsharp=_parameter(context, "ocr_unsharp", "strong"),
        binarize=_parameter(context, "ocr_binarize", "off"),
        deskew=_bool_parameter(context, "ocr_deskew", True),
        locator_hint=_bool_parameter(context, "numeric_locator_hint", True),
        prompt="",
    )
    report = run_numeric_check(args)
    status_counts: dict[str, int] = {}
    for check in report.get("checks", []):
        if isinstance(check, dict):
            status = str(check.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

    context.progress(1.0)
    context.log(f"[NUMERIC CHECK] JSON: {Path(report['json']).relative_to(context.paths.root)}")
    context.log(f"[NUMERIC CHECK] Markdown: {Path(report['markdown']).relative_to(context.paths.root)}")
    context.log(f"[NUMERIC CHECK] locator used={report.get('locator')}")
    if report.get("locator_error"):
        context.log(f"[NUMERIC CHECK] locator note={report.get('locator_error')}")
    context.log(f"[NUMERIC CHECK] statuses={status_counts}")
    context.log(f"[NUMERIC CHECK] cost estimate=${float(report.get('total_cost_usd_estimate') or 0.0):.8f}")
    return {
        "exit_code": 0,
        "source": str(source),
        "page": args.page,
        "model": model,
        "locator": report.get("locator"),
        "locator_error": report.get("locator_error"),
        "json": report["json"],
        "markdown": report["markdown"],
        "candidates": len(report.get("candidates", [])),
        "checks": len(report.get("checks", [])),
        "statuses": status_counts,
        "cost_usd_estimate": report.get("total_cost_usd_estimate"),
    }


def _clean_registry_font_name(name: object) -> str:
    text = str(name or "").strip()
    for suffix in (
        " (TrueType Collection)",
        " (TrueType)",
        " (OpenType)",
        " (Type 1)",
        " (Raster)",
    ):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return " ".join(text.split())


def _system_font_names() -> list[str]:
    names: list[str] = list(COMMON_FONT_NAMES)
    if os.name == "nt":
        try:
            import winreg

            keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
            ]
            for hive, key_name in keys:
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        index = 0
                        while True:
                            try:
                                value_name, _value, _kind = winreg.EnumValue(key, index)
                            except OSError:
                                break
                            index += 1
                            clean = _clean_registry_font_name(value_name)
                            if clean:
                                names.append(clean)
                except OSError:
                    continue
        except Exception:
            pass

    unique: dict[str, str] = {}
    for name in names:
        clean = _clean_registry_font_name(name)
        if clean:
            unique.setdefault(clean.lower(), clean)
    return sorted(unique.values(), key=str.lower)


def font_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, str]]:
    return [{"value": name, "label": name, "label_ru": name} for name in _system_font_names()]


def _resolve_user_path(context: JobContext, raw: str, default: Path) -> tuple[Path, bool]:
    text = str(raw or "").strip().strip('"')
    if not text:
        return default.resolve(), False
    path = Path(os.path.expandvars(text)).expanduser()
    if not path.is_absolute():
        path = context.paths.root / path
    return path.resolve(), True


def _gui_path_settings(context: JobContext) -> tuple[Path, bool, Path, bool]:
    parameters = context.operation.parameters
    routed_source = str(parameters.get("_workbench_source_path", "") or "").strip()
    routed_destination = str(parameters.get("_workbench_target_path", "") or "").strip()
    if routed_source or routed_destination:
        source, source_explicit = _resolve_user_path(context, routed_source, context.paths.input)
        destination, destination_explicit = _resolve_user_path(
            context,
            routed_destination,
            context.paths.output,
        )
        return source, source_explicit, destination, destination_explicit

    data = load_yaml_or_json(context.paths.config / "gui_settings.yaml")
    gui = data.get("gui", {}) if isinstance(data, dict) else {}
    if not isinstance(gui, dict):
        gui = {}
    source, source_explicit = _resolve_user_path(context, str(gui.get("source_path", "")), context.paths.input)
    destination, destination_explicit = _resolve_user_path(
        context,
        str(gui.get("destination_path", "")),
        context.paths.output,
    )
    return source, source_explicit, destination, destination_explicit


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child_resolved = str(child.resolve())
        parent_resolved = str(parent.resolve())
        return os.path.commonpath([child_resolved, parent_resolved]) == parent_resolved
    except (OSError, ValueError):
        return False


def _paths_overlap(left: Path, right: Path) -> bool:
    return _is_inside(left, right) or _is_inside(right, left)


def _clear_managed_contents(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for item in folder.iterdir():
        if item.name == ".gitkeep":
            continue
        if item.is_symlink() or item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def _copy_tree_contents(source: Path, destination: Path, mirror: MirrorContext) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        target = destination / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        mirror.staged_files += 1
        return

    for path in sorted(source.rglob("*"), key=lambda item: str(item).lower()):
        if path.is_symlink():
            mirror.skipped.append(f"symlink skipped: {path}")
            continue
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            mirror.staged_dirs += 1
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            mirror.staged_files += 1


def _copy_output_tree(source: Path, destination: Path, mirror: MirrorContext) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*"), key=lambda item: str(item).lower()):
        if path.name == ".gitkeep":
            continue
        if path.is_symlink():
            mirror.skipped.append(f"symlink skipped: {path}")
            continue
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            mirror.synced_dirs += 1
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            mirror.synced_files += 1


def _prepare_mirror_context_from_paths(
    context: JobContext,
    source: Path,
    source_explicit: bool,
    destination: Path,
    destination_explicit: bool,
) -> MirrorContext:
    mirror = MirrorContext(
        source=source,
        destination=destination,
        source_explicit=source_explicit,
        destination_explicit=destination_explicit,
    )

    if not source.exists():
        raise RuntimeError(f"Source path does not exist: {source}")
    if source.is_symlink():
        raise RuntimeError(f"Source path is a symlink. Mirroring blocked: {source}")

    input_root = context.paths.input.resolve()
    output_root = context.paths.output.resolve()
    root = context.paths.root.resolve()

    if destination_explicit:
        if destination == root or _is_inside(root, destination):
            raise RuntimeError(f"Destination must not be the project root or its parent: {destination}")
        if destination == input_root or _is_inside(input_root, destination):
            raise RuntimeError(f"Destination must not contain the managed input folder: {destination}")
        if _paths_overlap(source, destination):
            raise RuntimeError("Source and destination must not overlap.")

    if source_explicit and source != input_root:
        if _is_inside(source, input_root):
            raise RuntimeError("A nested path inside input cannot be used as a separate mirrored source.")
        if _is_inside(input_root, source) or _is_inside(output_root, source) or _is_inside(root, source):
            raise RuntimeError("Source must not contain the project, input, or output folders.")

        context.log(f"[MIRROR] source -> input: {source} -> {input_root}")
        _clear_managed_contents(input_root)
        _clear_managed_contents(output_root)
        _copy_tree_contents(source, input_root, mirror)
        context.log(f"[MIRROR] staged files: {mirror.staged_files}, dirs: {mirror.staged_dirs}")
    else:
        context.log(f"[MIRROR] source: {input_root}")

    return mirror


def _prepare_mirror_context(context: JobContext) -> MirrorContext:
    source, source_explicit, destination, destination_explicit = _gui_path_settings(context)
    return _prepare_mirror_context_from_paths(
        context,
        source,
        source_explicit,
        destination,
        destination_explicit,
    )


def _sync_destination(context: JobContext, mirror: MirrorContext) -> None:
    output_root = context.paths.output.resolve()
    if not mirror.destination_explicit or mirror.destination == output_root:
        context.log(f"[MIRROR] destination: {output_root}")
        return

    if mirror.destination.is_symlink():
        raise RuntimeError(f"Destination path is a symlink. Mirroring blocked: {mirror.destination}")

    context.log(f"[MIRROR] output -> destination: {output_root} -> {mirror.destination}")
    _copy_output_tree(output_root, mirror.destination, mirror)
    context.log(f"[MIRROR] synced files: {mirror.synced_files}, dirs: {mirror.synced_dirs}")


def _write_mirror_report(context: JobContext, mirror: MirrorContext) -> None:
    payload = {
        "source": str(mirror.source),
        "destination": str(mirror.destination),
        "source_explicit": mirror.source_explicit,
        "destination_explicit": mirror.destination_explicit,
        "staged_files": mirror.staged_files,
        "staged_dirs": mirror.staged_dirs,
        "synced_files": mirror.synced_files,
        "synced_dirs": mirror.synced_dirs,
        "skipped": mirror.skipped,
    }
    context.report_dir.mkdir(parents=True, exist_ok=True)
    (context.report_dir / "mirror.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def project_status(context: JobContext) -> dict[str, object]:
    result = _run_script(context, "main.py", progress_seconds=20)
    return {"exit_code": result.exit_code}


def env_doctor(context: JobContext) -> dict[str, object]:
    result = _run_script(context, "doctor.py", progress_seconds=60)
    return {"exit_code": result.exit_code}


def install_tesseract(context: JobContext) -> dict[str, object]:
    script = context.paths.root / "install" / "Install-Portable-Tesseract.cmd"
    if not script.exists():
        raise RuntimeError(f"Tesseract installer was not found: {script}")

    context.log("Installing recommended project-local Tesseract OCR engine.")
    context.log("Tesseract payload/cache stays local and is ignored by Git.")
    result = run_process(
        context,
        ["cmd.exe", "/d", "/c", "call", str(script), "/NOPAUSE"],
        cwd=context.paths.root,
        progress_seconds=900,
    )
    return {"exit_code": result.exit_code, "script": str(script)}


def install_realesrgan(context: JobContext) -> dict[str, object]:
    script = context.paths.root / "install" / "Install-Portable-RealESRGAN.cmd"
    if not script.exists():
        raise RuntimeError(f"Real-ESRGAN installer was not found: {script}")

    context.log("Installing optional project-local Real-ESRGAN ncnn-vulkan engine.")
    context.log("Payload/cache stays local under install/download and tools/realesrgan-ncnn-vulkan.")
    result = run_process(
        context,
        ["cmd.exe", "/d", "/c", "call", str(script), "/NOPAUSE"],
        cwd=context.paths.root,
        progress_seconds=900,
    )
    return {"exit_code": result.exit_code, "script": str(script)}


def install_llamacpp(context: JobContext) -> dict[str, object]:
    script = context.paths.root / "install" / "Install-Portable-LlamaCpp.cmd"
    if not script.exists():
        raise RuntimeError(f"llama.cpp installer was not found: {script}")

    variant = _parameter(context, "llamacpp_variant", "vulkan")
    if variant not in {"vulkan", "cpu", "cuda124", "cuda133"}:
        variant = "vulkan"
    args = ["/NOPAUSE", "-Variant", variant]
    if _bool_parameter(context, "force_reinstall", False):
        args.append("-Force")

    context.log("Installing optional project-local llama.cpp server for Surya CPU/Vulkan backend.")
    context.log("Payload/cache stays local under install/download and tools/llama.cpp.")
    result = run_process(
        context,
        ["cmd.exe", "/d", "/c", "call", str(script), *args],
        cwd=context.paths.root,
        progress_seconds=900,
    )
    return {"exit_code": result.exit_code, "script": str(script), "variant": variant}


def install_optional_ocr_engines(context: JobContext) -> dict[str, object]:
    script = context.paths.root / "install" / "Install-Optional-OCREngines.cmd"
    if not script.exists():
        raise RuntimeError(f"Optional OCR engine installer was not found: {script}")

    engine = _parameter(context, "optional_ocr_engine", "surya")
    mode = _parameter(context, "optional_ocr_mode", "cpu")
    if engine != "surya":
        engine = "surya"
    if mode not in {"cpu", "cuda", "cuda40", "cuda50"}:
        mode = "cpu"

    args = ["/NOPAUSE", "-Engine", engine, "-Mode", mode]
    torch_index = _parameter(context, "torch_index_url", "")
    if torch_index:
        args.extend(["-TorchIndexUrl", torch_index])
    if _bool_parameter(context, "dry_run", False):
        args.append("-DryRun")
    if _bool_parameter(context, "force_reinstall", False):
        args.append("-Force")

    context.log("Installing optional Surya OCR/layout runtime.")
    context.log(f"Engine={engine}, mode={mode}; packages are installed into a portable optional engine runtime.")
    result = run_process(
        context,
        ["cmd.exe", "/d", "/c", "call", str(script), *args],
        cwd=context.paths.root,
        progress_seconds=1800,
    )
    return {"exit_code": result.exit_code, "script": str(script), "engine": engine, "mode": mode}


def check_models(context: JobContext) -> dict[str, object]:
    provider = _parameter(context, "provider", "gemini")
    key_selector = _parameter(context, "api_key", _parameter(context, f"{provider}_api_key", ""))
    extra_env, key_file = _key_env(context.paths.root, provider, key_selector)
    if provider == "xai":
        api_key = _read_key(key_file)
        if not api_key:
            raise RuntimeError(f"xAI API key is empty or missing: {_safe_key_label(context.paths.root, key_file)}")
        context.log(f"Model check: provider=xai, key={_safe_key_label(context.paths.root, key_file)}")
        models = _xai_models(api_key)
        cache_file = _write_models_cache(context.paths.root, "xai", models)
        vision_models = _xai_models(api_key, vision_only=True)
        if not vision_models:
            vision_models = list(DEFAULT_MODEL_OPTIONS.get("xai", ()))
        vision_cache_file = _write_models_cache(
            context.paths.root,
            "xai_vision",
            vision_models,
            "xAI vision models available for selected key",
        )
        for model in models:
            context.log(model)
        context.log(f"[OK] Saved to: {cache_file}")
        context.log(f"[OK] Vision selector cache: {vision_cache_file}")
        context.progress(1.0)
        return {
            "exit_code": 0,
            "provider": provider,
            "key_file": str(key_file),
            "models": len(models),
            "cache": str(cache_file),
            "vision_cache": str(vision_cache_file),
        }
    if provider == "yandex":
        api_key = _read_key(key_file)
        if not api_key:
            raise RuntimeError(f"Yandex API key is empty or missing: {_safe_key_label(context.paths.root, key_file)}")
        folder_id = _yandex_folder_id(context.paths.root)
        context.log(
            "Model check: "
            f"provider=yandex, key={_safe_key_label(context.paths.root, key_file)}, "
            f"folder={'present' if folder_id else 'missing'}"
        )
        models = _yandex_models(api_key, folder_id)
        inferred_folder = _infer_yandex_folder_id_from_models(models)
        folder_file = _yandex_folder_file(context.paths.root)
        if not _read_key(folder_file) and inferred_folder:
            folder_file.write_text(inferred_folder + "\n", encoding="utf-8")
            folder_id = inferred_folder
            context.log(f"Inferred Yandex folder id from model URIs and saved {_safe_key_label(context.paths.root, folder_file)}")
        cache_file = _write_models_cache(context.paths.root, "yandex", models)
        ocr_models = [
            model for model in models
            if model.lower() in {item.lower() for item in DEFAULT_MODEL_OPTIONS.get("yandex", ())}
            or "ocr" in model.lower()
            or "vision" in model.lower()
        ]
        if not ocr_models:
            ocr_models = list(DEFAULT_MODEL_OPTIONS.get("yandex", ()))
        ocr_cache_file = _write_models_cache(context.paths.root, "yandex_ocr", ocr_models, "Yandex OCR models available for selected key")
        for model in models:
            context.log(model)
        context.log(f"[OK] Saved to: {cache_file}")
        context.log(f"[OK] OCR selector cache: {ocr_cache_file}")
        context.progress(1.0)
        return {
            "exit_code": 0,
            "provider": provider,
            "key_file": str(key_file),
            "models": len(models),
            "cache": str(cache_file),
            "ocr_cache": str(ocr_cache_file),
        }

    script_name = "check_models_openai.py" if provider == "openai" else "check_models.py"
    context.log(f"Model check: provider={provider}, key={_safe_key_label(context.paths.root, key_file)}")
    result = _run_script(script_name=script_name, context=context, progress_seconds=60, extra_env=extra_env)
    return {"exit_code": result.exit_code, "provider": provider, "key_file": str(key_file)}


def extract_local(context: JobContext) -> dict[str, object]:
    return _run_mirrored_script(context, "extract_to_md.py", ["--local"], progress_seconds=900)




def _workbench_args(context: JobContext, *, mode: str, ai_provider: str = "none", ai_mode: str = "off") -> list[str]:
    if mode == "coordinates":
        ocr_engine = _parameter(context, "coordinate_ocr_engine", _parameter(context, "workbench_ocr_engine", "auto"))
        lang = _parameter(context, "coordinate_lang", _parameter(context, "workbench_lang", "rus+eng"))
        dpi = _parameter(context, "coordinate_dpi", _parameter(context, "workbench_dpi", "180"))
    else:
        ocr_engine = _parameter(context, "workbench_ocr_engine", "auto")
        lang = _parameter(context, "workbench_lang", "rus+eng")
        dpi = _parameter(context, "workbench_dpi", "180")
    psm = _parameter(context, "workbench_psm", "6")
    oem = _parameter(context, "workbench_oem", "1")
    low_confidence = _parameter(context, "workbench_low_confidence", "70")
    resolver_limit = _parameter(context, "ai_resolver_limit", "-1")
    provider = ai_provider if ai_provider != "none" else _parameter(context, "provider", "none")
    selected_ai_mode = _parameter(context, "ai_resolver_mode", ai_mode)
    model = _parameter(context, "model", _parameter(context, f"{provider}_model", "auto"))

    context.log(
        "Workbench settings: "
        f"mode={mode}, ocr_engine={ocr_engine}, lang={lang}, psm={psm}, oem={oem}, dpi={dpi}, "
        f"low_confidence={low_confidence}, ai_provider={provider}, ai_mode={selected_ai_mode}, "
        f"model={model}, resolver_limit={resolver_limit}"
    )
    return [
        "--mode",
        mode,
        "--report-dir",
        str(context.report_dir),
        "--ocr-engine",
        ocr_engine,
        "--lang",
        lang,
        "--psm",
        psm,
        "--oem",
        oem,
        "--dpi",
        dpi,
        "--low-confidence",
        low_confidence,
        "--ai-provider",
        provider,
        "--ai-mode",
        selected_ai_mode,
        "--model",
        model,
        "--resolver-limit",
        resolver_limit,
    ]


def workbench_review(context: JobContext) -> dict[str, object]:
    return _run_mirrored_script(
        context,
        "workbench_pipeline.py",
        _workbench_args(context, mode="review", ai_provider="none", ai_mode="off"),
        progress_seconds=900,
    )


def workbench_ai(context: JobContext) -> dict[str, object]:
    provider = _parameter(context, "provider", "openai")
    key_selector = _parameter(context, "api_key", _parameter(context, f"{provider}_api_key", ""))
    extra_env, key_file = _key_env(context.paths.root, provider, key_selector)
    context.log(f"Workbench AI resolver key: provider={provider}, key={_safe_key_label(context.paths.root, key_file)}")
    return _run_mirrored_script(
        context,
        "workbench_pipeline.py",
        _workbench_args(context, mode="ai-review", ai_provider=provider, ai_mode="review-only"),
        progress_seconds=900,
        extra_env=extra_env,
    )


def workbench_coordinates(context: JobContext) -> dict[str, object]:
    return _run_mirrored_script(
        context,
        "workbench_pipeline.py",
        _workbench_args(context, mode="coordinates", ai_provider="none", ai_mode="off"),
        progress_seconds=900,
    )


def _docx_layout_args(context: JobContext, *, default_font_size: str) -> list[str]:
    orientation = _parameter(context, "docx_orientation", "portrait")
    font_name = _parameter(context, "docx_font_name", "Arial")
    font_size = _parameter(context, "docx_font_size_pt", default_font_size)
    margin_top = _parameter(context, "docx_margin_top_mm", "20")
    margin_right = _parameter(context, "docx_margin_right_mm", "10")
    margin_bottom = _parameter(context, "docx_margin_bottom_mm", "20")
    margin_left = _parameter(context, "docx_margin_left_mm", "20")

    context.log(
        "DOCX layout: "
        f"orientation={orientation}, margins_mm={margin_top}/{margin_right}/{margin_bottom}/{margin_left}, "
        f"font={font_name}, size_pt={font_size}"
    )
    return [
        "--orientation",
        orientation,
        "--margin-top-mm",
        margin_top,
        "--margin-right-mm",
        margin_right,
        "--margin-bottom-mm",
        margin_bottom,
        "--margin-left-mm",
        margin_left,
        "--font-name",
        font_name,
        "--font-size-pt",
        font_size,
    ]


def build_docx(context: JobContext) -> dict[str, object]:
    return _run_mirrored_script(
        context,
        "compile_md_to_docx.py",
        _docx_layout_args(context, default_font_size="10.5"),
        progress_seconds=600,
    )


def build_docx_llm(context: JobContext) -> dict[str, object]:
    return _run_mirrored_script(
        context,
        "compile_md_to_docx_llm.py",
        _docx_layout_args(context, default_font_size="10"),
        progress_seconds=600,
    )


def build_pdf(context: JobContext) -> dict[str, object]:
    return _run_mirrored_script(context, "compile_md_to_pdf.py", progress_seconds=900)


DEV_DOC_KINDS = (
    "README",
    "USER",
    "GUIDE",
    "GUI",
    "GUARD",
    "ARCHITECTURE",
    "CHANGELOG",
    "INSTALL",
    "PORTABLE",
    "USAGE",
    "CONFIG",
    "TROUBLESHOOTING",
    "SECURITY",
    "FAQ",
    "API",
    "ROADMAP",
    "MIGRATION",
    "RELEASE",
    "LICENSE",
    "AGENTS",
)
DEFAULT_DEV_DOC_KINDS = (
    "README",
    "USER",
    "GUIDE",
    "GUI",
    "GUARD",
    "ARCHITECTURE",
    "CHANGELOG",
    "INSTALL",
    "PORTABLE",
    "USAGE",
    "CONFIG",
    "TROUBLESHOOTING",
    "SECURITY",
)
DEFAULT_DEV_EXCLUDE_DIRS = (
    "runtime",
    "data",
    "output",
    "logs",
    "release",
    "workspace",
    "work",
    "tools",
    "node_modules",
    "license",
    "licenses",
    "site-packages",
    "ripgrep",
)
DEV_PDF_THEMES = ("dark", "light-sand")
DEV_PDF_OUTPUT_MODES = {"beside", "md-folder-pdf", "docs-pdf", "mirror-output"}


def _normalize_dev_pdf_output_mode(value: object) -> str:
    mode = str(value or "docs-pdf").strip()
    if mode == "dev-output":
        return "md-folder-pdf"
    return mode if mode in DEV_PDF_OUTPUT_MODES else "docs-pdf"


def _dev_pdf_output_dir(project_root: Path, output_mode: str, values: dict[str, object] | None = None) -> Path:
    if output_mode == "docs-pdf":
        return project_root / "docs" / "PDF"
    if output_mode == "mirror-output":
        return _dev_pdf_workbench_path(project_root, values, "output_path", project_root / "output")
    return project_root / "output" / "dev_pdf"


def _list_parameter(context: JobContext, key: str, default: list[str] | tuple[str, ...] = ()) -> list[str]:
    value = context.operation.parameters.get(key, list(default))
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def _values_list(values: dict[str, object] | None, key: str, default: tuple[str, ...]) -> list[str]:
    value = (values or {}).get(key, list(default))
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def _resolve_dev_pdf_path(project_root: Path, raw_path: object, default: Path) -> Path:
    text = str(raw_path or "").strip().strip('"')
    if not text:
        return default.resolve()
    path = Path(os.path.expandvars(text)).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _dev_pdf_workbench_path(
    project_root: Path,
    values: dict[str, object] | None,
    key: str,
    default: Path,
) -> Path:
    return _resolve_dev_pdf_path(project_root, (values or {}).get(key), default)


def _dev_pdf_gui_source(project_root: Path, values: dict[str, object] | None = None) -> tuple[Path, bool]:
    workbench_source = str((values or {}).get("input_path") or "").strip()
    if workbench_source:
        return _resolve_dev_pdf_path(project_root, workbench_source, project_root), True
    data = load_yaml_or_json(project_root / "config" / "gui_settings.yaml")
    gui = data.get("gui", {}) if isinstance(data, dict) else {}
    if not isinstance(gui, dict):
        gui = {}
    source = str(gui.get("source_path", "")).strip()
    if not source:
        return project_root, False
    return _resolve_dev_pdf_path(project_root, source, project_root), True


def _dev_pdf_scan_root(project_root: Path, values: dict[str, object] | None) -> Path:
    mode = str((values or {}).get("dev_pdf_source_mode") or "selected").strip()
    gui_source, gui_source_explicit = _dev_pdf_gui_source(project_root, values)
    raw_path = str((values or {}).get("dev_pdf_source_path") or "").strip()
    if mode == "selected":
        return gui_source if gui_source_explicit else project_root
    if raw_path and raw_path != ".":
        return _resolve_dev_pdf_path(project_root, raw_path, project_root)
    return project_root


def _dev_pdf_source_roots(project_root: Path, values: dict[str, object] | None) -> tuple[list[Path], Path]:
    mode = str((values or {}).get("dev_pdf_source_mode") or "selected").strip()
    output_mode = _normalize_dev_pdf_output_mode((values or {}).get("dev_pdf_output_mode"))
    excludes = {item.lower() for item in _values_list(values, "dev_pdf_exclude_dirs", DEFAULT_DEV_EXCLUDE_DIRS)}
    if mode == "managed":
        roots = [project_root / "input", project_root / "output"]
        existing_roots = [path for path in roots if path.exists()]
        if output_mode == "docs-pdf":
            docs_roots = _dev_pdf_docs_roots(existing_roots, excludes)
            return docs_roots, project_root
        return existing_roots, project_root
    scan_root = _dev_pdf_scan_root(project_root, values)
    if output_mode == "docs-pdf":
        docs_roots = _dev_pdf_docs_roots([scan_root], excludes)
        return docs_roots, scan_root if scan_root.is_dir() else scan_root.parent
    return [scan_root], scan_root if scan_root.is_dir() else scan_root.parent


def _dev_pdf_docs_roots(roots: list[Path], excludes: set[str]) -> list[Path]:
    result: dict[str, Path] = {}
    for root in roots:
        root = root.resolve()
        if root.is_file():
            docs_dir = _dev_pdf_containing_docs_dir(root, root.parent)
            if docs_dir is not None and (docs_dir / "PDF").is_dir():
                result[str(root).lower()] = root
            continue
        if not root.is_dir():
            continue
        if root.name.lower() == "pdf" and root.parent.name.lower() == "docs":
            result[str(root.parent.resolve()).lower()] = root.parent.resolve()
            continue
        if root.name.lower() == "docs" and (root / "PDF").is_dir():
            result[str(root).lower()] = root
            continue
        for dirpath, dirnames, _filenames in os.walk(root):
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if dirname.lower() not in excludes
                and not dirname.startswith(".")
                and dirname != "__pycache__"
            ]
            current = Path(dirpath)
            if current.name.lower() == "pdf" and current.parent.name.lower() == "docs":
                result[str(current.parent.resolve()).lower()] = current.parent.resolve()
                dirnames[:] = []
    return list(result.values())


def _dev_pdf_doc_kind(path: Path) -> str:
    name = path.stem.upper()
    if name.startswith("NOTICE"):
        return "NOTICE"
    for kind in DEV_DOC_KINDS:
        if kind in name:
            return kind
    return "OTHER"


def _dev_pdf_custom_filters(values: dict[str, object] | None) -> list[str]:
    raw = str((values or {}).get("dev_pdf_custom_filters") or "").strip()
    if not raw:
        return []
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _dev_pdf_matches_custom_filter(project_root: Path, path: Path, filters: list[str]) -> bool:
    if not filters:
        return False
    relative = _dev_pdf_relative_label(project_root, path)
    haystack = f"{relative} {path.name} {path.stem}".upper()
    return any(token in haystack for token in filters)


def _dev_pdf_is_markdown(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in {".md", ".markdown"} and path.name != ".gitkeep"


def _iter_dev_markdown(root: Path, excludes: set[str]) -> list[Path]:
    if _dev_pdf_is_markdown(root):
        return [root.resolve()]
    if not root.is_dir():
        return []
    docs: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname.lower() not in excludes
            and not dirname.startswith(".")
            and dirname != "__pycache__"
        ]
        current = Path(dirpath)
        for filename in sorted(filenames, key=str.lower):
            path = current / filename
            if _dev_pdf_is_markdown(path):
                docs.append(path.resolve())
    return docs


def _dev_pdf_relative_label(project_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _dev_pdf_doc_value(project_root: Path, path: Path) -> str:
    return _dev_pdf_relative_label(project_root, path)


def _resolve_dev_pdf_doc_value(project_root: Path, value: str) -> Path:
    path = Path(str(value).strip())
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _dev_pdf_containing_docs_dir(source: Path, base_root: Path | None = None) -> Path | None:
    base_resolved = base_root.resolve() if base_root else None
    for parent in [source.parent, *source.parents]:
        if parent.name.lower() == "docs":
            return parent
        if base_resolved and parent.resolve() == base_resolved:
            break
    return None


def _dev_pdf_output_path(source: Path, theme: str, output_mode: str, out_dir: Path, base_root: Path) -> Path:
    if output_mode == "beside":
        return source.with_name(f"{source.stem}.{theme}.pdf")
    if output_mode == "md-folder-pdf":
        return source.parent / "PDF" / f"{source.stem}.{theme}.pdf"
    if output_mode == "docs-pdf":
        docs_dir = _dev_pdf_containing_docs_dir(source, base_root)
        if docs_dir is None:
            docs_dir = source.parent
        try:
            rel = source.resolve().relative_to(docs_dir.resolve())
        except ValueError:
            rel = Path(source.name)
        return docs_dir / "PDF" / rel.parent / f"{source.stem}.{theme}.pdf"
    else:
        try:
            rel = source.resolve().relative_to(base_root.resolve())
        except ValueError:
            rel = Path(source.name)
    return out_dir / rel.parent / f"{source.stem}.{theme}.pdf"


def _dev_pdf_status(source: Path, output_mode: str, out_dir: Path, base_root: Path) -> dict[str, object]:
    pdfs = [_dev_pdf_output_path(source, theme, output_mode, out_dir, base_root) for theme in DEV_PDF_THEMES]
    existing = [path for path in pdfs if path.exists()]
    missing = len(existing) < len(pdfs)
    try:
        source_mtime = source.stat().st_mtime
    except OSError:
        source_mtime = 0.0
    stale = any(path.exists() and path.stat().st_mtime < source_mtime for path in pdfs)
    return {
        "pdfs": pdfs,
        "pdf_count": len(existing),
        "has_pdf": bool(existing),
        "has_pdf_pair": len(existing) == len(pdfs),
        "missing_pdf": missing,
        "outdated": stale,
        "stale_after_export": missing or stale,
    }


def scan_dev_markdown_docs(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, object]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    mode = str((values or {}).get("dev_pdf_source_mode") or "selected").strip()
    output_mode = _normalize_dev_pdf_output_mode((values or {}).get("dev_pdf_output_mode"))

    selected_kinds = {item.upper() for item in _values_list(values, "dev_pdf_doc_kinds", DEFAULT_DEV_DOC_KINDS)}
    all_markdown = bool(selected_kinds.intersection({"ALL_MD", "ALL", "*"}))
    selected_kinds.difference_update({"ALL_MD", "ALL", "*"})
    custom_filters = _dev_pdf_custom_filters(values)
    excludes = {item.lower() for item in _values_list(values, "dev_pdf_exclude_dirs", DEFAULT_DEV_EXCLUDE_DIRS)}
    if output_mode == "docs-pdf":
        excludes.add("pdf")
    roots, base_root = _dev_pdf_source_roots(project_root, values)
    out_dir = _dev_pdf_output_dir(project_root, output_mode, values)

    docs: dict[str, Path] = {}
    for scan_root in roots:
        for path in _iter_dev_markdown(scan_root, excludes):
            kind = _dev_pdf_doc_kind(path)
            if not all_markdown and (selected_kinds or custom_filters):
                matches_preset = kind in selected_kinds
                matches_custom = _dev_pdf_matches_custom_filter(project_root, path, custom_filters)
                if not matches_preset and not matches_custom:
                    continue
            docs[str(path).lower()] = path

    result: list[dict[str, object]] = []
    for path in sorted(docs.values(), key=lambda item: _dev_pdf_relative_label(project_root, item).lower()):
        status = _dev_pdf_status(path, output_mode, out_dir, base_root)
        if mode == "existing_pdf_pairs" and not bool(status["has_pdf_pair"]):
            continue
        if mode == "outdated_only" and not bool(status["outdated"]):
            continue
        kind = _dev_pdf_doc_kind(path)
        result.append(
            {
                "path": path,
                "value": _dev_pdf_doc_value(project_root, path),
                "label": _dev_pdf_relative_label(project_root, path),
                "kind": kind,
                **status,
            }
        )
    return result


def dev_markdown_doc_options(root: Path | str | None = None, values: dict[str, object] | None = None) -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for item in scan_dev_markdown_docs(root, values)[:500]:
        badges: list[str] = [str(item["kind"])]
        if item.get("outdated"):
            badges.append("stale")
        elif item.get("missing_pdf"):
            badges.append("no PDF")
        elif item.get("has_pdf_pair"):
            badges.append("PDF pair")
        label = f"{item['label']} [{' / '.join(badges)}]"
        options.append(
            {
                "value": str(item["value"]),
                "label": label,
                "label_ru": label,
                "kind": item["kind"],
                "missing_pdf": bool(item["missing_pdf"]),
                "outdated": bool(item["outdated"]),
                "has_pdf": bool(item["has_pdf"]),
                "has_pdf_pair": bool(item["has_pdf_pair"]),
            }
        )
    return options


def _pdf_page_count(path: Path) -> int:
    try:
        import fitz

        with fitz.open(path) as doc:
            return int(doc.page_count)
    except Exception:
        return 0


def _write_dev_pdf_source_list(context: JobContext, docs: list[Path]) -> Path:
    context.report_dir.mkdir(parents=True, exist_ok=True)
    source_list = context.report_dir / "dev_markdown_pdf_sources.json"
    source_list.write_text(
        json.dumps([str(path) for path in docs], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return source_list


def _clear_docs_pdf_outputs(context: JobContext, docs: list[Path], base_root: Path) -> int:
    pdf_dirs: dict[str, Path] = {}
    for doc in docs:
        docs_dir = _dev_pdf_containing_docs_dir(doc, base_root)
        if docs_dir is None:
            continue
        pdf_dir = docs_dir / "PDF"
        if pdf_dir.is_dir():
            pdf_dirs[str(pdf_dir.resolve()).lower()] = pdf_dir.resolve()

    removed = 0
    for pdf_dir in sorted(pdf_dirs.values(), key=lambda item: str(item).lower()):
        context.log(f"[DEV PDF] clear docs\\PDF: {pdf_dir}")
        for child in list(pdf_dir.iterdir()):
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                removed += 1
            except OSError as exc:
                context.log(f"[WARN] Failed to remove {child}: {exc}")
    return removed


def _dev_markdown_pdf_args(context: JobContext, out_dir: Path, source_list: Path, base_root: Path) -> list[str]:
    margin_left = _parameter(context, "dev_pdf_margin_left_mm", "17")
    margin_right = _parameter(context, "dev_pdf_margin_right_mm", "17")
    margin_top = _parameter(context, "dev_pdf_margin_top_mm", "16")
    margin_bottom = _parameter(context, "dev_pdf_margin_bottom_mm", "20")
    page_margin_y = _parameter(context, "dev_pdf_page_margin_y_mm", "4")
    line_height = _parameter(context, "dev_pdf_line_height", "1.5")
    output_mode = _normalize_dev_pdf_output_mode(_parameter(context, "dev_pdf_output_mode", "docs-pdf"))

    context.log(
        "DEV Markdown PDF layout: "
        f"L/R/T/B={margin_left}/{margin_right}/{margin_top}/{margin_bottom} mm, "
        f"page Y={page_margin_y} mm, "
        f"line-height={line_height}, "
        f"output-mode={output_mode}"
    )
    return [
        "--output-mode",
        output_mode,
        "--out-dir",
        str(out_dir),
        "--source-list",
        str(source_list),
        "--base-root",
        str(base_root),
        "--margin-left-mm",
        margin_left,
        "--margin-right-mm",
        margin_right,
        "--margin-top-mm",
        margin_top,
        "--margin-bottom-mm",
        margin_bottom,
        "--page-margin-y-mm",
        page_margin_y,
        "--line-height",
        line_height,
    ]


def build_dev_markdown_pdf(context: JobContext) -> dict[str, object]:
    return build_dev_markdown_pdf_selected(context)


def build_dev_markdown_pdf_selected(context: JobContext) -> dict[str, object]:
    values = dict(context.operation.parameters)
    docs_info = scan_dev_markdown_docs(context.paths.root, values)
    selected_values = set(_list_parameter(context, "dev_pdf_selected_docs"))
    if selected_values:
        docs = [
            _resolve_dev_pdf_doc_value(context.paths.root, str(item["value"]))
            for item in docs_info
            if str(item["value"]) in selected_values
        ]
    else:
        docs = [Path(item["path"]) for item in docs_info]

    if not docs:
        context.log("[INFO] No Markdown documents matched DEV PDF filters.")
        context.progress(1.0)
        return {"exit_code": 0, "md": 0, "pdf": 0, "pages": 0, "errors": 0, "stale_after_export": 0}

    roots, base_root = _dev_pdf_source_roots(context.paths.root, values)
    output_mode = _normalize_dev_pdf_output_mode(_parameter(context, "dev_pdf_output_mode", "docs-pdf"))
    out_dir = _dev_pdf_output_dir(context.paths.root, output_mode, values)
    if output_mode == "docs-pdf":
        removed = _clear_docs_pdf_outputs(context, docs, base_root)
        context.log(f"[DEV PDF] cleared docs\\PDF items: {removed}")
    source_list = _write_dev_pdf_source_list(context, docs)

    context.log("[DEV PDF] source mode: " + _parameter(context, "dev_pdf_source_mode", "selected"))
    context.log("[DEV PDF] roots: " + ", ".join(str(path) for path in roots))
    context.log(f"[DEV PDF] matched Markdown: {len(docs_info)}")
    context.log(f"[DEV PDF] selected Markdown: {len(docs)}")

    result = _run_script(
        context,
        "dev_markdown_pdf_engine.py",
        _dev_markdown_pdf_args(context, out_dir, source_list, base_root),
        progress_seconds=900,
    )

    pdf_paths: list[Path] = []
    stale_after_export = 0
    for doc in docs:
        status = _dev_pdf_status(doc, output_mode, out_dir, base_root)
        pdf_paths.extend(path for path in status["pdfs"] if path.exists())
        if status["stale_after_export"]:
            stale_after_export += 1

    pages = sum(_pdf_page_count(path) for path in pdf_paths)
    errors = 0 if result.exit_code == 0 else 1
    context.log("")
    context.log("[DEV PDF REPORT]")
    context.log(f"MD: {len(docs)}")
    context.log(f"PDF: {len(pdf_paths)}")
    context.log(f"Pages: {pages}")
    context.log(f"Errors: {errors}")
    context.log(f"Stale after export: {stale_after_export}")
    return {
        "exit_code": result.exit_code,
        "md": len(docs),
        "pdf": len(pdf_paths),
        "pages": pages,
        "errors": errors,
        "stale_after_export": stale_after_export,
        "source_list": str(source_list),
        "output_mode": output_mode,
    }


def build_pptx(context: JobContext) -> dict[str, object]:
    return _run_mirrored_script(context, "compile_md_to_pptx.py", progress_seconds=600)


def build_xlsx(context: JobContext) -> dict[str, object]:
    return _run_mirrored_script(context, "compile_md_to_xlsx.py", progress_seconds=600)


def _markdown_files(root: Path) -> list[Path]:
    results: list[Path] = []
    for folder_name in ("input", "output"):
        folder = root / folder_name
        if not folder.exists():
            continue
        for path in folder.rglob("*.md"):
            if path.is_file() and path.name != ".gitkeep":
                results.append(path)
    return sorted(results, key=lambda item: str(item.relative_to(root)).lower())


def markdown_file_options(root: Path | str | None = None) -> list[dict[str, str]]:
    project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    options = [
        {
            "value": "",
            "label": "All Markdown files in input/output",
            "label_ru": "Все Markdown-файлы в input/output",
        }
    ]
    for path in _markdown_files(project_root)[:300]:
        relative = path.relative_to(project_root).as_posix()
        options.append({"value": relative, "label": relative, "label_ru": relative})
    return options


def inspect_tables(context: JobContext) -> dict[str, object]:
    mirror = _prepare_mirror_context(context)
    selected = _parameter(context, "markdown_file", "")
    if selected:
        candidates = [context.paths.root / selected]
    else:
        candidates = _markdown_files(context.paths.root)

    if not candidates:
        context.log("No Markdown files found in input/output.")
        context.progress(1.0)
        _sync_destination(context, mirror)
        _write_mirror_report(context, mirror)
        return {"files": 0, "source": str(mirror.source), "destination": str(mirror.destination)}

    processed = 0
    total = len(candidates)
    for index, path in enumerate(candidates, start=1):
        if context.cancelled():
            raise RuntimeError("Operation cancelled by user.")
        if not path.exists():
            context.log(f"[SKIP] Markdown file was not found: {path}")
            continue
        context.log("")
        context.log(f"[INSPECT] {path.relative_to(context.paths.root)}")
        _run_script(context, "inspect_md_tables.py", ["--input", str(path)], progress_seconds=60)
        processed += 1
        context.progress(index / max(1, total))

    _sync_destination(context, mirror)
    _write_mirror_report(context, mirror)
    return {"files": processed, "source": str(mirror.source), "destination": str(mirror.destination)}


def copy_output_markdown_to_input(context: JobContext) -> dict[str, object]:
    output_dir = context.paths.output
    input_dir = context.paths.input
    input_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(path for path in output_dir.rglob("*.md") if path.is_file() and path.name != ".gitkeep")
    if not files:
        context.log("No Markdown files found in output.")
        context.progress(1.0)
        return {"copied": 0}

    copied = 0
    for index, source in enumerate(files, start=1):
        if context.cancelled():
            raise RuntimeError("Operation cancelled by user.")
        relative = source.relative_to(output_dir)
        target = input_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
        context.log(f"[COPY] output/{relative.as_posix()} -> input/{relative.as_posix()}")
        context.progress(index / max(1, len(files)))

    return {"copied": copied}


def _clean_managed_folder(context: JobContext, folder: Path, label: str) -> dict[str, object]:
    root = context.paths.root.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    resolved = folder.resolve()
    if os.path.commonpath([str(root), str(resolved)]) != str(root):
        raise RuntimeError(f"{label} is outside project root. Cleanup blocked.")
    if folder.is_symlink():
        raise RuntimeError(f"{label} is a symlink. Cleanup blocked.")

    removed = 0
    skipped: list[str] = []
    for item in folder.iterdir():
        if item.name == ".gitkeep":
            continue
        try:
            if item.is_symlink() or item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
            removed += 1
            context.log(f"[REMOVE] {label}/{item.name}")
        except OSError as exc:
            skipped.append(f"{item.name}: {exc}")

    return {"removed": removed, "skipped": skipped}


def cleanup_input_output(context: JobContext) -> dict[str, object]:
    input_result = _clean_managed_folder(context, context.paths.input, "input")
    context.progress(0.5)
    output_result = _clean_managed_folder(context, context.paths.output, "output")
    context.progress(1.0)
    return {"input": input_result, "output": output_result}


def _clean_document_model_folder(context: JobContext, folder: Path, label: str) -> dict[str, object]:
    """Remove internal DocumentModel packages without deleting office deliverables."""
    project_root = context.paths.root.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    resolved_folder = folder.resolve()
    if os.path.commonpath([str(project_root), str(resolved_folder)]) != str(project_root):
        raise RuntimeError(f"{label} is outside project root. DocumentModel cleanup blocked.")
    if folder.is_symlink():
        raise RuntimeError(f"{label} is a symlink. DocumentModel cleanup blocked.")

    package_dirs = sorted(
        (item for item in folder.rglob("*.document") if item.is_dir() or item.is_symlink()),
        key=lambda item: len(item.parts),
        reverse=True,
    )
    package_roots = {item.absolute() for item in package_dirs}
    machine_files: list[Path] = []
    for pattern in ("*.document.json", "*.verification.json"):
        for item in folder.rglob(pattern):
            if not (item.is_file() or item.is_symlink()):
                continue
            if any(parent.absolute() in package_roots for parent in item.parents):
                continue
            machine_files.append(item)

    removed_packages = 0
    removed_files = 0
    skipped: list[str] = []
    for item in [*package_dirs, *sorted(set(machine_files), key=lambda path: str(path).lower())]:
        try:
            parent = item.parent.resolve()
            if os.path.commonpath([str(resolved_folder), str(parent)]) != str(resolved_folder):
                raise RuntimeError("resolved parent is outside the managed folder")
            relative = item.relative_to(folder)
            if item.is_symlink() or item.is_file():
                item.unlink()
                removed_files += 1
            elif item.is_dir():
                shutil.rmtree(item)
                removed_packages += 1
            context.log(f"[DOCUMENT MODEL REMOVE] {label}/{relative.as_posix()}")
        except (OSError, RuntimeError, ValueError) as exc:
            skipped.append(f"{item}: {exc}")

    return {
        "packages": removed_packages,
        "machine_files": removed_files,
        "skipped": skipped,
    }


def cleanup_document_model_artifacts(context: JobContext) -> dict[str, object]:
    """Delete regenerable DocumentModel artifacts, preserving DOCX/XLSX/MD/PDF outputs."""
    roots = (
        (context.paths.output, "output"),
        (context.paths.report, "report"),
        (context.paths.workspace, "workspace"),
    )
    results: dict[str, object] = {}
    for index, (folder, label) in enumerate(roots, start=1):
        results[label] = _clean_document_model_folder(context, folder, label)
        context.progress(index / len(roots))
    return results
