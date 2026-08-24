# pipeline_controller.py
# Orchestration glue between the GUI and the bricks. OCR cache is shared by content.
# Flow per page:  rasterize -> clean (service or local) -> engine.recognize -> L2 cache.
# No globals; all collaborators (cache, sr, engine, profiles) are injected or built
# from explicit paths. The GUI calls run_job(); it does not touch internals.
# EN comments only. UTF-8 without BOM.

from __future__ import annotations

import base64
import difflib
import html
import hashlib
import json
import re
import tempfile
from collections import Counter
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import cleanconfig, preprocess
from .cache import Cache
from .engines import registry
from .engines.base import OcrResult
from .engines.tesseract import TesseractAdapter

# Engines that load a heavy framework once -> host in the warm layout service.
HEAVY_ENGINES = {"surya"}
VISION_ENGINES = {"xai", "gemini", "chatgpt"}


@dataclass
class JobRequest:
    source_path: str
    engine: str                      # e.g. "tesseract"
    gui_overrides: dict[str, Any]    # cleaning knobs incl. {"enabled": False} bypass
    engine_params: dict[str, Any]    # e.g. {"lang": "rus", "psm": 6}
    output: str = "text"             # "text" (words) | "structured" (layout regions)
    asset_dir: str = ""               # optional DocumentModel pages directory


class PipelineController:
    def __init__(self, project_root: str | Path,
                 sr=None, tesseract_exe: str = "tesseract",
                 cache_max_bytes: int = 20 * 1024 ** 3,
                 layout_base_url: str | None = None) -> None:
        self.root = Path(project_root)
        self.brick_root = Path(__file__).resolve().parent
        self.profiles = cleanconfig.load_profiles(self.brick_root / "preprocess.profiles.json")
        self.engines = registry.load_engines(self.brick_root / "ocr.engines.json")
        self.sr = sr  # SRClient or None (None only valid if sr_scale==0 everywhere)
        self.tesseract_exe = tesseract_exe
        self.cache_max_bytes = cache_max_bytes
        self.layout_base_url = layout_base_url  # warm layout service for heavy engines

    def _adapter_for(self, engine: str):
        """Heavy engines go through the warm service (model loaded once); light
        engines are built in-process."""
        if engine in HEAVY_ENGINES and self.layout_base_url:
            from .engines.service_client import HeavyEngineClient
            return HeavyEngineClient(self.layout_base_url, engine)
        return registry.build_adapter(engine, self.engines, self.root, self.tesseract_exe)

    def run_job(self, req: JobRequest, job_id: str) -> list[dict]:
        """Process one source. Returns one result dict per page.

        text mode       -> OcrResult.to_dict() per page
        structured mode -> LayoutResult.to_dict() per page (requires a layout engine)
        """
        # L1/L2 keys already include page bytes, preprocessing, engine and all
        # engine parameters. A stable root makes interrupted jobs resumable.
        cache = Cache(self.root / "cache" / "ocr_pages", max_bytes=self.cache_max_bytes)
        profile = registry.engine_profile(req.engine, self.engines)
        adapter = self._adapter_for(req.engine)

        structured = req.output == "structured"
        if structured and not registry.provides_layout(adapter):
            raise ValueError(
                f"engine '{req.engine}' cannot produce structured output "
                "(no analyze_layout); use a layout engine (surya)")

        pages = preprocess.rasterize(req.source_path)
        results: list[dict] = []
        for idx, page_png in enumerate(pages):
            cfg = cleanconfig.resolve(
                self.profiles, target_engine=profile,
                gui_overrides=req.gui_overrides,
                original_name=req.source_path,
            )
            clean_png = preprocess.clean_page(page_png, cfg, cache=cache, sr=self.sr)
            assets = _write_page_assets(req.asset_dir, idx, page_png, clean_png)

            # cache key distinguishes text vs structured and the params
            tag = "layout" if structured else "ocr"
            eparams_canon = json.dumps(req.engine_params, sort_keys=True, separators=(",", ":"))
            cache_engine = f"{req.engine}:{tag}"
            hit = cache.l2_get(clean_png, cache_engine, eparams_canon)
            if hit is not None:
                if req.engine == "mistral" and not structured:
                    hit = _normalize_mistral_cached_result(hit, req.engine_params)
                    cache.l2_put(clean_png, cache_engine, eparams_canon, hit)
                if assets:
                    hit["assets"] = assets
                results.append(hit)
                continue

            d = self._process(adapter, clean_png, req, idx, structured)
            d["page"] = idx
            cache.l2_put(clean_png, cache_engine, eparams_canon, d)
            if assets:
                d["assets"] = assets
            results.append(d)
        return results


    def _process(self, adapter, clean_png: bytes, req: JobRequest, page: int,
                 structured: bool) -> dict:
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "clean.png"
            fp.write_bytes(clean_png)
            if structured:
                if req.engine == "mistral":
                    return adapter.analyze_layout(str(fp), page, req.engine_params).to_dict()
                return adapter.analyze_layout(str(fp), page).to_dict()
            params = dict(req.engine_params)
            second_pass = self._tesseract_2pass(str(fp), req, params)
            if second_pass.get("ok") and req.engine in VISION_ENGINES and _bool_param(params.get("tesseract_2pass_hint"), True):
                params["prompt"] = _prompt_with_tesseract_hint(
                    str(params.get("prompt") or ""),
                    str(second_pass.get("text") or ""),
                    int(params.get("tesseract_2pass_prompt_chars") or 6000),
                )
            result = adapter.recognize(str(fp), params).to_dict()
            if req.engine == "mistral" and getattr(adapter, "last_page", None):
                page_meta = dict(adapter.last_page)
                result["mistral_page"] = page_meta
                result["usage_info"] = dict(getattr(adapter, "last_usage", {}) or {})
            if req.engine == "xai":
                result = self._russian_review(adapter, str(fp), params, result)
            if second_pass:
                result["tesseract_2pass"] = second_pass
                if (
                    req.engine == "mistral"
                    and second_pass.get("ok")
                    and _bool_param(params.get("tesseract_verify"), True)
                ):
                    result["verification"] = build_ocr_verification(
                        str(result.get("text") or ""),
                        str(second_pass.get("text") or ""),
                        primary_engine="mistral",
                        threshold=float(params.get("tesseract_verify_threshold") or 0.90),
                    )
            if req.engine == "mistral" and str(params.get("secondary_pass") or "") in {"yandex", "yandex_tesseract"}:
                result = self._yandex_2pass(str(fp), params, result)
            return result

    def _yandex_2pass(
        self,
        clean_png_path: str,
        params: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        from .ocr_fusion import fuse_mistral_yandex, needs_yandex_review

        scope = str(params.get("yandex_2pass_scope") or "suspicious")
        should_run, reason = needs_yandex_review(result, scope)
        if not should_run:
            result["yandex_2pass"] = {
                "ok": True,
                "skipped": True,
                "scope": scope,
                "reason": reason,
            }
            return result
        try:
            adapter = registry.build_adapter("yandex", self.engines, self.root, self.tesseract_exe)
            languages_value = params.get("yandex_2pass_languages") or ["ru", "en"]
            languages = (
                [item.strip() for item in str(languages_value).split(",") if item.strip()]
                if isinstance(languages_value, str)
                else [str(item).strip() for item in languages_value if str(item).strip()]
            )
            yandex_result = adapter.recognize(clean_png_path, {
                "mode": "sync",
                "model": str(params.get("yandex_2pass_model") or "page"),
                "languageCodes": languages or ["ru", "en"],
            }).to_dict()
        except Exception as exc:
            result["yandex_2pass"] = {
                "ok": False,
                "skipped": False,
                "scope": scope,
                "reason": reason,
                "error": f"{exc.__class__.__name__}: {exc}",
            }
            return result
        yandex_result.update({"ok": True, "skipped": False, "scope": scope, "reason": reason})
        result["yandex_2pass"] = yandex_result
        result["yandex_verification"] = build_ocr_verification(
            str(result.get("text") or ""),
            str(yandex_result.get("text") or ""),
            primary_engine="mistral",
            secondary_engine="yandex",
            threshold=float(params.get("yandex_verify_threshold") or 0.90),
        )
        if _bool_param(params.get("yandex_fusion"), True):
            result["fusion"] = fuse_mistral_yandex(result, yandex_result, clean_png_path)
        return result

    def _russian_review(self, adapter, clean_png_path: str, params: dict[str, Any], result: dict) -> dict:
        enabled = _bool_param(params.get("russian_review_enabled"), False)
        draft = str(result.get("text") or "").strip()
        flags = _russian_quality_flags(draft)
        result["russian_review"] = {"enabled": enabled, "flags": flags, "applied": False}
        if not enabled or not flags or not draft:
            return result

        review_params = dict(params)
        review_params["model"] = str(params.get("russian_review_model") or params.get("model") or "grok-4.3")
        review_params["prompt"] = _russian_review_prompt(
            str(params.get("russian_review_prompt") or ""), draft, flags
        )
        for key in tuple(review_params):
            if key.startswith("tesseract_2pass") or key.startswith("russian_review"):
                review_params.pop(key, None)
        try:
            reviewed = adapter.recognize(clean_png_path, review_params).text.strip()
        except Exception as exc:
            result["russian_review"]["error"] = f"{exc.__class__.__name__}: {exc}"
            return result
        if not reviewed:
            result["russian_review"]["error"] = "Review returned empty text"
            return result

        change_ratio = 1.0 - difflib.SequenceMatcher(None, draft, reviewed).ratio()
        severe_encoding = any(flag in {"replacement_character", "probable_mojibake"} for flag in flags)
        if change_ratio > 0.45 and not severe_encoding:
            result["russian_review"].update({
                "error": "Review rejected: correction ratio exceeds 45%",
                "change_ratio": round(change_ratio, 4),
            })
            return result
        result["raw_text"] = draft
        result["text"] = reviewed
        result["russian_review"].update({"applied": True, "change_ratio": round(change_ratio, 4)})
        return result

    def _tesseract_2pass(self, clean_png_path: str, req: JobRequest, params: dict[str, Any]) -> dict[str, Any]:
        if req.engine == "tesseract" or not _bool_param(params.get("tesseract_2pass"), False):
            return {}
        adapter = TesseractAdapter(self.tesseract_exe)
        try:
            result = adapter.recognize(
                clean_png_path,
                {
                    "lang": str(params.get("tesseract_2pass_lang") or "rus+eng"),
                    "psm": int(params.get("tesseract_2pass_psm") or 6),
                },
            )
        except Exception as exc:
            return {
                "ok": False,
                "engine": "tesseract",
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        return {
            "ok": True,
            "engine": "tesseract",
            "lang": str(params.get("tesseract_2pass_lang") or "rus+eng"),
            "psm": int(params.get("tesseract_2pass_psm") or 6),
            "text": result.text,
            "words": [asdict(word) for word in result.words],
            "words_count": len(result.words),
        }


def _write_page_assets(asset_dir: str, page: int, source_png: bytes, clean_png: bytes) -> dict[str, Any]:
    if not str(asset_dir or "").strip():
        return {}
    directory = Path(asset_dir)
    directory.mkdir(parents=True, exist_ok=True)
    source_name = f"page-{page + 1:04d}.source.png"
    clean_name = f"page-{page + 1:04d}.ocr.png"
    (directory / source_name).write_bytes(source_png)
    (directory / clean_name).write_bytes(clean_png)
    return {
        "source_page_image": f"pages/{source_name}",
        "ocr_page_image": f"pages/{clean_name}",
        "source_page_sha256": hashlib.sha256(source_png).hexdigest(),
        "ocr_page_sha256": hashlib.sha256(clean_png).hexdigest(),
        "raster_dpi": 300,
    }


def _bool_param(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _normalize_mistral_cached_result(
    result: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upgrade pre-fix cache entries without another paid OCR request."""
    page = result.get("mistral_page")
    if not isinstance(page, dict):
        return result
    from .engines.mistral import _page_markdown

    normalized = _page_markdown(page)
    if normalized:
        result["text"] = normalized
    second_pass = result.get("tesseract_2pass")
    verification_params = dict(params or {})
    if (
        isinstance(second_pass, dict)
        and second_pass.get("ok")
        and _bool_param(verification_params.get("tesseract_verify"), True)
    ):
        result["verification"] = build_ocr_verification(
            str(result.get("text") or ""),
            str(second_pass.get("text") or ""),
            primary_engine="mistral",
            threshold=float(verification_params.get("tesseract_verify_threshold") or 0.90),
        )
    return result


_NUMERIC_TOKEN_RE = re.compile(
    r"(?<![\w])(?:"
    r"\d{1,4}(?:[./-]\d{1,2}){1,2}"
    r"|\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?"
    r"|\d+[.,]\d+"
    r"|\d+"
    r")(?![\w])"
)
_WORD_TOKEN_RE = re.compile(r"(?iu)[a-zа-яё]{2,}")


def _verification_visible_text(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(str(text or "")))


def _canonical_numeric_token(token: str) -> str:
    value = token.replace("\u00a0", " ").strip()
    if re.fullmatch(r"\d{1,4}(?:[./-]\d{1,2}){1,2}", value):
        return "-".join(re.findall(r"\d+", value))
    return value.replace(" ", "").replace(".", ",")


def _verification_numeric_tokens(text: str) -> list[str]:
    visible = _verification_visible_text(text)
    return [_canonical_numeric_token(match.group(0)) for match in _NUMERIC_TOKEN_RE.finditer(visible)]


def _counter_items(counter: Counter[str], limit: int = 100) -> list[dict[str, object]]:
    return [
        {"token": token, "count": count}
        for token, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def build_ocr_verification(
    primary_text: str,
    tesseract_text: str,
    *,
    primary_engine: str,
    secondary_engine: str = "tesseract",
    threshold: float = 0.90,
) -> dict[str, Any]:
    """Compare exact-value tokens and vocabulary without claiming OCR certainty."""
    threshold = max(0.0, min(1.0, float(threshold)))
    primary_numbers = Counter(_verification_numeric_tokens(primary_text))
    tesseract_numbers = Counter(_verification_numeric_tokens(tesseract_text))
    matched_numbers = primary_numbers & tesseract_numbers
    missing_in_tesseract = primary_numbers - tesseract_numbers
    extra_in_tesseract = tesseract_numbers - primary_numbers
    primary_total = sum(primary_numbers.values())
    tesseract_total = sum(tesseract_numbers.values())
    matched_total = sum(matched_numbers.values())
    numeric_denominator = max(primary_total, tesseract_total)
    numeric_agreement = matched_total / numeric_denominator if numeric_denominator else 0.0

    primary_words = set(_WORD_TOKEN_RE.findall(_verification_visible_text(primary_text).lower()))
    tesseract_words = set(_WORD_TOKEN_RE.findall(_verification_visible_text(tesseract_text).lower()))
    word_union = primary_words | tesseract_words
    text_jaccard = len(primary_words & tesseract_words) / len(word_union) if word_union else 0.0

    if not numeric_denominator:
        status = "insufficient"
    elif numeric_agreement >= threshold:
        status = "pass"
    else:
        status = "review"
    payload = {
        "version": 1,
        "primary_engine": primary_engine,
        "secondary_engine": secondary_engine,
        "status": status,
        "verified": status == "pass",
        "threshold": round(threshold, 4),
        "numeric_agreement": round(numeric_agreement, 4),
        "text_jaccard": round(text_jaccard, 4),
        "primary_numeric_count": primary_total,
        "secondary_numeric_count": tesseract_total,
        "tesseract_numeric_count": tesseract_total,
        "matched_numeric_count": matched_total,
        "missing_in_tesseract": _counter_items(missing_in_tesseract),
        "extra_in_tesseract": _counter_items(extra_in_tesseract),
        "missing_in_secondary": _counter_items(missing_in_tesseract),
        "extra_in_secondary": _counter_items(extra_in_tesseract),
        "note": "Pass means cross-engine agreement at the configured threshold, not ground-truth accuracy.",
    }
    return payload


def _prompt_with_tesseract_hint(prompt: str, tesseract_text: str, max_chars: int) -> str:
    hint = str(tesseract_text or "").strip()
    if not hint:
        return prompt
    max_chars = max(1000, min(20000, int(max_chars or 6000)))
    if len(hint) > max_chars:
        hint = hint[:max_chars].rstrip() + "\n[truncated]"
    return (
        f"{prompt.strip()}\n\n"
        "Local Tesseract OCR hypothesis for this same cleaned page follows. "
        "Treat it as a fallible hypothesis, not as truth. Use it to preserve "
        "digits, dates, names, and line order when the image agrees; correct it "
        "from the image when it is wrong. Do not mention this hint in the output.\n"
        "LOCAL_TESSERACT_OCR_HYPOTHESIS:\n"
        f"{hint}"
    ).strip()


def _russian_quality_flags(text: str) -> list[str]:
    flags: list[str] = []
    if "\ufffd" in text:
        flags.append("replacement_character")
    mojibake_markers = ("Рџ", "Рё", "Рµ", "Р°", "РЅ", "С‚", "СЂ", "СЏ")
    if sum(text.count(marker) for marker in mojibake_markers) >= 3:
        flags.append("probable_mojibake")
    mixed = re.findall(r"(?iu)\b(?=[\w-]*[а-яё])(?=[\w-]*[a-z])[\w-]+\b", text)
    if mixed:
        flags.append("mixed_latin_cyrillic")
    if text and len(text) < 20:
        flags.append("suspiciously_short")
    return flags


def _russian_review_prompt(base_prompt: str, draft: str, flags: list[str]) -> str:
    instruction = base_prompt.strip() or (
        "Проверь черновик OCR по исходному изображению. Исправляй только явно "
        "видимые ошибки распознавания русского текста, цифр, дат, ФИО и географии. "
        "Не нормализуй редкие фамилии и топонимы, не дополняй невидимый текст. "
        "Сохрани Markdown-структуру и верни только исправленный документ."
    )
    return (
        f"{instruction}\n\nПричины проверки: {', '.join(flags)}.\n"
        "ЧЕРНОВИК OCR:\n"
        f"{draft}"
    )
